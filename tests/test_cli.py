import json
import csv

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
        self.events: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def identify(self) -> str:
        return self.idn

    def write(self, command: str) -> None:
        self.writes.append(command)
        self.events.append(f"write:{command}")

    def query(self, command: str) -> str:
        self.queries.append(command)
        self.events.append(f"query:{command}")
        if command == "*IDN?":
            return self.idn
        if command == "SYST:ERR?":
            response = self.query_responses.get(command)
            if isinstance(response, list):
                if response:
                    return response.pop(0)
                return '0,"No error"'
            if response is not None:
                return response
            return '0,"No error"'
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


@pytest.mark.parametrize("channel", ["2", "3"])
def test_measure_real_edu36311a_channel_two_and_three_use_channel_list_queries(
    monkeypatch,
    capsys,
    channel,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,MY00000001,1.0",
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
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                channel,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    ]
    assert payload["data"]["measurements"] == {"voltage": 1.234, "current": 0.056}


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


def test_safe_off_real_all_reads_back_each_channel(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "OUTP? (@1)": "0",
            "OUTP? (@2)": "1",
            "OUTP? (@3)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "all",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.queries == ["*IDN?", "OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]
    assert session.events == [
        "query:*IDN?",
        "write:OUTP OFF,(@1)",
        "query:OUTP? (@1)",
        "write:OUTP OFF,(@2)",
        "query:OUTP? (@2)",
        "write:OUTP OFF,(@3)",
        "query:OUTP? (@3)",
        "query:SYST:ERR?",
    ]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": False},
    ]


def test_smoke_output_real_sends_safe_scpi_order_and_reads_final_state(
    monkeypatch,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "MEAS:VOLT? (@1)": "1.001",
            "MEAS:CURR? (@1)": "0.051",
            "OUTP? (@1)": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "smoke-output",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "OUTP ON,(@1)",
        "OUTP OFF,(@1)",
    ]
    assert session.queries == [
        "*IDN?",
        "MEAS:VOLT? (@1)",
        "MEAS:CURR? (@1)",
        "OUTP? (@1)",
        "SYST:ERR?",
    ]
    assert session.events == [
        "query:*IDN?",
        "write:CURR 0.05,(@1)",
        "write:VOLT 1,(@1)",
        "write:OUTP ON,(@1)",
        "query:MEAS:VOLT? (@1)",
        "query:MEAS:CURR? (@1)",
        "write:OUTP OFF,(@1)",
        "query:OUTP? (@1)",
        "query:SYST:ERR?",
    ]
    assert payload["data"]["setpoints"] == {"current": 0.05, "voltage": 1.0}
    assert payload["data"]["measurements"] == {"voltage": 1.001, "current": 0.051}
    assert payload["data"]["output"]["final_enabled"] is False
    assert payload["data"]["safe_off_attempted"] is True


def test_smoke_output_real_attempts_output_off_after_measurement_failure(
    monkeypatch,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"MEAS:VOLT? (@1)": "not-a-number"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "smoke-output",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "OUTP ON,(@1)",
        "OUTP OFF,(@1)",
    ]
    assert session.queries == ["*IDN?", "MEAS:VOLT? (@1)"]
    assert session.events == [
        "query:*IDN?",
        "write:CURR 0.05,(@1)",
        "write:VOLT 1,(@1)",
        "write:OUTP ON,(@1)",
        "query:MEAS:VOLT? (@1)",
        "write:OUTP OFF,(@1)",
    ]
    assert payload["error"]["code"] == "smoke_output_failed"


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


def output_command_args(
    command: str,
    *,
    channel: str = "1",
    voltage: str = "1",
    current: str = "0.05",
    duration_ms: str = "500",
) -> list[str]:
    args = [command, "--resource", OUTPUT_RESOURCE, "--channel", channel]
    if command in {"set", "apply"}:
        args.extend(["--voltage", voltage, "--current", current])
    if command == "cycle-output":
        args.extend(["--duration-ms", duration_ms])
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
        (output_command_args("output-state"), ["output_state"]),
        (
            output_command_args("cycle-output", duration_ms="250"),
            ["output_on", "sleep", "output_off"],
        ),
        (output_command_args("apply"), ["set_current_limit", "set_voltage", "output_on"]),
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


def test_cycle_output_dry_run_json_includes_duration(capsys) -> None:
    args = output_command_args("cycle-output", duration_ms="250")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["duration_ms"] == 250
    assert payload["data"]["plan"]["steps"][1] == {
        "index": 2,
        "type": "driver_action",
        "action": "sleep",
        "parameters": {"duration_ms": 250},
    }


def test_apply_dry_run_json_includes_setpoints_and_output_on(capsys) -> None:
    args = output_command_args("apply", voltage="1", current="0.05")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["voltage"] == 1.0
    assert payload["request"]["current"] == 0.05
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
    ]


def test_apply_all_no_output_dry_run_sets_each_channel_without_output(capsys) -> None:
    assert (
        cli.main(
            [
                "apply",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    steps = payload["data"]["plan"]["steps"]
    assert [(step["action"], step["parameters"]["channel"]) for step in steps] == [
        ("set_current_limit", 1),
        ("set_voltage", 1),
        ("set_current_limit", 2),
        ("set_voltage", 2),
        ("set_current_limit", 3),
        ("set_voltage", 3),
    ]
    assert all(step["action"] != "output_on" for step in steps)


def test_smoke_output_dry_run_json_emits_guarded_plan(capsys) -> None:
    assert (
        cli.main(
            [
                "smoke-output",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
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
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
        "sleep",
        "measure_voltage",
        "measure_current",
        "output_off",
        "output_state",
    ]


def test_smoke_output_simulate_json_does_not_create_real_resource_manager(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "smoke-output",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["mode"] == "simulate"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["operation"] == {"name": "smoke-output"}


def test_save_json_writes_same_envelope_as_stdout(tmp_path, capsys) -> None:
    save_path = tmp_path / "nested" / "snapshot.json"

    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--save-json",
                str(save_path),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    stdout_payload = json.loads(captured.out)
    saved_payload = json.loads(save_path.read_text(encoding="utf-8"))
    assert saved_payload == stdout_payload


def test_save_json_without_json_returns_argument_error(capsys, tmp_path) -> None:
    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--save-json",
                str(tmp_path / "snapshot.json"),
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "--save-json requires --json" in payload["error"]["message"]


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
        "backend": None,
        "timeout_ms": 5000,
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
        "backend": None,
        "timeout_ms": 5000,
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


def test_real_set_with_alias_without_dry_run_executes_after_validation(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
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
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] == "sim-e36103b"
    assert payload["execution"]["hardware_touched"] is True
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
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


def test_real_set_with_safety_config_without_dry_run_executes(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*output_command_args("set"), "--json", "--safety-config", safety_config]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["request"]["safety_config"] == safety_config
    assert payload["data"]["setpoints"] == {"current": 0.05, "voltage": 1.0}
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
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
        output_command_args("safe-off"),
    ],
)
def test_real_output_commands_without_dry_run_are_rejected_before_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == {"name": args[0]}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["target"]["channel"] == 1
    assert captured.err == ""


@pytest.mark.parametrize("channel", ["1", "2", "3"])
def test_output_state_real_e36312a_reads_channel_state(monkeypatch, capsys, channel) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={f"OUTP? (@{channel})": "ON"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                channel,
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", f"OUTP? (@{channel})"]
    assert session.writes == []
    assert payload["data"]["output"] == {"enabled": True}
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP? (@{channel})" in captured.err


def test_safe_off_real_e36312a_expands_all_channels(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "OUTP? (@1)": "0",
            "OUTP? (@2)": "0",
            "OUTP? (@3)": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.events == [
        "query:*IDN?",
        "write:OUTP OFF,(@1)",
        "query:OUTP? (@1)",
        "write:OUTP OFF,(@2)",
        "query:OUTP? (@2)",
        "write:OUTP OFF,(@3)",
        "query:OUTP? (@3)",
        "query:SYST:ERR?",
    ]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]
    assert captured.err == ""


def test_cycle_output_real_e36312a_cycles_output_without_delay(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "cycle-output",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--duration-ms",
                "250",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["OUTP ON,(@2)", "OUTP OFF,(@2)"]
    assert payload["data"]["duration_ms"] == 250
    assert payload["data"]["output"] == {"cycled": True, "final_enabled": False}
    assert captured.err == ""


def test_apply_real_e36312a_sets_then_enables_output(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "3",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["CURR 0.05,(@3)", "VOLT 1,(@3)", "OUTP ON,(@3)"]
    assert payload["data"]["output"] == {"enabled": True}
    assert captured.err == ""


def test_apply_real_e36312a_all_channels_sets_then_enables_each(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
        "OUTP ON,(@1)",
        "OUTP ON,(@2)",
        "OUTP ON,(@3)",
    ]
    assert payload["data"]["channel"] == "all"
    assert payload["data"]["output"] == {"enabled": True}
    assert payload["data"]["channels"] == [
        {"channel": 1, "setpoints": {"current": 0.05, "voltage": 1.0}},
        {"channel": 2, "setpoints": {"current": 0.05, "voltage": 1.0}},
        {"channel": 3, "setpoints": {"current": 0.05, "voltage": 1.0}},
    ]


def test_apply_real_e36312a_no_output_skips_output_on(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
    ]
    assert payload["request"]["no_output"] is True
    assert payload["data"]["output"] == {"enabled": False}


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


# --- E36312A real set (uses hardcoded resource) ---


@pytest.mark.parametrize(
    ("channel", "expected_writes"),
    [
        (1, ["CURR 0.05,(@1)", "VOLT 1,(@1)"]),
        (2, ["CURR 0.05,(@2)", "VOLT 1,(@2)"]),
        (3, ["CURR 0.05,(@3)", "VOLT 1,(@3)"]),
    ],
)
def test_set_real_e36312a_sends_current_before_voltage(
    monkeypatch,
    capsys,
    channel,
    expected_writes,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == expected_writes
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["data"] == {
        "resource": expected_resource(
            OUTPUT_RESOURCE,
            reachable=True,
            idn="KEYSIGHT,E36312A,MY00000001,1.0",
        ),
        "channel": channel,
        "setpoints": {"current": 0.05, "voltage": 1.0},
    }
    assert captured.err == ""


def test_set_real_text_output_is_minimal_without_output_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(output_command_args("set")) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        f"Resource: {OUTPUT_RESOURCE}\n"
        "Channel: 1\n"
        "Current limit: 0.05 A\n"
        "Voltage: 1 V\n"
    )
    assert "Output enabled" not in captured.out
    assert captured.err == ""


def test_set_real_resource_alias_backend_timeout_resolves_once(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]
max_voltage = 5.0
max_current = 0.5

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--safety-config",
                safety_config,
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
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["CURR 0.05,(@2)", "VOLT 1,(@2)"]
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "channel": 2,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""


def test_set_real_safety_config_rejects_before_open(monkeypatch, tmp_path, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
max_voltage = 5.0
max_current = 0.5
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_set_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> CURR 0.05,(@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT 1,(@1)" in captured.err
    json.loads(captured.out)


@pytest.mark.parametrize("idn", ["KEYSIGHT,E36103B,MY00000000,1.0", "UNKNOWN,MODEL,SN,FW"])
def test_set_real_non_e36312a_models_are_rejected(monkeypatch, capsys, idn) -> None:
    session = FakeSession(idn=idn)
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "unsupported_model_for_set"
    assert "E36312A" in payload["error"]["message"]
    assert session.closed is True


def test_set_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set", channel="99"), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 99 is not supported for set" in payload["error"]["message"]


def test_set_real_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "connection_failed"


def test_set_real_write_failure_uses_set_failed(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == ["CURR 0.05,(@1)"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "set_failed"


def test_set_real_instrument_error_queue_fails_command(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"SYST:ERR?": ['-222,"Data out of range"', '0,"No error"']},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert session.queries == ["*IDN?", "SYST:ERR?", "SYST:ERR?"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "set_failed"
    assert '-222,"Data out of range"' in payload["error"]["message"]


# --- E36312A real output-on (uses hardcoded resource) ---

@pytest.mark.parametrize("channel", [1, 2, 3])
def test_output_on_real_e36312a_sends_correct_scpi(monkeypatch, capsys, channel) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            f"VOLT? (@{channel})": "1.0",
            f"CURR? (@{channel})": "0.05",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
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
    assert session.writes == [f"OUTP ON,(@{channel})"]
    assert session.queries == ["*IDN?", f"VOLT? (@{channel})", f"CURR? (@{channel})", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["data"] == {
        "resource": expected_resource(
            OUTPUT_RESOURCE,
            reachable=True,
            idn="KEYSIGHT,E36312A,MY00000001,1.0",
        ),
        "channel": channel,
        "output": {"enabled": True},
        "readback": {
            "setpoints": {"voltage": 1.0, "current": 0.05},
            "safety_checked": False,
        },
    }
    assert captured.err == ""


def test_output_on_real_text_output_reports_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("output-on"), "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        f"Resource: {OUTPUT_RESOURCE}\n"
        "Channel: 2\n"
        "Output enabled: True\n"
    )
    assert session.writes == ["OUTP ON,(@2)"]
    assert captured.err == ""


def test_output_on_real_resource_alias_backend_timeout_resolves_once(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.05"},
    )
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--safety-config",
                safety_config,
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
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert session.queries == ["*IDN?", "VOLT? (@2)", "CURR? (@2)", "SYST:ERR?"]
    assert session.writes == ["OUTP ON,(@2)"]
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "channel": 2,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""


def test_output_on_real_safety_config_rejects_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
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
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_output_on_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
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
    assert payload["data"]["output"]["enabled"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT? (@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> CURR? (@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP ON,(@1)" in captured.err
    json.loads(captured.out)  # must not raise - stdout is valid JSON


@pytest.mark.parametrize("idn", ["KEYSIGHT,E36103B,MY00000000,1.0", "UNKNOWN,MODEL,SN,FW"])
def test_output_on_real_non_e36312a_models_are_rejected(monkeypatch, capsys, idn) -> None:
    session = FakeSession(idn=idn)
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
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
    assert payload["error"]["code"] == "unsupported_model_for_output_on"
    assert "E36312A" in payload["error"]["message"]
    assert session.closed is True


def test_output_on_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
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
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 99 is not supported for output-on" in payload["error"]["message"]


def test_output_on_real_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*output_command_args("output-on"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "connection_failed"


def test_output_on_real_write_failure_uses_output_on_failed(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("output-on"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "VOLT? (@1)", "CURR? (@1)"]
    assert session.writes == ["OUTP ON,(@1)"]
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "output_on_failed"


def test_output_on_real_safety_config_checks_readback_before_enabling(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "VOLT? (@1)", "CURR? (@1)", "SYST:ERR?"]
    assert session.writes == ["OUTP ON,(@1)"]
    assert payload["data"]["readback"] == {
        "setpoints": {"voltage": 1.0, "current": 0.05},
        "safety_checked": True,
    }


def test_output_on_real_safety_config_rejects_unsafe_readback(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "5.1", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "VOLT? (@1)", "CURR? (@1)"]
    assert session.writes == []
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "unsafe_output_setpoint"


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
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"]["mode"] == "real"
    assert payload["execution"]["dry_run"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["channel"] == channel
    assert payload["data"]["output"]["enabled"] is False
    assert payload["data"]["resource"]["name"] == OUTPUT_RESOURCE
    assert payload["data"]["resource"]["idn"]["model"] == "E36312A"
    assert captured.err == ""


def test_output_off_real_resource_alias_resolves_once_and_sends_scpi(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--safety-config",
                safety_config,
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
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["OUTP OFF,(@2)"]
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "channel": 2,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""


def test_output_off_real_safety_config_rejects_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
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
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
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


def test_output_state_real_non_e36312a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,MY00000000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
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
    assert payload["error"]["code"] == "unsupported_model_for_output_state"


def test_output_state_real_edu36311a_reads_channel_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,MY00000001,1.0",
        query_responses={"OUTP? (@3)": "OFF"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "3",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "OUTP? (@3)"]
    assert payload["data"]["output"]["enabled"] is False


def test_cycle_output_real_invalid_duration_rejected(capsys) -> None:
    assert (
        cli.main(
            [
                "cycle-output",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--duration-ms",
                "0",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"


def test_apply_real_generic_model_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,MY00000000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "unsupported_model_for_apply"


def test_measure_all_real_e36312a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == [
        "*IDN?",
        "MEAS:VOLT? (@1)",
        "MEAS:CURR? (@1)",
        "MEAS:VOLT? (@2)",
        "MEAS:CURR? (@2)",
        "MEAS:VOLT? (@3)",
        "MEAS:CURR? (@3)",
    ]
    assert session.writes == []
    assert session.closed is True
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "channels": [
            {"channel": 1, "measurements": {"voltage": 1.1, "current": 0.11}},
            {"channel": 2, "measurements": {"voltage": 2.2, "current": 0.22}},
            {"channel": 3, "measurements": {"voltage": 3.3, "current": 0.33}},
        ],
    }
    assert captured.err == ""


def test_measure_all_text_output(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "Channel 1: 1.1 V, 0.11 A\n"
        "Channel 2: 2.2 V, 0.22 A\n"
        "Channel 3: 3.3 V, 0.33 A\n"
    )


def test_status_real_reads_errors_then_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "SYST:ERR?": ['-100,"Command error"', '0,"No error"'],
            "OUTP? (@1)": "ON",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "1",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["status", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "SYST:ERR?",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert session.closed is True
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "errors": ['-100,"Command error"'],
        "read_count": 2,
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": True},
        ],
    }


def test_status_real_edu36311a_reads_errors_then_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,MY00000001,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["status", "--json", "--resource", "USB0::FAKE::EDU36311A::INSTR"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": False},
    ]


def test_status_real_one_channel_text(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["status", "--resource", OUTPUT_RESOURCE, "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "Errors: none\nChannel 2: Output enabled: false\n"


def test_trigger_pulse_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@3)": "1.0", "CURR? (@3)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "2",
                "--channel",
                "3",
                "--polarity",
                "negative",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "VOLT? (@3)", "CURR? (@3)", "SYST:ERR?"]
    assert session.writes == [
        "DIG:PIN2:FUNC TOUT",
        "DIG:PIN2:POL NEG",
        "DIG:TOUT:BUS ON",
        "CURR:TRIG 0.05,(@3)",
        "VOLT:TRIG 1,(@3)",
        "CURR:MODE STEP,(@3)",
        "VOLT:MODE STEP,(@3)",
        "TRIG:SOUR BUS,(@3)",
        "INIT (@3)",
        "*TRG",
    ]
    assert session.closed is True
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "pin": 2,
        "exclusive_pin": False,
        "channel": 3,
        "polarity": "negative",
        "triggered": True,
        "trigger_setpoints": {"current": 0.05, "voltage": 1.0},
    }


def test_trigger_pulse_dry_run_json_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "DIG:PIN1:FUNC TOUT"},
        {"index": 2, "type": "scpi", "command": "DIG:PIN1:POL POS"},
        {"index": 3, "type": "scpi", "command": "DIG:TOUT:BUS ON"},
        {"index": 4, "type": "scpi", "command": "CURR:TRIG <current-readback>,(@1)"},
        {"index": 5, "type": "scpi", "command": "VOLT:TRIG <voltage-readback>,(@1)"},
        {"index": 6, "type": "scpi", "command": "CURR:MODE STEP,(@1)"},
        {"index": 7, "type": "scpi", "command": "VOLT:MODE STEP,(@1)"},
        {"index": 8, "type": "scpi", "command": "TRIG:SOUR BUS,(@1)"},
        {"index": 9, "type": "scpi", "command": "INIT (@1)"},
        {"index": 10, "type": "scpi", "command": "*TRG"},
    ]


def test_trigger_pulse_exclusive_pin_clears_other_trigger_pins(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
                "--exclusive-pin",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes[:5] == [
        "DIG:PIN2:FUNC DIO",
        "DIG:PIN3:FUNC DIO",
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:TOUT:BUS ON",
    ]
    assert payload["data"]["exclusive_pin"] is True


def test_trigger_pulse_exclusive_pin_dry_run_lists_clear_steps(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "3",
                "--exclusive-pin",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["exclusive_pin"] is True
    assert payload["data"]["plan"]["steps"][:4] == [
        {"index": 1, "type": "scpi", "command": "DIG:PIN1:FUNC DIO"},
        {"index": 2, "type": "scpi", "command": "DIG:PIN2:FUNC DIO"},
        {"index": 3, "type": "scpi", "command": "DIG:PIN3:FUNC TOUT"},
        {"index": 4, "type": "scpi", "command": "DIG:PIN3:POL POS"},
    ]


def test_trigger_pulse_instrument_error_queue_fails_command(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "SYST:ERR?": ['-211,"Trigger ignored"', '0,"No error"'],
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == [
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:TOUT:BUS ON",
        "CURR:TRIG 0.05,(@1)",
        "VOLT:TRIG 1,(@1)",
        "CURR:MODE STEP,(@1)",
        "VOLT:MODE STEP,(@1)",
        "TRIG:SOUR BUS,(@1)",
        "INIT (@1)",
        "*TRG",
    ]
    assert session.queries == ["*IDN?", "VOLT? (@1)", "CURR? (@1)", "SYST:ERR?", "SYST:ERR?"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "trigger_pulse_failed"
    assert '-211,"Trigger ignored"' in payload["error"]["message"]


def test_trigger_pulse_resource_alias_resolves_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
""".strip(),
    )

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource-alias",
                "e36312a",
                "--safety-config",
                safety_config,
                "--pin",
                "1",
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
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "pin": 1,
        "channel": 1,
        "polarity": "positive",
        "exclusive_pin": False,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
    }


def test_new_commands_simulate_without_real_visa(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure-all",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["channels"][1]["measurements"] == {
        "voltage": 2.2,
        "current": 0.22,
    }

    assert (
        cli.main(
            [
                "status",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--pin",
                "3",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["triggered"] is True


@pytest.mark.parametrize(
    ("command", "extra_args", "code"),
    [
        ("measure-all", [], "unsupported_model_for_measure_all"),
        ("status", [], "unsupported_model_for_status"),
        ("trigger-pulse", ["--pin", "1"], "unsupported_model_for_trigger_pulse"),
    ],
)
def test_new_real_commands_reject_non_e36312a(
    monkeypatch,
    capsys,
    command,
    extra_args,
    code,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,MY00000000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == code
    assert session.closed is True


def test_status_unsupported_channel_is_argument_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["status", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "99"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"


def test_trigger_pulse_invalid_pin_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "4",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"


def test_status_invalid_max_errors_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "status",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--max-errors",
                "0",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"


def test_new_command_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "connection_failed"


def test_measure_all_scpi_failure_uses_measure_all_failed(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "measure_all_failed"


def test_trigger_pulse_write_failure_uses_trigger_pulse_failed(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "trigger_pulse_failed"


def test_status_scpi_failure_uses_status_failed(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"SYST:ERR?": '0,"No error"'},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["status", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "status_failed"


def test_new_commands_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> DIG:PIN1:FUNC TOUT" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> *TRG" in captured.err


def test_readback_real_e36312a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.15",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["readback", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "VOLT? (@1)",
        "CURR? (@1)",
        "VOLT? (@2)",
        "CURR? (@2)",
        "VOLT? (@3)",
        "CURR? (@3)",
    ]
    assert session.closed is True
    assert payload["data"]["channels"] == [
        {"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.05}},
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.1}},
        {"channel": 3, "setpoints": {"voltage": 3.0, "current": 0.15}},
    ]


def test_readback_real_edu36311a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,MY00000001,1.0",
        query_responses={
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "VOLT? (@2)", "CURR? (@2)"]
    assert payload["data"]["channels"] == [
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.1}},
    ]


def test_log_simulate_json_writes_csv(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"

    assert (
        cli.main(
            [
                "log",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "2",
                "--csv",
                str(csv_path),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert payload["data"]["samples_written"] == 2
    assert payload["data"]["stopped"] is False
    assert rows[0].keys() == set(cli.LOG_CSV_FIELDS)
    assert rows[0]["resource"] == "USB0::SIM::EDU36311A::INSTR"
    assert rows[0]["model"] == "EDU36311A"
    assert rows[0]["serial"] == "SIM000004"
    assert rows[0]["channel"] == "2"
    assert rows[0]["programmed_voltage"] == "2.0"
    assert rows[0]["programmed_current"] == "0.1"
    assert rows[0]["measured_voltage"] == "2.02"
    assert rows[0]["measured_current"] == "0.202"
    assert rows[0]["output_enabled"] == "False"


def test_log_simulate_json_logs_scpi_to_stderr_only(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"

    assert (
        cli.main(
            [
                "log",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                str(csv_path),
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert captured.out.startswith("{")
    assert "SCPI" not in captured.out
    assert "USB0::SIM::EDU36311A::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::SIM::EDU36311A::INSTR SCPI >> MEAS:VOLT? (@2)" in captured.err


def test_log_simulate_all_channels_jsonl_and_append(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"
    jsonl_path = tmp_path / "edu-log.jsonl"

    args = [
        "log",
        "--simulate",
        "--json",
        "--resource",
        "USB0::SIM::EDU36311A::INSTR",
        "--channel",
        "all",
        "--interval-sec",
        "0.01",
        "--samples",
        "1",
        "--csv",
        str(csv_path),
        "--jsonl",
        str(jsonl_path),
    ]
    assert cli.main(args) == 0
    first_payload = json.loads(capsys.readouterr().out)
    assert first_payload["data"]["channels"] == [1, 2, 3]

    assert cli.main([*args, "--append"]) == 0
    json.loads(capsys.readouterr().out)

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 6
    assert [row["channel"] for row in rows[:3]] == ["1", "2", "3"]
    jsonl_lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert jsonl_lines[-1]["event"] == "summary"
    assert jsonl_lines[-1]["channels"] == [1, 2, 3]


def test_sequence_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for sequence dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "sequence",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "planned"
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "log",
        "measure",
        "readback",
        "output-state",
        "wait",
        "safe-off",
    ]


def test_sequence_simulate_executes_read_only_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "sequence",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["completed_steps"] == 6
    assert payload["data"]["results"][1]["measurements"] == {"voltage": 2.02, "current": 0.202}


def test_doctor_capabilities_and_safety_inspect_json(capsys) -> None:
    assert cli.main(["doctor", "--simulate", "--json"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["data"]["simulator"]["available"] is True

    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
            ]
        )
        == 0
    )
    capabilities_payload = json.loads(capsys.readouterr().out)
    assert capabilities_payload["data"]["driver"]["class"] == "EDU36311APowerSupply"
    assert capabilities_payload["data"]["channels"] == [1, 2, 3]

    assert (
        cli.main(
            [
                "safety",
                "inspect",
                "--json",
                "--safety-config",
                "examples/safety-config.toml",
                "--resource-alias",
                "sim-e36103b",
                "--channel",
                "1",
            ]
        )
        == 0
    )
    safety_payload = json.loads(capsys.readouterr().out)
    assert safety_payload["command"] == {"name": "safety inspect"}
    assert safety_payload["data"]["limits"]["max_voltage"] == 3.3


def test_log_connection_failure_uses_log_failed(monkeypatch, tmp_path, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,MY00000001,1.0",
        query_responses={
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "SYST:ERR?": '0,"No error"',
            "MEAS:VOLT? (@2)": "2.02",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "log",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                str(tmp_path / "partial.csv"),
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "log_failed"


def test_log_interrupt_closes_session_without_stop_handler_io(monkeypatch, tmp_path, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,MY00000001,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "MEAS:VOLT? (@2)": "2.02",
            "MEAS:CURR? (@2)": "0.202",
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    def interrupting_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", interrupting_sleep)

    assert (
        cli.main(
            [
                "log",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "2",
                "--csv",
                str(tmp_path / "interrupted.csv"),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["samples_written"] == 1
    assert payload["data"]["stopped"] is True
    assert payload["data"]["stop_reason"] == "interrupted"
    assert session.closed is True
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "VOLT? (@2)",
        "CURR? (@2)",
        "MEAS:VOLT? (@2)",
        "MEAS:CURR? (@2)",
        "OUTP? (@2)",
    ]


def test_protection_status_real_reads_flags_then_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "VOLT:PROT:TRIP?": "1",
            "CURR:PROT:TRIP?": "0",
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-status",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "VOLT:PROT:TRIP?", "CURR:PROT:TRIP?", "OUTP? (@2)"]
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": False,
    }
    assert payload["data"]["outputs"] == [
        {"channel": 2, "enabled": False, "disabled_with_protection": True}
    ]


def test_clear_protection_requires_confirm_for_real_hardware(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened without --confirm")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(["clear-protection", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"])
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"


def test_clear_protection_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "clear-protection",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--all",
                "--confirm",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["OUTP:PROT:CLE (@1)", "OUTP:PROT:CLE (@2)", "OUTP:PROT:CLE (@3)"]
    assert payload["data"] == {"resource": OUTPUT_RESOURCE, "cleared_channels": [1, 2, 3]}


def test_clear_protection_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "clear-protection",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "OUTP:PROT:CLE (@2)"}
    ]


def test_protection_set_requires_confirm_for_real_hardware(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened without --confirm")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "protection-set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--ovp-voltage",
                "5",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"


def test_protection_set_requires_operation(capsys) -> None:
    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"


def test_protection_set_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
                "--ocp",
                "on",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "VOLT:PROT 5,(@1)"},
        {"index": 2, "type": "scpi", "command": "CURR:PROT:STAT ON,(@1)"},
        {"index": 3, "type": "scpi", "command": "VOLT:PROT 5,(@2)"},
        {"index": 4, "type": "scpi", "command": "CURR:PROT:STAT ON,(@2)"},
        {"index": 5, "type": "scpi", "command": "VOLT:PROT 5,(@3)"},
        {"index": 6, "type": "scpi", "command": "CURR:PROT:STAT ON,(@3)"},
    ]


def test_protection_set_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,MY00000001,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
                "--ocp",
                "on",
                "--confirm",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "VOLT:PROT 5,(@1)",
        "CURR:PROT:STAT ON,(@1)",
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "VOLT:PROT 5,(@3)",
        "CURR:PROT:STAT ON,(@3)",
    ]
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "channels": [
            {"channel": 1, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True}},
            {"channel": 2, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True}},
            {"channel": 3, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True}},
        ],
    }


def test_protection_set_rejects_ovp_above_safety_limit(tmp_path, capsys) -> None:
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--ovp-voltage",
                "5.1",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "voltage 5.1 exceeds maximum 5" in payload["error"]["message"]


def test_identify_real_reads_identity_queries(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
    assert payload["data"]["idn"]["model"] == "E36312A"
    assert payload["data"]["options"] == "0"
    assert payload["data"]["scpi_version"] == "1999.0"
    assert payload["data"]["remote_lockout_state"] == "RWLock"


def test_snapshot_real_reads_full_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "ON",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.15",
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
            "VOLT:PROT:TRIP?": "0",
            "CURR:PROT:TRIP?": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["snapshot", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries[0:2] == ["*IDN?", "SYST:ERR?"]
    assert payload["data"]["read_count"] == 1
    assert payload["data"]["idn"]["model"] == "E36312A"
    assert payload["data"]["outputs"][2] == {"channel": 3, "enabled": True}
    assert payload["data"]["readback"][1] == {
        "channel": 2,
        "setpoints": {"voltage": 2.0, "current": 0.1},
    }
    assert payload["data"]["measurements"][0] == {
        "channel": 1,
        "measurements": {"voltage": 1.1, "current": 0.11},
    }
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": False,
        "over_current_tripped": False,
    }


@pytest.mark.parametrize(
    ("command", "extra_args", "code"),
    [
        ("readback", [], "unsupported_model_for_readback"),
        ("protection-status", [], "unsupported_model_for_protection_status"),
        ("clear-protection", ["--channel", "1", "--confirm"], "unsupported_model_for_clear_protection"),
        ("snapshot", [], "unsupported_model_for_snapshot"),
    ],
)
def test_new_e36312a_commands_reject_non_e36312a(monkeypatch, capsys, command, extra_args, code) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,MY00000000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == code


@pytest.mark.parametrize(
    ("command", "extra_args", "code"),
    [
        ("readback", ["--channel", "99"], "argument_error"),
        ("protection-status", ["--channel", "99"], "argument_error"),
        ("clear-protection", ["--channel", "99", "--dry-run"], "argument_error"),
        ("snapshot", ["--max-errors", "0"], "argument_error"),
    ],
)
def test_new_e36312a_commands_argument_errors(capsys, command, extra_args, code) -> None:
    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == code


def test_new_e36312a_commands_simulate_without_real_visa(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    resource = "USB0::SIM::E36312A::INSTR"
    commands = [
        ["readback", "--simulate", "--json", "--resource", resource],
        ["protection-status", "--simulate", "--json", "--resource", resource],
        ["clear-protection", "--simulate", "--json", "--resource", resource, "--all"],
        ["identify", "--simulate", "--json", "--resource", resource],
        ["snapshot", "--simulate", "--json", "--resource", resource],
    ]

    for command in commands:
        assert cli.main(command) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True


def test_readback_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,MY00000001,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "readback",
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
    json.loads(captured.out)
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT? (@1)" in captured.err


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


# --- Safe-off dry-run remains logical ---


@pytest.mark.parametrize("command,extra_args", [
    ("safe-off", []),
])
def test_safe_off_dry_run_remains_logical(monkeypatch, capsys, command, extra_args) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    args = [command, "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"] + extra_args
    assert cli.main([*args, "--dry-run"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["operation"]["name"] == "safe-off"

