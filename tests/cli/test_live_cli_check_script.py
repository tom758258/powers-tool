import json
import os
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


def _run_powershell_command(command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=False,
        cwd=Path.cwd(),
        env=process_env,
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


def _fixture_cli_path(tmp_path: Path, *, mode: str, hardware_touched: bool) -> Path:
    fixture_cli = tmp_path / "keysight_power_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        f"""
import json
import sys

payload = {{
    "ok": True,
    "error": None,
    "execution": {{
        "mode": "{mode}",
        "dry_run": False,
        "hardware_touched": {str(hardware_touched)},
    }},
}}

save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _dynamic_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "keysight_power_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        """
import json
import sys

if "no-json" in sys.argv:
    sys.exit(1)

payload = {
    "ok": True,
    "error": None,
    "execution": {
        "mode": "real" if "real" in sys.argv else "simulate",
        "dry_run": "dry-run" in sys.argv,
        "hardware_touched": "hardware-true" in sys.argv,
    },
}

save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _live_fixture_validation_command(output_dir: Path, *, expect_passed: bool) -> str:
    expected_result = "passed" if expect_passed else "failed"
    failure_check = (
        'if ($script:Failures.Count -ne 0) { throw ($script:Failures -join "`n") }'
        if expect_passed
        else 'if ($script:Failures.Count -eq 0) { throw "expected a live validation failure" }'
    )
    return rf"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$case = New-CommandCase -Name "verify" -Suite "readonly" -Phase "live" -Args @("verify", "--json", "--resource", $script:RawResource) -LiveHardwareExpected:$true
$record = Invoke-ValidationCommand -Case $case
if ($record.result -ne "{expected_result}") {{ throw "expected result {expected_result}, got $($record.result)" }}
{failure_check}
if ($record.mode -ne "real") {{ throw "expected mode real, got $($record.mode)" }}
"""


def test_live_validation_accepts_real_execution_mode_fixture(tmp_path):
    fixture_path = _fixture_cli_path(tmp_path, mode="real", hardware_touched=True)
    output_dir = tmp_path / "out"
    command = _live_fixture_validation_command(output_dir, expect_passed=True)
    env = {"PYTHONPATH": str(fixture_path)}
    result = _run_powershell_command(command, env=env)

    assert result.returncode == 0, result.stdout + result.stderr


def test_live_validation_still_rejects_real_mode_without_hardware_touch_fixture(tmp_path):
    fixture_path = _fixture_cli_path(tmp_path, mode="real", hardware_touched=False)
    output_dir = tmp_path / "out"
    command = _live_fixture_validation_command(output_dir, expect_passed=False)
    env = {"PYTHONPATH": str(fixture_path)}
    result = _run_powershell_command(command, env=env)

    assert result.returncode == 0, result.stdout + result.stderr


def test_live_confirmation_warnings_are_scoped_to_selected_suites():
    command = """
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\\scripts\\live-cli-check.ps1
Write-LiveConfirmationWarnings -SuitesToRun @("readonly", "output", "software-sequence")
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Low-power setpoints may be written" in result.stdout
    assert "Outputs may briefly turn on" in result.stdout
    assert "Protection suite writes" not in result.stdout


def test_live_cli_check_uses_phase_specific_artifact_names(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$preflight = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "preflight" -Args @("simulate", "--json")
$live = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "live" -Args @("real", "hardware-true", "--json") -LiveHardwareExpected:$true
$preflightRecord = Invoke-ValidationCommand -Case $preflight
$liveRecord = Invoke-ValidationCommand -Case $live
if ($preflightRecord.result -ne "passed") {{ throw "preflight did not pass" }}
if ($liveRecord.result -ne "passed") {{ throw "live did not pass" }}
if ($preflightRecord.json_path -eq $liveRecord.json_path) {{ throw "artifact paths collided" }}
if ($preflightRecord.json_path -notmatch "preflight-trigger-step-bus\.json$") {{ throw "bad preflight path $($preflightRecord.json_path)" }}
if ($liveRecord.json_path -notmatch "live-trigger-step-bus\.json$") {{ throw "bad live path $($liveRecord.json_path)" }}
"""
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    assert (output_dir / "preflight-trigger-step-bus.json").exists()
    assert (output_dir / "live-trigger-step-bus.json").exists()


def test_live_cli_check_failed_live_command_does_not_reuse_stale_preflight_json(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$preflight = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "preflight" -Args @("simulate", "--json")
$live = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "live" -Args @("no-json", "--json") -LiveHardwareExpected:$true
$preflightRecord = Invoke-ValidationCommand -Case $preflight
$liveRecord = Invoke-ValidationCommand -Case $live
if ($preflightRecord.result -ne "passed") {{ throw "preflight did not pass" }}
if ($liveRecord.result -ne "failed") {{ throw "expected live failure, got $($liveRecord.result)" }}
if ($liveRecord.parse_error -ne "JSON output file was not created.") {{ throw "unexpected parse error $($liveRecord.parse_error)" }}
if ($liveRecord.mode) {{ throw "live mode should be empty when JSON is missing" }}
if ($liveRecord.hardware_touched) {{ throw "live hardware_touched should be empty when JSON is missing" }}
if (Test-Path -LiteralPath (Join-Path $script:OutputDir "live-trigger-step-bus.json")) {{ throw "live JSON should not exist" }}
"""
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    preflight_payload = json.loads((output_dir / "preflight-trigger-step-bus.json").read_text(encoding="utf-8"))
    assert preflight_payload["execution"]["hardware_touched"] is False
    assert not (output_dir / "live-trigger-step-bus.json").exists()


def test_live_cli_check_preflight_still_rejects_hardware_touched_fixture(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$case = New-CommandCase -Name "verify" -Suite "readonly" -Phase "preflight" -Args @("hardware-true", "--json")
$record = Invoke-ValidationCommand -Case $case
if ($record.result -ne "failed") {{ throw "expected preflight failure, got $($record.result)" }}
if ($script:Failures.Count -eq 0) {{ throw "expected failure message" }}
if (($script:Failures -join "`n") -notmatch "no-hardware validation") {{ throw ($script:Failures -join "`n") }}
"""
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr


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
