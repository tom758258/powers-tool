from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPT_IN = "POWERS_TOOL_RUN_CLEAN_PRE_VISA_ACCEPTANCE"
EXPECTED_COMMIT = "POWERS_TOOL_EXPECTED_COMMIT"


@pytest.mark.skipif(os.environ.get(OPT_IN) != "1", reason="clean pre-VISA acceptance is opt-in")
def test_clean_pre_visa_acceptance() -> None:
    expected = os.environ.get(EXPECTED_COMMIT)
    assert expected, f"{EXPECTED_COMMIT} is required"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    assert not status.strip(), "clean pre-VISA acceptance requires a clean working tree"
    assert head == expected, "HEAD does not match the expected reviewed commit"

    prepare = ROOT / "scripts" / "prepare-validation-environment.ps1"
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(prepare),
            "-ExpectedCommit", expected,
            "-DevelopmentPython", sys.executable,
            "-EnvironmentPath", ".venv-validation",
            "-ArtifactRoot", ".tmp_tests\\clean-pre-visa-environment",
        ],
        cwd=ROOT,
        check=True,
    )

    output_root = ROOT / ".tmp_tests" / "live_cli_check"
    before = set(output_root.glob("*")) if output_root.exists() else set()
    env = os.environ.copy()
    env["POWERS_TOOL_VALIDATION_TEST_STOP_BEFORE_VISA"] = "1"
    sentinel = "USB0::POWERS_TOOL_PRE_VISA_SENTINEL::INSTR"
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / "scripts" / "live-cli-check.ps1"),
            "-Target", "keysight-e36312a", "-Connection", "USB", "-Resource", sentinel,
            "-Suite", "readonly",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    created = set(output_root.glob("*")) - before
    assert len(created) == 1
    run_dir = created.pop()
    report = json.loads((run_dir / "shareable" / "report.json").read_text(encoding="utf-8"))

    assert report["validation_mode"] == "pre_visa_test"
    assert report["result"] == "passed"
    assert report["hardware_touched"] is False
    build = report["validation_build"]
    for field in (
        "installed_runtime_verified", "runtime_dependencies_verified", "retained_wheels_verified",
        "installed_files_record_verified", "module_origins_verified",
    ):
        assert build[field] is True
    assert build["repository_source_shadowed"] is False
    assert not [record for record in report["commands"] if record.get("phase") == "live"]
    assert report["instrument_identity"]["availability"] == "not_observed"
    private = run_dir / "private"
    assert not list(private.glob("candidate-run-manifest.json"))
    assert not list(private.glob("candidate-capability-*.json"))
    assert sentinel not in json.dumps(report)
