param(
    [string]$E36312AUsbResource,
    [string]$EDU36311AUsbResource,
    [string]$Backend,
    [switch]$RunE36312AOutput,
    [switch]$RunEDUReadOnly,
    [switch]$RunIntegrationPytest
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputDir = Join-Path (Join-Path $TmpRoot "batch_validation") $timestamp
$PythonExe = Join-Path (Join-Path $RepoRoot ".venv") "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
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

function Add-BackendArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    if (-not [string]::IsNullOrWhiteSpace($Backend)) {
        return @($Arguments + @("--backend", $Backend))
    }
    return $Arguments
}

function Test-SimulatedResource {
    param([Parameter(Mandatory = $true)][string]$Resource)
    return $Resource.ToUpperInvariant().Contains("::SIM::")
}

function Get-ResourceReportValue {
    param([string]$Resource)

    if ([string]::IsNullOrWhiteSpace($Resource)) {
        return $null
    }
    if (Test-SimulatedResource -Resource $Resource) {
        return $Resource
    }
    $prefix = ($Resource -split "::", 2)[0]
    if ([string]::IsNullOrWhiteSpace($prefix)) {
        $prefix = "VISA"
    }
    return "$prefix`:<redacted-resource>"
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
    $allArgs = @(Add-BackendArgument -Arguments $Arguments) + @("--save-json", $jsonPath)

    & $PythonExe -m keysight_power_cli.cli @allArgs 1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE

    $payload = $null
    $parseError = $null
    if (Test-Path -LiteralPath $jsonPath) {
        try {
            $payload = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
        }
        catch {
            $parseError = $_.Exception.Message
        }
    }
    else {
        $parseError = "JSON output file was not created."
    }

    return [pscustomobject]@{
        name = $Name
        status = $(if ($exitCode -eq 0 -and $null -eq $parseError -and $payload.ok -eq $true) { "passed" } else { "failed" })
        reason = $null
        exit_code = $exitCode
        ok = $(if ($null -ne $payload) { [bool]$payload.ok } else { $null })
        hardware_touched = $(if ($null -ne $payload) { [bool]$payload.execution.hardware_touched } else { $null })
        error_code = $(if ($null -ne $payload -and $null -ne $payload.error) { [string]$payload.error.code } else { $null })
        parse_error = $parseError
        json_path = ConvertTo-RepoRelativePath -Path $jsonPath
        stdout_path = ConvertTo-RepoRelativePath -Path $stdoutPath
        stderr_path = ConvertTo-RepoRelativePath -Path $stderrPath
    }
}

function New-SkippedRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Reason
    )
    return [pscustomobject]@{
        name = $Name
        status = "skipped"
        reason = $Reason
        exit_code = $null
        ok = $null
        hardware_touched = $false
        error_code = $null
        parse_error = $null
        json_path = $null
        stdout_path = $null
        stderr_path = $null
    }
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$startedAt = Get-Date
$records = New-Object System.Collections.Generic.List[object]

if ($RunE36312AOutput) {
    if ([string]::IsNullOrWhiteSpace($E36312AUsbResource)) {
        $records.Add((New-SkippedRecord -Name "e36312a-output-smoke" -Reason "missing -E36312AUsbResource"))
    }
    else {
        $args = @("smoke-output", "--json", "--resource", $E36312AUsbResource, "--channel", "1", "--voltage", "1", "--current", "0.05", "--duration-ms", "500")
        if (Test-SimulatedResource -Resource $E36312AUsbResource) {
            $args += "--simulate"
        }
        else {
            $args += "--confirm"
        }
        $records.Add((Invoke-CliJsonCommand -Name "e36312a-output-smoke" -Arguments $args -JsonFileName "e36312a-output-smoke.json"))
    }
}
else {
    $records.Add((New-SkippedRecord -Name "e36312a-output-smoke" -Reason "requires -RunE36312AOutput"))
}

if ($RunEDUReadOnly) {
    if ([string]::IsNullOrWhiteSpace($EDU36311AUsbResource)) {
        $records.Add((New-SkippedRecord -Name "edu36311a-readonly" -Reason "missing -EDU36311AUsbResource"))
    }
    else {
        $args = @("validate-readonly", "--json", "--resource", $EDU36311AUsbResource)
        if (Test-SimulatedResource -Resource $EDU36311AUsbResource) {
            $args += "--simulate"
        }
        $records.Add((Invoke-CliJsonCommand -Name "edu36311a-readonly" -Arguments $args -JsonFileName "edu36311a-readonly.json"))
    }
}
else {
    $records.Add((New-SkippedRecord -Name "edu36311a-readonly" -Reason "requires -RunEDUReadOnly"))
}

if ($RunIntegrationPytest) {
    $records.Add((New-SkippedRecord -Name "integration-pytest" -Reason "run manually with the desired pytest marker and hardware flags"))
}
else {
    $records.Add((New-SkippedRecord -Name "integration-pytest" -Reason "requires -RunIntegrationPytest"))
}

$failed = @($records.ToArray() | Where-Object { $_.status -eq "failed" })
$completedAt = Get-Date
$result = if ($failed.Count -gt 0) { "failed" } else { "passed" }
$reportPath = Join-Path $OutputDir "report.json"
$summaryPath = Join-Path $OutputDir "summary.md"
$report = [pscustomobject]@{
    schema_version = "1.0"
    kind = "batch_validation"
    output_dir = ConvertTo-RepoRelativePath -Path $OutputDir
    started_at = $startedAt.ToUniversalTime().ToString("o")
    completed_at = $completedAt.ToUniversalTime().ToString("o")
    result = $result
    backend = $Backend
    resources = [pscustomobject]@{
        e36312a_usb = Get-ResourceReportValue -Resource $E36312AUsbResource
        edu36311a_usb = Get-ResourceReportValue -Resource $EDU36311AUsbResource
    }
    switches = [pscustomobject]@{
        run_e36312a_output = [bool]$RunE36312AOutput
        run_edu_readonly = [bool]$RunEDUReadOnly
        run_integration_pytest = [bool]$RunIntegrationPytest
    }
    records = $records.ToArray()
}
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Keysight Power Batch Validation")
$lines.Add("")
$lines.Add("Result: " + $result.ToUpperInvariant())
$lines.Add("")
$lines.Add("Output directory: ``" + (ConvertTo-RepoRelativePath -Path $OutputDir) + "``")
$lines.Add("")
$lines.Add("| Task | Status | Reason/Error | JSON |")
$lines.Add("| --- | --- | --- | --- |")
foreach ($record in $records) {
    $reason = $record.reason
    if ([string]::IsNullOrWhiteSpace($reason)) {
        $reason = $record.error_code
    }
    $lines.Add("| ``" + $record.name + "`` | " + $record.status + " | " + $reason + " | ``" + $record.json_path + "`` |")
}
$lines | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Batch validation $result."
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path $reportPath)"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path $summaryPath)"
if ($result -ne "passed") {
    exit 1
}
