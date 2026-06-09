"""Shared core command router for CLI and WebUI adapters."""

from __future__ import annotations

from typing import Any, Callable

from keysight_power_core.core import CoreValidationError, OperationRequest, SequenceRequest, TriggerRequest
from keysight_power_core.discovery import run_discovery
from keysight_power_core.instrument_io import run_instrument_io
from keysight_power_core.operations import run_operation
from keysight_power_core.protection import run_protection
from keysight_power_core.readonly import run_readonly
from keysight_power_core.restore import run_restore
from keysight_power_core.sequence import run_sequence
from keysight_power_core.snapshot import run_snapshot
from keysight_power_core.trigger import run_trigger
from keysight_power_core.stop_cleanup import CleanupReporter, stop_aware_opener


def run_core_command(
    request: OperationRequest | TriggerRequest | SequenceRequest,
    *,
    opener: Callable[..., Any] | None = None,
    resource_lister: Callable[..., tuple[str, ...]] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
) -> dict[str, Any]:
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


def _default_opener(*args: Any, **kwargs: Any) -> Any:
    from keysight_power_core.connection import open_resource

    return open_resource(*args, **kwargs)
