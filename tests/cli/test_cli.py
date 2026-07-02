import json
import csv

import pytest

import keysight_power_core.connection as connection
import keysight_power_cli.cli as cli
from keysight_power_core.errors import VisaConnectionError


OUTPUT_RESOURCE = "USB0::SIM::E36103B::INSTR"
WRITE_VERIFICATION_REQUEST_DEFAULTS = {
    "settle_ms": 0,
    "verify_after_write": False,
    "setpoint_voltage_tolerance": 0.001,
    "setpoint_current_tolerance": 0.001,
}


def test_root_version_prints_package_version(capsys) -> None:
    assert cli.main(["--version"]) == 0

    captured = capsys.readouterr()

    assert captured.out.strip() == f"keysight-power {cli._package_version()}"
    assert captured.err == ""


class FakeSession:
    def __init__(
        self,
        idn: str = "KEYSIGHT,E36103B,SERIAL0000,1.0",
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
        lambda *, backend=None: ("USB0::FAKE::INSTR", "USB0::DEAD::INSTR"),
    )

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        if resource == "USB0::DEAD::INSTR":
            raise VisaConnectionError("not reachable")
        return FakeSession("KEYSIGHT,E36103B,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["list-resources", "--live-only"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "Live resources:\n"
        "  USB0::FAKE::INSTR\n"
        "    IDN: KEYSIGHT,E36103B,SERIAL0000,1.0\n"
    )
    assert captured.err == ""


def test_list_resources_live_only_can_log_scpi(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_resources", lambda *, backend=None: ("USB0::FAKE::INSTR",))
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,E36103B,SERIAL0000,1.0"
        ),
    )

    assert cli.main(["list-resources", "--live-only", "--log-scpi"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "Live resources:\n"
        "  USB0::FAKE::INSTR\n"
        "    IDN: KEYSIGHT,E36103B,SERIAL0000,1.0\n"
    )
    assert "USB0::FAKE::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::FAKE::INSTR SCPI << KEYSIGHT,E36103B,SERIAL0000,1.0" in captured.err


def test_verify_prints_idn_response(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return FakeSession("KEYSIGHT,E36232A,SERIAL0000,1.0")

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
    assert captured.out == "KEYSIGHT,E36232A,SERIAL0000,1.0\n"
    assert captured.err == ""
    assert opened == [("USB0::FAKE::INSTR", "@py", 1234)]


def test_verify_serial_flags_are_forwarded_to_opener(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append((resource, backend, timeout_ms, kwargs))
        return FakeSession("KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "verify",
                "--resource",
                "ASRL1::INSTR",
                "--serial-baud-rate",
                "9600",
                "--serial-data-bits",
                "8",
                "--serial-parity",
                "none",
                "--serial-stop-bits",
                "2",
                "--serial-flow-control",
                "dtr_dsr",
                "--serial-remote",
                "--serial-local-on-close",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out == "KEYSIGHT,E3646A,SERIAL0000,1.0\n"
    serial_options = opened[0][3]["serial_options"]
    assert serial_options.baud_rate == 9600
    assert serial_options.data_bits == 8
    assert serial_options.parity == "none"
    assert serial_options.stop_bits == "2"
    assert serial_options.flow_control == "dtr_dsr"
    assert opened[0][3]["serial_remote"] is True
    assert opened[0][3]["serial_local_on_close"] is True


@pytest.mark.parametrize(
    ("flag", "alias", "attribute", "expected"),
    [
        ("--serial-read-termination", "CR", "read_termination", "\r"),
        ("--serial-write-termination", "LF", "write_termination", "\n"),
        ("--serial-read-termination", "CRLF", "read_termination", "\r\n"),
    ],
)
def test_verify_serial_termination_aliases_are_normalized_for_runtime(
    monkeypatch,
    capsys,
    flag: str,
    alias: str,
    attribute: str,
    expected: str,
) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return FakeSession("KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "ASRL1::INSTR", flag, alias]) == 0

    capsys.readouterr()
    serial_options = opened[0]["serial_options"]
    assert getattr(serial_options, attribute) == expected


def test_verify_serial_termination_none_does_not_create_serial_options(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return FakeSession("KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "ASRL1::INSTR", "--serial-read-termination", "NONE"]) == 0

    capsys.readouterr()
    assert "serial_options" not in opened[0]


def test_verify_json_serial_termination_alias_uses_normalized_request_value(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000, **kwargs: FakeSession(
            "KEYSIGHT,E3646A,SERIAL0000,1.0"
        ),
    )

    assert (
        cli.main(
            [
                "verify",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--serial-read-termination",
                "CRLF",
                "--serial-write-termination",
                "LF",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"


def test_verify_json_omits_serial_options_when_not_provided(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,E3646A,SERIAL0000,1.0"
        ),
    )

    assert cli.main(["verify", "--resource", "ASRL1::INSTR", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "serial_options" not in payload["request"]
    assert "serial_remote" not in payload["request"]
    assert "serial_local_on_close" not in payload["request"]


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
    assert payload["metadata"]["duration_ms"] >= 0
    payload["metadata"] = {}
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
    assert payload["metadata"]["duration_ms"] >= 0
    assert captured.err == ""


def test_verify_json_prints_machine_readable_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, resource_manager=None, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,E36232A,SERIAL0000,1.0"
        ),
    )

    assert cli.main(["verify", "--resource", "USB0::FAKE::INSTR", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["metadata"]["duration_ms"] >= 0
    payload["metadata"] = {}
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
                idn="KEYSIGHT,E36232A,SERIAL0000,1.0",
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
    assert payload["metadata"]["duration_ms"] >= 0
    assert captured.err == ""


def test_verify_json_missing_resource_returns_validation_payload(capsys) -> None:
    assert cli.main(["verify", "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["metadata"]["duration_ms"] >= 0
    payload["metadata"] = {}
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
        "ASRL1::SIM::E3646A::INSTR\n"
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
            expected_resource(
                "ASRL1::SIM::E3646A::INSTR",
                interface="ASRL",
                simulated=True,
                reachable=True,
                idn="KEYSIGHT,E3646A,SIM000005,1.0",
            ),
        ]
    assert payload["data"]["count"] == 5
    assert payload["warnings"] == []
    assert payload["error"] is None
    assert payload["metadata"]["duration_ms"] >= 0
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


@pytest.mark.parametrize("command", ["clear", "error"])
def test_safe_generic_io_serial_termination_options_reach_request_and_opener(
    monkeypatch,
    capsys,
    command: str,
) -> None:
    session = FakeSession()
    opened = []

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append((resource, resource_manager, backend, timeout_ms, kwargs))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--serial-read-termination",
                "CRLF",
                "--serial-write-termination",
                "LF",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    serial_options = opened[0][4]["serial_options"]
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"


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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
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
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
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
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.1"},
    )
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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


def test_set_dry_run_json_accepts_voltage_only(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
        "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["voltage"] == 1.0
    assert "current" not in payload["request"]
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == ["set_voltage"]


def test_set_dry_run_json_accepts_current_only(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--current",
        "0.05",
        "--dry-run",
        "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["current"] == 0.05
    assert "voltage" not in payload["request"]
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == ["set_current_limit"]


def test_set_dry_run_json_rejects_missing_setpoints(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--dry-run",
        "--json",
    ]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "set requires voltage, current, or both" in payload["error"]["message"]


def test_set_text_dry_run_lists_only_requested_setpoint(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
    ]) == 0

    captured = capsys.readouterr()
    assert "set_voltage channel=1 voltage=1" in captured.out
    assert "set_current_limit" not in captured.out


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


def test_output_all_channel_dry_run_expands_supported_commands(capsys) -> None:
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

    for command, expected_actions in (
        ("output-on", ["output_on", "output_on", "output_on"]),
        ("output-off", ["output_off", "output_off", "output_off"]),
        ("output-state", ["output_state", "output_state", "output_state"]),
    ):
        assert cli.main([*output_command_args(command, channel="all"), "--dry-run", "--json"]) == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["data"]["plan"]["target"]["channel"] == "all"
        assert [step["action"] for step in payload["data"]["plan"]["steps"]] == expected_actions
        assert [step["parameters"]["channel"] for step in payload["data"]["plan"]["steps"]] == [1, 2, 3]

    assert cli.main([*output_command_args("cycle-output", channel="all", duration_ms="250"), "--dry-run", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "output_on",
        "output_on",
        "output_on",
        "sleep",
        "output_off",
        "output_off",
        "output_off",
    ]
    assert payload["data"]["plan"]["steps"][3]["parameters"] == {"duration_ms": 250}

    for command in ("set", "ramp", "smoke-output"):
        args = output_command_args(command, channel="all")
        if command == "ramp":
            args = [
                "ramp",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.1",
            ]
        assert cli.main([*args, "--dry-run", "--json"]) == 2
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
            idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        ),
        "channel": channel,
        "setpoints": {"current": 0.05, "voltage": 1.0},
    }
    assert captured.err == ""


def test_set_real_text_output_is_minimal_without_output_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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


@pytest.mark.parametrize("idn", ["KEYSIGHT,E36103B,SERIAL0000,1.0", "UNKNOWN,MODEL,SN,FW"])
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


def test_set_real_edu36311a_sends_current_before_voltage(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["CURR 0.05,(@2)", "VOLT 1,(@2)"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"


def test_set_real_edu36311a_rejects_completion_pulse(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "trigger_native_unsupported"


def test_set_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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

    session = FailingWriteSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
            idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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


@pytest.mark.parametrize("idn", ["KEYSIGHT,E36103B,SERIAL0000,1.0", "UNKNOWN,MODEL,SN,FW"])
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
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
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
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
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
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


def test_apply_real_edu36311a_all_no_output_writes_all_channels(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
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

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["output"]["enabled"] is False


def test_measure_all_real_e36312a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": ['-100,"Command error"', '0,"No error"'],
            "OUTP? (@1)": "ON",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "1",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 0

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
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", "USB0::FAKE::EDU36311A::INSTR"]) == 0

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


def test_validate_readonly_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "validate-readonly",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["driver"]["class"] == "EDU36311APowerSupply"
    assert payload["data"]["capabilities"]["channels"] == [1, 2, 3]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]


@pytest.mark.parametrize(
    ("idn", "resource", "driver_class"),
    [
        ("KEYSIGHT,E36312A,SERIAL0000,1.0", OUTPUT_RESOURCE, "E36312APowerSupply"),
        ("KEYSIGHT,EDU36311A,SERIAL0000,1.0", "USB0::FAKE::EDU36311A::INSTR", "EDU36311APowerSupply"),
    ],
)
def test_validate_readonly_real_sends_expected_scpi_for_supported_models(
    monkeypatch,
    capsys,
    idn,
    resource,
    driver_class,
) -> None:
    session = FakeSession(
        idn=idn,
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "0",
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
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["validate-readonly", "--json", "--resource", resource]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
        "VOLT? (@1)",
        "CURR? (@1)",
        "VOLT? (@2)",
        "CURR? (@2)",
        "VOLT? (@3)",
        "CURR? (@3)",
        "MEAS:VOLT? (@1)",
        "MEAS:CURR? (@1)",
        "MEAS:VOLT? (@2)",
        "MEAS:CURR? (@2)",
        "MEAS:VOLT? (@3)",
        "MEAS:CURR? (@3)",
    ]
    assert session.closed is True
    assert payload["data"]["driver"]["class"] == driver_class
    assert payload["data"]["read_count"] == 1
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": False},
    ]
    assert payload["data"]["readback"][1] == {
        "channel": 2,
        "setpoints": {"voltage": 2.0, "current": 0.1},
    }
    assert payload["data"]["measurements"][2] == {
        "channel": 3,
        "measurements": {"voltage": 3.3, "current": 0.33},
    }


def test_validate_readonly_rejects_generic_model(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["validate-readonly", "--json", "--resource", OUTPUT_RESOURCE]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "unsupported_model_for_validate_readonly"


def test_validate_readonly_invalid_max_errors_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "validate-readonly",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--max-errors",
                "0",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == "argument --max-errors: max-errors must be a positive integer"


def test_validate_readonly_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "OFF",
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
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["validate-readonly", "--json", "--resource", OUTPUT_RESOURCE, "--log-scpi"]) == 0

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> MEAS:CURR? (@3)" in captured.err


def test_validate_readonly_save_json_writes_stdout_envelope(tmp_path, capsys) -> None:
    json_path = tmp_path / "validate-readonly.json"

    assert (
        cli.main(
            [
                "validate-readonly",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--save-json",
                str(json_path),
            ]
        )
        == 0
    )

    stdout_payload = json.loads(capsys.readouterr().out)
    saved_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_payload == stdout_payload


def test_status_real_one_channel_text(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--resource", OUTPUT_RESOURCE, "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "Errors: none\nChannel 2: Output enabled: false\n"


def test_trigger_pulse_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        "CURR:MODE FIX,(@3)",
        "VOLT:MODE FIX,(@3)",
        "CURR:MODE STEP,(@3)",
        "VOLT:MODE STEP,(@3)",
        "TRIG:SOUR BUS,(@3)",
        "INIT (@3)",
        "*TRG",
    ]
    assert session.closed is True
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "pins": [2],
        "exclusive_pins": False,
        "channel": 3,
        "polarity": "negative",
        "triggered": True,
        "trigger_setpoints": {"current": 0.05, "voltage": 1.0},
        "pin": 2,
        "exclusive_pin": False,
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
        {"index": 6, "type": "scpi", "command": "CURR:MODE FIX,(@1)"},
        {"index": 7, "type": "scpi", "command": "VOLT:MODE FIX,(@1)"},
        {"index": 8, "type": "scpi", "command": "CURR:MODE STEP,(@1)"},
        {"index": 9, "type": "scpi", "command": "VOLT:MODE STEP,(@1)"},
        {"index": 10, "type": "scpi", "command": "TRIG:SOUR BUS,(@1)"},
        {"index": 11, "type": "scpi", "command": "INIT (@1)"},
        {"index": 12, "type": "scpi", "command": "*TRG"},
    ]


def test_trigger_pulse_dry_run_json_accepts_multiple_pins(monkeypatch, capsys) -> None:
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
                "--pins",
                "1,2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["pins"] == [1, 2]
    assert payload["request"]["exclusive_pins"] is False
    assert "pin" not in payload["request"]
    assert payload["data"]["plan"]["steps"][:5] == [
        {"index": 1, "type": "scpi", "command": "DIG:PIN1:FUNC TOUT"},
        {"index": 2, "type": "scpi", "command": "DIG:PIN1:POL POS"},
        {"index": 3, "type": "scpi", "command": "DIG:PIN2:FUNC TOUT"},
        {"index": 4, "type": "scpi", "command": "DIG:PIN2:POL POS"},
        {"index": 5, "type": "scpi", "command": "DIG:TOUT:BUS ON"},
    ]


def test_trigger_pulse_real_accepts_multiple_pins(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
                "--pins",
                "1,2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes[:5] == [
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:PIN2:FUNC TOUT",
        "DIG:PIN2:POL POS",
        "DIG:TOUT:BUS ON",
    ]
    assert payload["data"]["pins"] == [1, 2]
    assert payload["data"]["exclusive_pins"] is False
    assert "pin" not in payload["data"]


def test_trigger_pulse_exclusive_pin_clears_other_trigger_pins(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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


def test_trigger_pulse_exclusive_pins_clears_only_unselected_pin(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
                "--pins",
                "1,2",
                "--exclusive-pins",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes[:6] == [
        "DIG:PIN3:FUNC DIO",
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:PIN2:FUNC TOUT",
        "DIG:PIN2:POL POS",
        "DIG:TOUT:BUS ON",
    ]
    assert payload["data"]["pins"] == [1, 2]
    assert payload["data"]["exclusive_pins"] is True


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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        "CURR:MODE FIX,(@1)",
        "VOLT:MODE FIX,(@1)",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        "pins": [1],
        "channel": 1,
        "polarity": "positive",
        "exclusive_pins": False,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        "pin": 1,
        "exclusive_pin": False,
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
                "read-status",
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
        ("read-status", [], "unsupported_model_for_status"),
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
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == code
    assert session.closed is True


def test_status_unsupported_channel_is_argument_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "99"]) == 2

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


@pytest.mark.parametrize(
    "args",
    [
        ["--pins", "1,1"],
        ["--pins", "4"],
        ["--pins", ""],
        ["--pins", "1,"],
        ["--pin", "1", "--pins", "1,2"],
    ],
)
def test_trigger_pulse_invalid_pins_are_argument_errors(capsys, args) -> None:
    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                *args,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"


def test_status_invalid_max_errors_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "read-status",
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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

    session = FailingWriteSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"SYST:ERR?": '0,"No error"'},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "status_failed"


def test_new_commands_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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


def test_trigger_status_simulate_reports_list_and_pin_state(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-status",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["digital_pins"][0]["pin"] == 1
    assert payload["data"]["channels"][0]["trigger"]["source"] == "BUS"
    assert payload["data"]["channels"][0]["list"]["count"] == 1


def test_trigger_list_dry_run_json_plans_native_list_scpi(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--completion-pulse-pins",
                "1",
                "--fire",
                "--leave-trigger-configured",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert commands == [
        "ABOR (@1)",
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:TOUT:BUS ON",
        "LIST:VOLT 0,1,(@1)",
        "LIST:CURR 0.05,0.05,(@1)",
        "LIST:DWEL 0.01,0.01,(@1)",
        "LIST:TOUT:BOST 0,0,(@1)",
        "LIST:TOUT:EOST 0,1,(@1)",
        "LIST:COUN 1,(@1)",
        "LIST:STEP AUTO,(@1)",
        "LIST:TERM:LAST ON,(@1)",
        "CURR:MODE FIX,(@1)",
        "VOLT:MODE FIX,(@1)",
        "CURR:MODE LIST,(@1)",
        "VOLT:MODE LIST,(@1)",
        "TRIG:SOUR BUS,(@1)",
        "INIT (@1)",
        "*TRG",
    ]


def test_trigger_list_rejects_more_than_100_steps(capsys) -> None:
    values = ",".join(str(index / 100) for index in range(101))

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                values,
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "trigger_list_too_long"


def test_trigger_step_bus_fire_is_explicit(capsys) -> None:
    base_args = [
        "trigger-step",
        "--dry-run",
        "--json",
        "--resource",
        OUTPUT_RESOURCE,
        "--channel",
        "1",
        "--source",
        "bus",
        "--leave-trigger-configured",
    ]

    assert cli.main(base_args) == 0
    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "*TRG" not in commands

    assert cli.main([*base_args, "--fire"]) == 0
    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "*TRG" in commands


def test_trigger_list_dry_run_supports_explicit_bost_eost(capsys) -> None:
    assert cli.main([
        "trigger-list", "--dry-run", "--json", "--resource", OUTPUT_RESOURCE,
        "--channel", "1", "--voltage-list", "0,1", "--current-list", "0.05",
        "--dwell-list", "0.01", "--bost-list", "on,off", "--eost-list", "off,on",
        "--trigger-output-pins", "1,3", "--trigger-output-polarity", "negative",
        "--source", "immediate", "--wait-complete",
    ]) == 0

    commands = [step["command"] for step in json.loads(capsys.readouterr().out)["data"]["plan"]["steps"]]
    assert "LIST:TOUT:BOST 1,0,(@1)" in commands
    assert "LIST:TOUT:EOST 0,1,(@1)" in commands
    assert "DIG:PIN1:POL NEG" in commands
    assert "DIG:PIN3:POL NEG" in commands


def test_trigger_step_rejects_completion_pulse_pins(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-step",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "one-step trigger-list" in payload["error"]["message"]


def test_trigger_step_bus_arm_only_keeps_existing_non_wait_behavior(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-step",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--source",
                "bus",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_trigger_step_simulate_edu36311a_is_planning_only(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-step",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "1",
                "--source",
                "bus",
                "--fire",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["trigger"]["native"] is False
    assert payload["data"]["trigger"]["fallback_reason"] == "EDU36311A STEP trigger is simulator/dry-run planning only"


def test_trigger_step_real_edu36311a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-step",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "1",
                "--source",
                "bus",
                "--leave-trigger-configured",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "trigger_native_unsupported"


def test_trigger_list_bus_arm_only_requires_leave_configured(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "leave-trigger-configured" in payload["error"]["message"]


def test_trigger_list_started_without_wait_requires_leave_configured(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--fire",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert "without --wait-complete" in payload["error"]["message"]


def test_trigger_list_completion_pins_imply_final_eost(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--completion-pulse-pins",
                "1",
                "--fire",
                "--wait-complete",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "LIST:TOUT:EOST 0,1,(@1)" in commands
    assert "*OPC?" not in commands
    assert "*OPC" in commands
    assert "*ESR?" in commands


def test_trigger_list_file_steps_format(tmp_path, capsys) -> None:
    list_file = tmp_path / "list.json"
    list_file.write_text(
        json.dumps(
            {
                "channel": 1,
                "steps": [
                    {"voltage": 0.0, "current": 0.05, "dwell": 0.01},
                    {"voltage": 1.0, "current": 0.06, "dwell": 0.02},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--file",
                str(list_file),
                "--leave-trigger-configured",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "LIST:VOLT 0,1,(@1)" in commands
    assert "LIST:CURR 0.05,0.06,(@1)" in commands
    assert "LIST:DWEL 0.01,0.02,(@1)" in commands


def test_trigger_list_file_array_format_still_supported(tmp_path, capsys) -> None:
    list_file = tmp_path / "list.json"
    list_file.write_text(
        json.dumps({"channel": 1, "voltages": [0, 1], "currents": [0.05], "dwell": [0.01]}),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--file",
                str(list_file),
                "--leave-trigger-configured",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "LIST:CURR 0.05,0.05,(@1)" in commands


def test_trigger_list_safety_config_checks_each_step(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
max_voltage = 0.5
max_current = 0.5
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0.1,0.6",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--leave-trigger-configured",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "exceeds maximum" in payload["error"]["message"]


def test_trigger_list_exclusive_pins_clears_unselected_pins(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--completion-pulse-pins",
                "2",
                "--exclusive-pins",
                "--fire",
                "--wait-complete",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "DIG:PIN1:FUNC DIO" in commands
    assert "DIG:PIN2:FUNC DIO" not in commands
    assert "DIG:PIN3:FUNC DIO" in commands


def test_trigger_fire_wait_complete_requires_channel(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-fire",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--wait-complete",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "requires --channel" in payload["error"]["message"]


def test_trigger_abort_all_plans_each_channel(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-abort",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert commands[:3] == ["ABOR (@1)", "ABOR (@2)", "ABOR (@3)"]


def test_ramp_completion_over_100_steps_uses_software_without_warning(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.005",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["warnings"] == []
    assert payload["data"]["plan"]["trigger"]["native"] is False
    assert all("LIST:" not in str(step) for step in payload["data"]["plan"]["steps"])


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--completion-pulse-mode", "native"),
        ("--completion-pulse-dwell-ms", "10"),
        ("--wait-timeout-ms", "1000"),
        ("--poll-ms", "200"),
    ],
)
def test_ramp_removed_native_completion_options_are_argparse_errors(capsys, option: str, value: str) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.005",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
                option,
                value,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "unrecognized arguments" in payload["error"]["message"]


def test_ramp_dry_run_completion_uses_software_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert all("LIST:" not in str(step) for step in payload["data"]["plan"]["steps"])
    assert payload["data"]["plan"]["trigger"]["native"] is False


def test_readback_real_e36312a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
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


def test_readback_real_forwards_serial_options_to_opener(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append((resource, backend, timeout_ms, kwargs))
        return FakeSession(
            idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
            query_responses={
                "INST:NSEL?": "1",
                "VOLT?": "1.0",
                "CURR?": "0.05",
            },
        )

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                "--serial-baud-rate",
                "9600",
                "--serial-read-termination",
                "\\n",
                "--serial-write-termination",
                "\\r",
                "--serial-remote",
                "--serial-local-on-close",
            ]
        )
        == 0
    )

    json.loads(capsys.readouterr().out)
    serial_options = opened[0][3]["serial_options"]
    assert serial_options.baud_rate == 9600
    assert serial_options.read_termination == "\\n"
    assert serial_options.write_termination == "\\r"
    assert opened[0][3]["serial_remote"] is True
    assert opened[0][3]["serial_local_on_close"] is True


def test_readback_real_e3646a_preselects_and_restores_channel(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={
            "INST:NSEL?": "1",
            "VOLT?": "2.0",
            "CURR?": "0.10",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.events == [
        "query:*IDN?",
        "query:INST:NSEL?",
        "write:INST:NSEL 2",
        "query:VOLT?",
        "write:INST:NSEL 1",
        "query:INST:NSEL?",
        "write:INST:NSEL 2",
        "query:CURR?",
        "write:INST:NSEL 1",
    ]
    assert payload["data"]["channels"] == [
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.1}},
    ]


def test_readback_real_e3646a_rejects_channel_outside_driver_capabilities(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["readback", "--json", "--resource", "ASRL1::INSTR", "--channel", "3"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "supported: (1, 2)" in payload["error"]["message"]


def test_readback_serial_remote_local_log_scpi_stays_on_stderr(monkeypatch, capsys) -> None:
    class FakeSerialSession(FakeSession):
        def __init__(self, resource: str, scpi_logger):
            super().__init__(
                idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
                query_responses={
                    "INST:NSEL?": "1",
                    "VOLT?": "1.0",
                    "CURR?": "0.05",
                },
            )
            self.resource = resource
            self.scpi_logger = scpi_logger

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            if self.scpi_logger is not None:
                self.scpi_logger(self.resource, ">>", "SYST:LOC")
            super().__exit__(exc_type, exc, traceback)

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        scpi_logger = kwargs.get("scpi_logger")
        if kwargs.get("serial_remote") and scpi_logger is not None:
            scpi_logger(resource, ">>", "SYST:REM")
        return FakeSerialSession(resource, scpi_logger if kwargs.get("serial_local_on_close") else None)

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                "--log-scpi",
                "--serial-remote",
                "--serial-local-on-close",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "ASRL1::INSTR SCPI >> SYST:REM" in captured.err
    assert "ASRL1::INSTR SCPI >> SYST:LOC" in captured.err


E3646A_FORBIDDEN_WRITE_PREFIXES = (
    "VOLT",
    "CURR",
    "OUTP",
    "APPL",
    "TRIG",
    "INIT",
    "ABOR",
    "*TRG",
    "LIST:",
    "DIG:",
)


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("set", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("apply", ["--channel", "1", "--voltage", "1", "--current", "0.05", "--confirm"]),
        ("output-on", ["--channel", "1", "--confirm"]),
        ("output-off", ["--channel", "1"]),
        ("safe-off", ["--channel", "1"]),
        ("cycle-output", ["--channel", "1", "--duration-ms", "1", "--confirm"]),
        ("ramp", ["--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"]),
        ("ramp-list", ["--segment", "1", "0.05", "0", "1", "1", "0", "0"]),
        ("smoke-output", ["--channel", "1", "--voltage", "1", "--current", "0.05", "--confirm"]),
        ("protection-set", ["--channel", "1", "--ovp-voltage", "5", "--confirm"]),
        ("clear-protection", ["--channel", "1", "--confirm"]),
    ],
)
def test_e3646a_real_output_affecting_commands_remain_disabled(monkeypatch, capsys, command, extra_args) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={
            "INST:NSEL?": "1",
            "VOLT?": "1.0",
            "CURR?": "0.05",
            "OUTP?": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", "ASRL1::INSTR", *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] in {"validation", "unsupported_model"}
    assert payload["error"]["code"] != "connection_failed"
    assert not any(
        write.startswith(E3646A_FORBIDDEN_WRITE_PREFIXES)
        for write in session.writes
    )


def test_e3646a_cli_capabilities_keep_output_protection_and_trigger_disabled(capsys) -> None:
    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    support = payload["data"]["command_support"]
    guarded_commands = (
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "ramp-list",
        "smoke-output",
        "protection-status",
        "protection-set",
        "clear-protection",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    )
    for command in guarded_commands:
        assert support[command]["real"] is False


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("trigger-step", ["--channel", "1", "--source", "bus", "--fire"]),
        ("trigger-list", ["--channel", "1", "--voltage-list", "0,1", "--current-list", "0.05", "--dwell-list", "0.01", "--fire", "--wait-complete"]),
        ("trigger-fire", []),
        ("trigger-abort", ["--channel", "1"]),
    ],
)
def test_e3646a_real_trigger_write_workflows_remain_disabled(monkeypatch, capsys, command, extra_args) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", "ASRL1::INSTR", *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] in {"validation", "unsupported_model"}
    assert not any(
        write.startswith(E3646A_FORBIDDEN_WRITE_PREFIXES)
        for write in session.writes
    )


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


def test_sequence_lint_parses_bundled_yaml(capsys) -> None:
    assert (
        cli.main(
            [
                "sequence",
                "--lint",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "valid"
    assert payload["data"]["sequence_version"] == 1
    assert payload["data"]["step_count"] == 6


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
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "VOLT:PROT:TRIP? (@2)": "1",
            "CURR:PROT:TRIP? (@2)": "0",
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
    assert session.queries == ["*IDN?", "VOLT:PROT:TRIP? (@2)", "CURR:PROT:TRIP? (@2)", "OUTP? (@2)"]
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": False,
    }
    assert payload["data"]["outputs"] == [
        {"channel": 2, "enabled": False, "disabled_with_protection": True}
    ]


def test_protection_status_real_edu36311a_includes_by_channel(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "1",
            "VOLT:PROT:TRIP? (@2)": "0",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "1",
            "CURR:PROT:TRIP? (@3)": "0",
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-status",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--all",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "VOLT:PROT:TRIP? (@1)",
        "CURR:PROT:TRIP? (@1)",
        "VOLT:PROT:TRIP? (@2)",
        "CURR:PROT:TRIP? (@2)",
        "VOLT:PROT:TRIP? (@3)",
        "CURR:PROT:TRIP? (@3)",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": True,
    }
    assert payload["data"]["protection_by_channel"] == [
        {
            "channel": 1,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": True,
            },
        },
        {
            "channel": 2,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": False,
            },
        },
        {
            "channel": 3,
            "protection": {
                "over_voltage_tripped": True,
                "over_current_tripped": False,
            },
        },
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
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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


def test_clear_protection_real_edu36311a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "clear-protection",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "3",
                "--confirm",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["OUTP:PROT:CLE (@3)"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {
        "resource": "USB0::FAKE::EDU36311A::INSTR",
        "cleared_channels": [3],
    }


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
    assert payload["error"]["message"] == (
        "protection-set requires --ovp-voltage, --ocp, --ocp-delay, or --ocp-delay-trigger"
    )


def test_protection_set_rejects_negative_ocp_delay(capsys) -> None:
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
                "--ocp-delay",
                "-0.1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == "ocp_delay must be a finite non-negative number"


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
                "--ocp-delay",
                "0.5",
                "--ocp-delay-trigger",
                "setting-change",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "VOLT:PROT 5,(@1)"},
        {"index": 2, "type": "scpi", "command": "CURR:PROT:STAT ON,(@1)"},
        {"index": 3, "type": "scpi", "command": "CURR:PROT:DEL 0.5,(@1)"},
        {"index": 4, "type": "scpi", "command": "CURR:PROT:DEL:STAR SCH,(@1)"},
        {"index": 5, "type": "scpi", "command": "VOLT:PROT 5,(@2)"},
        {"index": 6, "type": "scpi", "command": "CURR:PROT:STAT ON,(@2)"},
        {"index": 7, "type": "scpi", "command": "CURR:PROT:DEL 0.5,(@2)"},
        {"index": 8, "type": "scpi", "command": "CURR:PROT:DEL:STAR SCH,(@2)"},
        {"index": 9, "type": "scpi", "command": "VOLT:PROT 5,(@3)"},
        {"index": 10, "type": "scpi", "command": "CURR:PROT:STAT ON,(@3)"},
        {"index": 11, "type": "scpi", "command": "CURR:PROT:DEL 0.5,(@3)"},
        {"index": 12, "type": "scpi", "command": "CURR:PROT:DEL:STAR SCH,(@3)"},
    ]


def test_protection_set_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
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
                "--ocp-delay",
                "0.5",
                "--ocp-delay-trigger",
                "cc-transition",
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
        "CURR:PROT:DEL 0.5,(@1)",
        "CURR:PROT:DEL:STAR CCTR,(@1)",
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "CURR:PROT:DEL 0.5,(@2)",
        "CURR:PROT:DEL:STAR CCTR,(@2)",
        "VOLT:PROT 5,(@3)",
        "CURR:PROT:STAT ON,(@3)",
        "CURR:PROT:DEL 0.5,(@3)",
        "CURR:PROT:DEL:STAR CCTR,(@3)",
    ]
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "channels": [
            {"channel": 1, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True, "ocp_delay": 0.5, "ocp_delay_trigger": "cc-transition"}},
            {"channel": 2, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True, "ocp_delay": 0.5, "ocp_delay_trigger": "cc-transition"}},
            {"channel": 3, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True, "ocp_delay": 0.5, "ocp_delay_trigger": "cc-transition"}},
        ],
    }


def test_protection_set_real_edu36311a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
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

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "VOLT:PROT 5,(@1)",
        "CURR:PROT:STAT ON,(@1)",
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "VOLT:PROT 5,(@3)",
        "CURR:PROT:STAT ON,(@3)",
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"] == "USB0::FAKE::EDU36311A::INSTR"


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
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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


def test_identify_edu36311a_real_reads_only_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?"]
    assert payload["data"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["options"] is None
    assert payload["data"]["scpi_version"] is None
    assert payload["data"]["remote_lockout_state"] is None


def test_identify_extended_query_failure_is_json_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "*OPT?"]
    assert payload["error"]["code"] == "identify_failed"
    assert "No fake response for '*OPT?'" in payload["error"]["message"]
    assert "Traceback" not in captured.err


def test_snapshot_real_reads_full_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "0",
            "VOLT:PROT:TRIP? (@2)": "0",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "0",
            "CURR:PROT:TRIP? (@3)": "0",
            "VOLT:PROT? (@1)": "5.0",
            "CURR:PROT:STAT? (@1)": "1",
            "CURR:PROT:DEL? (@1)": "0.1",
            "CURR:PROT:DEL:STAR? (@1)": "SCH",
            "VOLT:PROT? (@2)": "6.0",
            "CURR:PROT:STAT? (@2)": "0",
            "CURR:PROT:DEL? (@2)": "0.2",
            "CURR:PROT:DEL:STAR? (@2)": "CCTR",
            "VOLT:PROT? (@3)": "7.0",
            "CURR:PROT:STAT? (@3)": "1",
            "CURR:PROT:DEL? (@3)": "0.3",
            "CURR:PROT:DEL:STAR? (@3)": "SCHange",
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
    assert payload["data"]["protection_settings"][1] == {
        "channel": 2,
        "protection": {
            "ovp_voltage": 6.0,
            "ocp_enabled": False,
            "ocp_delay": 0.2,
            "ocp_delay_trigger": "cc-transition",
        },
    }


def test_snapshot_compare_accepts_raw_baseline(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    baseline = json.loads(capsys.readouterr().out)["data"]
    baseline_path = tmp_path / "snapshot-raw.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource, "--compare", str(baseline_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["passed"] is True
    assert payload["data"]["comparison"]["differences"] == []


def test_snapshot_compare_accepts_envelope_and_exits_3_on_mismatch(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    envelope = json.loads(capsys.readouterr().out)
    envelope["data"]["idn"]["serial"] = "DIFFERENT"
    baseline_path = tmp_path / "snapshot-envelope.json"
    baseline_path.write_text(json.dumps(envelope), encoding="utf-8")

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource, "--compare", str(baseline_path)]) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["passed"] is False
    assert payload["data"]["comparison"]["differences"][0]["path"] == "idn"


def test_snapshot_compare_tolerance_override_allows_measurement_delta(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    baseline = json.loads(capsys.readouterr().out)["data"]
    baseline["measurements"][0]["measurements"]["voltage"] += 0.5
    baseline_path = tmp_path / "snapshot-tolerance.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--json",
                "--resource",
                resource,
                "--compare",
                str(baseline_path),
                "--measured-voltage-tolerance",
                "0.6",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["comparison"]["passed"] is True


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
    session = FakeSession(idn="KEYSIGHT,E36103B,SERIAL0000,1.0")
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


def test_ramp_dry_run_json_plans_setpoint_only_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.05",
                "--delay-ms",
                "10",
                "--settle-ms",
                "20",
                "--verify-after-write",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    actions = [step["action"] for step in payload["data"]["plan"]["steps"]]
    assert actions == [
        "set_current_limit",
        "set_voltage",
        "sleep",
        "set_voltage",
        "sleep",
        "set_voltage",
        "sleep",
        "programmed_voltage",
        "programmed_current",
    ]
    assert "output_on" not in actions
    assert "output_off" not in actions
    assert payload["data"]["plan"]["steps"][5]["parameters"]["voltage"] == 1.0


def test_ramp_simulate_json_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for simulate ramp")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "ramp",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.25",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_ramp_real_writes_current_voltage_steps_and_exact_stop(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "ramp",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.4",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 0,(@1)", "VOLT 0.4,(@1)", "VOLT 0.8,(@1)", "VOLT 1,(@1)"]
    assert all("OUTP" not in command for command in session.writes)
    assert payload["data"]["voltages"] == [0.0, 0.4, 0.8, 1.0]


def test_ramp_real_completion_uses_software_core_path(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "ramp",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert "VOLT 0,(@1)" in session.writes
    assert "LIST:VOLT 0,0.5,1,(@1)" not in session.writes
    assert "LIST:TOUT:EOST 0,0,1,(@1)" not in session.writes
    assert payload["data"]["trigger"]["native"] is False


def test_ramp_rejects_more_than_1000_voltage_writes(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1000",
                "--step-voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "1000 voltage steps" in payload["error"]["message"]


def test_ramp_list_lint_inline_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for ramp-list lint")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "ramp-list",
                "--lint",
                "--json",
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "100",
                "0",
                "--segment",
                "2",
                "0.05",
                "1",
                "2",
                "0.5",
                "50",
                "250",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "valid"
    assert payload["data"]["segment_count"] == 2
    assert payload["data"]["segments"][1]["hold_ms"] == 250


def test_ramp_list_dry_run_file_uses_versioned_document(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "example.ramp-list.json"
    ramp_file.write_text(
        json.dumps(
            {
                "kind": "keysight-power-ramp-list",
                "version": 1,
                "segments": [
                    {
                        "channel": 1,
                        "current": 0.1,
                        "start_voltage": 0,
                        "stop_voltage": 1,
                        "step_voltage": 0.4,
                        "delay_ms": 0,
                        "hold_ms": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "ramp-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--file",
                str(ramp_file),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "planned"
    assert payload["data"]["plan"]["segments"][0]["voltages"] == [0.0, 0.4, 0.8, 1.0]


def test_ramp_list_simulate_inline_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for ramp-list simulate")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "ramp-list",
                "--simulate",
                "--json",
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "0",
                "0",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["status"] == "planned"


def test_ramp_list_file_and_segment_are_mutually_exclusive(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "example.ramp-list.json"
    ramp_file.write_text("{}", encoding="utf-8")

    assert (
        cli.main(
            [
                "ramp-list",
                "--json",
                "--file",
                str(ramp_file),
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "0",
                "0",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"


def test_ramp_list_real_executes_segments_in_order(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "ramp-list",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "1",
                "0",
                "0",
                "--segment",
                "2",
                "0.05",
                "2",
                "1",
                "1",
                "0",
                "0",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["completed_segments"] == 2
    assert session.writes == [
        "CURR 0.1,(@1)",
        "VOLT 0,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 2,(@2)",
        "VOLT 1,(@2)",
    ]


def _trigger_snapshot_query_responses() -> dict[str, str]:
    return {
        "DIG:PIN1:FUNC?": "TOUT",
        "DIG:PIN1:POL?": "POS",
        "DIG:PIN2:FUNC?": "TOUT",
        "DIG:PIN2:POL?": "POS",
        "DIG:PIN3:FUNC?": "DIO",
        "DIG:PIN3:POL?": "POS",
        "DIG:TOUT:BUS?": "0",
        "TRIG:SOUR? (@1)": "BUS",
        "TRIG:DEL? (@1)": "+0.00000000E+00",
        "VOLT:MODE? (@1)": "FIX",
        "CURR:MODE? (@1)": "FIX",
        "VOLT:TRIG? (@1)": "+0.00000000E+00",
        "CURR:TRIG? (@1)": "+2.00000000E-03",
        "LIST:VOLT? (@1)": "+0.00000000E+00",
        "LIST:CURR? (@1)": "+2.00000000E-03",
        "LIST:DWEL? (@1)": "+1.00000000E-02",
        "LIST:TOUT:BOST? (@1)": "0",
        "LIST:TOUT:EOST? (@1)": "0",
        "LIST:COUN? (@1)": "+1",
        "LIST:STEP? (@1)": "AUTO",
        "LIST:TERM:LAST? (@1)": "0",
        "*ESR?": "+1",
    }


@pytest.mark.parametrize(
    ("command", "args", "query_responses"),
    [
        ("set", ["--voltage", "1", "--current", "0.05"], {"VOLT? (@1)": "1.2", "CURR? (@1)": "0.05"}),
        ("apply", ["--voltage", "1", "--current", "0.05", "--no-output"], {"VOLT? (@1)": "1.2", "CURR? (@1)": "0.05"}),
        ("output-on", [], {"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05", "OUTP? (@1)": "OFF"}),
        ("output-off", [], {"OUTP? (@1)": "ON"}),
        (
            "ramp",
            ["--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"],
            {"VOLT? (@1)": "0.8", "CURR? (@1)": "0.05"},
        ),
    ],
)
def test_write_verification_failure_returns_exit_3(monkeypatch, capsys, command, args, query_responses) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0", query_responses=query_responses)
    monkeypatch.setattr(cli, "open_resource", lambda *open_args, **open_kwargs: session)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                *args,
                "--verify-after-write",
            ]
        )
        == 3
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "verification_failed"
    assert payload["metadata"]["verification"]["passed"] is False


def test_settle_ms_sleeps_before_verification(monkeypatch, capsys) -> None:
    sleeps = []
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))

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
                "--settle-ms",
                "25",
                "--verify-after-write",
            ]
        )
        == 0
    )

    assert sleeps == [0.025]
    assert json.loads(capsys.readouterr().out)["data"]["verification"]["passed"] is True


def test_readback_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
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
