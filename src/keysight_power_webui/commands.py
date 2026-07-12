"""WebUI request mapping for shared core command execution."""

from __future__ import annotations

import inspect
from typing import Any

from powers_tool_core import capabilities as core_capabilities
from powers_tool_core.command_runner import run_core_command
from powers_tool_core.connection import SerialOptions, normalize_serial_termination, open_resource
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    TriggerRequest,
)
from powers_tool_core.discovery import IDN_QUERY, resource_payload
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import select_driver
from powers_tool_core.identity import IdentityResolutionError, resolve_physical_model_identity
from powers_tool_core.live_support import enforce_product_live_support_for_idn
from powers_tool_core.model_resolution import validate_live_expected_model
from powers_tool_core.models import parse_idn
from powers_tool_core.readonly import run_live_panel_read
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_PRODUCT,
    exact_live_support_metadata,
    live_support_policy_metadata,
    normalize_backend,
    normalize_transport,
)
from powers_tool_core.testing.simulator import SimulatedResourceManager

from .jobs import Job


MUTATING_COMMANDS = {
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "cycle-output",
    "ramp",
    "ramp-list",
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
    "ramp-list",
    "smoke-output",
    "protection-status",
    "protection-set",
    "clear-protection",
    "identify",
    "snapshot",
    "restore-from-snapshot",
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

MODEL_INDEPENDENT_DIAGNOSTICS = {"verify", "clear", "error"}


def channel_capabilities_by_model() -> dict[str, dict[str, Any]]:
    """Return WebUI model-to-channel metadata from driver capabilities."""

    from powers_tool_core.drivers.e36312a import E36312APowerSupply
    from powers_tool_core.drivers.e3646a import E3646APowerSupply
    from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
    from powers_tool_core.drivers.generic_scpi import GenericScpiPowerSupply

    return {
        "E36312A": {
            "channels": list(E36312APowerSupply.capabilities.channels),
            "output_control_scope": "per_channel",
        },
        "EDU36311A": {
            "channels": list(EDU36311APowerSupply.capabilities.channels),
            "output_control_scope": "per_channel",
        },
        "E3646A": {
            "channels": list(E3646APowerSupply.capabilities.channels),
            "output_control_scope": "global",
        },
        "GENERIC": {
            "channels": list(GenericScpiPowerSupply.capabilities.channels),
            "output_control_scope": "unknown",
        },
    }


def live_support_by_model(command_names: set[str]) -> dict[str, dict[str, Any]]:
    """Return safe Core-owned live-support projections for WebUI commands."""

    projections = {
        model: live_support_policy_metadata(model_id, command_names)
        for model, model_id in {
            "E36312A": "keysight-e36312a",
            "EDU36311A": "keysight-edu36311a",
            "E3646A": "keysight-e3646a",
        }.items()
    }
    generic_commands: dict[str, dict[str, Any]] = {}
    generic_capabilities = core_capabilities.command_support(None)
    for command in command_names:
        capability = generic_capabilities.get(command, {})
        reason = "GENERIC is no-hardware/fallback-only; live exact scopes are unavailable."
        generic_commands[command] = {
            "profile_validation_status": None,
            "profile_supported": bool(capability.get("simulate") or capability.get("dry_run")),
            "metadata_available": False,
            "policy_exempt": command in MODEL_INDEPENDENT_DIAGNOSTICS,
            "offline_only": False,
            "disabled_reason": reason,
            "support_reason": reason,
            "scopes": [],
        }
    projections["GENERIC"] = {
        "schema_version": 2,
        "evaluated": False,
        "model_id": None,
        "live_capable": False,
        "fallback_only": True,
        "commands": generic_commands,
    }
    return projections


def build_runtime_options(runtime_dict: dict[str, Any]) -> RuntimeOptions:
    simulate = bool(runtime_dict.get("simulate", False))
    resource = runtime_dict.get("resource")
    return RuntimeOptions(
        resource=resource,
        resource_alias=runtime_dict.get("resource_alias"),
        safety_config=runtime_dict.get("safety_config"),
        simulate=simulate,
        dry_run=bool(runtime_dict.get("dry_run", False)),
        backend=runtime_dict.get("backend"),
        model_profile=runtime_dict.get("model_profile") or runtime_dict.get("model"),
        timeout_ms=int(runtime_dict.get("timeout_ms", 5000)),
        log_scpi=bool(runtime_dict.get("log_scpi", False)),
        confirm=bool(runtime_dict.get("confirm", False)),
        serial_options=_serial_options_from_runtime(runtime_dict),
        serial_remote=bool(runtime_dict.get("serial_remote", False)),
        serial_local_on_close=bool(runtime_dict.get("serial_local_on_close", False)),
        # WebUI is deliberately product-only; P4 mode selection is CLI-only.
        support_policy_mode="product",
    )


def execute_job_command(job: Job) -> dict[str, Any]:
    runtime = build_runtime_options(job.runtime)
    command = job.command
    if command == "capabilities":
        return _capabilities(runtime)
    if command == "safety inspect":
        return _safety_inspect(runtime)
    if command in WEBUI_UNSUPPORTED_COMMANDS:
        raise CoreValidationError(f"not_implemented_in_webui: {command}")
    if command not in SHARED_CORE_COMMANDS:
        raise CoreValidationError(f"unknown_webui_command: {command}")
    if _requires_real_confirmation(command, runtime):
        raise ConfirmationRequiredError(f"Command '{command}' affects hardware output and requires explicit confirmation.")
    request = _request_for_job(command, runtime, job.parameters)
    def report_cleanup(result: Any) -> None:
        payload = result.to_dict()
        job.cleanup.append(payload)
        job.add_event("power_cleanup", payload)
        if payload["status"] == "unsupported":
            job.warnings.append({"code": "cleanup_unsupported", "message": payload["message"]})

    kwargs: dict[str, Any] = {"stop_requested": lambda: job.cancel_requested}
    if "cleanup_reporter" in inspect.signature(run_core_command).parameters:
        kwargs["cleanup_reporter"] = report_cleanup
    result = run_core_command(request, **kwargs)
    if command in {"identify", "verify"}:
        result = _with_diagnostic_live_support(command, runtime, result)
    if command == "ramp-list" and result.get("status") == "stopped":
        failed = result.get("failed_segment") or {}
        raise CommandCancelled(f"ramp-list stopped at segment {failed.get('index')}")
    if command == "ramp-list" and result.get("status") == "failed":
        failed = result.get("failed_segment") or {}
        raise CoreExecutionError(f"ramp-list segment {failed.get('index')} failed: {failed.get('message', 'segment failed')}")
    return result


def _with_diagnostic_live_support(
    command: str,
    runtime: RuntimeOptions,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Attach safe exact-scope metadata after an exempt diagnostic reads IDN."""

    resource_data = result.get("resource")
    idn = result.get("idn")
    if not isinstance(idn, dict) and isinstance(resource_data, dict):
        idn = resource_data.get("idn")
    manufacturer = idn.get("manufacturer") if isinstance(idn, dict) else None
    model = idn.get("model") if isinstance(idn, dict) else None
    if not isinstance(model, str) or not model.strip():
        return result
    try:
        identity = resolve_physical_model_identity(manufacturer, model)
    except IdentityResolutionError:
        if not runtime.simulate:
            validate_live_expected_model(
                runtime.model_profile,
                model,
                command=command,
            )
        live_support = _unsupported_detected_model_live_support(
            manufacturer,
            model,
            runtime,
        )
        return {**result, "live_support": live_support}
    if runtime.simulate:
        live_support = _unevaluated_live_support(
            model_id=identity.model_id,
            reported_manufacturer=manufacturer,
            reported_model=model,
            runtime=runtime,
        )
    else:
        validate_live_expected_model(
            runtime.model_profile,
            identity.canonical_model,
            command=command,
        )
        try:
            live_support = exact_live_support_metadata(
                model_id=identity.model_id,
                resource=runtime.resource,
                backend=runtime.backend,
            )
        except LiveSupportPolicyError:
            live_support = _unsupported_detected_model_live_support(
                manufacturer,
                model,
                runtime,
            )
    return {**result, "live_support": live_support}


def _unevaluated_live_support(
    *,
    model_id: str | None,
    reported_manufacturer: str | None,
    reported_model: str | None,
    runtime: RuntimeOptions,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "evaluated": False,
        "model_id": model_id,
        "reported_manufacturer": reported_manufacturer,
        "reported_model": reported_model,
        "transport_scope": normalize_transport(runtime.resource),
        "backend_scope": normalize_backend(runtime.backend),
        "policy_mode": SUPPORT_POLICY_MODE_PRODUCT,
        "commands": {},
        "reason": "Live exact-scope policy applies to real hardware only.",
    }


def _unsupported_detected_model_live_support(
    reported_manufacturer: str | None,
    reported_model: str | None,
    runtime: RuntimeOptions,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "evaluated": False,
        "model_id": None,
        "reported_manufacturer": reported_manufacturer,
        "reported_model": reported_model,
        "transport_scope": normalize_transport(runtime.resource),
        "backend_scope": normalize_backend(runtime.backend),
        "policy_mode": SUPPORT_POLICY_MODE_PRODUCT,
        "commands": {},
        "reason": (
            "The reported manufacturer and model do not resolve to active "
            "exact live-support metadata."
        ),
    }


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


def webui_command_support(command_names: set[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Return model-aware support metadata for visible WebUI commands."""

    return {
        model_key: _filtered_command_support(model, command_names)
        for model_key, model in {
            "E36312A": "E36312A",
            "EDU36311A": "EDU36311A",
            "E3646A": "E3646A",
            "GENERIC": None,
        }.items()
    }


def _serial_options_from_runtime(runtime_dict: dict[str, Any]) -> SerialOptions | None:
    serial = runtime_dict.get("serial_options")
    if not isinstance(serial, dict):
        return None
    options = SerialOptions(
        baud_rate=_optional_int(serial.get("baud_rate")),
        data_bits=_optional_int(serial.get("data_bits")),
        parity=_optional_str(serial.get("parity")),
        stop_bits=serial.get("stop_bits"),
        flow_control=_optional_str(serial.get("flow_control")),
        read_termination=normalize_serial_termination(serial.get("read_termination")),
        write_termination=normalize_serial_termination(serial.get("write_termination")),
    )
    return options if options.has_explicit_values() else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


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


def _capabilities(runtime: RuntimeOptions) -> dict[str, Any]:
    from powers_tool_core.drivers.e36312a import E36312APowerSupply
    from powers_tool_core.drivers.e3646a import E3646APowerSupply
    from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
    from powers_tool_core.setpoint_ranges import (
        setpoint_ranges_for_model_id,
        setpoint_ranges_for_model_profile,
    )

    if runtime.resource:
        manager = SimulatedResourceManager() if runtime.simulate else None
        try:
            with open_resource(
                runtime.resource,
                manager,
                backend=runtime.backend,
                timeout_ms=runtime.timeout_ms,
                serial_options=runtime.serial_options,
                serial_remote=runtime.serial_remote,
                serial_local_on_close=runtime.serial_local_on_close,
            ) as instrument:
                idn_raw = instrument.query(IDN_QUERY)
                if not runtime.simulate:
                    enforce_product_live_support_for_idn(
                        OperationRequest(command="capabilities", runtime=runtime), idn_raw
                    )
        except VisaConnectionError as exc:
            raise CoreValidationError(f"capabilities failed: {exc}") from exc

        selection = select_driver(idn_raw)
        caps = selection.capabilities
        live_support = (
            _unevaluated_live_support(
                model_id=(
                    selection.physical_identity.model_id
                    if selection.physical_identity is not None
                    else None
                ),
                reported_manufacturer=selection.idn.manufacturer,
                reported_model=selection.idn.model,
                runtime=runtime,
            )
            if runtime.simulate
            else exact_live_support_metadata(
                model_id=selection.physical_identity.model_id,
                resource=runtime.resource,
                backend=runtime.backend,
            )
        )
        return {
            "resource": resource_payload(
                runtime.resource,
                simulated=runtime.simulate,
                reachable=True,
                idn_raw=idn_raw,
            ),
            "driver": {
                "class": selection.driver_class.__name__,
                "reason": selection.reason,
            },
            "channels": list(caps.channels),
            "measure_channels": {
                "simulate": list(caps.simulated_measure_channels),
                "real": list(caps.real_measure_channels),
            },
            "hardware_validation": core_capabilities.hardware_validation_status(
                selection.physical_identity.model_id if selection.physical_identity else None
            ),
            "command_support": core_capabilities.command_support(
                selection.physical_identity.model_id if selection.physical_identity else None
            ),
            "live_support": live_support,
            "electrical_ratings": caps.electrical_ratings.to_dict() if caps.electrical_ratings else None,
            "setpoint_ranges": (
                setpoint_ranges_for_model_id(selection.physical_identity.model_id).to_dict()
                if selection.physical_identity
                and setpoint_ranges_for_model_id(selection.physical_identity.model_id)
                else None
            ),
        }

    return {
        "models": {
            "E36312A": {
                "channels": list(E36312APowerSupply.capabilities.channels),
                "electrical_ratings": E36312APowerSupply.capabilities.electrical_ratings.to_dict(),
                "setpoint_ranges": setpoint_ranges_for_model_profile("E36312A").to_dict(),
            },
            "EDU36311A": {
                "channels": list(EDU36311APowerSupply.capabilities.channels),
                "electrical_ratings": EDU36311APowerSupply.capabilities.electrical_ratings.to_dict(),
                "setpoint_ranges": setpoint_ranges_for_model_profile("EDU36311A").to_dict(),
            },
            "E3646A": {
                "channels": list(E3646APowerSupply.capabilities.channels),
                "electrical_ratings": None,
                "setpoint_ranges": setpoint_ranges_for_model_profile("E3646A").to_dict(),
            },
        }
    }


def _filtered_command_support(model: str | None, command_names: set[str]) -> dict[str, dict[str, Any]]:
    support = core_capabilities.planning_profile_command_support(model)
    filtered = {
        command: dict(support[command])
        for command in sorted(command_names)
        if command in support
    }
    for command, entry in filtered.items():
        if entry.get("real") is False:
            entry["disabled_reason"] = core_capabilities.unsupported_command_reason(
                command,
                model or "GENERIC",
            )
    for command in sorted(command_names & MODEL_INDEPENDENT_DIAGNOSTICS):
        filtered[command] = {
            "real": True,
            "simulate": True,
            "dry_run": False,
            "requires_confirm": False,
            "hardware_validation": "model_independent",
        }
    return filtered


def _safety_inspect(runtime: RuntimeOptions) -> dict[str, Any]:
    if runtime.safety_config is None:
        return {"safety_config_loaded": False}
    from powers_tool_core.safety import resolve_safety_config

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
