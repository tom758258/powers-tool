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
        [System.Diagnostics.Process]$Process
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
            Write-Warning "Could not request worker stop: $($_.Exception.Message)"
        }
    }

    if ($null -ne $Process -and -not $Process.HasExited) {
        if (-not $Process.WaitForExit(3000)) {
            Write-Warning "Worker did not exit after /stop; stopping local smoke process."
            Stop-Process -Id $Process.Id -Force
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
    }
    finally {
        Pop-Location
    }

    $ready = Wait-WorkerReady -Path $EventsJsonl -TimeoutSec $ReadyTimeoutSec
    $body = @{
        schema_version = 2
        command = "read-status"
        arguments = @{ dry_run = $true }
    } | ConvertTo-Json -Depth 4
    $accepted = Invoke-RestMethod `
        -Method Post `
        -Uri $ready.command_url `
        -ContentType "application/json" `
        -Body $body

    if (-not $accepted.ok) {
        throw "Worker did not accept dry-run command."
    }

    $resultPath = Join-Path $ready.artifacts_dir "jobs\$($accepted.job_id)\result.json"
    $result = Wait-ResultArtifact -Path $resultPath -TimeoutSec $ResultTimeoutSec

    if (-not $result.ok) {
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

    Write-Host "Worker orchestrator smoke passed."
    Write-Host "Job: $($accepted.job_id)"
    Write-Host "Result: $resultPath"
}
finally {
    Stop-Worker -ReadyEvent $ready -Process $worker
    $env:UV_CACHE_DIR = $previousUvCacheDir
}
