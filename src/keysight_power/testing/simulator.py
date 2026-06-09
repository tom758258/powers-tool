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

SIMULATED_PROGRAMMED_SETPOINTS = {
    "USB0::SIM::E36312A::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
        2: {"voltage": "2.000", "current": "0.100"},
        3: {"voltage": "3.000", "current": "0.150"},
    },
    "USB0::SIM::EDU36311A::INSTR": {
        1: {"voltage": "1.000", "current": "0.050"},
        2: {"voltage": "2.000", "current": "0.100"},
        3: {"voltage": "3.000", "current": "0.150"},
    },
}

SIMULATED_OPTIONS = {
    "USB0::SIM::E36312A::INSTR": "0",
}

SIMULATED_SCPI_VERSION = {
    "USB0::SIM::E36312A::INSTR": "1999.0",
}

SIMULATED_REMOTE_LOCKOUT = {
    "USB0::SIM::E36312A::INSTR": "RWLock",
}

SIMULATED_PROTECTION_TRIPS = {
    "USB0::SIM::E36312A::INSTR": {"voltage": False, "current": False},
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
        output_change = _simulated_output_change(command)
        if output_change is not None:
            channel, enabled = output_change
            if channel not in SIMULATED_OUTPUT_STATES.get(self.resource_name, {}):
                raise VisaConnectionError(f"No simulated response for {command!r}")
            SIMULATED_OUTPUT_STATES[self.resource_name][channel] = enabled
            return
        setpoint_change = _simulated_setpoint_change(command)
        if setpoint_change is not None:
            name, channel, value = setpoint_change
            if channel not in SIMULATED_PROGRAMMED_SETPOINTS.get(self.resource_name, {}):
                raise VisaConnectionError(f"No simulated response for {command!r}")
            SIMULATED_PROGRAMMED_SETPOINTS[self.resource_name][channel][name] = value
            return
        if _simulated_clear_protection(command) is not None:
            return
        if _simulated_protection_set(command) is not None:
            return

    def query(self, command: str) -> str:
        self._ensure_open()
        self.commands.append(command)
        if command == "*IDN?":
            return SIMULATED_IDN[self.resource_name]
        if command == "SYST:ERR?":
            return '0,"No error"'
        if command == "*OPT?":
            return SIMULATED_OPTIONS.get(self.resource_name, "0")
        if command == "SYST:VERS?":
            return SIMULATED_SCPI_VERSION.get(self.resource_name, "1999.0")
        if command == "SYST:COMM:RLST?":
            return SIMULATED_REMOTE_LOCKOUT.get(self.resource_name, "RWLock")
        if command == "VOLT:PROT:TRIP?":
            return "1" if SIMULATED_PROTECTION_TRIPS.get(self.resource_name, {}).get("voltage") else "0"
        if command == "CURR:PROT:TRIP?":
            return "1" if SIMULATED_PROTECTION_TRIPS.get(self.resource_name, {}).get("current") else "0"
        if command == "*TRG":
            return ""
        if command.startswith("DIG:PIN") and ":POL " in command:
            return ""
        if command.startswith("DIG:PIN") and ":FUNC " in command:
            return ""
        if command.startswith("DIG:TOUT:BUS "):
            return ""
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
        setpoint = _simulated_setpoint(command)
        if setpoint is not None:
            setpoint_name, channel = setpoint
            try:
                return SIMULATED_PROGRAMMED_SETPOINTS[self.resource_name][channel][setpoint_name]
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


def _simulated_setpoint(command: str) -> tuple[str, int] | None:
    if command == "VOLT?":
        return ("voltage", 1)
    if command == "CURR?":
        return ("current", 1)
    if command.startswith("VOLT? (@") and command.endswith(")"):
        return ("voltage", _parse_channel_list(command, "VOLT? (@"))
    if command.startswith("CURR? (@") and command.endswith(")"):
        return ("current", _parse_channel_list(command, "CURR? (@"))
    return None


def _simulated_setpoint_change(command: str) -> tuple[str, int, str] | None:
    if command.startswith("VOLT ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("VOLT ").split(",(@", maxsplit=1)
        return ("voltage", _parse_channel_list(f"(@{channel_text}", "(@"), value)
    if command.startswith("CURR ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("CURR ").split(",(@", maxsplit=1)
        return ("current", _parse_channel_list(f"(@{channel_text}", "(@"), value)
    return None


def _simulated_output_change(command: str) -> tuple[int, bool] | None:
    if command.startswith("OUTP ") and ",(@" in command and command.endswith(")"):
        state, channel_text = command.removeprefix("OUTP ").split(",(@", maxsplit=1)
        if state not in {"ON", "OFF"}:
            raise VisaConnectionError(f"Unsupported simulated output command {command!r}")
        return (_parse_channel_list(f"(@{channel_text}", "(@"), state == "ON")
    return None


def _simulated_output_state(command: str) -> int | None:
    if command == "OUTP?":
        return 1
    if command.startswith("OUTP? (@") and command.endswith(")"):
        return _parse_channel_list(command, "OUTP? (@")
    return None


def _simulated_clear_protection(command: str) -> int | None:
    if command.startswith("OUTP:PROT:CLE (@") and command.endswith(")"):
        return _parse_channel_list(command, "OUTP:PROT:CLE (@")
    return None


def _simulated_protection_set(command: str) -> int | None:
    if command.startswith("VOLT:PROT ") and ",(@" in command and command.endswith(")"):
        value, channel_text = command.removeprefix("VOLT:PROT ").split(",(@", maxsplit=1)
        try:
            float(value)
        except ValueError as exc:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}") from exc
        return _parse_channel_list(f"(@{channel_text}", "(@")
    if command.startswith("CURR:PROT:STAT ") and ",(@" in command and command.endswith(")"):
        state, channel_text = command.removeprefix("CURR:PROT:STAT ").split(",(@", maxsplit=1)
        if state not in {"ON", "OFF"}:
            raise VisaConnectionError(f"Unsupported simulated protection command {command!r}")
        return _parse_channel_list(f"(@{channel_text}", "(@")
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
