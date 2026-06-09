param(
    [string]$Target,
    [string]$Connection,
    [string]$Resource,
    [string]$Backend,
    [string]$Profile = "auto",
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
    Fail-Validation "Missing required -Target. Supported targets: E36312A, EDU36311A."
}
if ([string]::IsNullOrWhiteSpace($Connection)) {
    Fail-Validation "Missing required -Connection. Supported names: USB/local or LAN/network."
}
$normalizedTarget = $Target.Trim().ToUpperInvariant()
if ($normalizedTarget -notin @("E36312A", "EDU36311A")) {
    Fail-Validation "Live smoke validation supports only Target E36312A or EDU36311A."
}

$normalizedConnection = $Connection.Trim().ToUpperInvariant()
$connectionLabel = $null
if ($normalizedConnection -in @("LAN", "NETWORK", "TCPIP", "TCP/IP", "LAN-NETWORK")) {
    $connectionLabel = "LAN"
}
elseif ($normalizedConnection -in @("USB", "LOCAL", "USB-LOCAL")) {
    $connectionLabel = "USB"
}
else {
    Fail-Validation "Unsupported connection name. Received: $Connection"
}
if ([string]::IsNullOrWhiteSpace($Resource)) {
    Fail-Validation "Missing required -Resource. Pass the exact VISA resource explicitly; this script does not scan resources or read an environment default."
}
$ResourceDisplay = "$connectionLabel`:<redacted-resource>"
$normalizedProfile = $Profile.Trim().ToLowerInvariant()
if ($normalizedProfile -notin @("auto", "readonly", "output", "output_smoke")) {
    Fail-Validation "Unsupported -Profile. Use auto, readonly, or output."
}
$isEduReadonly = $normalizedTarget -eq "EDU36311A" -and $normalizedProfile -ne "output" -and $normalizedProfile -ne "output_smoke"
$ProfileName = if ($isEduReadonly) { "readonly" } else { "output_smoke" }
$StateChanging = -not $isEduReadonly

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

function Protect-ValidationArgument {
    param([Parameter(Mandatory = $true)][string]$Argument)

    if ($Argument -eq $Resource) {
        return $ResourceDisplay
    }
    return $Argument
}

function Protect-ValidationArguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return @($Arguments | ForEach-Object { Protect-ValidationArgument -Argument $_ })
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

    $recordArgs = Protect-ValidationArguments -Arguments $allArgs
    $formattedArgs = @("-m", "keysight_power_cli.cli") + $recordArgs
    $commandLine = (Format-CommandArgument -Argument $PythonExe) + " " + (($formattedArgs | ForEach-Object { Format-CommandArgument -Argument $_ }) -join " ")
    $record = [pscustomobject]@{
        name = $Name
        command_line = $commandLine
        arguments = $recordArgs
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
        profile = $ProfileName
        state_changing = $StateChanging
        connection = $connectionLabel
        resource = "<redacted-resource>"
        resource_connection = $connectionLabel
        backend = $Backend
        restore = $Restore
        parameters = [pscustomobject]@{
            channel = 1
            voltage = if ($script:IsEduReadonly) { $null } else { 1.0 }
            current = if ($script:IsEduReadonly) { $null } else { 0.05 }
            duration_ms = if ($script:IsEduReadonly) { $null } else { 500 }
            readonly = $script:IsEduReadonly
        }
        output_dir = ConvertTo-RepoRelativePath -Path $OutputDir
        preflight_report = ".tmp_tests\smoke_validation_preflight\$Target\report.json"
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $completedAt.ToUniversalTime().ToString("o")
        result = $Result
        hardware_touched = (Any-CommandTouchedHardware)
        failures = $Failures
        commands = $script:CommandRecords.ToArray()
    }
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding UTF8

    $lines = New-Object System.Collections.Generic.List[string]
    $modeLabel = if ($script:IsEduReadonly) { "Read-Only Live Smoke Validation" } else { "Full Output Live Smoke Validation" }
    $lines.Add("# $Target $connectionLabel $modeLabel")
    $lines.Add("")
    $lines.Add("Result: " + $Result.ToUpperInvariant())
    $lines.Add("")
    $lines.Add("Target: ``" + $Target + "``")
    $lines.Add("Connection: ``" + $connectionLabel + "``")
    $lines.Add("Profile: ``" + $ProfileName + "``")
    $lines.Add("State-changing: ``" + $StateChanging + "``")
    $lines.Add("Resource: ``" + $ResourceDisplay + "``")
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
if ($isEduReadonly) {
    Write-Host "State-changing operations: none. EDU36311A live smoke is read-only."
    Write-Host "Read-only checks: verify, identify, channel measurements, output-state,"
    Write-Host "status, readback, validate-readonly, one log sample, read-only sequence, and capabilities."
}
else {
    Write-Host "State-changing operations:"
    Write-Host "- Set CH1-CH3 current limits to 0.05 A and voltage setpoints to 1 V."
    Write-Host "- Turn CH1-CH3 outputs OFF."
    Write-Host "- Briefly turn CH1 output ON for about 500 ms, then turn it OFF."
}
Write-Host ""
Write-Host "Possible final state changes:"
if ($isEduReadonly) {
    Write-Host "- The instrument error queue may be read and consumed."
    Write-Host "- No output, voltage, or current writes are sent."
}
else {
    Write-Host "- CH1, CH2, and CH3 outputs should be OFF."
    Write-Host "- CH1, CH2, and CH3 setpoints may remain at 1 V / 0.05 A."
    Write-Host "- The instrument error queue may be read and consumed."
}
Write-Host ""
Write-Host "Restore setting:"
if ($isEduReadonly) {
    Write-Host "- Restore is ignored for EDU36311A read-only smoke."
}
else {
    Write-Host "- Restore=$Restore means this script will attempt safe-off --channel all cleanup."
    Write-Host "- It does not restore original voltage/current/protection settings."
}
Write-Host ""
Write-Host "Physical instrument checks before pressing Enter:"
Write-Host "- Confirm this is the target $Target and the $connectionLabel resource is expected."
if (-not $isEduReadonly) {
    Write-Host "- Confirm CH1 has no DUT connected, or only a known safe load."
    Write-Host "- Confirm output indicators are currently OFF."
    Write-Host "- Confirm no OVP/OCP/error/protection abnormal indicators are shown."
}
Write-Host ""
Write-Host "Expected observation during execution:"
if ($isEduReadonly) {
    Write-Host "- Output indicators should not change."
}
else {
    Write-Host "- CH1 output indicator should turn ON only briefly for about 0.5 seconds."
    Write-Host "- After execution, CH1/CH2/CH3 output indicators should all be OFF."
    Write-Host "- No new protection/error indicators should appear."
}
Write-Host ""
Read-Host "Press Enter to run live smoke, or press Ctrl+C to abort"

$OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:IsEduReadonly = $isEduReadonly
$failures = New-Object System.Collections.Generic.List[string]
$startedAt = Get-Date
$result = "passed"
$logCsv = Join-Path $OutputDir "edu-readonly.csv"
$logJsonl = Join-Path $OutputDir "edu-readonly.jsonl"
$sequenceFile = Join-Path $RepoRoot "examples\sequence-readonly-edu.yaml"

try {
    if ($isEduReadonly) {
        Invoke-LiveCliJsonCommand `
            -Name "verify" `
            -Arguments @("verify", "--json", "--resource", $Resource, "--log-scpi") `
            -JsonFileName "verify.json" | Out-Null

        Invoke-LiveCliJsonCommand `
            -Name "identify" `
            -Arguments @("identify", "--json", "--resource", $Resource, "--log-scpi") `
            -JsonFileName "identify.json" | Out-Null

        foreach ($channel in @(1, 2, 3)) {
            Invoke-LiveCliJsonCommand `
                -Name ("measure-ch" + $channel) `
                -Arguments @("measure", "--json", "--resource", $Resource, "--channel", [string]$channel, "--log-scpi") `
                -JsonFileName ("measure-ch" + $channel + ".json") | Out-Null

            Invoke-LiveCliJsonCommand `
                -Name ("output-state-ch" + $channel) `
                -Arguments @("output-state", "--json", "--resource", $Resource, "--channel", [string]$channel, "--log-scpi") `
                -JsonFileName ("output-state-ch" + $channel + ".json") | Out-Null
        }

        Invoke-LiveCliJsonCommand `
            -Name "read-status" `
            -Arguments @("read-status", "--json", "--resource", $Resource, "--all", "--log-scpi") `
            -JsonFileName "read-status.json" | Out-Null

        Invoke-LiveCliJsonCommand `
            -Name "readback" `
            -Arguments @("readback", "--json", "--resource", $Resource, "--all", "--log-scpi") `
            -JsonFileName "readback.json" | Out-Null

        Invoke-LiveCliJsonCommand `
            -Name "validate-readonly" `
            -Arguments @("validate-readonly", "--json", "--resource", $Resource, "--log-scpi") `
            -JsonFileName "validate-readonly.json" | Out-Null

        Invoke-LiveCliJsonCommand `
            -Name "log" `
            -Arguments @("log", "--json", "--resource", $Resource, "--channel", "all", "--interval-sec", "0.1", "--samples", "1", "--csv", $logCsv, "--jsonl", $logJsonl, "--log-scpi") `
            -JsonFileName "log.json" | Out-Null

        Invoke-LiveCliJsonCommand `
            -Name "sequence-readonly" `
            -Arguments @("sequence", "--json", "--resource", $Resource, "--file", $sequenceFile, "--log-scpi") `
            -JsonFileName "sequence-readonly.json" | Out-Null

        Invoke-LiveCliJsonCommand `
            -Name "capabilities" `
            -Arguments @("capabilities", "--json", "--resource", $Resource, "--log-scpi") `
            -JsonFileName "capabilities.json" | Out-Null
    }
    else {
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
}
catch {
    $result = "failed"
    $failures.Add($_.Exception.Message)
    if ($Restore -and -not $isEduReadonly) {
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
