"""Command line interface for Keysight power supply discovery."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from keysight_power.connection import DEFAULT_TIMEOUT_MS, list_resources, open_resource
from keysight_power.errors import VisaConnectionError

IDN_QUERY = "*IDN?"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keysight_power.cli",
        description="Safe CLI tools for Keysight DC power supplies.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list-resources",
        help="List VISA resource strings reported by the selected backend.",
    )
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
    args = build_parser().parse_args(argv)
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


def _run_list_resources(args: argparse.Namespace) -> int:
    try:
        resources = list_resources(backend=args.backend)
    except VisaConnectionError as exc:
        print(f"Could not list VISA resources: {exc}", file=sys.stderr)
        return 1

    if args.live_only:
        live_resources = [
            resource
            for resource in resources
            if _query_idn(
                resource,
                backend=args.backend,
                timeout_ms=args.timeout_ms,
                log_scpi=args.log_scpi,
            )
            is not None
        ]
        if not live_resources:
            print("No live VISA resources found.")
            return 0

        for resource in live_resources:
            print(resource)
        return 0

    if not resources:
        print("No VISA resources found.")
        return 0

    for resource in resources:
        print(resource)
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    idn = _query_idn(
        args.resource,
        backend=args.backend,
        timeout_ms=args.timeout_ms,
        log_scpi=args.log_scpi,
    )
    if idn is None:
        print(f"Could not verify VISA resource: {args.resource}", file=sys.stderr)
        return 1

    print(idn)
    return 0


def _query_idn(
    resource: str,
    *,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
) -> str | None:
    try:
        with open_resource(
            resource,
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


def _log_scpi(resource: str, direction: str, message: str) -> None:
    print(f"{resource} SCPI {direction} {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
