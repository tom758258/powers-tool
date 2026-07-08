"""Parser-neutral trigger and native LIST core helpers."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Sequence

from keysight_power_core.cancellation import StopRequested, raise_if_cancelled
from keysight_power_core.connection import open_resource
from keysight_power_core.core import (
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    TriggerInterrupted,
    TriggerRequest,
    TriggerWaitTimeout,
    UnsupportedModelError,
)
from keysight_power_core.drivers.e36312a import E36312APowerSupply
from keysight_power_core.errors import VisaConnectionError
from keysight_power_core.factory import create_power_supply
from keysight_power_core.model_resolution import resolve_no_hardware_runtime, validate_live_expected_model
from keysight_power_core.models import parse_idn
from keysight_power_core.transport import dry_run_plan
from keysight_power_core.setpoint_limits import validate_effective_setpoint

IDN_QUERY = "*IDN?"


def run_trigger(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run a trigger command or return a dry-run trigger plan."""

    validate_trigger_request(request)
    request = _resolve_trigger_runtime(request)
    if request.runtime.dry_run:
        return {"plan": trigger_plan(request)}

    if request.command != "trigger-abort":
        raise_if_cancelled(stop_requested)
    if request.command == "trigger-pulse":
        return _run_trigger_pulse(request, opener=opener, scpi_logger=scpi_logger, stop_requested=stop_requested)
    if request.command == "trigger-status":
        return _run_trigger_status(request, opener=opener, scpi_logger=scpi_logger)
    if request.command == "trigger-step":
        return _run_trigger_step(request, opener=opener, sleep=sleep, scpi_logger=scpi_logger, stop_requested=stop_requested)
    if request.command == "trigger-list":
        return _run_trigger_list(request, opener=opener, sleep=sleep, scpi_logger=scpi_logger, stop_requested=stop_requested)
    if request.command == "trigger-fire":
        return _run_trigger_fire(request, opener=opener, sleep=sleep, scpi_logger=scpi_logger, stop_requested=stop_requested)
    if request.command == "trigger-abort":
        return _run_trigger_abort(request, opener=opener, scpi_logger=scpi_logger)

    raise CoreValidationError(f"unsupported trigger command {request.command!r}")


def validate_trigger_request(request: TriggerRequest) -> None:
    """Reject trigger controls that cannot complete or restore safely."""

    if request.command == "trigger-fire":
        if request.parameters.get("wait_complete", False) and request.parameters.get("channel") is None:
            raise CoreValidationError(
                "trigger-fire wait_complete requires channel as the abort target "
                "if the wait times out or is interrupted"
            )
        return
    if request.command not in {"trigger-step", "trigger-list"}:
        return
    source = str(request.parameters.get("source", "bus")).strip().lower()
    fire = request.parameters.get("fire", False) is True
    wait_complete = request.parameters.get("wait_complete", False) is True
    leave_configured = request.parameters.get("leave_trigger_configured", False) is True
    immediate = source in {"immediate", "imm"}
    if immediate and fire:
        raise CoreValidationError(f"{request.command} source=immediate does not accept fire=true; INIT starts it immediately")
    if source == "bus" and wait_complete and not fire:
        raise CoreValidationError(f"{request.command} wait_complete=true with BUS source requires fire=true")
    if request.command == "trigger-list":
        started = immediate or (source == "bus" and fire)
        if not started and not leave_configured:
            raise CoreValidationError("trigger-list arm-only requires leave_trigger_configured=true")
        if started and not wait_complete and not leave_configured:
            raise CoreValidationError(
                "trigger-list started without wait_complete=true requires leave_trigger_configured=true"
            )
        if any(field in request.parameters for field in ("voltages", "voltage_list", "bost_list", "eost_list", "trigger_output_pins")):
            trigger_list_config(request.parameters)


def _resolve_trigger_runtime(request: TriggerRequest) -> TriggerRequest:
    runtime = resolve_no_hardware_runtime(request.runtime)
    request = replace(request, runtime=runtime)
    if request.runtime.dry_run or request.runtime.simulate:
        _require_trigger_model_profile(request.runtime.model_profile)
    return request


def _require_trigger_model_profile(model_profile: str | None) -> None:
    if model_profile is None:
        raise CoreValidationError(
            "trigger no-hardware workflows require --model E36312A or a known deterministic E36312A SIM resource"
        )
    if model_profile != "E36312A":
        raise UnsupportedModelError(
            f"trigger no-hardware workflows are only supported for E36312A; requested model profile {model_profile}"
        )


def trigger_plan(request: TriggerRequest) -> dict[str, object]:
    """Build the unchanged SCPI preview for trigger commands."""

    request = _resolve_trigger_runtime(request)
    p = request.parameters
    if request.command == "trigger-pulse":
        scpi = trigger_pulse_scpi(
            tuple(p.get("pins") or ((p["pin"],) if p.get("pin") is not None else ())),
            p.get("polarity", "positive"),
            int(p.get("channel", 1)),
            exclusive_pins=bool(p.get("exclusive_pins", False)),
        )
        description = (
            "Preview configuring an E36312A rear digital trigger output pin then arming a "
            "channel with TRIG:SOUR BUS and INIT before issuing *TRG. *TRG may also "
            "trigger any already armed BUS-triggered behavior on the instrument."
        )
    elif request.command == "trigger-status":
        channel = p.get("channel", "all")
        channels = (1, 2, 3) if channel == "all" else (int(channel),)
        scpi = tuple(
            command
            for pin in (1, 2, 3)
            for command in (f"DIG:PIN{pin}:FUNC?", f"DIG:PIN{pin}:POL?")
        ) + ("DIG:TOUT:BUS?",) + tuple(
            command
            for selected in channels
            for command in (
                f"TRIG:SOUR? (@{selected})",
                f"VOLT:MODE? (@{selected})",
                f"CURR:MODE? (@{selected})",
            )
        )
        description = "Preview reading E36312A trigger pin and channel status."
    elif request.command == "trigger-step":
        scpi = trigger_step_scpi(
            channel=int(p["channel"]),
            source=str(p.get("source", "bus")),
            voltage=p.get("voltage"),
            current=p.get("current"),
            pins=tuple(p.get("completion_pulse_pins") or ()),
            polarity=str(p.get("completion_pulse_polarity", "positive")),
            fire=bool(p.get("fire", False)),
            wait_complete=bool(p.get("wait_complete", False)),
        )
        description = "Preview a native E36312A STEP transient trigger."
    elif request.command == "trigger-list":
        config = trigger_list_config(p)
        scpi = trigger_list_scpi(
            **config,
            exclusive_pins=bool(p.get("exclusive_pins", False)),
            fire=bool(p.get("fire", False)),
            wait_complete=bool(p.get("wait_complete", False)),
        )
        description = "Preview a native E36312A LIST transient trigger."
    elif request.command == "trigger-fire":
        scpi = ("*TRG", *_wait_complete_preview_commands(bool(p.get("wait_complete", False))))
        description = "Preview firing an already armed BUS trigger."
    elif request.command == "trigger-abort":
        channel = p.get("channel", "all")
        channels = (1, 2, 3) if channel == "all" else (int(channel),)
        scpi = tuple(f"ABOR (@{selected})" for selected in channels)
        description = "Preview aborting E36312A trigger/list execution."
    else:
        raise CoreValidationError(f"unsupported trigger command {request.command!r}")

    return dry_run_plan(
        command=request.command,
        resource=request.runtime.resource,
        model_profile=request.runtime.model_profile,
        scpi=scpi,
        description=description,
    )


def run_post_action_completion_pulse(
    power_supply: E36312APowerSupply,
    *,
    channel: int,
    pins: Sequence[int],
    polarity: str = "positive",
    leave_configured: bool = False,
) -> dict[str, Any] | None:
    """Emit the post-action completion pulse used by output operations."""

    selected_pins = tuple(pins)
    if not selected_pins:
        return None
    current = power_supply.programmed_current(channel=channel)
    voltage = power_supply.programmed_voltage(channel=channel)
    validate_effective_setpoint(
        model="E36312A",
        channel=channel,
        electrical_ratings=power_supply.capabilities.electrical_ratings,
        voltage=voltage,
        current=current,
    )
    snapshot = power_supply.trigger_snapshot(channel)
    restored: bool | None = None
    restore_errors: list[str] = []
    fired = False
    completed = False
    try:
        power_supply.abort_output_trigger(channel)
        configure_completion_output_pins(power_supply, selected_pins, polarity)
        power_supply.set_triggered_current(channel=channel, current=current)
        power_supply.set_triggered_voltage(channel=channel, voltage=voltage)
        power_supply.set_trigger_modes(channel=channel, current_mode="STEP", voltage_mode="STEP")
        power_supply.configure_output_trigger_source_bus(channel)
        power_supply.initiate_output_trigger(channel)
        power_supply.fire_bus_trigger()
        fired = True
        completed = True
    finally:
        if leave_configured:
            restored = False
        else:
            try:
                power_supply.restore_trigger_snapshot(snapshot)
                restored = True
            except Exception as exc:
                restored = False
                restore_errors.append(str(exc))

    return trigger_result_payload(
        mode="completion-pulse",
        native=False,
        channel=channel,
        pins=selected_pins,
        polarity=polarity,
        source="bus",
        armed=True,
        fired=fired,
        completed=completed,
        restored=restored,
        restore_errors=restore_errors,
    )


def configure_completion_output_pins(
    power_supply: E36312APowerSupply,
    pins: tuple[int, ...],
    polarity: str,
    *,
    exclusive_pins: bool = False,
) -> None:
    if not pins:
        return
    if exclusive_pins:
        power_supply.clear_trigger_output_pins(except_pins=pins)
    power_supply.configure_trigger_output_pins(pins, polarity)
    power_supply.enable_trigger_output_bus(True)


def trigger_result_payload(
    *,
    mode: str,
    native: bool,
    channel: int | None,
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    source: str = "bus",
    armed: bool = False,
    fired: bool = False,
    completed: bool = False,
    aborted: bool = False,
    stopped: bool = False,
    stop_reason: str | None = None,
    wait_timeout_ms: int | None = None,
    poll_ms: int | None = None,
    restored: bool | None = None,
    restore_errors: list[str] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "native": native,
        "channel": channel,
        "pins": list(pins),
        "polarity": polarity,
        "source": source,
        "armed": armed,
        "fired": fired,
        "completed": completed,
        "aborted": aborted,
        "stopped": stopped,
        "stop_reason": stop_reason,
        "wait_timeout_ms": wait_timeout_ms,
        "poll_ms": poll_ms,
        "restored": restored,
        "restore_errors": restore_errors or [],
    }
    if fallback_reason is not None:
        payload["fallback_reason"] = fallback_reason
    return payload


def trigger_pulse_scpi(
    pins: Sequence[int],
    polarity: str,
    channel: int,
    *,
    exclusive_pins: bool = False,
) -> tuple[str, ...]:
    polarity_command = "POS" if polarity == "positive" else "NEG"
    selected_pins = tuple(pins)
    clear_commands = tuple(
        f"DIG:PIN{other_pin}:FUNC DIO"
        for other_pin in (1, 2, 3)
        if exclusive_pins and other_pin not in selected_pins
    )
    configure_commands = tuple(
        command
        for pin in selected_pins
        for command in (f"DIG:PIN{pin}:FUNC TOUT", f"DIG:PIN{pin}:POL {polarity_command}")
    )
    return clear_commands + configure_commands + (
        "DIG:TOUT:BUS ON",
        f"CURR:TRIG <current-readback>,(@{channel})",
        f"VOLT:TRIG <voltage-readback>,(@{channel})",
        f"CURR:MODE FIX,(@{channel})",
        f"VOLT:MODE FIX,(@{channel})",
        f"CURR:MODE STEP,(@{channel})",
        f"VOLT:MODE STEP,(@{channel})",
        f"TRIG:SOUR BUS,(@{channel})",
        f"INIT (@{channel})",
        "*TRG",
    )


def trigger_step_scpi(
    *,
    channel: int,
    source: str,
    voltage: float | None,
    current: float | None,
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    fire: bool = False,
    wait_complete: bool = False,
) -> tuple[str, ...]:
    commands: list[str] = [f"ABOR (@{channel})"]
    polarity_command = "POS" if polarity == "positive" else "NEG"
    for pin in pins:
        commands.append(f"DIG:PIN{pin}:FUNC TOUT")
        commands.append(f"DIG:PIN{pin}:POL {polarity_command}")
    if pins:
        commands.append("DIG:TOUT:BUS ON")
    current_text = _format_text_value(current) if current is not None else "<current-readback>"
    voltage_text = _format_text_value(voltage) if voltage is not None else "<voltage-readback>"
    commands.extend(
        [
            f"CURR:TRIG {current_text},(@{channel})",
            f"VOLT:TRIG {voltage_text},(@{channel})",
            f"CURR:MODE FIX,(@{channel})",
            f"VOLT:MODE FIX,(@{channel})",
            f"CURR:MODE STEP,(@{channel})",
            f"VOLT:MODE STEP,(@{channel})",
            f"TRIG:SOUR {trigger_source_scpi(source)},(@{channel})",
            f"INIT (@{channel})",
        ]
    )
    if source == "bus" and fire:
        commands.append("*TRG")
    commands.extend(_wait_complete_preview_commands(wait_complete))
    return tuple(commands)


def trigger_list_scpi(
    *,
    channel: int,
    source: str,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    final_eost_pulse: bool = False,
    begin_outputs: tuple[bool, ...] | None = None,
    end_outputs: tuple[bool, ...] | None = None,
    exclusive_pins: bool = False,
    fire: bool = False,
    count: int = 1,
    wait_complete: bool = False,
) -> tuple[str, ...]:
    validate_trigger_list_limits(voltages=voltages, currents=currents, dwell=dwell, count=count)
    commands: list[str] = [f"ABOR (@{channel})"]
    polarity_command = "POS" if polarity == "positive" else "NEG"
    if exclusive_pins and pins:
        for pin in (1, 2, 3):
            if pin not in pins:
                commands.append(f"DIG:PIN{pin}:FUNC DIO")
    for pin in pins:
        commands.append(f"DIG:PIN{pin}:FUNC TOUT")
        commands.append(f"DIG:PIN{pin}:POL {polarity_command}")
    if pins:
        commands.append("DIG:TOUT:BUS ON")
    begin_outputs = begin_outputs if begin_outputs is not None else tuple(False for _ in voltages)
    end_outputs = end_outputs if end_outputs is not None else tuple(
        index == len(voltages) - 1 and final_eost_pulse for index, _ in enumerate(voltages)
    )
    commands.extend(
        [
            f"LIST:VOLT {_number_csv(voltages)},(@{channel})",
            f"LIST:CURR {_number_csv(currents)},(@{channel})",
            f"LIST:DWEL {_number_csv(dwell)},(@{channel})",
            f"LIST:TOUT:BOST {_bool_csv(begin_outputs)},(@{channel})",
            f"LIST:TOUT:EOST {_bool_csv(end_outputs)},(@{channel})",
            f"LIST:COUN {count},(@{channel})",
            f"LIST:STEP AUTO,(@{channel})",
            f"LIST:TERM:LAST ON,(@{channel})",
            f"CURR:MODE FIX,(@{channel})",
            f"VOLT:MODE FIX,(@{channel})",
            f"CURR:MODE LIST,(@{channel})",
            f"VOLT:MODE LIST,(@{channel})",
            f"TRIG:SOUR {trigger_source_scpi(source)},(@{channel})",
            f"INIT (@{channel})",
        ]
    )
    if source == "bus" and fire:
        commands.append("*TRG")
    commands.extend(_wait_complete_preview_commands(wait_complete))
    return tuple(commands)


def trigger_list_config(parameters: dict[str, Any]) -> dict[str, Any]:
    channel = parameters.get("channel")
    if channel is None:
        raise CoreValidationError("trigger-list requires channel")
    voltages = _float_tuple(parameters.get("voltages", parameters.get("voltage_list")))
    currents = _float_tuple(parameters.get("currents", parameters.get("current_list")))
    dwell = _float_tuple(parameters.get("dwell", parameters.get("dwell_list")))
    if voltages is None:
        raise CoreValidationError("trigger-list requires voltage list")
    if currents is None:
        raise CoreValidationError("trigger-list requires current list")
    if dwell is None:
        raise CoreValidationError("trigger-list requires dwell list")
    if len(currents) == 1 and len(voltages) > 1:
        currents = tuple(currents[0] for _ in voltages)
    if len(dwell) == 1 and len(voltages) > 1:
        dwell = tuple(dwell[0] for _ in voltages)
    canonical_fields = {"bost_list", "eost_list", "trigger_output_pins", "trigger_output_polarity"}
    legacy_fields = {"completion_pulse_pins", "completion_pulse_polarity"}
    if canonical_fields.intersection(parameters) and legacy_fields.intersection(parameters):
        raise CoreValidationError(
            "trigger-list completion_pulse_* fields cannot be mixed with "
            "bost_list, eost_list, or trigger_output_* fields"
        )
    canonical = bool(canonical_fields.intersection(parameters))
    begin_outputs = _bool_tuple(parameters.get("bost_list")) if canonical else None
    end_outputs = _bool_tuple(parameters.get("eost_list")) if canonical else None
    if canonical:
        begin_outputs = begin_outputs if begin_outputs is not None else tuple(False for _ in voltages)
        end_outputs = end_outputs if end_outputs is not None else tuple(False for _ in voltages)
        pins = tuple(parameters.get("trigger_output_pins") or ())
        polarity = str(parameters.get("trigger_output_polarity", "positive"))
    else:
        pins = tuple(parameters.get("completion_pulse_pins") or parameters.get("pins") or ())
        polarity = str(parameters.get("completion_pulse_polarity", parameters.get("polarity", "positive")))
        begin_outputs = tuple(False for _ in voltages)
        end_outputs = tuple(index == len(voltages) - 1 and bool(pins) for index, _ in enumerate(voltages))
    if len(begin_outputs) != len(voltages):
        raise CoreValidationError("BOST list length must match voltage list length")
    if len(end_outputs) != len(voltages):
        raise CoreValidationError("EOST list length must match voltage list length")
    if any(begin_outputs) or any(end_outputs):
        if not pins:
            raise CoreValidationError("trigger-list BOST/EOST pulses require explicit trigger_output_pins")
    if any(not isinstance(pin, int) or isinstance(pin, bool) or pin not in {1, 2, 3} for pin in pins):
        raise CoreValidationError("trigger-list output pins must contain only rear pins 1, 2, or 3")
    if len(set(pins)) != len(pins):
        raise CoreValidationError("trigger-list output pins must not contain duplicates")
    if polarity not in {"positive", "negative"}:
        raise CoreValidationError("trigger-list output polarity must be positive or negative")
    return {
        "channel": int(channel),
        "source": str(parameters.get("source", "bus")).lower(),
        "voltages": voltages,
        "currents": currents,
        "dwell": dwell,
        "pins": pins,
        "polarity": polarity,
        "final_eost_pulse": False,
        "begin_outputs": begin_outputs,
        "end_outputs": end_outputs,
        "count": int(parameters.get("count", 1)),
    }


def validate_trigger_list_limits(
    *,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    count: int,
) -> None:
    if not voltages:
        raise CoreValidationError("trigger LIST requires at least one step")
    if len(voltages) > 100:
        raise CoreValidationError("trigger LIST supports at most 100 steps")
    if len(currents) != len(voltages):
        raise CoreValidationError("current list length must match voltage list length")
    if len(dwell) != len(voltages):
        raise CoreValidationError("dwell list length must match voltage list length")
    if count < 1 or count > 256:
        raise CoreValidationError("LIST count must be between 1 and 256")
    for seconds in dwell:
        if seconds < 0.01 or seconds > 3600:
            raise CoreValidationError("LIST dwell values must be between 0.01 and 3600 seconds")


def validate_real_trigger_source(request: TriggerRequest, source: str) -> None:
    if request.runtime.simulate or request.runtime.dry_run:
        return
    if source not in {"bus", "immediate"}:
        raise CoreValidationError("real PIN/EXT trigger input is not enabled yet; use --dry-run or --simulate")


def trigger_source_scpi(source: str) -> str:
    normalized = source.strip().lower()
    if normalized == "immediate":
        return "IMM"
    if normalized in {"bus", "pin1", "pin2", "pin3", "ext"}:
        return normalized.upper()
    if normalized == "imm":
        return "IMM"
    raise CoreValidationError("trigger source must be bus, immediate, pin1, pin2, pin3, or ext")


def wait_for_trigger_completion(
    power_supply: E36312APowerSupply,
    *,
    timeout_ms: int,
    poll_ms: int,
    sleep: Callable[[float], None] = time.sleep,
    stop_requested: Callable[[], bool] | None = None,
) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    try:
        power_supply.prepare_operation_complete_wait()
        while True:
            if stop_requested is not None and stop_requested():
                raise TriggerInterrupted("trigger wait interrupted")
            if power_supply.operation_complete_event():
                return
            if time.monotonic() >= deadline:
                raise TriggerWaitTimeout(f"trigger wait timed out after {timeout_ms} ms")
            sleep_seconds = min(poll_ms / 1000, max(deadline - time.monotonic(), 0))
            if sleep_seconds > 0:
                sleep(sleep_seconds)
    except KeyboardInterrupt as exc:
        raise TriggerInterrupted("trigger wait interrupted") from exc


def _instrument_for_request(request: TriggerRequest, instrument: Any, scpi_logger: Callable[[str, str, str], None] | None) -> Any:
    if request.runtime.log_scpi and scpi_logger is not None:
        return ScpiLoggingSession(str(request.runtime.resource), instrument, scpi_logger)
    return instrument


class ScpiLoggingSession:
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

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def _run_trigger_pulse(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    p = request.parameters
    pins = tuple(p.get("pins") or ((p["pin"],) if p.get("pin") is not None else ()))
    opened = False
    try:
        with opener(request.runtime.resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            instrument = _instrument_for_request(request, instrument, scpi_logger)
            idn = instrument.query(IDN_QUERY)
            _validate_trigger_expected_model(request, idn)
            power_supply = create_power_supply(instrument, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise UnsupportedModelError(
                    "trigger-pulse is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channel = int(p.get("channel", 1))
            voltage = power_supply.programmed_voltage(channel=channel)
            current = power_supply.programmed_current(channel=channel)
            raise_if_cancelled(stop_requested)
            configure_completion_output_pins(
                power_supply,
                pins,
                str(p.get("polarity", "positive")),
                exclusive_pins=bool(p.get("exclusive_pins", False)),
            )
            power_supply.set_triggered_current(channel=channel, current=current)
            power_supply.set_triggered_voltage(channel=channel, voltage=voltage)
            power_supply.set_trigger_modes(channel=channel, current_mode="STEP", voltage_mode="STEP")
            power_supply.configure_output_trigger_source_bus(channel)
            raise_if_cancelled(stop_requested)
            power_supply.trigger_pulse(channel=channel)
            _raise_on_instrument_errors(power_supply, request.command)
            data = {
                "_resource": request.runtime.resource,
                "idn": idn,
                "pins": list(pins),
                "exclusive_pins": bool(p.get("exclusive_pins", False)),
                "channel": channel,
                "polarity": str(p.get("polarity", "positive")),
                "triggered": True,
                "trigger_setpoints": {"current": current, "voltage": voltage},
            }
            if p.get("pin") is not None:
                data["pin"] = p["pin"]
                data["exclusive_pin"] = bool(p.get("exclusive_pins", False))
            return data
    except VisaConnectionError as exc:
        raise CoreIoError(f"{'trigger-pulse failed' if opened else 'Could not open resource for trigger-pulse'}: {exc}", opened=opened) from exc


def _run_trigger_status(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    p = request.parameters
    selected = p.get("channel", "all")
    channels = (1, 2, 3) if selected == "all" else (int(selected),)
    opened = False
    try:
        with opener(request.runtime.resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            instrument = _instrument_for_request(request, instrument, scpi_logger)
            idn = instrument.query(IDN_QUERY)
            _validate_trigger_expected_model(request, idn)
            power_supply = create_power_supply(instrument, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise UnsupportedModelError(
                    "trigger-status is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = _trigger_channels_from_selection(selected, power_supply.capabilities.channels)
            return {
                "_resource": request.runtime.resource,
                "idn": idn,
                "digital_pins": [
                    {
                        "pin": pin,
                        "function": power_supply.digital_pin_function(pin),
                        "polarity": power_supply.digital_pin_polarity(pin),
                    }
                    for pin in (1, 2, 3)
                ],
                "trigger_output_bus_enabled": power_supply.trigger_output_bus_enabled(),
                "channels": [_trigger_channel_status(power_supply, channel) for channel in channels],
            }
    except VisaConnectionError as exc:
        raise CoreIoError(f"{'trigger-status failed' if opened else 'Could not open resource for trigger-status'}: {exc}", opened=opened) from exc


def _trigger_channels_from_selection(selected: int | str, supported_channels: tuple[int, ...]) -> tuple[int, ...]:
    if selected == "all":
        return supported_channels
    channel = int(selected)
    if channel not in supported_channels:
        raise CoreValidationError(f"channel {channel} is not supported; supported: {supported_channels}")
    return (channel,)


def _trigger_channel_status(power_supply: E36312APowerSupply, channel: int) -> dict[str, Any]:
    return {
        "channel": channel,
        "trigger": {
            "source": power_supply.output_trigger_source(channel),
            "delay": power_supply.output_trigger_delay(channel),
            "voltage_mode": power_supply.voltage_trigger_mode(channel),
            "current_mode": power_supply.current_trigger_mode(channel),
            "triggered_voltage": power_supply.triggered_voltage(channel),
            "triggered_current": power_supply.triggered_current(channel),
        },
        "list": {
            "voltage": list(power_supply.list_voltage(channel)),
            "current": list(power_supply.list_current(channel)),
            "dwell": list(power_supply.list_dwell(channel)),
            "tout_bost": list(power_supply.list_trigger_output_begin(channel)),
            "tout_eost": list(power_supply.list_trigger_output_end(channel)),
            "count": power_supply.list_count(channel),
            "step_mode": power_supply.list_step_mode(channel),
            "terminate_last": power_supply.list_terminate_last(channel),
        },
    }


def _run_trigger_step(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    p = request.parameters
    validate_real_trigger_source(request, str(p.get("source", "bus")))
    opened = False
    try:
        with opener(request.runtime.resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            instrument = _instrument_for_request(request, instrument, scpi_logger)
            power_supply = _trigger_power_supply(
                instrument,
                simulate=request.runtime.simulate,
                command=request.command,
                expected_model=request.runtime.model_profile,
            )
            if isinstance(power_supply, E36312APowerSupply):
                trigger = _native_step(
                    request,
                    power_supply,
                    channel=int(p["channel"]),
                    source=str(p.get("source", "bus")),
                    voltage=p.get("voltage"),
                    current=p.get("current"),
                    pins=tuple(p.get("completion_pulse_pins") or ()),
                    polarity=str(p.get("completion_pulse_polarity", "positive")),
                    fire=bool(p.get("fire", False)),
                    wait_complete=bool(p.get("wait_complete", False)),
                    sleep=sleep,
                    stop_requested=stop_requested,
                )
            else:
                raise UnsupportedModelError("trigger-step is only supported for E36312A")
            _raise_on_instrument_errors(power_supply, request.command)
            return {"_resource": request.runtime.resource, "idn": getattr(power_supply, "_core_idn_raw", None), "trigger": trigger}
    except VisaConnectionError as exc:
        raise CoreIoError(f"trigger-step failed: {exc}", opened=opened) from exc


def _run_trigger_list(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    p = request.parameters
    config = trigger_list_config(p)
    validate_real_trigger_source(request, str(config["source"]))
    opened = False
    try:
        with opener(request.runtime.resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            instrument = _instrument_for_request(request, instrument, scpi_logger)
            power_supply = _trigger_power_supply(
                instrument,
                simulate=request.runtime.simulate,
                command=request.command,
                expected_model=request.runtime.model_profile,
            )
            if not isinstance(power_supply, E36312APowerSupply):
                raise UnsupportedModelError("trigger-list is only supported for E36312A")
            trigger = _native_list(
                request,
                power_supply,
                **config,
                exclusive_pins=bool(p.get("exclusive_pins", False)),
                fire=bool(p.get("fire", False)),
                wait_complete=bool(p.get("wait_complete", False)),
                sleep=sleep,
                stop_requested=stop_requested,
            )
            _raise_on_instrument_errors(power_supply, request.command)
            return {
                "_resource": request.runtime.resource,
                "idn": getattr(power_supply, "_core_idn_raw", None),
                "steps": len(config["voltages"]),
                "trigger": trigger,
            }
    except VisaConnectionError as exc:
        raise CoreIoError(f"trigger-list failed: {exc}", opened=opened) from exc


def _run_trigger_fire(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    p = request.parameters
    opened = False
    try:
        with opener(request.runtime.resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            instrument = _instrument_for_request(request, instrument, scpi_logger)
            power_supply = _trigger_power_supply(
                instrument,
                simulate=request.runtime.simulate,
                command=request.command,
                expected_model=request.runtime.model_profile,
            )
            if not isinstance(power_supply, E36312APowerSupply):
                raise UnsupportedModelError("trigger-fire is only supported for E36312A")
            power_supply.fire_bus_trigger()
            completed = False
            if p.get("wait_complete", False):
                channel = p.get("channel")
                try:
                    wait_for_trigger_completion(power_supply, timeout_ms=_trigger_wait_timeout_ms(p), poll_ms=_trigger_poll_interval_ms(p), sleep=sleep, stop_requested=stop_requested)
                    completed = True
                except (TriggerInterrupted, TriggerWaitTimeout):
                    if channel is not None:
                        power_supply.abort_output_trigger(int(channel))
                    raise
            _raise_on_instrument_errors(power_supply, request.command)
            return {
                "_resource": request.runtime.resource,
                "idn": getattr(power_supply, "_core_idn_raw", None),
                "trigger": trigger_result_payload(
                    mode="fire",
                    native=True,
                    channel=int(p["channel"]) if p.get("channel") is not None else None,
                    armed=False,
                    fired=True,
                    completed=completed,
                    wait_timeout_ms=_trigger_wait_timeout_ms(p) if p.get("wait_complete", False) else None,
                    poll_ms=_trigger_poll_interval_ms(p) if p.get("wait_complete", False) else None,
                )
            }
    except VisaConnectionError as exc:
        raise CoreIoError(f"trigger-fire failed: {exc}", opened=opened) from exc


def _run_trigger_abort(
    request: TriggerRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    p = request.parameters
    channel = p.get("channel", "all")
    channels = (1, 2, 3) if channel == "all" else (int(channel),)
    opened = False
    try:
        with opener(request.runtime.resource, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            instrument = _instrument_for_request(request, instrument, scpi_logger)
            power_supply = _trigger_power_supply(
                instrument,
                simulate=request.runtime.simulate,
                command=request.command,
                expected_model=request.runtime.model_profile,
            )
            if not isinstance(power_supply, E36312APowerSupply):
                raise UnsupportedModelError("trigger-abort is only supported for E36312A")
            errors = []
            for selected_channel in channels:
                try:
                    power_supply.abort_output_trigger(selected_channel)
                except Exception as exc:
                    errors.append(str(exc))
            queue_errors, read_count = _read_error_queue(power_supply, int(p.get("max_errors", 20)))
            if queue_errors:
                raise CoreExecutionError(f"{request.command} completed with instrument errors: {queue_errors}")
            return {
                "_resource": request.runtime.resource,
                "idn": getattr(power_supply, "_core_idn_raw", None),
                "channels": list(channels),
                "errors": errors,
                "read_count": read_count,
            }
    except VisaConnectionError as exc:
        raise CoreIoError(f"trigger-abort failed: {exc}", opened=opened) from exc


def _native_step(
    request: TriggerRequest,
    power_supply: E36312APowerSupply,
    *,
    channel: int,
    source: str,
    voltage: float | None,
    current: float | None,
    pins: tuple[int, ...],
    polarity: str,
    fire: bool,
    wait_complete: bool,
    sleep: Callable[[float], None],
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    selected_voltage = power_supply.programmed_voltage(channel=channel) if voltage is None else voltage
    selected_current = power_supply.programmed_current(channel=channel) if current is None else current
    validate_effective_setpoint(
        model="E36312A",
        channel=channel,
        electrical_ratings=power_supply.capabilities.electrical_ratings,
        voltage=selected_voltage,
        current=selected_current,
    )
    snapshot = power_supply.trigger_snapshot(channel)
    try:
        raise_if_cancelled(stop_requested)
        power_supply.abort_output_trigger(channel)
        configure_completion_output_pins(power_supply, pins, polarity)
        power_supply.set_triggered_current(channel=channel, current=selected_current)
        power_supply.set_triggered_voltage(channel=channel, voltage=selected_voltage)
        power_supply.set_trigger_modes(channel=channel, current_mode="STEP", voltage_mode="STEP")
        power_supply.set_output_trigger_source(channel=channel, source=trigger_source_scpi(source))
        power_supply.initiate_output_trigger(channel)
        fired = False
        if source == "bus" and fire:
            power_supply.fire_bus_trigger()
            fired = True
        elif source == "immediate":
            fired = True
        completed = False
        if wait_complete:
            try:
                wait_for_trigger_completion(
                    power_supply,
                    timeout_ms=_trigger_wait_timeout_ms(request.parameters),
                    poll_ms=_trigger_poll_interval_ms(request.parameters),
                    sleep=sleep,
                    stop_requested=stop_requested,
                )
                completed = True
            except (TriggerInterrupted, TriggerWaitTimeout):
                power_supply.abort_output_trigger(channel)
                raise
    finally:
        if not request.parameters.get("leave_trigger_configured", False):
            power_supply.restore_trigger_snapshot(snapshot)
    return trigger_result_payload(
        mode="step",
        native=True,
        channel=channel,
        pins=pins,
        polarity=polarity,
        source=source,
        armed=True,
        fired=fired,
        completed=completed,
        wait_timeout_ms=_trigger_wait_timeout_ms(request.parameters) if wait_complete else None,
        poll_ms=_trigger_poll_interval_ms(request.parameters) if wait_complete else None,
        restored=not request.parameters.get("leave_trigger_configured", False),
    )


def _native_list(
    request: TriggerRequest,
    power_supply: E36312APowerSupply,
    *,
    channel: int,
    source: str,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    pins: tuple[int, ...],
    polarity: str,
    final_eost_pulse: bool,
    count: int,
    exclusive_pins: bool,
    fire: bool,
    wait_complete: bool,
    sleep: Callable[[float], None],
    begin_outputs: tuple[bool, ...] | None = None,
    end_outputs: tuple[bool, ...] | None = None,
    result_mode: str = "list",
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    validate_trigger_list_limits(voltages=voltages, currents=currents, dwell=dwell, count=count)
    for voltage, current in zip(voltages, currents):
        validate_effective_setpoint(
            model="E36312A",
            channel=channel,
            electrical_ratings=power_supply.capabilities.electrical_ratings,
            voltage=voltage,
            current=current,
        )
    snapshot = power_supply.trigger_snapshot(channel)
    try:
        raise_if_cancelled(stop_requested)
        power_supply.abort_output_trigger(channel)
        configure_completion_output_pins(power_supply, pins, polarity, exclusive_pins=exclusive_pins)
        begin_outputs = begin_outputs if begin_outputs is not None else tuple(False for _ in voltages)
        end_outputs = end_outputs if end_outputs is not None else tuple(
            index == len(voltages) - 1 and final_eost_pulse for index, _ in enumerate(voltages)
        )
        power_supply.configure_list(
            channel=channel,
            voltages=voltages,
            currents=currents,
            dwell=dwell,
            begin_outputs=begin_outputs,
            end_outputs=end_outputs,
            count=count,
            step_mode="AUTO",
            terminate_last=True,
        )
        power_supply.set_trigger_modes(channel=channel, current_mode="LIST", voltage_mode="LIST")
        power_supply.set_output_trigger_source(channel=channel, source=trigger_source_scpi(source))
        power_supply.initiate_output_trigger(channel)
        fired = False
        if source == "bus" and fire:
            power_supply.fire_bus_trigger()
            fired = True
        elif source == "immediate":
            fired = True
        completed = False
        if wait_complete:
            try:
                wait_for_trigger_completion(
                    power_supply,
                    timeout_ms=_trigger_wait_timeout_ms(request.parameters, dwell=dwell, count=count),
                    poll_ms=_trigger_poll_interval_ms(request.parameters),
                    sleep=sleep,
                    stop_requested=stop_requested,
                )
                completed = True
            except (TriggerInterrupted, TriggerWaitTimeout):
                power_supply.abort_output_trigger(channel)
                raise
    finally:
        if not request.parameters.get("leave_trigger_configured", False):
            power_supply.restore_trigger_snapshot(snapshot)
    return trigger_result_payload(
        mode=result_mode,
        native=True,
        channel=channel,
        pins=pins,
        polarity=polarity,
        source=source,
        armed=True,
        fired=fired,
        completed=completed,
        wait_timeout_ms=_trigger_wait_timeout_ms(request.parameters, dwell=dwell, count=count) if wait_complete else None,
        poll_ms=_trigger_poll_interval_ms(request.parameters) if wait_complete else None,
        restored=not request.parameters.get("leave_trigger_configured", False),
    )


def _trigger_power_supply(
    instrument: Any,
    *,
    simulate: bool,
    command: str,
    expected_model: str | None = None,
) -> Any:
    idn = instrument.query(IDN_QUERY)
    validate_live_expected_model(expected_model, parse_idn(idn).model, command=command)
    power_supply = create_power_supply(instrument, idn)
    setattr(power_supply, "_core_idn_raw", idn)
    return power_supply


def _validate_trigger_expected_model(request: TriggerRequest, idn: str) -> None:
    validate_live_expected_model(
        request.runtime.model_profile,
        parse_idn(idn).model,
        command=request.command,
    )


def _raise_on_instrument_errors(power_supply: Any, command: str) -> None:
    errors, _read_count = _read_error_queue(power_supply, 20)
    if errors:
        hint = ""
        if command == "trigger-fire" and any('-211,"Trigger ignored"' in error for error in errors):
            hint = "; no armed BUS trigger may be available"
        raise CoreExecutionError(f"{command} completed with instrument errors: {errors}{hint}")


def _read_error_queue(power_supply: Any, max_errors: int) -> tuple[list[str], int]:
    return power_supply.read_error_queue(max_errors)


def _wait_complete_preview_commands(wait_complete: bool) -> tuple[str, ...]:
    if not wait_complete:
        return ()
    return ("*CLS", "*ESE 1", "*OPC", "*ESR?")


def _trigger_wait_timeout_ms(parameters: dict[str, Any], *, dwell: tuple[float, ...] = (), count: int = 1) -> int:
    configured = parameters.get("wait_timeout_ms")
    if configured is not None:
        return int(configured)
    if dwell:
        return int(sum(dwell) * max(count, 1) * 1000) + 5000
    return 10000


def _trigger_poll_interval_ms(parameters: dict[str, Any]) -> int:
    return max(int(parameters.get("poll_ms", 200)), 50)


def _format_text_value(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def _number_csv(values: Sequence[float]) -> str:
    return ",".join(_format_text_value(value) for value in values)


def _bool_csv(values: Sequence[bool]) -> str:
    return ",".join("1" if value else "0" for value in values)


def _float_tuple(value: Any) -> tuple[float, ...] | None:
    if value is None:
        return None
    if isinstance(value, tuple):
        return tuple(float(item) for item in value)
    if isinstance(value, list):
        return tuple(float(item) for item in value)
    return (float(value),)


def _bool_tuple(value: Any) -> tuple[bool, ...] | None:
    if value is None:
        return None
    values = value if isinstance(value, (list, tuple)) else (value,)
    if any(not isinstance(item, bool) for item in values):
        raise CoreValidationError("trigger-list BOST/EOST lists must contain only booleans")
    return tuple(values)
