"""Keysight EDU36311A driver foundation."""

from __future__ import annotations

from keysight_power_core.drivers.base import DriverCapabilities
from keysight_power_core.electrical_ratings import EDU36311A_ELECTRICAL_RATINGS
from keysight_power_core.drivers.generic_scpi import (
    ChannelListStrategy,
    ChannelStrategy,
    GenericScpiPowerSupply,
)
from keysight_power_core.safety import SafetyLimits
from keysight_power_core.transport import SessionLike


class EDU36311APowerSupply(GenericScpiPowerSupply):
    """EDU36311A SCPI driver using channel-list syntax for output channels."""

    capabilities = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
        electrical_ratings=EDU36311A_ELECTRICAL_RATINGS,
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

    def set_triggered_voltage(self, *, channel: int, voltage: float) -> None:
        self._require_output_channel(channel)
        self._validate_driver_setpoint(channel=channel, voltage=voltage)
        self._session.write(f"VOLT:TRIG {_format_number(voltage)},(@{channel})")

    def set_triggered_current(self, *, channel: int, current: float) -> None:
        self._require_output_channel(channel)
        self._validate_driver_setpoint(channel=channel, current=current)
        self._session.write(f"CURR:TRIG {_format_number(current)},(@{channel})")

    def set_voltage_trigger_mode_step(self, channel: int) -> None:
        self._require_output_channel(channel)
        self._session.write(f"VOLT:MODE STEP,(@{channel})")

    def set_current_trigger_mode_step(self, channel: int) -> None:
        self._require_output_channel(channel)
        self._session.write(f"CURR:MODE STEP,(@{channel})")

    def set_output_trigger_source(self, *, channel: int, source: str) -> None:
        self._require_output_channel(channel)
        self._session.write(f"TRIG:SOUR {_trigger_source(source)},(@{channel})")

    def initiate_output_trigger(self, channel: int) -> None:
        self._require_output_channel(channel)
        self._session.write(f"INIT (@{channel})")

    def abort_output_trigger(self, channel: int) -> None:
        self._require_output_channel(channel)
        self._session.write(f"ABOR (@{channel})")

    def fire_bus_trigger(self) -> None:
        self._session.write("*TRG")

    def prepare_operation_complete_wait(self) -> None:
        self._session.write("*CLS")
        self._session.write("*ESE 1")
        self._session.write("*OPC")

    def operation_complete_event(self) -> bool:
        response = self._session.query("*ESR?").strip()
        try:
            return bool(int(float(response)) & 1)
        except ValueError as exc:
            raise ValueError(f"Could not parse *ESR? response: {response!r}") from exc

    def _require_output_channel(self, channel: int) -> None:
        if channel not in self.capabilities.channels:
            raise ValueError("trigger output channel must be 1, 2, or 3")


def _format_number(value: float) -> str:
    return format(value, ".12g")


def _trigger_source(source: str) -> str:
    normalized = source.strip().upper()
    aliases = {
        "IMMEDIATE": "IMM",
        "IMM": "IMM",
        "BUS": "BUS",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("trigger source must be BUS or IMM") from exc
