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
