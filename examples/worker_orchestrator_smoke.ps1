param(
    [int]$ReadyTimeoutSec = 10,
    [int]$ResultTimeoutSec = 10
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
$OutputDir = Join-Path $TmpRoot "worker_orchestrator_smoke"
$ArtifactsDir = Join-Path $OutputDir "artifacts"
$EventsJsonl = Join-Path $OutputDir "events.jsonl"
$StdoutLog = Join-Path $OutputDir "worker.stdout.log"
$StderrLog = Join-Path $OutputDir "worker.stderr.log"
$UvCacheDir = Join-Path $TmpRoot "uv_cache"

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
    New-Item -ItemType Directory -Path $TmpRoot -Force | Out-Null
    Assert-UnderDirectory -Path $OutputDir -Root $TmpRoot
    if (Test-Path -LiteralPath $OutputDir) {
        $resolvedPath = (Resolve-Path -LiteralPath $OutputDir).Path
        Assert-UnderDirectory -Path $resolvedPath -Root $TmpRoot
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
}

function Read-JsonLines {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    $items = @()
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        try {
            $items += ($line | ConvertFrom-Json)
        }
        catch {
            continue
        }
    }
    return $items
}

function Wait-WorkerReady {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$TimeoutSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        foreach ($event in Read-JsonLines -Path $Path) {
            if ($event.event -eq "ready") {
                return $event
            }
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Worker did not emit ready event within $TimeoutSec seconds. See $StdoutLog and $StderrLog."
}

function Wait-ResultArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$TimeoutSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Result artifact did not appear within $TimeoutSec seconds: $Path"
}

function Stop-Worker {
    param(
        [object]$ReadyEvent,
        [System.Diagnostics.Process]$Process,
        [switch]$RequireGracefulStop
    )

    if ($null -ne $ReadyEvent -and $ReadyEvent.stop_url) {
        try {
            Invoke-RestMethod `
                -Method Post `
                -Uri $ReadyEvent.stop_url `
                -ContentType "application/json" `
                -Body "{}" | Out-Null
        }
        catch {
            if ($RequireGracefulStop) { throw }
            Write-Warning "Could not request worker stop: $($_.Exception.Message)"
        }
    }

    if ($null -ne $Process -and -not $Process.HasExited) {
        if (-not $Process.WaitForExit(3000)) {
            Write-Warning "Worker did not exit after /stop; stopping local smoke process."
            # uv owns the Worker child; terminate the whole local process tree on failure.
            & taskkill.exe /PID $Process.Id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not terminate local smoke process tree." }
            if ($RequireGracefulStop) { throw "Worker did not shut down gracefully within 3 seconds." }
        }
    }
}

Reset-OutputDirectory
New-Item -ItemType Directory -Path $UvCacheDir -Force | Out-Null

$ready = $null
$worker = $null
$previousUvCacheDir = $env:UV_CACHE_DIR

try {
    $env:UV_CACHE_DIR = $UvCacheDir
    Push-Location $RepoRoot
    try {
        $worker = Start-Process `
            -FilePath "uv" `
            -ArgumentList @(
                "run",
                "powers-tool",
                "worker",
                "--id",
                "orchestrator_smoke",
                "--mode",
                "simulate",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--control-port",
                "0",
                "--artifacts-dir",
                $ArtifactsDir,
                "--events-jsonl",
                $EventsJsonl
            ) `
            -RedirectStandardOutput $StdoutLog `
            -RedirectStandardError $StderrLog `
            -PassThru `
            -WindowStyle Hidden
        # Cache the handle before exit so Windows PowerShell retains the exit code.
        $null = $worker.Handle
    }
    finally {
        Pop-Location
    }

    $ready = Wait-WorkerReady -Path $EventsJsonl -TimeoutSec $ReadyTimeoutSec
    $body = @{
        schema_version = 3
        command = "read-status"
        arguments = @{ channel = "all" }
        job_id = "orchestrator-read-status"
        context = @{ mode = "dry_run"; planning_model_id = "keysight-e36312a" }
    } | ConvertTo-Json -Depth 4
    $accepted = Invoke-RestMethod `
        -Method Post `
        -Uri $ready.command_url `
        -ContentType "application/json" `
        -Body $body

    if ($accepted.schema_version -ne 3 -or $accepted.status -ne "accepted" -or
        $accepted.kind -ne "async_job" -or $null -ne $accepted.error -or
        $accepted.run_id -ne $ready.run_id -or
        $accepted.job_id -ne "orchestrator-read-status" -or
        -not $accepted.worker_job_id -or -not $accepted.artifact_path) {
        throw "Worker did not accept the v3 dry-run command."
    }

    $resultPath = Join-Path $accepted.artifact_path "result.json"
    $result = Wait-ResultArtifact -Path $resultPath -TimeoutSec $ResultTimeoutSec

    if ($result.schema_version -ne 2 -or $result.run_id -ne $ready.run_id -or
        $result.worker_job_id -ne $accepted.worker_job_id -or
        $result.status -ne "succeeded" -or -not $result.ok) {
        throw "Dry-run result was not ok: $($result | ConvertTo-Json -Depth 8)"
    }
    if (-not $result.execution.dry_run) {
        throw "Dry-run result did not report execution.dry_run=true."
    }
    if ($result.execution.hardware_touched) {
        throw "Dry-run result reported hardware_touched=true."
    }
    if ($null -eq $result.data.plan) {
        throw "Dry-run result did not include data.plan."
    }

    Stop-Worker -ReadyEvent $ready -Process $worker -RequireGracefulStop
    if ($worker.ExitCode -cne 0) {
        throw "Worker process exited with code $($worker.ExitCode)."
    }
    $summaries = @(Read-JsonLines -Path $EventsJsonl | Where-Object { $_.event -eq "summary" })
    if ($summaries.Count -ne 1) {
        throw "Expected exactly one final Worker summary."
    }
    $summary = $summaries[0]
    if ($summary.schema_version -ne 3 -or $summary.run_id -cne $ready.run_id -or
        $summary.ok -isnot [bool] -or $summary.ok -ne $true -or
        ($summary.exit_code -isnot [int] -and $summary.exit_code -isnot [long]) -or
        $summary.exit_code -ne 0) {
        throw "Worker shutdown summary was not successful: $($summary | ConvertTo-Json -Depth 8)"
    }

    Write-Host "Worker orchestrator smoke passed."
    Write-Host "Job: $($accepted.worker_job_id)"
    Write-Host "Result: $resultPath"
}
finally {
    try {
        if ($null -ne $worker -and -not $worker.HasExited) {
            Stop-Worker -ReadyEvent $ready -Process $worker
        }
    }
    catch {
        Write-Warning "Worker cleanup failed: $($_.Exception.Message)"
    }
    finally {
        $env:UV_CACHE_DIR = $previousUvCacheDir
    }
}
