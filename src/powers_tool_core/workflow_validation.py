"""Validation shared by adapters and core workflow execution."""

from __future__ import annotations

from typing import Any

from powers_tool_core.core import CoreValidationError, OperationRequest


GENERAL_PULSE_COMMANDS = frozenset(
    {
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "smoke-output",
    }
)

COMPLETION_PULSE_PLANNING_MODEL_ID = "keysight-e36312a"


def normalize_loop_count(value: Any, *, field: str = "loop_count") -> int:
    """Return the strict finite workflow iteration count."""

    if type(value) is not int or not 1 <= value <= 255:
        raise CoreValidationError(f"{field} must be an integer from 1 to 255")
    return value


def normalize_completion_pulse_channel(value: Any) -> int:
    """Return one strict output-channel anchor for a completion pulse."""

    if type(value) is not int or not 1 <= value <= 3:
        raise CoreValidationError("completion_pulse_channel must be an integer from 1 to 3")
    return value


def validate_general_workflow_parameters(request: OperationRequest) -> None:
    """Validate execution-relevant general workflow semantics."""

    if request.command not in GENERAL_PULSE_COMMANDS:
        return
    if request.command == "set" and request.parameters.get("voltage") is None and request.parameters.get("current") is None:
        raise CoreValidationError("set requires voltage, current, or both")
    if request.command != "ramp" and "completion_pulse_timing" in request.parameters:
        raise CoreValidationError("completion_pulse_timing is only accepted by ramp")
    if request.command == "ramp":
        normalize_loop_count(request.parameters.get("loop_count", 1))
    # Direct operation helpers remain public test/programmatic entry points;
    # admitted requests take the registry dependency path above this layer.
    if "completion_pulse_channel" in request.parameters:
        normalize_completion_pulse_channel(request.parameters["completion_pulse_channel"])
        if "completion_pulse_pins" not in request.parameters:
            raise CoreValidationError("completion_pulse_channel requires completion_pulse_pins")


def validate_completion_pulse_planning_model(
    request: OperationRequest,
    *,
    requested: bool,
    context: str = "completion-pulse options",
) -> None:
    """Require the E36312A physical model for no-hardware pulse planning."""

    if not requested or not (request.runtime.dry_run or request.runtime.simulate):
        return
    if request.runtime.planning_model_id == COMPLETION_PULSE_PLANNING_MODEL_ID:
        return
    selected = request.runtime.planning_profile_id or request.runtime.planning_model_id or "missing"
    raise CoreValidationError(
        f"{context} require planning_model_id {COMPLETION_PULSE_PLANNING_MODEL_ID!r}; "
        f"received {selected!r}"
    )
