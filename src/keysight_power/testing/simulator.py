"""Deterministic simulator resources for CLI and driver tests."""

from __future__ import annotations

from keysight_power.errors import VisaConnectionError

SIMULATED_RESOURCES = (
    "USB0::SIM::E36103B::INSTR",
    "TCPIP0::SIM::E36232A::INSTR",
)

SIMULATED_IDN = {
    "USB0::SIM::E36103B::INSTR": "KEYSIGHT,E36103B,SIM000001,1.0",
    "TCPIP0::SIM::E36232A::INSTR": "KEYSIGHT,E36232A,SIM000002,1.0",
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
        if command == "MEAS:VOLT?":
            return "1.000"
        if command == "MEAS:CURR?":
            return "0.050"
        raise VisaConnectionError(f"No simulated response for {command!r}")

    def close(self) -> None:
        self.closed = True

    def _ensure_open(self) -> None:
        if self.closed:
            raise VisaConnectionError("Simulated resource is closed")
