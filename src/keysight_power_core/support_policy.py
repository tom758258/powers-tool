"""Exact live support-policy metadata for future Core enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from keysight_power_core.capabilities import command_support, known_capability_commands
from keysight_power_core.core import CoreValidationError
from keysight_power_core.model_resolution import canonical_model_profile
from keysight_power_core.models import DE_SCOPED_MODELS, resource_interface

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

ACTIVE_LIVE_POLICY_MODELS = frozenset({"E36312A", "EDU36311A", "E3646A"})
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
        VALIDATION_STATUS_FEATURE_PENDING,
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
    VALIDATION_STATUS_FEATURE_PENDING,
}


class LiveSupportPolicyError(CoreValidationError):
    """Raised when an exact live support-policy decision rejects a scope."""


@dataclass(frozen=True)
class CommandLiveSupportScope:
    validation_status: str
    transport_scope: str
    backend_scope: str
    evidence: str | None = None
    artifact: str | None = None
    note: str | None = None


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


def ensure_live_scope_supported(
    *,
    model: str,
    command: str,
    transport: str,
    backend: str,
    support_policy_mode: str,
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
                    VALIDATION_STATUS_FEATURE_PENDING,
                } and not scope.note:
                    raise ValueError(f"pending scope lacks note: {model}/{command}/{scope_key}")
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
    for model in sorted(ACTIVE_LIVE_POLICY_MODELS):
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


def _rejection_message(
    *,
    model: str,
    command: str,
    transport: str,
    backend: str,
    mode: str,
    status: str,
    reason: str,
) -> str:
    return (
        "live support-policy rejected: "
        f"model={model}, command={command}, transport={transport}, backend={backend}, "
        f"policy_mode={mode}, status={status}; reason={reason}"
    )


LIVE_SUPPORT_POLICY_REGISTRY = _build_registry()
