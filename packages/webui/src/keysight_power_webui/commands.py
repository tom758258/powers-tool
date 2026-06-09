"""WebUI request mapping for shared core command execution."""

from __future__ import annotations

from typing import Any

from keysight_power_core.command_runner import run_core_command
from keysight_power_core.core import (
    ConfirmationRequiredError,
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    TriggerRequest,
)
from keysight_power_core.readonly import run_live_panel_read

from .jobs import Job


MUTATING_COMMANDS = {
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "cycle-output",
    "ramp",
    "smoke-output",
    "sequence",
    "protection-set",
    "clear-protection",
    "restore-from-snapshot",
}

TRIGGER_COMMANDS = {
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
}

SHARED_CORE_COMMANDS = {
    "list-resources",
    "verify",
    "clear",
    "error",
    "measure",
    "measure-all",
    "read-status",
    "readback",
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "output-state",
    "cycle-output",
    "ramp",
    "smoke-output",
    "protection-status",
    "protection-set",
    "clear-protection",
    "identify",
    "snapshot",
    "sequence",
    *TRIGGER_COMMANDS,
}

WEBUI_UNSUPPORTED_COMMANDS = {
    "doctor",
    "validate-readonly",
    "snapshot-diff",
    "hardware-report",
    "log",
}


def build_runtime_options(runtime_dict: dict[str, Any]) -> RuntimeOptions:
    simulate = bool(runtime_dict.get("simulate", False))
    resource = runtime_dict.get("resource")
    if simulate and not resource:
        resource = "USB0::SIM::E36312A::INSTR"
    return RuntimeOptions(
        resource=resource,
        resource_alias=runtime_dict.get("resource_alias"),
        safety_config=runtime_dict.get("safety_config"),
        simulate=simulate,
        dry_run=bool(runtime_dict.get("dry_run", False)),
        backend=runtime_dict.get("backend"),
        timeout_ms=int(runtime_dict.get("timeout_ms", 5000)),
        log_scpi=bool(runtime_dict.get("log_scpi", False)),
        confirm=bool(runtime_dict.get("confirm", False)),
    )


def execute_job_command(job: Job) -> dict[str, Any]:
    runtime = build_runtime_options(job.runtime)
    command = job.command
    if command == "capabilities":
        return _capabilities()
    if command == "safety inspect":
        return _safety_inspect(runtime)
    if command in WEBUI_UNSUPPORTED_COMMANDS:
        raise CoreValidationError(f"not_implemented_in_webui: {command}")
    if command not in SHARED_CORE_COMMANDS:
        raise CoreValidationError(f"unknown_webui_command: {command}")
    if _requires_real_confirmation(command, runtime):
        raise ConfirmationRequiredError(f"Command '{command}' affects hardware output and requires explicit confirmation.")
    request = _request_for_job(command, runtime, job.parameters)
    return run_core_command(request, stop_requested=lambda: job.cancel_requested)


def execute_live_readonly(command: str, runtime: RuntimeOptions, parameters: dict[str, Any]) -> dict[str, Any]:
    if command not in {"measure", "measure-all", "read-status", "readback", "protection-status", "snapshot"}:
        raise CoreValidationError(f"live data command is not read-only: {command}")
    request = _request_for_job(command, runtime, parameters)
    return run_core_command(request)


def execute_live_panel_read(runtime: RuntimeOptions, parameters: dict[str, Any]) -> dict[str, Any]:
    request = OperationRequest(command="live-panel", runtime=runtime, parameters=_normalize_parameters(parameters))
    return run_live_panel_read(request)


def _request_for_job(command: str, runtime: RuntimeOptions, parameters: dict[str, Any]) -> OperationRequest | TriggerRequest | SequenceRequest:
    normalized_parameters = _normalize_parameters(parameters)
    if command == "list-resources":
        normalized_parameters["live_only"] = bool(normalized_parameters.get("live_only", False))
    if command == "clear-protection" and normalized_parameters.get("channel") == "all":
        normalized_parameters["all"] = True
    if command in TRIGGER_COMMANDS:
        return TriggerRequest(command=command, runtime=runtime, parameters=normalized_parameters)
    if command == "sequence":
        return SequenceRequest(command=command, runtime=runtime, parameters=normalized_parameters)
    return OperationRequest(command=command, runtime=runtime, parameters=normalized_parameters)


def _normalize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)
    if "channel" in normalized:
        normalized["channel"] = _normalize_channel(normalized["channel"])
    return normalized


def _normalize_channel(channel: Any) -> Any:
    if not isinstance(channel, str):
        return channel
    if channel == "all":
        return channel
    stripped = channel.strip()
    if stripped.isdecimal() and int(stripped) > 0:
        return int(stripped)
    return channel


def _requires_real_confirmation(command: str, runtime: RuntimeOptions) -> bool:
    return command in MUTATING_COMMANDS and not runtime.simulate and not runtime.dry_run and not runtime.confirm


def _capabilities() -> dict[str, Any]:
    from keysight_power_core.drivers.e36312a import E36312APowerSupply
    from keysight_power_core.drivers.edu36311a import EDU36311APowerSupply

    return {
        "models": {
            "E36312A": {"channels": list(E36312APowerSupply.capabilities.channels)},
            "EDU36311A": {"channels": list(EDU36311APowerSupply.capabilities.channels)},
        }
    }


def _safety_inspect(runtime: RuntimeOptions) -> dict[str, Any]:
    if runtime.safety_config is None:
        return {"safety_config_loaded": False}
    from keysight_power_core.safety import resolve_safety_config

    config = resolve_safety_config(
        runtime.safety_config,
        resource=None if runtime.resource_alias is not None else runtime.resource,
        resource_alias=runtime.resource_alias,
    )
    return {
        "safety_config_loaded": True,
        "limits": {
            "max_voltage": config.limits.max_voltage,
            "max_current": config.limits.max_current,
            "allowed_channels": list(config.limits.allowed_channels),
        },
    }
