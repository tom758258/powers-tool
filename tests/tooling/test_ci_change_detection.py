"""Tests for CI path classification, including complete PR and push ranges."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "ci_change_detection", ROOT / "scripts" / "ci_change_detection.py"
)
assert spec is not None and spec.loader is not None
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)

@pytest.mark.parametrize("path,flags", [
    ("README.md", (False, False, False)),
    ("docs/testing-guidelines.md", (False, False, False)),
    ("scripts/release-acceptance.ps1", (True, False, False)),
    ("scripts/live-cli-check.ps1", (True, False, False)),
    ("src/powers_tool_core/driver.py", (True, True, False)),
    ("src/powers_tool_cli/cli.py", (True, True, False)),
    ("src/powers_tool_webui/static/app.js", (True, True, False)),
    ("scripts/build_desktop.ps1", (True, True, False)),
    ("scripts/build_release.ps1", (True, True, True)),
    ("desktop/package-lock.json", (True, True, True)),
    ("desktop/assets/powers-icon.ico", (True, True, False)),
    ("docs/help/help.css", (False, True, False)),
    ("tests/cli/test_cli_wrappers.py", (True, False, False)),
    ("tests/packaging/inspect_windows_bundle.py", (False, True, False)),
    ("tests/packaging/test_release_acceptance.py", (True, False, False)),
    (".github/workflows/tests.yml", (True, True, True)),
    ("uv.lock", (True, True, True)),
])
def test_classification(path, flags):
    assert tuple(selector.classify_paths({path}).values()) == flags

def test_rename_checks_both_paths():
    assert selector.classify_paths({
        "README.md", "scripts/build_release.ps1",
    }) == {"validation": True, "packaging": True, "release-layout": True}

def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()

def _init(root: Path) -> str:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "ci@example.invalid")
    _git(root, "config", "user.name", "CI test")
    (root / "README.md").write_text("original\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "original")
    return _git(root, "rev-parse", "HEAD")

def _run(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ci_change_detection.py")],
        cwd=root, env={**os.environ, **env}, capture_output=True, text=True, check=False,
    )

def test_push_covers_multiple_commits(tmp_path):
    before = _init(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build_release.ps1").write_text("build\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "change build")
    (tmp_path / "README.md").write_text("updated\n")
    _git(tmp_path, "commit", "-am", "docs change")
    proc = _run(tmp_path, {
        "GITHUB_EVENT_NAME": "push",
        "PUSH_BEFORE": before,
        "GITHUB_SHA": _git(tmp_path, "rev-parse", "HEAD"),
    })
    assert proc.returncode == 0, proc.stderr
    assert '"release-layout": true' in proc.stdout

def test_pr_uses_merge_base_not_last_commit(tmp_path):
    _init(tmp_path)
    _git(tmp_path, "checkout", "-qb", "feature")
    target = tmp_path / "src" / "powers_tool_core"
    target.mkdir(parents=True)
    (target / "driver.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "runtime change")
    feature_sha = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "main")
    (tmp_path / "README.md").write_text("main moved\n")
    _git(tmp_path, "commit", "-am", "move base")
    proc = _run(tmp_path, {
        "GITHUB_EVENT_NAME": "pull_request",
        "PR_BASE_SHA": _git(tmp_path, "rev-parse", "HEAD"),
        "PR_HEAD_SHA": feature_sha,
    })
    assert proc.returncode == 0, proc.stderr
    assert '"validation": true' in proc.stdout
    assert '"packaging": true' in proc.stdout

def test_failed_comparison_does_not_skip_windows_jobs(tmp_path):
    _init(tmp_path)
    proc = _run(tmp_path, {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_SHA": _git(tmp_path, "rev-parse", "HEAD"),
        "PUSH_BEFORE": "abcdeadbeef",
    })
    assert proc.returncode != 0
    assert "trusted changed range" in proc.stderr

def test_manual_dispatch_forces_all_windows_checks(tmp_path):
    sha = _init(tmp_path)
    proc = _run(tmp_path, {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": sha})
    assert proc.returncode == 0, proc.stderr
    assert '"release-layout": true' in proc.stdout

def test_missing_before_sha_forces_all_windows_checks(tmp_path):
    sha = _init(tmp_path)
    proc = _run(tmp_path, {"GITHUB_EVENT_NAME": "push", "GITHUB_SHA": sha, "PUSH_BEFORE": "0" * 40})
    assert proc.returncode == 0, proc.stderr
    assert '"validation": true' in proc.stdout
    assert '"packaging": true' in proc.stdout

def test_git_rename_detection_includes_original_path(tmp_path):
    _init(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build_release.ps1").write_text("same\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add script")
    before = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "mv", "scripts/build_release.ps1", "scripts/renamed.ps1")
    _git(tmp_path, "commit", "-qm", "rename release script")
    proc = _run(tmp_path, {"GITHUB_EVENT_NAME": "push", "PUSH_BEFORE": before,
                            "GITHUB_SHA": _git(tmp_path, "rev-parse", "HEAD")})
    assert proc.returncode == 0, proc.stderr
    assert '"release-layout": true' in proc.stdout
