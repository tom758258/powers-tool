Set-StrictMode -Version Latest

$script:ValidationTargetProfiles = [ordered]@{
    "keysight-e36312a" = [pscustomobject]@{
        model_id = "keysight-e36312a"
        vendor_id = "keysight"
        model = "E36312A"
        model_name = "E36312A"
        channels = @(1, 2, 3)
        simulator_resource = "USB0::SIM::E36312A::INSTR"
        suites = @("readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence")
    }
    "keysight-edu36311a" = [pscustomobject]@{
        model_id = "keysight-edu36311a"
        vendor_id = "keysight"
        model = "EDU36311A"
        model_name = "EDU36311A"
        channels = @(1, 2, 3)
        simulator_resource = "USB0::SIM::EDU36311A::INSTR"
        suites = @("readonly", "output", "protection", "software-sequence")
    }
    "keysight-e3646a" = [pscustomobject]@{
        model_id = "keysight-e3646a"
        vendor_id = "keysight"
        model = "E3646A"
        model_name = "E3646A"
        channels = @(1, 2)
        simulator_resource = "ASRL1::SIM::E3646A::INSTR"
        suites = @("readonly", "output", "software-sequence")
    }
}

function Get-ValidationTargetProfiles {
    $seen = @{}
    foreach ($profile in $script:ValidationTargetProfiles.Values) {
        if ([string]::IsNullOrWhiteSpace([string]$profile.model_id)) {
            throw "Validation target model_id must not be empty."
        }
        if ($profile.model_id -cne $profile.model_id.ToLowerInvariant()) {
            throw "Validation target model_id must be lowercase: '$($profile.model_id)'."
        }
        if ($seen.ContainsKey($profile.model_id)) {
            throw "Duplicate validation target model_id '$($profile.model_id)'."
        }
        $seen[$profile.model_id] = $true
    }
    return @($script:ValidationTargetProfiles.Values)
}

function Get-SupportedTargetModelIds {
    return @(Get-ValidationTargetProfiles | ForEach-Object { $_.model_id })
}

function Resolve-ValidationTargets {
    param([AllowNull()][AllowEmptyString()][string]$Target = "all")

    if ([string]::IsNullOrWhiteSpace($Target)) {
        $Target = "all"
    }
    $normalized = $Target.Trim().ToLowerInvariant()
    if ($normalized -eq "all") {
        return @(Get-SupportedTargetModelIds)
    }
    $supported = @(Get-SupportedTargetModelIds)
    if ($normalized -notin $supported) {
        throw "Unsupported target '$Target'. Use all or one of: $($supported -join ', ')."
    }
    return @($normalized)
}

function Resolve-ValidationTarget {
    param([AllowNull()][AllowEmptyString()][string]$Target)

    $targets = @(Resolve-ValidationTargets -Target $Target)
    if ($targets.Count -ne 1) {
        throw "A single canonical target is required."
    }
    return $targets[0]
}

function Get-ValidationTargetProfile {
    param([Parameter(Mandatory = $true)][string]$Target)

    $resolved = Resolve-ValidationTarget -Target $Target
    return $script:ValidationTargetProfiles[$resolved]
}

function Get-ValidationSupportedSuites {
    param([Parameter(Mandatory = $true)][string]$Target)
    return @((Get-ValidationTargetProfile -Target $Target).suites)
}

function New-PreflightCommandCase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Category,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateSet("dry-run", "simulate")][string]$Mode,
        [string]$ExpectedPath,
        [AllowNull()]$ExpectedValue
    )
    return [pscustomobject]@{
        name = $Name
        category = $Category
        command = $Command
        arguments = $Arguments
        mode = $Mode
        expected_path = $ExpectedPath
        expected_value = $ExpectedValue
    }
}

function Get-ValidationPreflightCases {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$ArtifactDirectory,
        [Parameter(Mandatory = $true)][string]$SequencePath
    )

    $profile = Get-ValidationTargetProfile -Target $Target
    $model = $profile.model_id
    $resource = $profile.simulator_resource
    $cases = [System.Collections.Generic.List[object]]::new()
    $cases.Add((New-PreflightCommandCase -Name "list-resources-simulate" -Category "resource-planning" -Command "list-resources" -Arguments @("list-resources", "--simulate", "--json") -Mode "simulate" -ExpectedPath "data.count" -ExpectedValue 3))
    $cases.Add((New-PreflightCommandCase -Name "identify-simulate" -Category "identity" -Command "identify" -Arguments @("identify", "--simulate", "--json", "--resource", $resource) -Mode "simulate" -ExpectedPath "data.idn.model" -ExpectedValue $profile.model))
    $cases.Add((New-PreflightCommandCase -Name "verify-simulate" -Category "identity" -Command "verify" -Arguments @("verify", "--simulate", "--json", "--resource", $resource) -Mode "simulate"))
    $cases.Add((New-PreflightCommandCase -Name "capabilities-simulate" -Category "metadata" -Command "capabilities" -Arguments @("capabilities", "--simulate", "--json", "--resource", $resource) -Mode "simulate" -ExpectedPath "data.resource.model_id" -ExpectedValue $model))
    $cases.Add((New-PreflightCommandCase -Name "measure-ch1-simulate" -Category "readonly" -Command "measure" -Arguments @("measure", "--simulate", "--json", "--resource", $resource, "--channel", "1") -Mode "simulate"))
    $cases.Add((New-PreflightCommandCase -Name "readback-simulate" -Category "readonly" -Command "readback" -Arguments @("readback", "--simulate", "--json", "--resource", $resource, "--all") -Mode "simulate"))
    $cases.Add((New-PreflightCommandCase -Name "error-simulate" -Category "diagnostics" -Command "error" -Arguments @("error", "--simulate", "--json", "--resource", $resource, "--max-reads", "2") -Mode "simulate" -ExpectedPath "data.read_count" -ExpectedValue 1))
    $cases.Add((New-PreflightCommandCase -Name "set-dry-run" -Category "output" -Command "set" -Arguments @("set", "--dry-run", "--json", "--model", $model, "--channel", "1", "--voltage", "1", "--current", "0.05") -Mode "dry-run" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
    $cases.Add((New-PreflightCommandCase -Name "safe-off-dry-run" -Category "safe-off" -Command "safe-off" -Arguments @("safe-off", "--dry-run", "--json", "--model", $model, "--channel", "all") -Mode "dry-run" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
    $cases.Add((New-PreflightCommandCase -Name "ramp-list-dry-run" -Category "software-sequence" -Command "ramp-list" -Arguments @("ramp-list", "--dry-run", "--json", "--model", $model, "--segment", "1", "0.05", "0", "1", "0.25", "100", "0") -Mode "dry-run"))
    $cases.Add((New-PreflightCommandCase -Name "sequence-dry-run" -Category "software-sequence" -Command "sequence" -Arguments @("sequence", "--dry-run", "--json", "--model", $model, "--resource", $resource, "--file", $SequencePath) -Mode "dry-run"))

    if ("protection" -in $profile.suites) {
        $cases.Add((New-PreflightCommandCase -Name "protection-status-simulate" -Category "protection" -Command "protection-status" -Arguments @("protection-status", "--simulate", "--json", "--resource", $resource, "--all") -Mode "simulate"))
        $cases.Add((New-PreflightCommandCase -Name "protection-set-dry-run" -Category "protection" -Command "protection-set" -Arguments @("protection-set", "--dry-run", "--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "5", "--ocp", "on", "--confirm") -Mode "dry-run"))
    }
    if ("snapshot" -in $profile.suites) {
        $snapshotPath = Join-Path $ArtifactDirectory "snapshot.json"
        $cases.Add((New-PreflightCommandCase -Name "snapshot-simulate" -Category "snapshot" -Command "snapshot" -Arguments @("snapshot", "--simulate", "--json", "--resource", $resource, "--snapshot-json", $snapshotPath) -Mode "simulate"))
    }
    if ("trigger-list" -in $profile.suites) {
        $cases.Add((New-PreflightCommandCase -Name "trigger-status-simulate" -Category "trigger-list" -Command "trigger-status" -Arguments @("trigger-status", "--simulate", "--json", "--resource", $resource, "--channel", "1") -Mode "simulate"))
        $cases.Add((New-PreflightCommandCase -Name "trigger-step-dry-run" -Category "trigger-list" -Command "trigger-step" -Arguments @("trigger-step", "--dry-run", "--json", "--model", $model, "--channel", "1", "--source", "bus", "--fire") -Mode "dry-run"))
    }
    return $cases.ToArray()
}
