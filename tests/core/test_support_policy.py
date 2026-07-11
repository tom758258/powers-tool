import json
from dataclasses import replace

import pytest

from keysight_power_core.support_features import supported_sequence_actions

from keysight_power_core.support_policy import (
    ACTIVE_LIVE_POLICY_MODELS,
    BACKEND_CUSTOM_VISA,
    BACKEND_PYVISA_PY,
    BACKEND_SYSTEM_VISA,
    EXEMPT_LIVE_DIAGNOSTIC_COMMANDS,
    LIVE_SUPPORT_POLICY_REGISTRY,
    PURE_OFFLINE_COMMANDS,
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
    TRANSPORT_ASRL,
    TRANSPORT_GPIB,
    TRANSPORT_TCPIP,
    TRANSPORT_UNKNOWN,
    TRANSPORT_USB,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
    VALIDATION_STATUS_PROFILE_VALIDATED,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    CommandLiveSupportScope,
    CommandFeatureSupportScope,
    CommandSupportPolicy,
    LiveSupportPolicyError,
    ModelSupportPolicy,
    command_live_support,
    command_live_support_matrix,
    ensure_live_scope_supported,
    exact_live_support_metadata,
    find_live_support_scope,
    find_feature_support,
    is_live_support_policy_exempt,
    live_support_policy_metadata,
    normalize_backend,
    normalize_support_feature_value,
    normalize_transport,
    validate_live_support_metadata,
)


E36312A_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "read-status",
    "readback",
    "validate-readonly",
    "capabilities",
    "set",
    "output-off",
    "safe-off",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "ramp-list",
    "sequence",
    "protection-status",
    "protection-set",
    "clear-protection",
    "snapshot",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-abort",
}
EDU36311A_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "read-status",
    "readback",
    "validate-readonly",
    "capabilities",
    "set",
    "output-off",
    "safe-off",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "ramp-list",
    "sequence",
    "protection-status",
    "protection-set",
    "clear-protection",
}
E3646A_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "read-status",
    "readback",
    "capabilities",
    "set",
    "output-off",
    "safe-off",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "ramp-list",
    "sequence",
}


def _commands_for_scope(model: str, transport: str, backend: str) -> set[str]:
    return {
        command
        for command, policy in command_live_support_matrix(model).items()
        if any(
            scope.transport_scope == transport and scope.backend_scope == backend
            for scope in policy.scopes
        )
    }


def _replace_command(
    registry: tuple[ModelSupportPolicy, ...],
    model: str,
    command: str,
    replacement: CommandSupportPolicy,
) -> tuple[ModelSupportPolicy, ...]:
    return tuple(
        replace(
            model_policy,
            commands=tuple(
                replacement if policy.command == command else policy
                for policy in model_policy.commands
            ),
        )
        if model_policy.model == model
        else model_policy
        for model_policy in registry
    )


def test_required_constants_are_stable() -> None:
    assert SUPPORT_POLICY_MODE_PRODUCT == "product"
    assert SUPPORT_POLICY_MODE_VALIDATION == "validation"
    assert {
        VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
        VALIDATION_STATUS_PROFILE_VALIDATED,
        VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        VALIDATION_STATUS_TRANSPORT_PENDING,
        VALIDATION_STATUS_FEATURE_PENDING,
    } == {
        "not_supported_by_model",
        "profile_validated",
        "live_validated_full_suite",
        "transport_pending",
        "feature_pending",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("USB0::fixture::INSTR", TRANSPORT_USB),
        (" tcpip0::192.0.2.1::instr ", TRANSPORT_TCPIP),
        ("ASRL7::INSTR", TRANSPORT_ASRL),
        ("GPIB0::5::INSTR", TRANSPORT_GPIB),
        ("usb", TRANSPORT_USB),
        ("unrecognized", TRANSPORT_UNKNOWN),
        (None, TRANSPORT_UNKNOWN),
        ("   ", TRANSPORT_UNKNOWN),
    ],
)
def test_transport_normalization(value: str | None, expected: str) -> None:
    assert normalize_transport(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, BACKEND_SYSTEM_VISA),
        ("", BACKEND_SYSTEM_VISA),
        ("   ", BACKEND_SYSTEM_VISA),
        (" @PY ", BACKEND_PYVISA_PY),
        ("@ivi", BACKEND_CUSTOM_VISA),
    ],
)
def test_backend_normalization(value: str | None, expected: str) -> None:
    assert normalize_backend(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("system_visa", BACKEND_SYSTEM_VISA),
        ("pyvisa_py", BACKEND_PYVISA_PY),
        ("custom_visa", BACKEND_CUSTOM_VISA),
    ],
)
def test_canonical_backend_labels_remain_canonical(value: str, expected: str) -> None:
    assert normalize_backend(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "@py", "@ivi", "system_visa", "pyvisa_py", "custom_visa"],
)
def test_backend_normalization_is_idempotent(value: str | None) -> None:
    normalized = normalize_backend(value)
    assert normalize_backend(normalized) == normalized


@pytest.mark.parametrize(
    ("model", "transport", "commands"),
    [
        ("E36312A", TRANSPORT_USB, E36312A_VALIDATED_COMMANDS),
        ("E36312A", TRANSPORT_TCPIP, E36312A_VALIDATED_COMMANDS),
        ("EDU36311A", TRANSPORT_USB, EDU36311A_VALIDATED_COMMANDS),
        ("EDU36311A", TRANSPORT_TCPIP, EDU36311A_VALIDATED_COMMANDS),
        ("E3646A", TRANSPORT_ASRL, E3646A_VALIDATED_COMMANDS),
    ],
)
def test_exact_validated_command_inventory(
    model: str, transport: str, commands: set[str]
) -> None:
    assert _commands_for_scope(model, transport, BACKEND_SYSTEM_VISA) == commands
    for command in commands:
        scope = find_live_support_scope(
            model=model,
            command=command,
            transport=transport,
            backend=BACKEND_SYSTEM_VISA,
        )
        assert scope is not None
        assert scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
        assert scope.evidence
        assert scope.artifact
        assert "pyvisa.ResourceManager()" in (scope.note or "")


@pytest.mark.parametrize(
    ("model", "commands"),
    [
        ("E36312A", E36312A_VALIDATED_COMMANDS),
        ("EDU36311A", EDU36311A_VALIDATED_COMMANDS),
    ],
)
def test_tcpip_pyvisa_py_pending_inventory(model: str, commands: set[str]) -> None:
    assert _commands_for_scope(model, TRANSPORT_TCPIP, BACKEND_PYVISA_PY) == commands
    for command in commands:
        scope = find_live_support_scope(
            model=model,
            command=command,
            transport=TRANSPORT_TCPIP,
            backend="@py",
        )
        assert scope is not None
        assert scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
        assert "pending separate live validation" in (scope.note or "")


@pytest.mark.parametrize(
    ("model", "transport", "backend"),
    [
        ("E36312A", TRANSPORT_USB, BACKEND_PYVISA_PY),
        ("EDU36311A", TRANSPORT_USB, BACKEND_PYVISA_PY),
        ("E3646A", TRANSPORT_TCPIP, BACKEND_SYSTEM_VISA),
        ("E3646A", TRANSPORT_USB, BACKEND_SYSTEM_VISA),
        ("E3646A", TRANSPORT_TCPIP, BACKEND_PYVISA_PY),
        ("E36312A", TRANSPORT_TCPIP, BACKEND_CUSTOM_VISA),
    ],
)
def test_unregistered_scopes_do_not_appear(
    model: str, transport: str, backend: str
) -> None:
    assert _commands_for_scope(model, transport, backend) == set()


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_validated_scope_is_allowed_in_both_modes(mode: str) -> None:
    scope = ensure_live_scope_supported(
        model="e36312a",
        command="measure",
        transport="USB0::fixture::INSTR",
        backend=None,
        support_policy_mode=mode,
    )
    assert scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE


def test_product_rejects_and_validation_allows_transport_pending() -> None:
    arguments = {
        "model": "E36312A",
        "command": "measure",
        "transport": "TCPIP",
        "backend": "@py",
    }
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        ensure_live_scope_supported(
            **arguments, support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT
        )
    scope = ensure_live_scope_supported(
        **arguments, support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION
    )
    assert scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING


def test_feature_pending_is_validation_only_with_synthetic_metadata() -> None:
    base = command_live_support("E36312A", "sequence")
    feature_scope = replace(base.scopes[0], feature_scopes=(
        CommandFeatureSupportScope(
            feature_kind="sequence_action",
            feature_value="set",
            validation_status=VALIDATION_STATUS_FEATURE_PENDING,
            note="Synthetic feature candidate.",
        ),
    ))
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "sequence",
        replace(base, scopes=(feature_scope,)),
    )
    with pytest.raises(LiveSupportPolicyError, match="feature_pending"):
        ensure_live_scope_supported(
            model="E36312A",
            command="sequence",
            feature_requirements=(("sequence_action", "set"),),
            transport=feature_scope.transport_scope,
            backend=feature_scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
            registry=registry,
        )
    assert (
        ensure_live_scope_supported(
            model="E36312A",
            command="sequence",
            transport=feature_scope.transport_scope,
            backend=feature_scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        ).validation_status
        == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
    )


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("sequence_action", " SET ", "set"),
        ("trigger_source", "BUS", "bus"),
        ("trigger_source", "imm", "immediate"),
    ],
)
def test_feature_value_normalization(kind: str, value: str, expected: str) -> None:
    assert normalize_support_feature_value(kind, value) == expected


def test_feature_lookup_is_exact_and_rejects_duplicates() -> None:
    scope = command_live_support("E36312A", "trigger-step").scopes[0]
    assert find_feature_support(scope, "trigger_source", "IMM").feature_value == "immediate"
    without_immediate = replace(
        scope,
        feature_scopes=tuple(
            feature for feature in scope.feature_scopes if feature.feature_value != "immediate"
        ),
    )
    assert find_feature_support(without_immediate, "trigger_source", "immediate") is None
    duplicated = replace(scope, feature_scopes=scope.feature_scopes + (scope.feature_scopes[0],))
    with pytest.raises(LiveSupportPolicyError, match="duplicate live support feature metadata"):
        find_feature_support(duplicated, "trigger_source", scope.feature_scopes[0].feature_value)


def test_transport_pending_parent_requires_and_allows_pending_feature_only_in_validation() -> None:
    arguments = {
        "model": "E36312A",
        "command": "sequence",
        "transport": TRANSPORT_TCPIP,
        "backend": BACKEND_PYVISA_PY,
        "feature_requirements": (("sequence_action", "set"),),
    }
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        ensure_live_scope_supported(
            **arguments, support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT
        )
    scope = ensure_live_scope_supported(
        **arguments, support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION
    )
    feature = find_feature_support(scope, "sequence_action", "set")
    assert feature is not None
    assert feature.validation_status == VALIDATION_STATUS_FEATURE_PENDING


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_missing_feature_metadata_fails_closed(mode: str) -> None:
    base = command_live_support("E36312A", "sequence")
    scope = replace(
        base.scopes[0],
        feature_scopes=tuple(
            feature for feature in base.scopes[0].feature_scopes if feature.feature_value != "set"
        ),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "sequence",
        replace(base, scopes=(scope,)),
    )
    with pytest.raises(LiveSupportPolicyError, match="missing_feature_metadata") as raised:
        ensure_live_scope_supported(
            model="E36312A",
            command="sequence",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=mode,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        )
    assert "feature_kind=sequence_action" in str(raised.value)
    assert "feature_value=set" in str(raised.value)


def test_unknown_feature_status_fails_closed() -> None:
    base = command_live_support("E36312A", "trigger-step")
    source = base.scopes[0].feature_scopes[0]
    scope = replace(
        base.scopes[0],
        feature_scopes=(replace(source, validation_status="future"),)
        + base.scopes[0].feature_scopes[1:],
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "trigger-step",
        replace(base, scopes=(scope,)),
    )
    with pytest.raises(LiveSupportPolicyError, match="unknown validation status"):
        ensure_live_scope_supported(
            model="E36312A",
            command="trigger-step",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            feature_requirements=(("trigger_source", source.feature_value),),
            registry=registry,
        )


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_not_supported_is_rejected_in_both_modes(mode: str) -> None:
    with pytest.raises(LiveSupportPolicyError, match="not_supported_by_model"):
        ensure_live_scope_supported(
            model="EDU36311A",
            command="trigger-list",
            transport=TRANSPORT_USB,
            backend=BACKEND_SYSTEM_VISA,
            support_policy_mode=mode,
        )


@pytest.mark.parametrize(
    ("model", "command", "transport", "mode", "match"),
    [
        ("E36312A", "missing-command", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("E36312A", "measure", TRANSPORT_GPIB, SUPPORT_POLICY_MODE_PRODUCT, "no exact transport/backend scope"),
        ("E36312A", "measure", TRANSPORT_USB, "future", "unknown_policy_mode"),
        ("E36103B", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("E36232A", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("UNKNOWN", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("GENERIC", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
    ],
)
def test_evaluator_fails_closed(
    model: str, command: str, transport: str, mode: str, match: str
) -> None:
    with pytest.raises(LiveSupportPolicyError, match=match) as raised:
        ensure_live_scope_supported(
            model=model,
            command=command,
            transport=transport,
            backend=BACKEND_SYSTEM_VISA,
            support_policy_mode=mode,
        )
    message = str(raised.value)
    assert "model=" in message
    assert "command=" in message
    assert "transport=" in message
    assert "backend=" in message
    assert "policy_mode=" in message
    assert "status=" in message


def test_unknown_scope_status_fails_closed() -> None:
    base = command_live_support("E36312A", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "measure",
        replace(base, scopes=(replace(base.scopes[0], validation_status="future_status"),)),
    )
    with pytest.raises(LiveSupportPolicyError, match="unknown validation status"):
        ensure_live_scope_supported(
            model="E36312A",
            command="measure",
            transport=base.scopes[0].transport_scope,
            backend=base.scopes[0].backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            registry=registry,
        )


@pytest.mark.parametrize(
    "status",
    [
        "future_status",
        VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        VALIDATION_STATUS_TRANSPORT_PENDING,
        VALIDATION_STATUS_FEATURE_PENDING,
    ],
)
@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_evaluator_rejects_invalid_top_level_status_with_valid_scope(
    status: str, mode: str
) -> None:
    base = command_live_support("E36312A", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "measure",
        replace(base, validation_status=status),
    )
    with pytest.raises(LiveSupportPolicyError, match="command-policy validation status"):
        ensure_live_scope_supported(
            model="E36312A",
            command="measure",
            transport=base.scopes[0].transport_scope,
            backend=base.scopes[0].backend_scope,
            support_policy_mode=mode,
            registry=registry,
        )


def test_profile_validated_without_an_exact_scope_does_not_open_live() -> None:
    policy = command_live_support("E36312A", "output-on")
    assert policy.validation_status == VALIDATION_STATUS_PROFILE_VALIDATED
    assert policy.scopes == ()
    with pytest.raises(LiveSupportPolicyError, match="no exact transport/backend scope"):
        ensure_live_scope_supported(
            model="E36312A",
            command="output-on",
            transport=TRANSPORT_USB,
            backend=BACKEND_SYSTEM_VISA,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
        )


@pytest.mark.parametrize(
    ("model", "commands"),
    [
        (
            "EDU36311A",
            {
                "measure-all",
                "trigger-pulse",
                "trigger-status",
                "trigger-step",
                "trigger-list",
                "trigger-fire",
                "trigger-abort",
                "snapshot",
                "restore-from-snapshot",
            },
        ),
        (
            "E3646A",
            {
                "measure-all",
                "protection-status",
                "protection-set",
                "clear-protection",
                "snapshot",
                "restore-from-snapshot",
                "trigger-pulse",
                "trigger-status",
                "trigger-step",
                "trigger-list",
                "trigger-fire",
                "trigger-abort",
            },
        ),
    ],
)
def test_explicit_model_unsupported_boundaries(model: str, commands: set[str]) -> None:
    matrix = command_live_support_matrix(model)
    for command in commands:
        assert matrix[command].validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL
        assert matrix[command].scopes == ()


def test_e3646a_software_workflows_have_only_current_asrl_scope() -> None:
    for command in ("ramp-list", "sequence"):
        policy = command_live_support("E3646A", command)
        assert {
            (scope.transport_scope, scope.backend_scope, scope.validation_status)
            for scope in policy.scopes
        } == {
            (
                TRANSPORT_ASRL,
                BACKEND_SYSTEM_VISA,
                VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
            )
        }


def test_diagnostic_and_offline_boundaries_are_explicit() -> None:
    assert EXEMPT_LIVE_DIAGNOSTIC_COMMANDS == {
        "list-resources",
        "verify",
        "identify",
        "error",
        "clear",
    }
    assert all(is_live_support_policy_exempt(command) for command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS)
    assert all(is_live_support_policy_exempt(command) for command in PURE_OFFLINE_COMMANDS)
    assert not is_live_support_policy_exempt("doctor")
    assert not is_live_support_policy_exempt("capabilities")
    assert not is_live_support_policy_exempt("measure")
    assert not is_live_support_policy_exempt("missing-read-command")
    for matrix in (command_live_support_matrix(model) for model in ACTIVE_LIVE_POLICY_MODELS):
        assert EXEMPT_LIVE_DIAGNOSTIC_COMMANDS.isdisjoint(matrix)
        assert PURE_OFFLINE_COMMANDS.isdisjoint(matrix)


def test_checked_in_registry_passes_validation() -> None:
    validate_live_support_metadata()


def test_checked_in_feature_inventory_matches_current_profiles() -> None:
    for model in ACTIVE_LIVE_POLICY_MODELS:
        for scope in command_live_support(model, "sequence").scopes:
            assert {
                feature.feature_value for feature in scope.feature_scopes
            } == supported_sequence_actions(model)
            expected_status = (
                VALIDATION_STATUS_FEATURE_PENDING
                if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
                else VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
            )
            assert {feature.validation_status for feature in scope.feature_scopes} == {
                expected_status
            }
    assert "trigger-pulse" in supported_sequence_actions("E36312A")
    assert "trigger-pulse" not in supported_sequence_actions("EDU36311A")
    assert "trigger-pulse" not in supported_sequence_actions("E3646A")
    for command in ("trigger-step", "trigger-list"):
        for scope in command_live_support("E36312A", command).scopes:
            assert {feature.feature_value for feature in scope.feature_scopes} == {
                "bus", "immediate"
            }


def test_public_feature_projection_is_additive_and_redacted() -> None:
    metadata = live_support_policy_metadata("E36312A", {"sequence"})
    scope = metadata["commands"]["sequence"]["scopes"][0]
    assert scope["features"]
    assert {feature["feature_kind"] for feature in scope["features"]} == {
        "sequence_action"
    }
    serialized = json.dumps(metadata)
    assert "evidence" not in serialized
    assert "artifact" not in serialized
    assert ".tmp_tests" not in serialized
    assert "pre-P7" not in serialized


def test_validator_rejects_feature_inventory_drift() -> None:
    base = command_live_support("E36312A", "sequence")
    scope = replace(base.scopes[0], feature_scopes=base.scopes[0].feature_scopes[:-1])
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "sequence",
        replace(base, scopes=(scope,) + base.scopes[1:]),
    )
    with pytest.raises(ValueError, match="feature inventory drift"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize(
    ("feature", "match"),
    [
        (
            CommandFeatureSupportScope("future_kind", "set", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE, note="migration"),
            "unsupported feature kind",
        ),
        (
            CommandFeatureSupportScope("Sequence_Action", "set", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE, note="migration"),
            "noncanonical feature kind",
        ),
        (
            CommandFeatureSupportScope("sequence_action", " SET ", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE, note="migration"),
            "noncanonical feature value",
        ),
        (
            CommandFeatureSupportScope("sequence_action", "set", "future", note="migration"),
            "unknown feature validation status",
        ),
        (
            CommandFeatureSupportScope("sequence_action", "set", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE),
            "validated feature lacks evidence or migration note",
        ),
    ],
)
def test_validator_rejects_invalid_feature_metadata(
    feature: CommandFeatureSupportScope, match: str
) -> None:
    base = command_live_support("E36312A", "sequence")
    scope = replace(base.scopes[0], feature_scopes=(feature,) + base.scopes[0].feature_scopes[1:])
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "sequence",
        replace(base, scopes=(scope,) + base.scopes[1:]),
    )
    with pytest.raises(ValueError, match=match):
        validate_live_support_metadata(registry)


def test_validator_rejects_duplicate_feature_scope_and_wrong_command_kind() -> None:
    sequence = command_live_support("E36312A", "sequence")
    duplicate_scope = replace(
        sequence.scopes[0],
        feature_scopes=sequence.scopes[0].feature_scopes
        + (sequence.scopes[0].feature_scopes[0],),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "sequence",
        replace(sequence, scopes=(duplicate_scope,) + sequence.scopes[1:]),
    )
    with pytest.raises(ValueError, match="duplicate feature scope"):
        validate_live_support_metadata(registry)

    measure = command_live_support("E36312A", "measure")
    wrong_scope = replace(
        measure.scopes[0],
        feature_scopes=(sequence.scopes[0].feature_scopes[0],),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "measure",
        replace(measure, scopes=(wrong_scope,) + measure.scopes[1:]),
    )
    with pytest.raises(ValueError, match="unexpected feature scope"):
        validate_live_support_metadata(registry)


def test_validator_rejects_duplicate_exact_scope() -> None:
    base = command_live_support("E36312A", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "measure",
        replace(base, scopes=base.scopes + (base.scopes[0],)),
    )
    with pytest.raises(ValueError, match="duplicate exact scope"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize(
    ("replacement", "match"),
    [
        (
            replace(command_live_support("E36312A", "measure"), validation_status="future"),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
            ),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                validation_status=VALIDATION_STATUS_TRANSPORT_PENDING,
            ),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                validation_status=VALIDATION_STATUS_FEATURE_PENDING,
            ),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                scopes=(replace(command_live_support("E36312A", "measure").scopes[0], validation_status="future"),),
            ),
            "unknown scope validation status",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                scopes=(replace(command_live_support("E36312A", "measure").scopes[0], evidence=None),),
            ),
            "validated scope lacks evidence",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                scopes=(replace(command_live_support("E36312A", "measure").scopes[0], artifact=None),),
            ),
            "validated scope lacks artifact",
        ),
        (
            replace(
                command_live_support("E36312A", "measure"),
                scopes=(
                    CommandLiveSupportScope(
                        VALIDATION_STATUS_TRANSPORT_PENDING,
                        TRANSPORT_GPIB,
                        BACKEND_SYSTEM_VISA,
                    ),
                ),
            ),
            "pending scope lacks note",
        ),
        (
            replace(
                command_live_support("EDU36311A", "trigger-list"),
                scopes=(command_live_support("E36312A", "measure").scopes[0],),
            ),
            "unsupported command has live scopes",
        ),
    ],
)
def test_validator_rejects_invalid_command_metadata(
    replacement: CommandSupportPolicy, match: str
) -> None:
    model = "EDU36311A" if replacement.command == "trigger-list" else "E36312A"
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY, model, replacement.command, replacement
    )
    with pytest.raises(ValueError, match=match):
        validate_live_support_metadata(registry)


def test_validator_rejects_de_scoped_model() -> None:
    registry = LIVE_SUPPORT_POLICY_REGISTRY + (
        ModelSupportPolicy("E36103B", command_live_support_matrix("E36312A").values()),
    )
    with pytest.raises(ValueError, match="de-scoped model"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize("model", ["e36312a", " E36312A", "E36312A "])
def test_validator_rejects_noncanonical_model_metadata(model: str) -> None:
    registry = (replace(LIVE_SUPPORT_POLICY_REGISTRY[0], model=model),) + LIVE_SUPPORT_POLICY_REGISTRY[1:]
    with pytest.raises(ValueError, match="noncanonical model policy"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize("command", ["Measure", " measure", "measure "])
def test_validator_rejects_noncanonical_command_metadata(command: str) -> None:
    base = command_live_support("E36312A", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "measure",
        replace(base, command=command),
    )
    with pytest.raises(ValueError, match="noncanonical command policy"):
        validate_live_support_metadata(registry)


def test_validator_rejects_unknown_exact_transport() -> None:
    base = command_live_support("E36312A", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "E36312A",
        "measure",
        replace(base, scopes=(replace(base.scopes[0], transport_scope=TRANSPORT_UNKNOWN),)),
    )
    with pytest.raises(ValueError, match="exact live scope cannot use unknown transport"):
        validate_live_support_metadata(registry)


def test_validator_rejects_missing_and_unexpected_command_inventory_entries() -> None:
    inventory = set(command_live_support_matrix("E36312A"))
    with pytest.raises(ValueError, match="policy-governed commands missing"):
        validate_live_support_metadata(command_inventory=inventory | {"future-command"})
    with pytest.raises(ValueError, match="outside current inventory"):
        validate_live_support_metadata(command_inventory=inventory - {"measure"})


def test_public_model_projection_is_json_safe_and_omits_private_evidence() -> None:
    metadata = live_support_policy_metadata(
        "E36312A", {"set", "clear", "snapshot-diff", "future-command"}
    )

    assert metadata["model"] == "E36312A"
    assert metadata["live_capable"] is True
    set_support = metadata["commands"]["set"]
    assert set_support["profile_validation_status"] == VALIDATION_STATUS_PROFILE_VALIDATED
    assert set_support["profile_supported"] is True
    assert set_support["policy_exempt"] is False
    assert {
        (scope["transport_scope"], scope["backend_scope"], scope["validation_status"])
        for scope in set_support["scopes"]
    } == {
        (TRANSPORT_USB, BACKEND_SYSTEM_VISA, VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE),
        (TRANSPORT_TCPIP, BACKEND_SYSTEM_VISA, VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE),
        (TRANSPORT_TCPIP, BACKEND_PYVISA_PY, VALIDATION_STATUS_TRANSPORT_PENDING),
    }
    assert metadata["commands"]["clear"]["policy_exempt"] is True
    assert metadata["commands"]["clear"]["offline_only"] is False
    assert metadata["commands"]["clear"]["scopes"] == []
    offline = metadata["commands"]["snapshot-diff"]
    assert offline["policy_exempt"] is False
    assert offline["offline_only"] is True
    assert offline["scopes"] == []
    assert "Offline utility" in offline["support_reason"]
    assert metadata["commands"]["future-command"]["metadata_available"] is False
    assert metadata["commands"]["future-command"]["profile_supported"] is False

    serialized = json.dumps(metadata)
    assert ".tmp_tests" not in serialized
    assert "artifact" not in serialized
    assert "evidence" not in serialized
    assert "serial" not in serialized


def test_public_exact_projection_distinguishes_open_pending_and_missing_scopes() -> None:
    commands = {"set", "output-on", "clear", "snapshot-diff"}
    usb = exact_live_support_metadata(
        model="E36312A",
        resource="USB0::FAKE::INSTR",
        backend=None,
        commands=commands,
    )
    system_tcpip = exact_live_support_metadata(
        model="E36312A",
        resource="TCPIP0::192.0.2.1::INSTR",
        backend=None,
        commands=commands,
    )
    pending = exact_live_support_metadata(
        model="E36312A",
        resource="TCPIP0::192.0.2.1::INSTR",
        backend="@py",
        commands=commands,
    )

    assert usb["policy_mode"] == SUPPORT_POLICY_MODE_PRODUCT
    assert usb["commands"]["set"]["product_open"] is True
    assert system_tcpip["commands"]["set"]["product_open"] is True
    assert pending["commands"]["set"] == {
        "profile_validation_status": VALIDATION_STATUS_PROFILE_VALIDATED,
        "profile_supported": True,
        "metadata_available": True,
        "policy_exempt": False,
        "offline_only": False,
        "disabled_reason": "Pending live validation: TCPIP / pyvisa-py.",
        "support_reason": "Pending live validation: TCPIP / pyvisa-py.",
        "exact_scope_validation_status": VALIDATION_STATUS_TRANSPORT_PENDING,
        "product_open": False,
    }
    assert pending["commands"]["output-on"]["exact_scope_validation_status"] is None
    assert pending["commands"]["output-on"]["product_open"] is False
    assert "No product-open live scope" in pending["commands"]["output-on"]["disabled_reason"]
    assert pending["commands"]["clear"]["policy_exempt"] is True
    assert pending["commands"]["clear"]["offline_only"] is False
    assert pending["commands"]["clear"]["product_open"] is True
    assert pending["commands"]["clear"]["exact_scope_validation_status"] is None
    offline = pending["commands"]["snapshot-diff"]
    assert offline["policy_exempt"] is False
    assert offline["offline_only"] is True
    assert offline["product_open"] is False
    assert offline["exact_scope_validation_status"] is None
    assert offline["support_reason"] == "Offline utility; live exact scope is not applicable."


def test_public_projection_preserves_model_and_generic_boundaries() -> None:
    edu = live_support_policy_metadata("EDU36311A", {"trigger-list"})
    e3646a_asrl = exact_live_support_metadata(
        model="E3646A",
        resource="ASRL7::INSTR",
        backend=None,
        commands={"set"},
    )
    e3646a_usb = exact_live_support_metadata(
        model="E3646A",
        resource="USB0::FAKE::INSTR",
        backend=None,
        commands={"set"},
    )
    generic = live_support_policy_metadata("GENERIC", {"set", "identify"})

    assert edu["commands"]["trigger-list"]["profile_validation_status"] == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL
    assert edu["commands"]["trigger-list"]["profile_supported"] is False
    assert edu["commands"]["trigger-list"]["scopes"] == []
    assert e3646a_asrl["commands"]["set"]["product_open"] is True
    assert e3646a_usb["commands"]["set"]["product_open"] is False
    assert e3646a_usb["commands"]["set"]["exact_scope_validation_status"] is None
    assert generic["live_capable"] is False
    assert generic["fallback_only"] is True
    assert generic["commands"]["set"]["scopes"] == []
    assert generic["commands"]["identify"]["policy_exempt"] is True

    with pytest.raises(LiveSupportPolicyError):
        exact_live_support_metadata(
            model="GENERIC", resource="USB0::FAKE::INSTR", backend=None
        )
    with pytest.raises(LiveSupportPolicyError):
        live_support_policy_metadata("E36103B", {"set"})
    with pytest.raises(LiveSupportPolicyError):
        live_support_policy_metadata("UNKNOWN", {"set"})
