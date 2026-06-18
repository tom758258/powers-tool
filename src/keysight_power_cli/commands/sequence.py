"""Sequence command parser registration and request shaping."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from keysight_power_core.core import RuntimeOptions, SequenceRequest


REQUEST_FIELDS = (
    "resource",
    "resource_alias",
    "file",
    "safety_config",
    "backend",
    "timeout_ms",
)


def register_commands(subparsers: argparse._SubParsersAction[Any], runtime: Any) -> None:
    sequence_parser = subparsers.add_parser(
        "sequence",
        help="Run a conservative software sequence from a YAML or JSON file.",
    )
    runtime._add_output_resource_arguments(sequence_parser)
    sequence_parser.add_argument("--file", required=True, help="YAML or JSON sequence file.")
    runtime._add_json_argument(sequence_parser)
    runtime._add_simulate_argument(sequence_parser)
    runtime._add_dry_run_argument(sequence_parser)
    sequence_parser.add_argument("--lint", action="store_true", help="Validate the sequence file without opening VISA or executing steps.")
    runtime._add_safety_config_argument(sequence_parser)
    runtime._add_backend_argument(sequence_parser)
    runtime._add_timeout_argument(sequence_parser)
    sequence_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    sequence_parser.set_defaults(func=run_sequence, _runtime=runtime)


def request_for_args(args: argparse.Namespace, runtime: Any) -> dict[str, Any]:
    return {
        "resource": getattr(args, "resource", None),
        "resource_alias": getattr(args, "resource_alias", None),
        "file": getattr(args, "file", None),
        "safety_config": getattr(args, "safety_config", None),
        "backend": getattr(args, "backend", None),
        "timeout_ms": getattr(args, "timeout_ms", runtime.DEFAULT_TIMEOUT_MS),
    }


def request_from_argv(argv: Sequence[str], runtime: Any) -> dict[str, Any]:
    return {
        "resource": runtime._option_value(argv, "--resource"),
        "resource_alias": runtime._option_value(argv, "--resource-alias"),
        "file": runtime._option_value(argv, "--file"),
        "safety_config": runtime._option_value(argv, "--safety-config"),
        "backend": runtime._option_value(argv, "--backend"),
        "timeout_ms": runtime._timeout_from_argv(argv),
    }


def core_request_for_args(args: argparse.Namespace, runtime: Any) -> SequenceRequest:
    return SequenceRequest(
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
        parameters={
            "file": getattr(args, "file", None),
            "lint": getattr(args, "lint", False),
        },
    )


def run_sequence(args: argparse.Namespace) -> int:
    return args._runtime._run_sequence(args)
