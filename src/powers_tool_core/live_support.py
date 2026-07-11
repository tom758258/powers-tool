"""Core-owned enforcement for exact live support scopes."""

from __future__ import annotations

from typing import Iterable

from powers_tool_core.core import OperationRequest, SequenceRequest, TriggerRequest
from powers_tool_core.core import UnsupportedModelError
from powers_tool_core.identity import IdentityResolutionError, resolve_physical_model_identity
from powers_tool_core.models import DE_SCOPED_MODEL_IDS, de_scoped_model_message, parse_idn
from powers_tool_core.support_policy import (
    CommandLiveSupportScope,
    DE_SCOPED_POLICY_MODELS,
    LiveSupportPolicyError,
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
    if normalized_model in DE_SCOPED_POLICY_MODELS:
        resolved = resolve_physical_model_identity("KEYSIGHT", normalized_model)
        raise UnsupportedModelError(de_scoped_model_message(resolved.model_id))
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
        _policy_model_from_idn(idn_raw, command or request.command),
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
        _policy_model_from_idn(idn_raw, command or request.command),
        command=command,
        feature_requirements=feature_requirements,
    )


def _policy_model_from_idn(idn_raw: str, command: str) -> str | None:
    """Resolve live identity before entering the P3-owned policy-name bridge."""

    parsed = parse_idn(idn_raw)
    if is_live_support_policy_exempt(command):
        return parsed.model
    try:
        resolved = resolve_physical_model_identity(parsed.manufacturer, parsed.model)
    except IdentityResolutionError as exc:
        if exc.reason == "unknown_model" and parsed.model:
            model = parsed.model.strip().upper()
            message = f"unknown live support-policy model {model!r}; model={model}"
        else:
            message = (
                "connected instrument manufacturer and model do not resolve "
                "to a supported physical identity"
            )
        raise LiveSupportPolicyError(message) from exc
    if resolved.model_id in DE_SCOPED_MODEL_IDS:
        raise UnsupportedModelError(de_scoped_model_message(resolved.model_id))
    return resolved.canonical_model
