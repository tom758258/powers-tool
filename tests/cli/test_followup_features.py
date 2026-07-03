import json
from pathlib import Path

import keysight_power_cli.cli as cli
from keysight_power_core.errors import VisaConnectionError


class FakeSession:
    def __init__(
        self,
        idn: str = "KEYSIGHT,E36312A,SERIAL0000,1.0",
        *,
        query_responses: dict[str, str] | None = None,
    ) -> None:
        self.idn = idn
        self.query_responses = query_responses or {}
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        if command == "SYST:ERR?":
            return '0,"No error"'
        try:
            return self.query_responses[command]
        except KeyError as exc:
            raise VisaConnectionError(f"No fake response for {command!r}") from exc


class CleanupFailingSession(FakeSession):
    def write(self, command: str) -> None:
        self.writes.append(command)
        if command.startswith("OUTP OFF"):
            raise VisaConnectionError(f"cleanup failed for {command}")


def _payload(capsys):
    return json.loads(capsys.readouterr().out)


def _write_snapshot(
    path,
    *,
    enabled=False,
    voltage=1.0,
    current=0.05,
    ovp=6.0,
    ocp=True,
    ocp_delay=None,
    ocp_delay_trigger=None,
    errors=None,
):
    protection = {"ovp_voltage": ovp, "ocp_enabled": ocp}
    if ocp_delay is not None:
        protection["ocp_delay"] = ocp_delay
    if ocp_delay_trigger is not None:
        protection["ocp_delay_trigger"] = ocp_delay_trigger
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "resource": "USB0::FAKE::E36312A::INSTR",
                    "idn": {
                        "raw": "KEYSIGHT,E36312A,SERIAL0000,1.0",
                        "manufacturer": "KEYSIGHT",
                        "model": "E36312A",
                        "serial": "SERIAL0000",
                        "firmware": "1.0",
                        "parse_ok": True,
                    },
                    "errors": errors or [],
                    "outputs": [{"channel": 1, "enabled": enabled}],
                    "readback": [{"channel": 1, "setpoints": {"voltage": voltage, "current": current}}],
                    "measurements": [{"channel": 1, "measurements": {"voltage": voltage + 0.1, "current": current + 0.01}}],
                    "protection": {"over_voltage_tripped": False, "over_current_tripped": False},
                    "protection_settings": [{"channel": 1, "protection": protection}],
                },
            }
        ),
        encoding="utf-8",
    )


def test_output_on_requires_confirm_above_configured_threshold(monkeypatch, tmp_path, capsys):
    config = tmp_path / "safety.toml"
    config.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5
confirm_above_voltage = 0.5
allowed_channels = [1]
""".strip(),
        encoding="utf-8",
    )
    session = FakeSession(query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"})
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--safety-config",
                str(config),
            ]
        )
        == 2
    )

    payload = _payload(capsys)
    assert payload["error"]["code"] == "confirmation_required"
    assert session.writes == []


def test_apply_no_output_does_not_require_confirm(monkeypatch, tmp_path, capsys):
    config = tmp_path / "safety.toml"
    config.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5
confirm_above_voltage = 0.5
allowed_channels = [1]
""".strip(),
        encoding="utf-8",
    )
    session = FakeSession()
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
                "--safety-config",
                str(config),
            ]
        )
        == 0
    )
    _payload(capsys)
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]


def test_snapshot_diff_reports_core_changes(tmp_path, capsys):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_snapshot(before)
    _write_snapshot(after, enabled=True, voltage=1.2, ovp=4.0, errors=['-100,"Command error"'])

    assert cli.main(["snapshot-diff", "--json", "--before", str(before), "--after", str(after)]) == 0

    payload = _payload(capsys)
    categories = {difference["category"] for difference in payload["data"]["differences"]}
    assert {"output", "setpoint", "measurement", "protection_setting", "error_queue"} <= categories


def test_snapshot_diff_summary_json_keeps_differences(tmp_path, capsys):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_snapshot(before)
    _write_snapshot(after, enabled=True, voltage=1.2)

    assert cli.main(["snapshot-diff", "--summary", "--json", "--before", str(before), "--after", str(after)]) == 0

    payload = _payload(capsys)
    assert payload["data"]["summary"]["output"] == 1
    assert payload["data"]["summary"]["setpoint"] == 1
    assert payload["data"]["differences"]
    assert payload["metadata"]["duration_ms"] >= 0


def test_snapshot_diff_summary_human_omits_individual_differences(tmp_path, capsys):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_snapshot(before)
    _write_snapshot(after, enabled=True)

    assert cli.main(["snapshot-diff", "--summary", "--before", str(before), "--after", str(after)]) == 0

    output = capsys.readouterr().out
    assert "Changed: true" in output
    assert "output: 1" in output
    assert "enabled:" not in output


def test_restore_from_snapshot_dry_run_orders_safe_operations(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot, enabled=True)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--dry-run",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    actions = [step["action"] for step in _payload(capsys)["data"]["plan"]["steps"]]
    assert actions == [
        "output_off",
        "set_over_voltage_protection",
        "set_over_current_protection_enabled",
        "set_current_limit",
        "set_voltage",
    ]


def test_restore_from_snapshot_dry_run_restores_ocp_delay_settings(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot, ocp_delay=0.5, ocp_delay_trigger="cc-transition")

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--dry-run",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    steps = _payload(capsys)["data"]["plan"]["steps"]
    assert [step["action"] for step in steps] == [
        "output_off",
        "set_over_voltage_protection",
        "set_over_current_protection_enabled",
        "set_over_current_protection_delay",
        "set_over_current_protection_delay_trigger",
        "set_current_limit",
        "set_voltage",
    ]
    assert steps[3]["command"] == "CURR:PROT:DEL 0.5,(@1)"
    assert steps[4]["command"] == "CURR:PROT:DEL:STAR CCTR,(@1)"


def test_restore_from_snapshot_real_e3646a_remains_disabled(monkeypatch, tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot)
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                "--confirm",
            ]
        )
        == 2
    )

    payload = _payload(capsys)
    assert payload["error"]["type"] in {"validation", "unsupported_model"}
    assert not any(command.startswith(("VOLT", "CURR", "OUTP")) for command in session.writes)


def test_restore_from_snapshot_plan_json_requires_dry_run(monkeypatch, tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot)

    def fail_open(*args, **kwargs):
        raise AssertionError("restore should not open when --plan-json is invalid")

    monkeypatch.setattr(cli, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--plan-json",
                str(tmp_path / "plan.json"),
            ]
        )
        == 2
    )
    assert _payload(capsys)["error"]["code"] == "argument_error"


def test_restore_from_snapshot_dry_run_writes_plan_json(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    plan_json = tmp_path / "plan.json"
    _write_snapshot(snapshot, enabled=True)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--dry-run",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--restore-output-state",
                "--plan-json",
                str(plan_json),
            ]
        )
        == 0
    )

    payload = _payload(capsys)
    saved = json.loads(plan_json.read_text(encoding="utf-8"))
    assert saved == payload["data"]
    assert saved["restore_output_state"] is True
    assert saved["resource"] == "USB0::FAKE::E36312A::INSTR"


def test_restore_from_snapshot_replays_output_on_only_when_requested(monkeypatch, tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot, enabled=True)
    session = FakeSession()
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--confirm",
                "--restore-output-state",
            ]
        )
        == 0
    )

    _payload(capsys)
    assert session.writes == [
        "OUTP OFF,(@1)",
        "VOLT:PROT 6,(@1)",
        "CURR:PROT:STAT ON,(@1)",
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "OUTP ON,(@1)",
    ]


def test_restore_from_snapshot_real_requires_confirm_before_open(monkeypatch, tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot)

    def fail_open(*args, **kwargs):
        raise AssertionError("restore should not open without --confirm")

    monkeypatch.setattr(cli, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    assert _payload(capsys)["error"]["code"] == "confirmation_required"


def test_restore_from_snapshot_real_rejects_serial_mismatch(monkeypatch, tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    _write_snapshot(snapshot)
    session = FakeSession(idn="KEYSIGHT,E36312A,OTHER,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--snapshot",
                str(snapshot),
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--confirm",
            ]
        )
        == 2
    )
    assert _payload(capsys)["error"]["code"] == "snapshot_identity_mismatch"
    assert session.writes == []


def test_edu_protection_simulate_is_plan_only(capsys):
    assert (
        cli.main(
            [
                "protection-set",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
            ]
        )
        == 0
    )
    payload = _payload(capsys)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["steps"][0]["command"] == "VOLT:PROT 5,(@1)"


def test_edu_clear_protection_simulate_is_plan_only(capsys):
    assert (
        cli.main(
            [
                "clear-protection",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--all",
            ]
        )
        == 0
    )
    payload = _payload(capsys)
    assert payload["execution"]["hardware_touched"] is False
    assert [step["command"] for step in payload["data"]["plan"]["steps"]] == [
        "OUTP:PROT:CLE (@1)",
        "OUTP:PROT:CLE (@2)",
        "OUTP:PROT:CLE (@3)",
    ]


def test_sequence_interrupt_attempts_safe_off_and_closes(monkeypatch, tmp_path, capsys):
    sequence = tmp_path / "sequence.yaml"
    sequence.write_text("version: 1\nsteps:\n  - action: wait\n    seconds: 1\n", encoding="utf-8")
    session = FakeSession()
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    def interrupting_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", interrupting_sleep)

    assert (
        cli.main(
            [
                "sequence",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--file",
                str(sequence),
            ]
        )
        == 0
    )

    payload = _payload(capsys)
    assert payload["data"]["status"] == "stopped"
    assert payload["data"]["failed_step"]["code"] == "interrupted"
    assert payload["data"]["cleanup"] == {"safe_off_attempted": True, "errors": []}
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.closed is True


def test_safety_inspect_explain_json(tmp_path, capsys):
    config = tmp_path / "safety.toml"
    config.write_text(
        """
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[models.E36312A]
max_voltage = 4.0

[[resources]]
alias = "bench"
resource = "USB0::FAKE::E36312A::INSTR"
confirm_above_voltage = 2.0
[resources.channels."1"]
max_current = 0.2
""".strip(),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "safety",
                "inspect",
                "--json",
                "--explain",
                "--safety-config",
                str(config),
                "--resource-alias",
                "bench",
                "--model",
                "E36312A",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    data = _payload(capsys)["data"]
    assert data["limits"]["max_voltage"] == 4.0
    assert data["limits"]["max_current"] == 0.2
    assert data["sources"] == {"global": "safety", "model": "E36312A", "resource": "bench", "channel": "1"}
    assert data["explanation"]["max_current"]["value"] == 0.2
    assert data["explanation"]["max_current"]["effective_source"] == "channel:1"
    assert data["explanation"]["max_voltage"]["effective_source"] == "model:E36312A"


def test_capabilities_selected_command_and_unknown_guard(monkeypatch, capsys):
    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--command",
                "protection-set",
            ]
        )
        == 0
    )
    payload = _payload(capsys)
    assert payload["data"]["selected_command"]["name"] == "protection-set"
    assert payload["data"]["selected_command"]["dry_run"] is True

    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
                "--command",
                "set",
            ]
        )
        == 0
    )
    payload = _payload(capsys)
    assert payload["data"]["selected_command"]["name"] == "set"
    assert payload["data"]["selected_command"]["real"] is True
    assert payload["data"]["selected_command"]["hardware_validation"] == "validated"

    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
                "--command",
                "trigger-pulse",
            ]
        )
        == 0
    )
    payload = _payload(capsys)
    assert payload["data"]["selected_command"]["name"] == "trigger-pulse"
    assert payload["data"]["selected_command"]["real"] is False
    assert payload["data"]["selected_command"]["hardware_validation"] == "not_enabled"

    def fail_open(*args, **kwargs):
        raise AssertionError("unknown command should be rejected before open")

    monkeypatch.setattr(cli, "open_resource", fail_open)
    assert (
        cli.main(
            [
                "capabilities",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--command",
                "unknown-command",
            ]
        )
        == 2
    )
    assert _payload(capsys)["error"]["code"] == "argument_error"


def test_sequence_lint_and_dry_run_preview(monkeypatch, tmp_path, capsys):
    sequence = tmp_path / "sequence.yaml"
    sequence.write_text(
        """
version: 1
steps:
  - action: log
    message: starting
  - action: set
    channel: 1
    voltage: 1.2
    current: 0.05
  - action: output-on
    channel: 1
  - action: wait
    seconds: 0
  - action: safe-off
    channel: all
""".strip(),
        encoding="utf-8",
    )

    def fail_open(*args, **kwargs):
        raise AssertionError("sequence --lint should not open VISA")

    monkeypatch.setattr(cli, "open_resource", fail_open)
    assert (
        cli.main(
            [
                "sequence",
                "--lint",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--file",
                str(sequence),
            ]
        )
        == 0
    )
    lint_payload = _payload(capsys)
    assert lint_payload["data"]["status"] == "valid"
    assert lint_payload["data"]["step_count"] == 5

    assert (
        cli.main(
            [
                "sequence",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--file",
                str(sequence),
            ]
        )
        == 0
    )
    steps = _payload(capsys)["data"]["plan"]["steps"]
    assert "preview" not in steps[0]
    assert steps[1]["preview"]["commands"] == ["CURR 0.05,(@1)", "VOLT 1.2,(@1)"]
    assert steps[2]["preview"]["commands"] == ["OUTP ON,(@1)"]
    assert "preview" not in steps[3]
    assert steps[4]["preview"]["commands"] == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]


def test_sequence_lint_invalid_returns_argument_error(tmp_path, capsys):
    sequence = tmp_path / "bad.yaml"
    sequence.write_text("version: 1\nsteps:\n  - action: unknown\n", encoding="utf-8")

    assert (
        cli.main(
            [
                "sequence",
                "--lint",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--file",
                str(sequence),
            ]
        )
        == 2
    )
    assert _payload(capsys)["error"]["code"] == "argument_error"


def test_snapshot_redact_resource_keeps_identity(capsys):
    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--json",
                "--redact-resource",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
            ]
        )
        == 0
    )
    data = _payload(capsys)["data"]
    assert data["resource"] == "<redacted>"
    assert data["resource_redacted"] is True
    assert data["idn"]["model"] == "E36312A"
    assert data["idn"]["serial"]


def test_doctor_json_environment(capsys):
    assert cli.main(["doctor", "--simulate", "--json"]) == 0
    environment = _payload(capsys)["data"]["environment"]
    assert environment["cwd"]
    assert set(environment["venv"]) == {"active", "prefix"}
    assert environment["platform"]["system"]
    assert environment["python"]["executable"]


def test_no_hardware_regression_script_keeps_output_out_of_local():
    script = Path("scripts/no-hardware-regression.ps1").read_text(encoding="utf-8")

    assert ".tmp_tests\\no_hardware_regression" in script
    assert "--basetemp" in script
    assert "report.json" in script
    assert "summary.md" in script
    assert "Local\\" not in script
    assert "Local/" not in script


def test_smoke_validation_scripts_use_instrument_read_status_command():
    preflight = Path("scripts/preflight-smoke-validation.ps1").read_text(encoding="utf-8")
    live = Path("scripts/live-smoke-validation-check.ps1").read_text(encoding="utf-8")

    assert 'Args = @("read-status", "--simulate"' in preflight
    assert '-Arguments @("read-status", "--json"' in live
    assert 'Args = @("protection-status", "--simulate"' in preflight
    assert '-Arguments @("protection-status", "--json"' in live
    for channel in ("1", "2", "3"):
        assert f'Name = "smoke-output-ch{channel}-dry-run"' in preflight
        assert f'Json = "smoke-output-ch{channel}.json"' in preflight
    assert "foreach ($channel in @(1, 2, 3))" in live
    assert '-Name ("smoke-output-ch" + $channel)' in live


def test_edu36311a_live_smoke_defaults_to_output_profile():
    preflight = Path("scripts/preflight-smoke-validation.ps1").read_text(encoding="utf-8")
    live = Path("scripts/live-smoke-validation-check.ps1").read_text(encoding="utf-8")

    assert '[string]$Profile = "auto"' in preflight
    assert '$isEduReadonly = $normalizedTarget -eq "EDU36311A" -and $normalizedProfile -eq "readonly"' in preflight
    assert '$isEduReadonly = $normalizedTarget -eq "EDU36311A" -and $normalizedProfile -eq "readonly"' in live
    assert '& $preflightScript -Target $Target -Profile $Profile' in live
    assert 'Invoke-LiveReadOnlyChecks -LogPrefix "output-smoke" -IncludeSequence:($normalizedTarget -eq "EDU36311A")' in live
    assert 'Name = "sequence-readonly-simulate"' in preflight
    assert 'Name = "apply-no-output-dry-run"' in preflight


def test_sequence_failure_cleanup_errors_do_not_replace_original_failure(monkeypatch, tmp_path, capsys):
    sequence = tmp_path / "sequence.yaml"
    sequence.write_text("version: 1\nsteps:\n  - action: measure\n    channel: 1\n", encoding="utf-8")
    session = CleanupFailingSession()
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "sequence",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--file",
                str(sequence),
            ]
        )
        == 0
    )

    payload = _payload(capsys)
    assert payload["data"]["status"] == "failed"
    assert payload["data"]["failed_step"]["action"] == "measure"
    assert payload["data"]["failed_step"]["code"] == "step_failed"
    assert payload["data"]["cleanup"]["safe_off_attempted"] is True
    assert [error["channel"] for error in payload["data"]["cleanup"]["errors"]] == [1, 2, 3]
    assert session.closed is True
