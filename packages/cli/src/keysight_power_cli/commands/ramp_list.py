"""Ramp-list command parser registration and request shaping."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from keysight_power_core.core import OperationRequest, RuntimeOptions
from keysight_power_core.ramp_list import RAMP_LIST_KIND


def register_commands(subparsers: argparse._SubParsersAction[Any], runtime: Any) -> None:
    parser = subparsers.add_parser(
        "ramp-list",
        help="Run a versioned list of software setpoint ramp segments.",
    )
    resource_group = parser.add_mutually_exclusive_group()
    resource_group.add_argument("--resource", help="VISA resource string.")
    resource_group.add_argument("--resource-alias", help="Alias from an explicit safety config.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--file", help="Ramp-list JSON file.")
    source_group.add_argument(
        "--segment",
        action="append",
        nargs=7,
        metavar=("CHANNEL", "CURRENT", "START", "STOP", "STEP", "DELAY_MS", "HOLD_MS"),
        help="Repeatable segment: channel current start stop step delay-ms hold-ms.",
    )
    runtime._add_json_argument(parser)
    runtime._add_simulate_argument(parser)
    runtime._add_dry_run_argument(parser)
    parser.add_argument("--lint", action="store_true", help="Validate without opening VISA.")
    runtime._add_safety_config_argument(parser)
    runtime._add_backend_argument(parser)
    runtime._add_timeout_argument(parser)
    parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    parser.set_defaults(func=run_ramp_list, _runtime=runtime)


def request_for_args(args: argparse.Namespace, runtime: Any) -> dict[str, Any]:
    return {
        "resource": getattr(args, "resource", None),
        "resource_alias": getattr(args, "resource_alias", None),
        "file": getattr(args, "file", None),
        "segments": getattr(args, "segment", None),
        "safety_config": getattr(args, "safety_config", None),
        "backend": getattr(args, "backend", None),
        "timeout_ms": getattr(args, "timeout_ms", runtime.DEFAULT_TIMEOUT_MS),
        "lint": getattr(args, "lint", False),
    }


def request_from_argv(argv: Sequence[str], runtime: Any) -> dict[str, Any]:
    return {
        "resource": runtime._option_value(argv, "--resource"),
        "resource_alias": runtime._option_value(argv, "--resource-alias"),
        "file": runtime._option_value(argv, "--file"),
        "safety_config": runtime._option_value(argv, "--safety-config"),
        "backend": runtime._option_value(argv, "--backend"),
        "timeout_ms": runtime._timeout_from_argv(argv),
        "lint": "--lint" in argv,
    }


def core_request_for_args(args: argparse.Namespace, runtime: Any) -> OperationRequest:
    parameters: dict[str, Any] = {"file": getattr(args, "file", None), "lint": getattr(args, "lint", False)}
    if getattr(args, "segment", None) is not None:
        parameters["document"] = {
            "kind": RAMP_LIST_KIND,
            "version": 1,
            "segments": [_segment_document(values) for values in args.segment],
        }
        parameters.pop("file", None)
    return OperationRequest(
        command="ramp-list",
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", runtime.DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
        ),
        parameters=parameters,
    )


def _segment_document(values: Sequence[str]) -> dict[str, Any]:
    channel, current, start, stop, step, delay_ms, hold_ms = values
    try:
        return {
            "channel": int(channel),
            "current": float(current),
            "start_voltage": float(start),
            "stop_voltage": float(stop),
            "step_voltage": float(step),
            "delay_ms": int(delay_ms),
            "hold_ms": int(hold_ms),
        }
    except ValueError as exc:
        raise ValueError("--segment values must be numeric") from exc


def run_ramp_list(args: argparse.Namespace) -> int:
    return args._runtime._run_ramp_list(args)
