param(
    [string]$Python310 = "",
    [string]$CurrentPython = "",
    [string]$OutputRoot = ".tmp_tests\release_acceptance",
    [switch]$KeepWorktree,
    [switch]$IncludeWorkingTreeChanges,
    [switch]$InterpreterPreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:Commands = @()
$script:InstallChecks = [System.Collections.ArrayList]::new()
$script:EntryPointChecks = [System.Collections.ArrayList]::new()
$script:StandaloneChecks = [System.Collections.ArrayList]::new()
$script:LegacyChecks = [System.Collections.ArrayList]::new()
$script:DocumentationChecks = [System.Collections.ArrayList]::new()
$script:BuildArtifacts = @()
$script:FailedStep = $null
$script:FailureMessage = $null
$script:Ok = $false
$script:CurrentStep = "initialization"
$script:WorktreePath = $null
$script:RunRoot = $null
$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$script:PythonVersions = @{}
$script:FullAcceptanceCompleted = $false
$sourceCommit = $null
$sourceBranch = $null
$projectVersion = $null
$distributionName = $null
$initialStatus = @()
$cleanStatusBeforeOverlay = @()
$candidatePaths = @()
$candidateFileHashes = @()
$candidatePatchSha256 = $null
$candidatePatchPath = $null
$resolvedPython310 = $null
$resolvedCurrent = $null
$python310Metadata = $null
$currentPythonMetadata = $null
$interpretersDistinct = $null
$acceptanceWorktreeState = "not-created"
$acceptanceMode = if ($InterpreterPreflightOnly -and $IncludeWorkingTreeChanges) {
    "candidate-interpreter-preflight"
} elseif ($InterpreterPreflightOnly) {
    "interpreter-preflight"
} elseif ($IncludeWorkingTreeChanges) {
    "candidate-working-tree"
} else {
    "final-committed-clean-head"
}
$allowedCandidatePaths = @(
    ".github/workflows/tests.yml",
    "CHANGELOG.md",
    "MANIFEST.in",
    "README.md",
    "pyproject.toml",
    "docs/cli/README.md",
    "docs/core/README.md",
    "docs/core/supported-models.md",
    "scripts/build_release.ps1",
    "scripts/_validation_helpers.ps1",
    "scripts/live-cli-check.ps1",
    "scripts/preflight-cli.ps1",
    "scripts/release-acceptance.ps1",
    "src/powers_tool_cli/candidate_capability.py",
    "src/powers_tool_cli/cli.py",
    "src/powers_tool_core/build_profile.py",
    "src/powers_tool_core/core.py",
    "src/powers_tool_core/live_support.py",
    "src/powers_tool_core/support_policy.py",
    "tests/packaging/_inspector_utils.py",
    "tests/packaging/inspect_distribution.py",
    "tests/packaging/inspect_pyinstaller.py",
    "tests/packaging/test_packaging_identity.py",
    "tests/cli/test_cli_wrappers.py",
    "tests/cli/test_followup_features.py",
    "tests/cli/test_live_cli_check_script.py",
    "tests/cli/test_candidate_capability.py",
    "tests/cli/test_product_candidate_isolation.py",
    "tests/cli/test_supported_models_docs.py",
    "tests/core/test_model_enablement.py",
    "tests/core/test_live_support_policy_enforcement.py",
    "tests/packaging/test_distribution_isolation.py",
    "tests/packaging/test_release_acceptance.py",
    "validation/pyproject.toml",
    "validation/setup.py",
    "validation/src/powers_tool_validation/__init__.py",
    "validation/src/powers_tool_validation/__main__.py",
    "validation/src/powers_tool_validation/build_identity.py",
    "validation/src/powers_tool_validation/candidate_capability.py",
    "validation/src/powers_tool_validation/cli.py",
    "validation/src/powers_tool_validation/runtime_extension.py",
    "validation/tests/inspect_validation_distribution.py",
    "validation/tests/test_candidate_capability.py",
    "validation/tests/test_validation_runtime.py",
    "uv.lock"
)

# Local/, README.zh-TW.md, and generated localized files are outside this script's write scope.

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LiteralPath, $Content, $encoding)
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

function Get-ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$CandidatePath
    )

    if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
        $full = [System.IO.Path]::GetFullPath($CandidatePath)
    } else {
        $full = [System.IO.Path]::GetFullPath((Join-Path $BasePath $CandidatePath))
    }
    $base = [System.IO.Path]::GetFullPath($BasePath).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $prefix = $base + [System.IO.Path]::DirectorySeparatorChar
    if (-not ($full.Equals($base, [System.StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Path must stay under ${base}: $full"
    }
    return $full
}

function Get-ReportPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $full = [System.IO.Path]::GetFullPath($Path)
    $run = $script:RunRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if ($full.StartsWith($run, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($run.Length).Replace([System.IO.Path]::DirectorySeparatorChar, "/")
    }
    return $full
}

function Invoke-Recorded {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string]$Interpreter = "",
        [int]$TimeoutSeconds = 0
    )

    $started = Get-Date
    $lines = @()
    $exitCode = 1
    $previousErrorActionPreference = $ErrorActionPreference
    if ($TimeoutSeconds -gt 0) {
        $captureId = [guid]::NewGuid().ToString("N")
        $stdoutPath = Join-Path $script:RunRoot ($captureId + ".stdout")
        $stderrPath = Join-Path $script:RunRoot ($captureId + ".stderr")
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $lines = @("Command timed out after $TimeoutSeconds seconds")
            $exitCode = -1
        } else {
            $process.WaitForExit()
            $exitCode = [int]$process.ExitCode
            $lines = @(
                @(Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue)
                @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)
            )
        }
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    } else {
        Push-Location -LiteralPath $WorkingDirectory
        try {
            # Native tools may write normal progress to stderr; evaluate their exit code explicitly.
            $ErrorActionPreference = "Continue"
            $lines = @(& $FilePath @Arguments 2>&1)
            $exitCode = [int]$LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
            Pop-Location
        }
    }
    $finished = Get-Date
    $output = (($lines | ForEach-Object { [string]$_ }) -join "`n")
    if ($output.Length -gt 12000) {
        $output = $output.Substring($output.Length - 12000)
    }
    $record = [ordered]@{
        name = $Name
        command = ((@($FilePath) + $Arguments) -join " ")
        working_directory = (Get-ReportPath -Path $WorkingDirectory)
        interpreter = $Interpreter
        python_version = if ($Interpreter -and $script:PythonVersions.ContainsKey($Interpreter)) {
            $script:PythonVersions[$Interpreter]
        } else {
            $null
        }
        exit_code = $exitCode
        duration_ms = [int][Math]::Round(($finished - $started).TotalMilliseconds)
        output_tail = $output
    }
    $script:Commands += ,$record
    if ($output) {
        $lines | ForEach-Object { Write-Host $_ }
    }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode"
    }
    return $output
}

function Get-PythonMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $metadataCode = 'import sys; print(sys.version_info.major); print(sys.version_info.minor); print(sys.version); print(sys.executable)'
    $output = Invoke-Recorded -Name ("python-metadata-" + $Name) -FilePath $Python `
        -Arguments @("-c", $metadataCode) -WorkingDirectory $script:RunRoot -Interpreter $Python
    $lines = @($output -split "`r?`n")
    if ($lines.Count -lt 4) {
        throw "$Name interpreter returned invalid metadata: $Python"
    }
    $metadata = [pscustomobject]@{
        major = [int]$lines[0]
        minor = [int]$lines[1]
        version = [string]$lines[2]
        executable = [System.IO.Path]::GetFullPath([string]$lines[3])
    }
    $script:PythonVersions[$Python] = [string]$metadata.version
    return $metadata
}

function Assert-PythonVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Metadata,
        [Parameter(Mandatory = $true)][int]$ExpectedMajor,
        [Parameter(Mandatory = $true)][int]$ExpectedMinor
    )

    if ([int]$Metadata.major -ne $ExpectedMajor -or [int]$Metadata.minor -ne $ExpectedMinor) {
        $expected = "$ExpectedMajor.$ExpectedMinor"
        $actual = "$($Metadata.major).$($Metadata.minor) ($($Metadata.version))"
        throw "$Name interpreter version mismatch: path=$Path; expected Python $expected; actual Python $actual"
    }
}

function Resolve-Python {
    param(
        [string]$Requested,
        [Parameter(Mandatory = $true)][string]$VersionSelector,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($Requested) {
        $candidate = [System.IO.Path]::GetFullPath($Requested)
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "$Name interpreter was not found: $candidate"
        }
        return $candidate
    }
    $resolved = Invoke-Recorded -Name ("resolve-" + $Name) -FilePath "uv" `
        -Arguments @("python", "find", $VersionSelector) -WorkingDirectory $script:RepoRoot
    $candidate = ($resolved -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1).Trim()
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "uv did not return a usable $Name interpreter: $candidate"
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

function Sync-ProjectEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EnvironmentPath,
        [Parameter(Mandatory = $true)][string]$Python
    )

    if ((Test-Path -LiteralPath $EnvironmentPath) -and
        (Get-ChildItem -LiteralPath $EnvironmentPath -Force | Select-Object -First 1)) {
        throw "Refusing to reuse non-empty environment: $EnvironmentPath"
    }
    $env:UV_PROJECT_ENVIRONMENT = $EnvironmentPath
    Invoke-Recorded -Name ("sync-" + $Name) -FilePath "uv" `
        -Arguments @("sync", "--python", $Python, "--locked", "--all-extras", "--reinstall-package", "powers-tool", "--link-mode=copy") `
        -WorkingDirectory $script:WorktreePath | Out-Null
    $pythonExe = Join-Path $EnvironmentPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "Environment did not produce Python: $pythonExe"
    }
    Get-PythonMetadata -Python $pythonExe -Name ("environment-" + $Name) | Out-Null
    return $pythonExe
}

function New-ArtifactEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EnvironmentPath,
        [Parameter(Mandatory = $true)][string]$Python
    )

    Invoke-Recorded -Name ("venv-" + $Name) -FilePath "uv" `
        -Arguments @("venv", $EnvironmentPath, "--python", $Python) `
        -WorkingDirectory $script:RunRoot | Out-Null
    $pythonExe = Join-Path $EnvironmentPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "Artifact environment did not produce Python: $pythonExe"
    }
    Get-PythonMetadata -Python $pythonExe -Name ("artifact-environment-" + $Name) | Out-Null
    return $pythonExe
}

function Run-Python {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    return Invoke-Recorded -Name $Name -FilePath $Python -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory -Interpreter $Python
}

function Assert-Contains {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Needle,
        [Parameter(Mandatory = $true)][string]$Context
    )
    if ($Text.IndexOf($Needle, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Missing expected text in ${Context}: $Needle"
    }
}

function Assert-File {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing required artifact: $Path"
    }
}

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.IList]$Target,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [string]$Detail = ""
    )
    $Target.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail }) | Out-Null
    if (-not $Passed) {
        throw "Acceptance check failed: $Name"
    }
}

function Remove-GeneratedDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Test-InstalledEntryPoints {
    param(
        [Parameter(Mandatory = $true)][string]$Scope,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][System.Collections.IList]$Target
    )

    $scripts = Split-Path -Parent $Python
    $checks = @(
        @("powers-tool", "powers-tool $projectVersion", "Safe Powers Tool CLI for supported DC power supplies."),
        @("powers-tool-webui", "powers-tool-webui $projectVersion", "Powers Tool WebUI Server"),
        @("powers-tool-webui-launcher", "powers-tool-webui-launcher $projectVersion", "Powers Tool WebUI Launcher")
    )
    foreach ($check in $checks) {
        $exe = Join-Path $scripts ($check[0] + ".exe")
        Assert-File -Path $exe
        $versionOutput = Invoke-Recorded -Name ($Scope + "-" + $check[0] + "-version") `
            -FilePath $exe -Arguments @("--version") -WorkingDirectory $script:RunRoot `
            -Interpreter $Python -TimeoutSeconds 30
        Add-Check -Target $Target -Name ($Scope + " " + $check[0] + " --version") `
            -Passed ($versionOutput.Trim() -eq $check[1]) -Detail $versionOutput.Trim()
        $helpOutput = Invoke-Recorded -Name ($Scope + "-" + $check[0] + "-help") `
            -FilePath $exe -Arguments @("--help") -WorkingDirectory $script:RunRoot `
            -Interpreter $Python -TimeoutSeconds 30
        Add-Check -Target $Target -Name ($Scope + " " + $check[0] + " --help") `
            -Passed ($helpOutput.Contains($check[2])) -Detail $check[2]
    }

    foreach ($legacy in @("keysight-power", "keysight-power-webui", "keysight-power-webui-launcher")) {
        $legacyExe = Join-Path $scripts ($legacy + ".exe")
        $legacyScript = Join-Path $scripts ($legacy + "-script.py")
        Add-Check -Target $script:LegacyChecks -Name ($Scope + " legacy command absent: " + $legacy) `
            -Passed (-not (Test-Path -LiteralPath $legacyExe) -and -not (Test-Path -LiteralPath $legacyScript))
    }
}

function Get-StatusPath {
    param([Parameter(Mandatory = $true)][string]$StatusLine)

    $path = $StatusLine.Substring(3).Trim()
    if ($path.Contains(" -> ")) {
        $path = $path.Split(@(" -> "), [System.StringSplitOptions]::None)[-1]
    }
    return $path.Replace("\", "/")
}

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is required"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required"
    }

    $sourceCommit = (& git -C $script:RepoRoot rev-parse HEAD).Trim()
    $sourceBranch = (& git -C $script:RepoRoot branch --show-current).Trim()
    if (-not $sourceBranch) { $sourceBranch = "detached" }
    $initialStatus = @(& git -C $script:RepoRoot status --short --untracked-files=all 2>&1)

    $outputFull = Get-ContainedPath -BasePath $script:RepoRoot -CandidatePath $OutputRoot
    New-Item -ItemType Directory -Force -Path $outputFull | Out-Null
    $runName = "r_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $script:RunRoot = Join-Path $outputFull $runName
    New-Item -ItemType Directory -Force -Path $script:RunRoot | Out-Null
    $script:WorktreePath = Join-Path $script:RunRoot "worktree"
    $uvCache = Join-Path $script:RunRoot "uv-cache"
    New-Item -ItemType Directory -Force -Path $uvCache | Out-Null
    $env:UV_CACHE_DIR = $uvCache
    $env:PYTHONNOUSERSITE = "1"
    foreach ($name in @("PYTHONPATH", "PYTHONHOME", "UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV")) {
        if (Test-Path "Env:$name") { Remove-Item "Env:$name" }
    }

    if ($IncludeWorkingTreeChanges) {
        $candidatePaths = @($initialStatus | ForEach-Object { Get-StatusPath -StatusLine ([string]$_) } | Sort-Object -Unique)
        if ($candidatePaths.Count -eq 0) {
            throw "IncludeWorkingTreeChanges was requested, but the source worktree is clean"
        }
        $unexpectedCandidatePaths = @(Compare-Object -ReferenceObject $allowedCandidatePaths `
            -DifferenceObject $candidatePaths -PassThru | Where-Object { $_ -in $candidatePaths })
        if ($unexpectedCandidatePaths.Count -ne 0) {
            throw "Candidate overlay contains paths outside the release acceptance allowlist: $($unexpectedCandidatePaths -join ', ')"
        }
        foreach ($relative in $candidatePaths) {
            $sourcePath = Join-Path $script:RepoRoot $relative
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
                throw "Candidate overlay may not delete or replace a file with a non-file path: $relative"
            }
            $candidateFileHashes += ,([ordered]@{
                path = $relative
                sha256 = Get-Sha256File -LiteralPath $sourcePath
            })
        }
        $candidatePatchPath = Join-Path $script:RunRoot "working-tree.patch"
        Invoke-Recorded -Name "capture-working-tree-diff" -FilePath "git" `
            -Arguments @("-C", $script:RepoRoot, "-c", "core.autocrlf=false", "diff", "--binary", "--output=$candidatePatchPath") `
            -WorkingDirectory $script:RepoRoot | Out-Null
        $candidatePatchSha256 = Get-Sha256File -LiteralPath $candidatePatchPath
    }

    $pyprojectPath = Join-Path $script:RepoRoot "pyproject.toml"
    $pyprojectText = Get-Content -LiteralPath $pyprojectPath -Raw
    $nameMatch = [regex]::Match($pyprojectText, '(?m)^name\s*=\s*"([^"]+)"')
    $versionMatch = [regex]::Match($pyprojectText, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $nameMatch.Success -or -not $versionMatch.Success) { throw "Could not read project metadata" }
    $distributionName = $nameMatch.Groups[1].Value
    $projectVersion = $versionMatch.Groups[1].Value
    if ($distributionName -ne "powers-tool") {
        throw "Unexpected project identity: $distributionName $projectVersion"
    }

    $script:CurrentStep = "interpreter preflight"
    $resolvedPython310 = Resolve-Python -Requested $Python310 -VersionSelector "3.10" -Name "python310"
    $resolvedCurrent = Resolve-Python -Requested $CurrentPython -VersionSelector "3.13" -Name "current-python"
    $python310Metadata = Get-PythonMetadata -Python $resolvedPython310 -Name "python310"
    $currentPythonMetadata = Get-PythonMetadata -Python $resolvedCurrent -Name "current-python"
    $sameRequestedPath = $resolvedPython310.Equals($resolvedCurrent, [System.StringComparison]::OrdinalIgnoreCase)
    $sameExecutable = ([string]$python310Metadata.executable).Equals(
        [string]$currentPythonMetadata.executable,
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $interpretersDistinct = -not ($sameRequestedPath -or $sameExecutable)
    if (-not $interpretersDistinct) {
        throw "Python interpreters must be distinct files: Python310=$resolvedPython310; CurrentPython=$resolvedCurrent"
    }
    Assert-PythonVersion -Name "Python310" -Path $resolvedPython310 -Metadata $python310Metadata `
        -ExpectedMajor 3 -ExpectedMinor 10
    Assert-PythonVersion -Name "CurrentPython" -Path $resolvedCurrent -Metadata $currentPythonMetadata `
        -ExpectedMajor 3 -ExpectedMinor 13

    if ($InterpreterPreflightOnly) {
        $script:Ok = $true
    } else {
        $script:CurrentStep = "create isolated worktree"
        Invoke-Recorded -Name "worktree-add" -FilePath "git" `
            -Arguments @("-C", $script:RepoRoot, "worktree", "add", "--detach", $script:WorktreePath, $sourceCommit) `
            -WorkingDirectory $script:RepoRoot | Out-Null
        $acceptanceWorktreeState = "detached"
        $cleanStatusBeforeOverlay = @(& git -C $script:WorktreePath status --short --untracked-files=all 2>&1)
        if ($cleanStatusBeforeOverlay.Count -ne 0) {
            throw "Temporary worktree is not clean before overlay: $($cleanStatusBeforeOverlay -join '; ')"
        }
        if ($IncludeWorkingTreeChanges) {
            if ((Get-Item -LiteralPath $candidatePatchPath).Length -gt 0) {
                Invoke-Recorded -Name "apply-working-tree-diff" -FilePath "git" `
                    -Arguments @("-C", $script:WorktreePath, "-c", "core.autocrlf=false", "apply", "--binary", "--whitespace=nowarn", "--ignore-space-change", $candidatePatchPath) `
                    -WorkingDirectory $script:WorktreePath | Out-Null
            }
            $untracked = @(& git -C $script:RepoRoot ls-files --others --exclude-standard)
            foreach ($relative in $untracked) {
                if (-not $relative) { continue }
                $sourcePath = Join-Path $script:RepoRoot $relative
                $targetPath = Join-Path $script:WorktreePath $relative
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
                Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
            }
            $overlayStatus = @(& git -C $script:WorktreePath status --short --untracked-files=all)
            $overlayPaths = @($overlayStatus | ForEach-Object { Get-StatusPath -StatusLine ([string]$_) } | Sort-Object -Unique)
            if (@(Compare-Object -ReferenceObject $candidatePaths -DifferenceObject $overlayPaths).Count -ne 0) {
                throw "Candidate overlay paths differ from the reviewed source paths"
            }
        }
        $pyprojectPath = Join-Path $script:WorktreePath "pyproject.toml"
        $pyprojectText = Get-Content -LiteralPath $pyprojectPath -Raw
        $nameMatch = [regex]::Match($pyprojectText, '(?m)^name\s*=\s*"([^"]+)"')
        $versionMatch = [regex]::Match($pyprojectText, '(?m)^version\s*=\s*"([^"]+)"')
        if (-not $nameMatch.Success -or -not $versionMatch.Success) { throw "Could not read project metadata" }
        $distributionName = $nameMatch.Groups[1].Value
        $projectVersion = $versionMatch.Groups[1].Value
        if ($distributionName -ne "powers-tool") {
            throw "Unexpected project identity: $distributionName $projectVersion"
        }
        $worktreeTmp = Join-Path $script:WorktreePath ".tmp_tests\release_acceptance_work"
        New-Item -ItemType Directory -Force -Path $worktreeTmp | Out-Null

    $script:CurrentStep = "locked source environments"
    $python310Env = Join-Path $script:RunRoot "envs\python310"
    $currentEnvPath = Join-Path $script:WorktreePath ".venv"
    $python310 = Sync-ProjectEnvironment -Name "python310" -EnvironmentPath $python310Env -Python $resolvedPython310
    $current = Sync-ProjectEnvironment -Name "current" -EnvironmentPath $currentEnvPath -Python $resolvedCurrent

    $identityCode = @'
import importlib.metadata as metadata
import importlib.resources as resources
import importlib.util
import powers_tool_cli
import powers_tool_core
import powers_tool_webui

expected_version = "__PROJECT_VERSION__"
assert metadata.version("powers-tool") == expected_version
assert powers_tool_core.__version__ == expected_version
assert powers_tool_cli.__version__ == expected_version
assert powers_tool_webui.__version__ == expected_version
for legacy in ("keysight_power_core", "keysight_power_cli", "keysight_power_webui"):
    assert importlib.util.find_spec(legacy) is None, legacy
static = resources.files("powers_tool_webui").joinpath("static")
for filename in ("index.html", "styles.css", "app.js"):
    assert static.joinpath(filename).is_file(), filename
'@
    $identityCode = $identityCode.Replace("__PROJECT_VERSION__", $projectVersion)
    $identityScript = Join-Path $script:RunRoot "identity_check.py"
    Write-Utf8NoBomFile -LiteralPath $identityScript -Content $identityCode
    $script:CurrentStep = "source identity checks"
    foreach ($pair in @(@("python310", $python310), @("current", $current))) {
        Run-Python -Name ("identity-" + $pair[0]) -Python $pair[1] -WorkingDirectory $script:RunRoot `
            -Arguments @($identityScript) | Out-Null
    }

    $focusedTests = @(
        "tests\core\test_distribution_metadata.py",
        "tests\core\test_import.py",
        "tests\cli\test_cli.py",
        "tests\packaging\test_packaging_identity.py",
        "tests\packaging\test_release_acceptance.py",
        "tests\webui\test_webui_import.py",
        "tests\webui\test_launcher.py"
    )
    $script:CurrentStep = "focused release acceptance tests"
    foreach ($pair in @(@("python310", $python310), @("current", $current))) {
        Run-Python -Name ("pytest-focused-" + $pair[0]) -Python $pair[1] `
            -WorkingDirectory $script:WorktreePath -Arguments (@(
                "-m", "pytest"
            ) + $focusedTests + @(
                "-q", "-p", "no:cacheprovider", "--basetemp", (Join-Path $worktreeTmp ("pytest_focused_" + $pair[0]))
            )) | Out-Null
    }

    $editableEnv = Join-Path $script:RunRoot "envs\editable"
    $editable = Sync-ProjectEnvironment -Name "editable" -EnvironmentPath $editableEnv -Python $resolvedCurrent
    Test-InstalledEntryPoints -Scope "editable" -Python $editable -Target $script:EntryPointChecks

    $script:CurrentStep = "locked dependency export and package build"
    $requirements = Join-Path $script:RunRoot "requirements.txt"
    Invoke-Recorded -Name "uv-export-locked" -FilePath "uv" `
        -Arguments @("export", "--locked", "--all-extras", "--no-emit-project", "--format", "requirements.txt", "--output-file", $requirements) `
        -WorkingDirectory $script:WorktreePath | Out-Null
    foreach ($path in @("dist", "build")) {
        $full = Join-Path $script:WorktreePath $path
        if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
    }
    Run-Python -Name "build-wheel-sdist" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("-m", "build") | Out-Null
    Run-Python -Name "inspect-wheel-sdist" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("tests\packaging\inspect_distribution.py", "--expected-version", $projectVersion, "dist") | Out-Null
    $normalizedDistribution = $distributionName.Replace("-", "_")
    $wheel = (Get-ChildItem -LiteralPath (Join-Path $script:WorktreePath "dist") -Filter "$normalizedDistribution-$projectVersion-py3-none-any.whl" -File).FullName
    $sdist = (Get-ChildItem -LiteralPath (Join-Path $script:WorktreePath "dist") -Filter "$normalizedDistribution-$projectVersion.tar.gz" -File).FullName
    Assert-File -Path $wheel
    Assert-File -Path $sdist

    $script:CurrentStep = "wheel and sdist isolated installs"
    foreach ($artifact in @(@("wheel", $wheel), @("sdist", $sdist))) {
        $envPath = Join-Path $script:RunRoot ("envs\" + $artifact[0])
        $artifactPython = New-ArtifactEnvironment -Name $artifact[0] -EnvironmentPath $envPath -Python $resolvedCurrent
        Invoke-Recorded -Name ("install-dependencies-" + $artifact[0]) -FilePath "uv" `
            -Arguments @("pip", "install", "--python", $artifactPython, "--requirement", $requirements) `
            -WorkingDirectory $script:RunRoot | Out-Null
        if ($artifact[0] -eq "wheel") {
            Invoke-Recorded -Name "install-wheel" -FilePath "uv" `
                -Arguments @("pip", "install", "--python", $artifactPython, "--no-deps", $artifact[1]) `
                -WorkingDirectory $script:RunRoot | Out-Null
        } else {
            Invoke-Recorded -Name "install-sdist" -FilePath "uv" `
                -Arguments @("pip", "install", "--python", $artifactPython, "--no-deps", $artifact[1]) `
                -WorkingDirectory $script:RunRoot | Out-Null
        }
        Run-Python -Name ("identity-" + $artifact[0] + "-install") -Python $artifactPython `
            -WorkingDirectory $script:RunRoot -Arguments @($identityScript) | Out-Null
        Test-InstalledEntryPoints -Scope $artifact[0] -Python $artifactPython -Target $script:InstallChecks
    }

    $sdistExtract = Join-Path $script:RunRoot "sdist-source"
    $sdistWheelOut = Join-Path $script:RunRoot "sdist-wheel"
    New-Item -ItemType Directory -Force -Path $sdistExtract | Out-Null
    New-Item -ItemType Directory -Force -Path $sdistWheelOut | Out-Null
    Invoke-Recorded -Name "extract-sdist" -FilePath "tar.exe" `
        -Arguments @("-xf", $sdist, "-C", $sdistExtract) -WorkingDirectory $script:RunRoot | Out-Null
    $sdistRoot = Get-ChildItem -LiteralPath $sdistExtract -Directory | Select-Object -First 1
    if ($null -eq $sdistRoot) { throw "The sdist did not extract a project directory" }
    Run-Python -Name "build-wheel-from-sdist" -Python $current -WorkingDirectory $script:RunRoot `
        -Arguments @("-m", "build", "--wheel", "--outdir", $sdistWheelOut, $sdistRoot.FullName) | Out-Null
    Run-Python -Name "inspect-wheel-from-sdist" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("tests\packaging\inspect_distribution.py", "--wheel-only", "--expected-version", $projectVersion, $sdistWheelOut) | Out-Null

    $script:CurrentStep = "standalone PyInstaller builds"
    $standalone = Join-Path $worktreeTmp "standalone"
    New-Item -ItemType Directory -Force -Path $standalone | Out-Null
    $buildCli = Join-Path $script:WorktreePath "scripts\build_cli_exe.ps1"
    $buildWebui = Join-Path $script:WorktreePath "scripts\build_webui_exe.ps1"
    Invoke-Recorded -Name "build-standalone-cli" -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $buildCli, "-DistPath", $standalone, "-Name", "powers-tool") `
        -WorkingDirectory $script:WorktreePath | Out-Null
    Invoke-Recorded -Name "build-standalone-webui" -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $buildWebui, "-DistPath", $standalone, "-Name", "powers-tool-webui") `
        -WorkingDirectory $script:WorktreePath | Out-Null
    $standaloneCli = Join-Path $standalone "powers-tool.exe"
    $standaloneWebui = Join-Path $standalone "powers-tool-webui.exe"
    Assert-File -Path $standaloneCli
    Assert-File -Path $standaloneWebui
    foreach ($pair in @(@("cli", $standaloneCli), @("webui", $standaloneWebui))) {
        foreach ($arg in @("--version", "--help")) {
            $output = Invoke-Recorded -Name ("standalone-" + $pair[0] + "-" + $arg.TrimStart("-")) `
                -FilePath $pair[1] -Arguments @($arg) -WorkingDirectory $script:RunRoot -TimeoutSeconds 30
            $passed = if ($pair[0] -eq "webui") {
                (-not $output.Trim()) -or
                    ($arg -eq "--version" -and $output.Trim() -eq "powers-tool-webui-launcher $projectVersion") -or
                    ($arg -eq "--help" -and $output.Contains("Powers Tool WebUI Launcher"))
            } elseif ($arg -eq "--version") {
                $output.Trim() -eq "powers-tool $projectVersion"
            } else {
                $output.Contains("Safe Powers Tool CLI for supported DC power supplies.")
            }
            $detail = $output.Trim()
            if (-not $detail) { $detail = "clean exit; no windowed stdout" }
            Add-Check -Target $script:StandaloneChecks -Name ($pair[0] + " " + $arg) `
                -Passed $passed -Detail $detail
        }
    }
    Run-Python -Name "inspect-standalone-archives" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("tests\packaging\inspect_pyinstaller.py", "--expected-version", $projectVersion, $standaloneCli, $standaloneWebui) | Out-Null

    $script:CurrentStep = "versioned release folder"
    foreach ($path in @("dist", "build")) {
        $full = Join-Path $script:WorktreePath $path
        if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
    }
    $releaseRoot = Join-Path $worktreeTmp "release"
    Invoke-Recorded -Name "build-versioned-release" -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $script:WorktreePath "scripts\build_release.ps1"), "-Version", $projectVersion, "-ReleaseRoot", $releaseRoot) `
        -WorkingDirectory $script:WorktreePath | Out-Null
    $versionDir = Join-Path $releaseRoot $projectVersion
    $expectedRelease = @(
        "powers-tool-$projectVersion.exe",
        "powers-tool-webui-$projectVersion.exe",
        "$normalizedDistribution-$projectVersion-py3-none-any.whl",
        "$normalizedDistribution-$projectVersion.tar.gz",
        "checksums.txt"
    )
    $releaseFiles = @(Get-ChildItem -LiteralPath $versionDir -File | Select-Object -ExpandProperty Name)
    if (@(Compare-Object -ReferenceObject $expectedRelease -DifferenceObject $releaseFiles).Count -ne 0) {
        throw "Release folder contents differ: $($releaseFiles -join ', ')"
    }
    $checksumLines = Get-Content -LiteralPath (Join-Path $versionDir "checksums.txt")
    $checksumNames = @()
    foreach ($line in $checksumLines) {
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { throw "Invalid checksum line: $line" }
        $checksumNames += $Matches[2]
        $actual = Get-Sha256File -LiteralPath (Join-Path $versionDir $Matches[2])
        if ($actual -ne $Matches[1].ToLowerInvariant()) { throw "Checksum mismatch: $($Matches[2])" }
    }
    $expectedChecksumNames = @($expectedRelease | Where-Object { $_ -ne "checksums.txt" })
    if (@(Compare-Object -ReferenceObject $expectedChecksumNames -DifferenceObject $checksumNames).Count -ne 0) {
        throw "Checksum coverage differs from the release artifacts"
    }
    $checksumBytes = [System.IO.File]::ReadAllBytes((Join-Path $versionDir "checksums.txt"))
    if ($checksumBytes.Length -ge 3 -and $checksumBytes[0] -eq 0xEF -and `
        $checksumBytes[1] -eq 0xBB -and $checksumBytes[2] -eq 0xBF) {
        throw "checksums.txt must be UTF-8 without BOM"
    }
    Run-Python -Name "inspect-versioned-packages" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("tests\packaging\inspect_distribution.py", "--expected-version", $projectVersion, $versionDir) | Out-Null
    Run-Python -Name "inspect-versioned-archives" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("tests\packaging\inspect_pyinstaller.py", "--expected-version", $projectVersion, (Join-Path $versionDir "powers-tool-$projectVersion.exe"), (Join-Path $versionDir "powers-tool-webui-$projectVersion.exe")) | Out-Null
    foreach ($name in @("powers-tool-$projectVersion.exe", "powers-tool-webui-$projectVersion.exe")) {
        $path = Join-Path $versionDir $name
        $versionOutput = Invoke-Recorded -Name ("versioned-" + $name + "-version") `
            -FilePath $path -Arguments @("--version") -WorkingDirectory $script:RunRoot -TimeoutSeconds 30
        $helpOutput = Invoke-Recorded -Name ("versioned-" + $name + "-help") `
            -FilePath $path -Arguments @("--help") -WorkingDirectory $script:RunRoot -TimeoutSeconds 30
        if ($name -eq "powers-tool-$projectVersion.exe") {
            Add-Check -Target $script:StandaloneChecks -Name "versioned CLI --version" `
                -Passed ($versionOutput.Trim() -eq "powers-tool $projectVersion") -Detail $versionOutput.Trim()
            Add-Check -Target $script:StandaloneChecks -Name "versioned CLI --help" `
                -Passed $helpOutput.Contains("Safe Powers Tool CLI for supported DC power supplies.")
        } else {
            Add-Check -Target $script:StandaloneChecks -Name "versioned WebUI --version clean exit" `
                -Passed ((-not $versionOutput.Trim()) -or $versionOutput.Trim() -eq "powers-tool-webui-launcher $projectVersion")
            Add-Check -Target $script:StandaloneChecks -Name "versioned WebUI --help clean exit" `
                -Passed ((-not $helpOutput.Trim()) -or $helpOutput.Contains("Powers Tool WebUI Launcher"))
        }
    }

    $retainedArtifacts = Join-Path $script:RunRoot "artifacts"
    $retainedStandalone = Join-Path $retainedArtifacts "standalone"
    $retainedRelease = Join-Path $retainedArtifacts ("release\" + $projectVersion)
    New-Item -ItemType Directory -Force -Path $retainedStandalone, $retainedRelease | Out-Null
    Copy-Item -LiteralPath $standaloneCli, $standaloneWebui -Destination $retainedStandalone
    Get-ChildItem -LiteralPath $versionDir -File | Copy-Item -Destination $retainedRelease
    foreach ($path in Get-ChildItem -LiteralPath $retainedArtifacts -File -Recurse) {
        $script:BuildArtifacts += ,(Get-ReportPath -Path $path.FullName)
    }
    foreach ($generated in @("dist", "build")) {
        $generatedPath = Join-Path $script:WorktreePath $generated
        if (Test-Path -LiteralPath $generatedPath) {
            Remove-GeneratedDirectory -Path $generatedPath
        }
    }

    $script:CurrentStep = "documentation and identity gates"
    $readme = Get-Content -LiteralPath (Join-Path $script:WorktreePath "README.md") -Raw
    $webuiReadme = Get-Content -LiteralPath (Join-Path $script:WorktreePath "docs\webui\README.md") -Raw
    Assert-Contains -Text $readme -Needle "release-acceptance.ps1" -Context "README.md"
    Assert-Contains -Text $webuiReadme -Needle "FastAPI server console wrapper" -Context "docs/webui/README.md"
    Assert-Contains -Text $webuiReadme -Needle "GUI launcher console wrapper" -Context "docs/webui/README.md"
    Assert-Contains -Text $webuiReadme -Needle "dist\powers-tool-webui.exe" -Context "docs/webui/README.md"
    Add-Check -Target $script:DocumentationChecks -Name "English release usage" -Passed $true -Detail "README documents the acceptance entry point"
    Run-Python -Name "stale-identity-gate" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("-m", "pytest", "tests\packaging\test_packaging_identity.py", "-q", "-p", "no:cacheprovider", "--basetemp", (Join-Path $worktreeTmp "pytest_identity")) | Out-Null
    Add-Check -Target $script:LegacyChecks -Name "tracked stale-name allowlist" -Passed $true -Detail "Existing narrow packaging identity gate passed"

    $script:CurrentStep = "final source hygiene"
    Invoke-Recorded -Name "git-diff-check" -FilePath "git" `
        -Arguments @("-C", $script:WorktreePath, "diff", "--check") `
        -WorkingDirectory $script:WorktreePath | Out-Null
    $finalStatus = @(& git -C $script:WorktreePath status --short --untracked-files=all)
    $expectedFinalPaths = if ($IncludeWorkingTreeChanges) { $candidatePaths } else { @() }
    $finalPaths = @($finalStatus | ForEach-Object { Get-StatusPath -StatusLine ([string]$_) } | Sort-Object -Unique)
    if (@(Compare-Object -ReferenceObject $expectedFinalPaths -DifferenceObject $finalPaths).Count -ne 0) {
        throw "Acceptance commands changed tracked or untracked source paths: $($finalPaths -join ', ')"
    }

    $script:CurrentStep = "complete no-hardware suites"
    Run-Python -Name "pytest-python310-full" -Python $python310 -WorkingDirectory $script:WorktreePath `
        -Arguments @("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--basetemp", (Join-Path $worktreeTmp "pytest_python310")) | Out-Null
    Run-Python -Name "pytest-current-full" -Python $current -WorkingDirectory $script:WorktreePath `
        -Arguments @("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--basetemp", (Join-Path $worktreeTmp "pytest_current")) | Out-Null

    $script:CurrentStep = "model-aware CLI preflight"
    Invoke-Recorded -Name "preflight-cli-all" -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $script:WorktreePath "scripts\preflight-cli.ps1"), "-Target", "all", "-OutputRoot", (Join-Path $worktreeTmp "cli_preflight")) `
        -WorkingDirectory $script:WorktreePath | Out-Null

    $script:CurrentStep = "live CLI PlanOnly contract"
    Invoke-Recorded -Name "live-cli-plan-only" -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $script:WorktreePath "scripts\live-cli-check.ps1"), "-Target", "keysight-e36312a", "-Connection", "USB", "-Resource", "SIM::E36312A", "-Suite", "readonly", "-PlanOnly") `
        -WorkingDirectory $script:WorktreePath | Out-Null

        $script:FullAcceptanceCompleted = $true
        $script:Ok = $true
    }
}
catch {
    $script:FailedStep = $script:CurrentStep
    $script:FailureMessage = $_.Exception.Message
    Write-Warning ("Powers Tool release acceptance failed during {0}: {1}" -f $script:CurrentStep, $script:FailureMessage)
}
finally {
    if ($script:WorktreePath -and (Test-Path -LiteralPath $script:WorktreePath) -and -not $KeepWorktree) {
        try {
            foreach ($generated in @(".venv", ".tmp_tests", "dist", "build")) {
                $generatedPath = Join-Path $script:WorktreePath $generated
                if (Test-Path -LiteralPath $generatedPath) {
                    Remove-GeneratedDirectory -Path $generatedPath
                }
            }
            Invoke-Recorded -Name "worktree-remove" -FilePath "git" `
                -Arguments @("-C", $script:RepoRoot, "worktree", "remove", "--force", $script:WorktreePath) `
                -WorkingDirectory $script:RepoRoot | Out-Null
        } catch {
            $script:Ok = $false
            $script:FailedStep = "remove isolated worktree"
            Write-Warning $_
        }
    }
    if ($script:RunRoot) {
        $report = [ordered]@{
            schema_version = 1
            kind = "powers-tool-release-acceptance"
            ok = $script:Ok
            acceptance_mode = $acceptanceMode
            full_acceptance_completed = $script:FullAcceptanceCompleted
            source_commit = if ($sourceCommit) { $sourceCommit } else { $null }
            source_branch = if ($sourceBranch) { $sourceBranch } else { $null }
            acceptance_worktree_state = $acceptanceWorktreeState
            project_version = if ($projectVersion) { $projectVersion } else { $null }
            distribution_name = if ($distributionName) { $distributionName } else { $null }
            python_310 = [ordered]@{
                requested_interpreter = if ($Python310) { $Python310 } else { "uv python find 3.10" }
                resolved_interpreter = if ($resolvedPython310) { $resolvedPython310 } else { $null }
                expected_version = "3.10"
                actual_version = if ($python310Metadata) { [string]$python310Metadata.version } else { $null }
                actual_major = if ($python310Metadata) { [int]$python310Metadata.major } else { $null }
                actual_minor = if ($python310Metadata) { [int]$python310Metadata.minor } else { $null }
                actual_executable = if ($python310Metadata) { [string]$python310Metadata.executable } else { $null }
            }
            current_python = [ordered]@{
                requested_interpreter = if ($CurrentPython) { $CurrentPython } else { "uv python find 3.13" }
                resolved_interpreter = if ($resolvedCurrent) { $resolvedCurrent } else { $null }
                expected_version = "3.13"
                actual_version = if ($currentPythonMetadata) { [string]$currentPythonMetadata.version } else { $null }
                actual_major = if ($currentPythonMetadata) { [int]$currentPythonMetadata.major } else { $null }
                actual_minor = if ($currentPythonMetadata) { [int]$currentPythonMetadata.minor } else { $null }
                actual_executable = if ($currentPythonMetadata) { [string]$currentPythonMetadata.executable } else { $null }
            }
            python_310_version = if ($python310Metadata) { [string]$python310Metadata.version } else { $null }
            current_python_version = if ($currentPythonMetadata) { [string]$currentPythonMetadata.version } else { $null }
            interpreters_distinct = $interpretersDistinct
            initial_worktree_status = @($initialStatus)
            clean_worktree_before_overlay = if ($InterpreterPreflightOnly) { $null } else { (@($cleanStatusBeforeOverlay).Count -eq 0) }
            working_tree_overlay_applied = [bool]$IncludeWorkingTreeChanges
            candidate_paths = @($candidatePaths)
            candidate_file_hashes = @($candidateFileHashes)
            candidate_patch_sha256 = $candidatePatchSha256
            commands = @($script:Commands)
            build_artifacts = @($script:BuildArtifacts | Select-Object -Unique)
            install_checks = @($script:InstallChecks)
            entry_point_checks = @($script:EntryPointChecks)
            standalone_checks = @($script:StandaloneChecks)
            legacy_identity_checks = @($script:LegacyChecks)
            documentation_checks = @($script:DocumentationChecks)
            failed_step = $script:FailedStep
            failure_message = $script:FailureMessage
            hardware_touched = $false
            support_metadata_changed = $false
            evidence_changed = $false
            repository_renamed = $false
        }
        $reportJson = $report | ConvertTo-Json -Depth 8
        Write-Utf8NoBomFile -LiteralPath (Join-Path $script:RunRoot "report.json") -Content $reportJson
        $summaryTitle = if ($InterpreterPreflightOnly -and $IncludeWorkingTreeChanges) {
            "Powers Tool Candidate Working-Tree Interpreter Preflight"
        } elseif ($InterpreterPreflightOnly) {
            "Powers Tool Interpreter Preflight"
        } elseif ($IncludeWorkingTreeChanges) {
            "Powers Tool Candidate Working-Tree Validation"
        } else {
            "Powers Tool Release Acceptance"
        }
        $summary = @(
            "# $summaryTitle",
            "",
            "Result: **$(if ($script:Ok) { 'passed' } else { 'failed' })**",
            "",
            "- Acceptance mode: ``$acceptanceMode``",
            "- Full acceptance completed: ``$($script:FullAcceptanceCompleted.ToString().ToLowerInvariant())``",
            "- Source commit: ``$sourceCommit``",
            "- Working-tree overlay applied: ``$([bool]$IncludeWorkingTreeChanges)``",
            "- Candidate patch SHA-256: ``$(if ($candidatePatchSha256) { $candidatePatchSha256 } else { 'null' })``",
            "- Distribution: ``$distributionName`` $projectVersion",
            "- Hardware touched: ``false``",
            "- Support metadata changed: ``false``",
            "- Evidence changed: ``false``",
            "- Repository renamed: ``false``",
            "",
            "| Command | Exit code | Duration ms |",
            "| --- | ---: | ---: |"
        )
        if ($InterpreterPreflightOnly) {
            $summary += ""
            $summary += "This report covers interpreter preflight only; it is not release acceptance."
            if ($IncludeWorkingTreeChanges) {
                $summary += "This preflight records a working-tree candidate overlay; it is not committed-HEAD provenance."
            }
        } elseif ($IncludeWorkingTreeChanges) {
            $summary += ""
            $summary += "This validates the working-tree candidate only. It is not the final committed clean-HEAD acceptance."
        }
        foreach ($command in $script:Commands) {
            $summary += "| ``$($command.name)`` | $($command.exit_code) | $($command.duration_ms) |"
        }
        if (-not $script:Ok) {
            $summary += ""
            $summary += "Failed step: ``$($script:FailedStep)``"
            $summary += "Failure: $($script:FailureMessage)"
        }
        Write-Utf8NoBomFile -LiteralPath (Join-Path $script:RunRoot "summary.md") -Content ($summary -join "`n")
        Write-Host "Acceptance report: $(Join-Path $script:RunRoot 'report.json')"
    }
}

if (-not $script:Ok) { exit 1 }
exit 0
