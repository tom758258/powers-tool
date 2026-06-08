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
        real_measure_channels=(1,),
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
