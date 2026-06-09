"""Safe command line interface for Keysight power supplies."""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Sequence
from typing import Any

from keysight_power.cli_io import emit_json_error, emit_json_success
from keysight_power.connection import DEFAULT_TIMEOUT_MS, list_resources, open_resource
from keysight_power.drivers.generic_scpi import GenericScpiPowerSupply
from keysight_power.drivers.e36312a import E36312APowerSupply
from keysight_power.errors import VisaConnectionError
from keysight_power.factory import create_power_supply
from keysight_power.models import parse_idn, resource_interface
from keysight_power.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    resolve_safety_config,
    validate_channel,
    validate_setpoint,
)
from keysight_power.testing.simulator import SimulatedResourceManager
from keysight_power.transport import dry_run_plan

IDN_QUERY = "*IDN?"
CLEAR_STATUS_COMMAND = "*CLS"
ERROR_QUERY = "SYST:ERR?"
MEASURE_VOLTAGE_QUERY = "MEAS:VOLT?"
MEASURE_CURRENT_QUERY = "MEAS:CURR?"
COMMAND_NAMES = frozenset(
    {
        "list-resources",
        "verify",
        "clear",
        "error",
        "measure",
        "measure-all",
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "output-state",
        "cycle-output",
        "apply",
        "trigger-pulse",
        "status",
    }
)


class JsonCliArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that keeps JSON validation errors machine-readable."""

    active_argv: tuple[str, ...] = ()

    def error(self, message: str) -> None:
        if "--json" in self.active_argv:
            command = _command_from_argv(self.active_argv)
            emit_json_error(
                command=command,
                execution=_validation_execution_from_argv(self.active_argv),
                request=_request_from_argv(command, self.active_argv),
                error_type="validation",
                code="argument_error",
                message=message,
                retryable=False,
            )
            raise SystemExit(2)

        super().error(message)


class _MeasureChannelUnsupported(ValueError):
    """Raised when a measure channel is outside conservative driver capability."""


class _ScpiLoggingSession:
    """Session proxy that logs SCPI traffic while preserving driver behavior."""

    def __init__(self, resource: str, session: Any) -> None:
        self._resource = resource
        self._session = session

    def write(self, command: str) -> Any:
        _log_scpi(self._resource, ">>", command)
        return self._session.write(command)

    def query(self, command: str) -> str:
        _log_scpi(self._resource, ">>", command)
        response = self._session.query(command)
        _log_scpi(self._resource, "<<", response)
        return response

    def close(self) -> None:
        self._session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = JsonCliArgumentParser(
        prog="keysight_power.cli",
        description="Safe CLI tools for Keysight DC power supplies.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=JsonCliArgumentParser,
    )

    list_parser = subparsers.add_parser(
        "list-resources",
        help="List VISA resource strings reported by the selected backend.",
    )
    _add_json_argument(list_parser)
    _add_simulate_argument(list_parser)
    _add_backend_argument(list_parser)
    _add_timeout_argument(list_parser)
    list_parser.add_argument(
        "--live-only",
        action="store_true",
        help="Only print resources that can be opened and queried with *IDN?.",
    )
    list_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for live checks.",
    )
    list_parser.set_defaults(func=_run_list_resources)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify that one VISA resource can be opened and queried with *IDN?.",
    )
    verify_parser.add_argument("--resource", required=True, help="VISA resource string.")
    _add_json_argument(verify_parser)
    _add_simulate_argument(verify_parser)
    _add_backend_argument(verify_parser)
    _add_timeout_argument(verify_parser)
    verify_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print the SCPI command and response for the verification query.",
    )
    verify_parser.set_defaults(func=_run_verify)

    clear_parser = subparsers.add_parser(
        "clear",
        help="Clear instrument status and error queue with *CLS.",
    )
    _add_resource_argument(clear_parser)
    _add_json_argument(clear_parser)
    _add_simulate_argument(clear_parser)
    _add_dry_run_argument(clear_parser)
    _add_backend_argument(clear_parser)
    _add_timeout_argument(clear_parser)
    clear_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print the SCPI clear command.",
    )
    clear_parser.set_defaults(func=_run_clear)

    error_parser = subparsers.add_parser(
        "error",
        help="Read the instrument error queue with SYST:ERR?.",
    )
    _add_resource_argument(error_parser)
    _add_json_argument(error_parser)
    _add_simulate_argument(error_parser)
    _add_backend_argument(error_parser)
    _add_timeout_argument(error_parser)
    error_parser.add_argument(
        "--max-reads",
        type=_positive_max_reads,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    error_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for the error query.",
    )
    error_parser.set_defaults(func=_run_error)

    measure_parser = subparsers.add_parser(
        "measure",
        help="Query measured voltage and current for the selected channel.",
    )
    _add_resource_argument(measure_parser)
    measure_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help=(
            "Positive integer output channel. Real mode allows channel 1 for "
            "the generic path and model-specific measured channels after *IDN?."
        ),
    )
    _add_json_argument(measure_parser)
    _add_simulate_argument(measure_parser)
    _add_backend_argument(measure_parser)
    _add_timeout_argument(measure_parser)
    measure_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for measurements.",
    )
    measure_parser.set_defaults(func=_run_measure)

    measure_all_parser = subparsers.add_parser(
        "measure-all",
        help="Query measured voltage and current for all E36312A channels.",
    )
    _add_output_resource_arguments(measure_all_parser)
    _add_json_argument(measure_all_parser)
    _add_simulate_argument(measure_all_parser)
    _add_safety_config_argument(measure_all_parser)
    _add_backend_argument(measure_all_parser)
    _add_timeout_argument(measure_all_parser)
    measure_all_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for measurements.",
    )
    measure_all_parser.set_defaults(func=_run_measure_all)

    set_parser = subparsers.add_parser(
        "set",
        help="Preview safe voltage/current setpoint changes.",
    )
    _add_output_resource_arguments(set_parser)
    set_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help="Positive integer output channel.",
    )
    set_parser.add_argument("--voltage", required=True, type=float, help="Voltage setpoint.")
    set_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    _add_json_argument(set_parser)
    _add_simulate_argument(set_parser)
    _add_dry_run_argument(set_parser)
    _add_safety_config_argument(set_parser)
    _add_backend_argument(set_parser)
    _add_timeout_argument(set_parser)
    set_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    set_parser.set_defaults(func=_run_output_plan)

    output_on_parser = subparsers.add_parser(
        "output-on",
        help="Preview enabling one output channel.",
    )
    _add_output_resource_arguments(output_on_parser)
    output_on_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help="Positive integer output channel.",
    )
    _add_json_argument(output_on_parser)
    _add_simulate_argument(output_on_parser)
    _add_dry_run_argument(output_on_parser)
    _add_safety_config_argument(output_on_parser)
    _add_backend_argument(output_on_parser)
    _add_timeout_argument(output_on_parser)
    output_on_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    output_on_parser.set_defaults(func=_run_output_plan)

    output_off_parser = subparsers.add_parser(
        "output-off",
        help="Disable or preview disabling one output channel.",
    )
    _add_output_resource_arguments(output_off_parser)
    output_off_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help="Positive integer output channel.",
    )
    _add_json_argument(output_off_parser)
    _add_simulate_argument(output_off_parser)
    _add_dry_run_argument(output_off_parser)
    _add_safety_config_argument(output_off_parser)
    _add_backend_argument(output_off_parser)
    _add_timeout_argument(output_off_parser)
    output_off_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    output_off_parser.set_defaults(func=_run_output_plan)

    safe_off_parser = subparsers.add_parser(
        "safe-off",
        help="Preview a conservative output-off action for one channel or all channels.",
    )
    _add_output_resource_arguments(safe_off_parser)
    safe_off_parser.add_argument(
        "--channel",
        required=True,
        type=_safe_off_channel,
        help="Positive integer output channel or 'all'.",
    )
    _add_json_argument(safe_off_parser)
    _add_simulate_argument(safe_off_parser)
    _add_dry_run_argument(safe_off_parser)
    _add_safety_config_argument(safe_off_parser)
    safe_off_parser.set_defaults(func=_run_output_plan)

    output_state_parser = subparsers.add_parser(
        "output-state",
        help="Read the enabled state of one output channel.",
    )
    _add_output_resource_arguments(output_state_parser)
    output_state_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help="Positive integer output channel.",
    )
    _add_json_argument(output_state_parser)
    _add_simulate_argument(output_state_parser)
    _add_dry_run_argument(output_state_parser)
    _add_backend_argument(output_state_parser)
    _add_timeout_argument(output_state_parser)
    output_state_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    output_state_parser.set_defaults(func=_run_output_plan)

    cycle_output_parser = subparsers.add_parser(
        "cycle-output",
        help="Enable output briefly, then disable it again.",
    )
    _add_output_resource_arguments(cycle_output_parser)
    cycle_output_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help="Positive integer output channel.",
    )
    cycle_output_parser.add_argument(
        "--duration-ms",
        type=_positive_duration_ms,
        default=500,
        help="Enable duration in milliseconds.",
    )
    _add_json_argument(cycle_output_parser)
    _add_simulate_argument(cycle_output_parser)
    _add_dry_run_argument(cycle_output_parser)
    _add_safety_config_argument(cycle_output_parser)
    _add_backend_argument(cycle_output_parser)
    _add_timeout_argument(cycle_output_parser)
    cycle_output_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    cycle_output_parser.set_defaults(func=_run_output_plan)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Set low output values and enable output.",
    )
    _add_output_resource_arguments(apply_parser)
    apply_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help="Positive integer output channel.",
    )
    apply_parser.add_argument("--voltage", required=True, type=float, help="Voltage setpoint.")
    apply_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    _add_json_argument(apply_parser)
    _add_simulate_argument(apply_parser)
    _add_dry_run_argument(apply_parser)
    _add_safety_config_argument(apply_parser)
    _add_backend_argument(apply_parser)
    _add_timeout_argument(apply_parser)
    apply_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    apply_parser.set_defaults(func=_run_output_plan)

    trigger_pulse_parser = subparsers.add_parser(
        "trigger-pulse",
        help="Configure a trigger output pin and emit a BUS trigger pulse.",
    )
    _add_output_resource_arguments(trigger_pulse_parser)
    trigger_pulse_parser.add_argument(
        "--pin",
        required=True,
        type=_trigger_pin,
        help="Rear digital trigger output pin 1, 2, or 3.",
    )
    trigger_pulse_parser.add_argument(
        "--polarity",
        choices=("positive", "negative"),
        default="positive",
        help="Trigger output polarity.",
    )
    _add_json_argument(trigger_pulse_parser)
    _add_simulate_argument(trigger_pulse_parser)
    _add_dry_run_argument(trigger_pulse_parser)
    _add_safety_config_argument(trigger_pulse_parser)
    _add_backend_argument(trigger_pulse_parser)
    _add_timeout_argument(trigger_pulse_parser)
    trigger_pulse_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    trigger_pulse_parser.set_defaults(func=_run_trigger_pulse)

    status_parser = subparsers.add_parser(
        "status",
        help="Read error queue and selected channel output state(s).",
    )
    _add_output_resource_arguments(status_parser)
    status_parser.add_argument(
        "--channel",
        default="all",
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    status_parser.add_argument(
        "--all",
        action="store_true",
        help="Read all E36312A output channels.",
    )
    status_parser.add_argument(
        "--max-errors",
        type=_positive_max_errors,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    _add_json_argument(status_parser)
    _add_simulate_argument(status_parser)
    _add_safety_config_argument(status_parser)
    _add_backend_argument(status_parser)
    _add_timeout_argument(status_parser)
    status_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    status_parser.set_defaults(func=_run_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    JsonCliArgumentParser.active_argv = raw_argv
    try:
        args = build_parser().parse_args(raw_argv)
    except SystemExit as exc:
        return _exit_code(exc)
    finally:
        JsonCliArgumentParser.active_argv = ()
    return int(args.func(args))


def _add_backend_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", help="Optional PyVISA backend.")


def _add_timeout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="VISA timeout in milliseconds.",
    )


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON to stdout.",
    )


def _add_simulate_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use deterministic simulated resources instead of real VISA resources.",
    )


def _add_dry_run_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the logical operation without opening or writing to hardware.",
    )


def _add_duration_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--duration-ms",
        type=_positive_duration_ms,
        default=500,
        help="Enable duration in milliseconds.",
    )


def _add_resource_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--resource", required=True, help="VISA resource string.")


def _add_output_resource_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--resource", help="VISA resource string.")
    group.add_argument(
        "--resource-alias",
        help="Alias from an explicit --safety-config [[resources]] entry.",
    )


def _add_safety_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--safety-config",
        help="Explicit TOML safety config path with global or resource limits.",
    )


def _run_list_resources(args: argparse.Namespace) -> int:
    manager = _resource_manager_for_args(args)
    execution = _execution_for_args(args, hardware_intent=args.live_only)
    request = _request_for_args(args)
    try:
        resources = _list_resources(manager, backend=args.backend)
    except VisaConnectionError as exc:
        message = f"Could not list VISA resources: {exc}"
        if args.json:
            emit_json_error(
                command="list-resources",
                execution=execution,
                request=request,
                error_type="connection",
                code="resource_list_failed",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 1

    if args.live_only:
        live: list[dict[str, Any]] = []
        for resource in resources:
            idn = _query_idn(
                resource,
                resource_manager=manager,
                backend=args.backend,
                timeout_ms=args.timeout_ms,
                log_scpi=args.log_scpi,
            )
            if idn is not None:
                live.append(
                    _resource_payload(
                        resource,
                        simulated=args.simulate,
                        reachable=True,
                        idn_raw=idn,
                    )
                )

        if args.json:
            emit_json_success(
                command="list-resources",
                execution=execution,
                request=request,
                data={
                    "resources": live,
                    "count": len(live),
                },
            )
            return 0

        if not live:
            print("No live VISA resources found.")
            return 0

        for resource in live:
            print(resource["name"])
        return 0

    if args.json:
        resource_payloads = [
            _resource_payload(
                resource,
                simulated=args.simulate,
                reachable=None,
                idn_raw=None,
            )
            for resource in resources
        ]
        emit_json_success(
            command="list-resources",
            execution=execution,
            request=request,
            data={"resources": resource_payloads, "count": len(resource_payloads)},
        )
        return 0

    if not resources:
        print("No VISA resources found.")
        return 0

    for resource in resources:
        print(resource)
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    manager = _resource_manager_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    request = _request_for_args(args)
    idn = _query_idn(
        args.resource,
        resource_manager=manager,
        backend=args.backend,
        timeout_ms=args.timeout_ms,
        log_scpi=args.log_scpi,
    )
    if idn is None:
        message = f"Could not verify VISA resource: {args.resource}"
        if args.json:
            emit_json_error(
                command="verify",
                execution=execution,
                request=request,
                error_type="connection",
                code="resource_unreachable",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 1

    if args.json:
        emit_json_success(
            command="verify",
            execution=execution,
            request=request,
            data={
                "resource": _resource_payload(
                    args.resource,
                    simulated=args.simulate,
                    reachable=True,
                    idn_raw=idn,
                )
            },
        )
        return 0

    print(idn)
    return 0


def _run_clear(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)

    if args.dry_run:
        plan = dry_run_plan(
            command="clear",
            resource=args.resource,
            scpi=(CLEAR_STATUS_COMMAND,),
            description="Preview clearing instrument status and error queue.",
        )
        if args.json:
            emit_json_success(
                command="clear",
                execution=execution,
                request=request,
                data={"plan": plan},
            )
            return 0

        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    manager = _resource_manager_for_args(args)
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            if args.log_scpi:
                _log_scpi(args.resource, ">>", CLEAR_STATUS_COMMAND)
            instrument.write(CLEAR_STATUS_COMMAND)
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="status_clear_failed",
            message=f"Could not clear instrument status for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="clear",
            execution=execution,
            request=request,
            data={
                "resource": _safe_io_resource_payload(args),
                "cleared": True,
            },
        )
        return 0

    print(f"Cleared instrument status for {args.resource}")
    return 0


def _run_error(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        errors, read_count = _read_error_queue(
            args.resource,
            resource_manager=manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
            log_scpi=args.log_scpi,
            max_reads=args.max_reads,
        )
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="error_query_failed",
            message=f"Could not query error queue for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="error",
            execution=execution,
            request=request,
            data={
                "resource": _safe_io_resource_payload(args),
                "errors": errors,
                "read_count": read_count,
                "max_reads": args.max_reads,
            },
        )
        return 0

    if not errors:
        print("No instrument errors.")
        return 0

    for error in errors:
        print(error)
    return 0


def _run_measure(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        measurements = _measure_voltage_current(
            args.resource,
            resource_manager=manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
            log_scpi=args.log_scpi,
            channel=args.channel,
            simulate=args.simulate,
        )
    except _MeasureChannelUnsupported as exc:
        if args.json:
            emit_json_error(
                command="measure",
                execution=execution,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="measurement_failed",
            message=f"Could not measure voltage/current for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="measure",
            execution=execution,
            request=request,
            data={
                "resource": _safe_io_resource_payload(args),
                "channel": args.channel,
                "measurements": measurements,
            },
        )
        return 0

    print(f"Voltage: {_format_text_value(measurements['voltage'])} V")
    print(f"Current: {_format_text_value(measurements['current'])} A")
    return 0


def _run_measure_all(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    opened = False
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _MeasureAllModelError(
                    "measure-all is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = []
            for channel in (1, 2, 3):
                channels.append(
                    {
                        "channel": channel,
                        "measurements": {
                            "voltage": power_supply.measure_voltage(channel=channel),
                            "current": power_supply.measure_current(channel=channel),
                        },
                    }
                )
    except _MeasureAllModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_measure_all",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        code = "measure_all_failed" if opened else "connection_failed"
        message = (
            f"measure-all failed: {exc}"
            if opened
            else f"Could not open resource for measure-all: {exc}"
        )
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=code,
            message=message,
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="measure_all_failed",
            message=f"measure-all failed: {exc}",
        )

    data = {
        "resource": args.resource,
        "channels": channels,
    }
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    for channel in channels:
        measurements = channel["measurements"]
        print(
            f"Channel {channel['channel']}: "
            f"{_format_text_value(measurements['voltage'])} V, "
            f"{_format_text_value(measurements['current'])} A"
        )
    return 0


def _run_trigger_pulse(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    scpi = _trigger_pulse_scpi(args.pin, args.polarity)
    if args.dry_run:
        plan = dry_run_plan(
            command=args.command,
            resource=args.resource,
            scpi=scpi,
            description=(
                "Preview configuring an E36312A rear digital trigger output pin "
                "and issuing *TRG. *TRG may also trigger any already armed "
                "BUS-triggered behavior on the instrument."
            ),
        )
        if args.json:
            emit_json_success(
                command=args.command,
                execution=execution,
                request=request,
                data={"plan": plan},
            )
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    opened = False
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _TriggerPulseModelError(
                    "trigger-pulse is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            power_supply.configure_trigger_output_pin(args.pin, args.polarity)
            power_supply.enable_trigger_output_bus(True)
            power_supply.trigger_pulse()
    except _TriggerPulseModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_trigger_pulse",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        code = "trigger_pulse_failed" if opened else "connection_failed"
        message = (
            f"trigger-pulse failed: {exc}"
            if opened
            else f"Could not open resource for trigger-pulse: {exc}"
        )
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=code,
            message=message,
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="trigger_pulse_failed",
            message=f"trigger-pulse failed: {exc}",
        )

    data = {
        "resource": args.resource,
        "pin": args.pin,
        "polarity": args.polarity,
        "triggered": True,
    }
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Pin: {args.pin}")
    print(f"Polarity: {args.polarity}")
    print("Triggered: True")
    return 0


def _run_status(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    selected_channel = "all" if args.all else args.channel
    opened = False
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _StatusModelError(
                    "status is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = power_supply.capabilities.channels if selected_channel == "all" else (selected_channel,)
            if any(channel not in power_supply.capabilities.channels for channel in channels):
                raise _StatusChannelError(
                    f"channel {selected_channel} is not supported for status; "
                    f"supported: {power_supply.capabilities.channels}"
                )
            errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
            outputs = [
                {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
                for channel in channels
            ]
    except _StatusModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_status",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _StatusChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        code = "status_failed" if opened else "connection_failed"
        message = (
            f"status failed: {exc}"
            if opened
            else f"Could not open resource for status: {exc}"
        )
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=code,
            message=message,
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="status_failed",
            message=f"status failed: {exc}",
        )

    data = {
        "resource": args.resource,
        "errors": errors,
        "read_count": read_count,
        "outputs": outputs,
    }
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    if errors:
        for error in errors:
            print(f"Error: {error}")
    else:
        print("Errors: none")
    for output in outputs:
        print(f"Channel {output['channel']}: Output enabled: {str(output['enabled']).lower()}")
    return 0


def _run_output_plan(args: argparse.Namespace) -> int:
    if not args.simulate and not args.dry_run:
        real_handlers = {
            "set": _run_set_real,
            "output-on": _run_output_on_real,
            "output-off": _run_output_off_real,
            "safe-off": _run_safe_off_real,
            "output-state": _run_output_state_real,
            "cycle-output": _run_cycle_output_real,
            "apply": _run_apply_real,
        }
        handler = real_handlers.get(args.command)
        if handler is not None:
            return handler(args)

    request = _request_for_args(args)
    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    if not args.simulate and not args.dry_run:
        return _emit_cli_error(
            args,
            request=request,
            error_type="safety",
            code="real_execution_disabled",
            message=(
                "Real output execution is disabled; use --dry-run to preview the "
                "operation or --simulate for simulator-safe planning."
            ),
            retryable=False,
        )

    plan = _output_plan_for_args(args)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=args.command != "safe-off"),
            request=request,
            data={"plan": plan},
        )
        return 0

    _print_output_plan(plan, mode=_mode_for_args(args), dry_run=args.dry_run)
    return 0


def _query_idn(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
) -> str | None:
    try:
        with _open_resource(
            resource,
            resource_manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            if log_scpi:
                _log_scpi(resource, ">>", IDN_QUERY)
            response = instrument.identify()
            if log_scpi:
                _log_scpi(resource, "<<", response)
            return response
    except (VisaConnectionError, ValueError):
        return None


def _read_error_queue(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
    max_reads: int,
) -> tuple[list[str], int]:
    errors: list[str] = []
    read_count = 0
    with _open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        for _ in range(max_reads):
            if log_scpi:
                _log_scpi(resource, ">>", ERROR_QUERY)
            response = instrument.query(ERROR_QUERY)
            read_count += 1
            if log_scpi:
                _log_scpi(resource, "<<", response)
            if _is_no_error_response(response):
                break
            errors.append(response)
    return errors, read_count


def _measure_voltage_current(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
    channel: int,
    simulate: bool,
) -> dict[str, float]:
    with _open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        if simulate:
            return _measure_voltage_current_with_driver(
                resource,
                instrument,
                channel=channel,
                log_scpi=log_scpi,
                mode="simulate",
            )

        if channel not in GenericScpiPowerSupply.capabilities.real_measure_channels:
            return _measure_voltage_current_with_driver(
                resource,
                instrument,
                channel=channel,
                log_scpi=log_scpi,
                mode="real",
            )

        if log_scpi:
            _log_scpi(resource, ">>", MEASURE_VOLTAGE_QUERY)
        voltage_response = instrument.query(MEASURE_VOLTAGE_QUERY)
        if log_scpi:
            _log_scpi(resource, "<<", voltage_response)
            _log_scpi(resource, ">>", MEASURE_CURRENT_QUERY)
        current_response = instrument.query(MEASURE_CURRENT_QUERY)
        if log_scpi:
            _log_scpi(resource, "<<", current_response)

    return {
        "voltage": _parse_measurement(voltage_response, "voltage"),
        "current": _parse_measurement(current_response, "current"),
    }


def _measure_voltage_current_with_driver(
    resource: str,
    instrument: Any,
    *,
    channel: int,
    log_scpi: bool,
    mode: str,
) -> dict[str, float]:
    session = _ScpiLoggingSession(resource, instrument) if log_scpi else instrument
    idn = session.query(IDN_QUERY)
    power_supply = create_power_supply(session, idn)
    capabilities = power_supply.capabilities
    allowed_channels = (
        capabilities.simulated_measure_channels
        if mode == "simulate"
        else capabilities.real_measure_channels
    )
    if channel not in allowed_channels:
        raise _MeasureChannelUnsupported(
            _unsupported_measure_channel_message(
                channel=channel,
                mode=mode,
                driver_name=type(power_supply).__name__,
                allowed_channels=allowed_channels,
            )
        )

    return {
        "voltage": power_supply.measure_voltage(channel=channel),
        "current": power_supply.measure_current(channel=channel),
    }


def _resolve_optional_resource_alias(args: argparse.Namespace) -> None:
    if getattr(args, "resource_alias", None) is None:
        return
    _safety_limits_for_args(args)


def _trigger_pulse_scpi(pin: int, polarity: str) -> tuple[str, ...]:
    polarity_command = "POS" if polarity == "positive" else "NEG"
    return (
        f"DIG:PIN{pin}:FUNC TOUT",
        f"DIG:PIN{pin}:POL {polarity_command}",
        "DIG:TOUT:BUS ON",
        "*TRG",
    )


def _read_error_queue_from_driver(
    power_supply: GenericScpiPowerSupply,
    max_reads: int,
) -> tuple[list[str], int]:
    if max_reads < 1:
        raise ValueError("max_errors must be at least 1")

    errors: list[str] = []
    read_count = 0
    for _ in range(max_reads):
        response = power_supply._session.query(ERROR_QUERY).strip()
        read_count += 1
        if _is_no_error_response(response):
            break
        errors.append(response)
    return errors, read_count


def _resource_payload(
    name: str,
    *,
    simulated: bool,
    reachable: bool | None,
    idn_raw: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "interface": resource_interface(name),
        "simulated": simulated,
        "reachable": reachable,
        "idn": parse_idn(idn_raw).to_dict() if idn_raw is not None else None,
    }


def _safe_io_resource_payload(args: argparse.Namespace) -> dict[str, Any]:
    return _resource_payload(
        args.resource,
        simulated=args.simulate,
        reachable=True,
        idn_raw=None,
    )


def _resource_manager_for_args(args: argparse.Namespace) -> SimulatedResourceManager | None:
    if args.simulate:
        return SimulatedResourceManager()
    return None


class _OutputOffModelError(ValueError):
    """Raised when output-off is attempted on a non-E36312A model."""


class _OutputOffChannelError(ValueError):
    """Raised when output-off channel is outside E36312A capability (1,2,3)."""


class _OutputOnModelError(ValueError):
    """Raised when output-on is attempted on a non-E36312A model."""


class _OutputOnChannelError(ValueError):
    """Raised when output-on channel is outside E36312A capability (1,2,3)."""


class _SafeOffModelError(ValueError):
    """Raised when safe-off is attempted on a non-E36312A model."""


class _SafeOffChannelError(ValueError):
    """Raised when safe-off channel is outside E36312A capability (1,2,3)."""


class _OutputStateModelError(ValueError):
    """Raised when output-state is attempted on a non-E36312A model."""


class _OutputStateChannelError(ValueError):
    """Raised when output-state channel is outside E36312A capability (1,2,3)."""


class _CycleOutputModelError(ValueError):
    """Raised when cycle-output is attempted on a non-E36312A model."""


class _CycleOutputChannelError(ValueError):
    """Raised when cycle-output channel is outside E36312A capability (1,2,3)."""


class _ApplyModelError(ValueError):
    """Raised when apply is attempted on a non-E36312A model."""


class _ApplyChannelError(ValueError):
    """Raised when apply channel is outside E36312A capability (1,2,3)."""


class _SetModelError(ValueError):
    """Raised when set is attempted on a non-E36312A model."""


class _SetChannelError(ValueError):
    """Raised when set channel is outside E36312A capability (1,2,3)."""


class _MeasureAllModelError(ValueError):
    """Raised when measure-all is attempted on a non-E36312A model."""


class _TriggerPulseModelError(ValueError):
    """Raised when trigger-pulse is attempted on a non-E36312A model."""


class _StatusModelError(ValueError):
    """Raised when status is attempted on a non-E36312A model."""


class _StatusChannelError(ValueError):
    """Raised when status channel is outside E36312A capability (1,2,3)."""


def _run_set_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    opened = False
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _SetModelError(
                    "set real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            capabilities = power_supply.capabilities
            if args.channel not in capabilities.channels:
                raise _SetChannelError(
                    f"channel {args.channel} is not supported for set; "
                    f"supported: {capabilities.channels}"
                )
            power_supply.set_current_limit(channel=args.channel, current=args.current)
            power_supply.set_voltage(channel=args.channel, voltage=args.voltage)
    except _SetModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_set",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _SetChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        code = "set_failed" if opened else "connection_failed"
        message = f"set failed: {exc}" if opened else f"Could not open resource for set: {exc}"
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=code,
            message=message,
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="set_failed",
            message=f"set failed: {exc}",
        )

    resource_data = _set_resource_payload(args, idn)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print(f"Current limit: {_format_text_value(args.current)} A")
    print(f"Voltage: {_format_text_value(args.voltage)} V")
    return 0


def _run_output_state_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    backend = getattr(args, "backend", None)
    timeout_ms = getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        with _open_resource(
            args.resource,
            manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _OutputStateModelError(
                    "output-state real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            capabilities = power_supply.capabilities
            if args.channel not in capabilities.channels:
                raise _OutputStateChannelError(
                    f"channel {args.channel} is not supported for output-state; "
                    f"supported: {capabilities.channels}"
                )
            output_enabled = power_supply.output_state(channel=args.channel)
    except _OutputStateModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_output_state",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _OutputStateChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="connection_failed",
            message=f"Could not open resource for output-state: {exc}",
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="output_state_failed",
            message=f"output-state failed: {exc}",
        )

    resource_data = _output_state_resource_payload(args, idn, output_enabled)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print(f"Output enabled: {str(output_enabled).lower()}")
    return 0


def _run_cycle_output_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    backend = getattr(args, "backend", None)
    timeout_ms = getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        with _open_resource(
            args.resource,
            manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _CycleOutputModelError(
                    "cycle-output real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            capabilities = power_supply.capabilities
            if args.channel not in capabilities.channels:
                raise _CycleOutputChannelError(
                    f"channel {args.channel} is not supported for cycle-output; "
                    f"supported: {capabilities.channels}"
                )
            power_supply.output_on(channel=args.channel)
            time.sleep(args.duration_ms / 1000)
            power_supply.output_off(channel=args.channel)
    except _CycleOutputModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_cycle_output",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _CycleOutputChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="connection_failed",
            message=f"Could not open resource for cycle-output: {exc}",
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="cycle_output_failed",
            message=f"cycle-output failed: {exc}",
        )

    resource_data = _cycle_output_resource_payload(args, idn)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print("Cycle complete: true")
    return 0


def _run_apply_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    backend = getattr(args, "backend", None)
    timeout_ms = getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        with _open_resource(
            args.resource,
            manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _ApplyModelError(
                    "apply real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            capabilities = power_supply.capabilities
            if args.channel not in capabilities.channels:
                raise _ApplyChannelError(
                    f"channel {args.channel} is not supported for apply; "
                    f"supported: {capabilities.channels}"
                )
            power_supply.set_current_limit(channel=args.channel, current=args.current)
            power_supply.set_voltage(channel=args.channel, voltage=args.voltage)
            power_supply.output_on(channel=args.channel)
    except _ApplyModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_apply",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _ApplyChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="connection_failed",
            message=f"Could not open resource for apply: {exc}",
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="apply_failed",
            message=f"apply failed: {exc}",
        )

    resource_data = _apply_resource_payload(args, idn)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print(f"Current limit: {_format_text_value(args.current)} A")
    print(f"Voltage: {_format_text_value(args.voltage)} V")
    print("Output enabled: True")
    return 0


def _run_output_on_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    opened = False
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _OutputOnModelError(
                    "output-on real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            capabilities = power_supply.capabilities
            if args.channel not in capabilities.channels:
                raise _OutputOnChannelError(
                    f"channel {args.channel} is not supported for output-on; "
                    f"supported: {capabilities.channels}"
                )
            power_supply.output_on(channel=args.channel)
    except _OutputOnModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_output_on",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _OutputOnChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        code = "output_on_failed" if opened else "connection_failed"
        message = (
            f"output-on failed: {exc}"
            if opened
            else f"Could not open resource for output-on: {exc}"
        )
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=code,
            message=message,
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="output_on_failed",
            message=f"output-on failed: {exc}",
        )

    resource_data = _output_on_resource_payload(args, idn)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print(f"Output enabled: True")
    return 0


def _run_output_off_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _OutputOffModelError(
                    "output-off real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            capabilities = power_supply.capabilities
            if args.channel not in capabilities.channels:
                raise _OutputOffChannelError(
                    f"channel {args.channel} is not supported for output-off; "
                    f"supported: {capabilities.channels}"
                )
            power_supply.output_off(channel=args.channel)
    except _OutputOffModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_output_off",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _OutputOffChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="connection_failed",
            message=f"Could not open resource for output-off: {exc}",
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="output_off_failed",
            message=f"output-off failed: {exc}",
        )

    resource_data = _output_off_resource_payload(args, idn)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print(f"Output enabled: False")
    return 0


def _run_safe_off_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    backend = getattr(args, "backend", None)
    timeout_ms = getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS)
    log_scpi = getattr(args, "log_scpi", False)

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        with _open_resource(
            args.resource,
            manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _SafeOffModelError(
                    "safe-off real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            if args.channel == "all":
                outputs = []
                for channel in (1, 2, 3):
                    power_supply.output_off(channel=channel)
                    outputs.append({"channel": channel, "enabled": False})
            else:
                if args.channel not in power_supply.capabilities.channels:
                    raise _SafeOffChannelError(
                        f"channel {args.channel} is not supported for safe-off; "
                        f"supported: {power_supply.capabilities.channels}"
                    )
                power_supply.output_off(channel=args.channel)
                outputs = [{"channel": args.channel, "enabled": False}]
    except _SafeOffModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_safe_off",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _SafeOffChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="connection_failed",
            message=f"Could not open resource for safe-off: {exc}",
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="safe_off_failed",
            message=f"safe-off failed: {exc}",
        )

    resource_data = _safe_off_resource_payload(args, idn, outputs)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    for output in outputs:
        print(f"Channel {output['channel']}: Output enabled: False")
    return 0


def _set_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "setpoints": {
            "current": _json_safe_number(args.current),
            "voltage": _json_safe_number(args.voltage),
        },
    }


def _output_off_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "output": {
            "enabled": False,
        },
    }


def _safe_off_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "outputs": outputs,
    }


def _output_state_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "output": {
            "enabled": enabled,
        },
    }


def _cycle_output_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "duration_ms": args.duration_ms,
        "output": {
            "cycled": True,
            "final_enabled": False,
        },
    }


def _apply_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "setpoints": {
            "current": _json_safe_number(args.current),
            "voltage": _json_safe_number(args.voltage),
        },
        "output": {
            "enabled": True,
        },
    }


def _output_on_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "output": {
            "enabled": True,
        },
    }


def _list_resources(
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
) -> tuple[str, ...]:
    if resource_manager is None:
        return list_resources(backend=backend)
    return list_resources(resource_manager, backend=backend)


def _open_resource(
    resource: str,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
):
    if resource_manager is None:
        return open_resource(resource, backend=backend, timeout_ms=timeout_ms)
    return open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    )


def _mode_for_args(args: argparse.Namespace) -> str:
    if args.simulate:
        return "simulate"
    return "real"


def _execution_for_args(
    args: argparse.Namespace,
    *,
    hardware_intent: bool,
) -> dict[str, Any]:
    dry_run = bool(getattr(args, "dry_run", False))
    mode = _mode_for_args(args)
    return {
        "mode": mode,
        "dry_run": dry_run,
        "hardware_touched": bool(hardware_intent and mode == "real" and not dry_run),
    }


def _validation_execution_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    return {
        "mode": "simulate" if "--simulate" in argv else "real",
        "dry_run": "--dry-run" in argv,
        "hardware_touched": False,
    }


def _request_for_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "list-resources":
        return {
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "live_only": getattr(args, "live_only", False),
        }
    if args.command == "verify":
        return {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "clear":
        return {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "error":
        return {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "max_reads": args.max_reads,
        }
    if args.command == "measure":
        return {
            "resource": args.resource,
            "channel": args.channel,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "measure-all":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "set":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "voltage": _json_safe_number(args.voltage),
            "current": _json_safe_number(args.current),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "output-off":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "output-on":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "safe-off":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "safety_config": getattr(args, "safety_config", None),
        }
    if args.command == "output-state":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "cycle-output":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "duration_ms": args.duration_ms,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "apply":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "voltage": _json_safe_number(args.voltage),
            "current": _json_safe_number(args.current),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "trigger-pulse":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "pin": args.pin,
            "polarity": args.polarity,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "status":
        channel = "all" if getattr(args, "all", False) else args.channel
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "max_errors": args.max_errors,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    return {}


def _request_from_argv(command: str, argv: Sequence[str]) -> dict[str, Any]:
    if command == "list-resources":
        return {
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "live_only": "--live-only" in argv,
        }
    if command == "verify":
        return {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "clear":
        return {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "error":
        return {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "max_reads": _max_reads_from_argv(argv),
        }
    if command == "measure":
        return {
            "resource": _option_value(argv, "--resource"),
            "channel": _channel_from_argv(argv),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "measure-all":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "set":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "voltage": _number_from_argv(argv, "--voltage"),
            "current": _number_from_argv(argv, "--current"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "output-off":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "output-on":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "safe-off":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
        }
    if command == "output-state":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "cycle-output":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "duration_ms": _duration_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "apply":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "voltage": _number_from_argv(argv, "--voltage"),
            "current": _number_from_argv(argv, "--current"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "trigger-pulse":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "pin": _pin_from_argv(argv),
            "polarity": _option_value(argv, "--polarity") or "positive",
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "status":
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "max_errors": _max_errors_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    return {}


def _timeout_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--timeout-ms")
    if value is None:
        return DEFAULT_TIMEOUT_MS
    try:
        return int(value)
    except ValueError:
        return value


def _max_reads_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--max-reads")
    if value is None:
        return 20
    try:
        return int(value)
    except ValueError:
        return value


def _duration_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--duration-ms")
    if value is None:
        return 500
    try:
        return int(value)
    except ValueError:
        return value


def _max_errors_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--max-errors")
    if value is None:
        return 20
    try:
        return int(value)
    except ValueError:
        return value


def _option_value(argv: Sequence[str], option: str) -> str | None:
    prefix = f"{option}="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :]
        if item == option:
            value_index = index + 1
            if value_index >= len(argv) or argv[value_index].startswith("--"):
                return None
            return argv[value_index]
    return None


def _number_from_argv(argv: Sequence[str], option: str) -> float | str | None:
    value = _option_value(argv, option)
    if value is None:
        return None
    try:
        return _json_safe_number(float(value))
    except ValueError:
        return value


def _channel_from_argv(argv: Sequence[str]) -> int | str | None:
    value = _option_value(argv, "--channel")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _status_channel_from_argv(argv: Sequence[str]) -> int | str | None:
    value = _option_value(argv, "--channel")
    if value is None:
        return None
    if value.lower() == "all":
        return "all"
    try:
        return int(value)
    except ValueError:
        return value


def _pin_from_argv(argv: Sequence[str]) -> int | str | None:
    value = _option_value(argv, "--pin")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _command_from_argv(argv: Sequence[str]) -> str:
    for item in argv:
        if item in COMMAND_NAMES:
            return item
    return "unknown"


def _exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    return 1


def _log_scpi(resource: str, direction: str, message: str) -> None:
    print(f"{resource} SCPI {direction} {message}", file=sys.stderr)


def _positive_channel(value: str) -> int:
    try:
        channel = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("channel must be a positive integer") from exc
    if channel < 1:
        raise argparse.ArgumentTypeError("channel must be a positive integer")
    return channel


def _positive_max_reads(value: str) -> int:
    try:
        max_reads = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-reads must be a positive integer") from exc
    if max_reads < 1:
        raise argparse.ArgumentTypeError("max-reads must be a positive integer")
    return max_reads


def _positive_max_errors(value: str) -> int:
    try:
        max_errors = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-errors must be a positive integer") from exc
    if max_errors < 1:
        raise argparse.ArgumentTypeError("max-errors must be a positive integer")
    return max_errors


def _positive_duration_ms(value: str) -> int:
    try:
        duration_ms = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration-ms must be a positive integer") from exc
    if duration_ms < 1:
        raise argparse.ArgumentTypeError("duration-ms must be a positive integer")
    return duration_ms


def _safe_off_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _status_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _trigger_pin(value: str) -> int:
    pin = _positive_channel(value)
    if pin not in (1, 2, 3):
        raise argparse.ArgumentTypeError("pin must be 1, 2, or 3")
    return pin


def _safety_limits_for_args(args: argparse.Namespace) -> SafetyLimits | None:
    safety_config = getattr(args, "safety_config", None)
    resource_alias = getattr(args, "resource_alias", None)
    if resource_alias is not None and safety_config is None:
        raise SafetyConfigError("resource alias requires --safety-config")
    if safety_config is None:
        return None
    resolution = resolve_safety_config(
        safety_config,
        resource=getattr(args, "resource", None),
        resource_alias=resource_alias,
    )
    args.resource = resolution.resource
    return resolution.limits


def _validate_output_request(
    args: argparse.Namespace,
    safety_limits: SafetyLimits | None,
) -> None:
    if args.command in {"set", "apply"}:
        validate_setpoint(
            channel=args.channel,
            voltage=args.voltage,
            current=args.current,
            limits=safety_limits,
        )
        return
    if args.command in {"output-on", "output-off", "output-state", "cycle-output"}:
        validate_channel(args.channel, safety_limits)
        return
    if args.command == "safe-off" and args.channel != "all":
        validate_channel(args.channel, safety_limits)


def _emit_cli_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    error_type: str,
    code: str,
    message: str,
    retryable: bool,
    hardware_intent: bool = False,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=hardware_intent),
            request=request,
            error_type=error_type,
            code=code,
            message=message,
            retryable=retryable,
        )
    else:
        print(message, file=sys.stderr)
    return 2


def _emit_safe_io_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    code: str,
    message: str,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="connection",
            code=code,
            message=message,
            retryable=True,
        )
    else:
        print(message, file=sys.stderr)
    return 1


def _output_plan_for_args(args: argparse.Namespace) -> dict[str, Any]:
    channel = args.channel
    plan: dict[str, Any] = {
        "operation": {"name": args.command},
        "target": {
            "resource": args.resource,
            "channel": channel,
        },
        "steps": [],
        "description": _output_plan_description(args.command),
        "hardware_touched": False,
    }

    if args.command == "set":
        plan["steps"] = [
            _driver_step(
                1,
                "set_current_limit",
                channel=channel,
                current=_json_safe_number(args.current),
            ),
            _driver_step(
                2,
                "set_voltage",
                channel=channel,
                voltage=_json_safe_number(args.voltage),
            ),
        ]
    elif args.command == "output-on":
        plan["steps"] = [_driver_step(1, "output_on", channel=channel)]
    elif args.command == "output-off":
        plan["steps"] = [_driver_step(1, "output_off", channel=channel)]
    elif args.command == "safe-off":
        plan["steps"] = [_driver_step(1, "safe_off", channel=channel)]
    elif args.command == "output-state":
        plan["steps"] = [_driver_step(1, "output_state", channel=channel)]
    elif args.command == "cycle-output":
        plan["steps"] = [
            _driver_step(1, "output_on", channel=channel),
            _driver_step(2, "sleep", duration_ms=args.duration_ms),
            _driver_step(3, "output_off", channel=channel),
        ]
    elif args.command == "apply":
        plan["steps"] = [
            _driver_step(
                1,
                "set_current_limit",
                channel=channel,
                current=_json_safe_number(args.current),
            ),
            _driver_step(
                2,
                "set_voltage",
                channel=channel,
                voltage=_json_safe_number(args.voltage),
            ),
            _driver_step(3, "output_on", channel=channel),
        ]
    else:  # pragma: no cover - parser dispatch keeps this unreachable
        raise ValueError(f"Unsupported output command {args.command!r}")

    return plan


def _driver_step(index: int, action: str, **parameters: Any) -> dict[str, Any]:
    return {
        "index": index,
        "type": "driver_action",
        "action": action,
        "parameters": parameters,
    }


def _output_plan_description(command: str) -> str:
    descriptions = {
        "set": "Preview setting current limit before voltage.",
        "output-on": "Preview enabling the selected output channel.",
        "output-off": "Preview disabling the selected output channel.",
        "safe-off": "Preview a conservative output-off action without channel expansion.",
        "output-state": "Preview reading the selected output channel state.",
        "cycle-output": "Preview briefly enabling then disabling the selected output channel.",
        "apply": "Preview setting current, voltage, then enabling output.",
    }
    return descriptions[command]


def _print_output_plan(plan: dict[str, Any], *, mode: str, dry_run: bool) -> None:
    label = "Dry-run" if dry_run else "Simulation"
    print(f"{label} plan for {plan['operation']['name']}")
    print(f"Mode: {mode}")
    print(f"Resource: {plan['target']['resource']}")
    print(f"Channel: {plan['target']['channel']}")
    print(f"Hardware touched: {str(plan['hardware_touched']).lower()}")
    print("Steps:")
    for step in plan["steps"]:
        parameters = " ".join(
            f"{name}={_format_text_value(value)}"
            for name, value in step["parameters"].items()
        )
        print(f"{step['index']}. {step['action']} {parameters}".rstrip())


def _print_scpi_plan(plan: dict[str, object], *, mode: str, dry_run: bool) -> None:
    label = "Dry-run" if dry_run else "Simulation"
    print(f"{label} plan for {plan['operation']['name']}")
    print(f"Mode: {mode}")
    print(f"Resource: {plan['target']['resource']}")
    print(f"Hardware touched: {str(plan['hardware_touched']).lower()}")
    print("Steps:")
    for step in plan["steps"]:
        print(f"{step['index']}. {step['command']}")


def _json_safe_number(value: float) -> float | str:
    numeric = float(value)
    if math.isfinite(numeric):
        return numeric
    return str(value)


def _format_text_value(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def _parse_measurement(response: str, measurement: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise ValueError(f"Could not parse {measurement} measurement: {response!r}") from exc


def _is_no_error_response(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")


def _unsupported_measure_channel_message(
    *,
    channel: int,
    mode: str,
    driver_name: str,
    allowed_channels: tuple[int, ...],
) -> str:
    return (
        f"measure channel {channel} is not enabled in {mode} mode for "
        f"{driver_name}; supported: {_format_channel_set(allowed_channels)}"
    )


def _format_channel_set(channels: tuple[int, ...]) -> str:
    if channels == (1,):
        return "channel 1 only"
    return "channels " + ", ".join(str(channel) for channel in channels)


if __name__ == "__main__":
    raise SystemExit(main())
