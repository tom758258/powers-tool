"""Parser-neutral operation core for Keysight power supply commands."""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Sequence

from keysight_power_core.connection import open_resource
from keysight_power_core.core import (
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    CoreVerificationError,
    OperationRequest,
    UnsupportedChannelError,
    UnsupportedModelError,
)
from keysight_power_core.drivers.e36312a import E36312APowerSupply
from keysight_power_core.drivers.edu36311a import EDU36311APowerSupply
from keysight_power_core.errors import VisaConnectionError
from keysight_power_core.factory import create_power_supply
from keysight_power_core.models import parse_idn
from keysight_power_core.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    resolve_safety_config,
    validate_channel,
    validate_setpoint,
)
from keysight_power_core.trigger import run_native_list_operation, run_post_action_completion_pulse

IDN_QUERY = "*IDN?"
ERROR_QUERY = "SYST:ERR?"
OUTPUT_WRITE_POWER_SUPPLY_TYPES = (E36312APowerSupply, EDU36311APowerSupply)


class ScpiLoggingSession:
    """Session proxy that logs SCPI traffic while preserving driver behavior."""

    def __init__(self, resource: str, session: Any, logger: Callable[[str, str, str], None]) -> None:
        self._resource = resource
        self._session = session
        self._logger = logger

    def write(self, command: str) -> Any:
        self._logger(self._resource, ">>", command)
        return self._session.write(command)

    def query(self, command: str) -> str:
        self._logger(self._resource, ">>", command)
        response = self._session.query(command)
        self._logger(self._resource, "<<", response)
        return response

    def close(self) -> None:
        self._session.close()


def run_operation(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run an operation command and return parser-neutral data."""

    if request.runtime.dry_run or request.runtime.simulate:
        return output_plan(request)

    if request.command in {
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "output-state",
        "cycle-output",
        "ramp",
        "smoke-output",
    }:
        return _run_output_write_operation(request, opener=opener, sleep=sleep, scpi_logger=scpi_logger)

    raise CoreValidationError(f"unsupported operation command {request.command!r}")


def output_plan(request: OperationRequest) -> dict[str, Any]:
    """Build the dry-run/simulation output plan without opening hardware."""

    command = request.command
    p = request.parameters
    channel = p.get("channel")
    plan: dict[str, Any] = {
        "operation": {"name": command},
        "target": {
            "resource": request.runtime.resource,
            "channel": channel,
        },
        "steps": [],
        "description": _output_plan_description(command),
        "hardware_touched": False,
    }

    if command == "set":
        plan["steps"] = [
            _driver_step(1, "set_current_limit", channel=channel, current=_json_safe_number(p["current"])),
            _driver_step(2, "set_voltage", channel=channel, voltage=_json_safe_number(p["voltage"])),
        ]
        _append_write_followup_steps(p, plan["steps"], ("programmed_voltage", "programmed_current"))
    elif command == "output-on":
        channels = _plan_channels(channel)
        plan["steps"] = [
            _driver_step(index, "output_on", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
        _append_write_followup_steps(p, plan["steps"], ("output_state",))
    elif command == "output-off":
        channels = _plan_channels(channel)
        plan["steps"] = [
            _driver_step(index, "output_off", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
        _append_write_followup_steps(p, plan["steps"], ("output_state",))
    elif command == "safe-off":
        plan["steps"] = [_driver_step(1, "safe_off", channel=channel)]
    elif command == "output-state":
        channels = _plan_channels(channel)
        plan["steps"] = [
            _driver_step(index, "output_state", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
    elif command == "cycle-output":
        channels = _plan_channels(channel)
        steps = []
        index = 1
        for selected_channel in channels:
            steps.append(_driver_step(index, "output_on", channel=selected_channel))
            index += 1
        steps.append(_driver_step(index, "sleep", duration_ms=p.get("duration_ms", 0)))
        index += 1
        for selected_channel in channels:
            steps.append(_driver_step(index, "output_off", channel=selected_channel))
            index += 1
        plan["steps"] = steps
    elif command == "apply":
        channels = (1, 2, 3) if channel == "all" else (channel,)
        steps = []
        index = 1
        for selected_channel in channels:
            steps.append(_driver_step(index, "set_current_limit", channel=selected_channel, current=_json_safe_number(p["current"])))
            index += 1
            steps.append(_driver_step(index, "set_voltage", channel=selected_channel, voltage=_json_safe_number(p["voltage"])))
            index += 1
        if not p.get("no_output", False):
            for selected_channel in channels:
                steps.append(_driver_step(index, "output_on", channel=selected_channel))
                index += 1
        plan["steps"] = steps
        _append_write_followup_steps(p, plan["steps"], ("programmed_voltage", "programmed_current"))
    elif command == "ramp":
        voltages = ramp_voltages(p["start_voltage"], p["stop_voltage"], p["step_voltage"])
        steps = [_driver_step(1, "set_current_limit", channel=channel, current=_json_safe_number(p["current"]))]
        index = 2
        for voltage_index, voltage in enumerate(voltages):
            steps.append(_driver_step(index, "set_voltage", channel=channel, voltage=_json_safe_number(voltage)))
            index += 1
            if p.get("delay_ms", 0) > 0 and voltage_index < len(voltages) - 1:
                steps.append(_driver_step(index, "sleep", duration_ms=p["delay_ms"]))
                index += 1
        if p.get("settle_ms", 0) > 0:
            steps.append(_driver_step(index, "sleep", duration_ms=p["settle_ms"]))
            index += 1
        if p.get("verify_after_write", False):
            steps.append(_driver_step(index, "programmed_voltage", channel=channel))
            index += 1
            steps.append(_driver_step(index, "programmed_current", channel=channel))
        plan["steps"] = steps
    elif command == "smoke-output":
        plan["steps"] = [
            _driver_step(1, "set_current_limit", channel=channel, current=_json_safe_number(p["current"])),
            _driver_step(2, "set_voltage", channel=channel, voltage=_json_safe_number(p["voltage"])),
            _driver_step(3, "output_on", channel=channel),
            _driver_step(4, "sleep", duration_ms=p.get("duration_ms", 0)),
            _driver_step(5, "measure_voltage", channel=channel),
            _driver_step(6, "measure_current", channel=channel),
            _driver_step(7, "output_off", channel=channel),
            _driver_step(8, "output_state", channel=channel),
        ]
    else:
        raise CoreValidationError(f"unsupported output command {command!r}")

    return plan


def ramp_voltages(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise CoreValidationError("step-voltage must be greater than 0")
    direction = 1.0 if stop >= start else -1.0
    signed_step = direction * step
    voltages = [float(start)]
    current = float(start)
    for _ in range(1000):
        next_voltage = current + signed_step
        if (direction > 0 and next_voltage >= stop) or (direction < 0 and next_voltage <= stop):
            break
        voltages.append(next_voltage)
        current = next_voltage
    else:
        raise CoreValidationError("ramp would exceed 1000 voltage steps")
    if not math.isclose(voltages[-1], stop, rel_tol=0.0, abs_tol=1e-12):
        voltages.append(float(stop))
    if len(voltages) > 1000:
        raise CoreValidationError("ramp would exceed 1000 voltage steps")
    return voltages


def _run_output_write_operation(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    _validate_real_gate(request)
    opened = False
    resource = request.runtime.resource
    if resource is None:
        raise CoreValidationError("resource is required")

    try:
        with opener(resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            session = (
                ScpiLoggingSession(resource, instrument, scpi_logger)
                if request.runtime.log_scpi and scpi_logger is not None
                else instrument
            )
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, OUTPUT_WRITE_POWER_SUPPLY_TYPES):
                raise UnsupportedModelError(
                    f"{request.command} real execution is only supported for E36312A or EDU36311A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            return _execute_output_write(request, power_supply, idn=idn, sleep=sleep)
    except VisaConnectionError as exc:
        prefix = f"{request.command} failed" if opened else f"Could not open resource for {request.command}"
        raise CoreIoError(f"{prefix}: {exc}", opened=opened) from exc
    except (CoreValidationError, CoreExecutionError):
        raise
    except ValueError as exc:
        raise CoreExecutionError(f"{request.command} failed: {exc}") from exc


def _execute_output_write(
    request: OperationRequest,
    power_supply: Any,
    *,
    idn: str,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    command = request.command
    p = request.parameters
    channel = p.get("channel")

    if command == "set":
        _require_channel(power_supply, channel, command)
        _validate_setpoint_for_request(request, idn, channel)
        power_supply.set_current_limit(channel=channel, current=p["current"])
        power_supply.set_voltage(channel=channel, voltage=p["voltage"])
        _settle_after_write(request, sleep)
        verification = _verify_setpoints_after_write(request, power_supply, channels=(channel,))
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, voltage=p["voltage"], current=p["current"])
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "apply":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels)
        for selected_channel in channels:
            _validate_setpoint_for_request(request, idn, selected_channel)
            if not p.get("no_output", False):
                _require_confirmation_if_needed(request, p["voltage"], p["current"], selected_channel, idn)
        for selected_channel in channels:
            power_supply.set_current_limit(channel=selected_channel, current=p["current"])
            power_supply.set_voltage(channel=selected_channel, voltage=p["voltage"])
        if not p.get("no_output", False):
            for selected_channel in channels:
                power_supply.output_on(channel=selected_channel)
        _settle_after_write(request, sleep)
        verification = _verify_setpoints_after_write(request, power_supply, channels=channels)
        if verification["passed"] and not p.get("no_output", False):
            verification = _combine_verifications(
                "apply",
                verification,
                *(
                    _verify_output_state_after_write(request, power_supply, expected=True, channel=selected_channel)
                    for selected_channel in channels
                ),
            )
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=_completion_pulse_channel(request, channel))
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, voltage=p["voltage"], current=p["current"])
        data["channels"] = list(channels)
        data["output_enabled"] = not p.get("no_output", False)
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "output-on":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels, command=command)
        outputs = []
        for selected_channel in channels:
            voltage = power_supply.programmed_voltage(channel=selected_channel)
            current = power_supply.programmed_current(channel=selected_channel)
            _validate_setpoint_for_request(request, idn, selected_channel, voltage=voltage, current=current)
            _require_confirmation_if_needed(request, voltage, current, selected_channel, idn)
            outputs.append(
                {
                    "channel": selected_channel,
                    "enabled": True,
                    "readback": {
                        "setpoints": {"voltage": voltage, "current": current},
                        "safety_checked": request.runtime.safety_config is not None,
                    },
                }
            )
        for selected_channel in channels:
            power_supply.output_on(channel=selected_channel)
        _settle_after_write(request, sleep)
        verification = _combine_verifications(
            "output-on",
            *(
                _verify_output_state_after_write(request, power_supply, expected=True, channel=selected_channel)
                for selected_channel in channels
            ),
        )
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=_completion_pulse_channel(request, channel))
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel)
        data["output_enabled"] = True
        if channel == "all":
            data["outputs"] = outputs
        else:
            data["readback"] = outputs[0]["readback"]
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "output-off":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels, command=command)
        for selected_channel in channels:
            validate_channel(selected_channel, _safety_limits(request, channel=selected_channel, model=parse_idn(idn).model))
        for selected_channel in channels:
            power_supply.output_off(channel=selected_channel)
        _settle_after_write(request, sleep)
        verification = _combine_verifications(
            "output-off",
            *(
                _verify_output_state_after_write(request, power_supply, expected=False, channel=selected_channel)
                for selected_channel in channels
            ),
        )
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=_completion_pulse_channel(request, channel))
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel)
        data["output_enabled"] = False
        if channel == "all":
            data["outputs"] = [{"channel": selected_channel, "enabled": False} for selected_channel in channels]
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "safe-off":
        channels = power_supply.capabilities.channels if channel == "all" else (_require_channel(power_supply, channel, command),)
        outputs = []
        for selected_channel in channels:
            power_supply.output_off(channel=selected_channel)
            outputs.append({"channel": selected_channel, "enabled": power_supply.output_state(channel=selected_channel)})
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel)
        data["outputs"] = outputs
        _attach_trigger_if_present(data, trigger)
        return data

    if command == "output-state":
        channels = _channels_from_selection(
            channel,
            getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels),
            command=command,
        )
        outputs = []
        for selected_channel in channels:
            validate_channel(selected_channel, _safety_limits(request, channel=selected_channel, model=parse_idn(idn).model))
            outputs.append({"channel": selected_channel, "enabled": power_supply.output_state(channel=selected_channel)})
        data = _resource_payload(request, idn, channel=channel, output_enabled=outputs[0]["enabled"])
        if channel == "all":
            data["outputs"] = outputs
        return data

    if command == "cycle-output":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels, command=command)
        for selected_channel in channels:
            limits = _safety_limits(request, channel=selected_channel, model=parse_idn(idn).model)
            if limits is not None:
                voltage = power_supply.programmed_voltage(channel=selected_channel)
                current = power_supply.programmed_current(channel=selected_channel)
                _validate_setpoint_for_request(request, idn, selected_channel, voltage=voltage, current=current)
                _require_confirmation_if_needed(request, voltage, current, selected_channel, idn)
        enabled_channels: list[int] = []
        try:
            for selected_channel in channels:
                power_supply.output_on(channel=selected_channel)
                enabled_channels.append(selected_channel)
            sleep(p.get("duration_ms", 0) / 1000)
        finally:
            for selected_channel in enabled_channels:
                power_supply.output_off(channel=selected_channel)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=_completion_pulse_channel(request, channel))
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, duration_ms=p.get("duration_ms", 0))
        data["cycled"] = True
        data["final_output_enabled"] = False
        if channel == "all":
            data["outputs"] = [
                {"channel": selected_channel, "cycled": True, "final_enabled": False}
                for selected_channel in channels
            ]
        _attach_trigger_if_present(data, trigger)
        return data

    if command == "ramp":
        _require_channel(power_supply, channel, command)
        voltages = ramp_voltages(p["start_voltage"], p["stop_voltage"], p["step_voltage"])
        _validate_setpoint_for_request(request, idn, channel, voltage=p["stop_voltage"], current=p["current"])
        native_requested = _native_ramp_requested(request, voltages)
        if p.get("completion_pulse_mode", "auto") == "native" and len(voltages) > 100:
            raise CoreValidationError("native ramp LIST supports at most 100 steps")
        trigger: dict[str, Any] | None = None
        verification = {"passed": True, "checks": [], "differences": []}
        if native_requested:
            if isinstance(power_supply, EDU36311APowerSupply):
                raise CoreValidationError("EDU36311A real ramp does not support native LIST or completion pulses")
            if not isinstance(power_supply, E36312APowerSupply):
                raise UnsupportedModelError("native ramp LIST requires E36312A")
            dwell = tuple(
                max(
                    (
                        p.get("completion_pulse_dwell_ms", 10)
                        if index == len(voltages) - 1
                        else p.get("delay_ms", 0)
                    )
                    / 1000,
                    0.01,
                )
                for index, _ in enumerate(voltages)
            )
            trigger = run_native_list_operation(
                command="ramp",
                runtime=request.runtime,
                power_supply=power_supply,
                channel=channel,
                source="bus",
                voltages=tuple(voltages),
                currents=tuple(float(p["current"]) for _ in voltages),
                dwell=dwell,
                pins=tuple(p.get("completion_pulse_pins") or ()),
                polarity=p.get("completion_pulse_polarity", "positive"),
                final_eost_pulse=_completion_pulse_requested(request),
                count=1,
                fire=True,
                wait_complete=True,
                leave_trigger_configured=bool(p.get("leave_trigger_configured", False)),
                wait_timeout_ms=p.get("wait_timeout_ms"),
                poll_ms=p.get("poll_ms"),
                sleep=sleep,
                result_mode="ramp",
            )
        else:
            power_supply.set_current_limit(channel=channel, current=p["current"])
            for index, voltage in enumerate(voltages):
                power_supply.set_voltage(channel=channel, voltage=voltage)
                if p.get("delay_ms", 0) > 0 and index < len(voltages) - 1:
                    sleep(p["delay_ms"] / 1000)
            _settle_after_write(request, sleep)
            verification = _verify_setpoints_after_write(
                request,
                power_supply,
                channels=(channel,),
                expected_voltage=p["stop_voltage"],
            )
            _raise_verification_failed(verification)
            trigger = _maybe_run_completion_pulse(
                request,
                power_supply,
                default_channel=channel,
                fallback_reason=(
                    "native LIST supports at most 100 steps"
                    if _completion_pulse_requested(request) and len(voltages) > 100 and p.get("completion_pulse_mode", "auto") == "auto"
                    else None
                ),
            )
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, voltages=voltages)
        data["steps"] = len(voltages)
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "smoke-output":
        _require_channel(power_supply, channel, command)
        _validate_setpoint_for_request(request, idn, channel)
        _require_confirmation_if_needed(request, p["voltage"], p["current"], channel, idn)
        safe_off_attempted = False
        output_was_enabled = False
        measurements: dict[str, float]
        try:
            power_supply.set_current_limit(channel=channel, current=p["current"])
            power_supply.set_voltage(channel=channel, voltage=p["voltage"])
            power_supply.output_on(channel=channel)
            output_was_enabled = True
            sleep(p.get("duration_ms", 0) / 1000)
            measurements = {
                "voltage": power_supply.measure_voltage(channel=channel),
                "current": power_supply.measure_current(channel=channel),
            }
        finally:
            if output_was_enabled:
                safe_off_attempted = True
                power_supply.output_off(channel=channel)
        final_enabled = power_supply.output_state(channel=channel)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, voltage=p["voltage"], current=p["current"])
        data["measurements"] = measurements
        data["final_output_enabled"] = final_enabled
        data["safe_off_attempted"] = safe_off_attempted
        _attach_trigger_if_present(data, trigger)
        return data

    raise CoreValidationError(f"unsupported output command {command!r}")


def _validate_real_gate(request: OperationRequest) -> None:
    return None


def _validate_setpoint_for_request(
    request: OperationRequest,
    idn: str,
    channel: int,
    *,
    voltage: float | None = None,
    current: float | None = None,
) -> None:
    p = request.parameters
    limits = _safety_limits(request, channel=channel, model=parse_idn(idn).model)
    try:
        validate_setpoint(
            channel=channel,
            voltage=p["voltage"] if voltage is None else voltage,
            current=p["current"] if current is None else current,
            limits=limits,
        )
    except (SafetyConfigError, SafetyValidationError) as exc:
        raise CoreValidationError(str(exc)) from exc


def _require_confirmation_if_needed(
    request: OperationRequest,
    voltage: float,
    current: float,
    channel: int,
    idn: str,
) -> None:
    limits = _safety_limits(request, channel=channel, model=parse_idn(idn).model)
    if limits is None:
        return
    if request.runtime.confirm:
        return
    needs_confirmation = (
        voltage > 0
        and current > 0
        and (
            (
                limits.confirm_above_voltage is not None
                and voltage > limits.confirm_above_voltage
            )
            or (
                limits.confirm_above_current is not None
                and current > limits.confirm_above_current
            )
        )
    )
    if needs_confirmation:
        raise ConfirmationRequiredError(f"{request.command} requires confirm for real hardware execution")


def _safety_limits(request: OperationRequest, *, channel: int | None, model: str | None) -> SafetyLimits | None:
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


def _require_channel(power_supply: Any, channel: int, command: str) -> int:
    if channel not in power_supply.capabilities.channels:
        raise UnsupportedChannelError(
            f"channel {channel} is not supported for {command}; supported: {power_supply.capabilities.channels}"
        )
    return channel


def _require_read_only_channel(power_supply: Any, channel: int, command: str) -> int:
    channels = getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels)
    if channel not in channels:
        raise UnsupportedChannelError(
            f"channel {channel} is not supported for {command}; supported: {channels}"
        )
    return channel


def _channels_from_selection(selection: int | str, supported: Sequence[int], *, command: str | None = None) -> tuple[int, ...]:
    if selection == "all":
        return tuple(supported)
    if selection not in supported:
        command_label = f" for {command}" if command else ""
        raise UnsupportedChannelError(f"channel {selection} is not supported{command_label}; supported: {tuple(supported)}")
    return (int(selection),)


def _raise_on_instrument_errors(power_supply: Any, command: str) -> None:
    errors = []
    for _ in range(20):
        response = power_supply._session.query(ERROR_QUERY)
        if _is_no_error_response(response):
            break
        errors.append(response)
    if errors:
        raise CoreExecutionError(f"{command} completed with instrument errors: {errors}")


def _settle_after_write(request: OperationRequest, sleep: Callable[[float], None]) -> None:
    settle_ms = request.parameters.get("settle_ms", 0)
    if settle_ms > 0:
        sleep(settle_ms / 1000)


def _verify_setpoints_after_write(
    request: OperationRequest,
    power_supply: Any,
    *,
    channels: Sequence[int],
    expected_voltage: float | None = None,
) -> dict[str, Any]:
    p = request.parameters
    if not p.get("verify_after_write", False):
        return {"passed": True, "checks": [], "differences": []}
    voltage = p["voltage"] if expected_voltage is None else expected_voltage
    current = p["current"]
    voltage_tolerance = float(p.get("setpoint_voltage_tolerance", 0.001))
    current_tolerance = float(p.get("setpoint_current_tolerance", 0.001))
    tolerances = {"voltage": voltage_tolerance, "current": current_tolerance}
    checks = []
    differences = []
    for channel in channels:
        actual_voltage = power_supply.programmed_voltage(channel=channel)
        actual_current = power_supply.programmed_current(channel=channel)
        checks.append(
            {
                "channel": channel,
                "expected": {"voltage": _json_safe_number(voltage), "current": _json_safe_number(current)},
                "actual": {"voltage": _json_safe_number(actual_voltage), "current": _json_safe_number(actual_current)},
                "tolerances": tolerances,
            }
        )
        if abs(actual_voltage - voltage) > voltage_tolerance:
            differences.append(_verification_difference("programmed_voltage", channel, voltage, actual_voltage, voltage_tolerance))
        if abs(actual_current - current) > current_tolerance:
            differences.append(_verification_difference("programmed_current", channel, current, actual_current, current_tolerance))
    return {"passed": not differences, "checks": checks, "differences": differences}


def _verify_output_state_after_write(
    request: OperationRequest,
    power_supply: Any,
    *,
    expected: bool,
    channel: int | None = None,
) -> dict[str, Any]:
    if not request.parameters.get("verify_after_write", False):
        return {"passed": True, "checks": [], "differences": []}
    selected_channel = request.parameters.get("channel") if channel is None else channel
    actual = power_supply.output_state(channel=selected_channel)
    differences = []
    if actual is not expected:
        differences.append(
            {
                "path": f"outputs[channel={selected_channel}].enabled",
                "channel": selected_channel,
                "expected": expected,
                "actual": actual,
            }
        )
    return {
        "passed": not differences,
        "checks": [{"channel": selected_channel, "expected": expected, "actual": actual}],
        "differences": differences,
    }


def _verification_difference(path: str, channel: int, expected: float, actual: float, tolerance: float) -> dict[str, Any]:
    return {
        "path": f"{path}[channel={channel}]",
        "channel": channel,
        "expected": _json_safe_number(expected),
        "actual": _json_safe_number(actual),
        "tolerance": tolerance,
        "delta": _json_safe_number(actual - expected),
    }


def _combine_verifications(label: str, *verifications: dict[str, Any]) -> dict[str, Any]:
    checks = []
    differences = []
    for verification in verifications:
        checks.extend(verification.get("checks", []))
        differences.extend(verification.get("differences", []))
    return {"operation": label, "passed": not differences, "checks": checks, "differences": differences}


def _raise_verification_failed(verification: dict[str, Any]) -> None:
    if not verification["passed"]:
        raise CoreVerificationError("write verification failed", verification=verification)


def _attach_verification_if_requested(request: OperationRequest, data: dict[str, Any], verification: dict[str, Any]) -> None:
    if request.parameters.get("verify_after_write", False):
        data["verification"] = verification


def _completion_pulse_requested(request: OperationRequest) -> bool:
    return bool(request.parameters.get("completion_pulse_pins"))


def _native_ramp_requested(request: OperationRequest, voltages: Sequence[float]) -> bool:
    mode = request.parameters.get("completion_pulse_mode", "auto")
    if mode == "native":
        return True
    return mode == "auto" and _completion_pulse_requested(request) and len(voltages) <= 100


def _completion_pulse_channel(request: OperationRequest, default_channel: int | str | None = None) -> int:
    configured = request.parameters.get("completion_pulse_channel")
    if configured is not None:
        return int(configured)
    if isinstance(default_channel, int):
        return default_channel
    return 1


def _maybe_run_completion_pulse(
    request: OperationRequest,
    power_supply: Any,
    *,
    default_channel: int | str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any] | None:
    pins = tuple(request.parameters.get("completion_pulse_pins") or ())
    if not pins:
        return None
    if isinstance(power_supply, EDU36311APowerSupply):
        raise CoreValidationError("EDU36311A real execution does not support completion-pulse options")
    if not isinstance(power_supply, E36312APowerSupply):
        raise UnsupportedModelError("completion-pulse options require E36312A")
    channel = _completion_pulse_channel(request, default_channel)
    if request.parameters.get("completion_pulse_mode", "auto") == "native":
        raise CoreValidationError(
            f"{request.command} does not have a native completion event; use --completion-pulse-mode post-action"
        )
    trigger = run_post_action_completion_pulse(
        power_supply,
        channel=channel,
        pins=pins,
        polarity=request.parameters.get("completion_pulse_polarity", "positive"),
        leave_configured=bool(request.parameters.get("leave_trigger_configured", False)),
    )
    if trigger is not None:
        trigger["fallback_reason"] = fallback_reason
    return trigger


def _attach_trigger_if_present(data: dict[str, Any], trigger: dict[str, Any] | None) -> None:
    if trigger is not None:
        data["trigger"] = trigger


def _is_no_error_response(response: str) -> bool:
    stripped = response.strip()
    return stripped.startswith("+0") or stripped.startswith("0")


def _resource_payload(request: OperationRequest, idn: str, **extra: Any) -> dict[str, Any]:
    parsed = parse_idn(idn)
    data = {
        "resource": request.runtime.resource,
        "resource_alias": request.runtime.resource_alias,
        "idn": {
            "raw": idn,
            "manufacturer": parsed.manufacturer,
            "model": parsed.model,
            "serial": parsed.serial,
            "firmware": parsed.firmware,
            "parse_ok": parsed.parse_ok,
        },
    }
    data.update(extra)
    return data


def _driver_step(index: int, action: str, **parameters: Any) -> dict[str, Any]:
    return {"index": index, "type": "driver_action", "action": action, "parameters": parameters}


def _append_write_followup_steps(
    parameters: dict[str, Any],
    steps: list[dict[str, Any]],
    verification_actions: Sequence[str],
) -> None:
    channel = parameters.get("channel")
    next_index = len(steps) + 1
    if parameters.get("settle_ms", 0) > 0:
        steps.append(_driver_step(next_index, "sleep", duration_ms=parameters["settle_ms"]))
        next_index += 1
    if not parameters.get("verify_after_write", False):
        return
    channels = (1, 2, 3) if channel == "all" else (channel,)
    for selected_channel in channels:
        for action in verification_actions:
            steps.append(_driver_step(next_index, action, channel=selected_channel))
            next_index += 1


def _plan_channels(channel: int | str) -> tuple[int, ...]:
    if channel == "all":
        return E36312APowerSupply.capabilities.channels
    return (int(channel),)


def _json_safe_number(value: float) -> float | str:
    numeric = float(value)
    if math.isfinite(numeric):
        return numeric
    return str(value)


def _output_plan_description(command: str) -> str:
    descriptions = {
        "set": "Preview setting current limit before voltage.",
        "output-on": "Preview enabling the selected output channel.",
        "output-off": "Preview disabling the selected output channel.",
        "safe-off": "Preview a conservative output-off action without channel expansion.",
        "output-state": "Preview reading the selected output channel state.",
        "cycle-output": "Preview briefly enabling then disabling the selected output channel.",
        "apply": "Preview setting current, voltage, then enabling output.",
        "ramp": "Preview setting current, then stepping voltage setpoints without changing output state.",
        "smoke-output": "Preview a guarded set, output, measure, and safe-off sequence.",
    }
    try:
        return descriptions[command]
    except KeyError as exc:
        raise CoreValidationError(f"unsupported output command {command!r}") from exc
