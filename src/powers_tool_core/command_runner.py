"""Shared core command router for CLI and WebUI adapters."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from powers_tool_core import capabilities
from powers_tool_core.core import CoreValidationError, OperationRequest, SequenceRequest, TriggerRequest
from powers_tool_core.discovery import run_discovery
from powers_tool_core.instrument_io import run_instrument_io
from powers_tool_core.model_resolution import resolve_no_hardware_runtime
from powers_tool_core.operations import run_operation
from powers_tool_core.parameter_constraints import validate_request_parameters
from powers_tool_core.protection import run_protection
from powers_tool_core.ramp_list import run_ramp_list
from powers_tool_core.readonly import run_readonly
from powers_tool_core.restore import run_restore
from powers_tool_core.sequence import run_sequence
from powers_tool_core.snapshot import run_snapshot
from powers_tool_core.trigger import run_trigger
from powers_tool_core.stop_cleanup import CleanupReporter, stop_aware_opener
from powers_tool_core.workflow_validation import validate_general_workflow_parameters


def validate_request_admission(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    """Validate one command request without hardware I/O or state mutation."""

    validate_request_parameters(request)
    if isinstance(request, OperationRequest):
        validate_general_workflow_parameters(request)
    if isinstance(request, TriggerRequest) or request.command.startswith("trigger-"):
        from powers_tool_core.trigger import validate_trigger_request

        validate_trigger_request(request)

    if isinstance(request, SequenceRequest) or request.command == "sequence":
        from powers_tool_core.sequence import load_sequence_document, sequence_plan
        from powers_tool_core.support_features import sequence_feature_requirements

        document = request.parameters.get("document")
        if document is None and request.parameters.get("file") is not None:
            document = load_sequence_document(str(request.parameters["file"]))
        if document is None:
            raise CoreValidationError("sequence requires file or document")
        plan = sequence_plan(request, document)
        if (request.runtime.dry_run or request.runtime.simulate) and sequence_feature_requirements(plan):
            request = _apply_no_hardware_support_gate(request)
            sequence_plan(request, document)
        return request

    if request.command == "restore-from-snapshot":
        from powers_tool_core.restore import validate_restore_admission

        assert isinstance(request, OperationRequest)
        request = validate_restore_admission(request)
    else:
        request = _apply_no_hardware_support_gate(request)

    if request.command == "ramp-list":
        from powers_tool_core.ramp_list import ramp_list_document_for_request, ramp_list_plan

        ramp_list_plan(request, ramp_list_document_for_request(request))
    return request


def run_core_command(
    request: OperationRequest | TriggerRequest | SequenceRequest,
    *,
    opener: Callable[..., Any] | None = None,
    resource_lister: Callable[..., tuple[str, ...]] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
) -> dict[str, Any]:
    request = validate_request_admission(request)
    command = request.command
    if stop_requested is not None:
        opener = stop_aware_opener(
            opener or _default_opener,
            stop_requested=stop_requested,
            simulated=request.runtime.simulate,
            reporter=cleanup_reporter,
        )
    if isinstance(request, SequenceRequest) or command == "sequence":
        kwargs: dict[str, Any] = {"stop_requested": stop_requested}
        if opener is not None:
            kwargs["opener"] = opener
        return run_sequence(request, **kwargs)
    if command == "ramp-list":
        kwargs = {"stop_requested": stop_requested, "scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_ramp_list(request, **kwargs)
    if isinstance(request, TriggerRequest) or command.startswith("trigger-"):
        kwargs = {"stop_requested": stop_requested, "scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_trigger(request, **kwargs)
    if command in {"list-resources", "verify"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        if resource_lister is not None:
            kwargs["resource_lister"] = resource_lister
        return run_discovery(request, **kwargs)
    if command in {"clear", "error", "measure", "identify"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_instrument_io(request, **kwargs)
    if command in {"protection-status", "protection-set", "clear-protection"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_protection(request, **kwargs)
    if command == "snapshot":
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_snapshot(request, **kwargs)
    if command == "restore-from-snapshot":
        kwargs = {"scpi_logger": scpi_logger, "stop_requested": stop_requested}
        if opener is not None:
            kwargs["opener"] = opener
        return run_restore(request, **kwargs)
    if command in {"read-status", "readback", "measure-all"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_readonly(request, **kwargs)
    if command in {"set", "apply", "output-on", "output-off", "safe-off", "output-state", "cycle-output", "ramp", "smoke-output"}:
        kwargs = {"scpi_logger": scpi_logger, "stop_requested": stop_requested}
        if opener is not None:
            kwargs["opener"] = opener
        return run_operation(request, **kwargs)
    raise CoreValidationError(f"unsupported core command {command!r}")


def _apply_no_hardware_support_gate(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    if not (request.runtime.dry_run or request.runtime.simulate):
        return request
    if request.command not in capabilities.known_capability_commands():
        return request
    runtime = resolve_no_hardware_runtime(request.runtime)
    mode = "dry_run" if runtime.dry_run else "simulate"
    capabilities.ensure_command_supported(
        request.command,
        runtime.planning_model_id,
        runtime.planning_profile_id,
        mode,
    )
    return replace(request, runtime=runtime)


def _default_opener(*args: Any, **kwargs: Any) -> Any:
    from powers_tool_core.connection import open_resource

    return open_resource(*args, **kwargs)
