"""Command line interface for Keysight power supply discovery."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from keysight_power.cli_io import emit_json_error, emit_json_success
from keysight_power.connection import DEFAULT_TIMEOUT_MS, list_resources, open_resource
from keysight_power.errors import VisaConnectionError
from keysight_power.testing.simulator import SimulatedResourceManager

IDN_QUERY = "*IDN?"
COMMAND_NAMES = frozenset({"list-resources", "verify"})


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


def _resource_payload(
    name: str,
    *,
    simulated: bool,
    reachable: bool | None,
    idn_raw: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "interface": _resource_interface(name),
        "simulated": simulated,
        "reachable": reachable,
        "idn": _parse_idn(idn_raw) if idn_raw is not None else None,
    }


def _resource_interface(name: str) -> str:
    normalized = name.upper()
    for interface in ("USB", "TCPIP", "GPIB", "ASRL"):
        if normalized.startswith(interface):
            return interface
    return "UNKNOWN"


def _parse_idn(raw: str) -> dict[str, Any]:
    parts = [part.strip() for part in raw.split(",")]
    values = [part or None for part in parts]

    def get(index: int) -> str | None:
        if index >= len(values):
            return None
        return values[index]

    return {
        "raw": raw,
        "manufacturer": get(0),
        "model": get(1),
        "serial": get(2),
        "firmware": get(3),
        "parse_ok": all(get(index) is not None for index in range(4)),
    }


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
    return {}


def _timeout_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--timeout-ms")
    if value is None:
        return DEFAULT_TIMEOUT_MS
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


if __name__ == "__main__":
    raise SystemExit(main())
