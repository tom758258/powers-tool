"""Adapter-neutral restore-from-snapshot command."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Callable

from keysight_power_core import capabilities
from keysight_power_core.connection import open_resource
from keysight_power_core.cancellation import StopRequested, raise_if_cancelled
from keysight_power_core.core import ConfirmationRequiredError, CoreIoError, CoreValidationError, OperationRequest, UnsupportedModelError
from keysight_power_core.drivers.e36312a import E36312APowerSupply
from keysight_power_core.errors import VisaConnectionError
from keysight_power_core.factory import create_power_supply
from keysight_power_core.models import parse_idn
from keysight_power_core.model_resolution import resolve_no_hardware_runtime, validate_live_expected_model
from keysight_power_core.live_support import enforce_product_live_support_for_idn
from keysight_power_core.operations import IDN_QUERY, ScpiLoggingSession
from keysight_power_core.setpoint_limits import validate_effective_setpoint
from keysight_power_core.testing.simulator import SimulatedResourceManager


def run_restore(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    if request.command != "restore-from-snapshot":
        raise CoreValidationError(f"unsupported restore command {request.command!r}")
    snapshot = _snapshot_document(request)
    if request.runtime.dry_run or request.runtime.simulate:
        if request.runtime.model_profile is None:
            snapshot_idn = snapshot.get("idn") if isinstance(snapshot.get("idn"), dict) else {}
            snapshot_model = snapshot_idn.get("model")
            if isinstance(snapshot_model, str) and snapshot_model:
                request = replace(request, runtime=replace(request.runtime, model_profile=snapshot_model))
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
        mode = "dry_run" if request.runtime.dry_run else "simulate"
        capabilities.ensure_command_supported(request.command, request.runtime.model_profile, mode)
    channels = _restore_channels(request, snapshot)
    plan = restore_plan(
        snapshot,
        resource=str(request.runtime.resource),
        channels=channels,
        restore_output_state=bool(request.parameters.get("restore_output_state", False)),
        allow_output_on=bool(request.parameters.get("restore_output_state", False)) and request.runtime.confirm,
    )
    if request.runtime.dry_run or request.runtime.simulate:
        return {
            "plan": plan,
            "restored_channels": list(channels),
            "restore_output_state": bool(request.parameters.get("restore_output_state", False)),
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
            validate_live_expected_model(request.runtime.model_profile, parse_idn(idn_raw).model, command=request.command)
            _validate_restore_identity(parse_idn(idn_raw), snapshot.get("idn") if isinstance(snapshot.get("idn"), dict) else {})
            enforce_product_live_support_for_idn(request, idn_raw)
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
            ocp_command = "ON" if bool(ocp_enabled) else "OFF"
            steps.append(_restore_step("set_over_current_protection_enabled", f"CURR:PROT:STAT {ocp_command},(@{channel})", channel=channel, enabled=bool(ocp_enabled)))
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


def _snapshot_document(request: OperationRequest) -> dict[str, Any]:
    document = request.parameters.get("document")
    if isinstance(document, dict):
        return document
    path = request.parameters.get("snapshot")
    if path is None:
        path = request.parameters.get("file")
    if path is None:
        raise CoreValidationError("restore-from-snapshot requires snapshot, file, or document")
    try:
        loaded = json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoreValidationError(str(exc)) from exc
    if isinstance(loaded, dict) and isinstance(loaded.get("data"), dict):
        return loaded["data"]
    if not isinstance(loaded, dict):
        raise CoreValidationError("snapshot document must be a JSON object")
    return loaded


def _restore_channels(request: OperationRequest, snapshot: dict[str, Any]) -> tuple[int, ...]:
    available = sorted(_records_by_channel(snapshot.get("readback")))
    if not available:
        available = list(E36312APowerSupply.capabilities.channels)
    selected = request.parameters.get("channel", "all")
    if selected == "all":
        return tuple(channel for channel in available if channel in E36312APowerSupply.capabilities.channels)
    try:
        channel = int(selected)
    except (TypeError, ValueError) as exc:
        raise CoreValidationError(f"invalid channel parameter {selected!r}") from exc
    if channel not in E36312APowerSupply.capabilities.channels:
        raise CoreValidationError(f"channel {channel} is not supported; supported: {E36312APowerSupply.capabilities.channels}")
    if channel not in available:
        raise CoreValidationError(f"snapshot does not contain channel {channel}")
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
            power_supply.set_over_current_protection_enabled(channel=channel, enabled=bool(parameters["enabled"]))
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


def _validate_restore_identity(idn: Any, expected_idn: dict[str, Any]) -> None:
    expected_model = expected_idn.get("model")
    expected_serial = expected_idn.get("serial")
    if expected_model != "E36312A":
        raise CoreValidationError(f"snapshot model must be E36312A for real restore; found {expected_model!r}")
    if idn.model != expected_model:
        raise CoreValidationError(f"connected model {idn.model!r} does not match snapshot model {expected_model!r}")
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


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)
