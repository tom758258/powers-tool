import pytest

from keysight_power_core.connection import (
    DEFAULT_READ_TERMINATION,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WRITE_TERMINATION,
    InstrumentSession,
    list_resources,
    open_resource,
)
from keysight_power_core.errors import VisaConnectionError


class FakeResourceManager:
    def __init__(self, resources: tuple[str, ...] = ("USB0::FAKE::INSTR",)) -> None:
        self.resources = resources
        self.opened: list[str] = []
        self.resource = FakeResource()

    def list_resources(self) -> tuple[str, ...]:
        return self.resources

    def open_resource(self, resource_name: str) -> "FakeResource":
        self.opened.append(resource_name)
        return self.resource


class FakeResource:
    def __init__(self) -> None:
        self.timeout: int | None = None
        self.read_termination: str | None = None
        self.write_termination: str | None = None
        self.commands: list[str] = []
        self.responses: dict[str, list[str]] = {
            "*IDN?": ["KEYSIGHT,E36103B,SERIAL0000,1.0"],
            "SYST:ERR?": ['0,"No error"'],
        }
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        responses = self.responses.get(command)
        if not responses:
            raise RuntimeError(f"No fake response for {command}")
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]

    def close(self) -> None:
        self.closed = True


def test_list_resources_uses_supplied_resource_manager() -> None:
    manager = FakeResourceManager(("USB0::A::INSTR", "TCPIP0::B::INSTR"))

    assert list_resources(manager) == ("USB0::A::INSTR", "TCPIP0::B::INSTR")


def test_open_resource_configures_resource_and_returns_session() -> None:
    manager = FakeResourceManager()

    session = open_resource("USB0::FAKE::INSTR", manager)

    assert isinstance(session, InstrumentSession)
    assert session.resource_name == "USB0::FAKE::INSTR"
    assert manager.opened == ["USB0::FAKE::INSTR"]
    assert manager.resource.timeout == DEFAULT_TIMEOUT_MS
    assert manager.resource.read_termination == DEFAULT_READ_TERMINATION
    assert manager.resource.write_termination == DEFAULT_WRITE_TERMINATION


def test_instrument_session_wraps_basic_scpi_helpers() -> None:
    resource = FakeResource()
    session = InstrumentSession(resource, "USB0::FAKE::INSTR")

    assert session.identify() == "KEYSIGHT,E36103B,SERIAL0000,1.0"
    session.clear_status()
    assert session.query_error() == '0,"No error"'
    assert resource.commands == ["*IDN?", "*CLS", "SYST:ERR?"]


def test_check_errors_reads_until_no_error() -> None:
    resource = FakeResource()
    resource.responses["SYST:ERR?"] = [
        '-100,"Command error"',
        '-200,"Execution error"',
        '0,"No error"',
    ]
    session = InstrumentSession(resource)

    assert session.check_errors() == [
        '-100,"Command error"',
        '-200,"Execution error"',
    ]
    assert resource.commands == ["SYST:ERR?", "SYST:ERR?", "SYST:ERR?"]


def test_session_context_manager_closes_resource() -> None:
    manager = FakeResourceManager()

    with open_resource("USB0::FAKE::INSTR", manager) as session:
        assert not session.closed

    assert session.closed
    assert manager.resource.closed


def test_closed_session_rejects_io() -> None:
    resource = FakeResource()
    session = InstrumentSession(resource)
    session.close()

    with pytest.raises(VisaConnectionError, match="closed"):
        session.identify()


def test_open_resource_requires_resource_name() -> None:
    with pytest.raises(ValueError, match="resource_name"):
        open_resource("", FakeResourceManager())
