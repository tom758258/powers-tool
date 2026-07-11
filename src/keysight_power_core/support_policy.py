"""Exact live support-policy metadata for future Core enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from keysight_power_core.capabilities import command_support, known_capability_commands
from keysight_power_core.core import CoreValidationError
from keysight_power_core.model_resolution import canonical_model_profile
from keysight_power_core.models import (
    CANDIDATE_MODELS,
    DE_SCOPED_MODELS,
    PRODUCT_ACTIVE_MODELS,
    resource_interface,
)
from keysight_power_core.support_features import (
    FEATURE_KIND_SEQUENCE_ACTION,
    FEATURE_KIND_TRIGGER_SOURCE,
    REAL_TRIGGER_SOURCES,
    normalize_real_trigger_source,
    normalize_sequence_action,
    supported_sequence_actions,
)

SUPPORT_POLICY_MODE_PRODUCT = "product"
SUPPORT_POLICY_MODE_VALIDATION = "validation"

VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL = "not_supported_by_model"
VALIDATION_STATUS_PROFILE_VALIDATED = "profile_validated"
VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE = "live_validated_full_suite"
VALIDATION_STATUS_TRANSPORT_PENDING = "transport_pending"
VALIDATION_STATUS_FEATURE_PENDING = "feature_pending"

TRANSPORT_USB = "usb"
TRANSPORT_TCPIP = "tcpip"
TRANSPORT_ASRL = "asrl"
TRANSPORT_GPIB = "gpib"
TRANSPORT_UNKNOWN = "unknown"

BACKEND_SYSTEM_VISA = "system_visa"
BACKEND_PYVISA_PY = "pyvisa_py"
BACKEND_CUSTOM_VISA = "custom_visa"

ACTIVE_LIVE_POLICY_MODELS = PRODUCT_ACTIVE_MODELS | CANDIDATE_MODELS
EXEMPT_LIVE_DIAGNOSTIC_COMMANDS = frozenset(
    {"list-resources", "verify", "identify", "error", "clear"}
)
PURE_OFFLINE_COMMANDS = frozenset(
    {"snapshot-diff", "hardware-report", "safety inspect"}
)

_POLICY_MODES = frozenset(
    {SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION}
)
_COMMAND_POLICY_STATUSES = frozenset(
    {
        VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
        VALIDATION_STATUS_PROFILE_VALIDATED,
    }
)
_SCOPE_STATUSES = frozenset(
    {
        VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        VALIDATION_STATUS_TRANSPORT_PENDING,
    }
)
_FEATURE_STATUSES = frozenset(
    {
        VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        VALIDATION_STATUS_FEATURE_PENDING,
        VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
    }
)
_TRANSPORTS = frozenset(
    {TRANSPORT_USB, TRANSPORT_TCPIP, TRANSPORT_ASRL, TRANSPORT_GPIB, TRANSPORT_UNKNOWN}
)
_BACKENDS = frozenset(
    {BACKEND_SYSTEM_VISA, BACKEND_PYVISA_PY, BACKEND_CUSTOM_VISA}
)
_ALLOW_PRODUCT = frozenset({VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE})
_ALLOW_VALIDATION = _ALLOW_PRODUCT | {
    VALIDATION_STATUS_TRANSPORT_PENDING,
}
_PENDING_STATUSES = frozenset({VALIDATION_STATUS_TRANSPORT_PENDING})


class LiveSupportPolicyError(CoreValidationError):
    """Raised when an exact live support-policy decision rejects a scope."""


@dataclass(frozen=True)
class CommandFeatureSupportScope:
    feature_kind: str
    feature_value: str
    validation_status: str
    evidence: str | None = None
    artifact: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class CommandLiveSupportScope:
    validation_status: str
    transport_scope: str
    backend_scope: str
    evidence: str | None = None
    artifact: str | None = None
    note: str | None = None
    feature_scopes: tuple[CommandFeatureSupportScope, ...] = ()


@dataclass(frozen=True)
class CommandSupportPolicy:
    command: str
    validation_status: str
    scopes: tuple[CommandLiveSupportScope, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class ModelSupportPolicy:
    model: str
    commands: tuple[CommandSupportPolicy, ...]


def normalize_transport(resource_or_transport: str | None) -> str:
    """Return the canonical transport for a VISA resource or transport label."""

    if resource_or_transport is None or not resource_or_transport.strip():
        return TRANSPORT_UNKNOWN
    interface = resource_interface(resource_or_transport)
    return {
        "USB": TRANSPORT_USB,
        "TCPIP": TRANSPORT_TCPIP,
        "ASRL": TRANSPORT_ASRL,
        "GPIB": TRANSPORT_GPIB,
    }.get(interface, TRANSPORT_UNKNOWN)


def normalize_backend(backend: str | None) -> str:
    """Return the canonical backend without changing the runtime backend value."""

    normalized = (backend or "").strip().lower()
    if not normalized:
        return BACKEND_SYSTEM_VISA
    if normalized in {"@py", BACKEND_PYVISA_PY}:
        return BACKEND_PYVISA_PY
    if normalized == BACKEND_SYSTEM_VISA:
        return BACKEND_SYSTEM_VISA
    if normalized == BACKEND_CUSTOM_VISA:
        return BACKEND_CUSTOM_VISA
    return BACKEND_CUSTOM_VISA


def normalize_support_feature_value(feature_kind: str, feature_value: str) -> str:
    """Return the canonical value for a supported live-policy feature kind."""

    normalized_kind = (feature_kind or "").strip().lower()
    try:
        if normalized_kind == FEATURE_KIND_SEQUENCE_ACTION:
            return normalize_sequence_action(feature_value)
        if normalized_kind == FEATURE_KIND_TRIGGER_SOURCE:
            return normalize_real_trigger_source(feature_value)
    except ValueError as exc:
        raise LiveSupportPolicyError(str(exc)) from exc
    raise LiveSupportPolicyError(f"unsupported live support feature kind {feature_kind!r}")


def is_live_support_policy_exempt(command: str) -> bool:
    """Return whether a diagnostic or pure offline utility bypasses live policy."""

    normalized = _canonical_command(command)
    return normalized in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS | PURE_OFFLINE_COMMANDS


def command_live_support(
    model: str,
    command: str,
    *,
    registry: tuple[ModelSupportPolicy, ...] | None = None,
) -> CommandSupportPolicy:
    """Return one explicit command policy, failing closed for unknown metadata."""

    model_policy = _model_policy(model, registry=registry)
    normalized_command = _canonical_command(command)
    for policy in model_policy.commands:
        if policy.command == normalized_command:
            return policy
    raise LiveSupportPolicyError(
        _rejection_message(
            model=model_policy.model,
            command=normalized_command,
            transport=TRANSPORT_UNKNOWN,
            backend=BACKEND_SYSTEM_VISA,
            mode="unknown",
            status="missing_command_metadata",
            reason="the command has no explicit live support-policy decision",
        )
    )


def command_live_support_matrix(
    model: str,
    *,
    registry: tuple[ModelSupportPolicy, ...] | None = None,
) -> Mapping[str, CommandSupportPolicy]:
    """Return the immutable command-policy matrix for an active model."""

    model_policy = _model_policy(model, registry=registry)
    return MappingProxyType({policy.command: policy for policy in model_policy.commands})


def find_live_support_scope(
    *,
    model: str,
    command: str,
    transport: str,
    backend: str,
    registry: tuple[ModelSupportPolicy, ...] | None = None,
) -> CommandLiveSupportScope | None:
    """Return an exact transport/backend scope; wildcard matching is forbidden."""

    try:
        policy = command_live_support(model, command, registry=registry)
    except LiveSupportPolicyError:
        return None
    normalized_transport = normalize_transport(transport)
    normalized_backend = normalize_backend(backend)
    for scope in policy.scopes:
        if (
            scope.transport_scope == normalized_transport
            and scope.backend_scope == normalized_backend
        ):
            return scope
    return None


def find_feature_support(
    scope: CommandLiveSupportScope,
    feature_kind: str,
    feature_value: str,
) -> CommandFeatureSupportScope | None:
    """Return one exact normalized feature entry; wildcard matching is forbidden."""

    normalized_kind = (feature_kind or "").strip().lower()
    normalized_value = normalize_support_feature_value(normalized_kind, feature_value)
    matches = [
        feature
        for feature in scope.feature_scopes
        if feature.feature_kind == normalized_kind
        and feature.feature_value == normalized_value
    ]
    if len(matches) > 1:
        raise LiveSupportPolicyError(
            "duplicate live support feature metadata: "
            f"transport={scope.transport_scope}, backend={scope.backend_scope}, "
            f"feature_kind={normalized_kind}, feature_value={normalized_value}"
        )
    return matches[0] if matches else None


def live_support_policy_metadata(
    model: str,
    commands: Iterable[str] | None = None,
) -> dict[str, object]:
    """Return a safe JSON-ready model-level live-support projection."""

    normalized_model = _public_projection_model(model)
    command_names = _public_projection_commands(commands)
    if normalized_model == "GENERIC":
        return {
            "model": normalized_model,
            "live_capable": False,
            "fallback_only": True,
            "commands": {
                command: _generic_public_command(command)
                for command in command_names
            },
        }

    matrix = command_live_support_matrix(normalized_model)
    return {
        "model": normalized_model,
        "live_capable": True,
        "fallback_only": False,
        "commands": {
            command: _public_command_policy(
                model=normalized_model,
                command=command,
                policy=matrix.get(command),
            )
            for command in command_names
        },
    }


def exact_live_support_metadata(
    *,
    model: str,
    resource: str | None,
    backend: str | None,
    commands: Iterable[str] | None = None,
) -> dict[str, object]:
    """Return a safe JSON-ready Product-mode projection for one exact scope."""

    model_metadata = live_support_policy_metadata(model, commands)
    normalized_model = str(model_metadata["model"])
    if normalized_model == "GENERIC":
        raise LiveSupportPolicyError(
            "model 'GENERIC' has no active live support-policy metadata"
        )
    transport_scope = normalize_transport(resource)
    backend_scope = normalize_backend(backend)
    exact_commands: dict[str, dict[str, object]] = {}
    for command, model_entry in model_metadata["commands"].items():
        entry = dict(model_entry)
        scopes = entry.pop("scopes", [])
        if entry["offline_only"]:
            reason = "Offline utility; live exact scope is not applicable."
            entry.update(
                {
                    "exact_scope_validation_status": None,
                    "product_open": False,
                    "disabled_reason": reason,
                    "support_reason": reason,
                }
            )
        elif entry["policy_exempt"]:
            entry.update(
                {
                    "exact_scope_validation_status": None,
                    "product_open": True,
                    "disabled_reason": None,
                    "support_reason": (
                        "Identity/status diagnostic; exact model feature scope is not required."
                    ),
                }
            )
        elif not entry["profile_supported"]:
            entry.update(
                {
                    "exact_scope_validation_status": None,
                    "product_open": False,
                    "disabled_reason": entry["disabled_reason"],
                    "support_reason": entry["disabled_reason"],
                }
            )
        else:
            matching_scope = next(
                (
                    scope
                    for scope in scopes
                    if scope["transport_scope"] == transport_scope
                    and scope["backend_scope"] == backend_scope
                ),
                None,
            )
            if matching_scope is None:
                reason = (
                    "No product-open live scope is registered for "
                    f"{_transport_display(transport_scope)} / {_backend_display(backend_scope)}."
                )
                entry.update(
                    {
                        "exact_scope_validation_status": None,
                        "product_open": False,
                        "disabled_reason": reason,
                        "support_reason": reason,
                    }
                )
            else:
                exact_status = matching_scope["validation_status"]
                product_open = exact_status in _ALLOW_PRODUCT
                reason = _scope_support_reason(
                    status=exact_status,
                    transport=transport_scope,
                    backend=backend_scope,
                )
                entry.update(
                    {
                        "exact_scope_validation_status": exact_status,
                        "product_open": product_open,
                        "disabled_reason": None if product_open else reason,
                        "support_reason": reason,
                        **(
                            {"features": matching_scope["features"]}
                            if "features" in matching_scope
                            else {}
                        ),
                    }
                )
        exact_commands[command] = entry
    return {
        "evaluated": True,
        "model": normalized_model,
        "transport_scope": transport_scope,
        "backend_scope": backend_scope,
        "policy_mode": SUPPORT_POLICY_MODE_PRODUCT,
        "commands": exact_commands,
    }


def ensure_live_scope_supported(
    *,
    model: str,
    command: str,
    transport: str,
    backend: str,
    support_policy_mode: str,
    feature_requirements: Iterable[tuple[str, str]] = (),
    registry: tuple[ModelSupportPolicy, ...] | None = None,
) -> CommandLiveSupportScope:
    """Return an allowed exact scope or reject it with fail-closed semantics."""

    normalized_command = _canonical_command(command)
    normalized_transport = normalize_transport(transport)
    normalized_backend = normalize_backend(backend)
    normalized_mode = (support_policy_mode or "").strip().lower()
    context = {
        "model": (model or "").strip().upper() or "UNKNOWN",
        "command": normalized_command,
        "transport": normalized_transport,
        "backend": normalized_backend,
        "mode": normalized_mode or "unknown",
    }
    if normalized_mode not in _POLICY_MODES:
        raise LiveSupportPolicyError(
            _rejection_message(
                **context,
                status="unknown_policy_mode",
                reason="the support-policy mode is not recognized",
            )
        )
    try:
        policy = command_live_support(model, normalized_command, registry=registry)
    except LiveSupportPolicyError as exc:
        raise LiveSupportPolicyError(
            _rejection_message(
                **context,
                status="missing_or_unknown_metadata",
                reason=str(exc),
            )
        ) from exc
    if policy.validation_status not in _COMMAND_POLICY_STATUSES:
        raise LiveSupportPolicyError(
            _rejection_message(
                **context,
                status=policy.validation_status,
                reason="the command-policy validation status is not valid for a command policy",
            )
        )
    if policy.validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL:
        raise LiveSupportPolicyError(
            _rejection_message(
                **context,
                status=policy.validation_status,
                reason=policy.note or "the model/profile does not support this command",
            )
        )
    scope = find_live_support_scope(
        model=model,
        command=normalized_command,
        transport=normalized_transport,
        backend=normalized_backend,
        registry=registry,
    )
    if scope is None:
        raise LiveSupportPolicyError(
            _rejection_message(
                **context,
                status=policy.validation_status,
                reason="no exact transport/backend scope is registered",
            )
        )
    allowed = _ALLOW_PRODUCT if normalized_mode == SUPPORT_POLICY_MODE_PRODUCT else _ALLOW_VALIDATION
    if scope.validation_status not in allowed:
        reason = (
            "the exact scope is not allowed in this policy mode"
            if scope.validation_status in _SCOPE_STATUSES
            else "the exact scope has an unknown validation status"
        )
        raise LiveSupportPolicyError(
            _rejection_message(
                **context,
                status=scope.validation_status,
                reason=reason,
            )
        )
    feature_allowed = (
        _ALLOW_PRODUCT
        if normalized_mode == SUPPORT_POLICY_MODE_PRODUCT
        else _ALLOW_PRODUCT | {VALIDATION_STATUS_FEATURE_PENDING}
    )
    seen_requirements: set[tuple[str, str]] = set()
    for feature_kind, feature_value in feature_requirements:
        normalized_kind = (feature_kind or "").strip().lower()
        try:
            normalized_value = normalize_support_feature_value(normalized_kind, feature_value)
        except LiveSupportPolicyError as exc:
            raise LiveSupportPolicyError(
                _rejection_message(
                    **context,
                    feature_kind=normalized_kind or "unknown",
                    feature_value=(feature_value or "").strip().lower() or "unknown",
                    status="invalid_feature_requirement",
                    reason=str(exc),
                )
            ) from exc
        feature_key = (normalized_kind, normalized_value)
        if feature_key in seen_requirements:
            continue
        seen_requirements.add(feature_key)
        feature_context = {
            **context,
            "feature_kind": normalized_kind,
            "feature_value": normalized_value,
        }
        try:
            feature = find_feature_support(scope, normalized_kind, normalized_value)
        except LiveSupportPolicyError as exc:
            raise LiveSupportPolicyError(
                _rejection_message(
                    **feature_context,
                    status="duplicate_feature_metadata",
                    reason=str(exc),
                )
            ) from exc
        if feature is None:
            raise LiveSupportPolicyError(
                _rejection_message(
                    **feature_context,
                    status="missing_feature_metadata",
                    reason="no exact feature scope is registered",
                )
            )
        if feature.validation_status not in feature_allowed:
            reason = (
                "the exact feature is not allowed in this policy mode"
                if feature.validation_status in _FEATURE_STATUSES
                else "the exact feature has an unknown validation status"
            )
            raise LiveSupportPolicyError(
                _rejection_message(
                    **feature_context,
                    status=feature.validation_status,
                    reason=reason,
                )
            )
    return scope


def validate_live_support_metadata(
    registry: tuple[ModelSupportPolicy, ...] | None = None,
    *,
    command_inventory: Iterable[str] | None = None,
) -> None:
    """Validate registry structure and its consistency with current capabilities."""

    selected_registry = LIVE_SUPPORT_POLICY_REGISTRY if registry is None else registry
    expected_commands = (
        _policy_governed_command_inventory()
        if command_inventory is None
        else {_canonical_command(command) for command in command_inventory}
    )
    seen_models: set[str] = set()
    for model_policy in selected_registry:
        model = model_policy.model.strip().upper()
        if model_policy.model != model:
            raise ValueError(f"noncanonical model policy: {model_policy.model!r}")
        if model in seen_models:
            raise ValueError(f"duplicate model policy: {model}")
        seen_models.add(model)
        if model in DE_SCOPED_MODELS:
            raise ValueError(f"de-scoped model appears in live metadata: {model}")
        if model not in ACTIVE_LIVE_POLICY_MODELS:
            raise ValueError(f"unexpected active live policy model: {model}")
        seen_commands: set[str] = set()
        for policy in model_policy.commands:
            command = _canonical_command(policy.command)
            if policy.command != command:
                raise ValueError(f"noncanonical command policy: {model}/{policy.command!r}")
            if command in seen_commands:
                raise ValueError(f"duplicate command policy: {model}/{command}")
            seen_commands.add(command)
            if command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS:
                raise ValueError(f"exempt diagnostic entered live registry: {command}")
            if command not in expected_commands:
                raise ValueError(f"metadata command is outside current inventory: {command}")
            if policy.validation_status not in _COMMAND_POLICY_STATUSES:
                raise ValueError(
                    f"invalid command-policy validation status: {policy.validation_status}"
                )
            if (
                policy.validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL
                and policy.scopes
            ):
                raise ValueError(f"unsupported command has live scopes: {model}/{command}")
            if (
                policy.validation_status == VALIDATION_STATUS_PROFILE_VALIDATED
                and not policy.scopes
                and not policy.note
            ):
                raise ValueError(f"profile-supported command lacks exact-scope reason: {model}/{command}")
            seen_scopes: set[tuple[str, str]] = set()
            for scope in policy.scopes:
                scope_key = (scope.transport_scope, scope.backend_scope)
                if scope_key in seen_scopes:
                    raise ValueError(f"duplicate exact scope: {model}/{command}/{scope_key}")
                seen_scopes.add(scope_key)
                if scope.validation_status not in _SCOPE_STATUSES:
                    raise ValueError(f"unknown scope validation status: {scope.validation_status}")
                if scope.transport_scope not in _TRANSPORTS:
                    raise ValueError(f"invalid transport value: {scope.transport_scope}")
                if scope.transport_scope == TRANSPORT_UNKNOWN:
                    raise ValueError(
                        f"exact live scope cannot use unknown transport: {model}/{command}/{scope_key}"
                    )
                if scope.backend_scope not in _BACKENDS:
                    raise ValueError(f"invalid backend value: {scope.backend_scope}")
                if scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
                    if not scope.evidence:
                        raise ValueError(f"validated scope lacks evidence: {model}/{command}/{scope_key}")
                    if not scope.artifact:
                        raise ValueError(f"validated scope lacks artifact: {model}/{command}/{scope_key}")
                if scope.validation_status in {
                    VALIDATION_STATUS_TRANSPORT_PENDING,
                } and not scope.note:
                    raise ValueError(f"pending scope lacks note: {model}/{command}/{scope_key}")
                expected_features = _expected_feature_inventory(model, command)
                seen_features: set[tuple[str, str]] = set()
                for feature in scope.feature_scopes:
                    normalized_kind = feature.feature_kind.strip().lower()
                    if feature.feature_kind != normalized_kind:
                        raise ValueError(
                            f"noncanonical feature kind: {model}/{command}/{scope_key}/{feature.feature_kind!r}"
                        )
                    if normalized_kind not in {
                        FEATURE_KIND_SEQUENCE_ACTION,
                        FEATURE_KIND_TRIGGER_SOURCE,
                    }:
                        raise ValueError(f"unsupported feature kind: {normalized_kind}")
                    try:
                        normalized_value = normalize_support_feature_value(
                            normalized_kind, feature.feature_value
                        )
                    except LiveSupportPolicyError as exc:
                        raise ValueError(str(exc)) from exc
                    if feature.feature_value != normalized_value:
                        raise ValueError(
                            "noncanonical feature value: "
                            f"{model}/{command}/{scope_key}/{feature.feature_value!r}"
                        )
                    feature_key = (normalized_kind, normalized_value)
                    if feature_key in seen_features:
                        raise ValueError(
                            f"duplicate feature scope: {model}/{command}/{scope_key}/{feature_key}"
                        )
                    seen_features.add(feature_key)
                    if feature_key not in expected_features:
                        raise ValueError(
                            f"unexpected feature scope: {model}/{command}/{scope_key}/{feature_key}"
                        )
                    if feature.validation_status not in _FEATURE_STATUSES:
                        raise ValueError(
                            f"unknown feature validation status: {feature.validation_status}"
                        )
                    if (
                        feature.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
                        and not (feature.evidence or feature.note)
                    ):
                        raise ValueError(
                            f"validated feature lacks evidence or migration note: {model}/{command}/{scope_key}/{feature_key}"
                        )
                    if (
                        feature.validation_status == VALIDATION_STATUS_FEATURE_PENDING
                        and not feature.note
                    ):
                        raise ValueError(
                            f"pending feature lacks note: {model}/{command}/{scope_key}/{feature_key}"
                        )
                    required_status = (
                        VALIDATION_STATUS_FEATURE_PENDING
                        if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
                        else VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
                    )
                    if feature.validation_status != required_status:
                        raise ValueError(
                            "feature status does not match exact parent scope: "
                            f"{model}/{command}/{scope_key}/{feature_key}"
                        )
                missing_features = expected_features - seen_features
                if missing_features:
                    raise ValueError(
                        f"exact-scope feature inventory drift: {model}/{command}/{scope_key}/missing={sorted(missing_features)}"
                    )
        missing = expected_commands - seen_commands
        unexpected = seen_commands - expected_commands
        if missing:
            raise ValueError(f"policy-governed commands missing for {model}: {sorted(missing)}")
        if unexpected:
            raise ValueError(f"unexpected commands for {model}: {sorted(unexpected)}")
    missing_models = ACTIVE_LIVE_POLICY_MODELS - seen_models
    if missing_models:
        raise ValueError(f"active models missing from live metadata: {sorted(missing_models)}")
    unexpected_models = seen_models - ACTIVE_LIVE_POLICY_MODELS
    if unexpected_models:
        raise ValueError(f"unexpected active models in live metadata: {sorted(unexpected_models)}")


def _expected_feature_inventory(model: str, command: str) -> set[tuple[str, str]]:
    if command == "sequence":
        return {
            (FEATURE_KIND_SEQUENCE_ACTION, action)
            for action in supported_sequence_actions(model)
        }
    if command in {"trigger-step", "trigger-list"}:
        return {
            (FEATURE_KIND_TRIGGER_SOURCE, source)
            for source in REAL_TRIGGER_SOURCES
        }
    return set()


_LEGACY_BACKEND_NOTE = (
    "The legacy wrapper omitted the backend argument and used the default "
    "pyvisa.ResourceManager() system-VISA path; this does not validate pyvisa-py "
    "or a custom VISA backend."
)
_PENDING_BACKEND_NOTE = (
    "The model and command are implemented and validated over TCPIP with the "
    "system VISA backend. The TCPIP/pyvisa-py exact backend scope remains pending "
    "separate live validation."
)
_NO_EXACT_EVIDENCE_NOTE = (
    "The command is profile-supported, but no accepted full-suite live case provides "
    "an exact transport/backend scope for this command."
)
_FEATURE_BASELINE_MIGRATION_NOTE = (
    "Preserves the accepted pre-P7 command-level Product-open baseline; this is not new hardware evidence."
)
_FEATURE_PENDING_NOTE = (
    "The implemented feature remains pending with its exact TCPIP/pyvisa-py parent scope."
)

_ARTIFACTS = {
    ("E36312A", TRANSPORT_USB): ".tmp_tests/live_cli_check/20260709_153201_E36312A_USB_full",
    ("E36312A", TRANSPORT_TCPIP): ".tmp_tests/live_cli_check/20260709_201420_E36312A_LAN_full",
    ("EDU36311A", TRANSPORT_USB): ".tmp_tests/live_cli_check/20260709_151534_EDU36311A_USB_full",
    ("EDU36311A", TRANSPORT_TCPIP): ".tmp_tests/live_cli_check/20260709_200530_EDU36311A_LAN_full",
    ("E3646A", TRANSPORT_ASRL): ".tmp_tests/live_cli_check/20260709_151205_E3646A_ASRL_full",
}

_VALIDATED_COMMANDS = {
    "E36312A": frozenset(
        {
            "measure", "output-state", "read-status", "readback", "validate-readonly",
            "capabilities", "set", "output-off", "safe-off", "cycle-output", "apply",
            "ramp", "smoke-output", "ramp-list", "sequence", "protection-status",
            "protection-set", "clear-protection", "snapshot", "trigger-status",
            "trigger-step", "trigger-list", "trigger-abort",
        }
    ),
    "EDU36311A": frozenset(
        {
            "measure", "output-state", "read-status", "readback", "validate-readonly",
            "capabilities", "set", "output-off", "safe-off", "cycle-output", "apply",
            "ramp", "smoke-output", "ramp-list", "sequence", "protection-status",
            "protection-set", "clear-protection",
        }
    ),
    "E3646A": frozenset(
        {
            "measure", "output-state", "read-status", "readback", "capabilities", "set",
            "output-off", "safe-off", "cycle-output", "apply", "ramp", "smoke-output",
            "ramp-list", "sequence",
        }
    ),
}

_VALIDATED_TRANSPORTS = {
    "E36312A": (TRANSPORT_USB, TRANSPORT_TCPIP),
    "EDU36311A": (TRANSPORT_USB, TRANSPORT_TCPIP),
    "E3646A": (TRANSPORT_ASRL,),
}


def _build_registry() -> tuple[ModelSupportPolicy, ...]:
    commands = sorted(_policy_governed_command_inventory())
    model_policies: list[ModelSupportPolicy] = []
    for model in sorted(PRODUCT_ACTIVE_MODELS):
        current_support = command_support(model)
        policies: list[CommandSupportPolicy] = []
        for command in commands:
            capability = current_support.get(command)
            profile_supported = capability is not None and capability.get("real") is True
            if not profile_supported:
                policies.append(
                    CommandSupportPolicy(
                        command=command,
                        validation_status=VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
                        note="The current project model/profile does not support this command.",
                    )
                )
                continue
            scopes: list[CommandLiveSupportScope] = []
            if command in _VALIDATED_COMMANDS[model]:
                for transport in _VALIDATED_TRANSPORTS[model]:
                    artifact = _ARTIFACTS[(model, transport)]
                    scopes.append(
                        CommandLiveSupportScope(
                            validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
                            transport_scope=transport,
                            backend_scope=BACKEND_SYSTEM_VISA,
                            evidence="Accepted 2026-07-09 full-suite live validation record.",
                            artifact=artifact,
                            note=_LEGACY_BACKEND_NOTE,
                            feature_scopes=_feature_scopes_for(
                                model=model,
                                command=command,
                                validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
                            ),
                        )
                    )
                    if transport == TRANSPORT_TCPIP and model in {"E36312A", "EDU36311A"}:
                        scopes.append(
                            CommandLiveSupportScope(
                                validation_status=VALIDATION_STATUS_TRANSPORT_PENDING,
                                transport_scope=TRANSPORT_TCPIP,
                                backend_scope=BACKEND_PYVISA_PY,
                                evidence="Candidate derived from the matching accepted TCPIP/system-VISA command inventory.",
                                artifact=artifact,
                                note=_PENDING_BACKEND_NOTE,
                                feature_scopes=_feature_scopes_for(
                                    model=model,
                                    command=command,
                                    validation_status=VALIDATION_STATUS_FEATURE_PENDING,
                                ),
                            )
                        )
            policies.append(
                CommandSupportPolicy(
                    command=command,
                    validation_status=VALIDATION_STATUS_PROFILE_VALIDATED,
                    scopes=tuple(scopes),
                    note=None if scopes else _NO_EXACT_EVIDENCE_NOTE,
                )
            )
        model_policies.append(ModelSupportPolicy(model=model, commands=tuple(policies)))
    return tuple(model_policies)


def _feature_scopes_for(
    *,
    model: str,
    command: str,
    validation_status: str,
) -> tuple[CommandFeatureSupportScope, ...]:
    if command == "sequence":
        values = supported_sequence_actions(model)
        kind = FEATURE_KIND_SEQUENCE_ACTION
    elif command in {"trigger-step", "trigger-list"}:
        values = REAL_TRIGGER_SOURCES
        kind = FEATURE_KIND_TRIGGER_SOURCE
    else:
        return ()
    note = (
        _FEATURE_BASELINE_MIGRATION_NOTE
        if validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
        else _FEATURE_PENDING_NOTE
    )
    return tuple(
        CommandFeatureSupportScope(
            feature_kind=kind,
            feature_value=value,
            validation_status=validation_status,
            note=note,
        )
        for value in sorted(values)
    )


def _policy_governed_command_inventory() -> set[str]:
    return (
        known_capability_commands()
        - EXEMPT_LIVE_DIAGNOSTIC_COMMANDS
        - PURE_OFFLINE_COMMANDS
    )


def _model_policy(
    model: str,
    *,
    registry: tuple[ModelSupportPolicy, ...] | None,
) -> ModelSupportPolicy:
    try:
        normalized = canonical_model_profile(model)
    except CoreValidationError as exc:
        raise LiveSupportPolicyError(f"unknown live support-policy model {model!r}") from exc
    if normalized not in ACTIVE_LIVE_POLICY_MODELS:
        raise LiveSupportPolicyError(
            f"model {normalized!r} has no active live support-policy metadata"
        )
    selected_registry = LIVE_SUPPORT_POLICY_REGISTRY if registry is None else registry
    for policy in selected_registry:
        if policy.model == normalized:
            return policy
    raise LiveSupportPolicyError(f"model {normalized!r} is missing live support-policy metadata")


def _canonical_command(command: str) -> str:
    return (command or "").strip().lower()


def _public_projection_model(model: str) -> str:
    try:
        normalized = canonical_model_profile(model)
    except CoreValidationError as exc:
        raise LiveSupportPolicyError(
            f"unknown live support-policy model {model!r}"
        ) from exc
    if normalized == "GENERIC":
        return normalized
    if normalized not in ACTIVE_LIVE_POLICY_MODELS:
        raise LiveSupportPolicyError(
            f"model {normalized!r} has no active live support-policy metadata"
        )
    return normalized


def _public_projection_commands(commands: Iterable[str] | None) -> tuple[str, ...]:
    source = (
        known_capability_commands()
        | EXEMPT_LIVE_DIAGNOSTIC_COMMANDS
        | PURE_OFFLINE_COMMANDS
        if commands is None
        else commands
    )
    return tuple(
        sorted(
            {
                _canonical_command(command)
                for command in source
                if _canonical_command(command)
            }
        )
    )


def _public_command_policy(
    *,
    model: str,
    command: str,
    policy: CommandSupportPolicy | None,
) -> dict[str, object]:
    if command in PURE_OFFLINE_COMMANDS:
        reason = "Offline utility; live exact scope is not applicable."
        return {
            "profile_validation_status": None,
            "profile_supported": True,
            "metadata_available": True,
            "policy_exempt": False,
            "offline_only": True,
            "disabled_reason": reason,
            "support_reason": reason,
            "scopes": [],
        }
    if command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS:
        return {
            "profile_validation_status": None,
            "profile_supported": True,
            "metadata_available": True,
            "policy_exempt": True,
            "offline_only": False,
            "disabled_reason": None,
            "support_reason": (
                "Identity/status diagnostic; exact model feature scope is not required."
            ),
            "scopes": [],
        }
    if policy is None:
        reason = "Live support metadata is missing for this command."
        return {
            "profile_validation_status": None,
            "profile_supported": False,
            "metadata_available": False,
            "policy_exempt": False,
            "offline_only": False,
            "disabled_reason": reason,
            "support_reason": reason,
            "scopes": [],
        }
    profile_supported = policy.validation_status == VALIDATION_STATUS_PROFILE_VALIDATED
    reason = None if profile_supported else f"Not supported by {model}."
    return {
        "profile_validation_status": policy.validation_status,
        "profile_supported": profile_supported,
        "metadata_available": True,
        "policy_exempt": False,
        "offline_only": False,
        "disabled_reason": reason,
        "support_reason": reason,
        "scopes": [
            {
                "transport_scope": scope.transport_scope,
                "backend_scope": scope.backend_scope,
                "validation_status": scope.validation_status,
                "product_open": scope.validation_status in _ALLOW_PRODUCT,
                "pending": scope.validation_status in _PENDING_STATUSES,
                "disabled_reason": (
                    None
                    if scope.validation_status in _ALLOW_PRODUCT
                    else _scope_support_reason(
                        status=scope.validation_status,
                        transport=scope.transport_scope,
                        backend=scope.backend_scope,
                    )
                ),
                **(
                    {
                        "features": [
                            {
                                "feature_kind": feature.feature_kind,
                                "feature_value": feature.feature_value,
                                "validation_status": feature.validation_status,
                                "product_open": feature.validation_status in _ALLOW_PRODUCT,
                                "pending": feature.validation_status
                                == VALIDATION_STATUS_FEATURE_PENDING,
                                "disabled_reason": (
                                    None
                                    if feature.validation_status in _ALLOW_PRODUCT
                                    else _feature_support_reason(feature)
                                ),
                            }
                            for feature in scope.feature_scopes
                        ]
                    }
                    if scope.feature_scopes
                    else {}
                ),
            }
            for scope in policy.scopes
        ],
    }


def _generic_public_command(command: str) -> dict[str, object]:
    if command in PURE_OFFLINE_COMMANDS or command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS:
        return _public_command_policy(model="GENERIC", command=command, policy=None)
    capability = command_support(None).get(command, {})
    profile_supported = bool(capability.get("simulate") or capability.get("dry_run"))
    reason = "GENERIC is no-hardware/fallback-only; live exact scopes are unavailable."
    return {
        "profile_validation_status": None,
        "profile_supported": profile_supported,
        "metadata_available": False,
        "policy_exempt": False,
        "offline_only": False,
        "disabled_reason": reason,
        "support_reason": reason,
        "scopes": [],
    }


def _scope_support_reason(*, status: str, transport: str, backend: str) -> str:
    scope_label = f"{_transport_display(transport)} / {_backend_display(backend)}"
    if status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
        return f"Live validated: {scope_label}."
    if status in _PENDING_STATUSES:
        return f"Pending live validation: {scope_label}."
    return f"Live support status is unavailable for {scope_label}."


def _feature_support_reason(feature: CommandFeatureSupportScope) -> str:
    label = f"{feature.feature_kind}={feature.feature_value}"
    if feature.validation_status == VALIDATION_STATUS_FEATURE_PENDING:
        return f"Pending live feature validation: {label}."
    if feature.validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL:
        return f"Feature is not supported by the model: {label}."
    return f"Live feature support status is unavailable: {label}."


def _transport_display(transport: str) -> str:
    return {
        TRANSPORT_USB: "USB",
        TRANSPORT_TCPIP: "TCPIP",
        TRANSPORT_ASRL: "ASRL",
        TRANSPORT_GPIB: "GPIB",
        TRANSPORT_UNKNOWN: "unknown transport",
    }.get(transport, transport)


def _backend_display(backend: str) -> str:
    return {
        BACKEND_SYSTEM_VISA: "system VISA",
        BACKEND_PYVISA_PY: "pyvisa-py",
        BACKEND_CUSTOM_VISA: "custom VISA",
    }.get(backend, backend)


def _rejection_message(
    *,
    model: str,
    command: str,
    transport: str,
    backend: str,
    mode: str,
    status: str,
    reason: str,
    feature_kind: str | None = None,
    feature_value: str | None = None,
) -> str:
    feature_context = ""
    if feature_kind is not None or feature_value is not None:
        feature_context = (
            f", feature_kind={feature_kind or 'unknown'}, "
            f"feature_value={feature_value or 'unknown'}"
        )
    return (
        "live support-policy rejected: "
        f"model={model}, command={command}, transport={transport}, backend={backend}, "
        f"policy_mode={mode}{feature_context}, status={status}; reason={reason}"
    )


LIVE_SUPPORT_POLICY_REGISTRY = _build_registry()
