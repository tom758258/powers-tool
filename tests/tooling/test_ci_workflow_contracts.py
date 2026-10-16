"""Guard targeted Windows CI job selection after using paths-filter."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import re

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
