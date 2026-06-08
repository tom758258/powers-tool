import json

import keysight_power.connection as connection
import keysight_power.cli as cli
from keysight_power.errors import VisaConnectionError


class FakeSession:
    def __init__(self, idn: str) -> None:
        self.idn = idn
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def identify(self) -> str:
        return self.idn


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
    assert captured.out == "USB0::SIM::E36103B::INSTR\nTCPIP0::SIM::E36232A::INSTR\n"
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
    ]
    assert payload["data"]["count"] == 2
    assert payload["warnings"] == []
    assert payload["error"] is None
    assert payload["metadata"] == {}
    assert "SCPI >> *IDN?" in captured.err
    assert "KEYSIGHT,E36103B,SIM000001,1.0" in captured.err


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
