import pytest
from pyvisa.constants import RENLineOperation

from keysight_power_core.connection import (
    DEFAULT_READ_TERMINATION,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WRITE_TERMINATION,
    InstrumentSession,
    SerialOptions,
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
        self.fail_writes: set[str] = set()
        self.responses: dict[str, list[str]] = {
            "*IDN?": ["KEYSIGHT,E36103B,SERIAL0000,1.0"],
            "SYST:ERR?": ['0,"No error"'],
        }
        self.closed = False
        self.ren_operations: list[RENLineOperation] = []

    def write(self, command: str) -> None:
        self.commands.append(command)
        if command in self.fail_writes:
            raise RuntimeError(f"fake write failed for {command}")

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

    def control_ren(self, operation: RENLineOperation) -> None:
        self.ren_operations.append(operation)


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


def test_open_resource_leaves_asrl_termination_unset_without_explicit_serial_options() -> None:
    manager = FakeResourceManager(("ASRL1::INSTR",))

    open_resource("ASRL1::INSTR", manager, serial_options=SerialOptions(baud_rate=9600))

    assert manager.resource.timeout == DEFAULT_TIMEOUT_MS
    assert manager.resource.baud_rate == 9600
    assert manager.resource.read_termination is None
    assert manager.resource.write_termination is None


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


def test_gpib_release_to_local_addresses_only_current_device() -> None:
    resource = FakeResource()
    session = InstrumentSession(resource, "GPIB0::1::INSTR")

    session.release_to_local()

    assert resource.ren_operations == [RENLineOperation.address_gtl]


def test_closed_session_rejects_io() -> None:
    resource = FakeResource()
    session = InstrumentSession(resource)
    session.close()

    with pytest.raises(VisaConnectionError, match="closed"):
        session.identify()


def test_open_resource_requires_resource_name() -> None:
    with pytest.raises(ValueError, match="resource_name"):
        open_resource("", FakeResourceManager())


def test_open_resource_applies_explicit_serial_options_to_asrl_only() -> None:
    manager = FakeResourceManager(("ASRL1::INSTR",))

    open_resource(
        "ASRL1::INSTR",
        manager,
        serial_options=SerialOptions(
            baud_rate=9600,
            data_bits=8,
            parity="none",
            stop_bits="2",
            flow_control="dtr_dsr",
            read_termination="\r\n",
            write_termination="\r\n",
        ),
    )

    resource = manager.resource
    assert resource.baud_rate == 9600
    assert resource.data_bits == 8
    assert resource.read_termination == "\r\n"
    assert resource.write_termination == "\r\n"
    assert resource.parity is not None
    assert resource.stop_bits is not None
    assert resource.flow_control is not None


def test_open_resource_applies_asrl_termination_only_from_explicit_serial_options() -> None:
    manager = FakeResourceManager(("ASRL1::INSTR",))

    open_resource(
        "ASRL1::INSTR",
        manager,
        serial_options=SerialOptions(read_termination="\r\n", write_termination="\r"),
    )

    assert manager.resource.read_termination == "\r\n"
    assert manager.resource.write_termination == "\r"


def test_open_resource_rejects_serial_options_on_non_asrl() -> None:
    with pytest.raises(VisaConnectionError, match="Could not open VISA resource"):
        open_resource(
            "USB0::FAKE::INSTR",
            FakeResourceManager(),
            serial_options=SerialOptions(baud_rate=9600),
        )


def test_serial_remote_and_local_on_close_are_asrl_only() -> None:
    manager = FakeResourceManager(("ASRL1::INSTR",))

    session = open_resource(
        "ASRL1::INSTR",
        manager,
        serial_remote=True,
        serial_local_on_close=True,
    )
    session.close()

    assert manager.resource.commands == ["SYST:REM", "SYST:LOC"]


def test_serial_remote_and_local_on_close_are_logged() -> None:
    manager = FakeResourceManager(("ASRL1::INSTR",))
    logs: list[tuple[str, str, str]] = []

    session = open_resource(
        "ASRL1::INSTR",
        manager,
        serial_remote=True,
        serial_local_on_close=True,
        scpi_logger=lambda resource, direction, payload: logs.append((resource, direction, payload)),
    )
    session.close()

    assert logs == [
        ("ASRL1::INSTR", ">>", "SYST:REM"),
        ("ASRL1::INSTR", ">>", "SYST:LOC"),
    ]


def test_serial_remote_failure_closes_resource_and_preserves_connection_error() -> None:
    manager = FakeResourceManager(("ASRL1::INSTR",))
    manager.resource.fail_writes.add("SYST:REM")

    with pytest.raises(VisaConnectionError, match="Could not open VISA resource"):
        open_resource("ASRL1::INSTR", manager, serial_remote=True)

    assert manager.resource.commands == ["SYST:REM", "SYST:LOC"]
    assert manager.resource.closed is True
