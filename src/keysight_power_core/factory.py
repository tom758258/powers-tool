"""Driver selection and construction."""

from __future__ import annotations

from dataclasses import dataclass

from keysight_power_core.drivers.base import DriverCapabilities
from keysight_power_core.drivers.e36312a import E36312APowerSupply
from keysight_power_core.drivers.e3646a import E3646APowerSupply
from keysight_power_core.drivers.edu36311a import EDU36311APowerSupply
from keysight_power_core.drivers.generic_scpi import ChannelStrategy, GenericScpiPowerSupply
from keysight_power_core.core import UnsupportedModelError
from keysight_power_core.models import (
    DE_SCOPED_MODELS,
    IdnInfo,
    ModelInfo,
    de_scoped_model_message,
    lookup_model,
    parse_idn,
)
from keysight_power_core.safety import SafetyLimits
from keysight_power_core.transport import SessionLike

MODEL_DRIVERS: dict[str, type[GenericScpiPowerSupply]] = {
    "E36312A": E36312APowerSupply,
    "E3646A": E3646APowerSupply,
    "EDU36311A": EDU36311APowerSupply,
}


@dataclass(frozen=True)
class DriverSelection:
    """Result of selecting a driver for a parsed IDN response."""

    idn: IdnInfo
    model_info: ModelInfo | None
    driver_class: type[GenericScpiPowerSupply]
    reason: str

    @property
    def capabilities(self) -> DriverCapabilities:
        """Return the selected driver's conservative capability metadata."""

        return self.driver_class.capabilities


def select_driver(idn: str | IdnInfo) -> DriverSelection:
    """Select the safest available driver for an IDN response."""

    parsed_idn = parse_idn(idn) if isinstance(idn, str) else idn
    parsed_model = parsed_idn.model.strip().upper() if parsed_idn.model else None
    if parsed_idn.parse_ok and parsed_model in DE_SCOPED_MODELS:
        raise UnsupportedModelError(de_scoped_model_message(parsed_model))

    model_info = lookup_model(parsed_idn.model) if parsed_idn.parse_ok else None

    if not parsed_idn.parse_ok:
        reason = "malformed_idn_generic_fallback"
        driver_class = GenericScpiPowerSupply
    elif model_info is None:
        reason = "unknown_model_generic_fallback"
        driver_class = GenericScpiPowerSupply
    elif model_info.model in MODEL_DRIVERS:
        reason = "model_specific_driver"
        driver_class = MODEL_DRIVERS[model_info.model]
    else:
        reason = "known_model_generic_fallback"
        driver_class = GenericScpiPowerSupply

    return DriverSelection(
        idn=parsed_idn,
        model_info=model_info,
        driver_class=driver_class,
        reason=reason,
    )


def create_power_supply(
    session: SessionLike,
    idn: str | IdnInfo,
    *,
    channel_strategy: ChannelStrategy | None = None,
    safety_limits: SafetyLimits | None = None,
) -> GenericScpiPowerSupply:
    """Create a power-supply driver around an already-opened session."""

    selection = select_driver(idn)
    return selection.driver_class(
        session,
        channel_strategy=channel_strategy,
        safety_limits=safety_limits,
    )
