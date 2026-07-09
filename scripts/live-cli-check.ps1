param(
    [Alias("Model", "Profile")]
    [string]$Target,

    [Alias("Transport")]
    [string]$Connection,

    [string]$Resource,

    [string]$Backend,

    [ValidateSet("readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence", "full")]
    [string]$Suite = "readonly",

    [switch]$PlanOnly,

    [bool]$Restore = $true
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$SupportedTargets = @("E36312A", "EDU36311A", "E3646A")
$SimResources = @{
    E36312A = "USB0::SIM::E36312A::INSTR"
    EDU36311A = "USB0::SIM::EDU36311A::INSTR"
    E3646A = "ASRL1::SIM::E3646A::INSTR"
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
$PythonExe = Join-Path (Join-Path $RepoRoot ".venv") "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}

function Fail-Validation {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [int]$Code = 2
    )

    [Console]::Error.WriteLine($Message)
    exit $Code
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

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][AllowEmptyString()][string[]]$Value
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($LiteralPath, $Value, $encoding)
}

function Format-CommandArgument {
    param([Parameter(Mandatory = $true)][string]$Argument)

    if ($Argument -match '\s') {
        return '"' + ($Argument -replace '"', '\"') + '"'
    }
    return $Argument
}

function Protect-Argument {
    param([Parameter(Mandatory = $true)][string]$Argument)

    if ($Argument -eq $script:RawResource) {
        return $script:ResourceDisplay
    }
    return $Argument
}

function Protect-Arguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return @($Arguments | ForEach-Object { Protect-Argument -Argument $_ })
}

function Get-GitHead {
    try {
        $head = & git -C $RepoRoot rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [string]$head
        }
    }
    catch {
    }
    return $null
}

function Get-PackageVersion {
    $pyproject = Join-Path $RepoRoot "pyproject.toml"
    if (-not (Test-Path -LiteralPath $pyproject)) {
        return $null
    }
    foreach ($line in Get-Content -LiteralPath $pyproject) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"') {
            return $Matches[1]
        }
    }
    return $null
}

function Resolve-Target {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail-Validation "Missing required -Target. Supported targets: $($SupportedTargets -join ', '). GENERIC is no-hardware only."
    }
    $normalized = $Value.Trim().ToUpperInvariant()
    if ($normalized -eq "GENERIC") {
        Fail-Validation "GENERIC is no-hardware only and is not accepted as a live validation target."
    }
    if ($normalized -notin $SupportedTargets) {
        Fail-Validation "Unsupported -Target '$Value'. Supported targets: $($SupportedTargets -join ', ')."
    }
    return $normalized
}

function Resolve-Connection {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail-Validation "Missing required -Connection. Supported names: USB/local, LAN/network, or ASRL/RS-232/serial."
    }
    $normalized = $Value.Trim().ToUpperInvariant()
    if ($normalized -in @("USB", "LOCAL", "USB-LOCAL")) {
        return "USB"
    }
    if ($normalized -in @("LAN", "NETWORK", "TCPIP", "TCP/IP", "LAN-NETWORK")) {
        return "LAN"
    }
    if ($normalized -in @("ASRL", "RS232", "RS-232", "SERIAL")) {
        return "ASRL"
    }
    Fail-Validation "Unsupported -Connection '$Value'. Supported names: USB/local, LAN/network, or ASRL/RS-232/serial."
}

function Get-TargetChannels {
    param([string]$Model)

    if ($Model -in @("E36312A", "EDU36311A")) {
        return @(1, 2, 3)
    }
    if ($Model -eq "E3646A") {
        return @(1, 2)
    }
    return @(1)
}

function Get-SupportedSuites {
    param([string]$Model)

    if ($Model -eq "E36312A") {
        return @("readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence")
    }
    if ($Model -eq "EDU36311A") {
        return @("readonly", "output", "protection", "software-sequence")
    }
    if ($Model -eq "E3646A") {
        return @("readonly", "output", "software-sequence")
    }
    Fail-Validation "Unsupported -Target '$Model'. Supported targets: $($SupportedTargets -join ', ')."
}

function Test-LiveExecutionMode {
    param([string]$Mode)

    return $Mode -in @("real", "live")
}

function Get-CaseArtifactBaseName {
    param([Parameter(Mandatory = $true)]$Case)

    return "$($Case.phase)-$($Case.name)"
}

function New-CommandCase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Suite,
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)][string[]]$Args,
        [bool]$ExpectedSuccess = $true,
        [string]$ExpectedErrorContains,
        [bool]$StateChanging = $false,
        [bool]$LiveHardwareExpected = $false
    )

    return [pscustomobject]@{
        name = $Name
        suite = $Suite
        phase = $Phase
        args = $Args
        expected_success = $ExpectedSuccess
        expected_error_contains = $ExpectedErrorContains
        state_changing = $StateChanging
        live_hardware_expected = $LiveHardwareExpected
    }
}

function Add-BackendArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if (-not [string]::IsNullOrWhiteSpace($script:BackendValue)) {
        return @($Arguments + @("--backend", $script:BackendValue))
    }
    return $Arguments
}

function New-ValidationSequenceFile {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )

    $path = Join-Path $script:OutputDir ($Name + ".yaml")
    Write-Utf8NoBomFile -LiteralPath $path -Value $Lines
    return $path
}

function New-ValidationSnapshotFile {
    $path = Join-Path $script:OutputDir "generated-e36312a-snapshot.json"
    $snapshot = [pscustomobject]@{
        ok = $true
        data = [pscustomobject]@{
            resource = $SimResources.E36312A
            idn = [pscustomobject]@{
                raw = "KEYSIGHT,E36312A,SIM000003,1.0"
                manufacturer = "KEYSIGHT"
                model = "E36312A"
                serial = "SIM000003"
                firmware = "1.0"
                parse_ok = $true
            }
            errors = @()
            outputs = @([pscustomobject]@{ channel = 1; enabled = $false })
            readback = @([pscustomobject]@{ channel = 1; setpoints = [pscustomobject]@{ voltage = 1.0; current = 0.05 } })
            measurements = @([pscustomobject]@{ channel = 1; measurements = [pscustomobject]@{ voltage = 1.0; current = 0.0 } })
            protection = [pscustomobject]@{ over_voltage_tripped = $false; over_current_tripped = $false }
            protection_settings = @([pscustomobject]@{ channel = 1; protection = [pscustomobject]@{ ovp_voltage = 5.0; ocp_enabled = $true } })
        }
    }
    Write-Utf8NoBomFile -LiteralPath $path -Value @($snapshot | ConvertTo-Json -Depth 20)
    return $path
}

function Get-ReadOnlyCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $SimResources[$Model] }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $phase = if ($Live) { "live" } else { "preflight" }
    $cases = New-Object System.Collections.Generic.List[object]
    $cases.Add((New-CommandCase -Name "verify" -Suite "readonly" -Phase $phase -Args (@("verify") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "identify" -Suite "readonly" -Phase $phase -Args (@("identify") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "clear" -Suite "readonly" -Phase $phase -Args (@("clear") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "error" -Suite "readonly" -Phase $phase -Args (@("error") + $modeFlag + @("--json", "--resource", $resource, "--max-reads", "20", "--log-scpi")) -LiveHardwareExpected:$Live))
    foreach ($channel in Get-TargetChannels -Model $Model) {
        $cases.Add((New-CommandCase -Name ("measure-ch" + $channel) -Suite "readonly" -Phase $phase -Args (@("measure") + $modeFlag + @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi")) -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("output-state-ch" + $channel) -Suite "readonly" -Phase $phase -Args (@("output-state") + $modeFlag + @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi")) -LiveHardwareExpected:$Live))
    }
    $cases.Add((New-CommandCase -Name "read-status" -Suite "readonly" -Phase $phase -Args (@("read-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "readback" -Suite "readonly" -Phase $phase -Args (@("readback") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live))
    if ($Model -in @("E36312A", "EDU36311A")) {
        $cases.Add((New-CommandCase -Name "validate-readonly" -Suite "readonly" -Phase $phase -Args (@("validate-readonly") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name "protection-status" -Suite "readonly" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live))
    }
    $cases.Add((New-CommandCase -Name "capabilities" -Suite "readonly" -Phase $phase -Args (@("capabilities") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    return $cases.ToArray()
}

function Get-OutputCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $SimResources[$Model] }
    $modelArgs = if ($Live) { @() } else { @("--model", $Model) }
    $phase = if ($Live) { "live" } else { "preflight" }
    $cases = New-Object System.Collections.Generic.List[object]
    foreach ($channel in Get-TargetChannels -Model $Model) {
        $common = if ($Live) { @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", [string]$channel) }
        $cases.Add((New-CommandCase -Name ("set-ch" + $channel) -Suite "output" -Phase $phase -Args (@("set") + $common + @("--voltage", "1", "--current", "0.05")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("output-off-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-off") + $common) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("smoke-output-ch" + $channel) -Suite "output" -Phase $phase -Args (@("smoke-output") + $common + @("--voltage", "1", "--current", "0.05", "--duration-ms", "500", "--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("cycle-output-ch" + $channel) -Suite "output" -Phase $phase -Args (@("cycle-output") + $common + @("--duration-ms", "500", "--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("ramp-ch" + $channel) -Suite "output" -Phase $phase -Args (@("ramp") + $common + @("--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "0.25", "--current", "0.05", "--delay-ms", "100")) -StateChanging:$Live -LiveHardwareExpected:$Live))
    }
    $allCommon = if ($Live) { @("--json", "--resource", $resource, "--channel", "all", "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", "all") }
    $cases.Insert(0, (New-CommandCase -Name "safe-off-before" -Suite "output" -Phase $phase -Args (@("safe-off") + $allCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
    if ($Live) {
        $readbackArgs = @("readback", "--json", "--resource", $resource, "--all", "--log-scpi")
    }
    else {
        $readbackArgs = @("readback", "--simulate", "--json", "--resource", $resource, "--all")
    }
    $cases.Add((New-CommandCase -Name "readback-after-set" -Suite "output" -Phase $phase -Args $readbackArgs -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "apply-no-output-all" -Suite "output" -Phase $phase -Args (@("apply") + $allCommon + @("--voltage", "1", "--current", "0.05", "--no-output")) -StateChanging:$Live -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "safe-off-cleanup" -Suite "output" -Phase $phase -Args (@("safe-off") + $allCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
    return $cases.ToArray()
}

function Get-ProtectionCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $SimResources[$Model] }
    $phase = if ($Live) { "live" } else { "preflight" }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $writeFlag = if ($Live) { @() } else { @("--dry-run") }
    return @(
        (New-CommandCase -Name "protection-status-before" -Suite "protection" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "protection-set-all" -Suite "protection" -Phase $phase -Args (@("protection-set") + $writeFlag + @("--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "5", "--ocp", "on", "--confirm", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "protection-status-after-set" -Suite "protection" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "clear-protection-all" -Suite "protection" -Phase $phase -Args (@("clear-protection") + $writeFlag + @("--json", "--resource", $resource, "--all", "--confirm", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "protection-status-after-clear" -Suite "protection" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live)
    )
}

function Get-SnapshotCases {
    param([bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $SimResources.E36312A }
    $phase = if ($Live) { "live" } else { "preflight" }
    $snapshotPath = if ($Live) { Join-Path $script:OutputDir "snapshot-live.json" } else { New-ValidationSnapshotFile }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    return @(
        (New-CommandCase -Name "snapshot-save" -Suite "snapshot" -Phase $phase -Args (@("snapshot") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi", "--save-json", $snapshotPath)) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "snapshot-compare" -Suite "snapshot" -Phase $phase -Args (@("snapshot") + $modeFlag + @("--json", "--resource", $resource, "--compare", $snapshotPath, "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "restore-from-snapshot-plan" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--dry-run", "--json", "--snapshot", $snapshotPath, "--resource", $resource, "--channel", "all") -StateChanging:$false -LiveHardwareExpected:$false)
    )
}

function Get-TriggerListCases {
    param([bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $SimResources.E36312A }
    $phase = if ($Live) { "live" } else { "preflight" }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $stepFlag = if ($Live) { @() } else { @("--dry-run") }
    return @(
        (New-CommandCase -Name "trigger-status" -Suite "trigger-list" -Phase $phase -Args (@("trigger-status") + $modeFlag + @("--json", "--resource", $resource, "--channel", "1", "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase $phase -Args (@("trigger-step") + $stepFlag + @("--json", "--resource", $resource, "--channel", "1", "--source", "bus", "--fire", "--wait-complete", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "trigger-list-bus" -Suite "trigger-list" -Phase $phase -Args (@("trigger-list") + $modeFlag + @("--json", "--resource", $resource, "--channel", "1", "--voltage-list", "0,0.5,1", "--current-list", "0.05,0.05,0.05", "--dwell-list", "0.01,0.01,0.01", "--source", "bus", "--fire", "--wait-complete", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "trigger-abort" -Suite "trigger-list" -Phase $phase -Args (@("trigger-abort") + $modeFlag + @("--json", "--resource", $resource, "--channel", "1", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live)
    )
}

function Get-SoftwareSequenceCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $SimResources[$Model] }
    $phase = if ($Live) { "live" } else { "preflight" }
    $readOnlySequence = New-ValidationSequenceFile -Name "sequence-readonly" -Lines @(
        "version: 1",
        "steps:",
        "  - action: readback",
        "    channel: 1",
        "  - action: output-state",
        "    channel: 1"
    )
    $outputSequence = New-ValidationSequenceFile -Name "sequence-output-low-power" -Lines @(
        "version: 1",
        "steps:",
        "  - action: set",
        "    channel: 1",
        "    voltage: 1",
        "    current: 0.05",
        "  - action: output-on",
        "    channel: 1",
        "  - action: wait",
        "    seconds: 0.1",
        "  - action: output-off",
        "    channel: 1"
    )
    $rampListArgs = @("--segment", "1", "0.05", "0", "1", "0.25", "100", "0")
    $cases = New-Object System.Collections.Generic.List[object]
    if ($Live) {
        $safeOffArgs = @("safe-off", "--json", "--resource", $resource, "--channel", "all", "--log-scpi")
        $cases.Add((New-CommandCase -Name "safe-off-before-software-sequence" -Suite "software-sequence" -Phase $phase -Args $safeOffArgs -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "ramp-list-live-low-power" -Suite "software-sequence" -Phase $phase -Args (@("ramp-list", "--json", "--resource", $resource) + $rampListArgs + @("--log-scpi")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "sequence-live-readonly" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--json", "--resource", $resource, "--file", $readOnlySequence, "--log-scpi") -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "sequence-live-output-low-power" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--json", "--resource", $resource, "--file", $outputSequence, "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "safe-off-after-software-sequence" -Suite "software-sequence" -Phase $phase -Args $safeOffArgs -StateChanging:$true -LiveHardwareExpected:$true))
    }
    else {
        $cases.Add((New-CommandCase -Name "ramp-list-lint" -Suite "software-sequence" -Phase $phase -Args (@("ramp-list", "--lint", "--json", "--model", $Model) + $rampListArgs)))
        $cases.Add((New-CommandCase -Name "ramp-list-dry-run" -Suite "software-sequence" -Phase $phase -Args (@("ramp-list", "--dry-run", "--json", "--model", $Model) + $rampListArgs)))
        $cases.Add((New-CommandCase -Name "sequence-lint-readonly" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--lint", "--json", "--model", $Model, "--resource", $resource, "--file", $readOnlySequence)))
        $cases.Add((New-CommandCase -Name "sequence-dry-run-readonly" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--dry-run", "--json", "--model", $Model, "--resource", $resource, "--file", $readOnlySequence)))
        if ($Model -in @("EDU36311A", "E3646A")) {
            $negativeCases = @(
                @{ Name = "sequence-unsupported-trigger"; Action = "trigger-list"; Expected = "trigger-list" },
                @{ Name = "sequence-unsupported-snapshot"; Action = "snapshot"; Expected = "snapshot" },
                @{ Name = "sequence-unsupported-restore"; Action = "restore-from-snapshot"; Expected = "restore" },
                @{ Name = "sequence-unsupported-native-list"; Action = "native-list"; Expected = "native-list" }
            )
            if ($Model -eq "E3646A") {
                $negativeCases += @(
                    @{ Name = "sequence-unsupported-protection"; Action = "protection-set"; Expected = "protection" },
                    @{ Name = "sequence-unsupported-completion-pulse"; Action = "trigger-pulse"; Expected = "trigger-pulse" }
                )
            }
            foreach ($negative in $negativeCases) {
                $badSequence = New-ValidationSequenceFile -Name $negative.Name -Lines @(
                    "version: 1",
                    "steps:",
                    ("  - action: " + $negative.Action),
                    "    channel: 1"
                )
                $cases.Add((New-CommandCase -Name ($negative.Name + "-dry-run") -Suite "software-sequence" -Phase $phase -Args @("sequence", "--dry-run", "--json", "--model", $Model, "--resource", $resource, "--file", $badSequence) -ExpectedSuccess:$false -ExpectedErrorContains $negative.Expected))
                $cases.Add((New-CommandCase -Name ($negative.Name + "-simulate") -Suite "software-sequence" -Phase $phase -Args @("sequence", "--simulate", "--json", "--model", $Model, "--resource", $resource, "--file", $badSequence) -ExpectedSuccess:$false -ExpectedErrorContains $negative.Expected))
            }
        }
    }
    return $cases.ToArray()
}

function Get-SuiteCases {
    param(
        [string]$Model,
        [string[]]$Suites,
        [bool]$Live
    )

    $cases = New-Object System.Collections.Generic.List[object]
    foreach ($suiteName in $Suites) {
        if ($suiteName -eq "readonly") {
            $cases.AddRange((Get-ReadOnlyCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "output") {
            $cases.AddRange((Get-OutputCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "protection") {
            $cases.AddRange((Get-ProtectionCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "snapshot") {
            $cases.AddRange((Get-SnapshotCases -Live:$Live))
        }
        elseif ($suiteName -eq "trigger-list") {
            $cases.AddRange((Get-TriggerListCases -Live:$Live))
        }
        elseif ($suiteName -eq "software-sequence") {
            $cases.AddRange((Get-SoftwareSequenceCases -Model $Model -Live:$Live))
        }
    }
    return $cases.ToArray()
}

function Invoke-ValidationCommand {
    param([Parameter(Mandatory = $true)]$Case)

    $artifactBaseName = Get-CaseArtifactBaseName -Case $Case
    $jsonPath = Join-Path $script:OutputDir ($artifactBaseName + ".json")
    $stdoutPath = Join-Path $script:OutputDir ($artifactBaseName + ".stdout.txt")
    $stderrPath = Join-Path $script:OutputDir ($artifactBaseName + ".stderr-scpi.txt")
    $argsWithBackend = if ($Case.phase -eq "live") { Add-BackendArgument -Arguments $Case.args } else { $Case.args }
    $hasSaveJson = $false
    foreach ($arg in $argsWithBackend) {
        if ($arg -eq "--save-json") {
            $hasSaveJson = $true
            break
        }
    }
    $allArgs = if ($hasSaveJson) { $argsWithBackend } else { @($argsWithBackend + @("--save-json", $jsonPath)) }
    $actualJsonPath = $jsonPath
    if ($hasSaveJson) {
        for ($index = 0; $index -lt $allArgs.Count; $index++) {
            if ($allArgs[$index] -eq "--save-json" -and $index + 1 -lt $allArgs.Count) {
                $actualJsonPath = $allArgs[$index + 1]
                break
            }
        }
    }
    if (Test-Path -LiteralPath $actualJsonPath) {
        Remove-Item -LiteralPath $actualJsonPath -Force
    }

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
    if (Test-Path -LiteralPath $actualJsonPath) {
        try {
            $payload = Get-Content -LiteralPath $actualJsonPath -Raw | ConvertFrom-Json
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
    $errorMessage = $null
    if ($null -ne $payload) {
        $ok = [bool]$payload.ok
        $hardwareTouched = [bool]$payload.execution.hardware_touched
        $mode = [string]$payload.execution.mode
        $dryRun = [bool]$payload.execution.dry_run
        if ($null -ne $payload.error) {
            $errorCode = [string]$payload.error.code
            $errorMessage = [string]$payload.error.message
        }
    }

    $casePassed = $true
    $failure = $null
    if ($null -ne $parseError) {
        $casePassed = $false
        $failure = "$($Case.name) did not produce parseable JSON: $parseError"
    }
    elseif ($Case.expected_success) {
        if ($exitCode -ne 0 -or $ok -ne $true) {
            $casePassed = $false
            $failure = "$($Case.name) failed unexpectedly with exit code $exitCode ($errorCode): $errorMessage"
        }
        elseif ($Case.phase -ne "live" -and $hardwareTouched -ne $false) {
            $casePassed = $false
            $failure = "$($Case.name) reported execution.hardware_touched=$hardwareTouched during no-hardware validation."
        }
        elseif ($Case.phase -eq "live" -and -not (Test-LiveExecutionMode -Mode $mode)) {
            $casePassed = $false
            $failure = "$($Case.name) reported execution.mode=$mode during live validation."
        }
        elseif ($Case.phase -eq "live" -and $Case.live_hardware_expected -and $hardwareTouched -ne $true) {
            $casePassed = $false
            $failure = "$($Case.name) reported execution.hardware_touched=$hardwareTouched during live validation."
        }
    }
    else {
        if ($exitCode -eq 0 -or $ok -ne $false) {
            $casePassed = $false
            $failure = "$($Case.name) was expected to fail, but it succeeded."
        }
        elseif (-not [string]::IsNullOrWhiteSpace($Case.expected_error_contains) -and ($errorMessage -notmatch [regex]::Escape($Case.expected_error_contains))) {
            $casePassed = $false
            $failure = "$($Case.name) failed, but not for the expected reason '$($Case.expected_error_contains)': $errorMessage"
        }
        elseif ($hardwareTouched -ne $false) {
            $casePassed = $false
            $failure = "$($Case.name) expected-failure path reported execution.hardware_touched=$hardwareTouched."
        }
    }

    $recordArgs = Protect-Arguments -Arguments $allArgs
    $formattedArgs = @("-m", "keysight_power_cli.cli") + $recordArgs
    $commandLine = (Format-CommandArgument -Argument $PythonExe) + " " + (($formattedArgs | ForEach-Object { Format-CommandArgument -Argument $_ }) -join " ")
    $record = [pscustomobject]@{
        name = $Case.name
        suite = $Case.suite
        phase = $Case.phase
        command_line = $commandLine
        arguments = $recordArgs
        exit_code = $exitCode
        ok = $ok
        mode = $mode
        dry_run = $dryRun
        hardware_touched = $hardwareTouched
        error_code = $errorCode
        parse_error = $parseError
        expected_success = $Case.expected_success
        result = if ($casePassed) { "passed" } else { "failed" }
        stdout_path = ConvertTo-RepoRelativePath -Path $stdoutPath
        stderr_path = ConvertTo-RepoRelativePath -Path $stderrPath
        stderr_scpi_path = ConvertTo-RepoRelativePath -Path $stderrPath
        json_path = ConvertTo-RepoRelativePath -Path $actualJsonPath
    }
    $script:CommandRecords.Add($record)
    if (-not $casePassed) {
        $script:Failures.Add($failure)
    }
    return $record
}

function Invoke-SafeOffCleanup {
    if (-not $Restore) {
        return
    }
    $cleanupCase = New-CommandCase -Name "safe-off-failure-cleanup" -Suite "cleanup" -Phase "live" -Args @("safe-off", "--json", "--resource", $script:RawResource, "--channel", "all", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true
    try {
        Invoke-ValidationCommand -Case $cleanupCase | Out-Null
    }
    catch {
        $script:Failures.Add("Failure cleanup threw: " + $_.Exception.Message)
    }
}

function Write-LiveConfirmationWarnings {
    param([Parameter(Mandatory = $true)][string[]]$SuitesToRun)

    if (@($SuitesToRun | Where-Object { $_ -in @("output", "protection", "trigger-list", "software-sequence") }).Count -gt 0) {
        Write-Host "Possible state changes:"
        $outputAffectingSuites = @(@("output", "trigger-list", "software-sequence") | Where-Object { $_ -in $SuitesToRun })
        if (@($outputAffectingSuites).Count -gt 0) {
            if (@($outputAffectingSuites).Count -eq 1) {
                $outputCaseText = "$($outputAffectingSuites[0]) cases"
            }
            elseif (@($outputAffectingSuites).Count -eq 2) {
                $outputCaseText = "$($outputAffectingSuites[0]) or $($outputAffectingSuites[1]) cases"
            }
            else {
                $outputCaseText = "$($outputAffectingSuites[0]), $($outputAffectingSuites[1]), or $($outputAffectingSuites[2]) cases"
            }
            Write-Host "- Low-power setpoints may be written: 1 V / 0.05 A."
            Write-Host "- Outputs may briefly turn on for $outputCaseText."
        }
        if ("protection" -in $SuitesToRun) {
            Write-Host "- Protection suite writes OVP/OCP settings and clears protection state."
        }
        Write-Host "- Safe-off cleanup may be attempted when Restore is true."
        if ("protection" -in $SuitesToRun) {
            Write-Host "- Cleanup does not restore original voltage/current/protection settings."
        }
        else {
            Write-Host "- Cleanup does not restore original voltage/current settings."
        }
    }
    else {
        Write-Host "This suite is non-output-affecting except for possible status/error queue reads."
    }
}

function Write-ValidationArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ValidationMode,
        [Parameter(Mandatory = $true)][string]$Result,
        [Parameter(Mandatory = $true)][datetime]$StartedAt
    )

    $completedAt = Get-Date
    $reportPath = Join-Path $script:OutputDir "report.json"
    $summaryPath = Join-Path $script:OutputDir "summary.md"
    $caseRecords = @($script:CommandRecords | ForEach-Object {
        [pscustomobject]@{
            name = $_.name
            suite = $_.suite
            phase = $_.phase
            expected_success = $_.expected_success
            result = $_.result
        }
    })
    $report = [pscustomobject]@{
        schema_version = "1.0"
        kind = "power_cli_live_validation"
        target = $script:NormalizedTarget
        connection = $script:ConnectionLabel
        suite = $Suite
        validation_mode = $ValidationMode
        plan_only = [bool]$PlanOnly
        live_executed = ($ValidationMode -eq "live")
        state_changing = $script:StateChanging
        resource = $script:ResourceDisplay
        backend = if ([string]::IsNullOrWhiteSpace($Backend)) { $null } else { $Backend }
        git_head = Get-GitHead
        package_version = Get-PackageVersion
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $completedAt.ToUniversalTime().ToString("o")
        result = $Result
        output_dir = ConvertTo-RepoRelativePath -Path $script:OutputDir
        preflight_report = ConvertTo-RepoRelativePath -Path $reportPath
        suites = $script:SuitesToRun
        cases = $caseRecords
        commands = $script:CommandRecords.ToArray()
        failures = $script:Failures.ToArray()
    }
    Write-Utf8NoBomFile -LiteralPath $reportPath -Value @($report | ConvertTo-Json -Depth 30)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# Power CLI Live Validation")
    $lines.Add("")
    $lines.Add("Target: ``" + $script:NormalizedTarget + "``")
    $lines.Add("Connection: ``" + $script:ConnectionLabel + "``")
    $lines.Add("Suite: ``" + $Suite + "``")
    $lines.Add("Suites run: ``" + ($script:SuitesToRun -join ", ") + "``")
    $lines.Add("Result: ``" + $Result + "``")
    $lines.Add("PlanOnly: ``" + [bool]$PlanOnly + "``")
    $lines.Add("Live executed: ``" + ($ValidationMode -eq "live") + "``")
    $lines.Add("Output directory: ``" + (ConvertTo-RepoRelativePath -Path $script:OutputDir) + "``")
    $lines.Add("Resource: ``" + $script:ResourceDisplay + "``")
    $lines.Add("")
    $lines.Add("## Safety Notes")
    $lines.Add("- This suite validates only the selected model, connection, suite, and command cases.")
    $lines.Add("- It does not validate untested features or other connections.")
    if ($script:StateChanging) {
        $lines.Add("- State-changing live cases use low-power 1 V / 0.05 A settings.")
        $lines.Add("- Safe-off cleanup does not restore original voltage/current/protection settings.")
    }
    else {
        $lines.Add("- The selected suite is non-output-affecting except for possible status/error queue reads.")
    }
    if ($script:NormalizedTarget -eq "E3646A") {
        $lines.Add("- E3646A OUTP ON/OFF is global, not an independent per-channel relay behavior.")
        $lines.Add("- E3646A ramp-list and sequence are software workflows, not native LIST.")
    }
    $lines.Add("")
    $lines.Add("## Physical Checks")
    $lines.Add("- Confirm the expected instrument and explicit VISA resource.")
    $lines.Add("- Confirm no DUT is connected, or only a known safe load, before state-changing suites.")
    $lines.Add("- Confirm output indicators are off before output-affecting suites.")
    $lines.Add("- Confirm no OVP/OCP/error/protection abnormal indicators are shown.")
    $lines.Add("")
    $lines.Add("## Case Table")
    $lines.Add("| Case | Suite | Phase | Expected success | Result |")
    $lines.Add("| --- | --- | --- | --- | --- |")
    foreach ($caseRecord in $caseRecords) {
        $lines.Add("| ``" + $caseRecord.name + "`` | ``" + $caseRecord.suite + "`` | ``" + $caseRecord.phase + "`` | ``" + $caseRecord.expected_success + "`` | ``" + $caseRecord.result + "`` |")
    }
    $lines.Add("")
    $lines.Add("## Command Table")
    $lines.Add("| Command | Exit | ok | mode | dry_run | hardware_touched | JSON | SCPI/stderr |")
    $lines.Add("| --- | ---: | --- | --- | --- | --- | --- | --- |")
    foreach ($command in $script:CommandRecords) {
        $lines.Add("| ``" + $command.name + "`` | " + $command.exit_code + " | " + $command.ok + " | " + $command.mode + " | " + $command.dry_run + " | " + $command.hardware_touched + " | ``" + $command.json_path + "`` | ``" + $command.stderr_scpi_path + "`` |")
    }
    if ($script:Failures.Count -gt 0) {
        $lines.Add("")
        $lines.Add("## Failures")
        foreach ($failure in $script:Failures) {
            $lines.Add("- " + $failure)
        }
    }
    Write-Utf8NoBomFile -LiteralPath $summaryPath -Value $lines
}

if ($env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY -eq "1") {
    return
}

$NormalizedTarget = Resolve-Target -Value $Target
$ConnectionLabel = Resolve-Connection -Value $Connection
if ([string]::IsNullOrWhiteSpace($Resource)) {
    Fail-Validation "Missing required -Resource. Pass the exact VISA resource explicitly; this script never scans or guesses a live resource."
}
if ($NormalizedTarget -eq "E3646A" -and $ConnectionLabel -ne "ASRL") {
    Fail-Validation "E3646A live validation currently requires an explicit ASRL/RS-232/serial connection."
}

$script:NormalizedTarget = $NormalizedTarget
$script:ConnectionLabel = $ConnectionLabel
$script:RawResource = $Resource
$script:ResourceDisplay = "$ConnectionLabel`:<redacted-resource>"
$script:BackendValue = $Backend

$supportedSuites = Get-SupportedSuites -Model $NormalizedTarget
if ($Suite -eq "full") {
    $SuitesToRun = $supportedSuites
}
else {
    if ($Suite -notin $supportedSuites) {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $OutputDir = Join-Path (Join-Path $TmpRoot "live_cli_check") ($timestamp + "_" + $NormalizedTarget + "_" + $ConnectionLabel + "_" + $Suite)
        $script:OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
        $script:SuitesToRun = @($Suite)
        $script:StateChanging = $false
        $script:CommandRecords = New-Object System.Collections.Generic.List[object]
        $script:Failures = New-Object System.Collections.Generic.List[string]
        $script:Failures.Add("Unsupported suite '$Suite' for target $NormalizedTarget. Supported suites: $($supportedSuites -join ', ').")
        Write-ValidationArtifacts -ValidationMode "failed" -Result "failed" -StartedAt (Get-Date)
        Fail-Validation "Unsupported suite '$Suite' for target $NormalizedTarget. Supported suites: $($supportedSuites -join ', ')."
    }
    $SuitesToRun = @($Suite)
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputDir = Join-Path (Join-Path $TmpRoot "live_cli_check") ($timestamp + "_" + $NormalizedTarget + "_" + $ConnectionLabel + "_" + $Suite)
$script:OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
$script:SuitesToRun = @($SuitesToRun)
$script:StateChanging = @($SuitesToRun | Where-Object { $_ -in @("output", "protection", "trigger-list", "software-sequence") }).Count -gt 0
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$startedAt = Get-Date

Write-Host "Running no-hardware preflight for $NormalizedTarget suite '$Suite'..."
$preflightCases = Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$false
foreach ($case in $preflightCases) {
    Invoke-ValidationCommand -Case $case | Out-Null
}

if ($script:Failures.Count -gt 0) {
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "Preflight failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:OutputDir 'report.json'))."
    exit 1
}

if ($PlanOnly) {
    Write-ValidationArtifacts -ValidationMode "planned" -Result "planned" -StartedAt $startedAt
    Write-Host "Plan-only validation passed."
    Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:OutputDir 'report.json'))"
    Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:OutputDir 'summary.md'))"
    exit 0
}

if ([Console]::IsInputRedirected) {
    $script:Failures.Add("Interactive confirmation is required before opening VISA; stdin is redirected.")
    Write-ValidationArtifacts -ValidationMode "confirmation_required" -Result "confirmation_required" -StartedAt $startedAt
    Write-Error "Interactive confirmation is required before live execution. Re-run from an interactive PowerShell session, or use -PlanOnly."
    exit 2
}

Write-Host ""
Write-Host "Live suite validation is ready to open VISA and send SCPI."
Write-Host "Target: $NormalizedTarget"
Write-Host "Connection: $ConnectionLabel"
Write-Host "Resource: $Resource"
if (-not [string]::IsNullOrWhiteSpace($Backend)) {
    Write-Host "Backend: $Backend"
}
Write-Host "Suites: $($SuitesToRun -join ', ')"
Write-Host ""
Write-LiveConfirmationWarnings -SuitesToRun $SuitesToRun
if ($NormalizedTarget -eq "E3646A") {
    Write-Host "- E3646A OUTP ON/OFF is global, not independent per-channel relay behavior."
    Write-Host "- E3646A ramp-list and sequence are software workflows, not native LIST."
}
Write-Host ""
Write-Host "Physical checks before pressing Enter:"
Write-Host "- Confirm this is the target $NormalizedTarget and the explicit $ConnectionLabel resource is expected."
Write-Host "- Confirm no DUT is connected, or only known safe loads, for state-changing suites."
Write-Host "- Confirm output indicators are currently OFF before state-changing suites."
Write-Host "- Confirm no OVP/OCP/error/protection abnormal indicators are shown."
Write-Host ""
Read-Host "Press Enter to run live suite validation, or press Ctrl+C to abort"

$liveCases = Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$true
foreach ($case in $liveCases) {
    Invoke-ValidationCommand -Case $case | Out-Null
    if ($script:Failures.Count -gt 0 -and $script:StateChanging) {
        Invoke-SafeOffCleanup
        break
    }
}

if ($script:Failures.Count -gt 0) {
    Write-ValidationArtifacts -ValidationMode "live" -Result "failed" -StartedAt $startedAt
    Write-Error "Live validation failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:OutputDir 'report.json'))."
    exit 1
}

Write-ValidationArtifacts -ValidationMode "live" -Result "passed" -StartedAt $startedAt
Write-Host "Live validation passed."
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:OutputDir 'report.json'))"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:OutputDir 'summary.md'))"
