param(
    [string]$Version,
    [string]$ReleaseRoot = "release"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

function Get-ProjectVersion {
    $pyproject = Join-Path $RepoRoot "pyproject.toml"
    $match = Select-String -LiteralPath $pyproject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($null -eq $match) {
        throw "Could not read project version from $pyproject"
    }
    return $match.Matches[0].Groups[1].Value
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Value
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($LiteralPath, $Value, $encoding)
}

function Get-Sha256File {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath
    )

    $stream = $null
    $sha256 = $null
    try {
        $stream = [System.IO.File]::Open(
            $LiteralPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $hash = $sha256.ComputeHash($stream)
        return [System.BitConverter]::ToString($hash).Replace("-", "").ToLowerInvariant()
    } finally {
        if ($null -ne $sha256) { $sha256.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-ProjectVersion
}

if ([System.IO.Path]::IsPathRooted($ReleaseRoot)) {
    $releaseRootFull = [System.IO.Path]::GetFullPath($ReleaseRoot)
} else {
    $releaseRootFull = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ReleaseRoot))
}
$repoFull = [System.IO.Path]::GetFullPath($RepoRoot)
$repoPrefix = $repoFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not (
    $releaseRootFull.Equals($repoFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $releaseRootFull.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)
)) {
    throw "ReleaseRoot must stay under the repository: $releaseRootFull"
}

$versionDir = Join-Path $releaseRootFull $Version
New-Item -ItemType Directory -Force -Path $versionDir | Out-Null

& $Python -m build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $Python (Join-Path $RepoRoot "tests\packaging\inspect_distribution.py") --expected-version $Version (Join-Path $RepoRoot "dist")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_cli_exe.ps1") -DistPath $versionDir -Name "powers-tool-$Version"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_webui_exe.ps1") -DistPath $versionDir -Name "powers-tool-webui-$Version"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Copy-Item -LiteralPath (Join-Path $RepoRoot "dist\powers_tool-$Version-py3-none-any.whl") -Destination $versionDir -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "dist\powers_tool-$Version.tar.gz") -Destination $versionDir -Force

$checksums = foreach ($artifact in Get-ChildItem -LiteralPath $versionDir -File | Sort-Object Name) {
    $hash = Get-Sha256File -LiteralPath $artifact.FullName
    "$hash  $($artifact.Name)"
}
Write-Utf8NoBomFile -LiteralPath (Join-Path $versionDir "checksums.txt") -Value $checksums

Write-Host "release artifacts: $versionDir"
