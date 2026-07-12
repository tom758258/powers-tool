import json
import re
from dataclasses import fields, replace
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType

import pytest

from powers_tool_core.support_evidence import (
    SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY,
    SOURCE_AVAILABILITY_VERIFIED_LOCAL,
    SUPPORT_EVIDENCE_BY_ID,
    SUPPORT_EVIDENCE_RECORDS,
    validate_support_evidence_metadata,
)
from powers_tool_core.support_policy import (
    BACKEND_PYVISA_PY,
    LIVE_SUPPORT_POLICY_REGISTRY,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    exact_live_support_metadata,
    validate_live_support_metadata,
)


EXPECTED_EVIDENCE = {
    "keysight-e36312a-usb-system-visa-20260709-full": (
        "keysight-e36312a",
        "usb",
        ".tmp_tests/live_cli_check/20260709_153201_E36312A_USB_full",
    ),
    "keysight-e36312a-tcpip-system-visa-20260709-full": (
        "keysight-e36312a",
        "tcpip",
        ".tmp_tests/live_cli_check/20260709_201420_E36312A_LAN_full",
    ),
    "keysight-edu36311a-usb-system-visa-20260709-full": (
        "keysight-edu36311a",
        "usb",
        ".tmp_tests/live_cli_check/20260709_151534_EDU36311A_USB_full",
    ),
    "keysight-edu36311a-tcpip-system-visa-20260709-full": (
        "keysight-edu36311a",
        "tcpip",
        ".tmp_tests/live_cli_check/20260709_200530_EDU36311A_LAN_full",
    ),
    "keysight-e3646a-asrl-system-visa-20260709-full": (
        "keysight-e3646a",
        "asrl",
        ".tmp_tests/live_cli_check/20260709_151205_E3646A_ASRL_full",
    ),
}

EXPECTED_COMMAND_COUNTS = {
    "keysight-e36312a": 23,
    "keysight-edu36311a": 18,
    "keysight-e3646a": 14,
}

EXPECTED_FEATURES_BY_MODEL = {
    "keysight-e36312a": {
        "sequence": frozenset(
            ("sequence_action", value)
            for value in {
                "apply", "cycle-output", "measure", "output-off", "output-on",
                "output-state", "readback", "safe-off", "set", "trigger-pulse",
            }
        ),
        "trigger-step": frozenset(
            {("trigger_source", "bus"), ("trigger_source", "immediate")}
        ),
        "trigger-list": frozenset(
            {("trigger_source", "bus"), ("trigger_source", "immediate")}
        ),
    },
    "keysight-edu36311a": {
        "sequence": frozenset(
            ("sequence_action", value)
            for value in {
                "apply", "cycle-output", "measure", "output-off", "output-on",
                "output-state", "readback", "safe-off", "set",
            }
        ),
    },
    "keysight-e3646a": {
        "sequence": frozenset(
            ("sequence_action", value)
            for value in {
                "apply", "cycle-output", "measure", "output-off", "output-on",
                "output-state", "readback", "safe-off", "set",
            }
        ),
    },
}


def test_exactly_five_immutable_historical_evidence_identities_exist() -> None:
    assert len(SUPPORT_EVIDENCE_RECORDS) == 5
    assert len(SUPPORT_EVIDENCE_BY_ID) == 5
    assert set(SUPPORT_EVIDENCE_BY_ID) == set(EXPECTED_EVIDENCE)
    for evidence_id, (model_id, transport, artifact_directory) in EXPECTED_EVIDENCE.items():
        record = SUPPORT_EVIDENCE_BY_ID[evidence_id]
        assert (record.model_id, record.transport_scope, record.backend_scope) == (
            model_id,
            transport,
            "system_visa",
        )
        assert record.artifact_directory == artifact_directory
        assert record.report_path == f"{artifact_directory}/report.json"
        assert record.summary_path == f"{artifact_directory}/summary.md"
        assert record.source_availability == SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY
        assert record.report_sha256 is None
        assert record.artifact_schema_version == "1.0"
    with pytest.raises(TypeError):
        SUPPORT_EVIDENCE_BY_ID["new-evidence"] = SUPPORT_EVIDENCE_RECORDS[0]  # type: ignore[index]


def test_historical_evidence_inventories_are_frozen_and_exact() -> None:
    for record in SUPPORT_EVIDENCE_RECORDS:
        assert len(record.accepted_commands) == EXPECTED_COMMAND_COUNTS[record.model_id]
        assert record.accepted_features_by_command == EXPECTED_FEATURES_BY_MODEL[record.model_id]
        assert isinstance(record.accepted_features_by_command, MappingProxyType)
        with pytest.raises(AttributeError):
            record.accepted_commands.add("future-command")  # type: ignore[attr-defined]
        with pytest.raises(TypeError):
            record.accepted_features_by_command["sequence"] = frozenset()  # type: ignore[index]


def test_unrecorded_command_cannot_inherit_accepted_evidence() -> None:
    evidence = SUPPORT_EVIDENCE_RECORDS[0]
    mismatched = replace(
        evidence,
        accepted_commands=evidence.accepted_commands - {"measure"},
    )
    evidence_registry = {**SUPPORT_EVIDENCE_BY_ID, evidence.evidence_id: mismatched}
    with pytest.raises(ValueError, match="evidence command mismatch"):
        validate_live_support_metadata(evidence_registry=evidence_registry)


def test_unrecorded_feature_cannot_inherit_accepted_evidence() -> None:
    evidence = SUPPORT_EVIDENCE_RECORDS[0]
    features = dict(evidence.accepted_features_by_command)
    features["sequence"] = features["sequence"] - {
        ("sequence_action", "apply")
    }
    mismatched = replace(
        evidence,
        accepted_features_by_command=MappingProxyType(features),
    )
    evidence_registry = {**SUPPORT_EVIDENCE_BY_ID, evidence.evidence_id: mismatched}
    with pytest.raises(ValueError, match="evidence feature mismatch"):
        validate_live_support_metadata(evidence_registry=evidence_registry)


def test_evidence_paths_are_relative_and_metadata_is_non_sensitive() -> None:
    forbidden = re.compile(
        r"::|\b(?:10\.|192\.168\.|169\.254\.|172\.(?:1[6-9]|2\d|3[01])\.)"
    )
    for record in SUPPORT_EVIDENCE_RECORDS:
        for path_value in (record.artifact_directory, record.report_path, record.summary_path):
            assert not PurePosixPath(path_value).is_absolute()
            assert not PureWindowsPath(path_value).is_absolute()
            assert ".." not in PurePosixPath(path_value).parts
        for field in fields(record):
            value = getattr(record, field.name)
            if isinstance(value, str):
                assert forbidden.search(value) is None


def test_availability_and_checksum_combinations_fail_closed() -> None:
    base = SUPPORT_EVIDENCE_RECORDS[0]
    verified = replace(
        base,
        source_availability=SOURCE_AVAILABILITY_VERIFIED_LOCAL,
        report_sha256="a" * 64,
    )
    validate_support_evidence_metadata((verified,))

    with pytest.raises(ValueError, match="requires SHA-256"):
        validate_support_evidence_metadata(
            (replace(base, source_availability=SOURCE_AVAILABILITY_VERIFIED_LOCAL),)
        )
    with pytest.raises(ValueError, match="cannot claim a checksum"):
        validate_support_evidence_metadata((replace(base, report_sha256="a" * 64),))
    with pytest.raises(ValueError, match="invalid evidence source availability"):
        validate_support_evidence_metadata((replace(base, source_availability="unknown"),))
    with pytest.raises(ValueError, match="invalid artifact schema version"):
        validate_support_evidence_metadata((replace(base, artifact_schema_version=1),))
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        validate_support_evidence_metadata((base, base))
    with pytest.raises(ValueError, match="noncanonical evidence model_id"):
        validate_support_evidence_metadata((replace(base, model_id="E36312A"),))
    with pytest.raises(ValueError, match="repository-relative"):
        validate_support_evidence_metadata(
            (replace(base, artifact_directory="C:/Users/example/evidence"),)
        )


def test_policy_accepted_and_candidate_basis_references_are_exact() -> None:
    accepted_count = 0
    pending_count = 0
    for model_policy in LIVE_SUPPORT_POLICY_REGISTRY:
        for command_policy in model_policy.commands:
            for scope in command_policy.scopes:
                if scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
                    accepted_count += 1
                    assert scope.accepted_evidence_ids
                    assert scope.candidate_basis_evidence_ids == ()
                    for evidence_id in scope.accepted_evidence_ids:
                        evidence = SUPPORT_EVIDENCE_BY_ID[evidence_id]
                        assert evidence.model_id == model_policy.model_id
                        assert evidence.transport_scope == scope.transport_scope
                        assert evidence.backend_scope == scope.backend_scope
                elif scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING:
                    pending_count += 1
                    assert scope.backend_scope == BACKEND_PYVISA_PY
                    assert scope.accepted_evidence_ids == ()
                    assert scope.candidate_basis_evidence_ids
                    for evidence_id in scope.candidate_basis_evidence_ids:
                        evidence = SUPPORT_EVIDENCE_BY_ID[evidence_id]
                        assert evidence.model_id == model_policy.model_id
                        assert evidence.transport_scope == scope.transport_scope
                        assert evidence.backend_scope == "system_visa"
                    assert all(
                        feature.validation_status == VALIDATION_STATUS_FEATURE_PENDING
                        and not feature.inherits_parent_accepted_evidence
                        for feature in scope.feature_scopes
                    )
    assert accepted_count > 0
    assert pending_count > 0


@pytest.mark.parametrize(
    ("evidence_id", "match"),
    [
        ("keysight-edu36311a-usb-system-visa-20260709-full", "evidence model mismatch"),
        ("keysight-e36312a-tcpip-system-visa-20260709-full", "evidence transport mismatch"),
        ("missing-evidence-id", "missing evidence registry entry"),
    ],
)
def test_wrong_or_missing_evidence_cannot_authorize_scope(
    evidence_id: str,
    match: str,
) -> None:
    model_policy = next(
        policy for policy in LIVE_SUPPORT_POLICY_REGISTRY if policy.model_id == "keysight-e36312a"
    )
    command_policy = next(policy for policy in model_policy.commands if policy.command == "measure")
    scope = next(scope for scope in command_policy.scopes if scope.transport_scope == "usb")
    changed_command = replace(
        command_policy,
        scopes=(replace(scope, accepted_evidence_ids=(evidence_id,)),)
        + tuple(item for item in command_policy.scopes if item is not scope),
    )
    changed_model = replace(
        model_policy,
        commands=(changed_command,)
        + tuple(item for item in model_policy.commands if item is not command_policy),
    )
    registry = (changed_model,) + tuple(
        item for item in LIVE_SUPPORT_POLICY_REGISTRY if item is not model_policy
    )
    with pytest.raises(ValueError, match=match):
        validate_live_support_metadata(registry)


def test_evidence_backend_must_exactly_match_policy_scope() -> None:
    evidence = SUPPORT_EVIDENCE_RECORDS[0]
    mismatched = replace(evidence, backend_scope="pyvisa_py")
    evidence_registry = {**SUPPORT_EVIDENCE_BY_ID, evidence.evidence_id: mismatched}
    with pytest.raises(ValueError, match="evidence backend mismatch"):
        validate_live_support_metadata(evidence_registry=evidence_registry)


def test_pending_scope_cannot_claim_accepted_evidence() -> None:
    model_policy = next(
        policy for policy in LIVE_SUPPORT_POLICY_REGISTRY if policy.model_id == "keysight-e36312a"
    )
    command_policy = next(policy for policy in model_policy.commands if policy.command == "measure")
    pending = next(
        scope for scope in command_policy.scopes if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
    )
    changed_pending = replace(
        pending,
        accepted_evidence_ids=pending.candidate_basis_evidence_ids,
        candidate_basis_evidence_ids=(),
    )
    changed_command = replace(
        command_policy,
        scopes=tuple(changed_pending if scope is pending else scope for scope in command_policy.scopes),
    )
    changed_model = replace(
        model_policy,
        commands=tuple(
            changed_command if policy is command_policy else policy
            for policy in model_policy.commands
        ),
    )
    registry = tuple(
        changed_model if policy is model_policy else policy
        for policy in LIVE_SUPPORT_POLICY_REGISTRY
    )
    with pytest.raises(ValueError, match="pending scope claims accepted evidence"):
        validate_live_support_metadata(registry)


def test_validated_features_explicitly_inherit_parent_evidence() -> None:
    for model_policy in LIVE_SUPPORT_POLICY_REGISTRY:
        for command_policy in model_policy.commands:
            for scope in command_policy.scopes:
                if scope.validation_status != VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
                    continue
                for feature in scope.feature_scopes:
                    assert feature.inherits_parent_accepted_evidence is True


def test_public_projection_is_schema_v2_and_redacts_evidence() -> None:
    projection = exact_live_support_metadata(
        model_id="keysight-e36312a",
        resource="USB0::FAKE::INSTR",
        backend=None,
        commands={"set", "sequence"},
    )
    assert projection["schema_version"] == 2
    assert projection["model_id"] == "keysight-e36312a"
    assert "model" not in projection
    serialized = json.dumps(projection)
    for forbidden in (
        "evidence_id",
        "accepted_evidence_ids",
        "candidate_basis_evidence_ids",
        ".tmp_tests",
        "report_sha256",
        "migration note",
    ):
        assert forbidden not in serialized
