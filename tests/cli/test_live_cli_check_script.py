import json
import os
import shutil
import subprocess
import sys
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


def _confirmation_warnings_for_suites(suites):
    suite_items = ", ".join(f'"{suite}"' for suite in suites)
    command = f"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\\scripts\\live-cli-check.ps1
Write-LiveConfirmationWarnings -SuitesToRun @({suite_items})
"""
    return _run_powershell_command(command)


def test_live_confirmation_warnings_are_scoped_to_selected_suites():
    result = _confirmation_warnings_for_suites(
        ["readonly", "output", "software-sequence"]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Low-power setpoints may be written" in result.stdout
    assert (
        "Outputs may briefly turn on for output or software-sequence cases."
        in result.stdout
    )
    assert "trigger-list cases" not in result.stdout
    assert "Protection suite writes" not in result.stdout


def test_live_confirmation_warnings_include_trigger_list_when_selected():
    result = _confirmation_warnings_for_suites(
        ["readonly", "output", "trigger-list", "software-sequence"]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Low-power setpoints may be written" in result.stdout
    assert (
        "Outputs may briefly turn on for output, trigger-list, or software-sequence cases."
        in result.stdout
    )
    assert "Protection suite writes" not in result.stdout


def test_live_confirmation_warnings_format_single_output_affecting_suite():
    result = _confirmation_warnings_for_suites(["readonly", "output"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Outputs may briefly turn on for output cases." in result.stdout


def test_live_confirmation_warnings_format_single_software_sequence_suite():
    result = _confirmation_warnings_for_suites(["readonly", "software-sequence"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "Outputs may briefly turn on for software-sequence cases." in result.stdout
    )


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
    assert (output_dir / "private" / "preflight-trigger-step-bus.json").exists()
    assert (output_dir / "private" / "live-trigger-step-bus.json").exists()
    assert (output_dir / "shareable" / "preflight-trigger-step-bus.json").exists()
    assert (output_dir / "shareable" / "live-trigger-step-bus.json").exists()


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
    preflight_payload = json.loads((output_dir / "private" / "preflight-trigger-step-bus.json").read_text(encoding="utf-8"))
    assert preflight_payload["execution"]["hardware_touched"] is False
    assert not (output_dir / "private" / "live-trigger-step-bus.json").exists()


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
    assert report["schema_version"] == "1.1"
    assert report["support_policy_mode"] == "validation"
    assert report["pending_live_support_allowed"] is True
    assert report["candidate_evidence_only"] is True
    assert report["promotes_live_support"] is False
    assert report["plan_only"] is True
    assert report["live_executed"] is False
    assert report["expected_model"] == target
    assert report["transport_scope"] == {"USB": "usb", "ASRL": "asrl"}[connection]
    assert report["backend"] == "system_visa"
    assert report["backend_scope"] == "system_visa"
    assert report["backend_argument"] is None
    assert report["instrument_identity"]["availability"] == "not_observed_plan_only"
    assert report["instrument_identity"]["detected_model"] is None
    assert report["cleanup"]["status"] == "not_executed_plan_only"
    assert all(command["hardware_touched"] is False for command in report["commands"])


def test_live_cli_check_centrally_adds_validation_flag_only_for_policy_commands():
    command = r"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$policy = @(Add-ValidationSupportPolicyArgument -Arguments @("measure", "--json"))
if (@($policy | Where-Object { $_ -eq "--validation-allow-pending-live-support" }).Count -ne 1) { throw "policy command did not receive exactly one flag" }
$duplicate = @(Add-ValidationSupportPolicyArgument -Arguments @("measure", "--validation-allow-pending-live-support", "--json"))
if (@($duplicate | Where-Object { $_ -eq "--validation-allow-pending-live-support" }).Count -ne 1) { throw "duplicate flag inserted" }
foreach ($diagnostic in @("list-resources", "verify", "identify", "error", "clear")) {
    $args = @(Add-ValidationSupportPolicyArgument -Arguments @($diagnostic, "--json"))
    if ($args -contains "--validation-allow-pending-live-support") { throw "$diagnostic should remain exempt" }
}
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("value", "backend", "scope", "argument"),
    [
        (None, "system_visa", "system_visa", None),
        ("@py", "@py", "pyvisa_py", "@py"),
        ("@ivi", "@ivi", "custom_visa", "@ivi"),
    ],
)
def test_live_cli_check_normalizes_backend_for_artifacts(value, backend, scope, argument):
    literal = "$null" if value is None else f'"{value}"'
    expected_argument = "$null" if argument is None else f'"{argument}"'
    command = rf"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$fields = Get-BackendArtifactFields -Value {literal}
if ($fields.backend -ne "{backend}") {{ throw "wrong backend: $($fields.backend)" }}
if ($fields.backend_scope -ne "{scope}") {{ throw "wrong scope: $($fields.backend_scope)" }}
if ($fields.backend_argument -ne {expected_argument}) {{ throw "wrong backend argument" }}
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr


def test_live_cli_check_plan_artifact_redacts_resource_and_command_paths():
    resource = "TCPIP0::PLANONLY::E36312A::INSTR"
    result = _run_live_cli_check(
        "-Target",
        "E36312A",
        "-Connection",
        "LAN",
        "-Resource",
        resource,
        "-Backend",
        "@py",
        "-Suite",
        "readonly",
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert resource not in report_text
    assert str(Path.cwd()) not in report_text
    assert report["resource"] == "LAN:<redacted-resource>"
    assert all("<redacted-resource>" not in command["arguments"] for command in report["commands"])
    assert "candidate validation evidence only" in report_path.with_name("summary.md").read_text(encoding="utf-8")


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
    assert "sequence-unsupported-protection-dry-run" in case_names
    assert "sequence-unsupported-trigger-dry-run" in case_names
    assert "sequence-unsupported-snapshot-dry-run" in case_names
    assert "sequence-unsupported-restore-dry-run" in case_names
    assert "sequence-unsupported-native-list-dry-run" in case_names
    assert "sequence-unsupported-completion-pulse-dry-run" in case_names
    assert all(command["hardware_touched"] is False for command in report["commands"])


def test_live_cli_check_full_suite_composition_is_model_aware():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'return @("readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence")' in script
    assert 'return @("readonly", "output", "protection", "software-sequence")' in script
    assert 'return @("readonly", "output", "software-sequence")' in script


@pytest.mark.parametrize(
    ("target", "connection", "resource", "expected_suites"),
    [
        (
            "E36312A",
            "USB",
            "USB0::SIM::E36312A::INSTR",
            ["readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence"],
        ),
        (
            "EDU36311A",
            "USB",
            "USB0::SIM::EDU36311A::INSTR",
            ["readonly", "output", "protection", "software-sequence"],
        ),
        (
            "E3646A",
            "ASRL",
            "ASRL1::SIM::E3646A::INSTR",
            ["readonly", "output", "software-sequence"],
        ),
    ],
)
def test_live_cli_check_full_plan_reports_expanded_software_sequence_suites(
    target: str,
    connection: str,
    resource: str,
    expected_suites: list[str],
):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "full",
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report_path.with_name("summary.md").read_text(encoding="utf-8")
    assert report["suites"] == expected_suites
    assert "software-sequence" in report["suites"]
    assert "software-sequence" in summary
    case_names = {case["name"] for case in report["cases"] if case["suite"] == "software-sequence"}
    assert {
        "ramp-list-lint",
        "ramp-list-dry-run",
        "sequence-lint-readonly",
        "sequence-dry-run-readonly",
    } <= case_names
    assert all(command["hardware_touched"] is False for command in report["commands"])


@pytest.mark.parametrize(
    ("target", "connection", "resource"),
    [
        ("E36312A", "USB", "USB0::SIM::E36312A::INSTR"),
        ("EDU36311A", "USB", "USB0::SIM::EDU36311A::INSTR"),
        ("E3646A", "ASRL", "ASRL1::SIM::E3646A::INSTR"),
    ],
)
def test_live_cli_check_software_sequence_plan_only_supported_for_active_targets(target: str, connection: str, resource: str):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "software-sequence",
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suites"] == ["software-sequence"]
    command_names = [command["name"] for command in report["commands"]]
    assert "ramp-list-lint" in command_names
    assert "ramp-list-dry-run" in command_names
    assert "sequence-lint-readonly" in command_names
    assert "sequence-dry-run-readonly" in command_names
    assert len({command["json_path"] for command in report["commands"]}) == len(report["commands"])
    assert len({command["stdout_path"] for command in report["commands"]}) == len(report["commands"])
    assert len({command["stderr_path"] for command in report["commands"]}) == len(report["commands"])


@pytest.mark.parametrize(
    ("target", "connection", "resource", "expected_failures"),
    [
        (
            "EDU36311A",
            "USB",
            "USB0::SIM::EDU36311A::INSTR",
            {
                "sequence-unsupported-trigger-dry-run",
                "sequence-unsupported-trigger-simulate",
                "sequence-unsupported-snapshot-dry-run",
                "sequence-unsupported-snapshot-simulate",
                "sequence-unsupported-restore-dry-run",
                "sequence-unsupported-restore-simulate",
                "sequence-unsupported-native-list-dry-run",
                "sequence-unsupported-native-list-simulate",
            },
        ),
        (
            "E3646A",
            "ASRL",
            "ASRL1::SIM::E3646A::INSTR",
            {
                "sequence-unsupported-protection-dry-run",
                "sequence-unsupported-protection-simulate",
                "sequence-unsupported-trigger-dry-run",
                "sequence-unsupported-trigger-simulate",
                "sequence-unsupported-snapshot-dry-run",
                "sequence-unsupported-snapshot-simulate",
                "sequence-unsupported-restore-dry-run",
                "sequence-unsupported-restore-simulate",
                "sequence-unsupported-native-list-dry-run",
                "sequence-unsupported-native-list-simulate",
                "sequence-unsupported-completion-pulse-dry-run",
                "sequence-unsupported-completion-pulse-simulate",
            },
        ),
    ],
)
def test_live_cli_check_software_sequence_expected_failures_are_reported_as_passed(
    target: str,
    connection: str,
    resource: str,
    expected_failures: set[str],
):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "software-sequence",
        "-PlanOnly",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    cases_by_name = {case["name"]: case for case in report["cases"]}
    assert expected_failures <= set(cases_by_name)
    for name in expected_failures:
        assert cases_by_name[name]["expected_success"] is False
        assert cases_by_name[name]["result"] == "passed"


def _cleanup_fixture_cli_path(
    tmp_path: Path,
    *,
    safe_off_ok: bool = True,
    output_state_ok: bool = True,
    error_queue_ok: bool = True,
    output_states: object = None,
    instrument_errors: list[str] | None = None,
) -> Path:
    fixture_cli = tmp_path / "keysight_power_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    config = json.dumps(
        {
            "safe_off_ok": safe_off_ok,
            "output_state_ok": output_state_ok,
            "error_queue_ok": error_queue_ok,
            "output_states": [{"channel": 1, "enabled": False}] if output_states is None else output_states,
            "instrument_errors": [] if instrument_errors is None else instrument_errors,
        }
    )
    (fixture_cli / "cli.py").write_text(
        rf"""
import json
import sys

config = json.loads({config!r})
command = sys.argv[1]
payload = {{
    "ok": True,
    "error": None,
    "execution": {{"mode": "real", "dry_run": False, "hardware_touched": True}},
    "data": {{
        "resource": {{
            "resource": "TCPIP0::192.168.50.77::5025::SOCKET",
            "idn": {{
                "raw": "KEYSIGHT,E36312A,MY12345678,2.10",
                "manufacturer": "KEYSIGHT",
                "model": "E36312A",
                "serial": "MY12345678",
                "firmware": "2.10",
                "parse_ok": True,
            }},
        }},
        "external_path": r"C:\\Users\\Example User\\private\\sequence.yaml",
    }},
}}
if command == "safe-off" and not config["safe_off_ok"]:
    payload["ok"] = False
    payload["error"] = {{"code": "safe_off_failed", "message": "safe-off failed"}}
elif command == "output-state":
    payload["data"] = {{"outputs": config["output_states"]}}
    if not config["output_state_ok"]:
        payload["ok"] = False
        payload["error"] = {{"code": "output_state_failed", "message": "output-state failed"}}
elif command == "error":
    payload["data"] = {{"errors": config["instrument_errors"]}}
    if not config["error_queue_ok"]:
        payload["ok"] = False
        payload["error"] = {{"code": "error_queue_failed", "message": "error queue failed"}}

print(r"TCPIP0::192.168.50.77::5025::SOCKET KEYSIGHT,E36312A,MY12345678,2.10 C:\Users\Example User\private\sequence.yaml")
print(r"TCPIP0::192.168.50.77::5025::SOCKET MY12345678", file=sys.stderr)
save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
sys.exit(0 if payload["ok"] else 2)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _run_state_changing_fixture(
    output_dir: Path,
    *,
    restore: bool = True,
    expect_result: str = "passed",
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    command = rf"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "TCPIP0::192.168.50.77::5025::SOCKET"
$script:ResourceDisplay = "LAN:<redacted-resource>"
$script:NormalizedTarget = "E36312A"
$script:ConnectionLabel = "LAN"
$script:TransportScope = "tcpip"
$script:BackendArtifact = Get-BackendArtifactFields -Value "@py"
$script:BackendValue = "@py"
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:SuitesToRun = @("output")
$script:Suite = "output"
$script:StateChanging = $true
$script:Restore = ${str(restore).lower()}
$script:PlanOnly = $false
$case = New-CommandCase -Name "fixture-set" -Suite "output" -Phase "live" -Args @("set", "--json", "--resource", $script:RawResource, "--channel", "1", "--voltage", "1", "--current", "0.05", "--confirm") -StateChanging:$true -LiveHardwareExpected:$true
Invoke-ValidationCommand -Case $case | Out-Null
Invoke-SafeOffCleanup -Role "final"
$result = if ($script:Failures.Count -eq 0) {{ "passed" }} else {{ "failed" }}
if (-not $script:Restore -and $result -eq "passed") {{ $result = "passed_without_cleanup_verification" }}
Write-ValidationArtifacts -ValidationMode "live" -Result $result -StartedAt (Get-Date)
if ($result -ne "{expect_result}") {{ throw "expected {expect_result}, got $result" }}
Write-Output (Join-Path $script:ShareableArtifactDir "report.json")
"""
    return _run_powershell_command(command, env=env)


def test_live_cli_check_shareable_artifacts_recursively_redact_private_live_fixture(tmp_path):
    fixture_path = _cleanup_fixture_cli_path(tmp_path)
    result = _run_state_changing_fixture(
        tmp_path / "out",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = Path(result.stdout.strip())
    shareable_dir = report_path.parent
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert shareable_dir.name == "shareable"
    assert report["shareable_artifact_dir"].endswith("\\shareable")
    assert report["instrument_identity"] == {
        "availability": "observed",
        "manufacturer": "KEYSIGHT",
        "detected_model": "E36312A",
        "firmware": "2.10",
        "serial": "<redacted>",
        "serial_redacted": True,
        "source_command": "fixture-set",
    }
    assert all("\\shareable\\" in value for command in report["commands"] for value in (command["json_path"], command["stdout_path"], command["stderr_path"]))
    assert all("\\private\\" not in " ".join(command["arguments"]) for command in report["commands"])
    forbidden = (
        "TCPIP0::192.168.50.77::5025::SOCKET",
        "192.168.50.77",
        "MY12345678",
        "KEYSIGHT,E36312A,MY12345678,2.10",
        r"C:\Users\Example User",
        str(Path.cwd()),
        str(Path(sys.executable)),
    )
    shareable_text = "\n".join(path.read_text(encoding="utf-8") for path in shareable_dir.rglob("*") if path.is_file())
    assert all(value not in shareable_text for value in forbidden)
    for expected in ("KEYSIGHT", "E36312A", "2.10", "fixture-set", "transport_scope", "backend_scope"):
        assert expected in shareable_text
    shareable_payload = json.loads((shareable_dir / "live-fixture-set.json").read_text(encoding="utf-8"))
    assert shareable_payload["data"]["resource"]["idn"]["raw"] == "<redacted-idn>"
    assert shareable_payload["data"]["resource"]["idn"]["serial"] == "<redacted>"
    assert (shareable_dir.parent / "private").is_dir()


@pytest.mark.parametrize(
    ("safe_off_ok", "output_states", "instrument_errors", "cleanup_status", "failure_fragment"),
    [
        (False, [{"channel": 1, "enabled": False}], [], "failed", "Cleanup safe-off command failed."),
        (True, [{"channel": 1, "enabled": True}], [], "failed", "Cleanup could not confirm that all outputs are off."),
        (True, [{"channel": 1, "enabled": None}], [], "partial", "Cleanup did not produce verifiable output-state evidence."),
        (True, [{"channel": 1, "enabled": False}], ["-200,Instrument error"], "partial", "Cleanup finished with instrument errors."),
    ],
)
def test_live_cli_check_required_state_cleanup_incomplete_forces_failed_result(
    tmp_path,
    safe_off_ok,
    output_states,
    instrument_errors,
    cleanup_status,
    failure_fragment,
):
    fixture_path = _cleanup_fixture_cli_path(
        tmp_path,
        safe_off_ok=safe_off_ok,
        output_states=output_states,
        instrument_errors=instrument_errors,
    )
    result = _run_state_changing_fixture(
        tmp_path / "out",
        expect_result="failed",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["result"] == "failed"
    assert report["cleanup"]["status"] == cleanup_status
    assert failure_fragment in report["failures"]


@pytest.mark.parametrize(
    ("fixture_kwargs", "failure_fragment"),
    [
        ({"output_state_ok": False}, "Cleanup did not produce verifiable output-state evidence."),
        ({"error_queue_ok": False}, "Cleanup could not verify the instrument error queue."),
    ],
)
def test_live_cli_check_required_state_cleanup_command_failures_are_not_passed(
    tmp_path,
    fixture_kwargs,
    failure_fragment,
):
    fixture_path = _cleanup_fixture_cli_path(tmp_path, **fixture_kwargs)
    result = _run_state_changing_fixture(
        tmp_path / "out",
        expect_result="failed",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["cleanup"]["status"] == "partial"
    assert failure_fragment in report["failures"]


def test_live_cli_check_restore_false_is_truthfully_not_cleanup_verified(tmp_path):
    fixture_path = _cleanup_fixture_cli_path(tmp_path)
    result = _run_state_changing_fixture(
        tmp_path / "out",
        restore=False,
        expect_result="passed_without_cleanup_verification",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["cleanup"]["requested"] is False
    assert report["cleanup"]["attempted"] is False
    assert report["cleanup"]["status"] == "skipped_by_operator"
    assert report["result"] == "passed_without_cleanup_verification"


def test_live_cli_check_cleanup_lifecycle_statuses_are_distinct():
    command = r"""
$env:KEYSIGHT_POWER_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:StateChanging = $true
$script:Restore = $true
$planned = New-CleanupEvidence -ValidationMode "planned"
$preflight = New-CleanupEvidence -ValidationMode "preflight_failed"
$confirmation = New-CleanupEvidence -ValidationMode "confirmation_required"
$script:StateChanging = $false
$readonly = New-CleanupEvidence -ValidationMode "live"
$script:StateChanging = $true
$script:Restore = $false
$skipped = New-CleanupEvidence -ValidationMode "live"
@{ planned = $planned.status; preflight = $preflight.status; confirmation = $confirmation.status; readonly = $readonly.status; skipped = $skipped.status } | ConvertTo-Json -Compress
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "planned": "not_executed_plan_only",
        "preflight": "not_executed_preflight_failed",
        "confirmation": "not_executed_confirmation_required",
        "readonly": "not_required",
        "skipped": "skipped_by_operator",
    }


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
