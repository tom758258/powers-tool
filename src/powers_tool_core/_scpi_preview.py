"""Internal helpers for no-hardware SCPI previews."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from powers_tool_core.factory import create_power_supply


class RecordingSession:
    """Session fake that records driver commands and returns numeric query data."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        return "0"

    def close(self) -> None:
        self.closed = True


def preview_measure_scpi(idn: str, *, channel: int) -> tuple[str, ...]:
    """Return SCPI queries a selected driver would use for one measurement pair."""

    return preview_driver_scpi(
        idn,
        lambda power_supply: (
            power_supply.measure_voltage(channel=channel),
            power_supply.measure_current(channel=channel),
        ),
    )


def preview_driver_scpi(
    idn: str,
    action: Callable[[Any], object],
) -> tuple[str, ...]:
    """Run a driver action against a recording session and return SCPI commands."""

    session = RecordingSession()
    power_supply = create_power_supply(session, idn)
    action(power_supply)
    return tuple(session.commands)
