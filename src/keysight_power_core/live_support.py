"""Core-owned enforcement for exact live support scopes."""

from __future__ import annotations

from typing import Iterable

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
    feature_requirements: Iterable[tuple[str, str]] = (),
) -> CommandLiveSupportScope | None:
    """Compatibility wrapper for callers that intentionally require product mode."""

    return _enforce_live_support(
        request,
        detected_model,
        command=command,
        feature_requirements=feature_requirements,
        support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
    )


def enforce_live_support(
    request: _Request,
    detected_model: str | None,
    *,
    command: str | None = None,
    feature_requirements: Iterable[tuple[str, str]] = (),
) -> CommandLiveSupportScope | None:
    """Fail closed against the detected model and request exact runtime scope."""

    return _enforce_live_support(
        request,
        detected_model,
        command=command,
        feature_requirements=feature_requirements,
        support_policy_mode=request.runtime.support_policy_mode,
    )


def _enforce_live_support(
    request: _Request,
    detected_model: str | None,
    *,
    command: str | None,
    feature_requirements: Iterable[tuple[str, str]],
    support_policy_mode: str,
) -> CommandLiveSupportScope | None:
    """Apply the exact policy with an explicit mode source."""

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
        support_policy_mode=support_policy_mode,
        feature_requirements=feature_requirements,
    )


def enforce_product_live_support_for_idn(
    request: _Request,
    idn_raw: str,
    *,
    command: str | None = None,
    feature_requirements: Iterable[tuple[str, str]] = (),
) -> CommandLiveSupportScope | None:
    """Parse a live IDN response before applying product exact-scope policy."""

    return enforce_product_live_support(
        request,
        parse_idn(idn_raw).model,
        command=command,
        feature_requirements=feature_requirements,
    )


def enforce_live_support_for_idn(
    request: _Request,
    idn_raw: str,
    *,
    command: str | None = None,
    feature_requirements: Iterable[tuple[str, str]] = (),
) -> CommandLiveSupportScope | None:
    """Parse a live IDN response before applying request-mode exact policy."""

    return enforce_live_support(
        request,
        parse_idn(idn_raw).model,
        command=command,
        feature_requirements=feature_requirements,
    )
