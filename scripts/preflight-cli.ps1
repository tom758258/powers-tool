param(
    [string]$Target = "all",
    [ValidateSet("smoke", "deep", "full")][string]$Suite = "full",
    [string]$OutputRoot = ".tmp_tests\cli_preflight",
    [switch]$DebugArtifacts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
. (Join-Path $PSScriptRoot "_validation_helpers.ps1")

function Get-PreflightRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $prefix = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if ($full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($prefix.Length)
    }
    return "<redacted-path>"
}

function Protect-PreflightText {
    param([AllowEmptyString()][string]$Text)
    if ($null -eq $Text) { return "" }
    $result = $Text.Replace($RepoRoot, "<repo>")
    $result = $result -replace '(?i)\b(?:TCPIP\d*::[^\s"''<>]+|USB\d*::[^\s"''<>]+::INSTR|ASRL\d+::[^\s"''<>]+)\b', '<redacted-resource>'
    $result = $result -replace '(?i)\b(?:10|127|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<redacted-ip>'
    $result = $result -replace '(?i)[a-z]:\\(?:Users|Documents and Settings)\\[^\s"''<>]+', '<redacted-path>'
    return $result
}

function Get-ProjectMetadata {
    $content = Get-Content -LiteralPath (Join-Path $RepoRoot "pyproject.toml") -Raw
    $nameMatch = [regex]::Match($content, '(?m)^name\s*=\s*"([^"]+)"')
    $versionMatch = [regex]::Match($content, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $nameMatch.Success -or -not $versionMatch.Success) { throw "Could not resolve project metadata." }
    return [pscustomobject]@{ name = $nameMatch.Groups[1].Value; version = $versionMatch.Groups[1].Value }
}

function Get-GitHead {
    $head = & git -C $RepoRoot rev-parse HEAD 2>$null
    if ($LASTEXITCODE -eq 0) { return $head.Trim() }
    return $null
}

function Get-NestedValue {
    param([Parameter(Mandatory = $true)]$Object, [Parameter(Mandatory = $true)][string]$Path)
    $value = $Object
    foreach ($part in $Path.Split('.')) {
        $property = $value.PSObject.Properties[$part]
        if ($null -eq $property) { throw "Missing JSON field '$Path'." }
        $value = $property.Value
    }
    return ,$value
}

function Invoke-PreflightCase {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][string]$PrivateDirectory,
        [Parameter(Mandatory = $true)][string]$ShareableDirectory
    )
    $name = $Case.name -replace '[^A-Za-z0-9_.-]', '_'
    $jsonPath = Join-Path $PrivateDirectory ($name + ".json")
    $stdoutPath = Join-Path $PrivateDirectory ($name + ".stdout.txt")
    $stderrPath = Join-Path $PrivateDirectory ($name + ".stderr.txt")
    $arguments = @($Case.arguments)
    if ($DebugArtifacts) { $arguments += @("--save-json", $jsonPath) }
    $started = Get-Date
    $failures = New-Object System.Collections.Generic.List[string]
    $checks = New-Object System.Collections.Generic.List[object]
    $payload = $null
    $exitCode = -1
    $capture = $null
    try {
        $capture = Invoke-CapturedValidationCommand -FilePath $script:CliExecutable -Arguments $arguments -WorkingDirectory $RepoRoot -PythonPath (Join-Path $RepoRoot "src") -CaptureInMemory:(-not $DebugArtifacts) -StdOutPath $stdoutPath -StdErrPath $stderrPath
        $exitCode = $capture.exit_code
        $jsonText = if ($DebugArtifacts) {
            if (-not (Test-Path -LiteralPath $jsonPath)) { throw "CLI JSON output missing." }
            Get-Content -LiteralPath $jsonPath -Raw
        } else { $capture.stdout_text }
        $payload = $jsonText | ConvertFrom-Json -ErrorAction Stop
    }
    catch { $failures.Add("CLI execution or JSON parsing failed.") }
    if ($exitCode -ne 0) { $failures.Add("Exit code was $exitCode.") }
    if ($null -ne $payload) {
        $checks.Add([pscustomobject]@{ name="ok"; expected=$true; observed=$payload.ok; passed=($payload.ok -eq $true) })
        $checks.Add([pscustomobject]@{ name="command"; expected=$Case.command; observed=$payload.command.name; passed=($payload.command.name -eq $Case.command) })
        $checks.Add([pscustomobject]@{ name="hardware_touched"; expected=$false; observed=$payload.execution.hardware_touched; passed=($payload.execution.hardware_touched -eq $false) })
        if ($Case.mode -eq "dry-run") {
            $checks.Add([pscustomobject]@{ name="dry_run"; expected=$true; observed=$payload.execution.dry_run; passed=($payload.execution.dry_run -eq $true) })
        } elseif ($Case.mode -eq "simulate") {
            $checks.Add([pscustomobject]@{ name="mode"; expected="simulate"; observed=$payload.execution.mode; passed=($payload.execution.mode -eq "simulate") })
        }
        if (-not [string]::IsNullOrWhiteSpace($Case.expected_path)) {
            try {
                $actual = Get-NestedValue -Object $payload -Path $Case.expected_path
                $checks.Add([pscustomobject]@{ name=$Case.expected_path; expected=$Case.expected_value; observed=$actual; passed=([string]$actual -eq [string]$Case.expected_value) })
            } catch { $failures.Add("Required expected field was missing or invalid.") }
        }
        foreach ($expectation in $Case.expected_values.GetEnumerator()) {
            try {
                $actual = Get-NestedValue -Object $payload -Path $expectation.Key
                $actualJson = ConvertTo-Json -InputObject $actual -Compress -Depth 10
                $expectedJson = ConvertTo-Json -InputObject $expectation.Value -Compress -Depth 10
                $checks.Add([pscustomobject]@{ name=$expectation.Key; expected=$expectation.Value; observed=$actual; passed=($actualJson -ceq $expectedJson) })
            } catch { $failures.Add("Required expected field was missing or invalid.") }
        }
        foreach ($check in $checks) {
            if (-not $check.passed) { $failures.Add("Assertion '$($check.name)' did not match its expected value.") }
        }
    }
    $shareableJson = $null
    $shareableOut = $null
    $shareableErr = $null
    if ($DebugArtifacts) {
        $shareableJson = Join-Path $ShareableDirectory ($name + ".json")
        $shareableOut = Join-Path $ShareableDirectory ($name + ".stdout.txt")
        $shareableErr = Join-Path $ShareableDirectory ($name + ".stderr.txt")
        if ($null -ne $payload) {
            Write-Utf8NoBomText -LiteralPath $shareableJson -Text (Protect-PreflightText -Text ($payload | ConvertTo-Json -Depth 30))
        } else {
            Write-Utf8NoBomText -LiteralPath $shareableJson -Text '{"artifact_available":false,"parse_error":"Command JSON unavailable"}'
        }
        $outText = if ($null -ne $capture) { [string]$capture.stdout_text } else { "" }
        $errText = if ($null -ne $capture) { [string]$capture.stderr_text } else { "" }
        Write-Utf8NoBomText -LiteralPath $shareableOut -Text (Protect-PreflightText -Text $outText)
        Write-Utf8NoBomText -LiteralPath $shareableErr -Text (Protect-PreflightText -Text $errText)
    }
    return [pscustomobject]@{
        name=$Case.name; suite=$Case.suite; category=$Case.category; command=$Case.command
        arguments=@($Case.arguments | ForEach-Object { Protect-PreflightText -Text $_ })
        exit_code=$exitCode; duration_ms=[math]::Round(((Get-Date)-$started).TotalMilliseconds,3)
        ok=if ($null -ne $payload) { $payload.ok } else { $null }
        mode=if ($null -ne $payload) { $payload.execution.mode } else { $null }
        dry_run=if ($null -ne $payload) { $payload.execution.dry_run } else { $null }
        hardware_touched=if ($null -ne $payload) { $payload.execution.hardware_touched } else { $null }
        passed=($failures.Count -eq 0); failures=@($failures.ToArray()); assertions=@($checks.ToArray())
        json_path=if ($DebugArtifacts) { Get-PreflightRelativePath -Path $shareableJson } else { $null }
        stdout_path=if ($DebugArtifacts) { Get-PreflightRelativePath -Path $shareableOut } else { $null }
        stderr_path=if ($DebugArtifacts) { Get-PreflightRelativePath -Path $shareableErr } else { $null }
    }
}

$outputBase = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputRoot))
}
$temporaryBase = [System.IO.Path]::GetFullPath($TmpRoot).TrimEnd('\','/')
if (-not $outputBase.StartsWith(($temporaryBase + [System.IO.Path]::DirectorySeparatorChar), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Preflight output must stay under .tmp_tests."
}
$runRoot = Join-Path $outputBase ("run_" + (Get-Date -Format "yyyyMMdd_HHmmss_fff") + "_" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$script:CliExecutable = Join-Path $RepoRoot ".venv\Scripts\powers-tool.exe"
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $script:CliExecutable)) {
    throw "Repository .venv CLI is required."
}
$metadata = Get-ProjectMetadata
if ($metadata.name -ne "powers-tool") { throw "Unexpected distribution name." }
try {
    $resolvedSuite = Resolve-ValidationSuite -Suite $Suite
    $targets = @(Resolve-ValidationPreflightTargets -Target $Target -Suite $resolvedSuite)
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
$anyFailed = $false
try {
    foreach ($resolvedTarget in $targets) {
        $targetDir = Join-Path $runRoot $resolvedTarget
        $privateDir = Join-Path $targetDir "private"
        $shareableDir = Join-Path $targetDir "shareable"
        New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
        New-Item -ItemType Directory -Path $shareableDir -Force | Out-Null
        $sequencePath = Join-Path $privateDir "sequence-readonly.yaml"
        if ($resolvedSuite -ne "smoke") {
            $sequence = @("version: 1","steps:","  - action: readback","    channel: 1","  - action: output-state","    channel: 1") -join [Environment]::NewLine
            Write-Utf8NoBomText -LiteralPath $sequencePath -Text $sequence
        }
        $commands = New-Object System.Collections.Generic.List[object]
        foreach ($case in @(Get-ValidationPreflightCases -Target $resolvedTarget -ArtifactDirectory $privateDir -SequencePath $sequencePath -Suite $resolvedSuite)) {
            $commands.Add((Invoke-PreflightCase -Case $case -PrivateDirectory $privateDir -ShareableDirectory $shareableDir))
        }
        $failed = @($commands | Where-Object { -not $_.passed })
        if ($failed.Count -gt 0) { $anyFailed = $true }
        $profile = Get-ValidationTargetProfile -Target $resolvedTarget
        $reportPath = Join-Path $shareableDir "report.json"
        $summaryPath = Join-Path $shareableDir "summary.md"
        $report = [ordered]@{
            schema_version=1; kind="powers-tool-cli-preflight"; status=if ($failed.Count -eq 0) { "passed" } else { "failed" }
            target=$resolvedTarget; targets=@($resolvedTarget); suite=$resolvedSuite; model_id=$resolvedTarget
            expected_model=$profile.model; package_version=$metadata.version; git_head=Get-GitHead
            generated_at=(Get-Date).ToUniversalTime().ToString("o")
            validation_mode="no-hardware-cli-preflight"; hardware_touched=$false
            simulator_resource=$profile.simulator_resource; support_policy_mode="no-hardware"
            visa_io_performed=$false; resource_scan_performed=$false; resource_guess_performed=$false
            artifact_mode=if ($DebugArtifacts) { "debug" } else { "minimal" }
            debug_artifacts_retained=[bool]$DebugArtifacts; private_raw_artifacts_retained=[bool]$DebugArtifacts
            redaction_applied=$true; promotes_live_support=$false
            suites=@($profile.suites); commands=$commands.ToArray()
            checks=@($commands | ForEach-Object { [pscustomobject]@{ name=$_.name; passed=$_.passed; failures=$_.failures } })
            artifact_paths=[ordered]@{ output_dir=Get-PreflightRelativePath -Path $shareableDir; report=Get-PreflightRelativePath -Path $reportPath; summary=Get-PreflightRelativePath -Path $summaryPath }
            summary_counts=[ordered]@{ total=$commands.Count; passed=$commands.Count-$failed.Count; failed=$failed.Count }
        }
        Write-Utf8NoBomText -LiteralPath $reportPath -Text ($report | ConvertTo-Json -Depth 30)
        $summary = New-Object System.Collections.Generic.List[string]
        foreach ($line in @("# Powers Tool CLI Preflight", "", "Target: $resolvedTarget", ("Suite: " + [char]96 + $resolvedSuite + [char]96), "Status: $($report.status)", "Hardware touched: false", "", "| Command | Category | Exit | Result |", "| --- | --- | ---: | --- |")) { $summary.Add($line) }
        foreach ($command in $commands) { $summary.Add("| $($command.name) | $($command.category) | $($command.exit_code) | $(if ($command.passed) { 'passed' } else { 'failed' }) |") }
        Write-Utf8NoBomText -LiteralPath $summaryPath -Text ($summary.ToArray() -join [Environment]::NewLine)
        Test-ValidationShareablePair -Report $reportPath -Summary $summaryPath
        Write-Host ("Report: " + (Get-PreflightRelativePath -Path $reportPath))
        Write-Host ("Summary: " + (Get-PreflightRelativePath -Path $summaryPath))
    }
    if (-not $DebugArtifacts) {
        $keep = @()
        foreach ($resolvedTarget in $targets) {
            $keep += (Join-Path (Join-Path (Join-Path $runRoot $resolvedTarget) "shareable") "report.json")
            $keep += (Join-Path (Join-Path (Join-Path $runRoot $resolvedTarget) "shareable") "summary.md")
        }
        Clear-ValidationRunExcept -RunRoot $runRoot -TmpRoot $TmpRoot -KeepPaths $keep
    }
}
catch {
    try { Write-ValidationArtifactFailure -RunRoot $runRoot -TmpRoot $TmpRoot }
    catch { [Console]::Error.WriteLine("Validation artifact failure cleanup was blocked for safety.") }
    [Console]::Error.WriteLine("Shareable artifact generation or validation failed.")
    exit 1
}
if ($anyFailed) { exit 1 }
exit 0
