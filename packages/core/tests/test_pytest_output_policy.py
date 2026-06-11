from __future__ import annotations

from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE_TEST = "packages/core/tests/test_import.py"


def run_probe(basetemp: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            PROBE_TEST,
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            basetemp,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pytest_basetemp_allows_tmp_tests():
    result = run_probe(".tmp_tests/output_policy_allowed")

    assert result.returncode == 0, result.stdout + result.stderr


def test_pytest_basetemp_rejects_local():
    result = run_probe("Local/output_policy_rejected")

    assert result.returncode != 0
    assert "pytest basetemp must not be inside Local/" in result.stderr
    assert not (REPO_ROOT / "Local" / "output_policy_rejected").exists()
