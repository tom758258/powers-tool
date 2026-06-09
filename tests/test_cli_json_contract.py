import json

import pytest

import keysight_power.cli as cli


SIM_RESOURCE = "USB0::SIM::E36103B::INSTR"
SIM_E36312A_RESOURCE = "USB0::SIM::E36312A::INSTR"
ENVELOPE_KEYS = {
    "schema_version",
    "ok",
    "status",
    "command",
    "execution",
    "request",
    "data",
    "warnings",
    "error",
    "metadata",
}


def parse_json_result(args: list[str], capsys) -> tuple[int, dict[str, object]]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


def assert_contract_envelope(payload: dict[str, object], *, command: str, ok: bool) -> None:
    assert set(payload) == ENVELOPE_KEYS
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is ok
    assert payload["status"] == ("ok" if ok else "error")
    assert payload["command"] == {"name": command}
    assert set(payload["execution"]) == {"mode", "dry_run", "hardware_touched"}
    assert isinstance(payload["request"], dict)
    assert payload["warnings"] == []
    assert payload["metadata"] == {}

    if ok:
        assert isinstance(payload["data"], dict)
        assert payload["error"] is None
    else:
        assert payload["data"] is None
        assert set(payload["error"]) == {"type", "code", "message", "retryable"}


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (
            "clear",
            [
                "clear",
                "--dry-run",
                "--json",
                "--resource",
                SIM_RESOURCE,
            ],
        ),
        (
            "error",
            [
                "error",
                "--simulate",
                "--json",
                "--resource",
                SIM_RESOURCE,
            ],
        ),
        (
            "measure",
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
            ],
        ),
        (
            "measure",
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "2",
            ],
        ),
        (
            "output-state",
            [
                "output-state",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "2",
            ],
        ),
        (
            "cycle-output",
            [
                "cycle-output",
                "--dry-run",
                "--json",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
                "--duration-ms",
                "250",
            ],
        ),
        (
            "apply",
            [
                "apply",
                "--dry-run",
                "--json",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ],
        ),
    ],
)
def test_safe_cli_json_commands_keep_contract(command, args, capsys) -> None:
    exit_code, payload = parse_json_result(args, capsys)

    assert exit_code == 0
    assert_contract_envelope(payload, command=command, ok=True)
    assert payload["execution"]["hardware_touched"] is False


def test_measure_simulate_json_keeps_stdout_parseable_with_scpi_logs(capsys) -> None:
    exit_code = cli.main(
        [
            "measure",
            "--simulate",
            "--json",
            "--log-scpi",
            "--resource",
            SIM_E36312A_RESOURCE,
            "--channel",
            "2",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert_contract_envelope(payload, command="measure", ok=True)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["measurements"] == {"voltage": 2.2, "current": 0.22}
    assert "SCPI >> *IDN?" in captured.err
    assert "SCPI >> MEAS:VOLT? (@2)" in captured.err


def test_output_state_simulate_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "output-state",
            "--simulate",
            "--json",
            "--resource",
            SIM_E36312A_RESOURCE,
            "--channel",
            "2",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="output-state", ok=True)
    assert payload["data"]["plan"]["operation"] == {"name": "output-state"}


def test_cycle_output_dry_run_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "cycle-output",
            "--dry-run",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "1",
            "--duration-ms",
            "250",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="cycle-output", ok=True)
    assert payload["data"]["plan"]["steps"][1]["action"] == "sleep"


def test_apply_dry_run_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "apply",
            "--dry-run",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "1",
            "--voltage",
            "1",
            "--current",
            "0.05",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="apply", ok=True)
    assert payload["data"]["plan"]["steps"][-1]["action"] == "output_on"


def test_output_dry_run_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "set",
            "--dry-run",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "1",
            "--voltage",
            "1",
            "--current",
            "0.05",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="set", ok=True)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["steps"][0]["action"] == "set_current_limit"
    assert payload["data"]["plan"]["steps"][1]["action"] == "set_voltage"


def test_validation_error_json_keeps_contract_and_does_not_touch_visa(
    monkeypatch,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    exit_code, payload = parse_json_result(
        [
            "measure",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "0",
        ],
        capsys,
    )

    assert exit_code == 2
    assert_contract_envelope(payload, command="measure", ok=False)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
