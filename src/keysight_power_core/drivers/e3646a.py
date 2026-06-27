"""Keysight E3646A read-only driver foundation."""

from __future__ import annotations

from keysight_power_core.drivers.base import Channel, DriverCapabilities
from keysight_power_core.drivers.generic_scpi import (
    ChannelStrategy,
    GenericScpiPowerSupply,
)
from keysight_power_core.safety import SafetyLimits
from keysight_power_core.transport import SessionLike


class E3646APowerSupply(GenericScpiPowerSupply):
    """E3646A SCPI driver using INST:NSEL channel preselection."""

    capabilities = DriverCapabilities(
        channels=(1, 2),
        simulated_measure_channels=(1, 2),
        real_measure_channels=(1, 2),
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
            channel_strategy=channel_strategy,
            safety_limits=safety_limits,
        )

    def set_voltage(self, *, channel: Channel = None, voltage: float) -> None:
        raise NotImplementedError("E3646A output writes are disabled in read-only support")

    def set_current_limit(self, *, channel: Channel = None, current: float) -> None:
        raise NotImplementedError("E3646A output writes are disabled in read-only support")

    def output_on(self, *, channel: Channel = None) -> None:
        raise NotImplementedError("E3646A output writes are disabled in read-only support")

    def output_off(self, *, channel: Channel = None) -> None:
        raise NotImplementedError("E3646A output writes are disabled in read-only support")

    def _query(self, command: str, *, channel: Channel) -> str:
        selected_channel = _e3646a_channel(channel)
        previous_channel = self._selected_channel()
        try:
            self._session.write(f"INST:NSEL {selected_channel}")
            return self._session.query(command).strip()
        finally:
            if previous_channel in (1, 2):
                try:
                    self._session.write(f"INST:NSEL {previous_channel}")
                except Exception:
                    pass

    def _selected_channel(self) -> int | None:
        try:
            response = self._session.query("INST:NSEL?").strip()
            return int(float(response))
        except Exception:
            return None


def _e3646a_channel(channel: Channel) -> int:
    if channel in (1, "1"):
        return 1
    if channel in (2, "2"):
        return 2
    raise ValueError("E3646A channel must be 1 or 2")
