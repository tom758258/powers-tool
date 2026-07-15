param(
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [string]$EnvironmentPath = ".venv-validation",
    [string]$ArtifactRoot = ".tmp_tests\validation-environment-dist"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$head = (& git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $ExpectedCommit) { throw "HEAD does not match the reviewed commit." }
if (-not [string]::IsNullOrWhiteSpace((& git -C $RepoRoot status --porcelain))) { throw "A clean repository is required." }

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "The maintained Product development environment is required." }
$artifacts = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ArtifactRoot))
$environment = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $EnvironmentPath))
if (Test-Path -LiteralPath $artifacts) { Remove-Item -LiteralPath $artifacts -Recurse -Force }
if (Test-Path -LiteralPath $environment) { Remove-Item -LiteralPath $environment -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $artifacts "product"),(Join-Path $artifacts "validation") -Force | Out-Null

& $python -m build --no-isolation --outdir (Join-Path $artifacts "product") $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "Product wheel build failed." }
& $python (Join-Path $RepoRoot "tests\packaging\inspect_distribution.py") --expected-version 2.0.0 (Join-Path $artifacts "product")
if ($LASTEXITCODE -ne 0) { throw "Product wheel inspection failed." }
& $python -m build --no-isolation --wheel --outdir (Join-Path $artifacts "validation") (Join-Path $RepoRoot "validation")
if ($LASTEXITCODE -ne 0) { throw "Validation wheel build failed." }
& $python (Join-Path $RepoRoot "validation\tests\inspect_validation_distribution.py") --expected-version 2.0.0 (Join-Path $artifacts "validation")
if ($LASTEXITCODE -ne 0) { throw "Validation wheel inspection failed." }

$productWheels = @(Get-ChildItem (Join-Path $artifacts "product\*.whl"))
$validationWheels = @(Get-ChildItem (Join-Path $artifacts "validation\*.whl"))
if ($productWheels.Count -ne 1 -or $validationWheels.Count -ne 1) { throw "Expected exactly one Product wheel and one Validation wheel." }
$productWheel = $productWheels[0]
$validationWheel = $validationWheels[0]
$productHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $productWheel.FullName).Hash.ToLowerInvariant()
$validationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $validationWheel.FullName).Hash.ToLowerInvariant()
& $python -m venv $environment
$environmentPython = Join-Path $environment "Scripts\python.exe"
& $environmentPython -m pip install --no-index --no-deps $productWheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Exact Product wheel installation failed." }
& $environmentPython -m pip install --no-index --no-deps $validationWheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Exact Validation wheel installation failed." }

$identityInput = Join-Path $artifacts "installation-identity-input.json"
$identity = [ordered]@{
    schema_version = 1; product_distribution_name = "powers-tool"; product_version = "2.0.0"
    product_wheel_filename = $productWheel.Name; product_wheel_sha256 = $productHash
    validation_distribution_name = "powers-tool-validation"; validation_version = "2.0.0"
    validation_wheel_filename = $validationWheel.Name; validation_wheel_sha256 = $validationHash
    source_commit = $head; source_dirty = $false; build_time = (Get-Date).ToUniversalTime().ToString("o")
    python_version = (& $environmentPython -c "import platform; print(platform.python_version())").Trim()
}
[System.IO.File]::WriteAllText($identityInput, ($identity | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
$keyPath = Join-Path $environment ".powers-tool-validation-installation.key"
$key = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($key)
[System.IO.File]::WriteAllBytes($keyPath, $key)
& $python (Join-Path $RepoRoot "scripts\write-validation-installation-identity.py") --input $identityInput --output (Join-Path $environment ".powers-tool-validation-installation.json") --key $keyPath
$oldPythonPath = $env:PYTHONPATH
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $buildInfo = & (Join-Path $environment "Scripts\powers-tool-validation.exe") _internal-build-info --json
    if ($LASTEXITCODE -ne 0) { throw "Installed Validation entry point verification failed." }
    $parsed = $buildInfo | ConvertFrom-Json
    if (-not $parsed.installed_runtime_verified -or $parsed.repository_source_shadowed) { throw "Installed runtime isolation verification failed." }
}
finally { if ($null -ne $oldPythonPath) { $env:PYTHONPATH = $oldPythonPath } }
Write-Host "Prepared validation environment: Product SHA-256 $productHash; Validation SHA-256 $validationHash"
