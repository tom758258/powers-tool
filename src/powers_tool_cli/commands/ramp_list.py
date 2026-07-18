"""Ramp-list command parser registration and request shaping."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from powers_tool_core.core import OperationRequest, RuntimeOptions
from powers_tool_core.ramp_list import RAMP_LIST_KIND, RAMP_LIST_VERSION


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
        help="Repeatable segment: channel current start stop step additional-delay-ms hold-ms.",
    )
    parser.add_argument("--completion-pulse-timing", choices=("segment", "step", "loop"), help="Emit a pulse after each segment, voltage step, or completed loop set.")
    parser.add_argument("--completion-pulse-pins", type=runtime._trigger_pins_list, help="Comma-separated E36312A rear digital pulse pins.")
    parser.add_argument("--completion-pulse-polarity", choices=("positive", "negative"), default="positive", help="Completion pulse polarity.")
    parser.add_argument(
        "--enable-output",
        action="store_true",
        help="Enable each channel after its first validated segment setpoint.",
    )
    parser.add_argument("--loop-count", type=runtime._loop_count, help="Total Ramp List iterations (1 to 255).")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real output enable when configured thresholds require it.",
    )
    runtime._add_json_argument(parser)
    runtime._add_simulate_argument(parser)
    runtime._add_dry_run_argument(parser)
    runtime._add_validation_support_policy_argument(parser)
    runtime._add_model_argument(parser, allow_profile=True)
    parser.add_argument("--lint", action="store_true", help="Validate without opening VISA.")
    runtime._add_safety_config_argument(parser)
    runtime._add_backend_argument(parser)
    runtime._add_timeout_argument(parser)
    runtime._add_serial_arguments(parser)
    parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    parser.set_defaults(func=run_ramp_list, _runtime=runtime)


def request_for_args(args: argparse.Namespace, runtime: Any) -> dict[str, Any]:
    return runtime._with_serial_request_fields(args, {
        "resource": getattr(args, "resource", None),
        "resource_alias": getattr(args, "resource_alias", None),
        "file": getattr(args, "file", None),
        "segments": getattr(args, "segment", None),
        "safety_config": getattr(args, "safety_config", None),
        "backend": getattr(args, "backend", None),
        "timeout_ms": getattr(args, "timeout_ms", runtime.DEFAULT_TIMEOUT_MS),
        "lint": getattr(args, "lint", False),
        "enable_output": getattr(args, "enable_output", False),
        "loop_count": getattr(args, "loop_count", None),
    })


def request_from_argv(argv: Sequence[str], runtime: Any) -> dict[str, Any]:
    return runtime._with_serial_request_fields_from_argv(argv, {
        "resource": runtime._option_value(argv, "--resource"),
        "resource_alias": runtime._option_value(argv, "--resource-alias"),
        "file": runtime._option_value(argv, "--file"),
        "safety_config": runtime._option_value(argv, "--safety-config"),
        "backend": runtime._option_value(argv, "--backend"),
        "timeout_ms": runtime._timeout_from_argv(argv),
        "lint": "--lint" in argv,
        "enable_output": "--enable-output" in argv,
        "loop_count": runtime._option_value(argv, "--loop-count"),
    })


def core_request_for_args(args: argparse.Namespace, runtime: Any) -> OperationRequest:
    parameters: dict[str, Any] = {"file": getattr(args, "file", None), "lint": getattr(args, "lint", False)}
    pulse_requested = getattr(args, "completion_pulse_timing", None) is not None or getattr(args, "completion_pulse_pins", None) is not None
    if getattr(args, "file", None) is not None and pulse_requested:
        raise ValueError("--file Ramp List completion_pulse settings must come from the document")
    if getattr(args, "file", None) is not None and getattr(args, "enable_output", False):
        raise ValueError("--file cannot be combined with --enable-output; the document controls enable_output")
    if getattr(args, "segment", None) is not None:
        enable_output = getattr(args, "enable_output", False)
        document: dict[str, Any] = {
            "kind": RAMP_LIST_KIND,
            "version": RAMP_LIST_VERSION,
            "enable_output": enable_output,
            "loop_count": getattr(args, "loop_count", None) or 1,
            "segments": [_segment_document(values) for values in args.segment],
        }
        if pulse_requested:
            if getattr(args, "completion_pulse_pins", None) is None:
                raise ValueError("--completion-pulse-pins is required when --completion-pulse-timing is used")
            document["completion_pulse"] = {
                "timing": getattr(args, "completion_pulse_timing", None) or "segment",
                "pins": list(args.completion_pulse_pins),
                "polarity": getattr(args, "completion_pulse_polarity", "positive"),
            }
        parameters["document"] = document
        parameters.pop("file", None)
    if getattr(args, "file", None) is not None and getattr(args, "loop_count", None) is not None:
        parameters["loop_count"] = args.loop_count
    return OperationRequest(
        command="ramp-list",
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **runtime._runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", runtime.DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            confirm=getattr(args, "confirm", False),
            serial_options=runtime._serial_options_for_args(args),
            serial_remote=getattr(args, "serial_remote", False),
            serial_local_on_close=getattr(args, "serial_local_on_close", False),
            support_policy_mode=runtime._support_policy_mode_for_args(args),
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
