import json
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path("scripts/live-cli-check.ps1")


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is required for live-cli-check.ps1 tests")
    return executable


def _run_live_cli_check(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        check=False,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )


def _report_path(stdout: str, stderr: str) -> Path:
    combined = stdout + "\n" + stderr
    for line in combined.splitlines():
        if "Report:" in line:
            return Path(line.split("Report:", 1)[1].strip())
        if "See " in line and line.strip().endswith("report.json."):
            return Path(line.rsplit("See ", 1)[1].rstrip("."))
    raise AssertionError(f"report path not found in output:\n{combined}")


@pytest.mark.parametrize(
    ("target", "connection", "resource"),
    [
        ("E36312A", "USB", "USB0::SIM::E36312A::INSTR"),
        ("EDU36311A", "USB", "USB0::SIM::EDU36311A::INSTR"),
        ("E3646A", "ASRL", "ASRL1::SIM::E3646A::INSTR"),
    ],
)
def test_live_cli_check_readonly_plan_only_succeeds_without_hardware(target, connection, resource):
    assert SCRIPT.exists()

    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "readonly",
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Press Enter" not in result.stdout
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    assert report["validation_mode"] == "planned"
    assert report["plan_only"] is True
    assert report["live_executed"] is False
    assert all(command["hardware_touched"] is False for command in report["commands"])


@pytest.mark.parametrize(
    ("target", "connection", "resource", "suite"),
    [
        ("EDU36311A", "USB", "USB0::SIM::EDU36311A::INSTR", "trigger-list"),
        ("EDU36311A", "USB", "USB0::SIM::EDU36311A::INSTR", "snapshot"),
        ("E3646A", "ASRL", "ASRL1::SIM::E3646A::INSTR", "protection"),
        ("E3646A", "ASRL", "ASRL1::SIM::E3646A::INSTR", "trigger-list"),
        ("E3646A", "ASRL", "ASRL1::SIM::E3646A::INSTR", "snapshot"),
    ],
)
def test_live_cli_check_unsupported_explicit_suites_fail_before_live(target, connection, resource, suite):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        suite,
        "-PlanOnly",
    )

    assert result.returncode == 2
    assert "Unsupported suite" in (result.stdout + result.stderr)


def test_live_cli_check_e3646a_full_plan_contains_software_sequence_not_native_list():
    result = _run_live_cli_check(
        "-Target",
        "E3646A",
        "-Connection",
        "ASRL",
        "-Resource",
        "ASRL1::SIM::E3646A::INSTR",
        "-Suite",
        "full",
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    assert report["suites"] == ["readonly", "output", "software-sequence"]
    case_names = {case["name"] for case in report["cases"]}
    assert "reject-protection-step" in case_names
    assert "reject-trigger-step" in case_names
    assert "reject-snapshot-step" in case_names
    assert "reject-restore-step" in case_names
    assert "reject-native-list-step" in case_names
    assert "reject-completion-pulse-step" in case_names
    assert all(command["hardware_touched"] is False for command in report["commands"])


def test_live_cli_check_full_suite_composition_is_model_aware():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'return @("readonly", "output", "protection", "snapshot", "trigger-list")' in script
    assert 'return @("readonly", "output", "protection")' in script
    assert 'return @("readonly", "output", "software-sequence")' in script


@pytest.mark.parametrize("target", ["E36103B", "E36232A", "GENERIC"])
def test_live_cli_check_descoped_and_generic_targets_fail_before_live(target: str):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        "USB",
        "-Resource",
        "USB0::SIM::E36312A::INSTR",
        "-Suite",
        "readonly",
        "-PlanOnly",
    )

    assert result.returncode == 2
    combined = result.stdout + result.stderr
    if target == "GENERIC":
        assert "GENERIC is no-hardware only" in combined
    else:
        assert "Unsupported -Target" in combined
    assert "Running no-hardware preflight" not in result.stdout


def test_live_smoke_script_remains_compatible_legacy_entrypoint():
    smoke = Path("scripts/live-smoke-validation-check.ps1").read_text(encoding="utf-8")

    assert '[string]$Profile = "auto"' in smoke
    assert "Live smoke validation supports only Target E36312A or EDU36311A." in smoke
    assert "preflight-smoke-validation.ps1" in smoke


def test_english_docs_describe_suite_scoped_validation_and_e3646a_boundaries():
    docs = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/cli/README.md",
            "docs/core/README.md",
            "docs/core/supported-models.md",
            "docs/webui/README.md",
        )
    )

    normalized = " ".join(docs.split())
    assert "live-cli-check.ps1" in docs
    assert "validates only the selected" in normalized
    assert "does not validate the entire model" in normalized
    assert "Legacy smoke" in docs
    assert "software workflows, not native LIST" in normalized
    assert "OUTP ON/OFF" in docs
