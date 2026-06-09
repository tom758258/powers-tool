"""Keysight E36312A driver foundation."""

from __future__ import annotations

from keysight_power.drivers.base import DriverCapabilities
from keysight_power.drivers.generic_scpi import (
    ChannelListStrategy,
    ChannelStrategy,
    GenericScpiPowerSupply,
)
from keysight_power.safety import SafetyLimits
from keysight_power.transport import SessionLike


class E36312APowerSupply(GenericScpiPowerSupply):
    """E36312A SCPI driver using channel-list syntax for output channels."""

    capabilities = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
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

        if pin not in (1, 2, 3):
            raise ValueError("trigger output pin must be 1, 2, or 3")
        polarity_command = _trigger_polarity_command(polarity)
        self._session.write(f"DIG:PIN{pin}:FUNC TOUT")
        self._session.write(f"DIG:PIN{pin}:POL {polarity_command}")

    def enable_trigger_output_bus(self, enabled: bool = True) -> None:
        """Enable or disable BUS-triggered trigger output pulses."""

        self._session.write(f"DIG:TOUT:BUS {'ON' if enabled else 'OFF'}")

    def set_triggered_voltage(self, *, channel: int, voltage: float) -> None:
        """Program a triggered voltage level for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"VOLT:TRIG {_format_number(voltage)},(@{channel})")

    def set_triggered_current(self, *, channel: int, current: float) -> None:
        """Program a triggered current level for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"CURR:TRIG {_format_number(current)},(@{channel})")

    def set_voltage_trigger_mode_step(self, channel: int) -> None:
        """Set voltage transient mode to STEP for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"VOLT:MODE STEP,(@{channel})")

    def set_current_trigger_mode_step(self, channel: int) -> None:
        """Set current transient mode to STEP for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"CURR:MODE STEP,(@{channel})")

    def configure_output_trigger_source_bus(self, channel: int) -> None:
        """Select BUS as the output trigger source for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"TRIG:SOUR BUS,(@{channel})")

    def initiate_output_trigger(self, channel: int) -> None:
        """Initiate the output trigger system for one channel."""

        self._require_output_channel(channel)
        self._session.write(f"INIT (@{channel})")

    def trigger_pulse(self, *, channel: int) -> None:
        """Emit a BUS trigger pulse."""

        self.initiate_output_trigger(channel)
        self._session.write("*TRG")

    def _require_output_channel(self, channel: int) -> None:
        if channel not in self.capabilities.channels:
            raise ValueError("trigger output channel must be 1, 2, or 3")


def _trigger_polarity_command(polarity: str) -> str:
    normalized = polarity.strip().lower()
    if normalized == "positive":
        return "POS"
    if normalized == "negative":
        return "NEG"
    raise ValueError("trigger polarity must be positive or negative")


def _format_number(value: float) -> str:
    return format(value, ".12g")
