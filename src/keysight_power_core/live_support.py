"""Core-owned product enforcement for exact live support scopes."""

from __future__ import annotations

from keysight_power_core.core import OperationRequest, SequenceRequest, TriggerRequest
from keysight_power_core.core import UnsupportedModelError
from keysight_power_core.models import DE_SCOPED_MODELS, de_scoped_model_message, parse_idn
from keysight_power_core.support_policy import (
    CommandLiveSupportScope,
    SUPPORT_POLICY_MODE_PRODUCT,
    ensure_live_scope_supported,
    is_live_support_policy_exempt,
)

_Request = OperationRequest | TriggerRequest | SequenceRequest


def enforce_product_live_support(
    request: _Request,
    detected_model: str | None,
    *,
    command: str | None = None,
) -> CommandLiveSupportScope | None:
    """Fail closed against the detected model and the exact runtime scope."""

    effective_command = command or request.command
    if is_live_support_policy_exempt(effective_command):
        return None
    normalized_model = (detected_model or "").strip().upper()
    if normalized_model in DE_SCOPED_MODELS:
        raise UnsupportedModelError(de_scoped_model_message(normalized_model))
    return ensure_live_scope_supported(
        model=normalized_model,
        command=effective_command,
        transport=request.runtime.resource,
        backend=request.runtime.backend,
        support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
    )


def enforce_product_live_support_for_idn(
    request: _Request,
    idn_raw: str,
    *,
    command: str | None = None,
) -> CommandLiveSupportScope | None:
    """Parse a live IDN response before applying product exact-scope policy."""

    return enforce_product_live_support(request, parse_idn(idn_raw).model, command=command)
