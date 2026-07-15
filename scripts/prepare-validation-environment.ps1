param(
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [string]$EnvironmentPath = ".venv-validation",
    [string]$ArtifactRoot = ".tmp_tests\validation-environment-dist",
    [string]$DevelopmentPython
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$head = (& git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $ExpectedCommit) { throw "HEAD does not match the reviewed commit." }
if (-not [string]::IsNullOrWhiteSpace((& git -C $RepoRoot status --porcelain))) { throw "A clean repository is required." }
$python = if ($DevelopmentPython) { [System.IO.Path]::GetFullPath($DevelopmentPython) } else { Join-Path $RepoRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $python)) { throw "The maintained Product development environment is required." }
$productVersion = (& $python (Join-Path $PSScriptRoot "resolve_validation_version.py") (Join-Path $RepoRoot "pyproject.toml") (Join-Path $RepoRoot "validation\pyproject.toml")).Trim()
if ($LASTEXITCODE -ne 0 -or -not $productVersion) { throw "Product and Validation versions must be valid and match." }
$validationVersion = $productVersion

$artifacts = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ArtifactRoot))
$environment = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $EnvironmentPath))
if (Test-Path -LiteralPath $artifacts) { Remove-Item -LiteralPath $artifacts -Recurse -Force }
if (Test-Path -LiteralPath $environment) { Remove-Item -LiteralPath $environment -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $artifacts "product"),(Join-Path $artifacts "validation"),(Join-Path $artifacts "wheelhouse") -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $RepoRoot "validation\build")) { Remove-Item -LiteralPath (Join-Path $RepoRoot "validation\build") -Recurse -Force }

& $python -m build --no-isolation --outdir (Join-Path $artifacts "product") $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "Product artifact build failed." }
& $python (Join-Path $RepoRoot "tests\packaging\inspect_distribution.py") --expected-version $productVersion (Join-Path $artifacts "product")
if ($LASTEXITCODE -ne 0) { throw "Product artifact inspection failed." }
& $python -m build --no-isolation --wheel --outdir (Join-Path $artifacts "validation") (Join-Path $RepoRoot "validation")
if ($LASTEXITCODE -ne 0) { throw "Validation wheel build failed." }
& $python (Join-Path $RepoRoot "validation\tests\inspect_validation_distribution.py") --expected-version $validationVersion (Join-Path $artifacts "validation")
if ($LASTEXITCODE -ne 0) { throw "Validation wheel inspection failed." }

$requirements = Join-Path $artifacts "runtime-requirements.txt"
& uv export --locked --no-dev --no-emit-workspace --format requirements.txt --output-file $requirements
if ($LASTEXITCODE -ne 0) { throw "Locked runtime dependency export failed." }
& $python -m pip download --require-hashes --only-binary=:all: --dest (Join-Path $artifacts "wheelhouse") --requirement $requirements
if ($LASTEXITCODE -ne 0) { throw "Locked runtime dependency wheelhouse creation failed." }

$productWheels = @(Get-ChildItem (Join-Path $artifacts "product\*.whl"))
$validationWheels = @(Get-ChildItem (Join-Path $artifacts "validation\*.whl"))
if ($productWheels.Count -ne 1 -or $validationWheels.Count -ne 1) { throw "Expected exactly one Product wheel and one Validation wheel." }
$productWheel = $productWheels[0]; $validationWheel = $validationWheels[0]
$productHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $productWheel.FullName).Hash.ToLowerInvariant()
$validationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $validationWheel.FullName).Hash.ToLowerInvariant()
& $python -m venv $environment
$environmentPython = Join-Path $environment "Scripts\python.exe"
& $environmentPython -m pip install --no-index --find-links (Join-Path $artifacts "wheelhouse") --requirement $requirements
if ($LASTEXITCODE -ne 0) { throw "Locked runtime dependency installation failed." }
& $environmentPython -m pip install --no-index --no-deps $productWheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Exact Product wheel installation failed." }
& $environmentPython -m pip install --no-index --no-deps $validationWheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Exact Validation wheel installation failed." }
& $environmentPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Prepared environment dependency check failed." }

$retained = Join-Path $environment ".powers-tool-validation-artifacts"
New-Item -ItemType Directory -Path $retained -Force | Out-Null
Copy-Item -LiteralPath $productWheel.FullName -Destination (Join-Path $retained $productWheel.Name)
Copy-Item -LiteralPath $validationWheel.FullName -Destination (Join-Path $retained $validationWheel.Name)
$productRecordHash = (& $environmentPython -c "from importlib import metadata; import hashlib; p=metadata.distribution('powers-tool').locate_file(metadata.distribution('powers-tool')._path.name+'/RECORD'); print(hashlib.sha256(p.read_bytes()).hexdigest())").Trim()
$validationRecordHash = (& $environmentPython -c "from importlib import metadata; import hashlib; p=metadata.distribution('powers-tool-validation').locate_file(metadata.distribution('powers-tool-validation')._path.name+'/RECORD'); print(hashlib.sha256(p.read_bytes()).hexdigest())").Trim()
$identityInput = Join-Path $artifacts "installation-identity-input.json"
$identity = [ordered]@{
    schema_version = 2; product_distribution_name = "powers-tool"; product_version = $productVersion
    product_wheel_filename = $productWheel.Name; product_wheel_sha256 = $productHash; product_installed_record_sha256 = $productRecordHash
    validation_distribution_name = "powers-tool-validation"; validation_version = $validationVersion
    validation_wheel_filename = $validationWheel.Name; validation_wheel_sha256 = $validationHash; validation_installed_record_sha256 = $validationRecordHash
    source_commit = $head; source_dirty = $false; build_time = (Get-Date).ToUniversalTime().ToString("o")
    python_version = (& $environmentPython -c "import platform; print(platform.python_version())").Trim()
}
[System.IO.File]::WriteAllText($identityInput, ($identity | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
$keyPath = Join-Path $environment ".powers-tool-validation-installation.key"
$key = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($key); [System.IO.File]::WriteAllBytes($keyPath, $key)
& $python (Join-Path $RepoRoot "scripts\write-validation-installation-identity.py") --input $identityInput --output (Join-Path $environment ".powers-tool-validation-installation.json") --key $keyPath

$oldPythonPath = $env:PYTHONPATH
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    & $environmentPython -c "import yaml,pyvisa,powers_tool_core,powers_tool_cli,powers_tool_validation; assert callable(pyvisa.ResourceManager.open_resource)"
    if ($LASTEXITCODE -ne 0) { throw "Runtime dependency smoke failed." }
    $entry = Join-Path $environment "Scripts\powers-tool-validation.exe"
    & $entry --version; if ($LASTEXITCODE -ne 0) { throw "Validation version smoke failed." }
    & $entry --help | Out-Null; if ($LASTEXITCODE -ne 0) { throw "Validation parser smoke failed." }
    & $entry output-state --help | Out-Null; if ($LASTEXITCODE -ne 0) { throw "Product-open parser smoke failed." }
    & $entry _internal-candidate-inventory --json | Out-Null; if ($LASTEXITCODE -ne 0) { throw "Candidate inventory smoke failed." }
    $parsed = (& $entry _internal-build-info --json) | ConvertFrom-Json
    if (-not $parsed.installed_runtime_verified -or -not $parsed.runtime_dependencies_verified -or -not $parsed.retained_wheels_verified -or -not $parsed.installed_files_record_verified -or $parsed.repository_source_shadowed) { throw "Installed runtime verification failed." }
}
finally { if ($null -ne $oldPythonPath) { $env:PYTHONPATH = $oldPythonPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } }
Write-Host "Prepared validation environment: version $productVersion; Product SHA-256 $productHash; Validation SHA-256 $validationHash"
