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


@pytest.mark.parametrize("value", [True, False])
def test_restore_output_state_accepts_exact_booleans(value: bool) -> None:
    admitted = validate_request_admission(
        OperationRequest(
            "restore-from-snapshot",
            RuntimeOptions(dry_run=True),
            {"document": _snapshot(), "channel": 1, "restore_output_state": value},
        )
    )

    assert admitted.parameters["restore_output_state"] is value


def test_restore_output_state_omission_defaults_to_false() -> None:
    result = run_core_command(
        OperationRequest(
            "restore-from-snapshot",
            RuntimeOptions(dry_run=True),
            {"document": _snapshot(), "channel": 1},
        )
    )

    assert result["restore_output_state"] is False


@pytest.mark.parametrize("value", ["false", "true", 0, 1, 0.0, 1.0, None, [], {}])
def test_restore_output_state_rejects_non_booleans_before_open(value: object) -> None:
    opened = False

    def forbidden_opener(*args: object, **kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("opener must not be called")

    with pytest.raises(CoreValidationError, match="restore_output_state must be a boolean"):
        run_core_command(
            OperationRequest(
                "restore-from-snapshot",
                RuntimeOptions(resource="USB0::FAKE::INSTR"),
                {"document": _snapshot(), "channel": 1, "restore_output_state": value},
            ),
            opener=forbidden_opener,
        )

    assert opened is False


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_restore_rejects_non_boolean_output_state(value: object) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["outputs"][0]["enabled"] = value

    with pytest.raises(CoreValidationError, match=r"outputs\[\]\.enabled must be a boolean"):
        validate_snapshot_document(snapshot)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, [], {}])
def test_restore_rejects_non_boolean_ocp_enabled(value: object) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["protection_settings"][0]["protection"]["ocp_enabled"] = value

    with pytest.raises(CoreValidationError, match="ocp_enabled must be a boolean or null"):
        validate_snapshot_document(snapshot)


@pytest.mark.parametrize("section", ["outputs", "readback", "protection_settings"])
def test_restore_rejects_duplicate_snapshot_channels(section: str) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot[section].append(deepcopy(snapshot[section][0]))

    with pytest.raises(CoreValidationError, match=f"duplicate snapshot {section} channel"):
        validate_snapshot_document(snapshot)


@pytest.mark.parametrize("channel", [True, 1.0, "1", 0, -1])
def test_restore_rejects_invalid_snapshot_channel_types(channel: object) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["outputs"][0]["channel"] = channel

    with pytest.raises(CoreValidationError, match=r"outputs\[\]\.channel must be a positive integer"):
        validate_snapshot_document(snapshot)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -float("inf")])
def test_restore_rejects_invalid_setpoint_numbers(value: object) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["readback"][0]["setpoints"]["voltage"] = value

    with pytest.raises(CoreValidationError, match="setpoints.voltage must be a finite number"):
        validate_snapshot_document(snapshot)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ovp_voltage", True, "ovp_voltage must be a finite number"),
        ("ovp_voltage", float("nan"), "ovp_voltage must be a finite number"),
        ("ocp_delay", -0.1, "ocp_delay must be non-negative"),
        ("ocp_delay", float("inf"), "ocp_delay must be a finite number"),
        ("ocp_delay_trigger", "other", "ocp_delay_trigger must be one of"),
    ],
)
def test_restore_rejects_invalid_protection_values(
    field: str,
    value: object,
    message: str,
) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["protection_settings"][0]["protection"][field] = value

    with pytest.raises(CoreValidationError, match=message):
        validate_snapshot_document(snapshot)


def test_restore_rejects_empty_or_incomplete_readback_and_missing_output_channel() -> None:
    empty = deepcopy(_snapshot())
    empty["readback"] = []
    with pytest.raises(CoreValidationError, match="readback must not be empty"):
        validate_snapshot_document(empty)

    incomplete = deepcopy(_snapshot())
    del incomplete["readback"][0]["setpoints"]["current"]
    with pytest.raises(CoreValidationError, match="setpoints.current"):
        validate_snapshot_document(incomplete)

    missing_output = deepcopy(_snapshot())
    missing_output["outputs"] = missing_output["outputs"][1:]
    with pytest.raises(CoreValidationError, match="outputs does not contain channel 1"):
        validate_request_admission(
            OperationRequest(
                "restore-from-snapshot",
                RuntimeOptions(dry_run=True),
                {"document": missing_output, "channel": 1},
            )
        )
