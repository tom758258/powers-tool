"""Adapter-neutral restore-from-snapshot command."""

from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path
from typing import Any, Callable

from powers_tool_core import capabilities
from powers_tool_core.connection import open_resource
from powers_tool_core.cancellation import StopRequested, raise_if_cancelled
from powers_tool_core.core import ConfirmationRequiredError, CoreIoError, CoreValidationError, OperationRequest, UnsupportedModelError
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.identity import IDENTITY_INDEXES, IdentityResolutionError, resolve_physical_model_identity
from powers_tool_core.models import parse_idn
from powers_tool_core.model_resolution import resolve_no_hardware_runtime
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.operations import IDN_QUERY, ScpiLoggingSession
from powers_tool_core.parameter_constraints import strict_boolean_parameter
from powers_tool_core.setpoint_limits import validate_effective_setpoint
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.snapshot import SNAPSHOT_KIND, SNAPSHOT_SCHEMA_VERSION


def run_restore(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    if request.command != "restore-from-snapshot":
        raise CoreValidationError(f"unsupported restore command {request.command!r}")
    request, snapshot = prepare_restore_request(request)
    restore_output_state = strict_boolean_parameter(
        request.parameters,
        "restore_output_state",
        default=False,
    )
    if request.runtime.dry_run or request.runtime.simulate:
        mode = "dry_run" if request.runtime.dry_run else "simulate"
        capabilities.ensure_command_supported(
            request.command,
            request.runtime.planning_model_id,
            request.runtime.planning_profile_id,
            mode,
        )
    channels = _restore_channels(request, snapshot)
    plan = restore_plan(
        snapshot,
        resource=str(request.runtime.resource),
        channels=channels,
        restore_output_state=restore_output_state,
        allow_output_on=restore_output_state and request.runtime.confirm,
    )
    if request.runtime.dry_run or request.runtime.simulate:
        return {
            "plan": plan,
            "restored_channels": list(channels),
            "restore_output_state": restore_output_state,
            "resource": request.runtime.resource,
        }
    if not request.runtime.confirm:
        raise ConfirmationRequiredError("restore-from-snapshot real execution requires confirmation")
    resource = request.runtime.resource
    if not resource:
        raise CoreValidationError("resource is required")
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    opened = False
    try:
        with opener(resource, manager, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            session = ScpiLoggingSession(resource, instrument, scpi_logger) if request.runtime.log_scpi and scpi_logger is not None else instrument
            idn_raw = session.query(IDN_QUERY)
            _validate_restore_identity(parse_idn(idn_raw), snapshot)
            enforce_live_support_for_idn(request, idn_raw)
            power_supply = create_power_supply(session, idn_raw)
            if not isinstance(power_supply, E36312APowerSupply):
                model = parse_idn(idn_raw).model
                raise UnsupportedModelError(
                    f"{capabilities.unsupported_command_message('restore-from-snapshot', model, 'live')}\n"
                    f"Found {type(power_supply).__name__} from *IDN? response."
                )
            _validate_restore_setpoints(power_supply, plan)
            _execute_restore_plan(power_supply, plan, stop_requested=stop_requested)
            _raise_on_instrument_errors(power_supply)
    except CoreValidationError:
        raise
    except VisaConnectionError as exc:
        raise CoreIoError(f"{'restore-from-snapshot failed' if opened else 'Could not open resource for restore-from-snapshot'}: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"restore-from-snapshot failed: {exc}", opened=opened) from exc
    return {"resource": resource, "restored_channels": list(channels), "plan": plan}


def restore_plan(
    snapshot: dict[str, Any],
    *,
    resource: str,
    channels: tuple[int, ...],
    restore_output_state: bool,
    allow_output_on: bool,
) -> dict[str, Any]:
    outputs = _records_by_channel(snapshot.get("outputs"))
    readback = _records_by_channel(snapshot.get("readback"))
    protection = _records_by_channel(snapshot.get("protection_settings"))
    steps: list[dict[str, Any]] = []
    for channel in channels:
        steps.append(_restore_step("output_off", f"OUTP OFF,(@{channel})", channel=channel))
        protection_record = protection.get(channel, {}).get("protection", {})
        ovp_voltage = protection_record.get("ovp_voltage")
        if ovp_voltage is not None:
            steps.append(_restore_step("set_over_voltage_protection", f"VOLT:PROT {_format_value(ovp_voltage)},(@{channel})", channel=channel, voltage=ovp_voltage))
        ocp_enabled = protection_record.get("ocp_enabled")
        if ocp_enabled is not None:
            ocp_command = "ON" if ocp_enabled else "OFF"
            steps.append(_restore_step("set_over_current_protection_enabled", f"CURR:PROT:STAT {ocp_command},(@{channel})", channel=channel, enabled=ocp_enabled))
        ocp_delay = protection_record.get("ocp_delay")
        if ocp_delay is not None:
            steps.append(_restore_step("set_over_current_protection_delay", f"CURR:PROT:DEL {_format_value(ocp_delay)},(@{channel})", channel=channel, seconds=ocp_delay))
        ocp_delay_trigger = protection_record.get("ocp_delay_trigger")
        if ocp_delay_trigger is not None:
            trigger_command = _ocp_delay_trigger_scpi(ocp_delay_trigger)
            steps.append(_restore_step("set_over_current_protection_delay_trigger", f"CURR:PROT:DEL:STAR {trigger_command},(@{channel})", channel=channel, trigger=ocp_delay_trigger))
        setpoints = readback.get(channel, {}).get("setpoints", {})
        if "current" not in setpoints or "voltage" not in setpoints:
            raise CoreValidationError(f"snapshot does not contain voltage/current setpoints for channel {channel}")
        steps.append(_restore_step("set_current_limit", f"CURR {_format_value(setpoints['current'])},(@{channel})", channel=channel, current=setpoints["current"]))
        steps.append(_restore_step("set_voltage", f"VOLT {_format_value(setpoints['voltage'])},(@{channel})", channel=channel, voltage=setpoints["voltage"]))
        if restore_output_state and allow_output_on and outputs.get(channel, {}).get("enabled") is True:
            steps.append(_restore_step("output_on", f"OUTP ON,(@{channel})", channel=channel))
    return {
        "operation": {"name": "restore-from-snapshot"},
        "target": {"resource": resource, "channels": list(channels)},
        "steps": [{"index": index, "type": "driver_action", **step} for index, step in enumerate(steps, start=1)],
        "description": "Restore output-off, protection settings, current, voltage, and optionally prior ON states.",
        "hardware_touched": False,
    }


def prepare_restore_request(
    request: OperationRequest,
) -> tuple[OperationRequest, dict[str, Any]]:
    """Validate snapshot identity and resolve no-hardware restore planning."""

    strict_boolean_parameter(request.parameters, "restore_output_state", default=False)
    snapshot = snapshot_document_for_request(request)
    snapshot_model_id = snapshot["resolved_identity"]["model_id"]
    if request.runtime.planning_profile_id is not None:
        raise CoreValidationError("planning_profile_id is invalid for restore-from-snapshot")
    if request.runtime.dry_run or request.runtime.simulate:
        explicit_model_id = request.runtime.planning_model_id
        if explicit_model_id is not None and explicit_model_id != snapshot_model_id:
            raise CoreValidationError(
                f"planning_model_id {explicit_model_id!r} does not match snapshot "
                f"model_id {snapshot_model_id!r}"
            )
        request = replace(
            request,
            runtime=replace(
                request.runtime,
                planning_model_id=snapshot_model_id,
            ),
        )
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
    return request, snapshot


def validate_restore_admission(request: OperationRequest) -> OperationRequest:
    """Validate restore document, identity, channels, and plan without I/O."""

    request, snapshot = prepare_restore_request(request)
    restore_output_state = strict_boolean_parameter(
        request.parameters,
        "restore_output_state",
        default=False,
    )
    channels = _restore_channels(request, snapshot)
    restore_plan(
        snapshot,
        resource=str(request.runtime.resource),
        channels=channels,
        restore_output_state=restore_output_state,
        allow_output_on=False,
    )
    return request


def snapshot_document_for_request(request: OperationRequest) -> dict[str, Any]:
    """Load and strictly validate one schema-2 snapshot document."""

    document = request.parameters.get("document")
    if isinstance(document, dict):
        return validate_snapshot_document(document)
    path = request.parameters.get("snapshot")
    if path is None:
        path = request.parameters.get("file")
    if path is None:
        raise CoreValidationError("restore-from-snapshot requires snapshot, file, or document")
    try:
        loaded = json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoreValidationError(str(exc)) from exc
    if not isinstance(loaded, dict):
        raise CoreValidationError("snapshot document must be a JSON object")
    return validate_snapshot_document(loaded)


def validate_snapshot_document(document: dict[str, Any]) -> dict[str, Any]:
    """Require the canonical schema-2 snapshot identity contract."""

    schema_version = document.get("schema_version")
    if type(schema_version) is not int or schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise CoreValidationError("snapshot requires integer schema_version=2")
    if document.get("kind") != SNAPSHOT_KIND:
        raise CoreValidationError(f"snapshot kind must be {SNAPSHOT_KIND!r}")
    reported = document.get("reported_identity")
    resolved = document.get("resolved_identity")
    if not isinstance(reported, dict):
        raise CoreValidationError("snapshot reported_identity must be an object")
    if not isinstance(resolved, dict):
        raise CoreValidationError("snapshot resolved_identity must be an object")
    if reported.get("parse_ok") is not True:
        raise CoreValidationError("snapshot reported_identity.parse_ok must be true")
    for field in ("manufacturer", "model", "serial", "firmware"):
        value = reported.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CoreValidationError(
                f"snapshot reported_identity.{field} must be a non-empty string"
            )
    try:
        identity = resolve_physical_model_identity(
            reported["manufacturer"],
            reported["model"],
        )
    except IdentityResolutionError as exc:
        raise CoreValidationError(
            "snapshot reported manufacturer and model do not resolve to a canonical physical identity"
        ) from exc
    model_info = IDENTITY_INDEXES.models_by_id[identity.model_id]
    expected_resolved = {
        "vendor_id": identity.vendor_id,
        "model_id": identity.model_id,
        "model_name": identity.canonical_model,
        "display_name": model_info.display_name,
    }
    if resolved != expected_resolved:
        raise CoreValidationError(
            "snapshot reported_identity conflicts with resolved_identity"
        )
    if identity.model_id != "keysight-e36312a":
        raise CoreValidationError(
            "snapshot model must be E36312A (model_id keysight-e36312a) "
            "for restore-from-snapshot"
        )
    outputs = _validate_output_records(document.get("outputs"))
    readback = _validate_readback_records(document.get("readback"))
    protection = _validate_protection_records(document.get("protection_settings"))
    if not outputs:
        raise CoreValidationError("snapshot outputs must not be empty")
    if not readback:
        raise CoreValidationError("snapshot readback must not be empty")
    missing_outputs = sorted(set(readback) - set(outputs))
    if missing_outputs:
        raise CoreValidationError(
            f"snapshot outputs does not contain channel {missing_outputs[0]}"
        )
    extra_outputs = sorted(set(outputs) - set(readback))
    if extra_outputs:
        raise CoreValidationError(
            f"snapshot readback does not contain output channel {extra_outputs[0]}"
        )
    extra_protection = sorted(set(protection) - set(readback))
    if extra_protection:
        raise CoreValidationError(
            f"snapshot readback does not contain protection channel {extra_protection[0]}"
        )
    return document


def _restore_channels(request: OperationRequest, snapshot: dict[str, Any]) -> tuple[int, ...]:
    available = sorted(_records_by_channel(snapshot.get("readback")))
    if not available:
        raise CoreValidationError("snapshot readback must not be empty")
    selected = request.parameters.get("channel", "all")
    if selected == "all":
        channels = tuple(channel for channel in available if channel in E36312APowerSupply.capabilities.channels)
        _require_output_channels(snapshot, channels)
        return channels
    try:
        channel = int(selected)
    except (TypeError, ValueError) as exc:
        raise CoreValidationError(f"invalid channel parameter {selected!r}") from exc
    if channel not in E36312APowerSupply.capabilities.channels:
        raise CoreValidationError(f"channel {channel} is not supported; supported: {E36312APowerSupply.capabilities.channels}")
    if channel not in available:
        raise CoreValidationError(f"snapshot does not contain channel {channel}")
    _require_output_channels(snapshot, (channel,))
    return (channel,)


def _restore_step(action: str, scpi: str, **parameters: Any) -> dict[str, Any]:
    return {"action": action, "command": scpi, "parameters": parameters}


def _ocp_delay_trigger_scpi(trigger: Any) -> str:
    if trigger == "setting-change":
        return "SCH"
    if trigger == "cc-transition":
        return "CCTR"
    raise CoreValidationError("ocp_delay_trigger must be one of: setting-change, cc-transition")


def _execute_restore_plan(
    power_supply: E36312APowerSupply,
    plan: dict[str, Any],
    *,
    stop_requested: StopRequested = None,
) -> None:
    for step in plan["steps"]:
        raise_if_cancelled(stop_requested)
        action = step["action"]
        parameters = step["parameters"]
        channel = parameters["channel"]
        if action == "output_off":
            power_supply.output_off(channel=channel)
        elif action == "set_over_voltage_protection":
            power_supply.set_over_voltage_protection(channel=channel, voltage=float(parameters["voltage"]))
        elif action == "set_over_current_protection_enabled":
            power_supply.set_over_current_protection_enabled(channel=channel, enabled=parameters["enabled"])
        elif action == "set_over_current_protection_delay":
            power_supply.set_over_current_protection_delay(channel=channel, seconds=float(parameters["seconds"]))
        elif action == "set_over_current_protection_delay_trigger":
            power_supply.set_over_current_protection_delay_trigger(channel=channel, trigger=str(parameters["trigger"]))
        elif action == "set_current_limit":
            power_supply.set_current_limit(channel=channel, current=float(parameters["current"]))
        elif action == "set_voltage":
            power_supply.set_voltage(channel=channel, voltage=float(parameters["voltage"]))
        elif action == "output_on":
            power_supply.output_on(channel=channel)
        else:
            raise CoreValidationError(f"unsupported restore action: {action}")


def _validate_restore_setpoints(power_supply: E36312APowerSupply, plan: dict[str, Any]) -> None:
    pending: dict[int, dict[str, float]] = {}
    for step in plan["steps"]:
        parameters = step["parameters"]
        channel = parameters.get("channel")
        if not isinstance(channel, int):
            continue
        values = pending.setdefault(channel, {})
        if step["action"] == "set_current_limit":
            values["current"] = float(parameters["current"])
        elif step["action"] == "set_voltage":
            values["voltage"] = float(parameters["voltage"])
    for channel, values in pending.items():
        validate_effective_setpoint(
            model="E36312A",
            channel=channel,
            electrical_ratings=power_supply.capabilities.electrical_ratings,
            voltage=values.get("voltage"),
            current=values.get("current"),
        )


def _validate_restore_identity(idn: Any, snapshot: dict[str, Any]) -> None:
    expected_model_id = snapshot["resolved_identity"]["model_id"]
    expected_serial = snapshot["reported_identity"]["serial"]
    try:
        connected = resolve_physical_model_identity(idn.manufacturer, idn.model)
    except IdentityResolutionError as exc:
        raise CoreValidationError(
            "connected manufacturer and model do not resolve to a canonical physical identity"
        ) from exc
    if connected.model_id != expected_model_id:
        raise CoreValidationError(
            f"connected model_id {connected.model_id!r} does not match snapshot "
            f"model_id {expected_model_id!r}"
        )
    if idn.serial != expected_serial:
        raise CoreValidationError(f"connected serial {idn.serial!r} does not match snapshot serial {expected_serial!r}")


def _raise_on_instrument_errors(power_supply: E36312APowerSupply) -> None:
    errors, _read_count = power_supply.read_error_queue(20)
    if errors:
        raise CoreValidationError("instrument reported errors after restore-from-snapshot: " + "; ".join(errors))


def _records_by_channel(records: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        return {}
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            channel = int(record.get("channel"))
        except (TypeError, ValueError):
            continue
        by_channel[channel] = record
    return by_channel


def _validated_channel_records(records: Any, section: str) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        raise CoreValidationError(f"snapshot {section} must be a list")
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise CoreValidationError(f"snapshot {section} entries must be objects")
        channel = record.get("channel")
        if type(channel) is not int or channel <= 0:
            raise CoreValidationError(
                f"snapshot {section}[].channel must be a positive integer"
            )
        if channel not in E36312APowerSupply.capabilities.channels:
            raise CoreValidationError(
                f"snapshot {section}[].channel {channel} is not supported"
            )
        if channel in by_channel:
            raise CoreValidationError(f"duplicate snapshot {section} channel {channel}")
        by_channel[channel] = record
    return by_channel


def _validate_output_records(records: Any) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(records, "outputs")
    for record in by_channel.values():
        if type(record.get("enabled")) is not bool:
            raise CoreValidationError("snapshot outputs[].enabled must be a boolean")
    return by_channel


def _validate_readback_records(records: Any) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(records, "readback")
    for record in by_channel.values():
        setpoints = record.get("setpoints")
        if not isinstance(setpoints, dict):
            raise CoreValidationError("snapshot readback[].setpoints must be an object")
        for field in ("voltage", "current"):
            _require_finite_number(
                setpoints.get(field),
                f"snapshot readback[].setpoints.{field}",
            )
    return by_channel


def _validate_protection_records(records: Any) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(records, "protection_settings")
    for record in by_channel.values():
        protection = record.get("protection")
        if not isinstance(protection, dict):
            raise CoreValidationError(
                "snapshot protection_settings[].protection must be an object"
            )
        ovp_voltage = protection.get("ovp_voltage")
        if ovp_voltage is not None:
            _require_finite_number(
                ovp_voltage,
                "snapshot protection_settings[].protection.ovp_voltage",
            )
        ocp_enabled = protection.get("ocp_enabled")
        if ocp_enabled is not None and type(ocp_enabled) is not bool:
            raise CoreValidationError("snapshot ocp_enabled must be a boolean or null")
        ocp_delay = protection.get("ocp_delay")
        if ocp_delay is not None:
            _require_finite_number(
                ocp_delay,
                "snapshot protection_settings[].protection.ocp_delay",
            )
            if float(ocp_delay) < 0:
                raise CoreValidationError("snapshot ocp_delay must be non-negative")
        ocp_delay_trigger = protection.get("ocp_delay_trigger")
        if ocp_delay_trigger is not None and ocp_delay_trigger not in {
            "setting-change",
            "cc-transition",
        }:
            raise CoreValidationError(
                "snapshot ocp_delay_trigger must be one of: setting-change, cc-transition, null"
            )
    return by_channel


def _require_finite_number(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreValidationError(f"{field} must be a finite number")
    if not math.isfinite(float(value)):
        raise CoreValidationError(f"{field} must be a finite number")


def _require_output_channels(snapshot: dict[str, Any], channels: tuple[int, ...]) -> None:
    outputs = _records_by_channel(snapshot.get("outputs"))
    for channel in channels:
        if channel not in outputs:
            raise CoreValidationError(f"snapshot outputs does not contain channel {channel}")


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)
