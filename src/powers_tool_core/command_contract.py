"""Fail-closed, adapter-neutral command parameter admission contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from powers_tool_core.core import CoreValidationError, OperationRequest, SequenceRequest, TriggerRequest


_MISSING = object()


@dataclass(frozen=True)
class Field:
    kind: str
    required: bool = False
    nullable: bool = False
    default: Any = _MISSING
    values: frozenset[str] = frozenset()
    allow_all: bool = False


@dataclass(frozen=True)
class CommandContract:
    fields: Mapping[str, Field]
    aliases: Mapping[str, str] = None  # alias -> canonical
    mutually_exclusive: tuple[tuple[str, ...], ...] = ()


def _fields(*names: str, **typed: Field) -> dict[str, Field]:
    result = {name: Field("any") for name in names}
    result.update(typed)
    return result


BOOLEAN_FALSE = Field("bool", default=False)
POSITIVE_INTEGER = Field("int", required=False)
NUMBER = Field("number")
CHANNEL = Field("channel")
ALL_CHANNEL = Field("channel", allow_all=True)
STRING = Field("string")
DOCUMENT = Field("object")


_PULSE_FIELDS = {
    "completion_pulse_pins": Field("pin_list"),
    "completion_pulse_polarity": Field("enum", default="positive", values=frozenset({"positive", "negative"})),
    "completion_pulse_channel": Field("pulse_channel"),
    "leave_trigger_configured": BOOLEAN_FALSE,
}
_VERIFY_FIELDS = {
    "verify_after_write": BOOLEAN_FALSE,
    "settle_ms": Field("nonnegative_int", default=0),
    "setpoint_voltage_tolerance": Field("nonnegative_number", default=0.001),
    "setpoint_current_tolerance": Field("nonnegative_number", default=0.001),
}


COMMAND_CONTRACTS: dict[str, CommandContract] = {
    "list-resources": CommandContract(_fields(live_only=BOOLEAN_FALSE)),
    "verify": CommandContract({}),
    "clear": CommandContract({}),
    "error": CommandContract(_fields(max_reads=Field("positive_int", default=20))),
    "measure": CommandContract(_fields(channel=CHANNEL)),
    "measure-all": CommandContract({}),
    "read-status": CommandContract(_fields(channel=ALL_CHANNEL, max_errors=Field("positive_int", default=20))),
    "readback": CommandContract(_fields(channel=ALL_CHANNEL)),
    "identify": CommandContract({}),
    "snapshot": CommandContract(_fields(max_errors=Field("positive_int", default=20))),
    "protection-status": CommandContract(_fields(channel=ALL_CHANNEL, all=BOOLEAN_FALSE)),
    "protection-set": CommandContract(_fields(
        channel=ALL_CHANNEL,
        all=BOOLEAN_FALSE,
        ovp_voltage=Field("nonnegative_number"),
        ocp=Field("enum", values=frozenset({"on", "off"})),
        ocp_delay=Field("nonnegative_number"),
        ocp_delay_trigger=Field("enum", values=frozenset({"setting-change", "cc-transition"})),
    )),
    "clear-protection": CommandContract(_fields(channel=ALL_CHANNEL, all=BOOLEAN_FALSE)),
    "set": CommandContract(_fields(channel=CHANNEL, voltage=Field("nonnegative_number"), current=Field("nonnegative_number"), **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "apply": CommandContract(_fields(channel=ALL_CHANNEL, voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True), no_output=BOOLEAN_FALSE, **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "output-on": CommandContract(_fields(channel=ALL_CHANNEL, **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "output-off": CommandContract(_fields(channel=ALL_CHANNEL, **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "safe-off": CommandContract(_fields(channel=ALL_CHANNEL, **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "output-state": CommandContract(_fields(channel=ALL_CHANNEL)),
    "cycle-output": CommandContract(_fields(channel=ALL_CHANNEL, duration_ms=Field("positive_int", default=500), **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "ramp": CommandContract(_fields(
        channel=CHANNEL,
        current=Field("nonnegative_number", required=True),
        start_voltage=Field("nonnegative_number", required=True),
        stop_voltage=Field("nonnegative_number", required=True),
        step_voltage=Field("positive_number", required=True),
        delay_ms=Field("nonnegative_int", default=0),
        enable_output=BOOLEAN_FALSE,
        loop_count=Field("range_int", default=1),
        completion_pulse_timing=Field("enum", default="segment", values=frozenset({"segment", "step", "loop"})),
        **_VERIFY_FIELDS,
        **_PULSE_FIELDS,
    )),
    "smoke-output": CommandContract(_fields(channel=CHANNEL, voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True), duration_ms=Field("positive_int", default=500), **_VERIFY_FIELDS, **_PULSE_FIELDS)),
    "ramp-list": CommandContract(_fields(file=STRING, document=DOCUMENT, lint=BOOLEAN_FALSE, loop_count=Field("range_int")), mutually_exclusive=(("file", "document"),)),
    "sequence": CommandContract(_fields(file=STRING, document=DOCUMENT, lint=BOOLEAN_FALSE, loop_count=Field("range_int")), mutually_exclusive=(("file", "document"),)),
    "restore-from-snapshot": CommandContract(_fields(document=DOCUMENT, snapshot=STRING, file=STRING, channel=ALL_CHANNEL, restore_output_state=BOOLEAN_FALSE), mutually_exclusive=(("document", "snapshot", "file"),)),
    "trigger-pulse": CommandContract(_fields(channel=CHANNEL, pin=Field("pin"), pins=Field("pin_list"), polarity=Field("enum", default="positive", values=frozenset({"positive", "negative"})), exclusive_pins=BOOLEAN_FALSE, max_errors=Field("positive_int", default=20)), mutually_exclusive=(("pin", "pins"),)),
    "trigger-status": CommandContract(_fields(channel=ALL_CHANNEL, max_errors=Field("positive_int", default=20))),
    "trigger-step": CommandContract(_fields(
        channel=CHANNEL,
        source=Field("enum", default="bus", values=frozenset({"bus", "immediate", "pin1", "pin2", "pin3", "ext"})),
        voltage=Field("nonnegative_number"), current=Field("nonnegative_number"), fire=BOOLEAN_FALSE,
        wait_complete=BOOLEAN_FALSE, wait_timeout_ms=Field("positive_int", default=10000), poll_ms=Field("min50_int", default=200),
        **_PULSE_FIELDS,
    )),
    "trigger-list": CommandContract(_fields(
        channel=CHANNEL,
        source=Field("enum", default="bus", values=frozenset({"bus", "immediate", "pin1", "pin2", "pin3", "ext"})),
        voltages=Field("number_list"), currents=Field("number_list"), dwell=Field("number_list"),
        bost_list=Field("bool_list"), eost_list=Field("bool_list"), trigger_output_pins=Field("pin_list"),
        trigger_output_polarity=Field("enum", values=frozenset({"positive", "negative"})),
        count=Field("range_count", default=1), fire=BOOLEAN_FALSE, wait_complete=BOOLEAN_FALSE, exclusive_pins=BOOLEAN_FALSE,
        wait_timeout_ms=Field("positive_int", default=10000), poll_ms=Field("min50_int", default=200),
        completion_pulse_pins=Field("pin_list"), completion_pulse_polarity=Field("enum", values=frozenset({"positive", "negative"})),
        pins=Field("pin_list"), polarity=Field("enum", values=frozenset({"positive", "negative"})), leave_trigger_configured=BOOLEAN_FALSE,
    ), aliases={"voltage_list": "voltages", "current_list": "currents", "dwell_list": "dwell"}, mutually_exclusive=(("voltages", "voltage_list"), ("currents", "current_list"), ("dwell", "dwell_list"))),
    "trigger-fire": CommandContract(_fields(channel=CHANNEL, wait_complete=BOOLEAN_FALSE, wait_timeout_ms=Field("positive_int", default=10000), poll_ms=Field("min50_int", default=200))),
    "trigger-abort": CommandContract(_fields(channel=ALL_CHANNEL, max_errors=Field("positive_int", default=20))),
}

SEQUENCE_ACTION_CONTRACTS: dict[str, CommandContract] = {
    "measure": CommandContract(_fields(channel=Field("channel", default=1))),
    "readback": CommandContract(_fields(channel=Field("channel", default=1))),
    "output-state": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "log": CommandContract(_fields(message=Field("string", default=""))),
    "wait": CommandContract(_fields(seconds=Field("nonnegative_number", required=True)), aliases={"duration_sec": "seconds"}, mutually_exclusive=(("seconds", "duration_sec"),)),
    "trigger-pulse": CommandContract(_fields(channel=Field("channel", default=1), pins=Field("pin_list"), polarity=Field("enum", default="positive", values=frozenset({"positive", "negative"})), leave_trigger_configured=BOOLEAN_FALSE)),
    "safe-off": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "output-on": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "output-off": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "cycle-output": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True), duration_ms=Field("positive_int", default=500))),
    "set": CommandContract(_fields(channel=Field("channel", default=1), voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True))),
    "apply": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True), voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True), no_output=BOOLEAN_FALSE)),
}


def command_parameter_names(command: str) -> frozenset[str]:
    """Return the Core-owned allowed parameter names for an adapter request."""

    contract = COMMAND_CONTRACTS.get(command)
    if contract is None:
        return frozenset()
    return frozenset(contract.fields)


def validate_sequence_action_parameters(action: str, parameters: Any) -> dict[str, Any]:
    """Validate one parsed Sequence action through the Core contract registry."""

    contract = SEQUENCE_ACTION_CONTRACTS[action]
    if not isinstance(parameters, dict):
        raise CoreValidationError(f"sequence {action} parameters must be an object")
    raw = dict(parameters)
    aliases = contract.aliases or {}
    for group in contract.mutually_exclusive:
        present = [name for name in group if name in raw]
        if len(present) > 1:
            raise CoreValidationError(f"sequence {action} alias conflict: {', '.join(present)}")
    for alias, canonical in aliases.items():
        if alias in raw:
            raw[canonical] = raw.pop(alias)
    unknown = sorted(set(raw) - set(contract.fields))
    if unknown:
        raise CoreValidationError(f"sequence {action} has inapplicable field(s): {', '.join(unknown)}")
    normalized: dict[str, Any] = {}
    for name, field in contract.fields.items():
        if name not in raw:
            continue
        value = raw[name]
        if value is None:
            raise CoreValidationError(f"sequence {action} {name} must not be null")
        normalized[name] = _normalize_field(name, value, field)
    for name, field in contract.fields.items():
        if name not in normalized:
            if field.required:
                raise CoreValidationError(f"sequence {action} requires {name}")
            if field.default is not _MISSING:
                normalized[name] = field.default
    return normalized


def validate_and_normalize_request(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    """Return an admitted request whose parameters contain only canonical typed values."""

    contract = COMMAND_CONTRACTS.get(request.command)
    if contract is None:
        raise CoreValidationError(f"unsupported core command {request.command!r}")
    if not isinstance(request.parameters, dict):
        raise CoreValidationError("parameters must be an object")
    raw = dict(request.parameters)
    aliases = contract.aliases or {}
    for group in contract.mutually_exclusive:
        present = [name for name in group if name in raw]
        if len(present) > 1:
            if any(name in aliases for name in present) or any(name in aliases.values() for name in present):
                raise CoreValidationError(f"alias conflict: {', '.join(present)} cannot be supplied together")
            raise CoreValidationError(f"mutually exclusive fields: {', '.join(present)}")
    for alias, canonical in aliases.items():
        if alias in raw:
            raw[canonical] = raw.pop(alias)
    if "completion_pulse_channel" in raw:
        _normalize_field("completion_pulse_channel", raw["completion_pulse_channel"], Field("pulse_channel"))
        if not raw.get("completion_pulse_pins"):
            raise CoreValidationError("completion_pulse_channel requires completion_pulse_pins")
    unknown = sorted(set(raw) - set(contract.fields))
    if unknown:
        if request.command == "measure-all" and unknown == ["channel"]:
            raise CoreValidationError("measure-all always reads all channels and does not accept channel")
        raise CoreValidationError(f"{request.command} has unknown or inapplicable field(s): {', '.join(unknown)}")
    normalized: dict[str, Any] = {}
    # Validate supplied values first so an invalid supplied field wins over a
    # separate missing required field, as it did before central admission.
    for name, field in contract.fields.items():
        if name not in raw:
            continue
        value = raw[name]
        if value is None:
            if field.kind == "bool":
                raise CoreValidationError(f"{name} must be a boolean")
            if field.kind in {"channel", "pulse_channel"}:
                normalized[name] = _normalize_field(name, value, field)
                continue
            if not field.nullable:
                raise CoreValidationError(f"{name} must not be null")
            normalized[name] = None
            continue
        normalized[name] = _normalize_field(name, value, field)
    for name, field in contract.fields.items():
        if name in normalized:
            continue
        if field.required:
            raise CoreValidationError(f"{request.command} requires {name}")
        if field.default is not _MISSING and request.command.startswith("trigger-"):
            normalized[name] = field.default
    return replace(request, parameters=normalized)


def _normalize_field(name: str, value: Any, field: Field) -> Any:
    kind = field.kind
    if kind == "any":
        return value
    if kind == "bool":
        if type(value) is not bool:
            raise CoreValidationError(f"{name} must be a boolean")
        return value
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            raise CoreValidationError(f"{name} must be a non-empty string")
        return value
    if kind == "object":
        if not isinstance(value, dict):
            raise CoreValidationError(f"{name} must be an object")
        return value
    if kind == "enum":
        if type(value) is not str or value not in field.values:
            raise CoreValidationError(f"{name} must be one of: {', '.join(sorted(field.values))}")
        return value
    if kind == "channel":
        if field.allow_all and type(value) is str and value == "all":
            return value
        if type(value) is not int or value < 1:
            suffix = " or 'all'" if field.allow_all else ""
            raise CoreValidationError(f"{name} must be a positive integer{suffix}")
        return value
    if kind == "pin":
        if type(value) is not int or value not in {1, 2, 3}:
            raise CoreValidationError(f"{name} must be one of rear pins 1, 2, or 3")
        return value
    if kind == "pulse_channel":
        if type(value) is not int or not 1 <= value <= 3:
            raise CoreValidationError("completion_pulse_channel must be an integer from 1 to 3")
        return value
    if kind == "pin_list":
        if not isinstance(value, (list, tuple)) or not value:
            raise CoreValidationError(f"{name} must be a non-empty list of rear pins")
        if any(type(pin) is not int or pin not in {1, 2, 3} for pin in value) or len(set(value)) != len(value):
            raise CoreValidationError(f"{name} must contain unique rear pins 1, 2, or 3")
        return tuple(value)
    if kind in {"number_list", "bool_list"}:
        if not isinstance(value, (list, tuple)):
            raise CoreValidationError(f"{name} must be a list")
        if kind == "bool_list":
            if any(type(item) is not bool for item in value):
                raise CoreValidationError(f"{name} must contain exact booleans")
            return tuple(value)
        return tuple(_number(name, item) for item in value)
    if kind in {"int", "positive_int", "nonnegative_int", "min50_int", "range_int", "range_count"}:
        if type(value) is not int:
            raise CoreValidationError(f"{name} must be an exact integer")
        if kind == "positive_int" and value < 1:
            raise CoreValidationError(f"{name} must be positive")
        if kind == "nonnegative_int" and value < 0:
            raise CoreValidationError(f"{name} must be non-negative")
        if kind == "min50_int" and value < 50:
            raise CoreValidationError(f"{name} must be at least 50")
        if kind == "range_int" and not 1 <= value <= 255:
            raise CoreValidationError(f"{name} must be an integer from 1 to 255")
        if kind == "range_count" and not 1 <= value <= 256:
            raise CoreValidationError(f"{name} must be an integer from 1 to 256")
        return value
    number = _number(name, value)
    if kind == "nonnegative_number" and number < 0:
        raise CoreValidationError(f"{name} must be non-negative")
    if kind == "positive_number" and number <= 0:
        raise CoreValidationError(f"{name} must be positive")
    return number


def _number(name: str, value: Any) -> int | float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise CoreValidationError(f"{name} must be a finite number")
    return value
