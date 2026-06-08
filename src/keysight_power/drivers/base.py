"""Common power-supply driver protocols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

Channel = int | str | None


@dataclass(frozen=True)
class DriverCapabilities:
    """Driver behavior that is safe to expose before hardware validation."""

    channels: tuple[int, ...]
    simulated_measure_channels: tuple[int, ...]
    real_measure_channels: tuple[int, ...]


class PowerSupply(Protocol):
    """Common API expected from power-supply drivers."""

    capabilities: DriverCapabilities

    def set_voltage(self, *, channel: Channel = None, voltage: float) -> None:
        """Set the programmed output voltage without enabling output."""
        ...

    def set_current_limit(self, *, channel: Channel = None, current: float) -> None:
        """Set the programmed current limit."""
        ...

    def output_on(self, *, channel: Channel = None) -> None:
        """Enable output for the selected channel."""
        ...

    def output_off(self, *, channel: Channel = None) -> None:
        """Disable output for the selected channel."""
        ...

    def measure_voltage(self, *, channel: Channel = None) -> float:
        """Measure output voltage for the selected channel."""
        ...

    def measure_current(self, *, channel: Channel = None) -> float:
        """Measure output current for the selected channel."""
        ...

    def clear_status(self) -> None:
        """Clear instrument status."""
        ...

    def check_errors(self, max_reads: int = 20) -> list[str]:
        """Read the instrument error queue until no error is reported."""
        ...

    def close(self) -> None:
        """Close the underlying session."""
        ...
