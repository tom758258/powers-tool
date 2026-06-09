param(
    [string]$Target,
    [string]$Connection,
    [string]$Resource,
    [string]$Backend,
    [bool]$Restore = $true
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

function Fail-Validation {
    param([Parameter(Mandatory = $true)][string]$Message)

    [Console]::Error.WriteLine($Message)
    exit 2
}

if ([string]::IsNullOrWhiteSpace($Target)) {
    Fail-Validation "Missing required -Target. v1 supports only -Target E36312A."
}
if ([string]::IsNullOrWhiteSpace($Connection)) {
    Fail-Validation "Missing required -Connection. v1 supports only -Connection USB for live smoke."
}
if ($Target -eq "EDU36311A") {
    Fail-Validation "EDU36311A live smoke is not supported in v1 because real output execution is not enabled for EDU36311A."
}
if ($Target -ne "E36312A") {
    Fail-Validation "Live smoke validation v1 supports only Target E36312A."
}

$normalizedConnection = $Connection.Trim().ToUpperInvariant()
if ($normalizedConnection -in @("LAN", "NETWORK", "TCPIP", "TCP/IP", "LAN-NETWORK")) {
    Fail-Validation "LAN/network live smoke is blocked in v1. Use E36312A with a USB/local resource only."
}
if ($normalizedConnection -notin @("USB", "LOCAL", "USB-LOCAL")) {
    Fail-Validation "Live smoke validation v1 supports only USB/local connection names. Received: $Connection"
}
if ([string]::IsNullOrWhiteSpace($Resource)) {
    Fail-Validation "Missing required -Resource. Pass the exact VISA resource explicitly; this script does not scan resources or read an environment default."
}
$connectionLabel = "USB"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputDir = Join-Path (Join-Path $TmpRoot "smoke_validation_live") ($timestamp + "_" + $Target + "_" + $connectionLabel)
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

function Add-BackendArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if (-not [string]::IsNullOrWhiteSpace($Backend)) {
        return @($Arguments + @("--backend", $Backend))
    }
    return $Arguments
}

function Invoke-LiveCliJsonCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$JsonFileName,
        [bool]$Required = $true
    )

    $jsonPath = Join-Path $OutputDir $JsonFileName
    $stdoutPath = Join-Path $OutputDir ($Name + ".stdout.txt")
    $stderrPath = Join-Path $OutputDir ($Name + ".stderr-scpi.txt")
    $argsWithBackend = Add-BackendArgument -Arguments $Arguments
    $allArgs = @($argsWithBackend + @("--save-json", $jsonPath))
    $oldPythonPath = $env:PYTHONPATH
    $srcPath = Join-Path $RepoRoot "src"
    if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        $env:PYTHONPATH = $srcPath
    }
    else {
        $env:PYTHONPATH = $srcPath + [System.IO.Path]::PathSeparator + $oldPythonPath
    }

    try {
        & $PythonExe -m keysight_power.cli @allArgs 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $oldPythonPath
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

    $formattedArgs = @("-m", "keysight_power.cli") + $allArgs
    $commandLine = (Format-CommandArgument -Argument $PythonExe) + " " + (($formattedArgs | ForEach-Object { Format-CommandArgument -Argument $_ }) -join " ")
    $record = [pscustomobject]@{
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
        required = $Required
        json_path = ConvertTo-RepoRelativePath -Path $jsonPath
        stdout_path = ConvertTo-RepoRelativePath -Path $stdoutPath
        stderr_scpi_path = ConvertTo-RepoRelativePath -Path $stderrPath
    }
    $script:CommandRecords.Add($record)

    if ($Required) {
        if ($exitCode -ne 0) {
            throw "$Name failed with exit code $exitCode."
        }
        if ($null -ne $parseError) {
            throw "$Name did not produce parseable JSON: $parseError"
        }
        if ($ok -ne $true) {
            throw "$Name returned ok=false ($errorCode)."
        }
    }

    return $record
}

function Invoke-SafeOffCleanup {
    param([Parameter(Mandatory = $true)][string]$Name)

    Invoke-LiveCliJsonCommand `
        -Name $Name `
        -Arguments @("safe-off", "--json", "--resource", $Resource, "--channel", "all", "--log-scpi") `
        -JsonFileName ($Name + ".json") `
        -Required:$false | Out-Null
}

function Any-CommandTouchedHardware {
    foreach ($record in $script:CommandRecords) {
        if ($record.hardware_touched -eq $true) {
            return $true
        }
    }
    return $false
}

function Write-LiveArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Result,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Failures,
        [Parameter(Mandatory = $true)][datetime]$StartedAt
    )

    $completedAt = Get-Date
    $reportPath = Join-Path $OutputDir "report.json"
    $summaryPath = Join-Path $OutputDir "summary.md"
    $report = [pscustomobject]@{
        schema_version = "1.0"
        kind = "smoke_validation_live"
        target = $Target
        connection = $connectionLabel
        resource = $Resource
        backend = $Backend
        restore = $Restore
        parameters = [pscustomobject]@{
            channel = 1
            voltage = 1.0
            current = 0.05
            duration_ms = 500
        }
        output_dir = ConvertTo-RepoRelativePath -Path $OutputDir
        preflight_report = ".tmp_tests\smoke_validation_preflight\E36312A\report.json"
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $completedAt.ToUniversalTime().ToString("o")
        result = $Result
        hardware_touched = (Any-CommandTouchedHardware)
        failures = $Failures
        commands = $script:CommandRecords.ToArray()
    }
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding UTF8

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# E36312A USB Live Smoke Validation")
    $lines.Add("")
    $lines.Add("Result: " + $Result.ToUpperInvariant())
    $lines.Add("")
    $lines.Add("Target: ``" + $Target + "``")
    $lines.Add("Connection: ``" + $connectionLabel + "``")
    $lines.Add("Resource: ``" + $Resource + "``")
    $lines.Add("Restore safe-off cleanup: ``" + $Restore + "``")
    $lines.Add("Output directory: ``" + (ConvertTo-RepoRelativePath -Path $OutputDir) + "``")
    $lines.Add("")
    $lines.Add("| Command | Exit | ok | hardware_touched | JSON | SCPI/stderr |")
    $lines.Add("| --- | ---: | --- | --- | --- | --- |")
    foreach ($command in $script:CommandRecords) {
        $lines.Add("| ``" + $command.name + "`` | " + $command.exit_code + " | " + $command.ok + " | " + $command.hardware_touched + " | ``" + $command.json_path + "`` | ``" + $command.stderr_scpi_path + "`` |")
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

function Assert-LiveArtifacts {
    param([Parameter(Mandatory = $true)][string]$ExpectedResult)

    $reportPath = Join-Path $OutputDir "report.json"
    $summaryPath = Join-Path $OutputDir "summary.md"
    if (-not (Test-Path -LiteralPath $reportPath)) {
        throw "Expected live report was not created: $reportPath"
    }
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        throw "Expected live summary was not created: $summaryPath"
    }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.result -ne $ExpectedResult) {
        throw "Live report result mismatch: expected $ExpectedResult, got $($report.result)"
    }
}

$preflightScript = Join-Path $PSScriptRoot "preflight-smoke-validation.ps1"
if (-not (Test-Path -LiteralPath $preflightScript)) {
    Write-Error "Preflight script was not found: $preflightScript"
    exit 1
}

Write-Host "Running hardware-free preflight before live smoke..."
& $preflightScript -Target $Target
if ($LASTEXITCODE -ne 0) {
    Write-Error "Preflight failed. Live smoke will not run."
    exit 1
}

Write-Host ""
Write-Host "Live smoke validation is ready to open VISA and send SCPI."
Write-Host ""
Write-Host "Target: $Target"
Write-Host "Connection: $connectionLabel"
Write-Host "Resource: $Resource"
if (-not [string]::IsNullOrWhiteSpace($Backend)) {
    Write-Host "Backend: $Backend"
}
Write-Host ""
Write-Host "This will open VISA for the selected resource and send SCPI commands."
Write-Host "State-changing operations:"
Write-Host "- Set CH1-CH3 current limits to 0.05 A and voltage setpoints to 1 V."
Write-Host "- Turn CH1-CH3 outputs OFF."
Write-Host "- Briefly turn CH1 output ON for about 500 ms, then turn it OFF."
Write-Host ""
Write-Host "Possible final state changes:"
Write-Host "- CH1, CH2, and CH3 outputs should be OFF."
Write-Host "- CH1, CH2, and CH3 setpoints may remain at 1 V / 0.05 A."
Write-Host "- The instrument error queue may be read and consumed."
Write-Host ""
Write-Host "Restore setting:"
Write-Host "- Restore=$Restore means this script will attempt safe-off --channel all cleanup."
Write-Host "- It does not restore original voltage/current/protection settings."
Write-Host ""
Write-Host "Physical instrument checks before pressing Enter:"
Write-Host "- Confirm this is the target E36312A and the USB/local resource is expected."
Write-Host "- Confirm CH1 has no DUT connected, or only a known safe load."
Write-Host "- Confirm output indicators are currently OFF."
Write-Host "- Confirm no OVP/OCP/error/protection abnormal indicators are shown."
Write-Host ""
Write-Host "Expected observation during execution:"
Write-Host "- CH1 output indicator should turn ON only briefly for about 0.5 seconds."
Write-Host "- After execution, CH1/CH2/CH3 output indicators should all be OFF."
Write-Host "- No new protection/error indicators should appear."
Write-Host ""
Read-Host "Press Enter to run live smoke, or press Ctrl+C to abort"

$OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$failures = New-Object System.Collections.Generic.List[string]
$startedAt = Get-Date
$result = "passed"

try {
    Invoke-LiveCliJsonCommand `
        -Name "before" `
        -Arguments @("snapshot", "--json", "--resource", $Resource, "--log-scpi") `
        -JsonFileName "before.json" | Out-Null

    Invoke-LiveCliJsonCommand `
        -Name "apply-no-output" `
        -Arguments @("apply", "--json", "--resource", $Resource, "--channel", "all", "--voltage", "1", "--current", "0.05", "--no-output", "--log-scpi") `
        -JsonFileName "apply-no-output.json" | Out-Null

    Invoke-LiveCliJsonCommand `
        -Name "safe-off-before" `
        -Arguments @("safe-off", "--json", "--resource", $Resource, "--channel", "all", "--log-scpi") `
        -JsonFileName "safe-off-before.json" | Out-Null

    Invoke-LiveCliJsonCommand `
        -Name "smoke-output" `
        -Arguments @("smoke-output", "--json", "--resource", $Resource, "--channel", "1", "--voltage", "1", "--current", "0.05", "--duration-ms", "500", "--log-scpi") `
        -JsonFileName "smoke-output.json" | Out-Null

    if ($Restore) {
        Invoke-LiveCliJsonCommand `
            -Name "safe-off-cleanup" `
            -Arguments @("safe-off", "--json", "--resource", $Resource, "--channel", "all", "--log-scpi") `
            -JsonFileName "safe-off-cleanup.json" | Out-Null
    }

    Invoke-LiveCliJsonCommand `
        -Name "after" `
        -Arguments @("snapshot", "--json", "--resource", $Resource, "--log-scpi") `
        -JsonFileName "after.json" | Out-Null
}
catch {
    $result = "failed"
    $failures.Add($_.Exception.Message)
    if ($Restore) {
        try {
            Invoke-SafeOffCleanup -Name "safe-off-failure-cleanup"
        }
        catch {
            $failures.Add("Failure cleanup threw: " + $_.Exception.Message)
        }
    }
}

Write-LiveArtifacts -Result $result -Failures $failures.ToArray() -StartedAt $startedAt
Assert-LiveArtifacts -ExpectedResult $result

if ($result -ne "passed") {
    Write-Error "Live smoke validation failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $OutputDir 'report.json'))."
    exit 1
}

Write-Host "Live smoke validation passed."
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $OutputDir 'report.json'))"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $OutputDir 'summary.md'))"
