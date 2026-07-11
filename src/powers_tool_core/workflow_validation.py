"""Validation shared by adapters and core workflow execution."""

from __future__ import annotations

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
