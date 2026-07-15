param(
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

$PolicyGatedCommands = @(
    "measure", "measure-all", "output-state", "read-status", "validate-readonly", "readback",
    "protection-status", "protection-set", "clear-protection", "snapshot", "restore-from-snapshot",
    "log", "doctor", "capabilities", "set", "apply", "output-on", "output-off", "safe-off",
    "cycle-output", "ramp", "ramp-list", "smoke-output", "sequence", "trigger-pulse",
    "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort"
)
$ExemptLiveDiagnosticCommands = @("list-resources", "verify", "identify", "error", "clear")
$IdentityBearingExpectedModelCommands = @("verify", "identify")
$ModelAwareExpectedModelCommands = @(
    "set", "output-on", "output-off", "safe-off", "output-state", "cycle-output", "apply",
    "ramp", "smoke-output", "trigger-pulse", "trigger-status", "trigger-step", "trigger-list",
    "trigger-fire", "trigger-abort", "protection-set", "clear-protection", "snapshot",
    "restore-from-snapshot", "sequence", "ramp-list", "measure-all", "log", "doctor"
)
$RawDiagnosticCommands = @("error", "clear")
$NoPhysicalIdentityCommands = @("list-resources")
$IdnSelectedCommandsWithoutExplicitModelGuard = @(
    "measure", "read-status", "validate-readonly", "readback", "protection-status", "capabilities"
)
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
. (Join-Path $PSScriptRoot "_validation_helpers.ps1")
$TargetMetadata = $script:ValidationTargetProfiles
$SupportedTargets = @(Get-SupportedTargetModelIds)
$PreflightScript = Join-Path $PSScriptRoot "preflight-cli.ps1"
$PythonExe = Join-Path (Join-Path $RepoRoot ".venv") "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}
$CliExecutable = if ($PythonExe -eq "python") { "powers-tool" } else { Join-Path (Split-Path -Parent $PythonExe) "powers-tool.exe" }
if ($PythonExe -ne "python" -and -not (Test-Path -LiteralPath $CliExecutable)) {
    $CliExecutable = "powers-tool"
}
$CliPrefix = @()

function Get-ValidationChildPythonPath {
    $parts = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHONPATH)) { $parts.Add($env:PYTHONPATH) }
    $parts.Add((Join-Path $RepoRoot "src"))
    return ($parts -join [System.IO.Path]::PathSeparator)
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
    return "<redacted-path>"
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
        return "<redacted>"
    }
    if ([System.IO.Path]::IsPathRooted($Argument)) {
        $fullArgument = [System.IO.Path]::GetFullPath($Argument)
        if (-not [string]::IsNullOrWhiteSpace($script:PrivateArtifactDir)) {
            $privateRoot = [System.IO.Path]::GetFullPath($script:PrivateArtifactDir).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )
            if ($fullArgument.Equals($privateRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
                $fullArgument.StartsWith($privateRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                return "<private-local-path>"
            }
        }
        $fullRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        if ($fullArgument.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            return ConvertTo-RepoRelativePath -Path $fullArgument
        }
        return "<redacted-path>"
    }
    return $Argument
}

function Get-ShareablePythonCommand {
    if ($PythonExe -eq "python") {
        return "python"
    }
    return ".venv\\Scripts\\python.exe"
}

function Get-ShareableCliCommand {
    return "powers-tool"
}

function Add-SensitiveValue {
    param([AllowNull()][string]$Value)

    if (-not [string]::IsNullOrWhiteSpace($Value) -and -not ($script:SensitiveValues -contains $Value)) {
        $script:SensitiveValues.Add($Value)
    }
}

function Get-FreeFormIdnPattern {
    return '(?i)\b[A-Z][A-Z0-9 .&_-]{1,63}\s*,\s*[A-Z0-9][A-Z0-9._/-]{1,31}\s*,\s*([^,\r\n]{1,64})\s*,\s*[A-Z0-9][A-Z0-9._/-]{0,31}'
}

function Test-DistinctiveSensitiveToken {
    param([AllowNull()][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    $trimmed = $Value.Trim()
    return $trimmed.Length -ge 4 -and $trimmed -notmatch '^0+$'
}

function Add-SerialSensitiveValue {
    param([AllowNull()][string]$Value)

    if (Test-DistinctiveSensitiveToken -Value $Value) {
        Add-SensitiveValue -Value $Value.Trim()
    }
}

function Add-SensitiveValuesFromText {
    param([AllowNull()][string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return
    }
    $idnPattern = Get-FreeFormIdnPattern
    foreach ($match in [regex]::Matches($Text, $idnPattern)) {
        Add-SerialSensitiveValue -Value $match.Groups[1].Value
    }
}

function Protect-ShareableText {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) {
        return $null
    }
    $redacted = [string]$Text
    Add-SensitiveValuesFromText -Text $redacted
    if (-not [string]::IsNullOrWhiteSpace($script:RawResource)) {
        $redacted = $redacted -replace [regex]::Escape($script:RawResource), $script:ResourceDisplay
    }
    # Protect VISA resources that appear in nested simulator/resource-manager diagnostics too.
    $redacted = $redacted -replace '(?i)\b(?:USB|TCPIP|ASRL|GPIB|PXI|VXI|SOCKET)\d*::[^\s"''<>|]+', "<redacted>"
    $idnPattern = Get-FreeFormIdnPattern
    $redacted = [regex]::Replace($redacted, $idnPattern, { param($match) "<redacted-idn>" })
    foreach ($value in @($script:SensitiveValues)) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $redacted = $redacted -replace [regex]::Escape($value), "<redacted>"
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) {
        $redacted = $redacted -replace [regex]::Escape($RepoRoot), "<repository-root>"
    }
    if ($PythonExe -ne "python") {
        $redacted = $redacted -replace [regex]::Escape($PythonExe), (Get-ShareablePythonCommand)
    }
    $redacted = $redacted -replace '(?i)\b(?:10(?:\.\d{1,3}){3}|127(?:\.\d{1,3}){3}|169\.254(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})\b', "<redacted-ip>"
    $redacted = $redacted -replace '(?i)[a-z]:(?:\\\\|\\)[^\r\n"''<>|?*]+', "<redacted-path>"
    $redacted = $redacted -replace '(?<![A-Za-z0-9_])/(?:home|users|mnt|tmp)/[^\r\n"''<>|]+', "<redacted-path>"
    return $redacted
}

function Test-ShareableSensitiveField {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()][string]$ParentName
    )

    $normalized = $Name.Trim().ToLowerInvariant() -replace '-', '_'
    if ($normalized -in @("json_path", "stdout_path", "stderr_path", "stderr_scpi_path", "output_dir", "shareable_artifact_dir", "preflight_report")) {
        return $false
    }
    if ($normalized -in @("resource", "resource_alias", "visa_resource", "resource_name", "serial", "serial_number")) {
        return $true
    }
    if ($normalized -match '(?:^|_)(?:path|file|filename)$') {
        return $true
    }
    return ($normalized -eq "raw" -and $ParentName -eq "idn")
}

function ConvertTo-ShareableJsonValue {
    param(
        [AllowNull()]$Value,
        [AllowNull()][string]$FieldName,
        [AllowNull()][string]$ParentName
    )

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [string]) {
        $safeStructuralField = ([string]$FieldName).Trim().ToLowerInvariant()
        if ($safeStructuralField -in @("name", "command", "suite", "phase", "validation_kind", "cleanup_role")) {
            if ($Value -match '(?i)\b(?:USB|TCPIP|ASRL|GPIB|PXI|VXI|SOCKET)\d*::[^\s"''<>|]+') {
                return "<redacted>"
            }
            return $Value
        }
        if (Test-ShareableSensitiveField -Name ([string]$FieldName) -ParentName $ParentName) {
            $normalized = ([string]$FieldName).Trim().ToLowerInvariant() -replace '-', '_'
            if ($normalized -in @("resource", "resource_alias", "visa_resource", "resource_name")) {
                return $script:ResourceDisplay
            }
            if ($normalized -eq "raw" -and $ParentName -eq "idn") {
                return "<redacted-idn>"
            }
            if ($normalized -match '(?:^|_)(?:path|file|filename)$') {
                return "<redacted-path>"
            }
            return "<redacted>"
        }
        return Protect-ShareableText -Text $Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $result[[string]$key] = ConvertTo-ShareableJsonValue -Value $Value[$key] -FieldName ([string]$key) -ParentName $FieldName
        }
        return [pscustomobject]$result
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = New-Object System.Collections.Generic.List[object]
        foreach ($item in $Value) {
            $items.Add((ConvertTo-ShareableJsonValue -Value $item -FieldName $FieldName -ParentName $ParentName))
        }
        return ,($items.ToArray())
    }
    if ($Value -is [psobject] -and @($Value.PSObject.Properties).Count -gt 0) {
        $result = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $result[$property.Name] = ConvertTo-ShareableJsonValue -Value $property.Value -FieldName $property.Name -ParentName $FieldName
        }
        return [pscustomobject]$result
    }
    return $Value
}

function Ensure-ArtifactDirectories {
    if ([string]::IsNullOrWhiteSpace($script:OutputDir)) {
        throw "Output directory is not configured."
    }
    $script:PrivateArtifactDir = Join-Path $script:OutputDir "private"
    $script:ShareableArtifactDir = Join-Path $script:OutputDir "shareable"
    New-Item -ItemType Directory -Path $script:PrivateArtifactDir -Force | Out-Null
    New-Item -ItemType Directory -Path $script:ShareableArtifactDir -Force | Out-Null
}

function Write-ShareableTextArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$PrivatePath,
        [Parameter(Mandatory = $true)][string]$ShareablePath
    )

    $text = if (Test-Path -LiteralPath $PrivatePath) { Get-Content -LiteralPath $PrivatePath -Raw } else { "" }
    Write-Utf8NoBomFile -LiteralPath $ShareablePath -Value @((Protect-ShareableText -Text $text))
}

function Write-ShareableJsonArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$PrivatePath,
        [Parameter(Mandatory = $true)][string]$ShareablePath,
        [AllowNull()]$Payload,
        [Parameter(Mandatory = $true)][ValidateSet("parsed", "missing", "failed")][string]$ParseStatus
    )

    if ($null -ne $Payload) {
        $shareablePayload = ConvertTo-ShareableJsonValue -Value $Payload -FieldName $null -ParentName $null
        Write-Utf8NoBomFile -LiteralPath $ShareablePath -Value @($shareablePayload | ConvertTo-Json -Depth 30)
        return
    }
    $placeholder = [pscustomobject]@{
        artifact_available = $false
        artifact_kind = "command_json"
        parse_status = $ParseStatus
        parse_error = if ($ParseStatus -eq "missing") { "JSON output file was not created." } else { "Could not parse command JSON." }
        private_raw_artifact_retained = (Test-Path -LiteralPath $PrivatePath)
    }
    Write-Utf8NoBomFile -LiteralPath $ShareablePath -Value @($placeholder | ConvertTo-Json -Depth 10)
}

function Protect-Arguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return @($Arguments | ForEach-Object { Protect-Argument -Argument $_ })
}

function Get-GitHead {
    try {
        $head = & git -C $RepoRoot rev-parse HEAD 2>$null
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
        Fail-Validation "Missing required -Target. Supported canonical model IDs: $($SupportedTargets -join ', '). generic-scpi is no-hardware planning only."
    }
    if ($Value -notin $SupportedTargets) {
        Fail-Validation "Unsupported -Target '$Value'. Use one canonical model_id: $($SupportedTargets -join ', ')."
    }
    return $Value
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

    if ($TargetMetadata.Contains($Model)) {
        return @($TargetMetadata[$Model].channels)
    }
    Fail-Validation "Unsupported -Target '$Model'. Supported targets: $($SupportedTargets -join ', ')."
}

function Get-SupportedSuites {
    param([string]$Model)

    if ($TargetMetadata.Contains($Model)) {
        return @($TargetMetadata[$Model].suites)
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
        [bool]$LiveHardwareExpected = $false,
        [string]$CleanupRole,
        [string]$ValidationKind,
        [int[]]$ExpectedChannels = @(),
        [AllowNull()]$ExpectedOutputEnabled = $null,
        [string[]]$GeneratedArtifacts = @(),
        [string[]]$CompareSnapshotPaths = @(),
        [bool]$CandidateContextRequired = $false
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
        cleanup_role = $CleanupRole
        validation_kind = $ValidationKind
        expected_channels = @($ExpectedChannels)
        expected_output_enabled = $ExpectedOutputEnabled
        generated_artifacts = @($GeneratedArtifacts)
        compare_snapshot_paths = @($CompareSnapshotPaths)
        candidate_context_required = $CandidateContextRequired
    }
}

function Test-CurrentConnectionUsesCandidateCapabilities {
    return $script:BackendArtifact.backend_scope -eq "system_visa"
}

function Load-CoreCandidateInventory {
    $code = "import json; from powers_tool_core.support_policy import internal_validation_candidate_inventory as inventory; data=inventory(); print(json.dumps({model: {'commands': list(entry['commands']), 'connections': [list(value) for value in entry['connections']]} for model, entry in data.items()}))"
    $hadPythonPath = $null -ne [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", (Get-ValidationChildPythonPath), "Process")
        $inventoryJson = & $PythonExe -c $code
    }
    finally {
        if ($hadPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process") }
        else { [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process") }
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($inventoryJson -join ""))) {
        throw "Core validation candidate inventory could not be loaded."
    }
    try { $script:CandidateInventory = ($inventoryJson -join "`n") | ConvertFrom-Json }
    catch { throw "Core validation candidate inventory is malformed." }
}

function Get-BaseValidationCommandArguments {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][string]$JsonPath
    )

    $arguments = Add-LiveExpectedModelArgument -Case $Case
    $arguments = Add-ValidationSupportPolicyArgument -Arguments $arguments
    if ($Case.phase -eq "live") {
        $arguments = Add-BackendArgument -Arguments $arguments
    }
    if ($arguments -notcontains "--save-json") {
        $arguments = @($arguments + @("--save-json", $JsonPath))
    }
    return $arguments
}

function Add-BackendArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if (-not [string]::IsNullOrWhiteSpace($script:BackendValue)) {
        return @($Arguments + @("--backend", $script:BackendValue))
    }
    return $Arguments
}

function Add-ValidationSupportPolicyArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if ($Arguments.Count -eq 0) {
        return $Arguments
    }
    $command = $Arguments[0].Trim().ToLowerInvariant()
    if ($command -in $script:ExemptLiveDiagnosticCommands -or $command -notin $script:PolicyGatedCommands) {
        return $Arguments
    }
    if ($Arguments -contains "--validation-allow-pending-live-support") {
        return $Arguments
    }
    return @($Arguments + "--validation-allow-pending-live-support")
}

function Get-LiveCommandIdentityContract {
    param([Parameter(Mandatory = $true)][string]$Command)

    $normalized = $Command.Trim().ToLowerInvariant()
    if ($normalized -in $script:IdentityBearingExpectedModelCommands) {
        return "identity_expected_model"
    }
    if ($normalized -in $script:ModelAwareExpectedModelCommands) {
        return "model_aware_expected_model"
    }
    if ($normalized -in $script:RawDiagnosticCommands) {
        return "raw_diagnostic"
    }
    if ($normalized -in $script:NoPhysicalIdentityCommands) {
        return "no_physical_identity"
    }
    if ($normalized -in $script:IdnSelectedCommandsWithoutExplicitModelGuard) {
        return "idn_selected_without_explicit_guard"
    }
    return "unclassified"
}

function Add-LiveExpectedModelArgument {
    param([Parameter(Mandatory = $true)]$Case)

    if ($Case.phase -ne "live" -or $Case.args.Count -eq 0) {
        return $Case.args
    }
    $contract = Get-LiveCommandIdentityContract -Command $Case.args[0]
    if ($contract -in @("identity_expected_model", "model_aware_expected_model")) {
        if ($Case.args -contains "--model") {
            return $Case.args
        }
        return @($Case.args + @("--model", $script:NormalizedTarget))
    }
    if ($Case.args -contains "--model") {
        throw "$($Case.args[0]) does not accept a live expected-model argument."
    }
    return $Case.args
}

function Get-ValidationCommandArguments {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][string]$JsonPath
    )

    $arguments = @(Get-BaseValidationCommandArguments -Case $Case -JsonPath $JsonPath)
    return $arguments
}

function Get-TransportScope {
    param([Parameter(Mandatory = $true)][string]$Connection)

    switch ($Connection) {
        "USB" { return "usb" }
        "LAN" { return "tcpip" }
        "ASRL" { return "asrl" }
        default { throw "Unsupported validation connection '$Connection'." }
    }
}

function Get-BackendArtifactFields {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return [pscustomobject]@{
            backend = "system_visa"
            backend_scope = "system_visa"
            backend_argument = $null
        }
    }
    if ($Value.Trim().ToLowerInvariant() -eq "@py") {
        return [pscustomobject]@{
            backend = $Value
            backend_scope = "pyvisa_py"
            backend_argument = $Value
        }
    }
    return [pscustomobject]@{
        backend = $Value
        backend_scope = "custom_visa"
        backend_argument = $Value
    }
}

function Get-PropertyValue {
    param(
        [AllowNull()]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function New-CleanupEvidence {
    param([Parameter(Mandatory = $true)][string]$ValidationMode)

    $stateChanging = [bool]$script:StateChanging
    $requested = [bool]($stateChanging -and $Restore)
    $status = if ($ValidationMode -eq "planned") {
        "not_executed_plan_only"
    }
    elseif ($ValidationMode -eq "preflight_failed") {
        "not_executed_preflight_failed"
    }
    elseif ($ValidationMode -eq "confirmation_required") {
        "not_executed_confirmation_required"
    }
    elseif (-not $stateChanging) {
        "not_required"
    }
    elseif ($requested) {
        "pending"
    }
    else {
        "skipped_by_operator"
    }
    return [pscustomobject]@{
        requested = $requested
        attempted = $false
        safe_off_command = $null
        safe_off_exit_code = $null
        safe_off_ok = $null
        output_state_checked = $false
        all_outputs_off = $null
        error_queue_checked = $false
        instrument_errors = $null
        status = $status
    }
}

function New-ValidationSequenceFile {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )

    Ensure-ArtifactDirectories
    $path = Join-Path $script:PrivateArtifactDir ($Name + ".yaml")
    Write-Utf8NoBomFile -LiteralPath $path -Value $Lines
    return $path
}

function New-ValidationSnapshotFile {
    Ensure-ArtifactDirectories
    $path = Join-Path $script:PrivateArtifactDir "generated-e36312a-snapshot.json"
    $snapshot = [pscustomobject]@{
        schema_version = 2
        kind = "powers-tool-snapshot"
        resource = $TargetMetadata["keysight-e36312a"].simulator_resource
        reported_identity = [pscustomobject]@{
            manufacturer = "KEYSIGHT"
            model = "E36312A"
            serial = "SIM000003"
            firmware = "1.0"
            parse_ok = $true
        }
        resolved_identity = [pscustomobject]@{
            vendor_id = "keysight"
            model_id = "keysight-e36312a"
            model_name = "E36312A"
            display_name = "Keysight E36312A"
        }
        errors = @()
        outputs = @([pscustomobject]@{ channel = 1; enabled = $false })
        readback = @([pscustomobject]@{ channel = 1; setpoints = [pscustomobject]@{ voltage = 1.0; current = 0.05 } })
        measurements = @([pscustomobject]@{ channel = 1; measurements = [pscustomobject]@{ voltage = 1.0; current = 0.0 } })
        protection = [pscustomobject]@{ over_voltage_tripped = $false; over_current_tripped = $false }
        protection_settings = @([pscustomobject]@{ channel = 1; protection = [pscustomobject]@{ ovp_voltage = 5.0; ocp_enabled = $true; ocp_delay = $null; ocp_delay_trigger = $null } })
    }
    Write-Utf8NoBomFile -LiteralPath $path -Value @($snapshot | ConvertTo-Json -Depth 20)
    return $path
}

function Get-ReadOnlyCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $phase = if ($Live) { "live" } else { "preflight" }
    $cases = New-Object System.Collections.Generic.List[object]
    $channels = @(Get-TargetChannels -Model $Model)
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
    if ($Model -in @("keysight-e36312a", "keysight-edu36311a")) {
        $cases.Add((New-CommandCase -Name "validate-readonly" -Suite "readonly" -Phase $phase -Args (@("validate-readonly") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name "protection-status" -Suite "readonly" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live))
    }
    $cases.Add((New-CommandCase -Name "capabilities" -Suite "readonly" -Phase $phase -Args (@("capabilities") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    if ($Live) {
        $cases.Add((New-CommandCase -Name "doctor-resource" -Suite "readonly" -Phase $phase -Args @("doctor", "--json", "--resource", $resource, "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "doctor" -CandidateContextRequired:($Live -and (Test-CurrentConnectionUsesCandidateCapabilities))))
    }
    else {
        $cases.Add((New-CommandCase -Name "doctor-environment" -Suite "readonly" -Phase $phase -Args @("doctor", "--simulate", "--json") -ValidationKind "doctor-offline"))
    }
    if ($Model -eq "keysight-e36312a") {
        $cases.Add((New-CommandCase -Name "measure-all" -Suite "readonly" -Phase $phase -Args (@("measure-all") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live -ValidationKind "measure-all" -ExpectedChannels $channels -CandidateContextRequired:($Live -and (Test-CurrentConnectionUsesCandidateCapabilities))))
        if ($Live) {
            $cases.Add((New-CommandCase -Name "measure-all-error-queue" -Suite "readonly" -Phase $phase -Args @("error", "--json", "--resource", $resource, "--max-reads", "20", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "empty-errors"))
        }
    }
    if ($Model -in @("keysight-e36312a", "keysight-edu36311a")) {
        $logCsv = Join-Path $script:PrivateArtifactDir ($phase + "-log.csv")
        $logJsonl = Join-Path $script:PrivateArtifactDir ($phase + "-log.jsonl")
        $cases.Add((New-CommandCase -Name "log-one-sample" -Suite "readonly" -Phase $phase -Args (@("log") + $modeFlag + @("--channel", "all", "--interval-sec", "0.1", "--samples", "1", "--csv", $logCsv, "--jsonl", $logJsonl, "--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live -ValidationKind "log" -ExpectedChannels $channels -GeneratedArtifacts @($logCsv, $logJsonl) -CandidateContextRequired:($Live -and (Test-CurrentConnectionUsesCandidateCapabilities))))
    }
    return $cases.ToArray()
}

function Get-OutputCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $modelArgs = if ($Live) { @() } else { @("--model", $Model) }
    $phase = if ($Live) { "live" } else { "preflight" }
    $cases = New-Object System.Collections.Generic.List[object]
    $channels = @(Get-TargetChannels -Model $Model)
    $allCommon = if ($Live) { @("--json", "--resource", $resource, "--channel", "all", "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", "all") }
    $cases.Add((New-CommandCase -Name "safe-off-before" -Suite "output" -Phase $phase -Args (@("safe-off") + $allCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
    foreach ($channel in Get-TargetChannels -Model $Model) {
        $common = if ($Live) { @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", [string]$channel) }
        $cases.Add((New-CommandCase -Name ("set-ch" + $channel) -Suite "output" -Phase $phase -Args (@("set") + $common + @("--voltage", "1", "--current", "0.05")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("output-off-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-off") + $common) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("smoke-output-ch" + $channel) -Suite "output" -Phase $phase -Args (@("smoke-output") + $common + @("--voltage", "1", "--current", "0.05", "--duration-ms", "500", "--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("cycle-output-ch" + $channel) -Suite "output" -Phase $phase -Args (@("cycle-output") + $common + @("--duration-ms", "500", "--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("ramp-ch" + $channel) -Suite "output" -Phase $phase -Args (@("ramp") + $common + @("--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "0.25", "--current", "0.05", "--delay-ms", "100")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        if ($Model -ne "keysight-e3646a") {
            $cases.Add((New-CommandCase -Name ("output-on-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-on") + $common + @("--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateContextRequired:($Live -and (Test-CurrentConnectionUsesCandidateCapabilities))))
            $stateArgs = if ($Live) { @("output-state", "--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi") } else { @("output-state", "--simulate", "--json", "--resource", $resource, "--channel", [string]$channel) }
            $stateValidation = if ($Live) { "output-state" } else { $null }
            $cases.Add((New-CommandCase -Name ("assert-output-on-ch" + $channel) -Suite "output" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ValidationKind $stateValidation -ExpectedChannels @($channel) -ExpectedOutputEnabled $true))
            $cases.Add((New-CommandCase -Name ("standalone-output-off-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-off") + $common) -StateChanging:$Live -LiveHardwareExpected:$Live))
            $cases.Add((New-CommandCase -Name ("assert-output-off-ch" + $channel) -Suite "output" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ValidationKind $stateValidation -ExpectedChannels @($channel) -ExpectedOutputEnabled $false))
        }
    }
    if ($Model -eq "keysight-e3646a") {
        $globalSwitchCommon = if ($Live) { @("--json", "--resource", $resource, "--channel", "1", "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", "1") }
        $cases.Add((New-CommandCase -Name "output-on-global" -Suite "output" -Phase $phase -Args (@("output-on") + $globalSwitchCommon + @("--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateContextRequired:($Live -and (Test-CurrentConnectionUsesCandidateCapabilities))))
        $globalStateArgs = if ($Live) { @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") } else { @("output-state", "--simulate", "--json", "--resource", $resource, "--channel", "all") }
        $globalStateValidation = if ($Live) { "output-state" } else { $null }
        $cases.Add((New-CommandCase -Name "assert-global-output-on" -Suite "output" -Phase $phase -Args $globalStateArgs -LiveHardwareExpected:$Live -ValidationKind $globalStateValidation -ExpectedChannels $channels -ExpectedOutputEnabled $true))
        $cases.Add((New-CommandCase -Name "output-off-global" -Suite "output" -Phase $phase -Args (@("output-off") + $globalSwitchCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name "assert-global-output-off" -Suite "output" -Phase $phase -Args $globalStateArgs -LiveHardwareExpected:$Live -ValidationKind $globalStateValidation -ExpectedChannels $channels -ExpectedOutputEnabled $false))
    }
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

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
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
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata["keysight-e36312a"].simulator_resource }
    $phase = if ($Live) { "live" } else { "preflight" }
    $snapshotPath = if ($Live) { Join-Path $script:PrivateArtifactDir "snapshot-live.json" } else { New-ValidationSnapshotFile }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $cases = New-Object System.Collections.Generic.List[object]
    $cases.AddRange(@(
        (New-CommandCase -Name "snapshot-save" -Suite "snapshot" -Phase $phase -Args (@("snapshot") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi", "--snapshot-json", $snapshotPath)) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "snapshot-compare" -Suite "snapshot" -Phase $phase -Args (@("snapshot") + $modeFlag + @("--json", "--resource", $resource, "--compare", $snapshotPath, "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "restore-from-snapshot-plan" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--dry-run", "--json", "--snapshot", $snapshotPath, "--resource", $resource, "--channel", "all") -StateChanging:$false -LiveHardwareExpected:$false)
    ))
    if ($Live -and $Model -eq "keysight-e36312a") {
        $snapshotA = Join-Path $script:PrivateArtifactDir "restore-off-snapshot-a.json"
        $snapshotB = Join-Path $script:PrivateArtifactDir "restore-off-snapshot-b.json"
        $snapshotC = Join-Path $script:PrivateArtifactDir "restore-off-snapshot-c.json"
        $snapshotOn = Join-Path $script:PrivateArtifactDir "restore-on-snapshot.json"
        $commonAll = @("--json", "--resource", $resource, "--channel", "all", "--log-scpi")
        $cases.Add((New-CommandCase -Name "restore-off-safe-off" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-program-a" -Suite "snapshot" -Phase $phase -Args (@("apply") + $commonAll + @("--voltage", "1", "--current", "0.05", "--no-output")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-protection-a" -Suite "snapshot" -Phase $phase -Args @("protection-set", "--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "5", "--ocp", "on", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-save-a" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotA, "--log-scpi") -LiveHardwareExpected:$true -GeneratedArtifacts @($snapshotA)))
        $cases.Add((New-CommandCase -Name "restore-off-mutate-setpoints" -Suite "snapshot" -Phase $phase -Args (@("apply") + $commonAll + @("--voltage", "0.5", "--current", "0.04", "--no-output")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-mutate-protection" -Suite "snapshot" -Phase $phase -Args @("protection-set", "--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "4", "--ocp", "off", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-save-b" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotB, "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "snapshot-mutation" -GeneratedArtifacts @($snapshotB) -CompareSnapshotPaths @($snapshotA,$snapshotB)))
        $cases.Add((New-CommandCase -Name "restore-off-execute" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--json", "--resource", $resource, "--snapshot", $snapshotA, "--channel", "all", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -ValidationKind "restore" -ExpectedChannels @(1,2,3) -CandidateContextRequired:(Test-CurrentConnectionUsesCandidateCapabilities)))
        $cases.Add((New-CommandCase -Name "restore-off-save-c" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotC, "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "snapshot-compare" -GeneratedArtifacts @($snapshotC) -CompareSnapshotPaths @($snapshotA,$snapshotC)))
        $cases.Add((New-CommandCase -Name "restore-off-assert-outputs" -Suite "snapshot" -Phase $phase -Args @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "output-state" -ExpectedChannels @(1,2,3) -ExpectedOutputEnabled $false))
        $cases.Add((New-CommandCase -Name "restore-on-safe-off" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-program-all" -Suite "snapshot" -Phase $phase -Args (@("apply") + $commonAll + @("--voltage", "1", "--current", "0.05", "--no-output")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-enable-ch1" -Suite "snapshot" -Phase $phase -Args @("output-on", "--json", "--resource", $resource, "--channel", "1", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -CandidateContextRequired:(Test-CurrentConnectionUsesCandidateCapabilities)))
        $cases.Add((New-CommandCase -Name "restore-on-save" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotOn, "--log-scpi") -LiveHardwareExpected:$true -GeneratedArtifacts @($snapshotOn)))
        $cases.Add((New-CommandCase -Name "restore-on-safe-off-before-restore" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-mutate-ch1" -Suite "snapshot" -Phase $phase -Args @("set", "--json", "--resource", $resource, "--channel", "1", "--voltage", "0.5", "--current", "0.04", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-execute" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--json", "--resource", $resource, "--snapshot", $snapshotOn, "--channel", "all", "--restore-output-state", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -ValidationKind "restore" -ExpectedChannels @(1,2,3) -CandidateContextRequired:(Test-CurrentConnectionUsesCandidateCapabilities)))
        $cases.Add((New-CommandCase -Name "restore-on-readback" -Suite "snapshot" -Phase $phase -Args @("readback", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "snapshot-readback" -ExpectedChannels @(1,2,3) -CompareSnapshotPaths @($snapshotOn)))
        $cases.Add((New-CommandCase -Name "restore-on-assert" -Suite "snapshot" -Phase $phase -Args @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "output-state-one-on" -ExpectedChannels @(1,2,3)))
        $cases.Add((New-CommandCase -Name "restore-on-immediate-safe-off" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true -CleanupRole "restore_on_immediate_safe_off"))
        $cases.Add((New-CommandCase -Name "restore-on-final-output-state" -Suite "snapshot" -Phase $phase -Args @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "output-state" -ExpectedChannels @(1,2,3) -ExpectedOutputEnabled $false))
        $cases.Add((New-CommandCase -Name "restore-error-queue" -Suite "snapshot" -Phase $phase -Args @("error", "--json", "--resource", $resource, "--max-reads", "20", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "empty-errors"))
    }
    return $cases.ToArray()
}

function Get-TriggerListCases {
    param([bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata["keysight-e36312a"].simulator_resource }
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

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
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
        if ($Model -in @("keysight-edu36311a", "keysight-e3646a")) {
            $negativeCases = @(
                @{ Name = "sequence-unsupported-trigger"; Action = "trigger-list"; Expected = "trigger-list" },
                @{ Name = "sequence-unsupported-snapshot"; Action = "snapshot"; Expected = "snapshot" },
                @{ Name = "sequence-unsupported-restore"; Action = "restore-from-snapshot"; Expected = "restore" },
                @{ Name = "sequence-unsupported-native-list"; Action = "native-list"; Expected = "native-list" }
            )
            if ($Model -eq "keysight-e3646a") {
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
            $cases.AddRange((Get-SnapshotCases -Model $Model -Live:$Live))
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

function Assert-CandidateContextInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Model,
        [Parameter(Mandatory = $true)][object[]]$LiveCases,
        [bool]$RequireComplete = $false
    )

    if ($null -eq $script:CandidateInventory) {
        throw "Core candidate inventory is unavailable."
    }
    $modelProperty = $script:CandidateInventory.PSObject.Properties[$Model]
    if ($null -eq $modelProperty) {
        throw "Candidate inventory has no entry for $Model."
    }
    $expectedCommands = @($modelProperty.Value.commands)
    $connectionMatches = @($modelProperty.Value.connections | Where-Object {
        $_.Count -eq 2 -and $_[0] -eq $script:TransportScope -and $_[1] -eq $script:BackendArtifact.backend_scope
    })
    $candidateConnectionSelected = $connectionMatches.Count -eq 1
    foreach ($case in @($LiveCases)) {
        $command = if ($case.args.Count -gt 0) { [string]$case.args[0] } else { "" }
        $isCandidateCommand = ($candidateConnectionSelected -and $case.phase -eq "live" -and [bool]$case.live_hardware_expected -and $command -in $expectedCommands)
        if ($isCandidateCommand -and -not [bool]$case.candidate_context_required) {
            throw "Live candidate command '$command' in case '$($case.name)' is missing candidate context."
        }
        if ([bool]$case.candidate_context_required -and -not $isCandidateCommand) {
            throw "Noncandidate live case '$($case.name)' is marked candidate-context-required."
        }
        if ($command -in @("trigger-pulse", "trigger-fire") -and [bool]$case.candidate_context_required) {
            throw "Direct trigger command '$command' must not receive candidate context."
        }
    }
    $seenCandidateCommands = @($LiveCases | Where-Object {
        if ($_.phase -ne "live" -or -not [bool]$_.live_hardware_expected) { return $false }
        $command = if ($_.args.Count -gt 0) { [string]$_.args[0] } else { "" }
        $command -in $expectedCommands
    } | ForEach-Object { [string]$_.args[0] } | Sort-Object -Unique)
    $missingCommands = @($expectedCommands | Where-Object { $_ -notin $seenCandidateCommands })
    if ($RequireComplete -and $candidateConnectionSelected -and $missingCommands.Count -gt 0) {
        throw "Live candidate inventory is missing command uses: $($missingCommands -join ', ')."
    }
}

function Get-CaseAssertionFailures {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [AllowNull()]$Payload,
        [AllowNull()]$Identity,
        [AllowNull()]$OutputStates,
        [AllowNull()]$InstrumentErrors,
        [Parameter(Mandatory = $true)][string]$StderrPath
    )

    $failures = New-Object System.Collections.Generic.List[string]
    $kind = [string]$Case.validation_kind
    if ([string]::IsNullOrWhiteSpace($kind) -or $null -eq $Payload) {
        return $failures.ToArray()
    }
    $data = Get-PropertyValue -Object $Payload -Name "data"
    if ($Case.phase -eq "live" -and $kind -ne "empty-errors") {
        $observedModel = [string](Get-PropertyValue -Object $Identity -Name "model")
        $expectedModel = [string]$TargetMetadata[$script:NormalizedTarget].model
        if ($observedModel -ne $expectedModel) {
            $failures.Add("$($Case.name) did not report the expected detected model $expectedModel.")
        }
    }

    if ($kind -in @("output-state", "output-state-one-on")) {
        $states = @($OutputStates)
        if ($states.Count -eq 0 -and $Case.expected_channels.Count -eq 1) {
            $states = @([pscustomobject]@{
                channel = $Case.expected_channels[0]
                enabled = Get-PropertyValue -Object $data -Name "output_enabled"
            })
        }
        foreach ($channel in $Case.expected_channels) {
            $matches = @($states | Where-Object { (Get-PropertyValue -Object $_ -Name "channel") -eq $channel })
            if ($matches.Count -ne 1) {
                $failures.Add("$($Case.name) expected exactly one output-state record for channel $channel.")
                continue
            }
            $enabled = Get-PropertyValue -Object $matches[0] -Name "enabled"
            if ($kind -eq "output-state-one-on") {
                $expected = ($channel -eq 1)
            }
            else {
                $expected = [bool]$Case.expected_output_enabled
            }
            if ($null -eq $enabled -or [bool]$enabled -ne $expected) {
                $failures.Add("$($Case.name) expected channel $channel output enabled=$expected.")
            }
        }
        if ($states.Count -ne $Case.expected_channels.Count) {
            $failures.Add("$($Case.name) returned an unexpected output-state channel count.")
        }
    }
    elseif ($kind -eq "measure-all") {
        $records = @((Get-PropertyValue -Object $data -Name "channels"))
        foreach ($channel in $Case.expected_channels) {
            $matches = @($records | Where-Object { (Get-PropertyValue -Object $_ -Name "channel") -eq $channel })
            if ($matches.Count -ne 1) {
                $failures.Add("$($Case.name) expected exactly one measurement record for channel $channel.")
                continue
            }
            $measurements = Get-PropertyValue -Object $matches[0] -Name "measurements"
            foreach ($field in @("voltage", "current")) {
                $value = Get-PropertyValue -Object $measurements -Name $field
                $parsed = 0.0
                if ($null -eq $value -or -not [double]::TryParse([string]$value, [ref]$parsed)) {
                    $failures.Add("$($Case.name) channel $channel has a nonnumeric measured $field value.")
                }
            }
        }
        if ($records.Count -ne $Case.expected_channels.Count) {
            $failures.Add("$($Case.name) returned an unexpected measurement channel count.")
        }
        $scpiText = if (Test-Path -LiteralPath $StderrPath) { Get-Content -LiteralPath $StderrPath -Raw } else { "" }
        if ($scpiText -match '(?im)>>.*(?:OUTP\s+(?:ON|OFF)|VOLT\s|CURR\s|\*CLS|\*TRG|INIT|ABOR)') {
            $failures.Add("$($Case.name) emitted state-changing SCPI.")
        }
    }
    elseif ($kind -eq "doctor") {
        $manager = Get-PropertyValue -Object $data -Name "real_resource_manager"
        $resource = Get-PropertyValue -Object $data -Name "resource"
        if ((Get-PropertyValue -Object $manager -Name "checked") -ne $true -or (Get-PropertyValue -Object $manager -Name "available") -ne $true) {
            $failures.Add("$($Case.name) did not complete the real resource-manager check.")
        }
        if ((Get-PropertyValue -Object $resource -Name "reachable") -ne $true -or $null -eq (Get-PropertyValue -Object $resource -Name "idn")) {
            $failures.Add("$($Case.name) did not open and identify the requested resource.")
        }
        $pyvisa = Get-PropertyValue -Object $data -Name "pyvisa"
        $reportedBackend = [string](Get-PropertyValue -Object $pyvisa -Name "backend")
        $expectedBackend = [string]$script:BackendValue
        if ($reportedBackend -ne $expectedBackend) {
            $failures.Add("$($Case.name) reported an unexpected selected backend.")
        }
        $scpiText = if (Test-Path -LiteralPath $StderrPath) { Get-Content -LiteralPath $StderrPath -Raw } else { "" }
        if ($scpiText -match '(?im)>>.*(?:OUTP\s+(?:ON|OFF)|VOLT\s|CURR\s|\*CLS|\*TRG|INIT|ABOR)') {
            $failures.Add("$($Case.name) emitted state-changing SCPI.")
        }
    }
    elseif ($kind -eq "doctor-offline") {
        $manager = Get-PropertyValue -Object $data -Name "real_resource_manager"
        if ((Get-PropertyValue -Object $manager -Name "checked") -ne $false) {
            $failures.Add("$($Case.name) unexpectedly checked a real resource manager.")
        }
    }
    elseif ($kind -eq "empty-errors") {
        if ($null -eq $InstrumentErrors -or @($InstrumentErrors).Count -ne 0) {
            $failures.Add("$($Case.name) did not confirm an empty instrument error queue.")
        }
    }
    elseif ($kind -eq "restore") {
        $restored = @((Get-PropertyValue -Object $data -Name "restored_channels"))
        if (($restored -join ',') -ne ($Case.expected_channels -join ',')) {
            $failures.Add("$($Case.name) did not restore exactly the selected channels.")
        }
    }
    elseif ($kind -eq "snapshot-compare") {
        try {
            $left = Get-Content -LiteralPath $Case.compare_snapshot_paths[0] -Raw | ConvertFrom-Json
            $right = Get-Content -LiteralPath $Case.compare_snapshot_paths[1] -Raw | ConvertFrom-Json
            foreach ($section in @("readback", "protection_settings")) {
                $leftValue = (Get-PropertyValue -Object $left -Name $section) | ConvertTo-Json -Depth 20 -Compress
                $rightValue = (Get-PropertyValue -Object $right -Name $section) | ConvertTo-Json -Depth 20 -Compress
                if ($leftValue -cne $rightValue) {
                    $failures.Add("$($Case.name) restorable $section differs after restore.")
                }
            }
        }
        catch {
            $failures.Add("$($Case.name) could not compare canonical snapshot artifacts.")
        }
    }
    elseif ($kind -eq "snapshot-mutation") {
        try {
            $left = Get-Content -LiteralPath $Case.compare_snapshot_paths[0] -Raw | ConvertFrom-Json
            $right = Get-Content -LiteralPath $Case.compare_snapshot_paths[1] -Raw | ConvertFrom-Json
            foreach ($channel in @(1,2,3)) {
                $leftReadback = @($left.readback | Where-Object { $_.channel -eq $channel })
                $rightReadback = @($right.readback | Where-Object { $_.channel -eq $channel })
                $leftProtection = @($left.protection_settings | Where-Object { $_.channel -eq $channel })
                $rightProtection = @($right.protection_settings | Where-Object { $_.channel -eq $channel })
                if ($leftReadback.Count -ne 1 -or $rightReadback.Count -ne 1 -or
                    $leftReadback[0].setpoints.voltage -eq $rightReadback[0].setpoints.voltage -or
                    $leftReadback[0].setpoints.current -eq $rightReadback[0].setpoints.current) {
                    $failures.Add("$($Case.name) did not prove changed setpoints for channel $channel.")
                }
                if ($leftProtection.Count -ne 1 -or $rightProtection.Count -ne 1 -or
                    $leftProtection[0].protection.ovp_voltage -eq $rightProtection[0].protection.ovp_voltage -or
                    $leftProtection[0].protection.ocp_enabled -eq $rightProtection[0].protection.ocp_enabled) {
                    $failures.Add("$($Case.name) did not prove changed OVP and OCP state for channel $channel.")
                }
            }
        }
        catch {
            $failures.Add("$($Case.name) could not prove the pre-restore snapshot mutation.")
        }
    }
    elseif ($kind -eq "snapshot-readback") {
        try {
            $snapshot = Get-Content -LiteralPath $Case.compare_snapshot_paths[0] -Raw | ConvertFrom-Json
            $expected = @($snapshot.readback)
            $actual = @((Get-PropertyValue -Object $data -Name "channels"))
            if ($expected.Count -ne $Case.expected_channels.Count -or $actual.Count -ne $Case.expected_channels.Count) {
                $failures.Add("$($Case.name) snapshot/readback channel inventory differs.")
            }
            foreach ($channel in $Case.expected_channels) {
                $expectedRecord = @($expected | Where-Object { $_.channel -eq $channel })
                $actualRecord = @($actual | Where-Object { $_.channel -eq $channel })
                if ($expectedRecord.Count -ne 1 -or $actualRecord.Count -ne 1) {
                    $failures.Add("$($Case.name) expected exactly one snapshot and live record for channel $channel.")
                    continue
                }
                foreach ($field in @("voltage", "current")) {
                    $expectedValue = 0.0
                    $actualValue = 0.0
                    if (-not [double]::TryParse([string]$expectedRecord[0].setpoints.$field, [ref]$expectedValue) -or
                        -not [double]::TryParse([string]$actualRecord[0].setpoints.$field, [ref]$actualValue)) {
                        $failures.Add("$($Case.name) channel $channel has a nonnumeric $field setpoint.")
                        continue
                    }
                    $tolerance = if ($field -eq "voltage") { 0.001 } else { 0.001 }
                    if ([math]::Abs($expectedValue - $actualValue) -gt $tolerance -or $actualValue -lt 0 -or
                        ($field -eq "voltage" -and $actualValue -gt 1.0) -or
                        ($field -eq "current" -and $actualValue -gt 0.05)) {
                        $failures.Add("$($Case.name) channel $channel restored $field is outside the snapshot tolerance or safe bound.")
                    }
                }
            }
        }
        catch {
            $failures.Add("$($Case.name) could not compare the restored live readback with its snapshot.")
        }
    }
    elseif ($kind -eq "log") {
        $csvPath = $Case.generated_artifacts[0]
        $jsonlPath = $Case.generated_artifacts[1]
        if (-not (Test-Path -LiteralPath $csvPath) -or -not (Test-Path -LiteralPath $jsonlPath)) {
            $failures.Add("$($Case.name) did not create both CSV and JSONL artifacts.")
        }
        else {
            try {
                $rows = @(Import-Csv -LiteralPath $csvPath)
                $expectedHeader = @("timestamp","resource","resource_alias","model","serial","channel","programmed_voltage","programmed_current","measured_voltage","measured_current","output_enabled","errors")
                $actualHeader = if ($rows.Count -gt 0) { @($rows[0].PSObject.Properties.Name) } else { @() }
                if (($actualHeader -join ',') -cne ($expectedHeader -join ',')) { $failures.Add("$($Case.name) CSV header does not match the logging contract.") }
                if ($rows.Count -ne $Case.expected_channels.Count) { $failures.Add("$($Case.name) CSV row count does not match the target channel count.") }
                foreach ($channel in $Case.expected_channels) {
                    $matches = @($rows | Where-Object { $_.channel -eq [string]$channel })
                    if ($matches.Count -ne 1) { $failures.Add("$($Case.name) expected one CSV sample for channel $channel."); continue }
                    $row = $matches[0]
                    foreach ($field in @("programmed_voltage","programmed_current","measured_voltage","measured_current","output_enabled")) {
                        if ([string]::IsNullOrWhiteSpace([string]$row.$field)) { $failures.Add("$($Case.name) CSV field $field is missing for channel $channel.") }
                    }
                    if (-not [string]::IsNullOrEmpty([string]$row.errors)) { $failures.Add("$($Case.name) CSV contains instrument errors for channel $channel.") }
                }
                $events = @(Get-Content -LiteralPath $jsonlPath | ForEach-Object { $_ | ConvertFrom-Json })
                $samples = @($events | Where-Object { $_.event -eq "sample" })
                $summaries = @($events | Where-Object { $_.event -eq "summary" })
                if ($samples.Count -ne $Case.expected_channels.Count -or $summaries.Count -ne 1) { $failures.Add("$($Case.name) JSONL sample/summary event count is invalid.") }
                elseif ($summaries[0].samples_written -ne 1 -or $summaries[0].stopped -ne $false -or $summaries[0].stop_reason -ne "completed") { $failures.Add("$($Case.name) JSONL summary is not a completed one-sample run.") }
                foreach ($channel in $Case.expected_channels) {
                    $jsonlMatches = @($samples | Where-Object { (Get-PropertyValue -Object $_.sample -Name "channel") -eq $channel })
                    if ($jsonlMatches.Count -ne 1) { $failures.Add("$($Case.name) expected one JSONL sample for channel $channel.") }
                }
            }
            catch {
                $failures.Add("$($Case.name) could not parse its CSV/JSONL artifacts.")
            }
        }
        if ((Get-PropertyValue -Object $data -Name "samples_written") -ne 1 -or (Get-PropertyValue -Object $data -Name "stopped") -ne $false) {
            $failures.Add("$($Case.name) command result is not a completed one-sample run.")
        }
    }
    return $failures.ToArray()
}

function Invoke-ValidationCommand {
    param([Parameter(Mandatory = $true)]$Case)

    Ensure-ArtifactDirectories
    $artifactBaseName = Get-CaseArtifactBaseName -Case $Case
    $jsonPath = Join-Path $script:PrivateArtifactDir ($artifactBaseName + ".json")
    $stdoutPath = Join-Path $script:PrivateArtifactDir ($artifactBaseName + ".stdout.txt")
    $stderrPath = Join-Path $script:PrivateArtifactDir ($artifactBaseName + ".stderr-scpi.txt")
    $shareableJsonPath = Join-Path $script:ShareableArtifactDir ($artifactBaseName + ".json")
    $shareableStdoutPath = Join-Path $script:ShareableArtifactDir ($artifactBaseName + ".stdout.txt")
    $shareableStderrPath = Join-Path $script:ShareableArtifactDir ($artifactBaseName + ".stderr-scpi.txt")
    $allArgs = @(Get-ValidationCommandArguments -Case $Case -JsonPath $jsonPath)
    $hasSaveJson = $Case.args -contains "--save-json"
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
    $hadPythonPath = $null -ne [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            $oldNativePreference = [bool]$nativePreferenceVariable.Value
            $PSNativeCommandUseErrorActionPreference = $false
        }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", (Get-ValidationChildPythonPath), "Process")
        & $CliExecutable @CliPrefix @allArgs 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadPythonPath) {
            [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process")
        }
        else {
            [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
        }
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }

    $payload = $null
    $parseError = $null
    $parseStatus = "parsed"
    if (Test-Path -LiteralPath $actualJsonPath) {
        try {
            $payload = Get-Content -LiteralPath $actualJsonPath -Raw | ConvertFrom-Json
        }
        catch {
            $parseStatus = "failed"
            $parseError = "Could not parse command JSON."
        }
    }
    else {
        $parseStatus = "missing"
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

    $identity = $null
    $outputStates = $null
    $instrumentErrors = $null
    if ($null -ne $payload) {
        $data = Get-PropertyValue -Object $payload -Name "data"
        if ($null -ne $data) {
            $resourceData = Get-PropertyValue -Object $data -Name "resource"
            $identity = Get-PropertyValue -Object $resourceData -Name "idn"
            if ($null -eq $identity) {
                $identity = Get-PropertyValue -Object $data -Name "idn"
            }
            $outputStates = Get-PropertyValue -Object $data -Name "outputs"
            if ($null -eq $outputStates) {
                $outputStates = Get-PropertyValue -Object $data -Name "output"
            }
            $instrumentErrors = Get-PropertyValue -Object $data -Name "errors"
        }
    }
    if ($null -ne $identity) {
        Add-SensitiveValue -Value ([string](Get-PropertyValue -Object $identity -Name "raw"))
        Add-SerialSensitiveValue -Value ([string](Get-PropertyValue -Object $identity -Name "serial"))
    }
    Write-ShareableJsonArtifact -PrivatePath $actualJsonPath -ShareablePath $shareableJsonPath -Payload $payload -ParseStatus $parseStatus
    Write-ShareableTextArtifact -PrivatePath $stdoutPath -ShareablePath $shareableStdoutPath
    Write-ShareableTextArtifact -PrivatePath $stderrPath -ShareablePath $shareableStderrPath

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

    $assertionFailures = @()
    if ($casePassed) {
        $assertionFailures = @(Get-CaseAssertionFailures -Case $Case -Payload $payload -Identity $identity -OutputStates $outputStates -InstrumentErrors $instrumentErrors -StderrPath $stderrPath)
        if ($assertionFailures.Count -gt 0) {
            $casePassed = $false
            $failure = $assertionFailures -join " "
        }
    }

    $generatedArtifactPaths = New-Object System.Collections.Generic.List[string]
    $artifactIndex = 0
    foreach ($generatedPath in $Case.generated_artifacts) {
        $artifactIndex += 1
        if (Test-Path -LiteralPath $generatedPath) {
            $extension = [System.IO.Path]::GetExtension($generatedPath)
            $shareableGeneratedPath = Join-Path $script:ShareableArtifactDir ($artifactBaseName + "-generated-" + $artifactIndex + $extension)
            Write-ShareableTextArtifact -PrivatePath $generatedPath -ShareablePath $shareableGeneratedPath
            $generatedArtifactPaths.Add((ConvertTo-RepoRelativePath -Path $shareableGeneratedPath))
            $shareableGeneratedText = Get-Content -LiteralPath $shareableGeneratedPath -Raw
            $forbiddenValues = @($script:RawResource, $RepoRoot, $PythonExe) + @($script:SensitiveValues)
            foreach ($forbiddenValue in $forbiddenValues) {
                if (-not [string]::IsNullOrWhiteSpace([string]$forbiddenValue) -and $shareableGeneratedText.Contains([string]$forbiddenValue)) {
                    $assertionFailures += "$($Case.name) shareable generated artifact leaked sensitive data."
                    $casePassed = $false
                    $failure = $assertionFailures -join " "
                    break
                }
            }
        }
    }

    $recordArgs = Protect-Arguments -Arguments $allArgs
    $commandLine = (Get-ShareableCliCommand) + " " + (($recordArgs | ForEach-Object { Format-CommandArgument -Argument $_ }) -join " ")
    $backendScope = if ($null -eq $script:BackendArtifact) { $null } else { $script:BackendArtifact.backend_scope }
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
        error_code = $errorCode
        parse_error = $parseError
        expected_success = $Case.expected_success
        support_policy_mode = if ($allArgs -contains "--validation-allow-pending-live-support") { "validation" } else { $null }
        transport_scope = $script:TransportScope
        backend_scope = $backendScope
        identity_observed = [bool]($Case.phase -eq "live" -and $null -ne $identity)
        output_states_observed = $outputStates
        instrument_errors_observed = $instrumentErrors
        cleanup_role = $Case.cleanup_role
        state_changing = $Case.state_changing
        validation_kind = $Case.validation_kind
        assertion_failures = @($assertionFailures | ForEach-Object { Protect-ShareableText -Text $_ })
        generated_artifacts = $generatedArtifactPaths.ToArray()
        comparison_result = if ($Case.validation_kind -eq "snapshot-compare") { if ($assertionFailures.Count -eq 0) { "matched" } else { "mismatch" } } else { $null }
        result = if ($casePassed) { "passed" } else { "failed" }
        stdout_path = ConvertTo-RepoRelativePath -Path $shareableStdoutPath
        stderr_path = ConvertTo-RepoRelativePath -Path $shareableStderrPath
        stderr_scpi_path = ConvertTo-RepoRelativePath -Path $shareableStderrPath
        json_path = ConvertTo-RepoRelativePath -Path $shareableJsonPath
    }
    $script:CommandRecords.Add($record)
    if (-not $casePassed) {
        $script:Failures.Add($failure)
    }
    if ($casePassed -and $Case.phase -eq "live" -and $null -ne $identity -and ($null -eq $script:InstrumentIdentity -or $script:InstrumentIdentity.availability -ne "observed")) {
        $serial = Get-PropertyValue -Object $identity -Name "serial"
        $script:InstrumentIdentity = [pscustomobject]@{
            availability = "observed"
            manufacturer = Get-PropertyValue -Object $identity -Name "manufacturer"
            detected_model = Get-PropertyValue -Object $identity -Name "model"
            firmware = Get-PropertyValue -Object $identity -Name "firmware"
            serial = if ([string]::IsNullOrWhiteSpace([string]$serial)) { $null } else { "<redacted>" }
            serial_redacted = -not [string]::IsNullOrWhiteSpace([string]$serial)
            source_command = $Case.name
        }
    }
    return $record
}

function Test-AllOutputsOff {
    param([AllowNull()]$OutputStates)

    if ($null -eq $OutputStates) {
        return $null
    }
    $items = @($OutputStates)
    if ($items.Count -eq 0) {
        return $null
    }
    foreach ($item in $items) {
        if ($item -is [bool]) {
            if ($item) { return $false }
            continue
        }
        $enabled = Get-PropertyValue -Object $item -Name "enabled"
        if ($null -eq $enabled) {
            $enabled = Get-PropertyValue -Object $item -Name "output"
        }
        if ($null -eq $enabled) {
            return $null
        }
        if ([bool]$enabled) {
            return $false
        }
    }
    return $true
}

function Invoke-SafeOffCleanup {
    param([ValidateSet("failure", "final")][string]$Role = "failure")

    if (-not $Restore) {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
        return
    }
    $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
    $script:CleanupEvidence.requested = $true
    $script:CleanupEvidence.attempted = $true
    $cleanupName = if ($Role -eq "failure") { "safe-off-failure-cleanup" } else { "safe-off-final-cleanup" }
    $cleanupCase = New-CommandCase -Name $cleanupName -Suite "cleanup" -Phase "live" -Args @("safe-off", "--json", "--resource", $script:RawResource, "--channel", "all", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -CleanupRole ($Role + "_safe_off")
    try {
        $safeOffRecord = Invoke-ValidationCommand -Case $cleanupCase
        $script:CleanupEvidence.safe_off_command = $safeOffRecord.command_line
        $script:CleanupEvidence.safe_off_exit_code = $safeOffRecord.exit_code
        $script:CleanupEvidence.safe_off_ok = ($safeOffRecord.result -eq "passed")
        if (-not $script:CleanupEvidence.safe_off_ok) {
            $script:CleanupEvidence.status = "failed"
            $script:Failures.Add("Cleanup safe-off command failed.")
            return
        }

        $outputStateCase = New-CommandCase -Name "cleanup-output-state" -Suite "cleanup" -Phase "live" -Args @("output-state", "--json", "--resource", $script:RawResource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -CleanupRole "final_output_state"
        $outputStateRecord = Invoke-ValidationCommand -Case $outputStateCase
        if ($outputStateRecord.result -eq "passed") {
            $script:CleanupEvidence.output_state_checked = $true
            $script:CleanupEvidence.all_outputs_off = Test-AllOutputsOff -OutputStates $outputStateRecord.output_states_observed
        }
        else {
            $script:Failures.Add("Cleanup did not produce verifiable output-state evidence.")
        }

        $errorCase = New-CommandCase -Name "cleanup-error-queue" -Suite "cleanup" -Phase "live" -Args @("error", "--json", "--resource", $script:RawResource, "--max-reads", "20", "--log-scpi") -LiveHardwareExpected:$true -CleanupRole "final_error_queue"
        $errorRecord = Invoke-ValidationCommand -Case $errorCase
        if ($errorRecord.result -eq "passed") {
            $script:CleanupEvidence.error_queue_checked = $true
            $script:CleanupEvidence.instrument_errors = $errorRecord.instrument_errors_observed
        }
        else {
            $script:Failures.Add("Cleanup could not verify the instrument error queue.")
        }

        if ($script:CleanupEvidence.all_outputs_off -eq $false) {
            $script:CleanupEvidence.status = "failed"
            $script:Failures.Add("Cleanup could not confirm that all outputs are off.")
        }
        elseif (-not $script:CleanupEvidence.output_state_checked -or -not $script:CleanupEvidence.error_queue_checked -or $null -eq $script:CleanupEvidence.all_outputs_off) {
            $script:CleanupEvidence.status = "partial"
            if (-not $script:CleanupEvidence.output_state_checked -or $null -eq $script:CleanupEvidence.all_outputs_off) {
                if ($script:Failures -notcontains "Cleanup did not produce verifiable output-state evidence.") {
                    $script:Failures.Add("Cleanup did not produce verifiable output-state evidence.")
                }
            }
            if (-not $script:CleanupEvidence.error_queue_checked) {
                if ($script:Failures -notcontains "Cleanup could not verify the instrument error queue.") {
                    $script:Failures.Add("Cleanup could not verify the instrument error queue.")
                }
            }
        }
        elseif ($null -ne $script:CleanupEvidence.instrument_errors -and @($script:CleanupEvidence.instrument_errors).Count -gt 0) {
            $script:CleanupEvidence.status = "partial"
            $script:Failures.Add("Cleanup finished with instrument errors.")
        }
        else {
            $script:CleanupEvidence.status = "passed"
        }
    }
    catch {
        $script:CleanupEvidence.status = "failed"
        $script:Failures.Add("$Role cleanup threw: " + $_.Exception.Message)
    }
}

function Write-LiveConfirmationWarnings {
    param([Parameter(Mandatory = $true)][string[]]$SuitesToRun)

    if (@($SuitesToRun | Where-Object { $_ -in @("output", "protection", "snapshot", "trigger-list", "software-sequence") }).Count -gt 0) {
        Write-Host "Possible state changes:"
        $outputAffectingSuites = @(@("output", "snapshot", "trigger-list", "software-sequence") | Where-Object { $_ -in $SuitesToRun })
        if (@($outputAffectingSuites).Count -gt 0) {
            if (@($outputAffectingSuites).Count -eq 1) {
                $outputCaseText = "$($outputAffectingSuites[0]) cases"
            }
            elseif (@($outputAffectingSuites).Count -eq 2) {
                $outputCaseText = "$($outputAffectingSuites[0]) or $($outputAffectingSuites[1]) cases"
            }
            else {
                $head = @($outputAffectingSuites[0..($outputAffectingSuites.Count - 2)]) -join ", "
                $outputCaseText = "$head, or $($outputAffectingSuites[-1]) cases"
            }
            Write-Host "- Low-power setpoints may be written: 1 V / 0.05 A."
            Write-Host "- Outputs may briefly turn on for $outputCaseText."
        }
        if ("protection" -in $SuitesToRun) {
            Write-Host "- Protection suite writes OVP/OCP settings and clears protection state."
        }
        if ("snapshot" -in $SuitesToRun) {
            Write-Host "- E36312A snapshot validation includes confirmed real restore paths and mandatory safe-off cleanup."
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

function Normalize-CleanupEvidenceForReport {
    param([Parameter(Mandatory = $true)][string]$ValidationMode)

    $completedStatuses = @("passed", "partial", "failed", "skipped_by_operator")
    if ($null -eq $script:CleanupEvidence) {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode $ValidationMode
        return
    }
    if ($script:CleanupEvidence.status -in $completedStatuses) {
        return
    }
    if ($ValidationMode -eq "planned") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "planned"
        return
    }
    if ($ValidationMode -eq "preflight_failed") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "preflight_failed"
        return
    }
    if ($ValidationMode -eq "confirmation_required") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "confirmation_required"
        return
    }
    if ($ValidationMode -eq "live") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
    }
}

function Write-ValidationArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ValidationMode,
        [Parameter(Mandatory = $true)][string]$Result,
        [Parameter(Mandatory = $true)][datetime]$StartedAt
    )

    Ensure-ArtifactDirectories
    $completedAt = Get-Date
    $reportPath = Join-Path $script:ShareableArtifactDir "report.json"
    $summaryPath = Join-Path $script:ShareableArtifactDir "summary.md"
    $caseRecords = @($script:CommandRecords | ForEach-Object {
        [pscustomobject]@{
            name = $_.name
            suite = $_.suite
            phase = $_.phase
            expected_success = $_.expected_success
            result = $_.result
        }
    })
    $plannedLiveCases = @($script:PlannedLiveCases | ForEach-Object {
        [pscustomobject]@{
            name = $_.name
            suite = $_.suite
            command = if ($_.args.Count -gt 0) { $_.args[0] } else { $null }
            arguments = Protect-Arguments -Arguments $_.args
            state_changing = $_.state_changing
            validation_kind = $_.validation_kind
            expected_channels = $_.expected_channels
            cleanup_role = $_.cleanup_role
        }
    })
    if ($null -eq $script:InstrumentIdentity) {
        $script:InstrumentIdentity = [pscustomobject]@{
            availability = if ($ValidationMode -eq "planned") { "not_observed_plan_only" } else { "not_observed" }
            manufacturer = $null
            detected_model = $null
            firmware = $null
            serial = $null
            serial_redacted = $false
            source_command = $null
        }
    }
    Normalize-CleanupEvidenceForReport -ValidationMode $ValidationMode
    if ($ValidationMode -eq "live" -and $script:StateChanging -and $Restore -and $Result -eq "passed" -and $script:CleanupEvidence.status -ne "passed") {
        if ($script:Failures -notcontains "Required cleanup did not complete successfully.") {
            $script:Failures.Add("Required cleanup did not complete successfully.")
        }
        $Result = "failed"
    }
    $reportFields = [ordered]@{
        schema_version = "2.0"
        kind = "powers-tool-live-validation"
        vendor_id = $TargetMetadata[$script:NormalizedTarget].vendor_id
        model_id = $script:NormalizedTarget
        connection = $script:ConnectionLabel
        transport_scope = $script:TransportScope
        suite = $Suite
        validation_mode = $ValidationMode
        support_policy_mode = "validation"
        pending_live_support_allowed = $true
        candidate_evidence_only = $true
        promotes_live_support = $false
        plan_only = [bool]$PlanOnly
        live_executed = ($ValidationMode -eq "live")
        state_changing = $script:StateChanging
        restore_requested = [bool]$Restore
        resource = $script:ResourceDisplay
        backend = $script:BackendArtifact.backend
        backend_scope = $script:BackendArtifact.backend_scope
        backend_argument = $script:BackendArtifact.backend_argument
        instrument_identity = $script:InstrumentIdentity
        cleanup = $script:CleanupEvidence
        git_head = Get-GitHead
        package_version = Get-PackageVersion
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $completedAt.ToUniversalTime().ToString("o")
        result = $Result
        status = $Result
        output_dir = ConvertTo-RepoRelativePath -Path $script:ShareableArtifactDir
        shareable_artifact_dir = ConvertTo-RepoRelativePath -Path $script:ShareableArtifactDir
        preflight_report = ConvertTo-RepoRelativePath -Path $reportPath
        external_preflight = $script:ExternalPreflight
        suites = $script:SuitesToRun
        cases = $caseRecords
        planned_live_cases = $plannedLiveCases
        commands = $script:CommandRecords.ToArray()
        failures = @($script:Failures | ForEach-Object { Protect-ShareableText -Text $_ })
    }
    if ($ValidationMode -eq "live") {
        $reportFields.expected_model_id = $script:NormalizedTarget
    }
    else {
        $reportFields.planning_model_id = $script:NormalizedTarget
    }
    $report = [pscustomobject]$reportFields
    $shareableReport = ConvertTo-ShareableJsonValue -Value $report -FieldName $null -ParentName $null
    Write-Utf8NoBomFile -LiteralPath $reportPath -Value @($shareableReport | ConvertTo-Json -Depth 30)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# Powers Tool Live Validation")
    $lines.Add("")
    $lines.Add("Target: ``" + $script:NormalizedTarget + "``")
    $lines.Add("Connection: ``" + $script:ConnectionLabel + "``")
    $lines.Add("Suite: ``" + $Suite + "``")
    $lines.Add("Suites run: ``" + ($script:SuitesToRun -join ", ") + "``")
    $lines.Add("Result: ``" + $Result + "``")
    $lines.Add("PlanOnly: ``" + [bool]$PlanOnly + "``")
    $lines.Add("External preflight: ``" + $script:ExternalPreflight.status + "``")
    $lines.Add("Live executed: ``" + ($ValidationMode -eq "live") + "``")
    $lines.Add("Support policy mode: ``validation``")
    $lines.Add("Candidate evidence only: ``true``")
    $lines.Add("Promotes product support: ``false``")
    $lines.Add("Transport scope: ``" + $script:TransportScope + "``")
    $lines.Add("Backend scope: ``" + $script:BackendArtifact.backend_scope + "``")
    $lines.Add("Shareable artifact directory: ``" + (ConvertTo-RepoRelativePath -Path $script:ShareableArtifactDir) + "``")
    $lines.Add("Resource: ``" + $script:ResourceDisplay + "``")
    $lines.Add("")
    $lines.Add("## Safety Notes")
    $lines.Add("- This run produces candidate validation evidence only. Passing artifacts do not automatically promote product support.")
    $lines.Add("- This suite validates only the selected model, connection, suite, and command cases.")
    $lines.Add("- It does not validate untested features or other connections.")
    if ($script:StateChanging) {
        $lines.Add("- State-changing live cases use low-power 1 V / 0.05 A settings.")
        $lines.Add("- Safe-off cleanup does not restore original voltage/current/protection settings.")
    }
    else {
        $lines.Add("- The selected suite is non-output-affecting except for possible status/error queue reads.")
    }
    if ($script:NormalizedTarget -eq "keysight-e3646a") {
        $lines.Add("- E3646A OUTP ON/OFF is global, not an independent per-channel relay behavior.")
        $lines.Add("- E3646A ramp-list and sequence are software workflows, not native LIST.")
    }
    $lines.Add("")
    $lines.Add("## Identity And Cleanup Evidence")
    $lines.Add("- Canonical model ID: ``" + $script:NormalizedTarget + "`` (not a detected-driver override).")
    $lines.Add("- Observed identity availability: ``" + $script:InstrumentIdentity.availability + "``")
    if ($null -ne $script:InstrumentIdentity.detected_model) {
        $lines.Add("- Detected model: ``" + $script:InstrumentIdentity.detected_model + "`` from ``" + $script:InstrumentIdentity.source_command + "``.")
    }
    $lines.Add("- Cleanup status: ``" + $script:CleanupEvidence.status + "``")
    $lines.Add("- Cleanup output state checked: ``" + $script:CleanupEvidence.output_state_checked + "``; all outputs off: ``" + $script:CleanupEvidence.all_outputs_off + "``")
    $lines.Add("- Cleanup error queue checked: ``" + $script:CleanupEvidence.error_queue_checked + "``")
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
    $lines.Add("| Command | Exit | ok | mode | dry_run | JSON | SCPI/stderr |")
    $lines.Add("| --- | ---: | --- | --- | --- | --- | --- |")
    foreach ($command in $script:CommandRecords) {
        $lines.Add("| ``" + $command.name + "`` | " + $command.exit_code + " | " + $command.ok + " | " + $command.mode + " | " + $command.dry_run + " | ``" + $command.json_path + "`` | ``" + $command.stderr_scpi_path + "`` |")
    }
    if ($script:Failures.Count -gt 0) {
        $lines.Add("")
        $lines.Add("## Failures")
        foreach ($failure in $script:Failures) {
            $lines.Add("- " + (Protect-ShareableText -Text $failure))
        }
    }
    Write-Utf8NoBomFile -LiteralPath $summaryPath -Value $lines
}

$script:TransportScope = $null
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:InstrumentIdentity = $null
$script:CleanupEvidence = $null
$script:PrivateArtifactDir = $null
$script:ShareableArtifactDir = $null
$script:ExternalPreflight = [pscustomobject]@{ status = "not_run" }
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:PlannedLiveCases = @()
$script:CandidateInventory = $null

if ($env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY -eq "1") {
    return
}

$NormalizedTarget = Resolve-Target -Value $Target
$ConnectionLabel = Resolve-Connection -Value $Connection
if ([string]::IsNullOrWhiteSpace($Resource)) {
    Fail-Validation "Missing required -Resource. Pass the exact VISA resource explicitly; this script never scans or guesses a live resource."
}
if ($NormalizedTarget -eq "keysight-e3646a" -and $ConnectionLabel -ne "ASRL") {
    Fail-Validation "E3646A live validation currently requires an explicit ASRL/RS-232/serial connection."
}

$script:NormalizedTarget = $NormalizedTarget
$script:ConnectionLabel = $ConnectionLabel
$script:RawResource = $Resource
$script:ResourceDisplay = "$ConnectionLabel`:<redacted-resource>"
$script:BackendValue = $Backend
$script:TransportScope = Get-TransportScope -Connection $ConnectionLabel
$script:BackendArtifact = Get-BackendArtifactFields -Value $Backend
$script:InstrumentIdentity = $null
$script:CleanupEvidence = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]

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
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "failed"
        $script:Failures.Add("Unsupported suite '$Suite' for target $NormalizedTarget. Supported suites: $($supportedSuites -join ', ').")
        Write-ValidationArtifacts -ValidationMode "failed" -Result "failed" -StartedAt (Get-Date)
        Fail-Validation "Unsupported suite '$Suite' for target $NormalizedTarget. Supported suites: $($supportedSuites -join ', ')."
    }
    $SuitesToRun = @($Suite)
}
if (-not $PlanOnly -and -not $Restore -and "snapshot" -in $SuitesToRun) {
    Fail-Validation "Snapshot live validation requires safe-off cleanup; -Restore:`$false is not allowed."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputDir = Join-Path (Join-Path $TmpRoot "live_cli_check") ($timestamp + "_" + $NormalizedTarget + "_" + $ConnectionLabel + "_" + $Suite)
$script:OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
$script:SuitesToRun = @($SuitesToRun)
$script:StateChanging = @($SuitesToRun | Where-Object { $_ -in @("output", "protection", "snapshot", "trigger-list", "software-sequence") }).Count -gt 0
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "planned"
$script:ExternalPreflight = [pscustomobject]@{ status = "not_run" }
$startedAt = Get-Date

Ensure-ArtifactDirectories
try {
    Load-CoreCandidateInventory
}
catch {
    $script:Failures.Add("Validation build resolution failed: $($_.Exception.Message)")
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "Core candidate inventory load failed before VISA access."
    exit 1
}
$externalPreflightRoot = Join-Path $script:PrivateArtifactDir "external_preflight"
$externalPreflightStdout = Join-Path $script:PrivateArtifactDir "external_preflight.stdout.txt"
$externalPreflightStderr = Join-Path $script:PrivateArtifactDir "external_preflight.stderr.txt"
Write-Host "Running external no-hardware CLI preflight for $NormalizedTarget..."
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
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $PreflightScript -Target $NormalizedTarget -OutputRoot $externalPreflightRoot 1> $externalPreflightStdout 2> $externalPreflightStderr
    $externalPreflightExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldErrorActionPreference
    if ($hadNativePreference) { $PSNativeCommandUseErrorActionPreference = $oldNativePreference }
}
$externalReportPath = @(Get-ChildItem -LiteralPath $externalPreflightRoot -Filter report.json -File -Recurse -ErrorAction SilentlyContinue | Sort-Object { $_.FullName.Length } | Select-Object -First 1)
$script:ExternalPreflight = [pscustomobject]@{
    status = if ($externalPreflightExit -eq 0) { "passed" } else { "failed" }
    exit_code = $externalPreflightExit
    output_root = ConvertTo-RepoRelativePath -Path $externalPreflightRoot
    report = if ($externalReportPath.Count -eq 1) { ConvertTo-RepoRelativePath -Path $externalReportPath[0].FullName } else { $null }
    stdout = ConvertTo-RepoRelativePath -Path $externalPreflightStdout
    stderr = ConvertTo-RepoRelativePath -Path $externalPreflightStderr
}
if ($externalPreflightExit -ne 0) {
    $script:Failures.Add("External preflight-cli.ps1 failed before live resource access.")
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "External preflight failed; no VISA resource was opened. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))."
    exit 1
}

Write-Host "Running selected-suite no-hardware plans for $NormalizedTarget suite '$Suite'..."
$preflightCases = Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$false
foreach ($case in $preflightCases) {
    try {
        Invoke-ValidationCommand -Case $case | Out-Null
    }
    catch {
        $script:Failures.Add("$($case.name) could not be prepared: $($_.Exception.Message)")
        break
    }
}
$script:PlannedLiveCases = @(Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$true)
try {
    Assert-CandidateContextInventory -Model $NormalizedTarget -LiveCases $script:PlannedLiveCases -RequireComplete:($Suite -eq "full")
}
catch {
    $script:Failures.Add("Candidate context inventory invariant failed: $($_.Exception.Message)")
}

if ($script:Failures.Count -gt 0) {
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "Preflight failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))."
    exit 1
}

if ($PlanOnly) {
    Write-ValidationArtifacts -ValidationMode "planned" -Result "planned" -StartedAt $startedAt
    Write-Host "Plan-only validation passed."
    Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))"
    Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'summary.md'))"
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
if ($NormalizedTarget -eq "keysight-e3646a") {
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
    try {
        Invoke-ValidationCommand -Case $case | Out-Null
    }
    catch {
        $script:Failures.Add("$($case.name) could not be prepared or executed: $($_.Exception.Message)")
    }
    if ($script:Failures.Count -gt 0 -and $script:StateChanging) {
        Invoke-SafeOffCleanup -Role "failure"
        break
    }
}

if ($script:Failures.Count -eq 0 -and $script:StateChanging) {
    Invoke-SafeOffCleanup -Role "final"
}

if ($script:Failures.Count -gt 0) {
    Write-ValidationArtifacts -ValidationMode "live" -Result "failed" -StartedAt $startedAt
    Write-Error "Live validation failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))."
    exit 1
}

$liveResult = if ($script:StateChanging -and -not $Restore) { "passed_without_cleanup_verification" } else { "passed" }
Write-ValidationArtifacts -ValidationMode "live" -Result $liveResult -StartedAt $startedAt
if ($liveResult -eq "passed") {
    Write-Host "Live validation passed."
}
else {
    Write-Host "Live validation completed without cleanup verification because -Restore:`$false was selected."
}
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'summary.md'))"
