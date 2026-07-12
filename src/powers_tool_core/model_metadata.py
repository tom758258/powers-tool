"""Frontend-safe metadata for Product-active physical models."""

from __future__ import annotations

from typing import Any, Iterable

from powers_tool_core import capabilities
from powers_tool_core.electrical_ratings import ratings_for_model_id
from powers_tool_core.factory import MODEL_DRIVERS
from powers_tool_core.identity import IDENTITY_INDEXES
from powers_tool_core.models import PRODUCT_ACTIVE_MODEL_IDS, REGISTERED_MODELS
from powers_tool_core.setpoint_ranges import setpoint_ranges_for_model_id
from powers_tool_core.support_policy import live_support_policy_metadata


OUTPUT_CONTROL_SCOPE_BY_MODEL_ID = {
    "keysight-e36312a": "per_channel",
    "keysight-edu36311a": "per_channel",
    "keysight-e3646a": "global",
}


def product_active_model_metadata(
    commands: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Return complete public metadata keyed by canonical physical model ID."""

    command_names = set(commands)
    metadata: dict[str, dict[str, Any]] = {}
    for model_id in sorted(PRODUCT_ACTIVE_MODEL_IDS):
        model = REGISTERED_MODELS.get(model_id)
        driver = MODEL_DRIVERS.get(model_id)
        output_scope = OUTPUT_CONTROL_SCOPE_BY_MODEL_ID.get(model_id)
        setpoint_ranges = setpoint_ranges_for_model_id(model_id)
        if model is None:
            raise ValueError(f"{model_id}: missing registered model metadata")
        if driver is None:
            raise ValueError(f"{model_id}: missing model-specific driver metadata")
        if output_scope not in {"per_channel", "global"}:
            raise ValueError(f"{model_id}: missing output-control scope metadata")
        if setpoint_ranges is None:
            raise ValueError(f"{model_id}: missing setpoint-range metadata")
        identity = model.identity
        vendor = IDENTITY_INDEXES.vendors_by_id[identity.vendor_id]
        ratings = ratings_for_model_id(model_id)
        metadata[model_id] = {
            "model_id": identity.model_id,
            "vendor_id": identity.vendor_id,
            "vendor_display_name": vendor.display_name,
            "model_name": identity.canonical_model,
            "display_name": identity.display_name,
            "channels": list(driver.capabilities.channels),
            "output_control_scope": output_scope,
            "command_support": {
                command: dict(entry)
                for command, entry in capabilities.command_support(model_id).items()
                if command in command_names
            },
            "live_support": live_support_policy_metadata(model_id, command_names),
            "electrical_ratings": ratings.to_dict() if ratings is not None else None,
            "setpoint_ranges": setpoint_ranges.to_dict(),
        }
    return metadata


def validate_product_active_model_metadata() -> None:
    """Fail closed when a Product-active model lacks required public metadata."""

    metadata = product_active_model_metadata(())
    if set(metadata) != set(PRODUCT_ACTIVE_MODEL_IDS):
        raise ValueError("Product-active public model metadata inventory drift")
