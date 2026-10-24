"""Guard targeted Windows CI job selection after using paths-filter."""

from __future__ import annotations

from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def change_filters(workflow: str) -> dict[str, list[str]]:
    match = re.search(r"(?m)^\s{10}filters: \|\n((?:\s{12,}.*\n)+)", workflow)
    assert match, "Windows change filters missing"
    filters: dict[str, list[str]] = {}
    category = ""
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if line.endswith(":"):
            category = line[:-1]
            filters[category] = []
        elif line.startswith("- '") and line.endswith("'"):
            filters[category].append(line[3:-1])
    assert set(filters) == {"validation", "packaging", "release_layout"}
    return filters


def affected(filters: dict[str, list[str]], path: str) -> tuple[bool, bool, bool]:
    return tuple(
        any(fnmatchcase(path, pattern) for pattern in filters[name])
        for name in ("validation", "packaging", "release_layout")
    )


def test_workflow_keeps_tests_automatic_and_windows_jobs_conditional() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request:\n" in workflow
    assert "  push:\n" in workflow
    assert "  workflow_dispatch:" not in workflow
    assert "uses: dorny/paths-filter@v4" in workflow
    assert "pull-requests: read" in workflow
    assert "base: ${{ github.event.repository.default_branch }}" in workflow
    assert "run: python scripts/ci_change_detection.py" not in workflow
    assert "tests/tooling/test_ci_workflow_contracts.py" in workflow
    for job in (
        "quality-webui", "pytest-linux", "pytest-windows",
        "detect-validation-changes", "windows-validation", "windows-live-validation",
        "windows-release-acceptance", "windows-packaging-smoke",
    ):
        assert f"  {job}:" in workflow
    for name in ("validation", "packaging", "release_layout"):
        assert f"steps.filter.outputs.{name}" in workflow
    assert "needs.detect-validation-changes.outputs.validation == 'true'" in workflow
    assert "needs.detect-validation-changes.outputs.packaging == 'true'" in workflow
    assert "needs.detect-validation-changes.outputs.release_layout" in workflow
    jobs = yaml.safe_load(workflow)["jobs"]
    smoke = next(step for step in jobs["windows-packaging-smoke"]["steps"]
                 if step.get("name") == "Inspect real outputs and smoke executables")
    assert "$arguments += '--release-layout'" in smoke["run"]


def test_windows_powershell_jobs_are_focused_and_independent() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    owners = {
        "windows-validation": "tests/cli/test_cli_wrappers.py",
        "windows-live-validation": "tests/cli/test_live_cli_check_script.py",
        "windows-release-acceptance": "tests/packaging/test_release_acceptance.py",
    }
    for job_id, test_file in owners.items():
        job = jobs[job_id]
        assert job["needs"] == "detect-validation-changes"
        assert job["if"] == "needs.detect-validation-changes.outputs.validation == 'true'"
        assert job["runs-on"] == "windows-latest"
        assert any(step.get("name") == "Require Windows PowerShell" for step in job["steps"])
        command = job["steps"][-1]["run"]
        assert "--strict-markers" in command
        assert '-m "windows_powershell and not hardware"' in command
        assert f"--basetemp .tmp_tests/ci-{job_id}" in command
        assert command.split()[-1] == test_file


def test_windows_build_workflow_contracts_have_one_ci_owner() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    owners = []
    for job_id, job in jobs.items():
        for step in job["steps"]:
            command = step.get("run", "")
            if ("tests/tooling/test_ci_workflow_contracts.py" in command
                    and '-m "windows_powershell and not hardware"' in command):
                owners.append(job_id)
                assert "--strict-markers" in command
    assert owners == ["windows-packaging-smoke"]


def test_change_paths_only_start_relevant_windows_jobs() -> None:
    filters = change_filters(WORKFLOW.read_text(encoding="utf-8"))
    expected = {
        "README.md": (False, False, False),
        "docs/testing-guidelines.md": (False, False, False),
        "src/powers_tool_core/safety.py": (True, True, False),
        "src/powers_tool_core/drivers/e36312a.py": (True, True, False),
        "src/powers_tool_cli/cli.py": (True, True, False),
        "src/powers_tool_cli/commands/output.py": (True, True, False),
        "src/powers_tool_cli/help/cli.html": (False, True, False),
        "src/powers_tool_webui/server.py": (False, True, False),
        "src/powers_tool_webui/static/app.js": (False, True, False),
        "desktop/main.cjs": (False, True, False),
        "desktop/package-lock.json": (False, True, True),
        "scripts/preflight-cli.ps1": (True, False, False),
        "scripts/live-cli-check.ps1": (True, False, False),
        "scripts/_validation_helpers.ps1": (True, False, False),
        "scripts/e36312a_trigger_validation.py": (True, False, False),
        "scripts/build_desktop.ps1": (False, True, False),
        "scripts/build_release.ps1": (False, True, True),
        "scripts/powers-tool-windows.spec": (False, True, False),
        "scripts/ci_packaging_smoke.py": (False, True, True),
        "tests/cli/test_cli_wrappers.py": (True, False, False),
        "tests/cli/test_live_cli_check_script.py": (True, False, False),
        "tests/packaging/test_release_acceptance.py": (True, False, False),
        "tests/packaging/inspect_windows_bundle.py": (False, True, False),
        "tests/tooling/test_ci_workflow_contracts.py": (False, True, False),
        "docs/help/help.css": (False, True, False),
        ".github/workflows/tests.yml": (True, True, False),
        ".github/workflows/build-windows.yml": (False, True, True),
        "pyproject.toml": (True, True, True),
        "uv.lock": (True, True, True),
    }
    for path, required in expected.items():
        assert affected(filters, path) == required, path


def test_release_layout_inputs_always_request_packaging() -> None:
    filters = change_filters(WORKFLOW.read_text(encoding="utf-8"))
    for pattern in filters["release_layout"]:
        assert affected(filters, pattern) == (affected(filters, pattern)[0], True, True), pattern


BUILD_WORKFLOW = yaml.safe_load(
    (ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
)
BUILD_JOBS = BUILD_WORKFLOW["jobs"]


def build_step(name: str) -> dict:
    return next(s for s in BUILD_JOBS["build"]["steps"] if s.get("name") == name)


@pytest.fixture
def acceptance_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "4.0.0"\n', encoding="utf-8")
    root = tmp_path / ".tmp_tests" / "acceptance"
    run = root / "r_current"
    release = run / "artifacts" / "release" / "4.0.0"
    release.mkdir(parents=True)
    names = [
        "powers-tool-4.0.0-windows-x64.zip",
        "powers_tool-4.0.0-py3-none-any.whl",
        "powers_tool-4.0.0.tar.gz",
    ]
    checksums = []
    for name in names:
        (release / name).write_bytes(name.encode())
        checksums.append(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}\n")
    (release / "checksums.txt").write_text("".join(checksums), encoding="utf-8")
    commands = [
        "python-metadata", "uv-lock-check", "pytest-full-no-hardware", "build-versioned-release",
        "create-wheel-environment", "install-final-wheel", "inspect-wheel-install",
        "create-sdist-environment", "install-final-sdist", "inspect-sdist-install",
        "packaged-cli-version", "packaged-webui-launcher-version",
        "preflight-cli-all-smoke", "preflight-cli-deep-representatives",
        "live-cli-plan-only", "git-diff-check",
        *[f"sdist-{entry}-{option}" for entry in (
            "powers-tool", "powers-tool-webui", "powers-tool-webui-launcher"
        ) for option in ("version", "help")],
    ]
    report = {
        "schema_version": 1, "kind": "powers-tool-release-acceptance",
        "ok": True, "full_acceptance_completed": True,
        "acceptance_mode": "committed-clean-head", "distribution_name": "powers-tool",
        "source_commit": "a" * 40, "project_version": "4.0.0",
        "initial_worktree_status": [], "final_worktree_status": [],
        "commands": [{"name": name, "exit_code": 0} for name in commands],
        "build_artifacts": [f"artifacts/release/4.0.0/{name}" for name in [*names, "checksums.txt"]],
        "failed_step": None, "failure_message": None,
        "artifact_checks": [{"name": name, "passed": True} for name in (
            "versioned release folder contents", "checksum artifact coverage",
            "checksums UTF-8 without BOM", *[f"SHA-256 {name}" for name in names]
        )],
        "install_checks": [{"name": f"{kind} package identity, contents, and bundled Help",
                            "passed": True} for kind in ("wheel", "sdist")],
        "entry_point_checks": [{"name": f"{entry} --{option}", "passed": True} for entry in
                               ("powers-tool", "powers-tool-webui", "powers-tool-webui-launcher")
                               for option in ("version", "help")],
        "standalone_checks": [{"name": f"{entry} --version", "passed": True}
                              for entry in ("CLI", "WebUI")],
    }
    (run / "summary.md").write_text("Acceptance summary", encoding="utf-8")
    monkeypatch.setenv("ACCEPTANCE_ROOT", str(root))
    monkeypatch.setenv("EXPECTED_COMMIT", "a" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    return root, run, release, report


def verify_acceptance(run, report):
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
    exec(build_step("Verify acceptance report and release artifacts")["run"], {})


def test_acceptance_gate_uses_current_original_artifacts(acceptance_run):
    root, run, release, report = acceptance_run
    # Full pytest creates nested report fixtures; they are not invocation reports.
    nested = run / "pytest" / "fixture"
    nested.mkdir(parents=True)
    (nested / "report.json").write_text("{}", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in release.iterdir()}
    verify_acceptance(run, report)
    outputs = Path(os.environ["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
    assert "verified=true\n" in outputs
    assert f"source_commit={'a' * 40}\n" in outputs
    assert f"release_dir={release.as_posix()}\n" in outputs
    assert before == {p.name: p.read_bytes() for p in release.iterdir()}


@pytest.mark.parametrize("field,value", [
    ("ok", False), ("ok", "true"), ("full_acceptance_completed", False),
    ("acceptance_mode", "dirty-head"), ("source_commit", "b" * 40),
    ("project_version", "3.1.2"), ("initial_worktree_status", [" M tracked"]),
    ("final_worktree_status", ["?? untracked"]), ("final_worktree_status", None),
    ("failed_step", "build"), ("failure_message", "failure"),
    ("artifact_checks", [{"passed": False}]),
    ("artifact_checks", [{"name": "checksum artifact coverage", "passed": True}]), ("install_checks", []),
    ("entry_point_checks", None), ("standalone_checks", [{"passed": "true"}]),
    ("commands", [{"name": "build-versioned-release", "exit_code": 0}]),
    ("build_artifacts", []),
])
def test_acceptance_gate_rejects_failed_or_incomplete_report(acceptance_run, field, value):
    _, run, _, report = acceptance_run
    report[field] = value
    with pytest.raises(SystemExit):
        verify_acceptance(run, report)
    assert not Path(os.environ["GITHUB_OUTPUT"]).exists()


@pytest.mark.parametrize("damage", [
    "missing-report", "multiple-reports", "invalid-json", "non-object", "missing-summary",
    "failed-command", "missing-artifact", "empty-artifact", "wrong-version",
    "checksum-mismatch", "missing-checksum", "duplicate-checksum", "checksum-path",
    "extra-artifact",
])
def test_acceptance_gate_rejects_invalid_evidence_and_artifacts(acceptance_run, damage):
    root, run, release, report = acceptance_run
    report_path = run / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    checksum_path = release / "checksums.txt"
    if damage == "missing-report":
        report_path.unlink()
    elif damage == "multiple-reports":
        other = root / "r_old"
        other.mkdir()
        (other / "report.json").write_text(json.dumps(report), encoding="utf-8")
    elif damage in {"invalid-json", "non-object"}:
        report_path.write_text("{" if damage == "invalid-json" else "[]", encoding="utf-8")
    elif damage == "missing-summary":
        (run / "summary.md").unlink()
    elif damage == "failed-command":
        report["commands"][0]["exit_code"] = 1
        report_path.write_text(json.dumps(report), encoding="utf-8")
    elif damage in {"missing-artifact", "empty-artifact", "checksum-mismatch"}:
        artifact = release / "powers_tool-4.0.0.tar.gz"
        if damage == "missing-artifact":
            artifact.unlink()
        else:
            artifact.write_bytes(b"" if damage == "empty-artifact" else b"corrupt")
    elif damage == "wrong-version":
        release.rename(release.with_name("3.1.2"))
    elif damage == "extra-artifact":
        (release / "report.json").write_text("{}", encoding="utf-8")
    else:
        lines = checksum_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if damage == "missing-checksum":
            lines.pop()
        elif damage == "duplicate-checksum":
            lines.append(lines[0])
        else:
            lines[0] = "0" * 64 + "  ../outside.zip\n"
        checksum_path.write_text("".join(lines), encoding="utf-8")
    with pytest.raises((SystemExit, ValueError, FileNotFoundError)):
        exec(build_step("Verify acceptance report and release artifacts")["run"], {})
    assert not Path(os.environ["GITHUB_OUTPUT"]).exists()


def run_workflow_powershell(tmp_path, script, replacements, prefix=""):
    for token, value in replacements.items():
        script = script.replace("${{ " + token + " }}", value)
    path = tmp_path / "workflow.ps1"
    path.write_text("$ErrorActionPreference = 'Stop'\n" + prefix + script, encoding="utf-8")
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(path)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )


@pytest.mark.windows_powershell
@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("pwsh"),
                    reason="Windows with PowerShell 7 required")
@pytest.mark.parametrize("mode,draft,ref,allowed", [
    *[(mode, "false", "refs/heads/main", True) for mode in (
        "bundle", "desktop", "release", "release-acceptance")],
    *[(mode, "true", "refs/heads/main", False) for mode in ("bundle", "desktop", "release")],
    ("release-acceptance", "true", "refs/heads/topic", False),
    ("release-acceptance", "true", "refs/heads/main", True),
])
def test_build_options_reject_invalid_draft_before_build(tmp_path, mode, draft, ref, allowed):
    result = run_workflow_powershell(tmp_path, build_step("Validate options")["run"], {
        "inputs.build_mode": mode, "inputs.create_draft": draft, "github.ref": ref,
    })
    assert (result.returncode == 0) is allowed, result.stderr


@pytest.mark.windows_powershell
@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("pwsh"),
                    reason="Windows with PowerShell 7 required")
@pytest.mark.parametrize("mode,script", [
    ("bundle", "scripts/build_windows_bundle.ps1"),
    ("desktop", "scripts/build_desktop.ps1"),
    ("release", "scripts/build_release.ps1"),
    ("release-acceptance", "scripts/release-acceptance.ps1"),
])
def test_build_modes_dispatch_once_to_existing_script(tmp_path, monkeypatch, mode, script):
    monkeypatch.setenv("ACCEPTANCE_ROOT", ".tmp_tests/current")
    result = run_workflow_powershell(
        tmp_path, build_step("Build with existing PowerShell script")["run"],
        {"inputs.build_mode": mode},
        prefix="function powershell.exe { $args -join '|' ; $global:LASTEXITCODE = 0 }\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count(script) == 1
    assert result.stdout.count("-File|") == 1
    if mode == "release-acceptance":
        assert "-OutputRoot|.tmp_tests/current" in result.stdout
        assert "build_release.ps1" not in result.stdout


def test_draft_job_requires_verified_acceptance_and_preserves_evidence_boundary():
    dispatch = BUILD_WORKFLOW.get("on", BUILD_WORKFLOW.get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["build_mode"]["options"] == ["bundle", "desktop", "release", "release-acceptance"]
    assert dispatch["create_draft"]["type"] == "boolean"
    assert dispatch["create_draft"]["default"] is False
    build = BUILD_JOBS["build"]
    steps = build["steps"]
    assert steps.index(build_step("Validate options")) < steps.index(build_step("Set up Python"))
    verify = build_step("Verify acceptance report and release artifacts")
    assert verify["if"] == "${{ inputs.build_mode == 'release-acceptance' }}"
    assert "always()" not in verify["if"]  # Failed acceptance cannot reach verification.
    assert build["outputs"]["acceptance_verified"] == "${{ steps.acceptance.outputs.verified }}"
    draft = BUILD_JOBS["draft-release"]
    for requirement in (
        "needs.build.result == 'success'", "inputs.build_mode == 'release-acceptance'",
        "inputs.create_draft", "github.ref == 'refs/heads/main'",
        "needs.build.outputs.acceptance_verified == 'true'",
    ):
        assert requirement in draft["if"]
    create = draft["steps"][-1]
    assert '--target "$ACCEPTED_COMMIT"' in create["run"]
    assert create["env"]["ACCEPTED_COMMIT"] == "${{ needs.build.outputs.source_commit }}"
    assert "--draft" in create["run"] and "--notes-file .tmp_tests/release-notes.md" in create["run"]
    assert "sha256sum --strict --check checksums.txt" in create["run"]
    evidence = build_step("Upload acceptance evidence")
    assert "always()" in evidence["if"]
    assert set(evidence["with"]["path"].splitlines()) == {
        "${{ env.ACCEPTANCE_ROOT }}/*/report.json",
        "${{ env.ACCEPTANCE_ROOT }}/*/summary.md",
    }
    assert evidence["with"]["include-hidden-files"] is True
    assert evidence["with"]["if-no-files-found"] == "error"
    upload = build_step("Upload downloadable ZIP artifact")
    assert upload["with"]["path"] == "action-artifacts/*"


def test_draft_release_notes_use_only_selected_changelog_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERSION", "4.0.0")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n## 4.0.0\n\n### Changed\n\n- Current.\n\n"
        "## 3.1.2\n\n- Previous.\n", encoding="utf-8",
    )
    step = next(s for s in BUILD_JOBS["draft-release"]["steps"]
                if s.get("name") == "Prepare changelog release notes")
    exec(step["run"], {})
    assert (tmp_path / ".tmp_tests/release-notes.md").read_text(encoding="utf-8") == (
        "### Changed\n\n- Current.\n"
    )
    monkeypatch.setenv("VERSION", "9.0.0")
    with pytest.raises(SystemExit):
        exec(step["run"], {})


@pytest.mark.windows_powershell
@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("pwsh"),
                    reason="Windows with PowerShell 7 required")
@pytest.mark.parametrize("mode", ["bundle", "desktop", "release", "release-acceptance"])
def test_build_packages_only_selected_artifacts(tmp_path, monkeypatch, mode):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "4.0.0"\n', encoding="utf-8")
    accepted = ".tmp_tests/current/r_run/artifacts/release/4.0.0"
    source = tmp_path / {
        "bundle": "dist/powers-tool", "desktop": "dist/desktop/win-unpacked",
        "release": "release/4.0.0", "release-acceptance": accepted,
    }[mode]
    source.mkdir(parents=True)
    names = ["powers-tool-4.0.0-windows-x64.zip", "powers_tool-4.0.0-py3-none-any.whl",
             "powers_tool-4.0.0.tar.gz", "checksums.txt"]
    for name in (names if mode in {"release", "release-acceptance"} else ["app.exe"]):
        (source / name).write_bytes(name.encode())
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    result = run_workflow_powershell(
        tmp_path, build_step("Package artifacts and extract version")["run"],
        {"inputs.build_mode": mode, "steps.acceptance.outputs.release_dir": accepted},
        prefix="function git { 'abcdef0' }\n",
    )
    assert result.returncode == 0, result.stderr
    artifacts = tmp_path / "action-artifacts"
    if mode in {"release", "release-acceptance"}:
        assert {p.name for p in artifacts.iterdir()} == set(names)
        assert all((artifacts / name).read_bytes() == (source / name).read_bytes() for name in names)
    else:
        assert [p.name for p in artifacts.iterdir()] == [f"powers-tool-{mode}-windows-x64.zip"]


@pytest.mark.windows_powershell
@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("pwsh"),
                    reason="Windows with PowerShell 7 required")
def test_acceptance_dispatch_failure_stops_job(tmp_path):
    result = run_workflow_powershell(
        tmp_path, build_step("Build with existing PowerShell script")["run"],
        {"inputs.build_mode": "release-acceptance"},
        prefix="function powershell.exe { $global:LASTEXITCODE = 1 }\n",
    )
    assert result.returncode != 0
    assert "Release acceptance failed" in result.stderr


@pytest.mark.windows_powershell
@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("pwsh"),
                    reason="Windows with PowerShell 7 required")
def test_acceptance_output_is_unique_and_cannot_reuse_stale_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "environment"))
    replacements = {"github.run_id": "1234", "github.run_attempt": "2"}
    step = build_step("Prepare acceptance output directory")
    result = run_workflow_powershell(tmp_path, step["run"], replacements)
    assert result.returncode == 0, result.stderr
    output = tmp_path / ".tmp_tests/actions-release-acceptance/1234-2"
    assert output.is_dir() and list(output.iterdir()) == []
    assert "ACCEPTANCE_ROOT=.tmp_tests/actions-release-acceptance/1234-2" in (
        tmp_path / "environment"
    ).read_text(encoding="utf-8-sig")
    (output / "old-report.json").write_text("{}", encoding="utf-8")
    result = run_workflow_powershell(tmp_path, step["run"], replacements)
    assert result.returncode != 0
    assert "Acceptance output already exists" in result.stderr
