import json

import pytest

import keysight_power.connection as connection
import keysight_power.cli as cli
from keysight_power.errors import VisaConnectionError


OUTPUT_RESOURCE = "USB0::SIM::E36103B::INSTR"


class FakeSession:
    def __init__(
        self,
        idn: str = "KEYSIGHT,E36103B,MY00000000,1.0",
        *,
        query_responses: dict[str, list[str] | str] | None = None,
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

    def identify(self) -> str:
        return self.idn

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        response = self.query_responses.get(command)
        if isinstance(response, list):
            if response:
                return response.pop(0)
            return '0,"No error"'
        if response is not None:
            return response
        raise VisaConnectionError(f"No fake response for {command!r}")


def expected_idn(raw: str) -> dict[str, object]:
    manufacturer, model, serial, firmware = raw.split(",", maxsplit=3)
    return {
        "raw": raw,
        "manufacturer": manufacturer,
        "model": model,
        "serial": serial,
        "firmware": firmware,
        "parse_ok": True,
    }


def expected_resource(
    name: str,
    *,
    interface: str = "USB",
    simulated: bool = False,
    reachable: bool | None = None,
    idn: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "interface": interface,
        "simulated": simulated,
        "reachable": reachable,
        "idn": expected_idn(idn) if idn is not None else None,
    }


def test_list_resources_prints_backend_resources(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "list_resources",
        lambda *, backend=None: ("USB0::A::INSTR", "TCPIP0::B::INSTR"),
    )

    assert cli.main(["list-resources"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "USB0::A::INSTR\nTCPIP0::B::INSTR\n"
    assert captured.err == ""


def test_list_resources_prints_empty_message(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_resources", lambda *, backend=None: ())

    assert cli.main(["list-resources"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "No VISA resources found.\n"
    assert captured.err == ""


def test_list_resources_live_only_prints_openable_idn_resources(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "list_resources",
        lambda *, backend=None: ("USB0::LIVE::INSTR", "USB0::DEAD::INSTR"),
    )

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        if resource == "USB0::DEAD::INSTR":
            raise VisaConnectionError("not reachable")
        return FakeSession("KEYSIGHT,E36103B,MY00000000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["list-resources", "--live-only"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "USB0::LIVE::INSTR\n"
    assert captured.err == ""


def test_list_resources_live_only_can_log_scpi(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_resources", lambda *, backend=None: ("USB0::LIVE::INSTR",))
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,E36103B,MY00000000,1.0"
        ),
    )

    assert cli.main(["list-resources", "--live-only", "--log-scpi"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "USB0::LIVE::INSTR\n"
    assert "USB0::LIVE::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::LIVE::INSTR SCPI << KEYSIGHT,E36103B,MY00000000,1.0" in captured.err


def test_verify_prints_idn_response(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return FakeSession("KEYSIGHT,E36232A,MY00000001,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "verify",
                "--resource",
                "USB0::FAKE::INSTR",
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out == "KEYSIGHT,E36232A,MY00000001,1.0\n"
    assert captured.err == ""
    assert opened == [("USB0::FAKE::INSTR", "@py", 1234)]


def test_verify_returns_failure_when_resource_cannot_be_queried(monkeypatch, capsys) -> None:
    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        raise VisaConnectionError("not reachable")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "USB0::DEAD::INSTR"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Could not verify VISA resource: USB0::DEAD::INSTR" in captured.err


def test_list_resources_json_prints_machine_readable_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "list_resources",
        lambda resource_manager=None, *, backend=None: ("USB0::A::INSTR",),
    )

    assert cli.main(["list-resources", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": "1.0",
        "ok": True,
        "status": "ok",
        "command": {"name": "list-resources"},
        "execution": {
            "mode": "real",
            "dry_run": False,
            "hardware_touched": False,
        },
        "request": {
            "backend": None,
            "timeout_ms": 5000,
            "live_only": False,
        },
        "data": {
            "resources": [expected_resource("USB0::A::INSTR")],
            "count": 1,
        },
        "warnings": [],
        "error": None,
        "metadata": {},
    }
    assert captured.err == ""


def test_list_resources_json_failure_uses_stable_error_code(monkeypatch, capsys) -> None:
    def fail_list_resources(resource_manager=None, *, backend=None):
        raise VisaConnectionError("backend unavailable")

    monkeypatch.setattr(cli, "list_resources", fail_list_resources)

    assert cli.main(["list-resources", "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": "list-resources"}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "backend": None,
        "timeout_ms": 5000,
        "live_only": False,
    }
    assert payload["data"] is None
    assert payload["warnings"] == []
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "resource_list_failed"
    assert payload["error"]["retryable"] is True
    assert payload["metadata"] == {}
    assert captured.err == ""


def test_verify_json_prints_machine_readable_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, resource_manager=None, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,E36232A,MY00000001,1.0"
        ),
    )

    assert cli.main(["verify", "--resource", "USB0::FAKE::INSTR", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": "1.0",
        "ok": True,
        "status": "ok",
        "command": {"name": "verify"},
        "execution": {
            "mode": "real",
            "dry_run": False,
            "hardware_touched": True,
        },
        "request": {
            "resource": "USB0::FAKE::INSTR",
            "backend": None,
            "timeout_ms": 5000,
        },
        "data": {
            "resource": expected_resource(
                "USB0::FAKE::INSTR",
                reachable=True,
                idn="KEYSIGHT,E36232A,MY00000001,1.0",
            ),
        },
        "warnings": [],
        "error": None,
        "metadata": {},
    }
    assert captured.err == ""


def test_verify_json_failure_prints_error_payload(monkeypatch, capsys) -> None:
    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000):
        raise VisaConnectionError("not reachable")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "USB0::DEAD::INSTR", "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": "verify"}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["request"] == {
        "resource": "USB0::DEAD::INSTR",
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"] is None
    assert payload["warnings"] == []
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "resource_unreachable"
    assert payload["error"]["retryable"] is True
    assert "USB0::DEAD::INSTR" in payload["error"]["message"]
    assert payload["metadata"] == {}
    assert captured.err == ""


def test_verify_json_missing_resource_returns_validation_payload(capsys) -> None:
    assert cli.main(["verify", "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": "1.0",
        "ok": False,
        "status": "error",
        "command": {"name": "verify"},
        "execution": {
            "mode": "real",
            "dry_run": False,
            "hardware_touched": False,
        },
        "request": {
            "resource": None,
            "backend": None,
            "timeout_ms": 5000,
        },
        "data": None,
        "warnings": [],
        "error": {
            "type": "validation",
            "code": "argument_error",
            "message": "the following arguments are required: --resource",
            "retryable": False,
        },
        "metadata": {},
    }
    assert captured.err == ""


def test_list_resources_simulate_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main(["list-resources", "--simulate"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "USB0::SIM::E36103B::INSTR\n"
        "TCPIP0::SIM::E36232A::INSTR\n"
        "USB0::SIM::E36312A::INSTR\n"
        "USB0::SIM::EDU36311A::INSTR\n"
    )
    assert captured.err == ""


def test_list_resources_simulate_live_only_json_logs_scpi_to_stderr(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main(["list-resources", "--simulate", "--live-only", "--json", "--log-scpi"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["command"] == {"name": "list-resources"}
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "backend": None,
        "timeout_ms": 5000,
        "live_only": True,
    }
    assert payload["data"]["resources"] == [
        expected_resource(
            "USB0::SIM::E36103B::INSTR",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,E36103B,SIM000001,1.0",
        ),
        expected_resource(
            "TCPIP0::SIM::E36232A::INSTR",
            interface="TCPIP",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,E36232A,SIM000002,1.0",
        ),
        expected_resource(
            "USB0::SIM::E36312A::INSTR",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,E36312A,SIM000003,1.0",
        ),
        expected_resource(
            "USB0::SIM::EDU36311A::INSTR",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,EDU36311A,SIM000004,1.0",
        ),
    ]
    assert payload["data"]["count"] == 4
    assert payload["warnings"] == []
    assert payload["error"] is None
    assert payload["metadata"] == {}
    assert "SCPI >> *IDN?" in captured.err
    assert "KEYSIGHT,E36103B,SIM000001,1.0" in captured.err
    assert "KEYSIGHT,E36312A,SIM000003,1.0" in captured.err


def test_verify_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "verify",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36103B::INSTR",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "1.0"
    assert payload["command"] == {"name": "verify"}
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": "USB0::SIM::E36103B::INSTR",
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"] == {
        "resource": expected_resource(
            "USB0::SIM::E36103B::INSTR",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,E36103B,SIM000001,1.0",
        ),
    }
    assert captured.err == ""


def test_clear_dry_run_json_does_not_open_visa(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "clear",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "*CLS"}
    ]
    assert captured.err == ""


def test_clear_real_json_writes_only_cls(monkeypatch, capsys) -> None:
    session = FakeSession()
    opened = []

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000):
        opened.append((resource, resource_manager, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "clear",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert opened == [(OUTPUT_RESOURCE, None, "@py", 1234)]
    assert session.writes == ["*CLS"]
    assert session.queries == []
    assert session.closed is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["data"]["cleared"] is True
    assert payload["data"]["resource"] == expected_resource(OUTPUT_RESOURCE, reachable=True)
    assert captured.err == ""


def test_error_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "error",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36103B::INSTR",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": "USB0::SIM::E36103B::INSTR",
        "backend": None,
        "timeout_ms": 5000,
        "max_reads": 20,
    }
    assert payload["data"]["errors"] == []
    assert payload["data"]["read_count"] == 1
    assert captured.err == ""


def test_error_real_json_reads_until_no_error(monkeypatch, capsys) -> None:
    session = FakeSession(
        query_responses={
            "SYST:ERR?": ['-100,"Command error"', '0,"No error"'],
        }
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(["error", "--json", "--resource", OUTPUT_RESOURCE, "--max-reads", "5"])
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == ["SYST:ERR?", "SYST:ERR?"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["errors"] == ['-100,"Command error"']
    assert payload["data"]["read_count"] == 2
    assert payload["data"]["max_reads"] == 5
    assert captured.err == ""


def test_measure_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36103B::INSTR",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": "USB0::SIM::E36103B::INSTR",
        "channel": 1,
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"]["channel"] == 1
    assert payload["data"]["measurements"] == {"voltage": 1.0, "current": 0.05}
    assert captured.err == ""


@pytest.mark.parametrize(
    ("resource", "channel", "expected_measurements"),
    [
        (
            "USB0::SIM::E36312A::INSTR",
            "1",
            {"voltage": 1.1, "current": 0.11},
        ),
        (
            "USB0::SIM::E36312A::INSTR",
            "2",
            {"voltage": 2.2, "current": 0.22},
        ),
        (
            "USB0::SIM::E36312A::INSTR",
            "3",
            {"voltage": 3.3, "current": 0.33},
        ),
        (
            "USB0::SIM::EDU36311A::INSTR",
            "1",
            {"voltage": 1.01, "current": 0.101},
        ),
        (
            "USB0::SIM::EDU36311A::INSTR",
            "2",
            {"voltage": 2.02, "current": 0.202},
        ),
        (
            "USB0::SIM::EDU36311A::INSTR",
            "3",
            {"voltage": 3.03, "current": 0.303},
        ),
    ],
)
def test_measure_simulate_uses_model_driver_for_first_target_channels(
    monkeypatch,
    capsys,
    resource,
    channel,
    expected_measurements,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                resource,
                "--channel",
                channel,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"]["resource"] == resource
    assert payload["request"]["channel"] == int(channel)
    assert payload["data"]["channel"] == int(channel)
    assert payload["data"]["measurements"] == expected_measurements
    assert captured.err == ""


def test_measure_simulate_model_driver_logs_channel_list_scpi_to_stderr(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--log-scpi",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["data"]["measurements"] == {"voltage": 2.2, "current": 0.22}
    assert "USB0::SIM::E36312A::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::SIM::E36312A::INSTR SCPI >> MEAS:VOLT? (@2)" in captured.err
    assert "USB0::SIM::E36312A::INSTR SCPI >> MEAS:CURR? (@2)" in captured.err


def test_measure_simulate_generic_channel_two_is_rejected_without_real_visa(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36103B::INSTR",
                "--channel",
                "2",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "GenericScpiPowerSupply" in payload["error"]["message"]
    assert "channel 1 only" in payload["error"]["message"]
    assert captured.err == ""


def test_measure_real_json_queries_voltage_then_current(monkeypatch, capsys) -> None:
    session = FakeSession(
        query_responses={
            "MEAS:VOLT?": "1.234",
            "MEAS:CURR?": "0.056",
        }
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(["measure", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"])
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == ["MEAS:VOLT?", "MEAS:CURR?"]
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["measurements"] == {"voltage": 1.234, "current": 0.056}
    assert captured.err == ""


@pytest.mark.parametrize("channel", ["2", "3"])
def test_measure_real_e36312a_channel_two_and_three_use_channel_list_queries(
    monkeypatch,
    capsys,
    channel,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            f"MEAS:VOLT? (@{channel})": "1.234",
            f"MEAS:CURR? (@{channel})": "0.056",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                channel,
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == [
        "*IDN?",
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    ]
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["channel"] == int(channel)
    assert payload["data"]["measurements"] == {"voltage": 1.234, "current": 0.056}
    assert "USB0::FAKE::E36312A::INSTR SCPI >> *IDN?" in captured.err
    assert f"USB0::FAKE::E36312A::INSTR SCPI >> MEAS:VOLT? (@{channel})" in captured.err
    assert f"USB0::FAKE::E36312A::INSTR SCPI >> MEAS:CURR? (@{channel})" in captured.err


def test_measure_real_generic_channel_two_is_rejected_after_idn(
    monkeypatch,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,MY00000000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(["measure", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "2"])
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == ["*IDN?"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 1 only" in payload["error"]["message"]
    assert captured.err == ""


@pytest.mark.parametrize(
    ("args", "expected_code"),
    [
        (["clear", "--json", "--resource", OUTPUT_RESOURCE], "status_clear_failed"),
        (["error", "--json", "--resource", OUTPUT_RESOURCE], "error_query_failed"),
        (
            ["measure", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"],
            "measurement_failed",
        ),
    ],
)
def test_safe_io_connection_failures_use_stable_error_codes(
    monkeypatch,
    capsys,
    args,
    expected_code,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("not reachable")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main(args) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["retryable"] is True
    assert captured.err == ""


def output_command_args(command: str, *, channel: str = "1") -> list[str]:
    args = [command, "--resource", OUTPUT_RESOURCE, "--channel", channel]
    if command == "set":
        args.extend(["--voltage", "1", "--current", "0.05"])
    return args


def write_safety_config(tmp_path, content: str | None = None) -> str:
    config_path = tmp_path / "keysight-power.toml"
    config_path.write_text(
        content
        or """
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]
""".strip(),
        encoding="utf-8",
    )
    return str(config_path)


@pytest.mark.parametrize(
    ("args", "expected_actions"),
    [
        (output_command_args("set"), ["set_current_limit", "set_voltage"]),
        (output_command_args("output-on"), ["output_on"]),
        (output_command_args("output-off"), ["output_off"]),
        (output_command_args("safe-off"), ["safe_off"]),
    ],
)
def test_output_commands_dry_run_json_emit_logical_plans(
    args,
    expected_actions,
    capsys,
) -> None:
    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["request"]["safety_config"] is None
    assert payload["request"]["resource_alias"] is None
    assert payload["data"]["plan"]["operation"] == {"name": args[0]}
    assert payload["data"]["plan"]["target"] == {
        "resource": OUTPUT_RESOURCE,
        "channel": 1,
    }
    assert payload["data"]["plan"]["hardware_touched"] is False
    steps = payload["data"]["plan"]["steps"]
    assert [step["action"] for step in steps] == expected_actions
    assert all(step["type"] == "driver_action" for step in steps)
    assert all("command" not in step for step in steps)
    assert captured.err == ""


def test_set_dry_run_json_applies_explicit_safety_config(tmp_path, capsys) -> None:
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "channel": 1,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
    }
    assert payload["data"]["plan"]["steps"][0]["action"] == "set_current_limit"
    assert payload["data"]["plan"]["steps"][1]["action"] == "set_voltage"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "5.1",
                "--current",
                "0.05",
            ],
            "voltage 5.1 exceeds maximum 5",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.6",
            ],
            "current 0.6 exceeds maximum 0.5",
        ),
    ],
)
def test_set_safety_config_limit_failures_use_json_validation_errors(
    tmp_path,
    args,
    expected_message,
    capsys,
) -> None:
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*args, "--dry-run", "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is False
    assert payload["request"]["safety_config"] == safety_config
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["retryable"] is False
    assert expected_message in payload["error"]["message"]
    assert captured.err == ""


@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set", channel="2"),
        output_command_args("output-on", channel="2"),
        output_command_args("output-off", channel="2"),
    ],
)
def test_safety_config_rejects_disallowed_integer_channels(
    tmp_path,
    args,
    capsys,
) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert cli.main([*args, "--dry-run", "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_safe_off_all_with_safety_config_is_allowed(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "safe-off",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "channel": "all",
        "safety_config": safety_config,
    }
    assert payload["data"]["plan"]["target"]["channel"] == "all"
    assert payload["data"]["plan"]["steps"][0]["parameters"]["channel"] == "all"
    assert captured.err == ""


def test_output_plan_resource_alias_resolves_effective_resource_and_limits(
    tmp_path,
    capsys,
) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36103b"
resource = "{OUTPUT_RESOURCE}"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36103b",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "sim-e36103b",
        "channel": 1,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
    }
    assert payload["data"]["plan"]["target"]["resource"] == OUTPUT_RESOURCE
    assert captured.err == ""


def test_raw_resource_match_applies_resource_specific_limits(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36103b"
resource = "{OUTPUT_RESOURCE}"
max_voltage = 0.5
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] is None
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "voltage 1 exceeds maximum 0.5" in payload["error"]["message"]
    assert captured.err == ""


def test_resource_alias_requires_explicit_safety_config(capsys) -> None:
    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36103b",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] is None
    assert payload["request"]["resource_alias"] == "sim-e36103b"
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "resource alias requires --safety-config" in payload["error"]["message"]
    assert captured.err == ""


def test_unknown_resource_alias_uses_json_validation_error(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36103b"
resource = "{OUTPUT_RESOURCE}"
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "missing",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] is None
    assert payload["request"]["resource_alias"] == "missing"
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "unknown resource alias: missing" in payload["error"]["message"]
    assert captured.err == ""


def test_real_output_with_alias_without_dry_run_is_rejected_before_visa(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1]

[[resources]]
alias = "sim-e36103b"
resource = "{OUTPUT_RESOURCE}"
max_current = 0.1
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36103b",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] == "sim-e36103b"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "real_execution_disabled"
    assert captured.err == ""


def test_simulate_output_with_safety_config_does_not_create_real_resource_manager(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--simulate",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"]["safety_config"] == safety_config
    assert captured.err == ""


def test_real_output_with_safety_config_without_dry_run_is_rejected_before_visa(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*output_command_args("set"), "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"]["safety_config"] == safety_config
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "real_execution_disabled"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("config_content", "args", "expected_message"),
    [
        (
            "[safety]\nunknown = 1\n",
            [*output_command_args("set"), "--dry-run"],
            "unsupported [safety] key: unknown",
        ),
        (
            "[safety]\nmax_voltage = 0.5\n",
            [*output_command_args("set"), "--dry-run"],
            "voltage 1 exceeds maximum 0.5",
        ),
    ],
)
def test_safety_config_text_errors_go_to_stderr(
    tmp_path,
    config_content,
    args,
    expected_message,
    capsys,
) -> None:
    safety_config = write_safety_config(tmp_path, config_content)

    assert cli.main([*args, "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert expected_message in captured.err


def test_missing_safety_config_path_uses_json_validation_error(capsys) -> None:
    missing_path = "does-not-exist.toml"

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--dry-run",
                "--json",
                "--safety-config",
                missing_path,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["safety_config"] == missing_path
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "safety config not found" in payload["error"]["message"]
    assert captured.err == ""


@pytest.mark.parametrize(
    ("args", "expected_lines"),
    [
        (
            output_command_args("set"),
            [
                "Dry-run plan for set",
                "1. set_current_limit channel=1 current=0.05",
                "2. set_voltage channel=1 voltage=1",
            ],
        ),
        (
            output_command_args("output-on"),
            ["Dry-run plan for output-on", "1. output_on channel=1"],
        ),
        (
            output_command_args("output-off"),
            ["Dry-run plan for output-off", "1. output_off channel=1"],
        ),
        (
            output_command_args("safe-off"),
            ["Dry-run plan for safe-off", "1. safe_off channel=1"],
        ),
    ],
)
def test_output_commands_text_dry_run_output(args, expected_lines, capsys) -> None:
    assert cli.main([*args, "--dry-run"]) == 0

    captured = capsys.readouterr()
    for line in expected_lines:
        assert line in captured.out
    assert f"Resource: {OUTPUT_RESOURCE}" in captured.out
    assert "Hardware touched: false" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set"),
        output_command_args("output-on"),
        output_command_args("safe-off"),
    ],
)
def test_real_output_commands_without_dry_run_are_rejected_before_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    """set, output-on, and safe-off real mode are still disabled."""
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*args, "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["command"] == {"name": args[0]}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "real_execution_disabled"
    assert payload["error"]["retryable"] is False
    assert payload["data"] is None
    assert captured.err == ""


@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set"),
        output_command_args("output-on"),
        output_command_args("output-off"),
        output_command_args("safe-off"),
    ],
)
def test_output_commands_simulate_without_dry_run_succeed_without_real_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main([*args, "--simulate", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["operation"] == {"name": args[0]}
    assert payload["data"]["plan"]["hardware_touched"] is False
    assert captured.err == ""


def test_set_plan_orders_current_limit_before_voltage(capsys) -> None:
    assert cli.main([*output_command_args("set"), "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    steps = json.loads(captured.out)["data"]["plan"]["steps"]
    assert steps == [
        {
            "index": 1,
            "type": "driver_action",
            "action": "set_current_limit",
            "parameters": {"channel": 1, "current": 0.05},
        },
        {
            "index": 2,
            "type": "driver_action",
            "action": "set_voltage",
            "parameters": {"channel": 1, "voltage": 1.0},
        },
    ]


def test_channel_two_plan_is_logical_and_not_scpi(capsys) -> None:
    args = output_command_args("set", channel="2")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    plan = payload["data"]["plan"]
    assert plan["target"]["channel"] == 2
    assert all(step["parameters"]["channel"] == 2 for step in plan["steps"])
    assert all("command" not in step for step in plan["steps"])
    assert "SCPI" not in captured.out


def test_safe_off_all_allowed_but_other_output_commands_reject_all(capsys) -> None:
    assert (
        cli.main(
            [
                "safe-off",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["data"]["plan"]["target"]["channel"] == "all"
    assert payload["data"]["plan"]["steps"] == [
        {
            "index": 1,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": "all"},
        }
    ]

    for command in ("set", "output-on", "output-off"):
        assert cli.main([*output_command_args(command, channel="all"), "--dry-run", "--json"]) == 2
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["error"]["type"] == "validation"
        assert payload["error"]["code"] == "argument_error"
        assert payload["execution"]["hardware_touched"] is False


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "-0.1",
                "--current",
                "0.05",
            ],
            "voltage must be non-negative",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "nan",
                "--current",
                "0.05",
            ],
            "voltage must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "inf",
                "--current",
                "0.05",
            ],
            "voltage must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "-0.05",
            ],
            "current must be non-negative",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "nan",
            ],
            "current must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "inf",
            ],
            "current must be finite",
        ),
        (
            [
                "output-on",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "0",
            ],
            "channel must be a positive integer",
        ),
    ],
)
def test_output_command_invalid_values_use_stable_json_validation_errors(
    args,
    expected_message,
    capsys,
) -> None:
    assert cli.main([*args, "--dry-run", "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"] is None
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["retryable"] is False
    assert expected_message in payload["error"]["message"]
    assert captured.err == ""

import json

import pytest

import keysight_power.cli as cli
import keysight_power.connection as connection

# --- E36312A real output-off (uses hardcoded resource) ---

@pytest.mark.parametrize("channel", [1, 2, 3])
def test_output_off_real_e36312a_sends_correct_scpi(monkeypatch, capsys, channel) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [f"OUTP OFF,(@{channel})"]
    assert session.queries == ["*IDN?"]
    assert session.closed is True
    assert payload["execution"]["mode"] == "real"
    assert payload["execution"]["dry_run"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["channel"] == channel
    assert payload["data"]["output"]["enabled"] is False
    assert payload["data"]["resource"]["name"] == OUTPUT_RESOURCE
    assert payload["data"]["resource"]["idn"]["model"] == "E36312A"
    assert captured.err == ""


def test_output_off_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"]["output"]["enabled"] is False
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP OFF,(@1)" in captured.err
    json.loads(captured.out)  # must not raise - stdout is valid JSON


def test_output_off_real_generic_e36312a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,MY00000000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "unsupported_model_for_output_off"
    assert "E36312A" in payload["error"]["message"]
    assert session.closed is True


def test_output_off_real_unknown_model_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="UNKNOWN,MODEL,SN,FW")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unsupported_model_for_output_off"


def test_output_off_real_unsupported_channel_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "99",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    # session is closed by context manager after error


# --- Preserved behaviors: dry-run and simulate ---


def test_output_off_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "output-off",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload["data"]
    assert payload["data"]["plan"]["operation"]["name"] == "output-off"
    assert payload["execution"]["hardware_touched"] is False


def test_output_off_simulate_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for simulate")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "output-off",
                "--simulate",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload["data"]


# --- Other output commands remain disabled ---


@pytest.mark.parametrize("command,extra_args", [
    ("set",      ["--voltage", "1", "--current", "0.05"]),
    ("output-on", []),
    ("safe-off", []),
])
def test_other_output_commands_real_remain_disabled(monkeypatch, capsys, command, extra_args) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    args = [command, "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"] + extra_args
    assert cli.main(args) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "real_execution_disabled"

