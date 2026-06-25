param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$OutputDir = ".tmp_tests\no_hardware_regression"
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][AllowEmptyString()][string[]]$Value
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($LiteralPath, $Value, $encoding)
}

$commands = @(
    @{
        Name = "followup-features"
        Args = @("-m", "pytest", "tests\cli\test_followup_features.py", "-q")
    },
    @{
        Name = "json-contract-docs"
        Args = @("-m", "pytest", "tests\cli\test_cli_json_contract.py", "tests\cli\test_supported_models_docs.py", "-q")
    },
    @{
        Name = "full-pytest"
        Args = @("-m", "pytest", "-q")
    }
)

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$runId = Get-Date -Format "yyyyMMdd_HHmmss_fff"

$results = @()
$failed = $false

foreach ($command in $commands) {
    $started = Get-Date
    $pytestTemp = Join-Path $OutputDir ("pytest_" + $runId + "_" + $command.Name)
    $argsWithTemp = @($command.Args) + @("-p", "no:cacheprovider", "--basetemp", $pytestTemp)
    & $Python @argsWithTemp
    $exitCode = $LASTEXITCODE
    $finished = Get-Date
    $result = [ordered]@{
        name = $command.Name
        command = "$Python $($argsWithTemp -join ' ')"
        exit_code = $exitCode
        duration_ms = [int][Math]::Round(($finished - $started).TotalMilliseconds)
    }
    $results += $result
    if ($exitCode -ne 0) {
        $failed = $true
        break
    }
}

$report = [ordered]@{
    ok = -not $failed
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    commands = $results
    failed_command = $(if ($failed) { $results[-1].name } else { $null })
}

$reportJson = Join-Path $OutputDir "report.json"
$summaryMd = Join-Path $OutputDir "summary.md"
Write-Utf8NoBomFile -LiteralPath $reportJson -Value @($report | ConvertTo-Json -Depth 5)

$summary = @()
$summary += "# No-Hardware Regression"
$summary += ""
$summary += "Result: $(if ($failed) { 'failed' } else { 'passed' })"
$summary += ""
$summary += "| Command | Exit Code | Duration ms |"
$summary += "| --- | ---: | ---: |"
foreach ($result in $results) {
    $summary += "| ``$($result.command)`` | $($result.exit_code) | $($result.duration_ms) |"
}
if ($failed) {
    $summary += ""
    $summary += "Failed command: ``$($results[-1].command)``"
}
Write-Utf8NoBomFile -LiteralPath $summaryMd -Value $summary

if ($failed) {
    exit 1
}
exit 0
