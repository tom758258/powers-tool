"""Conservative generic SCPI power-supply driver."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from keysight_power.drivers.base import Channel
from keysight_power.transport import SessionLike


class ChannelStrategy(Protocol):
    """Build channel-specific command sequences for a driver operation."""

    def commands(self, command: str, *, channel: Channel) -> tuple[str, ...]:
        """Return SCPI commands for one operation."""
        ...


@dataclass(frozen=True)
class NoChannelStrategy:
    """Use commands without channel syntax.

    The default accepts no channel or channel 1 only. That keeps the generic
    driver useful for single-output supplies without hiding multi-output channel
    assumptions in command strings.
    """

    accepted_channels: tuple[Channel, ...] = (None, 1, "1")

    def commands(self, command: str, *, channel: Channel) -> tuple[str, ...]:
        if channel not in self.accepted_channels:
            raise ValueError(f"channel {channel!r} is not valid for no-channel SCPI")
        return (command,)


@dataclass(frozen=True)
class ChannelListStrategy:
    """Append a SCPI channel-list suffix such as `(@1)` to each command."""

    def commands(self, command: str, *, channel: Channel) -> tuple[str, ...]:
        channel_name = _required_channel_name(channel)
        suffix = f"(@{channel_name})"
        separator = "," if _command_has_parameter(command) else " "
        return (f"{command}{separator}{suffix}",)


@dataclass(frozen=True)
class PreselectChannelStrategy:
    """Preselect a channel before each command."""

    select_command_template: str = "INST:NSEL {channel}"

    def commands(self, command: str, *, channel: Channel) -> tuple[str, ...]:
        channel_name = _required_channel_name(channel)
        return (self.select_command_template.format(channel=channel_name), command)


class GenericScpiPowerSupply:
    """Small generic driver for common SCPI DC-supply operations."""

    def __init__(
        self,
        session: SessionLike,
        *,
        channel_strategy: ChannelStrategy | None = None,
    ) -> None:
        self._session = session
        self._channel_strategy = channel_strategy or NoChannelStrategy()

    def __enter__(self) -> "GenericScpiPowerSupply":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def set_voltage(self, *, channel: Channel = None, voltage: float) -> None:
        _validate_non_negative_finite("voltage", voltage)
        self._write(f"VOLT {_format_number(voltage)}", channel=channel)

    def set_current_limit(self, *, channel: Channel = None, current: float) -> None:
        _validate_non_negative_finite("current", current)
        self._write(f"CURR {_format_number(current)}", channel=channel)

    def output_on(self, *, channel: Channel = None) -> None:
        self._write("OUTP ON", channel=channel)

    def output_off(self, *, channel: Channel = None) -> None:
        self._write("OUTP OFF", channel=channel)

    def measure_voltage(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS:VOLT?", channel=channel), "voltage")

    def measure_current(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS:CURR?", channel=channel), "current")

    def clear_status(self) -> None:
        self._session.write("*CLS")

    def check_errors(self, max_reads: int = 20) -> list[str]:
        if max_reads < 1:
            raise ValueError("max_reads must be at least 1")

        errors: list[str] = []
        for _ in range(max_reads):
            response = self._session.query("SYST:ERR?").strip()
            if _is_no_error(response):
                break
            errors.append(response)
        return errors

    def close(self) -> None:
        self._session.close()

    def _write(self, command: str, *, channel: Channel) -> None:
        for prepared_command in self._channel_strategy.commands(command, channel=channel):
            self._session.write(prepared_command)

    def _query(self, command: str, *, channel: Channel) -> str:
        commands = self._channel_strategy.commands(command, channel=channel)
        for prepared_command in commands[:-1]:
            self._session.write(prepared_command)
        return self._session.query(commands[-1]).strip()


def _required_channel_name(channel: Channel) -> str:
    if channel is None:
        raise ValueError("channel is required for this channel strategy")
    if isinstance(channel, int) and channel < 1:
        raise ValueError("channel must be at least 1")
    channel_name = str(channel).strip()
    if not channel_name:
        raise ValueError("channel is required for this channel strategy")
    return channel_name


def _command_has_parameter(command: str) -> bool:
    return " " in command.strip()


def _validate_non_negative_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _format_number(value: float) -> str:
    return format(value, ".12g")


def _parse_float(response: str, measurement: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise ValueError(f"Could not parse {measurement} measurement: {response!r}") from exc


def _is_no_error(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")
