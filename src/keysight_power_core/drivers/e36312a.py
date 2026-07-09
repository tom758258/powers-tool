"""Keysight E36312A driver foundation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from keysight_power_core.drivers.base import DriverCapabilities
from keysight_power_core.electrical_ratings import E36312A_ELECTRICAL_RATINGS
from keysight_power_core.drivers.generic_scpi import (
    ChannelListStrategy,
    ChannelStrategy,
    GenericScpiPowerSupply,
)
from keysight_power_core.safety import SafetyLimits
from keysight_power_core.transport import SessionLike


class E36312APowerSupply(GenericScpiPowerSupply):
    """E36312A SCPI driver using channel-list syntax for output channels."""

    capabilities = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
        electrical_ratings=E36312A_ELECTRICAL_RATINGS,
    )

    def __init__(
        self,
        session: SessionLike,
        *,
        channel_strategy: ChannelStrategy | None = None,
        safety_limits: SafetyLimits | None = None,
    ) -> None:
        super().__init__(
            session,
            channel_strategy=channel_strategy or ChannelListStrategy(),
            safety_limits=safety_limits,
        )

    def configure_trigger_output_pin(self, pin: int, polarity: str) -> None:
        """Configure a rear digital pin as a trigger output."""

        self.configure_trigger_output_pins((pin,), polarity)

    def configure_trigger_output_pins(self, pins: tuple[int, ...], polarity: str) -> None:
        """Configure rear digital pins as trigger outputs."""

        _validate_trigger_pins(pins)
        polarity_command = _trigger_polarity_command(polarity)
        for pin in pins:
            self._session.write(f"DIG:PIN{pin}:FUNC TOUT")
            self._session.write(f"DIG:PIN{pin}:POL {polarity_command}")

    def clear_trigger_output_pins(
        self,
        *,
        except_pin: int | None = None,
        except_pins: tuple[int, ...] | None = None,
    ) -> None:
        """Configure rear digital trigger output pins back to digital I/O."""

        if except_pin is not None and except_pins is not None:
            raise ValueError("use except_pin or except_pins, not both")
        keep_pins = (except_pin,) if except_pin is not None else tuple(except_pins or ())
        if keep_pins:
            _validate_trigger_pins(keep_pins)
        for pin in (1, 2, 3):
            if pin not in keep_pins:
                self._session.write(f"DIG:PIN{pin}:FUNC DIO")

    def enable_trigger_output_bus(self, enabled: bool = True) -> None:
        """Enable or disable BUS-triggered trigger output pulses."""

        self._session.write(f"DIG:TOUT:BUS {'ON' if enabled else 'OFF'}")

    def digital_pin_function(self, pin: int) -> str:
        """Return the configured rear digital pin function."""

        _validate_trigger_pins((pin,))
        return self._session.query(f"DIG:PIN{pin}:FUNC?").strip().upper()

    def digital_pin_polarity(self, pin: int) -> str:
        """Return the configured rear digital pin polarity."""

        _validate_trigger_pins((pin,))
        return self._session.query(f"DIG:PIN{pin}:POL?").strip().upper()

    def trigger_output_bus_enabled(self) -> bool:
        """Return whether BUS-triggered trigger outputs are enabled."""

        return _parse_bool(self._session.query("DIG:TOUT:BUS?"))

    def set_digital_pin_function(self, pin: int, function: str) -> None:
        """Set a rear digital pin function."""

        _validate_trigger_pins((pin,))
        self._session.write(f"DIG:PIN{pin}:FUNC {_digital_pin_function_command(function)}")

    def set_digital_pin_polarity(self, pin: int, polarity: str) -> None:
        """Set a rear digital pin polarity using POS/NEG or positive/negative."""

        _validate_trigger_pins((pin,))
        self._session.write(f"DIG:PIN{pin}:POL {_trigger_polarity_command(polarity)}")

    def set_triggered_voltage(self, *, channel: int, voltage: float) -> None:
        """Program a triggered voltage level for one channel."""

        self._require_output_channel(channel)
        self._validate_driver_setpoint(channel=channel, voltage=voltage)
        self._session.write(f"VOLT:TRIG {_format_number(voltage)},(@{channel})")

    def set_triggered_current(self, *, channel: int, current: float) -> None:
        """Program a triggered current level for one channel."""

        self._require_output_channel(channel)
        self._validate_driver_setpoint(channel=channel, current=current)
        self._session.write(f"CURR:TRIG {_format_number(current)},(@{channel})")

    def set_voltage_trigger_mode_step(self, channel: int) -> None:
        """Set voltage transient mode to STEP for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"VOLT:MODE STEP,(@{channel})")

    def set_current_trigger_mode_step(self, channel: int) -> None:
        """Set current transient mode to STEP for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"CURR:MODE STEP,(@{channel})")

    def set_voltage_trigger_mode(self, *, channel: int, mode: str) -> None:
        """Set voltage transient mode to FIX, STEP, or LIST for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"VOLT:MODE {_trigger_mode(mode)},(@{channel})")

    def set_current_trigger_mode(self, *, channel: int, mode: str) -> None:
        """Set current transient mode to FIX, STEP, or LIST for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"CURR:MODE {_trigger_mode(mode)},(@{channel})")

    def set_trigger_modes(self, *, channel: int, current_mode: str, voltage_mode: str) -> None:
        """Safely switch current and voltage transient modes together."""

        normalized_current = _trigger_mode(current_mode)
        normalized_voltage = _trigger_mode(voltage_mode)
        self.set_current_trigger_mode(channel=channel, mode="FIX")
        self.set_voltage_trigger_mode(channel=channel, mode="FIX")
        if normalized_current != "FIX":
            self.set_current_trigger_mode(channel=channel, mode=normalized_current)
        if normalized_voltage != "FIX":
            self.set_voltage_trigger_mode(channel=channel, mode=normalized_voltage)

    def voltage_trigger_mode(self, channel: int) -> str:
        self._require_output_channel(channel)
        return self._session.query(f"VOLT:MODE? (@{channel})").strip().upper()

    def current_trigger_mode(self, channel: int) -> str:
        self._require_output_channel(channel)
        return self._session.query(f"CURR:MODE? (@{channel})").strip().upper()

    def triggered_voltage(self, channel: int) -> float:
        self._require_output_channel(channel)
        return _parse_float(self._session.query(f"VOLT:TRIG? (@{channel})"), "triggered voltage")

    def triggered_current(self, channel: int) -> float:
        self._require_output_channel(channel)
        return _parse_float(self._session.query(f"CURR:TRIG? (@{channel})"), "triggered current")

    def configure_output_trigger_source_bus(self, channel: int) -> None:
        """Select BUS as the output trigger source for one channel."""

        self.set_output_trigger_source(channel=channel, source="BUS")

    def set_output_trigger_source(self, *, channel: int, source: str) -> None:
        """Select output trigger source for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"TRIG:SOUR {_trigger_source(source)},(@{channel})")

    def output_trigger_source(self, channel: int) -> str:
        self._require_output_channel(channel)
        return self._session.query(f"TRIG:SOUR? (@{channel})").strip().upper()

    def set_output_trigger_delay(self, *, channel: int, delay: float) -> None:
        self._require_output_channel(channel)
        if delay < 0:
            raise ValueError("trigger delay must be non-negative")
        self._session.write(f"TRIG:DEL {_format_number(delay)},(@{channel})")

    def output_trigger_delay(self, channel: int) -> float:
        self._require_output_channel(channel)
        return _parse_float(self._session.query(f"TRIG:DEL? (@{channel})"), "trigger delay")

    def initiate_output_trigger(self, channel: int) -> None:
        """Initiate the output trigger system for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"INIT (@{channel})")

    def abort_output_trigger(self, channel: int) -> None:
        """Abort output trigger/list execution for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"ABOR (@{channel})")

    def fire_bus_trigger(self) -> None:
        """Fire the SCPI bus trigger."""

        self._session.write("*TRG")

    def wait_complete(self) -> str:
        """Block until pending operations complete."""

        return self._session.query("*OPC?").strip()

    def prepare_operation_complete_wait(self) -> None:
        """Arm status polling for operation-complete without blocking on *OPC?."""

        self._session.write("*CLS")
        self._session.write("*ESE 1")
        self._session.write("*OPC")

    def operation_complete_event(self) -> bool:
        """Return whether the standard event status register reports OPC."""

        try:
            response = self._session.query("*ESR?").strip()
        except Exception as query_exc:
            read_stb = getattr(self._session, "read_stb", None)
            if callable(read_stb):
                return bool(int(read_stb()) & 32)
            raise query_exc
        try:
            return bool(int(float(response)) & 1)
        except ValueError as exc:
            raise ValueError(f"Could not parse *ESR? response: {response!r}") from exc

    def trigger_pulse(self, *, channel: int) -> None:
        """Emit a BUS trigger pulse."""

        self.initiate_output_trigger(channel)
        self.fire_bus_trigger()

    def configure_voltage_list(self, *, channel: int, values: tuple[float, ...]) -> None:
        self._require_output_channel(channel)
        _validate_list_values(values, "voltage")
        for value in values:
            self._validate_driver_setpoint(channel=channel, voltage=value)
        self._session.write(f"LIST:VOLT {_format_number_list(values)},(@{channel})")

    def configure_current_list(self, *, channel: int, values: tuple[float, ...]) -> None:
        self._require_output_channel(channel)
        _validate_list_values(values, "current")
        for value in values:
            self._validate_driver_setpoint(channel=channel, current=value)
        self._session.write(f"LIST:CURR {_format_number_list(values)},(@{channel})")

    def configure_dwell_list(self, *, channel: int, values: tuple[float, ...]) -> None:
        self._require_output_channel(channel)
        _validate_dwell_values(values)
        self._session.write(f"LIST:DWEL {_format_number_list(values)},(@{channel})")

    def configure_trigger_output_begin_list(self, *, channel: int, values: tuple[bool, ...]) -> None:
        self._require_output_channel(channel)
        _validate_bool_list(values, "BOST")
        self._session.write(f"LIST:TOUT:BOST {_format_bool_list(values)},(@{channel})")

    def configure_trigger_output_end_list(self, *, channel: int, values: tuple[bool, ...]) -> None:
        self._require_output_channel(channel)
        _validate_bool_list(values, "EOST")
        self._session.write(f"LIST:TOUT:EOST {_format_bool_list(values)},(@{channel})")

    def set_list_count(self, *, channel: int, count: int) -> None:
        self._require_output_channel(channel)
        if count < 1 or count > 256:
            raise ValueError("LIST count must be between 1 and 256")
        self._session.write(f"LIST:COUN {count},(@{channel})")

    def set_list_step_mode(self, *, channel: int, mode: str) -> None:
        self._require_output_channel(channel)
        normalized = mode.strip().upper()
        if normalized not in {"AUTO", "ONCE"}:
            raise ValueError("LIST step mode must be AUTO or ONCE")
        self._session.write(f"LIST:STEP {normalized},(@{channel})")

    def set_list_terminate_last(self, *, channel: int, enabled: bool) -> None:
        self._require_output_channel(channel)
        self._session.write(f"LIST:TERM:LAST {'ON' if enabled else 'OFF'},(@{channel})")

    def list_voltage(self, channel: int) -> tuple[float, ...]:
        self._require_output_channel(channel)
        return _parse_float_list(self._session.query(f"LIST:VOLT? (@{channel})"))

    def list_current(self, channel: int) -> tuple[float, ...]:
        self._require_output_channel(channel)
        return _parse_float_list(self._session.query(f"LIST:CURR? (@{channel})"))

    def list_dwell(self, channel: int) -> tuple[float, ...]:
        self._require_output_channel(channel)
        return _parse_float_list(self._session.query(f"LIST:DWEL? (@{channel})"))

    def list_trigger_output_begin(self, channel: int) -> tuple[bool, ...]:
        self._require_output_channel(channel)
        return _parse_bool_list(self._session.query(f"LIST:TOUT:BOST? (@{channel})"))

    def list_trigger_output_end(self, channel: int) -> tuple[bool, ...]:
        self._require_output_channel(channel)
        return _parse_bool_list(self._session.query(f"LIST:TOUT:EOST? (@{channel})"))

    def list_count(self, channel: int) -> int:
        self._require_output_channel(channel)
        return int(float(self._session.query(f"LIST:COUN? (@{channel})").strip()))

    def list_step_mode(self, channel: int) -> str:
        self._require_output_channel(channel)
        return self._session.query(f"LIST:STEP? (@{channel})").strip().upper()

    def list_terminate_last(self, channel: int) -> bool:
        self._require_output_channel(channel)
        return _parse_bool(self._session.query(f"LIST:TERM:LAST? (@{channel})"))

    def configure_list(
        self,
        *,
        channel: int,
        voltages: tuple[float, ...],
        currents: tuple[float, ...],
        dwell: tuple[float, ...],
        begin_outputs: tuple[bool, ...] | None = None,
        end_outputs: tuple[bool, ...] | None = None,
        count: int = 1,
        step_mode: str = "AUTO",
        terminate_last: bool = True,
    ) -> None:
        """Configure an E36312A output LIST for one channel."""

        _validate_parallel_lists(voltages, currents, dwell, begin_outputs, end_outputs)
        self.configure_voltage_list(channel=channel, values=voltages)
        self.configure_current_list(channel=channel, values=currents)
        self.configure_dwell_list(channel=channel, values=dwell)
        if begin_outputs is not None:
            self.configure_trigger_output_begin_list(channel=channel, values=begin_outputs)
        if end_outputs is not None:
            self.configure_trigger_output_end_list(channel=channel, values=end_outputs)
        self.set_list_count(channel=channel, count=count)
        self.set_list_step_mode(channel=channel, mode=step_mode)
        self.set_list_terminate_last(channel=channel, enabled=terminate_last)

    def _require_output_channel(self, channel: int) -> None:
        if channel not in self.capabilities.channels:
            raise ValueError("trigger output channel must be 1, 2, or 3")

    def trigger_snapshot(self, channel: int) -> "TriggerSnapshot":
        """Read trigger, LIST, and digital-pin state needed for restoration."""

        self._require_output_channel(channel)
        return TriggerSnapshot(
            channel=channel,
            digital_pins={
                pin: {
                    "function": self.digital_pin_function(pin),
                    "polarity": self.digital_pin_polarity(pin),
                }
                for pin in (1, 2, 3)
            },
            trigger_output_bus_enabled=self.trigger_output_bus_enabled(),
            trigger={
                "source": self.output_trigger_source(channel),
                "delay": self.output_trigger_delay(channel),
                "voltage_mode": self.voltage_trigger_mode(channel),
                "current_mode": self.current_trigger_mode(channel),
                "triggered_voltage": self.triggered_voltage(channel),
                "triggered_current": self.triggered_current(channel),
            },
            list_state={
                "voltage": self.list_voltage(channel),
                "current": self.list_current(channel),
                "dwell": self.list_dwell(channel),
                "tout_bost": self.list_trigger_output_begin(channel),
                "tout_eost": self.list_trigger_output_end(channel),
                "count": self.list_count(channel),
                "step_mode": self.list_step_mode(channel),
                "terminate_last": self.list_terminate_last(channel),
            },
        )

    def restore_trigger_snapshot(self, snapshot: "TriggerSnapshot") -> None:
        """Restore state captured by :meth:`trigger_snapshot`."""

        channel = snapshot.channel
        self._require_output_channel(channel)
        self.abort_output_trigger(channel)
        for pin, state in snapshot.digital_pins.items():
            self.set_digital_pin_function(pin, str(state["function"]))
            self.set_digital_pin_polarity(pin, str(state["polarity"]))
        self.enable_trigger_output_bus(bool(snapshot.trigger_output_bus_enabled))
        self.set_output_trigger_source(channel=channel, source=str(snapshot.trigger["source"]))
        self.set_output_trigger_delay(channel=channel, delay=float(snapshot.trigger["delay"]))
        self.set_triggered_current(channel=channel, current=float(snapshot.trigger["triggered_current"]))
        self.set_triggered_voltage(channel=channel, voltage=float(snapshot.trigger["triggered_voltage"]))
        self.set_trigger_modes(
            channel=channel,
            current_mode=str(snapshot.trigger["current_mode"]),
            voltage_mode=str(snapshot.trigger["voltage_mode"]),
        )
        list_state = snapshot.list_state
        self.configure_list(
            channel=channel,
            voltages=tuple(float(value) for value in list_state["voltage"]),
            currents=tuple(float(value) for value in list_state["current"]),
            dwell=tuple(float(value) for value in list_state["dwell"]),
            begin_outputs=tuple(bool(value) for value in list_state["tout_bost"]),
            end_outputs=tuple(bool(value) for value in list_state["tout_eost"]),
            count=int(list_state["count"]),
            step_mode=str(list_state["step_mode"]),
            terminate_last=bool(list_state["terminate_last"]),
        )


@dataclass(frozen=True)
class TriggerSnapshot:
    """E36312A trigger/list state captured for best-effort restoration."""

    channel: int
    digital_pins: dict[int, dict[str, str]]
    trigger_output_bus_enabled: bool
    trigger: dict[str, Any]
    list_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "digital_pins": {
                str(pin): dict(state)
                for pin, state in self.digital_pins.items()
            },
            "trigger_output_bus_enabled": self.trigger_output_bus_enabled,
            "trigger": dict(self.trigger),
            "list": {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in self.list_state.items()
            },
        }


def _trigger_polarity_command(polarity: str) -> str:
    normalized = polarity.strip().lower()
    if normalized in {"positive", "pos"}:
        return "POS"
    if normalized in {"negative", "neg"}:
        return "NEG"
    raise ValueError("trigger polarity must be positive or negative")


def _digital_pin_function_command(function: str) -> str:
    normalized = function.strip().upper()
    aliases = {
        "DIO": "DIO",
        "DINP": "DIO",
        "TOUT": "TOUT",
        "TINP": "TINP",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("digital pin function must be DIO, DINP, TOUT, or TINP") from exc


def _validate_trigger_pins(pins: tuple[int, ...]) -> None:
    if not pins:
        raise ValueError("at least one trigger output pin is required")
    seen: set[int] = set()
    for pin in pins:
        if pin not in (1, 2, 3):
            raise ValueError("trigger output pin must be 1, 2, or 3")
        if pin in seen:
            raise ValueError("trigger output pins must not contain duplicates")
        seen.add(pin)


def _format_number(value: float) -> str:
    return format(value, ".12g")


def _format_number_list(values: tuple[float, ...]) -> str:
    return ",".join(_format_number(value) for value in values)


def _format_bool_list(values: tuple[bool, ...]) -> str:
    return ",".join("1" if value else "0" for value in values)


def _parse_float(response: str, label: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise ValueError(f"Could not parse {label}: {response!r}") from exc


def _parse_float_list(response: str) -> tuple[float, ...]:
    stripped = response.strip()
    if not stripped:
        return ()
    return tuple(float(item.strip()) for item in stripped.split(",") if item.strip())


def _parse_bool(response: str) -> bool:
    normalized = response.strip().upper()
    if normalized in {"1", "ON", "TRUE"}:
        return True
    if normalized in {"0", "OFF", "FALSE"}:
        return False
    raise ValueError(f"Could not parse boolean response: {response!r}")


def _parse_bool_list(response: str) -> tuple[bool, ...]:
    stripped = response.strip()
    if not stripped:
        return ()
    return tuple(_parse_bool(item) for item in stripped.split(","))


def _trigger_source(source: str) -> str:
    normalized = source.strip().upper()
    aliases = {
        "IMMEDIATE": "IMM",
        "IMM": "IMM",
        "BUS": "BUS",
        "PIN1": "PIN1",
        "PIN2": "PIN2",
        "PIN3": "PIN3",
        "EXT": "EXT",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("trigger source must be BUS, IMM, PIN1, PIN2, PIN3, or EXT") from exc


def _trigger_mode(mode: str) -> str:
    normalized = mode.strip().upper()
    if normalized not in {"FIX", "STEP", "LIST"}:
        raise ValueError("trigger mode must be FIX, STEP, or LIST")
    return normalized


def _validate_list_values(values: tuple[float, ...], label: str) -> None:
    if not values:
        raise ValueError(f"LIST {label} requires at least one step")
    if len(values) > 100:
        raise ValueError("LIST supports at most 100 steps")
    for value in values:
        float(value)


def _validate_dwell_values(values: tuple[float, ...]) -> None:
    _validate_list_values(values, "dwell")
    for dwell in values:
        if dwell < 0.01 or dwell > 3600:
            raise ValueError("LIST dwell values must be between 0.01 and 3600 seconds")


def _validate_bool_list(values: tuple[bool, ...], label: str) -> None:
    if not values:
        raise ValueError(f"LIST:TOUT:{label} requires at least one step")
    if len(values) > 100:
        raise ValueError("LIST supports at most 100 steps")


def _validate_parallel_lists(
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    begin_outputs: tuple[bool, ...] | None,
    end_outputs: tuple[bool, ...] | None,
) -> None:
    _validate_list_values(voltages, "voltage")
    _validate_list_values(currents, "current")
    _validate_dwell_values(dwell)
    length = len(voltages)
    for label, values in {
        "current": currents,
        "dwell": dwell,
        "BOST": begin_outputs,
        "EOST": end_outputs,
    }.items():
        if values is not None and len(values) != length:
            raise ValueError(f"LIST {label} length must match voltage length")
