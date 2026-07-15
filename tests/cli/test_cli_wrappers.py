from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_validation_script_inventory_and_obsolete_removals() -> None:
    assert (ROOT / "scripts" / "preflight-cli.ps1").is_file()
    assert (ROOT / "scripts" / "live-cli-check.ps1").is_file()
    assert (ROOT / "scripts" / "_validation_helpers.ps1").is_file()
    for obsolete in (
        "no-hardware-regression.ps1",
        "preflight-smoke-validation.ps1",
        "live-smoke-validation-check.ps1",
    ):
        assert not (ROOT / "scripts" / obsolete).exists()


def test_shared_helper_owns_all_model_and_suite_boundaries() -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    helper = ROOT / "scripts" / "_validation_helpers.ps1"
    command = (
        f". '{helper}'; "
        "$profiles = @(Get-ValidationTargetProfiles | ForEach-Object { "
        "[pscustomobject]@{ model_id=$_.model_id; channels=@($_.channels); suites=@($_.suites) } }); "
        "ConvertTo-Json -InputObject $profiles -Compress -Depth 5"
    )
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    profiles = {item["model_id"]: item for item in json.loads(result.stdout)}
    assert set(profiles) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    }
    assert profiles["keysight-e36312a"]["suites"] == [
        "readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence"
    ]
    assert profiles["keysight-edu36311a"]["suites"] == [
        "readonly", "output", "protection", "software-sequence"
    ]
    assert profiles["keysight-e3646a"]["suites"] == [
        "readonly", "output", "software-sequence"
    ]


def test_preflight_report_contract_executes_no_hardware_cli() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-e3646a",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    reports = sorted(output.glob("run_*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["kind"] == "powers-tool-cli-preflight"
    assert report["status"] == "passed"
    assert report["targets"] == ["keysight-e3646a"]
    assert report["hardware_touched"] is False
    assert report["summary_counts"]["failed"] == 0
    assert reports[0].with_name("summary.md").is_file()
    target_report = json.loads(
        (reports[0].parent / "keysight-e3646a" / "report.json").read_text(encoding="utf-8")
    )
    assert target_report["commands"]
    assert all(command["hardware_touched"] is False for command in target_report["commands"])
    assert {command["category"] for command in target_report["commands"]} >= {
        "identity", "metadata", "readonly", "output", "safe-off",
        "software-sequence", "diagnostics", "resource-planning",
    }
    for command in target_report["commands"]:
        for key in ("json_path", "stdout_path", "stderr_path"):
            assert str(command[key]).startswith(".tmp_tests\\")
