param(
    [string]$DistPath = "dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

$pythonBits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if ($pythonBits.Trim() -ne "64") {
    throw "Windows shared bundle requires 64-bit Python; detected $($pythonBits.Trim())-bit Python"
}

$tkProbe = @'
import sys
import tkinter as tk

root = None
try:
    root = tk.Tk()
    root.withdraw()
except Exception:
    sys.exit(1)
finally:
    if root is not None:
        root.destroy()
'@
& $Python -c $tkProbe | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Windows shared bundle includes a Tkinter WebUI Launcher and requires a working Tcl/Tk runtime; no bundle was built."
}

if ([System.IO.Path]::IsPathRooted($DistPath)) {
    $distFull = [System.IO.Path]::GetFullPath($DistPath)
} else {
    $distFull = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $DistPath))
}
$repoFull = [System.IO.Path]::GetFullPath($RepoRoot)
$repoPrefix = $repoFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not (
    $distFull.Equals($repoFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $distFull.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)
)) {
    throw "DistPath must stay under the repository: $distFull"
}

$bundlePath = Join-Path $distFull "powers-tool"
if (Test-Path -LiteralPath $bundlePath) {
    Remove-Item -LiteralPath $bundlePath -Recurse -Force
}

$specPath = Join-Path $RepoRoot "scripts\powers-tool-windows.spec"
$workPath = Join-Path $RepoRoot "build\pyinstaller-windows"

# Keep the bundled LGPL library version aligned with the reviewed notice.
$zeroconfVersion = & $Python -c "from importlib.metadata import version; print(version('zeroconf'))"
if ($LASTEXITCODE -ne 0 -or "$zeroconfVersion".Trim() -ne "0.151.5") {
    throw "Installed zeroconf version '$zeroconfVersion' differs from the reviewed 0.151.5 license notice. Update notices before building."
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distFull `
    --workpath $workPath `
    $specPath

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

# Preserve project and LGPL library license notices in the shared onedir
# bundle; Desktop and release packaging copy this directory unchanged.
$noticePaths = @(
    "LICENSE",
    "THIRD_PARTY_NOTICES.txt",
    "third_party/licenses/zeroconf-COPYING"
)
if (-not (Test-Path -LiteralPath $bundlePath -PathType Container)) {
    throw "Windows bundle directory not found: $bundlePath"
}
foreach ($relativePath in $noticePaths) {
    $sourceNotice = Join-Path $RepoRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourceNotice -PathType Leaf)) {
        throw "Required license notice not found: $sourceNotice"
    }
    $targetNotice = Join-Path $bundlePath $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetNotice) | Out-Null
    Copy-Item -LiteralPath $sourceNotice -Destination $targetNotice -Force
    if (-not (Test-Path -LiteralPath $targetNotice -PathType Leaf)) {
        throw "License notice was not copied into the bundle: $targetNotice"
    }
}
