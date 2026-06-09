"""Deterministic simulator resources for CLI and driver tests."""

from __future__ import annotations

from keysight_power.errors import VisaConnectionError

SIMULATED_RESOURCES = (
    "USB0::SIM::E36103B::INSTR",
    "TCPIP0::SIM::E36232A::INSTR",
    "USB0::SIM::E36312A::INSTR",
    "USB0::SIM::EDU36311A::INSTR",
)

SIMULATED_IDN = {
    "USB0::SIM::E36103B::INSTR": "KEYSIGHT,E36103B,SIM000001,1.0",
    "TCPIP0::SIM::E36232A::INSTR": "KEYSIGHT,E36232A,SIM000002,1.0",
    "USB0::SIM::E36312A::INSTR": "KEYSIGHT,E36312A,SIM000003,1.0",
    "USB0::SIM::EDU36311A::INSTR": "KEYSIGHT,EDU36311A,SIM000004,1.0",
}

SIMULATED_MEASUREMENTS = {
    "USB0::SIM::E36103B::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
    },
    "TCPIP0::SIM::E36232A::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
    },
    "USB0::SIM::E36312A::INSTR": {
        1: {"voltage": "1.100", "current": "0.110"},
        2: {"voltage": "2.200", "current": "0.220"},
        3: {"voltage": "3.300", "current": "0.330"},
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {"voltage": "1.010", "current": "0.101"},
        2: {"voltage": "2.020", "current": "0.202"},
        3: {"voltage": "3.030", "current": "0.303"},
    },
}

SIMULATED_OUTPUT_STATES = {
    "USB0::SIM::E36103B::INSTR": {1: False},
    "TCPIP0::SIM::E36232A::INSTR": {1: False},
    "USB0::SIM::E36312A::INSTR": {1: False, 2: False, 3: False},
    "USB0::SIM::EDU36311A::INSTR": {1: False, 2: False, 3: False},
}


class SimulatedResourceManager:
    """Resource manager that never opens real VISA resources."""

    def __init__(self, resources: tuple[str, ...] = SIMULATED_RESOURCES) -> None:
        self._resources = resources

    def list_resources(self) -> tuple[str, ...]:
        return self._resources

    def open_resource(self, resource_name: str) -> "SimulatedResource":
        if resource_name not in SIMULATED_IDN:
            raise VisaConnectionError(f"Unknown simulated resource {resource_name!r}")
        return SimulatedResource(resource_name)


class SimulatedResource:
    """Small PyVISA-like resource for deterministic no-hardware flows."""

    def __init__(self, resource_name: str) -> None:
        self.resource_name = resource_name
        self.timeout: int | None = None
        self.read_termination: str | None = None
        self.write_termination: str | None = None
        self.commands: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self._ensure_open()
        self.commands.append(command)

    def query(self, command: str) -> str:
        self._ensure_open()
        self.commands.append(command)
        if command == "*IDN?":
            return SIMULATED_IDN[self.resource_name]
        if command == "SYST:ERR?":
            return '0,"No error"'
        output_state = _simulated_output_state(command)
        if output_state is not None:
            channel = output_state
            try:
                return "ON" if SIMULATED_OUTPUT_STATES[self.resource_name][channel] else "OFF"
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        measurement = _simulated_measurement(command)
        if measurement is not None:
            measurement_name, channel = measurement
            try:
                return SIMULATED_MEASUREMENTS[self.resource_name][channel][measurement_name]
            except KeyError as exc:
                raise VisaConnectionError(f"No simulated response for {command!r}") from exc
        raise VisaConnectionError(f"No simulated response for {command!r}")

    def close(self) -> None:
        self.closed = True

    def _ensure_open(self) -> None:
        if self.closed:
            raise VisaConnectionError("Simulated resource is closed")


def _simulated_measurement(command: str) -> tuple[str, int] | None:
    if command == "MEAS:VOLT?":
        return ("voltage", 1)
    if command == "MEAS:CURR?":
        return ("current", 1)
    if command.startswith("MEAS:VOLT? (@") and command.endswith(")"):
        return ("voltage", _parse_channel_list(command, "MEAS:VOLT? (@"))
    if command.startswith("MEAS:CURR? (@") and command.endswith(")"):
        return ("current", _parse_channel_list(command, "MEAS:CURR? (@"))
    return None


def _simulated_output_state(command: str) -> int | None:
    if command == "OUTP?":
        return 1
    if command.startswith("OUTP? (@") and command.endswith(")"):
        return _parse_channel_list(command, "OUTP? (@")
    return None


def _parse_channel_list(command: str, prefix: str) -> int:
    channel_text = command.removeprefix(prefix).removesuffix(")").strip()
    try:
        channel = int(channel_text)
    except ValueError as exc:
        raise VisaConnectionError(f"Unsupported simulated channel list in {command!r}") from exc
    if channel < 1:
        raise VisaConnectionError(f"Unsupported simulated channel list in {command!r}")
    return channel
