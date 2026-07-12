from __future__ import annotations

from copy import deepcopy

import pytest

from powers_tool_core.command_runner import run_core_command, validate_request_admission
from powers_tool_core.core import CoreValidationError, OperationRequest, RuntimeOptions
from powers_tool_core.models import parse_idn
from powers_tool_core.restore import _validate_restore_identity, validate_snapshot_document


def _snapshot() -> dict[str, object]:
    return run_core_command(
        OperationRequest(
            "snapshot",
            RuntimeOptions(
                simulate=True,
                resource="USB0::SIM::E36312A::INSTR",
            ),
        )
    )


def test_snapshot_document_uses_schema_2_canonical_identity() -> None:
    snapshot = _snapshot()

    assert snapshot["schema_version"] == 2
    assert type(snapshot["schema_version"]) is int
    assert snapshot["kind"] == "powers-tool-snapshot"
    assert snapshot["reported_identity"] == {
        "manufacturer": "KEYSIGHT",
        "model": "E36312A",
        "serial": "SIM000003",
        "firmware": "1.0",
        "parse_ok": True,
    }
    assert snapshot["resolved_identity"] == {
        "vendor_id": "keysight",
        "model_id": "keysight-e36312a",
        "model_name": "E36312A",
        "display_name": "Keysight E36312A",
    }
    assert "idn" not in snapshot


@pytest.mark.parametrize("schema_version", [None, 1, "2", 2.0, True, False, 3])
def test_restore_rejects_invalid_snapshot_schema_versions(schema_version: object) -> None:
    snapshot = _snapshot()
    snapshot["schema_version"] = schema_version

    with pytest.raises(CoreValidationError, match="integer schema_version=2"):
        validate_snapshot_document(snapshot)


def test_restore_rejects_wrong_kind_and_cli_envelope() -> None:
    snapshot = _snapshot()
    wrong_kind = {**snapshot, "kind": "legacy-snapshot"}

    with pytest.raises(CoreValidationError, match="snapshot kind"):
        validate_snapshot_document(wrong_kind)
    with pytest.raises(CoreValidationError, match="snapshot kind"):
        validate_request_admission(
            OperationRequest(
                "restore-from-snapshot",
                RuntimeOptions(dry_run=True),
                {"document": {"schema_version": 2, "data": snapshot}},
            )
        )


def test_restore_rejects_conflicting_reported_and_resolved_identity() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["reported_identity"]["manufacturer"] = "OTHER"

    with pytest.raises(CoreValidationError, match="do not resolve"):
        validate_snapshot_document(snapshot)


def test_restore_no_hardware_admission_derives_snapshot_model_and_rejects_mismatch() -> None:
    snapshot = _snapshot()
    admitted = validate_request_admission(
        OperationRequest(
            "restore-from-snapshot",
            RuntimeOptions(dry_run=True),
            {"document": snapshot, "channel": 1},
        )
    )
    assert admitted.runtime.planning_model_id == "keysight-e36312a"

    with pytest.raises(CoreValidationError, match="does not match snapshot"):
        validate_request_admission(
            OperationRequest(
                "restore-from-snapshot",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
                {"document": snapshot, "channel": 1},
            )
        )
    with pytest.raises(CoreValidationError, match="does not match deterministic SIM"):
        validate_request_admission(
            OperationRequest(
                "restore-from-snapshot",
                RuntimeOptions(
                    simulate=True,
                    resource="ASRL1::SIM::E3646A::INSTR",
                ),
                {"document": snapshot, "channel": 1},
            )
        )


def test_real_restore_identity_compares_vendor_qualified_model_and_serial() -> None:
    snapshot = _snapshot()

    with pytest.raises(CoreValidationError, match="do not resolve"):
        _validate_restore_identity(
            parse_idn("OTHER,E36312A,SIM0001,1.0"),
            snapshot,
        )
    with pytest.raises(CoreValidationError, match="connected serial"):
        _validate_restore_identity(
            parse_idn("KEYSIGHT TECHNOLOGIES,E36312A,OTHER,1.0"),
            snapshot,
        )
