from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-acceptance.ps1"


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip(
            "Windows PowerShell is required for acceptance-script behavior tests"
        )
    return executable


def _find_uv_python(version: str, cache: Path) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for acceptance-script behavior tests")
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(cache)
    result = subprocess.run(
        [uv, "python", "find", version],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        pytest.skip(f"Python {version} is not installed for the behavior test")
    path = Path(result.stdout.strip().splitlines()[-1]).resolve()
    if not path.is_file():
        pytest.skip(f"uv returned no usable Python {version} interpreter")
    return path


@pytest.fixture
def find_python(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    _powershell()
    cache = tmp_path_factory.mktemp("release_uv_cache")
    return lambda version: _find_uv_python(version, cache)


def _make_distinct_interpreter(
    base_python: Path, request: pytest.FixtureRequest
) -> Path:
    environment = ROOT / ".tmp_tests" / "release_preflight_python" / uuid4().hex
    request.addfinalizer(lambda: shutil.rmtree(environment, ignore_errors=True))
    clean_env = os.environ.copy()
    for name in ("PYTHONHOME", "UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV", "PYTHONPATH"):
        clean_env.pop(name, None)
    _run(
        [str(base_python), "-m", "venv", "--without-pip", str(environment)],
        cwd=ROOT,
        env=clean_env,
    )
    return environment / "Scripts" / "python.exe"


def _make_preflight_repository(request: pytest.FixtureRequest) -> Path:
    fixture_id = uuid4().hex
    repository = ROOT / ".tmp_tests" / "release_preflight_repo" / fixture_id
    git_directory = ROOT / ".tmp_tests" / "release_preflight_git" / fixture_id
    repository.mkdir(parents=True)
    git_directory.parent.mkdir(parents=True, exist_ok=True)
    request.addfinalizer(lambda: shutil.rmtree(repository, ignore_errors=True))
    request.addfinalizer(lambda: shutil.rmtree(git_directory, ignore_errors=True))
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "powers-tool"\nversion = "3.4.5"\n',
        encoding="utf-8",
    )
    (repository / "README.md").write_text("preflight fixture\n", encoding="utf-8")
    _run(
        [
            "git",
            "-c",
            "core.longpaths=true",
            "init",
            f"--separate-git-dir={git_directory}",
            "-b",
            "main",
        ],
        cwd=repository,
    )
    _run(["git", "config", "core.longpaths", "true"], cwd=repository)
    _run(["git", "config", "user.email", "release-tests@example.invalid"], cwd=repository)
    _run(["git", "config", "user.name", "Release Tests"], cwd=repository)
    _run(["git", "add", "."], cwd=repository)
    _run(["git", "commit", "-m", "preflight fixture"], cwd=repository)
    return repository


def _run_preflight(
    repository: Path,
    *,
    python310: Path,
    current_python: Path,
    include_working_tree: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    command = [
        _powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repository / "scripts" / SCRIPT.name),
        "-InterpreterPreflightOnly",
        "-Python310",
        str(python310),
        "-CurrentPython",
        str(current_python),
        "-OutputRoot",
        ".tmp_tests\\preflight",
    ]
    if include_working_tree:
        command.append("-IncludeWorkingTreeChanges")
    result = _run(command, cwd=repository, check=False)
    reports = list((repository / ".tmp_tests" / "preflight").glob("r_*/report.json"))
    assert len(reports) == 1, result.stdout + result.stderr
    return result, json.loads(reports[0].read_text(encoding="utf-8"))


def test_release_acceptance_script_uses_isolated_locked_workflows() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for required in (
        '"worktree", "add"',
        '"worktree", "remove"',
        "--locked",
        "--all-extras",
        "--no-emit-project",
        "Python310",
        "CurrentPython",
        "IncludeWorkingTreeChanges",
        "powers-tool-webui-launcher",
        "inspect_distribution.py",
        "inspect_pyinstaller.py",
        "hardware_touched = $false",
        "support_metadata_changed = $false",
        "evidence_changed = $false",
        "repository_renamed = $false",
        "acceptance_worktree_state = $acceptanceWorktreeState",
        "candidate_patch_sha256",
        "candidate_file_hashes",
        "failure_message",
        "InterpreterPreflightOnly",
        'VersionSelector "3.13"',
        "Assert-PythonVersion",
        "interpreters_distinct",
        "full_acceptance_completed",
    ):
        assert required in text

    build_text = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in ("build_cli_exe.ps1", "build_webui_exe.ps1", "build_release.ps1")
    )
    assert "DistPath must stay under the repository" in build_text
    assert "ReleaseRoot must stay under the repository" in build_text
    assert "--reinstall-package" in text
    assert "--basetemp" in text
    assert "PYTHONNOUSERSITE" in text
    assert "apply-working-tree-diff" in text
    assert "ls-files --others --exclude-standard" in text
    assert "outside the release acceptance allowlist" in text
    assert text.index('"focused release acceptance tests"') < text.index(
        '"complete no-hardware suites"'
    )
    assert "PythonVersions.Values | Where-Object" not in text


def test_release_scripts_use_module_independent_sha256_helper() -> None:
    for name in ("release-acceptance.ps1", "build_release.ps1"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")

        assert "Get-FileHash" not in text
        assert "function Get-Sha256File" in text
        assert "[System.Security.Cryptography.SHA256]::Create()" in text
        assert "[System.IO.FileAccess]::Read" in text
        assert ".Dispose()" in text


def test_preflight_rejects_non_310_python310(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    current_python = find_python("3.13")
    wrong_python310 = _make_distinct_interpreter(current_python, request)
    result, report = _run_preflight(
        repository,
        python310=wrong_python310,
        current_python=current_python,
    )

    assert result.returncode == 1
    assert report["ok"] is False
    assert report["failed_step"] == "interpreter preflight"
    assert str(wrong_python310) in report["failure_message"]
    assert "expected Python 3.10" in report["failure_message"]
    assert "actual Python 3.13" in report["failure_message"]


def test_preflight_rejects_non_313_current_python(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    python310 = find_python("3.10")
    wrong_current = _make_distinct_interpreter(python310, request)
    result, report = _run_preflight(
        repository,
        python310=python310,
        current_python=wrong_current,
    )

    assert result.returncode == 1
    assert report["ok"] is False
    assert str(wrong_current) in report["failure_message"]
    assert "expected Python 3.13" in report["failure_message"]
    assert "actual Python 3.10" in report["failure_message"]


def test_preflight_rejects_the_same_interpreter_for_both_roles(
    request: pytest.FixtureRequest,
) -> None:
    repository = _make_preflight_repository(request)
    interpreter = Path(sys.executable).resolve()
    result, report = _run_preflight(
        repository,
        python310=interpreter,
        current_python=interpreter,
    )

    assert result.returncode == 1
    assert report["ok"] is False
    assert report["interpreters_distinct"] is False
    assert "must be distinct files" in report["failure_message"]


def test_preflight_report_records_exact_interpreter_and_committed_provenance(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    python310 = find_python("3.10")
    current_python = find_python("3.13")
    expected_commit = _run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
    result, report = _run_preflight(
        repository,
        python310=python310,
        current_python=current_python,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["ok"] is True
    assert report["acceptance_mode"] == "interpreter-preflight"
    assert report["full_acceptance_completed"] is False
    assert report["source_commit"] == expected_commit
    assert report["distribution_name"] == "powers-tool"
    assert report["project_version"] == "3.4.5"
    assert Path(report["python_310"]["requested_interpreter"]) == python310
    assert report["python_310"]["expected_version"] == "3.10"
    assert report["python_310"]["actual_version"].startswith("3.10.")
    assert report["python_310"]["actual_major"] == 3
    assert report["python_310"]["actual_minor"] == 10
    assert (
        Path(report["python_310"]["resolved_interpreter"])
        == python310
    )
    assert Path(report["current_python"]["requested_interpreter"]) == current_python
    assert report["current_python"]["expected_version"] == "3.13"
    assert report["current_python"]["actual_version"].startswith("3.13.")
    assert report["current_python"]["actual_major"] == 3
    assert report["current_python"]["actual_minor"] == 13
    assert (
        Path(report["current_python"]["resolved_interpreter"])
        == current_python
    )
    assert report["interpreters_distinct"] is True
    assert report["working_tree_overlay_applied"] is False
    assert report["candidate_paths"] == []
    assert report["candidate_patch_sha256"] is None


def test_preflight_candidate_report_keeps_commit_and_patch_provenance_distinct(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    python310 = find_python("3.10")
    current_python = find_python("3.13")
    source_commit = _run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
    (repository / "README.md").write_text("candidate change\n", encoding="utf-8")
    result, report = _run_preflight(
        repository,
        python310=python310,
        current_python=current_python,
        include_working_tree=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["acceptance_mode"] == "candidate-interpreter-preflight"
    assert report["full_acceptance_completed"] is False
    assert report["working_tree_overlay_applied"] is True
    assert report["source_commit"] == source_commit
    assert report["candidate_paths"] == ["README.md"]
    candidate_hashes = {
        item["path"]: item["sha256"] for item in report["candidate_file_hashes"]
    }
    assert candidate_hashes == {
        "README.md": hashlib.sha256(
            (repository / "README.md").read_bytes()
        ).hexdigest()
    }
    patch = next(
        (repository / ".tmp_tests" / "preflight").glob("r_*/working-tree.patch")
    )
    assert report["candidate_patch_sha256"] == hashlib.sha256(
        patch.read_bytes()
    ).hexdigest()
    assert report["candidate_patch_sha256"] != report["source_commit"]
    summary = next(
        (repository / ".tmp_tests" / "preflight").glob("r_*/summary.md")
    ).read_text(encoding="utf-8")
    assert "Candidate Working-Tree Interpreter Preflight" in summary
    assert "not release acceptance" in summary
    assert "not committed-HEAD provenance" in summary


def test_readme_uses_python_313_and_distinguishes_candidate_from_final_acceptance(
) -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "-CurrentPython (uv python find 3.13)" in text
    assert "-CurrentPython (uv python find 3.12)" not in text
    assert "-IncludeWorkingTreeChanges" in text
    assert "does not replace final release\nacceptance" in text


def test_release_acceptance_candidate_overlay_has_an_exact_write_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    allowed_block = text.split("$allowedCandidatePaths = @(", 1)[1].split(")", 1)[0]
    expected = {
        ".github/workflows/tests.yml",
        "README.md",
        "pyproject.toml",
        "docs/cli/README.md",
        "docs/core/README.md",
        "scripts/_validation_helpers.ps1",
        "scripts/live-cli-check.ps1",
        "scripts/preflight-cli.ps1",
        "scripts/release-acceptance.ps1",
        "tests/packaging/inspect_distribution.py",
        "tests/packaging/inspect_pyinstaller.py",
        "tests/packaging/test_packaging_identity.py",
        "tests/cli/test_cli_wrappers.py",
        "tests/cli/test_followup_features.py",
        "tests/cli/test_live_cli_check_script.py",
        "tests/cli/test_supported_models_docs.py",
        "tests/core/test_model_enablement.py",
        "tests/packaging/test_release_acceptance.py",
        "uv.lock",
    }
    actual = {
        line.strip().strip('",')
        for line in allowed_block.splitlines()
        if line.strip().startswith('"')
    }
    assert actual == expected
    assert not any(path.startswith("Local/") for path in actual)
    assert not any("zh-TW" in path for path in actual)


def test_ci_main_push_and_safe_launcher_smoke_are_preserved() -> None:
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    push_block = text.split("  push:\n", 1)[1].split("\n\njobs:", 1)[0]
    assert "      - main" in push_block
    assert "      - master" not in push_block
    assert "      - Codex" not in push_block
    assert "uv run powers-tool --help" in text
    assert "uv run powers-tool-webui --help" in text
    assert "uv run powers-tool-webui-launcher --version" in text


def test_release_acceptance_script_is_no_hardware_and_keeps_localized_docs_out_of_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "list-resources --live-only",
        "*IDN?",
        "pyvisa_py",
        "VISA discovery",
    ):
        assert forbidden not in text
    for protected in (
        "Local/",
        "README.zh-TW.md",
        "generated localized",
        "hardware_touched = $false",
    ):
        assert protected in text
    assert '"preflight-cli-all"' in text
    assert '"live-cli-plan-only"' in text
    assert '"-PlanOnly"' in text
    assert '"SIM::E36312A"' in text
    assert "no-hardware-regression.ps1" not in text


def test_release_acceptance_is_version_neutral() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '$projectVersion = $versionMatch.Groups[1].Value' in text
    assert '$distributionName -ne "powers-tool"' in text
    assert '$projectVersion -ne "2.0.0"' not in text
    assert '"-Version", $projectVersion' in text
    assert 'Join-Path $releaseRoot $projectVersion' in text
    assert 'kind = "powers-tool-release-acceptance"' in text
    for stale in (
        "powers-tool-v2-release-acceptance",
        "v2_release_acceptance",
        "p7_release_acceptance",
        "Powers Tool v2 Release Acceptance",
    ):
        assert stale not in text


def test_pyinstaller_inspector_requires_release_metadata_and_webui_assets() -> None:
    text = (ROOT / "tests" / "packaging" / "inspect_pyinstaller.py").read_text(
        encoding="utf-8"
    )
    assert "Name: powers-tool" in text
    assert "Version: 2.0.0" in text
    assert '"index.html", "styles.css", "app.js"' in text
    assert "keysight_power_" in text
    assert "open_embedded_archive" in text
    assert "names[powers_metadata]" in text
