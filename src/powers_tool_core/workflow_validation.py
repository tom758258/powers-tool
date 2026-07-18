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

REMOVED_GENERAL_WORKFLOW_FIELDS = frozenset(
    {
        "completion_pulse_mode",
        "completion_pulse_dwell_ms",
        "wait_timeout_ms",
        "poll_ms",
    }
)

COMPLETION_PULSE_PLANNING_MODEL_ID = "keysight-e36312a"


def normalize_loop_count(value: Any, *, field: str = "loop_count") -> int:
    """Return the strict finite workflow iteration count."""

    if type(value) is not int or not 1 <= value <= 255:
        raise CoreValidationError(f"{field} must be an integer from 1 to 255")
    return value


def validate_general_workflow_parameters(request: OperationRequest) -> None:
    """Reject removed or command-inapplicable general workflow fields."""

    if request.command not in GENERAL_PULSE_COMMANDS:
        return
    if request.command == "set" and request.parameters.get("voltage") is None and request.parameters.get("current") is None:
        raise CoreValidationError("set requires voltage, current, or both")
    removed = sorted(REMOVED_GENERAL_WORKFLOW_FIELDS.intersection(request.parameters))
    if removed:
        raise CoreValidationError(
            f"{request.command} does not accept removed Native LIST/trigger-wait field(s): {', '.join(removed)}"
        )
    if request.command != "ramp" and "completion_pulse_timing" in request.parameters:
        raise CoreValidationError("completion_pulse_timing is only accepted by ramp")


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
