param(
    [string]$Target = "E36312A"
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$normalizedTarget = $Target.Trim().ToUpperInvariant()
if ($normalizedTarget -notin @("E36312A", "EDU36311A")) {
    [Console]::Error.WriteLine("Smoke validation preflight supports only Target E36312A or EDU36311A.")
    exit 2
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
$OutputDir = Join-Path (Join-Path $TmpRoot "smoke_validation_preflight") $Target
$ProfileName = if ($normalizedTarget -eq "EDU36311A") { "readonly" } else { "output_smoke" }
$StateChanging = $false
$PythonExe = Join-Path (Join-Path $RepoRoot ".venv") "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}

function Assert-UnderDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $comparison = [System.StringComparison]::OrdinalIgnoreCase

    if ($fullPath.Equals($fullRoot, $comparison)) {
        return
    }
    if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, $comparison)) {
        return
    }
    if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::AltDirectorySeparatorChar, $comparison)) {
        return
    }

    throw "Refusing to operate outside $fullRoot`: $fullPath"
}

function Reset-OutputDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    Assert-UnderDirectory -Path $Path -Root $Root
    if (Test-Path -LiteralPath $Path) {
        $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
        Assert-UnderDirectory -Path $resolvedPath -Root $Root
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    return (Resolve-Path -LiteralPath $Path).Path
}

function ConvertTo-RepoRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, $comparison)) {
        return $fullPath.Substring($fullRoot.Length + 1)
    }
    return $fullPath
}

function Format-CommandArgument {
    param([Parameter(Mandatory = $true)][string]$Argument)

    if ($Argument -match '\s') {
        return '"' + ($Argument -replace '"', '\"') + '"'
    }
    return $Argument
}

function Invoke-CliJsonCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$JsonFileName
    )

    $jsonPath = Join-Path $OutputDir $JsonFileName
    $stdoutPath = Join-Path $OutputDir ($Name + ".stdout.txt")
    $stderrPath = Join-Path $OutputDir ($Name + ".stderr.txt")
    $allArgs = @($Arguments + @("--save-json", $jsonPath))

    $oldErrorActionPreference = $ErrorActionPreference
    $nativePreferenceVariable = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $hadNativePreference = $null -ne $nativePreferenceVariable
    $oldNativePreference = $null
    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            $oldNativePreference = [bool]$nativePreferenceVariable.Value
            $PSNativeCommandUseErrorActionPreference = $false
        }
        & $PythonExe -m keysight_power_cli.cli @allArgs 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }

    $payload = $null
    $parseError = $null
    if (Test-Path -LiteralPath $jsonPath) {
        try {
            $payload = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
        }
        catch {
            $parseError = "Could not parse JSON output: " + $_.Exception.Message
        }
    }
    else {
        $parseError = "JSON output file was not created."
    }

    $ok = $null
    $hardwareTouched = $null
    $mode = $null
    $dryRun = $null
    $errorCode = $null
    if ($null -ne $payload) {
        $ok = [bool]$payload.ok
        $hardwareTouched = [bool]$payload.execution.hardware_touched
        $mode = [string]$payload.execution.mode
        $dryRun = [bool]$payload.execution.dry_run
        if ($null -ne $payload.error) {
            $errorCode = [string]$payload.error.code
        }
    }

    $formattedArgs = @("-m", "keysight_power_cli.cli") + $allArgs
    $commandLine = (Format-CommandArgument -Argument $PythonExe) + " " + (($formattedArgs | ForEach-Object { Format-CommandArgument -Argument $_ }) -join " ")

    return [pscustomobject]@{
        name = $Name
        command_line = $commandLine
        arguments = $allArgs
        exit_code = $exitCode
        ok = $ok
        mode = $mode
        dry_run = $dryRun
        hardware_touched = $hardwareTouched
        error_code = $errorCode
        parse_error = $parseError
        json_path = ConvertTo-RepoRelativePath -Path $jsonPath
        stdout_path = ConvertTo-RepoRelativePath -Path $stdoutPath
        stderr_path = ConvertTo-RepoRelativePath -Path $stderrPath
    }
}

function Test-PreflightRecord {
    param([Parameter(Mandatory = $true)]$Record)

    if ($Record.exit_code -ne 0) {
        return "$($Record.name) failed with exit code $($Record.exit_code)."
    }
    if ($null -ne $Record.parse_error) {
        return "$($Record.name) did not produce parseable JSON: $($Record.parse_error)"
    }
    if ($Record.ok -ne $true) {
        return "$($Record.name) returned ok=false ($($Record.error_code))."
    }
    if ($Record.hardware_touched -ne $false) {
        return "$($Record.name) reported execution.hardware_touched=$($Record.hardware_touched)."
    }
    return $null
}

function Write-PreflightArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Result,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Commands,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Failures,
        [Parameter(Mandatory = $true)][datetime]$StartedAt
    )

    $completedAt = Get-Date
    $reportPath = Join-Path $OutputDir "report.json"
    $summaryPath = Join-Path $OutputDir "summary.md"
    $report = [pscustomobject]@{
        schema_version = "1.0"
        kind = "smoke_validation_preflight"
        target = $Target
        profile = $ProfileName
        state_changing = $StateChanging
        resource = $script:SimResource
        parameters = [pscustomobject]@{
            channels = @(1, 2, 3)
            voltage = 1.0
            current = 0.05
            duration_ms = 500
        }
        output_dir = ConvertTo-RepoRelativePath -Path $OutputDir
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $completedAt.ToUniversalTime().ToString("o")
        result = $Result
        hardware_touched = $false
        failures = $Failures
        commands = $Commands
    }
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding UTF8

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# $Target Smoke Validation Preflight")
    $lines.Add("")
    $lines.Add("Result: " + $Result.ToUpperInvariant())
    $lines.Add("")
    $lines.Add("Output directory: ``" + (ConvertTo-RepoRelativePath -Path $OutputDir) + "``")
    $lines.Add("")
    $lines.Add("This preflight uses only ``--dry-run`` and ``--simulate`` commands. It does not open VISA or touch hardware.")
    $lines.Add("")
    $lines.Add("Profile: ``" + $ProfileName + "``")
    $lines.Add("")
    $lines.Add("| Command | Exit | ok | hardware_touched | JSON |")
    $lines.Add("| --- | ---: | --- | --- | --- |")
    foreach ($command in $Commands) {
        $lines.Add("| ``" + $command.name + "`` | " + $command.exit_code + " | " + $command.ok + " | " + $command.hardware_touched + " | ``" + $command.json_path + "`` |")
    }
    if ($Failures.Count -gt 0) {
        $lines.Add("")
        $lines.Add("## Failures")
        foreach ($failure in $Failures) {
            $lines.Add("- " + $failure)
        }
    }
    $lines | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}

function Assert-PreflightArtifacts {
    $reportPath = Join-Path $OutputDir "report.json"
    $summaryPath = Join-Path $OutputDir "summary.md"
    if (-not (Test-Path -LiteralPath $reportPath)) {
        throw "Expected preflight report was not created: $reportPath"
    }
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        throw "Expected preflight summary was not created: $summaryPath"
    }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.result -ne $result) {
        throw "Preflight report result mismatch: expected $result, got $($report.result)"
    }
    foreach ($command in $report.commands) {
        if ($command.hardware_touched -ne $false) {
            throw "Preflight report contains hardware_touched=true for $($command.name)."
        }
    }
}

$OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
$startedAt = Get-Date
$simResource = if ($normalizedTarget -eq "EDU36311A") { "USB0::SIM::EDU36311A::INSTR" } else { "USB0::SIM::E36312A::INSTR" }
$script:SimResource = $simResource
$records = New-Object System.Collections.Generic.List[object]
$failures = New-Object System.Collections.Generic.List[string]

if ($normalizedTarget -eq "EDU36311A") {
    $commands = @(
        [pscustomobject]@{ Name = "verify-simulate"; Json = "verify.json"; Args = @("verify", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "identify-simulate"; Json = "identify.json"; Args = @("identify", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "measure-ch1-simulate"; Json = "measure-ch1.json"; Args = @("measure", "--simulate", "--json", "--resource", $simResource, "--channel", "1") },
        [pscustomobject]@{ Name = "measure-ch2-simulate"; Json = "measure-ch2.json"; Args = @("measure", "--simulate", "--json", "--resource", $simResource, "--channel", "2") },
        [pscustomobject]@{ Name = "measure-ch3-simulate"; Json = "measure-ch3.json"; Args = @("measure", "--simulate", "--json", "--resource", $simResource, "--channel", "3") },
        [pscustomobject]@{ Name = "output-state-ch1-simulate"; Json = "output-state-ch1.json"; Args = @("output-state", "--simulate", "--json", "--resource", $simResource, "--channel", "1") },
        [pscustomobject]@{ Name = "output-state-ch2-simulate"; Json = "output-state-ch2.json"; Args = @("output-state", "--simulate", "--json", "--resource", $simResource, "--channel", "2") },
        [pscustomobject]@{ Name = "output-state-ch3-simulate"; Json = "output-state-ch3.json"; Args = @("output-state", "--simulate", "--json", "--resource", $simResource, "--channel", "3") },
        [pscustomobject]@{ Name = "read-status-simulate"; Json = "read-status.json"; Args = @("read-status", "--simulate", "--json", "--resource", $simResource, "--all") },
        [pscustomobject]@{ Name = "readback-simulate"; Json = "readback.json"; Args = @("readback", "--simulate", "--json", "--resource", $simResource, "--all") },
        [pscustomobject]@{ Name = "validate-readonly-simulate"; Json = "validate-readonly.json"; Args = @("validate-readonly", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "protection-status-simulate"; Json = "protection-status.json"; Args = @("protection-status", "--simulate", "--json", "--resource", $simResource, "--all") },
        [pscustomobject]@{ Name = "log-simulate"; Json = "log.json"; Args = @("log", "--simulate", "--json", "--resource", $simResource, "--channel", "all", "--interval-sec", "0.1", "--samples", "1", "--csv", (Join-Path $OutputDir "edu-readonly.csv"), "--jsonl", (Join-Path $OutputDir "edu-readonly.jsonl")) },
        [pscustomobject]@{ Name = "sequence-readonly-simulate"; Json = "sequence.json"; Args = @("sequence", "--simulate", "--json", "--resource", $simResource, "--file", (Join-Path $RepoRoot "examples\sequence-readonly-edu.yaml")) },
        [pscustomobject]@{ Name = "capabilities-simulate"; Json = "capabilities.json"; Args = @("capabilities", "--simulate", "--json", "--resource", $simResource) }
    )
}
else {
    $commands = @(
        [pscustomobject]@{ Name = "verify-simulate"; Json = "verify.json"; Args = @("verify", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "identify-simulate"; Json = "identify.json"; Args = @("identify", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "measure-ch1-simulate"; Json = "measure-ch1.json"; Args = @("measure", "--simulate", "--json", "--resource", $simResource, "--channel", "1") },
        [pscustomobject]@{ Name = "measure-ch2-simulate"; Json = "measure-ch2.json"; Args = @("measure", "--simulate", "--json", "--resource", $simResource, "--channel", "2") },
        [pscustomobject]@{ Name = "measure-ch3-simulate"; Json = "measure-ch3.json"; Args = @("measure", "--simulate", "--json", "--resource", $simResource, "--channel", "3") },
        [pscustomobject]@{ Name = "output-state-ch1-simulate"; Json = "output-state-ch1.json"; Args = @("output-state", "--simulate", "--json", "--resource", $simResource, "--channel", "1") },
        [pscustomobject]@{ Name = "output-state-ch2-simulate"; Json = "output-state-ch2.json"; Args = @("output-state", "--simulate", "--json", "--resource", $simResource, "--channel", "2") },
        [pscustomobject]@{ Name = "output-state-ch3-simulate"; Json = "output-state-ch3.json"; Args = @("output-state", "--simulate", "--json", "--resource", $simResource, "--channel", "3") },
        [pscustomobject]@{ Name = "read-status-simulate"; Json = "read-status.json"; Args = @("read-status", "--simulate", "--json", "--resource", $simResource, "--all") },
        [pscustomobject]@{ Name = "readback-simulate"; Json = "readback.json"; Args = @("readback", "--simulate", "--json", "--resource", $simResource, "--all") },
        [pscustomobject]@{ Name = "validate-readonly-simulate"; Json = "validate-readonly.json"; Args = @("validate-readonly", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "protection-status-simulate"; Json = "protection-status.json"; Args = @("protection-status", "--simulate", "--json", "--resource", $simResource, "--all") },
        [pscustomobject]@{ Name = "log-simulate"; Json = "log.json"; Args = @("log", "--simulate", "--json", "--resource", $simResource, "--channel", "all", "--interval-sec", "0.1", "--samples", "1", "--csv", (Join-Path $OutputDir "e36312a-smoke.csv"), "--jsonl", (Join-Path $OutputDir "e36312a-smoke.jsonl")) },
        [pscustomobject]@{ Name = "capabilities-simulate"; Json = "capabilities.json"; Args = @("capabilities", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "snapshot-before-simulate"; Json = "snapshot-before.json"; Args = @("snapshot", "--simulate", "--json", "--resource", $simResource) },
        [pscustomobject]@{ Name = "apply-no-output-dry-run"; Json = "apply-no-output.json"; Args = @("apply", "--dry-run", "--json", "--resource", $simResource, "--channel", "all", "--voltage", "1", "--current", "0.05", "--no-output") },
        [pscustomobject]@{ Name = "safe-off-before-dry-run"; Json = "safe-off-before.json"; Args = @("safe-off", "--dry-run", "--json", "--resource", $simResource, "--channel", "all") },
        [pscustomobject]@{ Name = "smoke-output-ch1-dry-run"; Json = "smoke-output-ch1.json"; Args = @("smoke-output", "--dry-run", "--json", "--resource", $simResource, "--channel", "1", "--voltage", "1", "--current", "0.05", "--duration-ms", "500") },
        [pscustomobject]@{ Name = "smoke-output-ch2-dry-run"; Json = "smoke-output-ch2.json"; Args = @("smoke-output", "--dry-run", "--json", "--resource", $simResource, "--channel", "2", "--voltage", "1", "--current", "0.05", "--duration-ms", "500") },
        [pscustomobject]@{ Name = "smoke-output-ch3-dry-run"; Json = "smoke-output-ch3.json"; Args = @("smoke-output", "--dry-run", "--json", "--resource", $simResource, "--channel", "3", "--voltage", "1", "--current", "0.05", "--duration-ms", "500") },
        [pscustomobject]@{ Name = "safe-off-cleanup-dry-run"; Json = "safe-off-cleanup.json"; Args = @("safe-off", "--dry-run", "--json", "--resource", $simResource, "--channel", "all") },
        [pscustomobject]@{ Name = "snapshot-after-simulate"; Json = "snapshot-after.json"; Args = @("snapshot", "--simulate", "--json", "--resource", $simResource) }
    )
}

foreach ($command in $commands) {
    $record = Invoke-CliJsonCommand -Name $command.Name -Arguments $command.Args -JsonFileName $command.Json
    $records.Add($record)
    $failure = Test-PreflightRecord -Record $record
    if ($null -ne $failure) {
        $failures.Add($failure)
    }
}

$result = "passed"
if ($failures.Count -gt 0) {
    $result = "failed"
}

Write-PreflightArtifacts -Result $result -Commands $records.ToArray() -Failures $failures.ToArray() -StartedAt $startedAt
Assert-PreflightArtifacts

if ($result -ne "passed") {
    Write-Error "Smoke validation preflight failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $OutputDir 'report.json'))."
    exit 1
}

Write-Host "Smoke validation preflight passed."
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $OutputDir 'report.json'))"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $OutputDir 'summary.md'))"
