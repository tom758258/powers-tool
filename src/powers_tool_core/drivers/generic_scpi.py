"""Conservative generic SCPI power-supply driver."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from powers_tool_core.drivers.base import Channel, DriverCapabilities
from powers_tool_core.safety import SafetyLimits, validate_setpoint
from powers_tool_core.setpoint_limits import validate_effective_setpoint
from powers_tool_core.transport import SessionLike


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

    capabilities = DriverCapabilities(
        channels=(1,),
        simulated_measure_channels=(1,),
        real_measure_channels=(1,),
    )

    def __init__(
        self,
        session: SessionLike,
        *,
        channel_strategy: ChannelStrategy | None = None,
        safety_limits: SafetyLimits | None = None,
    ) -> None:
        self._session = session
        self._channel_strategy = channel_strategy or NoChannelStrategy()
        self._safety_limits = safety_limits

    def __enter__(self) -> "GenericScpiPowerSupply":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def set_voltage(self, *, channel: Channel = None, voltage: float) -> None:
        self._validate_driver_setpoint(channel=channel, voltage=voltage)
        self._write(f"VOLT {_format_number(voltage)}", channel=channel)

    def set_current_limit(self, *, channel: Channel = None, current: float) -> None:
        self._validate_driver_setpoint(channel=channel, current=current)
        self._write(f"CURR {_format_number(current)}", channel=channel)

    def output_on(self, *, channel: Channel = None) -> None:
        self._write("OUTP ON", channel=channel)

    def output_off(self, *, channel: Channel = None) -> None:
        self._write("OUTP OFF", channel=channel)

    def output_state(self, *, channel: Channel = None) -> bool:
        response = self._query("OUTP?", channel=channel)
        return _parse_output_state(response)

    def measure_voltage(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS:VOLT?", channel=channel), "voltage")

    def measure_current(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS:CURR?", channel=channel), "current")

    def programmed_voltage(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("VOLT?", channel=channel), "voltage setpoint")

    def programmed_current(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("CURR?", channel=channel), "current setpoint")

    def over_voltage_protection_tripped(self, *, channel: Channel = None) -> bool:
        response = (
            self._session.query("VOLT:PROT:TRIP?")
            if channel is None
            else self._query("VOLT:PROT:TRIP?", channel=channel)
        )
        return _parse_bool(response, "over-voltage protection")

    def over_current_protection_tripped(self, *, channel: Channel = None) -> bool:
        response = (
            self._session.query("CURR:PROT:TRIP?")
            if channel is None
            else self._query("CURR:PROT:TRIP?", channel=channel)
        )
        return _parse_bool(response, "over-current protection")

    def over_voltage_protection_level(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("VOLT:PROT?", channel=channel), "over-voltage protection level")

    def over_current_protection_enabled(self, *, channel: Channel = None) -> bool:
        return _parse_bool(self._query("CURR:PROT:STAT?", channel=channel), "over-current protection state")

    def over_current_protection_delay(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("CURR:PROT:DEL?", channel=channel), "over-current protection delay")

    def over_current_protection_delay_trigger(self, *, channel: Channel = None) -> str:
        return _parse_ocp_delay_trigger(self._query("CURR:PROT:DEL:STAR?", channel=channel))

    def clear_output_protection(self, *, channel: Channel = None) -> None:
        self._write("OUTP:PROT:CLE", channel=channel)

    def set_over_voltage_protection(self, *, channel: Channel = None, voltage: float) -> None:
        validate_setpoint(channel=channel, voltage=voltage, limits=self._safety_limits)
        self._write(f"VOLT:PROT {_format_number(voltage)}", channel=channel)

    def set_over_current_protection_enabled(
        self,
        *,
        channel: Channel = None,
        enabled: bool,
    ) -> None:
        self._write(f"CURR:PROT:STAT {'ON' if enabled else 'OFF'}", channel=channel)

    def set_over_current_protection_delay(self, *, channel: Channel = None, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("over-current protection delay must be a finite non-negative number")
        self._write(f"CURR:PROT:DEL {_format_number(seconds)}", channel=channel)

    def set_over_current_protection_delay_trigger(self, *, channel: Channel = None, trigger: str) -> None:
        self._write(f"CURR:PROT:DEL:STAR {_ocp_delay_trigger_to_scpi(trigger)}", channel=channel)

    def clear_status(self) -> None:
        self._session.write("*CLS")

    def check_errors(self, max_reads: int = 20) -> list[str]:
        errors, _read_count = self.read_error_queue(max_reads)
        return errors

    def read_error_queue(self, max_reads: int = 20) -> tuple[list[str], int]:
        if max_reads < 1:
            raise ValueError("max_reads must be at least 1")

        errors: list[str] = []
        read_count = 0
        for _ in range(max_reads):
            response = self._session.query("SYST:ERR?").strip()
            read_count += 1
            if _is_no_error(response):
                break
            errors.append(response)
        return errors, read_count

    def close(self) -> None:
        self._session.close()

    def _write(self, command: str, *, channel: Channel) -> None:
        for prepared_command in self._channel_strategy.commands(command, channel=channel):
            self._session.write(prepared_command)

    def _validate_driver_setpoint(
        self,
        *,
        channel: Channel,
        voltage: float | None = None,
        current: float | None = None,
    ) -> None:
        validate_setpoint(channel=channel, voltage=voltage, current=current, limits=self._safety_limits)
        if isinstance(channel, int):
            validate_effective_setpoint(
                model=self.capabilities.electrical_ratings.model if self.capabilities.electrical_ratings else None,
                channel=channel,
                electrical_ratings=self.capabilities.electrical_ratings,
                safety_limits=self._safety_limits,
                voltage=voltage,
                current=current,
            )

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


def _format_number(value: float) -> str:
    return format(value, ".12g")


def _parse_float(response: str, measurement: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise ValueError(f"Could not parse {measurement} measurement: {response!r}") from exc


def _parse_output_state(response: str) -> bool:
    return _parse_bool(response, "output state")


def _parse_bool(response: str, label: str) -> bool:
    normalized = response.strip().upper()
    if normalized in {"1", "ON", "TRUE"}:
        return True
    if normalized in {"0", "OFF", "FALSE"}:
        return False
    raise ValueError(f"Could not parse {label}: {response!r}")


def _parse_ocp_delay_trigger(response: str) -> str:
    normalized = response.strip().upper()
    if normalized in {"SCH", "SCHA", "SCHAN", "SCHANG", "SCHANGE"}:
        return "setting-change"
    if normalized in {"CCTR", "CCTRA", "CCTRAN", "CCTRANS"}:
        return "cc-transition"
    raise ValueError(f"Could not parse over-current protection delay trigger: {response!r}")


def _ocp_delay_trigger_to_scpi(trigger: str) -> str:
    if trigger == "setting-change":
        return "SCH"
    if trigger == "cc-transition":
        return "CCTR"
    raise ValueError(f"unsupported over-current protection delay trigger: {trigger!r}")


def _is_no_error(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")
