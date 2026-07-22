"""Trigger-family parser registration and runner adapters."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from functools import partial
from typing import Any, Callable

from powers_tool_cli import cli_parser as parser_helpers
from powers_tool_cli.request_primitives import (
    channel_from_argv,
    completion_request_fields,
    completion_request_fields_from_argv,
    float_list_from_argv,
    int_option_from_argv,
    json_safe_number,
    max_errors_from_argv,
    number_from_argv,
    option_value,
    pin_from_argv,
    pins_from_argv,
    status_channel_from_argv,
    timeout_from_argv,
    trigger_pins_for_args,
)
from powers_tool_core.connection import DEFAULT_TIMEOUT_MS

TRIGGER_COMMANDS = frozenset(
    {
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }
)


def register_commands(
    subparsers: argparse._SubParsersAction[Any],
    *,
    run_core_trigger: Callable[[argparse.Namespace], int],
) -> None:
    runtime = parser_helpers
    handler = partial(run_trigger, run_core_trigger=run_core_trigger)
    trigger_pulse_parser = subparsers.add_parser(
        "trigger-pulse",
        help="Configure a trigger output pin and emit a BUS trigger pulse.",
    )
    runtime._add_output_resource_arguments(trigger_pulse_parser)
    trigger_pin_group = trigger_pulse_parser.add_mutually_exclusive_group(required=True)
    trigger_pin_group.add_argument(
        "--pin",
        type=runtime._trigger_pin,
        help="Rear digital trigger output pin 1, 2, or 3.",
    )
    trigger_pin_group.add_argument(
        "--pins",
        type=runtime._trigger_pins_list,
        help="Comma-separated rear digital trigger output pins: 1, 2, and/or 3.",
    )
    trigger_pulse_parser.add_argument(
        "--channel",
        type=runtime._e36312a_channel,
        default=1,
        help="E36312A output channel to arm for the BUS trigger: 1, 2, or 3.",
    )
    trigger_pulse_parser.add_argument(
        "--polarity",
        choices=("positive", "negative"),
        default="positive",
        help="Trigger output polarity.",
    )
    trigger_pulse_parser.add_argument(
        "--exclusive-pins",
        "--exclusive-pin",
        dest="exclusive_pins",
        action="store_true",
        help="Reset unselected rear digital pins to DIO before pulsing the selected pin(s).",
    )
    runtime._add_json_argument(trigger_pulse_parser)
    runtime._add_simulate_argument(trigger_pulse_parser)
    runtime._add_dry_run_argument(trigger_pulse_parser)
    runtime._add_model_argument(trigger_pulse_parser)
    runtime._add_safety_config_argument(trigger_pulse_parser)
    runtime._add_backend_argument(trigger_pulse_parser)
    runtime._add_timeout_argument(trigger_pulse_parser)
    trigger_pulse_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    trigger_pulse_parser.set_defaults(func=handler)

    trigger_status_parser = subparsers.add_parser(
        "trigger-status",
        help="Read E36312A trigger, digital pin, and LIST state.",
    )
    runtime._add_output_resource_arguments(trigger_status_parser)
    trigger_status_parser.add_argument(
        "--channel",
        default="all",
        type=runtime._status_channel,
        help="E36312A output channel or all.",
    )
    runtime._add_json_argument(trigger_status_parser)
    runtime._add_simulate_argument(trigger_status_parser)
    runtime._add_dry_run_argument(trigger_status_parser)
    runtime._add_model_argument(trigger_status_parser)
    runtime._add_safety_config_argument(trigger_status_parser)
    runtime._add_backend_argument(trigger_status_parser)
    runtime._add_timeout_argument(trigger_status_parser)
    trigger_status_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    trigger_status_parser.set_defaults(func=handler)

    trigger_step_parser = subparsers.add_parser(
        "trigger-step",
        help="Configure and fire an E36312A STEP transient trigger.",
    )
    runtime._add_output_resource_arguments(trigger_step_parser)
    trigger_step_parser.add_argument("--channel", required=True, type=runtime._e36312a_channel)
    trigger_step_parser.add_argument("--voltage", type=float, help="Triggered voltage; defaults to current readback.")
    trigger_step_parser.add_argument("--current", type=float, help="Triggered current; defaults to current readback.")
    trigger_step_parser.add_argument(
        "--source",
        choices=("bus", "immediate", "pin1", "pin2", "pin3", "ext"),
        default="bus",
        help="Trigger source. Real hardware currently enables bus and immediate.",
    )
    trigger_step_parser.add_argument("--fire", action="store_true", help="Send *TRG after arming a BUS-source trigger.")
    trigger_step_parser.add_argument("--wait-complete", action="store_true", help="Poll operation-complete status after starting.")
    runtime._add_trigger_wait_arguments(trigger_step_parser)
    runtime._add_completion_pulse_arguments(trigger_step_parser)
    runtime._add_trigger_restore_argument(trigger_step_parser)
    runtime._add_json_argument(trigger_step_parser)
    runtime._add_simulate_argument(trigger_step_parser)
    runtime._add_dry_run_argument(trigger_step_parser)
    runtime._add_model_argument(trigger_step_parser)
    runtime._add_safety_config_argument(trigger_step_parser)
    runtime._add_backend_argument(trigger_step_parser)
    runtime._add_timeout_argument(trigger_step_parser)
    trigger_step_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_step_parser.set_defaults(func=handler)

    trigger_list_parser = subparsers.add_parser(
        "trigger-list",
        help="Configure and run a native E36312A LIST transient.",
    )
    runtime._add_output_resource_arguments(trigger_list_parser)
    trigger_list_parser.add_argument("--file", help="YAML or JSON trigger-list document.")
    trigger_list_parser.add_argument("--channel", type=runtime._e36312a_channel, help="E36312A output channel.")
    trigger_list_parser.add_argument("--voltage-list", type=runtime._float_list, help="Comma-separated voltage list.")
    trigger_list_parser.add_argument("--current-list", type=runtime._float_list, help="Comma-separated current list.")
    trigger_list_parser.add_argument("--dwell-list", type=runtime._float_list, help="Comma-separated dwell values in seconds.")
    trigger_list_parser.add_argument("--bost-list", type=runtime._bool_list, help="Comma-separated per-step BOST booleans.")
    trigger_list_parser.add_argument("--eost-list", type=runtime._bool_list, help="Comma-separated per-step EOST booleans.")
    trigger_list_parser.add_argument("--trigger-output-pins", type=runtime._trigger_pins_list, help="Rear digital output pins used by BOST/EOST.")
    trigger_list_parser.add_argument("--trigger-output-polarity", choices=("positive", "negative"), help="BOST/EOST output polarity.")
    trigger_list_parser.add_argument("--count", type=runtime._positive_int, default=1, help="LIST repeat count, 1-256.")
    trigger_list_parser.add_argument(
        "--source",
        choices=("bus", "immediate", "pin1", "pin2", "pin3", "ext"),
        default="bus",
        help="Trigger source. Real hardware currently enables bus and immediate.",
    )
    trigger_list_parser.add_argument("--fire", action="store_true", help="Send *TRG after arming a BUS-source LIST.")
    trigger_list_parser.add_argument("--wait-complete", action="store_true", help="Poll operation-complete status after starting.")
    trigger_list_parser.add_argument("--exclusive-pins", action="store_true", help="Clear unselected rear digital pins back to DIO before configuring completion pins.")
    runtime._add_trigger_wait_arguments(trigger_list_parser)
    runtime._add_completion_pulse_arguments(trigger_list_parser)
    runtime._add_trigger_restore_argument(trigger_list_parser)
    runtime._add_json_argument(trigger_list_parser)
    runtime._add_simulate_argument(trigger_list_parser)
    runtime._add_dry_run_argument(trigger_list_parser)
    runtime._add_model_argument(trigger_list_parser)
    runtime._add_safety_config_argument(trigger_list_parser)
    runtime._add_backend_argument(trigger_list_parser)
    runtime._add_timeout_argument(trigger_list_parser)
    trigger_list_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_list_parser.set_defaults(func=handler)

    trigger_fire_parser = subparsers.add_parser(
        "trigger-fire",
        help="Send *TRG to an already armed BUS trigger.",
    )
    runtime._add_output_resource_arguments(trigger_fire_parser)
    trigger_fire_parser.add_argument("--channel", type=runtime._e36312a_channel, help="E36312A output channel to abort during interrupted waits.")
    trigger_fire_parser.add_argument("--wait-complete", action="store_true", help="Poll operation-complete status after *TRG.")
    runtime._add_trigger_wait_arguments(trigger_fire_parser)
    runtime._add_json_argument(trigger_fire_parser)
    runtime._add_simulate_argument(trigger_fire_parser)
    runtime._add_dry_run_argument(trigger_fire_parser)
    runtime._add_model_argument(trigger_fire_parser)
    runtime._add_safety_config_argument(trigger_fire_parser)
    runtime._add_backend_argument(trigger_fire_parser)
    runtime._add_timeout_argument(trigger_fire_parser)
    trigger_fire_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_fire_parser.set_defaults(func=handler)

    trigger_abort_parser = subparsers.add_parser(
        "trigger-abort",
        help="Abort E36312A trigger/list execution for one channel or all channels.",
    )
    runtime._add_output_resource_arguments(trigger_abort_parser)
    trigger_abort_parser.add_argument("--channel", required=True, type=runtime._e36312a_channel_or_all)
    trigger_abort_parser.add_argument("--max-errors", type=runtime._positive_max_errors, default=20)
    runtime._add_json_argument(trigger_abort_parser)
    runtime._add_simulate_argument(trigger_abort_parser)
    runtime._add_dry_run_argument(trigger_abort_parser)
    runtime._add_model_argument(trigger_abort_parser)
    runtime._add_safety_config_argument(trigger_abort_parser)
    runtime._add_backend_argument(trigger_abort_parser)
    runtime._add_timeout_argument(trigger_abort_parser)
    trigger_abort_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_abort_parser.set_defaults(func=handler)


def request_for_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "trigger-pulse":
        pins = trigger_pins_for_args(args)
        request = {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "pins": list(pins),
            "channel": getattr(args, "channel", 1),
            "polarity": args.polarity,
            "exclusive_pins": getattr(args, "exclusive_pins", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
        if args.pin is not None:
            request["pin"] = args.pin
            request["exclusive_pin"] = getattr(args, "exclusive_pins", False)
        return request
    if args.command == "trigger-status":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "trigger-step":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "source": args.source,
            "voltage": json_safe_number(args.voltage) if args.voltage is not None else None,
            "current": json_safe_number(args.current) if args.current is not None else None,
            "fire": args.fire,
            "wait_complete": args.wait_complete,
            "wait_timeout_ms": getattr(args, "wait_timeout_ms", None),
            "poll_ms": getattr(args, "poll_ms", 200),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            **completion_request_fields(args),
        }
    if args.command == "trigger-list":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "file": getattr(args, "file", None),
            "channel": getattr(args, "channel", None),
            "source": args.source,
            "voltage_list": list(args.voltage_list) if args.voltage_list is not None else None,
            "current_list": list(args.current_list) if args.current_list is not None else None,
            "dwell_list": list(args.dwell_list) if args.dwell_list is not None else None,
            "bost_list": list(args.bost_list) if getattr(args, "bost_list", None) is not None else None,
            "eost_list": list(args.eost_list) if getattr(args, "eost_list", None) is not None else None,
            "trigger_output_pins": list(args.trigger_output_pins) if getattr(args, "trigger_output_pins", None) is not None else None,
            "trigger_output_polarity": getattr(args, "trigger_output_polarity", None),
            "count": args.count,
            "fire": args.fire,
            "wait_complete": args.wait_complete,
            "wait_timeout_ms": getattr(args, "wait_timeout_ms", None),
            "poll_ms": getattr(args, "poll_ms", 200),
            "exclusive_pins": getattr(args, "exclusive_pins", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            **completion_request_fields(args),
        }
    if args.command == "trigger-fire":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "wait_complete": args.wait_complete,
            "wait_timeout_ms": getattr(args, "wait_timeout_ms", None),
            "poll_ms": getattr(args, "poll_ms", 200),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "trigger-abort":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "max_errors": args.max_errors,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    return {}


def request_from_argv(
    command: str,
    argv: Sequence[str],
) -> dict[str, Any]:
    if command == "trigger-pulse":
        pin = pin_from_argv(argv)
        pins = pins_from_argv(argv)
        request = {
            "resource": option_value(argv, "--resource"),
            "resource_alias": option_value(argv, "--resource-alias"),
            "pins": pins if pins is not None else ([pin] if pin is not None else None),
            "channel": channel_from_argv(argv) or 1,
            "polarity": option_value(argv, "--polarity") or "positive",
            "exclusive_pins": "--exclusive-pins" in argv or "--exclusive-pin" in argv,
            "safety_config": option_value(argv, "--safety-config"),
            "backend": option_value(argv, "--backend"),
            "timeout_ms": timeout_from_argv(argv),
        }
        if pin is not None:
            request["pin"] = pin
            request["exclusive_pin"] = "--exclusive-pins" in argv or "--exclusive-pin" in argv
        return request
    if command == "trigger-status":
        return {
            "resource": option_value(argv, "--resource"),
            "resource_alias": option_value(argv, "--resource-alias"),
            "channel": status_channel_from_argv(argv) or "all",
            "safety_config": option_value(argv, "--safety-config"),
            "backend": option_value(argv, "--backend"),
            "timeout_ms": timeout_from_argv(argv),
        }
    if command == "trigger-step":
        return {
            "resource": option_value(argv, "--resource"),
            "resource_alias": option_value(argv, "--resource-alias"),
            "channel": channel_from_argv(argv),
            "source": option_value(argv, "--source") or "bus",
            "voltage": number_from_argv(argv, "--voltage"),
            "current": number_from_argv(argv, "--current"),
            "fire": "--fire" in argv,
            "wait_complete": "--wait-complete" in argv,
            "wait_timeout_ms": int_option_from_argv(argv, "--wait-timeout-ms", None),
            "poll_ms": int_option_from_argv(argv, "--poll-ms", 200),
            "safety_config": option_value(argv, "--safety-config"),
            "backend": option_value(argv, "--backend"),
            "timeout_ms": timeout_from_argv(argv),
            **completion_request_fields_from_argv(argv),
        }
    if command == "trigger-list":
        return {
            "resource": option_value(argv, "--resource"),
            "resource_alias": option_value(argv, "--resource-alias"),
            "file": option_value(argv, "--file"),
            "channel": channel_from_argv(argv),
            "source": option_value(argv, "--source") or "bus",
            "voltage_list": float_list_from_argv(argv, "--voltage-list"),
            "current_list": float_list_from_argv(argv, "--current-list"),
            "dwell_list": float_list_from_argv(argv, "--dwell-list"),
            "count": int_option_from_argv(argv, "--count", 1),
            "fire": "--fire" in argv,
            "wait_complete": "--wait-complete" in argv,
            "wait_timeout_ms": int_option_from_argv(argv, "--wait-timeout-ms", None),
            "poll_ms": int_option_from_argv(argv, "--poll-ms", 200),
            "exclusive_pins": "--exclusive-pins" in argv,
            "safety_config": option_value(argv, "--safety-config"),
            "backend": option_value(argv, "--backend"),
            "timeout_ms": timeout_from_argv(argv),
            **completion_request_fields_from_argv(argv),
        }
    if command == "trigger-fire":
        return {
            "resource": option_value(argv, "--resource"),
            "resource_alias": option_value(argv, "--resource-alias"),
            "channel": channel_from_argv(argv),
            "wait_complete": "--wait-complete" in argv,
            "wait_timeout_ms": int_option_from_argv(argv, "--wait-timeout-ms", None),
            "poll_ms": int_option_from_argv(argv, "--poll-ms", 200),
            "safety_config": option_value(argv, "--safety-config"),
            "backend": option_value(argv, "--backend"),
            "timeout_ms": timeout_from_argv(argv),
        }
    if command == "trigger-abort":
        return {
            "resource": option_value(argv, "--resource"),
            "resource_alias": option_value(argv, "--resource-alias"),
            "channel": channel_from_argv(argv),
            "max_errors": max_errors_from_argv(argv),
            "safety_config": option_value(argv, "--safety-config"),
            "backend": option_value(argv, "--backend"),
            "timeout_ms": timeout_from_argv(argv),
        }
    return {}


def run_trigger(
    args: argparse.Namespace,
    *,
    run_core_trigger: Callable[[argparse.Namespace], int],
) -> int:
    return run_core_trigger(args)
