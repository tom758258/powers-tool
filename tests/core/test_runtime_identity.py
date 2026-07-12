from dataclasses import fields

import pytest

from powers_tool_core.core import CoreValidationError, RuntimeOptions
from powers_tool_core.model_resolution import (
    resolve_no_hardware_runtime,
    validate_live_expected_model,
    validate_runtime_identity,
)


def test_runtime_options_exposes_only_explicit_v2_identity_fields() -> None:
    field_names = {field.name for field in fields(RuntimeOptions)}

    assert "planning_model_id" in field_names
    assert "expected_model_id" in field_names
    assert "planning_profile_id" in field_names
    assert "model_profile" not in field_names


def test_dry_run_accepts_canonical_physical_planning_model() -> None:
    runtime = RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a")

    assert resolve_no_hardware_runtime(runtime).planning_model_id == "keysight-e36312a"


def test_dry_run_accepts_generic_scpi_planning_profile() -> None:
    runtime = RuntimeOptions(dry_run=True, planning_profile_id="generic-scpi")

    resolved = resolve_no_hardware_runtime(runtime)
    assert resolved.planning_profile_id == "generic-scpi"
    assert resolved.planning_model_id is None


def test_simulator_infers_canonical_model_from_deterministic_resource() -> None:
    runtime = RuntimeOptions(
        simulate=True,
        resource="USB0::SIM::E36312A::INSTR",
    )

    assert resolve_no_hardware_runtime(runtime).planning_model_id == "keysight-e36312a"


def test_simulator_rejects_explicit_resource_identity_mismatch() -> None:
    with pytest.raises(CoreValidationError, match="does not match deterministic SIM"):
        RuntimeOptions(
            simulate=True,
            resource="USB0::SIM::E36312A::INSTR",
            planning_model_id="keysight-e3646a",
        )


@pytest.mark.parametrize(
    ("runtime", "message"),
    [
        (
            {"dry_run": True, "planning_model_id": "keysight-e36312a", "planning_profile_id": "generic-scpi"},
            "mutually exclusive",
        ),
        ({"dry_run": True, "expected_model_id": "keysight-e36312a"}, "invalid in dry-run"),
        ({"simulate": True, "expected_model_id": "keysight-e36312a"}, "invalid in simulator"),
        ({"simulate": True, "planning_profile_id": "generic-scpi"}, "invalid in simulator"),
        ({"planning_model_id": "keysight-e36312a"}, "invalid in live"),
        ({"planning_profile_id": "generic-scpi"}, "invalid in live"),
    ],
)
def test_runtime_identity_mode_conflicts_fail_closed(
    runtime: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(CoreValidationError, match=message):
        RuntimeOptions(**runtime)


@pytest.mark.parametrize("value", ["E36312A", "GENERIC", "generic", "keysight-unknown"])
def test_noncanonical_runtime_identity_is_rejected(value: str) -> None:
    with pytest.raises(CoreValidationError):
        RuntimeOptions(dry_run=True, planning_model_id=value)


def test_live_expected_model_uses_canonical_model_ids() -> None:
    runtime = RuntimeOptions(expected_model_id="keysight-e36312a")

    validate_runtime_identity(runtime)
    assert (
        validate_live_expected_model(
            runtime.expected_model_id,
            "keysight-e36312a",
            command="set",
        )
        == "keysight-e36312a"
    )


def test_live_expected_model_mismatch_fails_closed() -> None:
    with pytest.raises(CoreValidationError, match="Expected model_id"):
        validate_live_expected_model(
            "keysight-e36312a",
            "keysight-e3646a",
            command="set",
        )
