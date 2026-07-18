"""Versioned multi-segment software ramp list runtime."""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from powers_tool_core.cancellation import interruptible_sleep, raise_if_cancelled
from powers_tool_core.connection import open_resource
from powers_tool_core.core import (
    CommandCancelled,
    CoreIoError,
    CoreValidationError,
    CoreVerificationError,
    OperationRequest,
)
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.models import parse_idn
from powers_tool_core.model_resolution import (
    no_hardware_channels,
    resolve_no_hardware_runtime,
)
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.operations import (
    ScpiLoggingSession,
    _require_confirmation_if_needed,
    ramp_voltages,
)
from powers_tool_core.safety import SafetyConfigError, SafetyValidationError, resolve_safety_config, validate_setpoint
from powers_tool_core.setpoint_limits import validate_effective_setpoint
from powers_tool_core.stop_cleanup import CleanupReporter, cancel_workflow_with_safe_off
from powers_tool_core.trigger import run_post_action_completion_pulse
from powers_tool_core.workflow_validation import normalize_loop_count, validate_completion_pulse_planning_model

RAMP_LIST_KIND = "powers-tool-ramp-list"
RAMP_LIST_VERSION_V2 = 2
RAMP_LIST_VERSION = 4
MAX_RAMP_SEGMENTS = 10
SEGMENT_FIELDS = frozenset(
    {
        "channel",
        "current",
        "start_voltage",
        "stop_voltage",
        "step_voltage",
        "delay_ms",
        "hold_ms",
    }
)
OUTPUT_WRITE_POWER_SUPPLY_TYPES = (E36312APowerSupply, E3646APowerSupply, EDU36311APowerSupply)


def run_ramp_list(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
) -> dict[str, Any]:
    """Lint, plan, or execute a versioned ramp list."""

    request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
    document = ramp_list_document_for_request(request)
    plan = ramp_list_plan(request, document)
    if request.runtime.simulate:
        _validate_known_simulated_plan(request, plan)
    if request.parameters.get("lint", False):
        return {
            "status": "valid",
            "ramp_list_version": plan["version"],
            "segment_count": len(plan["segments"]),
            "loop_count": plan["loop_count"],
            "completed_loops": 0,
            "completed_segment_executions": 0,
            "completed_segments": 0,
            "segments": plan["segments"],
            "plan": plan,
        }
    if request.runtime.dry_run or request.runtime.simulate:
        return {
            "status": "planned",
            "ramp_list_version": plan["version"],
            "segment_count": len(plan["segments"]),
            "loop_count": plan["loop_count"],
            "completed_loops": 0,
            "completed_segment_executions": 0,
            "completed_segments": 0,
            "failed_segment": None,
            "stopped": False,
            "segments": plan["segments"],
            "plan": plan,
            "enable_output": plan["enable_output"],
            "output_enable_executed": False,
            "enabled_channels": [],
            "final_output_states": [
                {
                    "channel": channel,
                    "enabled": None,
                    "verified": False,
                    "unchanged_by_workflow": not plan["enable_output"],
                }
                for channel in _ordered_plan_channels(plan)
            ],
            "cancellation_cleanup": None,
        }
    return execute_ramp_list(
        request,
        plan,
        opener=opener,
        sleep=sleep,
        scpi_logger=scpi_logger,
        stop_requested=stop_requested,
        cleanup_reporter=cleanup_reporter,
    )


def ramp_list_document_for_request(request: OperationRequest) -> dict[str, Any]:
    document = request.parameters.get("document")
    file_path = request.parameters.get("file")
    if document is not None and file_path is not None:
        raise CoreValidationError("ramp-list accepts either file or document, not both")
    if document is None:
        if file_path is None:
            raise CoreValidationError("ramp-list requires file or document")
        document = load_ramp_list_document(str(file_path))
    if not isinstance(document, dict):
        raise CoreValidationError("ramp-list document must be a JSON object")
    return document


def load_ramp_list_document(path: str) -> dict[str, Any]:
    ramp_path = Path(path)
    try:
        document = json.loads(ramp_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"could not read ramp-list file {ramp_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CoreValidationError(f"could not parse ramp-list JSON {ramp_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise CoreValidationError("ramp-list file must contain a JSON object")
    return document


def ramp_list_plan(request: OperationRequest, document: dict[str, Any]) -> dict[str, Any]:
    if request.parameters.get("loop_count") is not None:
        document = {**document, "loop_count": request.parameters["loop_count"], "version": RAMP_LIST_VERSION}
    if document.get("kind") != RAMP_LIST_KIND:
        raise CoreValidationError(f"ramp-list kind must be {RAMP_LIST_KIND!r}")
    version = document.get("version")
    if type(version) is not int or version not in {RAMP_LIST_VERSION_V2, 3, RAMP_LIST_VERSION}:
        raise CoreValidationError(f"unsupported ramp-list version: {version!r}")
    allowed_fields = {"kind", "version", "completion_pulse", "segments"}
    if version in {3, RAMP_LIST_VERSION}:
        allowed_fields.add("enable_output")
    if version == RAMP_LIST_VERSION:
        allowed_fields.add("loop_count")
    unknown = sorted(set(document) - allowed_fields)
    if unknown:
        raise CoreValidationError(f"unsupported ramp-list field(s): {', '.join(unknown)}")
    if version in {3, RAMP_LIST_VERSION}:
        if "enable_output" not in document:
            raise CoreValidationError(f"ramp-list version {version} requires enable_output")
        if type(document["enable_output"]) is not bool:
            raise CoreValidationError("ramp-list enable_output must be a boolean")
        enable_output = document["enable_output"]
    else:
        enable_output = False
    loop_count = normalize_loop_count(document.get("loop_count", 1), field="ramp-list loop_count")
    raw_segments = document.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise CoreValidationError("ramp-list requires 1 to 10 segments")
    if len(raw_segments) > MAX_RAMP_SEGMENTS:
        raise CoreValidationError("ramp-list supports at most 10 segments")

    segments = [
        normalize_ramp_segment(request, index, raw_segment)
        for index, raw_segment in enumerate(raw_segments, start=1)
    ]
    completion_pulse = normalize_completion_pulse(document.get("completion_pulse"))
    if completion_pulse and completion_pulse["timing"] == "loop" and loop_count < 2:
        raise CoreValidationError("ramp-list loop completion pulse requires loop_count of at least 2")
    validate_completion_pulse_planning_model(
        request,
        requested=completion_pulse is not None,
        context="ramp-list completion_pulse",
    )
    return {
        "kind": RAMP_LIST_KIND,
        "version": version,
        "operation": {"name": "ramp-list"},
        "target": {
            "resource": request.runtime.resource,
            "resource_alias": request.runtime.resource_alias,
            "planning_model_id": request.runtime.planning_model_id,
            "planning_profile_id": request.runtime.planning_profile_id,
        },
        "segment_count": len(segments),
        "loop_count": loop_count,
        "enable_output": enable_output,
        "completion_pulse": completion_pulse,
        "segments": segments,
        "hardware_touched": False,
    }


def normalize_completion_pulse(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CoreValidationError("ramp-list completion_pulse must be a JSON object")
    unknown = sorted(set(raw) - {"timing", "pins", "polarity"})
    if unknown:
        raise CoreValidationError(f"ramp-list completion_pulse has unsupported field(s): {', '.join(unknown)}")
    timing = raw.get("timing", "segment")
    polarity = raw.get("polarity", "positive")
    pins = raw.get("pins")
    if timing not in {"segment", "step", "loop"}:
        raise CoreValidationError("ramp-list completion_pulse timing must be segment, step, or loop")
    if polarity not in {"positive", "negative"}:
        raise CoreValidationError("ramp-list completion_pulse polarity must be positive or negative")
    if not isinstance(pins, list) or not pins or any(isinstance(pin, bool) or not isinstance(pin, int) or pin not in {1, 2, 3} for pin in pins):
        raise CoreValidationError("ramp-list completion_pulse pins must be a non-empty list containing rear pins 1, 2, or 3")
    if len(set(pins)) != len(pins):
        raise CoreValidationError("ramp-list completion_pulse pins must not contain duplicates")
    return {"timing": timing, "pins": list(pins), "polarity": polarity}


def normalize_ramp_segment(request: OperationRequest, index: int, raw_segment: Any) -> dict[str, Any]:
    if not isinstance(raw_segment, dict):
        raise CoreValidationError(f"ramp-list segment {index} must be a JSON object")
    unknown = sorted(set(raw_segment) - SEGMENT_FIELDS)
    missing = sorted(SEGMENT_FIELDS - set(raw_segment))
    if unknown:
        raise CoreValidationError(f"ramp-list segment {index} has unsupported field(s): {', '.join(unknown)}")
    if missing:
        raise CoreValidationError(f"ramp-list segment {index} is missing field(s): {', '.join(missing)}")
    try:
        channel = _strict_integer(raw_segment["channel"])
        current = float(raw_segment["current"])
        start_voltage = float(raw_segment["start_voltage"])
        stop_voltage = float(raw_segment["stop_voltage"])
        step_voltage = float(raw_segment["step_voltage"])
        delay_ms = _strict_integer(raw_segment["delay_ms"])
        hold_ms = _strict_integer(raw_segment["hold_ms"])
    except (TypeError, ValueError) as exc:
        raise CoreValidationError(f"ramp-list segment {index} contains an invalid numeric value") from exc
    if any(isinstance(raw_segment[field], bool) for field in ("current", "start_voltage", "stop_voltage", "step_voltage")):
        raise CoreValidationError(f"ramp-list segment {index} contains an invalid numeric value")
    if channel < 1:
        raise CoreValidationError(f"ramp-list segment {index} channel must be a positive integer")
    if (
        (request.runtime.dry_run or request.runtime.simulate)
        and (
            request.runtime.planning_model_id is not None
            or request.runtime.planning_profile_id is not None
        )
        and channel not in no_hardware_channels(
            request.runtime.planning_model_id,
            request.runtime.planning_profile_id,
        )
    ):
        supported = no_hardware_channels(
            request.runtime.planning_model_id,
            request.runtime.planning_profile_id,
        )
        raise CoreValidationError(
            f"ramp-list segment {index} channel {channel} is not supported; supported: {supported}"
        )
    if delay_ms < 0:
        raise CoreValidationError(f"ramp-list segment {index} delay_ms must be non-negative")
    if hold_ms < 0:
        raise CoreValidationError(f"ramp-list segment {index} hold_ms must be non-negative")
    if not math.isfinite(step_voltage) or step_voltage <= 0:
        raise CoreValidationError(f"ramp-list segment {index} step_voltage must be a positive finite number")
    try:
        voltages = ramp_voltages(start_voltage, stop_voltage, step_voltage)
    except CoreValidationError as exc:
        raise CoreValidationError(f"ramp-list segment {index}: {exc}") from exc
    limits = _safety_limits(request, channel=channel, model=None)
    try:
        for voltage in voltages:
            validate_setpoint(channel=channel, voltage=voltage, current=current, limits=limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        raise CoreValidationError(f"ramp-list segment {index}: {exc}") from exc
    return {
        "index": index,
        "channel": channel,
        "current": current,
        "start_voltage": start_voltage,
        "stop_voltage": stop_voltage,
        "step_voltage": step_voltage,
        "delay_ms": delay_ms,
        "hold_ms": hold_ms,
        "voltage_count": len(voltages),
        "voltages": voltages,
    }


def execute_ramp_list(
    request: OperationRequest,
    plan: dict[str, Any],
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
) -> dict[str, Any]:
    resource = request.runtime.resource
    if resource is None:
        raise CoreValidationError("resource is required")
    results: list[dict[str, Any]] = []
    failed_segment: dict[str, Any] | None = None
    stopped = False
    idn_raw: str | None = None
    opened = False
    try:
        with opener(
            resource,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            serial_options=request.runtime.serial_options,
            serial_remote=request.runtime.serial_remote,
            serial_local_on_close=request.runtime.serial_local_on_close,
        ) as instrument:
            opened = True
            session = (
                ScpiLoggingSession(resource, instrument, scpi_logger)
                if request.runtime.log_scpi and scpi_logger is not None
                else instrument
            )
            idn_raw = session.query("*IDN?")
            enforce_live_support_for_idn(request, idn_raw)
            power_supply = create_power_supply(session, idn_raw)
            if not isinstance(power_supply, OUTPUT_WRITE_POWER_SUPPLY_TYPES):
                raise CoreValidationError(
                    f"ramp-list real execution is only supported for E36312A, E3646A, or EDU36311A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            _validate_plan_for_power_supply(request, plan, power_supply, idn_raw)
            if plan.get("completion_pulse") and not isinstance(power_supply, E36312APowerSupply):
                raise CoreValidationError("ramp-list completion pulses are only supported for E36312A")
            enabled_channels: list[int] = []
            completed_loops = 0
            for loop_index in range(1, plan["loop_count"] + 1):
                for segment in plan["segments"]:
                    try:
                        raise_if_cancelled(stop_requested)
                        result = execute_ramp_segment(
                            power_supply,
                            segment,
                            completion_pulse=(None if (plan.get("completion_pulse") or {}).get("timing") == "loop" else plan.get("completion_pulse")),
                            enable_channel=(
                                plan["enable_output"]
                                and segment["channel"] not in enabled_channels
                            ),
                            on_channel_enabled=(
                                lambda channel: enabled_channels.append(channel)
                                if channel not in enabled_channels
                                else None
                            ),
                            sleep=sleep,
                            stop_requested=stop_requested,
                        )
                        result["loop_index"] = loop_index
                        results.append(result)
                    except (CommandCancelled, KeyboardInterrupt) as exc:
                        cancel_workflow_with_safe_off(
                        power_supply,
                        partial_result={
                            "ramp_list_version": plan["version"],
                            "enable_output": plan["enable_output"],
                            "output_enable_executed": bool(enabled_channels),
                            "enabled_channels": list(enabled_channels),
                            "completed_segments": len(results),
                            "segments": results,
                            "failed_segment": {
                                "loop_index": loop_index,
                                "index": segment["index"],
                                "channel": segment["channel"],
                                "code": "interrupted",
                                "message": str(exc),
                            },
                        },
                            reporter=cleanup_reporter,
                        )
                    except (VisaConnectionError, ValueError, CoreValidationError) as exc:
                        failed_segment = {
                            "loop_index": loop_index,
                            "index": segment["index"],
                            "channel": segment["channel"],
                            "code": "segment_failed",
                            "message": str(exc),
                        }
                        break
                if failed_segment is not None:
                    break
                completed_loops += 1
            if (plan.get("completion_pulse") or {}).get("timing") == "loop" and completed_loops == plan["loop_count"]:
                last_channel = plan["segments"][-1]["channel"]
                run_post_action_completion_pulse(power_supply, channel=last_channel, pins=plan["completion_pulse"]["pins"], polarity=plan["completion_pulse"]["polarity"])
            final_output_states = (
                [
                    {
                        "channel": channel,
                        "enabled": power_supply.output_state(channel=channel),
                        "verified": True,
                        "unchanged_by_workflow": False,
                    }
                    for channel in enabled_channels
                ]
                if plan["enable_output"] and failed_segment is None
                else [
                    {
                        "channel": channel,
                        "enabled": None,
                        "verified": False,
                        "unchanged_by_workflow": not plan["enable_output"],
                    }
                    for channel in _ordered_plan_channels(plan)
                ]
            )
            if plan["enable_output"] and failed_segment is None:
                differences = [
                    state for state in final_output_states if state["enabled"] is not True
                ]
                if differences:
                    raise CoreVerificationError(
                        "ramp-list final output-state verification failed",
                        verification={
                            "operation": "ramp-list-final-output-state",
                            "passed": False,
                            "checks": final_output_states,
                            "differences": differences,
                        },
                    )
                errors, _read_count = power_supply.read_error_queue(20)
                if errors:
                    raise ValueError(f"instrument errors: {errors}")
            try:
                raise_if_cancelled(stop_requested)
            except CommandCancelled as exc:
                cancel_workflow_with_safe_off(
                    power_supply,
                    partial_result={
                        "ramp_list_version": plan["version"],
                        "enable_output": plan["enable_output"],
                        "output_enable_executed": bool(enabled_channels),
                        "enabled_channels": list(enabled_channels),
                        "completed_segments": len(results),
                        "segments": results,
                        "failed_segment": {
                            "code": "interrupted",
                            "message": str(exc),
                        },
                    },
                    reporter=cleanup_reporter,
                )
    except VisaConnectionError as exc:
        prefix = "ramp-list failed" if opened else "Could not open resource for ramp-list"
        raise CoreIoError(f"{prefix}: {exc}", opened=opened) from exc

    parsed = parse_idn(idn_raw or "")
    return {
        "ramp_list_version": plan["version"],
        "resource": resource,
        "resource_alias": request.runtime.resource_alias,
        "idn": {
            "raw": idn_raw,
            "manufacturer": parsed.manufacturer,
            "model": parsed.model,
            "serial": parsed.serial,
            "firmware": parsed.firmware,
            "parse_ok": parsed.parse_ok,
        },
        "status": "stopped" if stopped else ("failed" if failed_segment else "completed"),
        "segment_count": len(plan["segments"]),
        "completed_segments": len(results),
        "loop_count": plan["loop_count"],
        "completed_loops": completed_loops,
        "completed_segment_executions": len(results),
        "failed_segment": failed_segment,
        "stopped": stopped,
        "segments": results,
        "plan": plan,
        "enable_output": plan["enable_output"],
        "output_enable_executed": bool(enabled_channels),
        "enabled_channels": enabled_channels,
        "final_output_states": final_output_states,
        "cancellation_cleanup": None,
    }


def execute_ramp_segment(
    power_supply: Any,
    segment: dict[str, Any],
    *,
    completion_pulse: dict[str, Any] | None,
    enable_channel: bool,
    on_channel_enabled: Callable[[int], None],
    sleep: Callable[[float], None],
    stop_requested: Callable[[], bool] | None,
) -> dict[str, Any]:
    channel = segment["channel"]
    triggers: list[dict[str, Any]] = []
    trigger: dict[str, Any] | None = None
    raise_if_cancelled(stop_requested)
    power_supply.set_current_limit(channel=channel, current=segment["current"])
    for voltage_index, voltage in enumerate(segment["voltages"]):
        raise_if_cancelled(stop_requested)
        power_supply.set_voltage(channel=channel, voltage=voltage)
        if voltage_index == 0 and enable_channel:
            power_supply.output_on(channel=channel)
            if power_supply.output_state(channel=channel) is not True:
                raise CoreVerificationError(
                    "ramp-list output-on verification failed",
                    verification={
                        "operation": "ramp-list-output-on",
                        "passed": False,
                        "checks": [{"channel": channel, "expected": True}],
                        "differences": [{"channel": channel, "expected": True}],
                    },
                )
            on_channel_enabled(channel)
        if completion_pulse and completion_pulse["timing"] == "step":
            pulse = run_post_action_completion_pulse(
                power_supply,
                channel=channel,
                pins=completion_pulse["pins"],
                polarity=completion_pulse["polarity"],
            )
            triggers.append({"step_index": voltage_index, "voltage": voltage, "trigger": pulse})
        if segment["delay_ms"] > 0 and voltage_index < len(segment["voltages"]) - 1:
            interruptible_sleep(segment["delay_ms"] / 1000, sleep=sleep, stop_requested=stop_requested)
    if segment["hold_ms"] > 0:
        interruptible_sleep(segment["hold_ms"] / 1000, sleep=sleep, stop_requested=stop_requested)
    if completion_pulse and completion_pulse["timing"] == "segment":
        trigger = run_post_action_completion_pulse(
            power_supply,
            channel=channel,
            pins=completion_pulse["pins"],
            polarity=completion_pulse["polarity"],
        )
    errors, _read_count = power_supply.read_error_queue(20)
    if errors:
        raise ValueError(f"instrument errors: {errors}")
    result = {
        "index": segment["index"],
        "channel": channel,
        "current": segment["current"],
        "start_voltage": segment["start_voltage"],
        "stop_voltage": segment["stop_voltage"],
        "voltage_count": segment["voltage_count"],
        "delay_ms": segment["delay_ms"],
        "hold_ms": segment["hold_ms"],
        "status": "completed",
    }
    if trigger is not None:
        result["trigger"] = trigger
    if triggers:
        result["triggers"] = triggers
    return result


def _validate_plan_for_power_supply(
    request: OperationRequest,
    plan: dict[str, Any],
    power_supply: Any,
    idn_raw: str,
) -> None:
    model = parse_idn(idn_raw).model
    for segment in plan["segments"]:
        channel = segment["channel"]
        if channel not in power_supply.capabilities.channels:
            raise CoreValidationError(
                f"ramp-list segment {segment['index']} channel {channel} is not supported; "
                f"supported: {power_supply.capabilities.channels}"
            )
        limits = _safety_limits(request, channel=channel, model=model)
        try:
            for voltage in segment["voltages"]:
                validate_setpoint(channel=channel, voltage=voltage, current=segment["current"], limits=limits)
                validate_effective_setpoint(
                    model=model,
                    channel=channel,
                    electrical_ratings=power_supply.capabilities.electrical_ratings,
                    safety_limits=limits,
                    voltage=voltage,
                    current=segment["current"],
                )
                if plan["enable_output"]:
                    _require_confirmation_if_needed(
                        request,
                        voltage,
                        segment["current"],
                        channel,
                        idn_raw,
                    )
        except (SafetyConfigError, SafetyValidationError) as exc:
            raise CoreValidationError(f"ramp-list segment {segment['index']}: {exc}") from exc


def _safety_limits(request: OperationRequest, *, channel: int, model: str | None) -> Any:
    if request.runtime.safety_config is None:
        return None
    try:
        return resolve_safety_config(
            request.runtime.safety_config,
            resource=None if request.runtime.resource_alias is not None else request.runtime.resource,
            resource_alias=request.runtime.resource_alias,
            model=model,
            channel=channel,
        ).limits
    except SafetyConfigError as exc:
        raise CoreValidationError(str(exc)) from exc


def _strict_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("value must be an integer")
    return value


def _validate_known_simulated_plan(request: OperationRequest, plan: dict[str, Any]) -> None:
    from powers_tool_core.electrical_ratings import ratings_for_model_id
    from powers_tool_core.identity import planning_model_id_from_sim_resource
    from powers_tool_core.testing.simulator import SIMULATED_IDN

    idn = SIMULATED_IDN.get(request.runtime.resource or "")
    model = parse_idn(idn).model if idn else None
    ratings = ratings_for_model_id(planning_model_id_from_sim_resource(request.runtime.resource))
    if ratings is None:
        return
    for segment in plan["segments"]:
        limits = _safety_limits(request, channel=segment["channel"], model=model)
        try:
            for voltage in segment["voltages"]:
                validate_effective_setpoint(
                    model=model,
                    channel=segment["channel"],
                    electrical_ratings=ratings,
                    safety_limits=limits,
                    voltage=voltage,
                    current=segment["current"],
                )
        except SafetyValidationError as exc:
            raise CoreValidationError(f"ramp-list segment {segment['index']}: {exc}") from exc


def _ordered_plan_channels(plan: dict[str, Any]) -> list[int]:
    channels: list[int] = []
    for segment in plan["segments"]:
        if segment["channel"] not in channels:
            channels.append(segment["channel"])
    return channels
