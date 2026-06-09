"""Safe command line interface for Keysight power supplies."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from typing import Any

from keysight_power.cli_io import emit_json_error, emit_json_success
from keysight_power.connection import DEFAULT_TIMEOUT_MS, list_resources, open_resource
from keysight_power.drivers.generic_scpi import GenericScpiPowerSupply
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
        "set",
        "output-on",
        "output-off",
        "safe-off",
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
    output_on_parser.set_defaults(func=_run_output_plan)

    output_off_parser = subparsers.add_parser(
        "output-off",
        help="Preview disabling one output channel.",
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


def _run_output_plan(args: argparse.Namespace) -> int:
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
            execution=_execution_for_args(args, hardware_intent=True),
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
            "backend": args.backend,
            "timeout_ms": args.timeout_ms,
            "live_only": args.live_only,
        }
    if args.command == "verify":
        return {
            "resource": args.resource,
            "backend": args.backend,
            "timeout_ms": args.timeout_ms,
        }
    if args.command == "clear":
        return {
            "resource": args.resource,
            "backend": args.backend,
            "timeout_ms": args.timeout_ms,
        }
    if args.command == "error":
        return {
            "resource": args.resource,
            "backend": args.backend,
            "timeout_ms": args.timeout_ms,
            "max_reads": args.max_reads,
        }
    if args.command == "measure":
        return {
            "resource": args.resource,
            "channel": args.channel,
            "backend": args.backend,
            "timeout_ms": args.timeout_ms,
        }
    if args.command == "set":
        return {
            "resource": args.resource,
            "resource_alias": args.resource_alias,
            "channel": args.channel,
            "voltage": _json_safe_number(args.voltage),
            "current": _json_safe_number(args.current),
            "safety_config": args.safety_config,
        }
    if args.command in {"output-on", "output-off", "safe-off"}:
        return {
            "resource": args.resource,
            "resource_alias": args.resource_alias,
            "channel": args.channel,
            "safety_config": args.safety_config,
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
    if command == "set":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "voltage": _number_from_argv(argv, "--voltage"),
            "current": _number_from_argv(argv, "--current"),
            "safety_config": _option_value(argv, "--safety-config"),
        }
    if command in {"output-on", "output-off", "safe-off"}:
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
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


def _safe_off_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


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
    if args.command == "set":
        validate_setpoint(
            channel=args.channel,
            voltage=args.voltage,
            current=args.current,
            limits=safety_limits,
        )
        return
    if args.command in {"output-on", "output-off"}:
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
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
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
