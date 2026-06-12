"""Trigger-family parser registration and runner adapters."""

from __future__ import annotations

import argparse
from typing import Any


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


def register_commands(subparsers: argparse._SubParsersAction[Any], runtime: Any) -> None:
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
    runtime._add_safety_config_argument(trigger_pulse_parser)
    runtime._add_backend_argument(trigger_pulse_parser)
    runtime._add_timeout_argument(trigger_pulse_parser)
    trigger_pulse_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    trigger_pulse_parser.set_defaults(func=run_trigger, _runtime=runtime)

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
    runtime._add_safety_config_argument(trigger_status_parser)
    runtime._add_backend_argument(trigger_status_parser)
    runtime._add_timeout_argument(trigger_status_parser)
    trigger_status_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    trigger_status_parser.set_defaults(func=run_trigger, _runtime=runtime)

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
    runtime._add_safety_config_argument(trigger_step_parser)
    runtime._add_backend_argument(trigger_step_parser)
    runtime._add_timeout_argument(trigger_step_parser)
    trigger_step_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_step_parser.set_defaults(func=run_trigger, _runtime=runtime)

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
    runtime._add_safety_config_argument(trigger_list_parser)
    runtime._add_backend_argument(trigger_list_parser)
    runtime._add_timeout_argument(trigger_list_parser)
    trigger_list_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_list_parser.set_defaults(func=run_trigger, _runtime=runtime)

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
    runtime._add_safety_config_argument(trigger_fire_parser)
    runtime._add_backend_argument(trigger_fire_parser)
    runtime._add_timeout_argument(trigger_fire_parser)
    trigger_fire_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_fire_parser.set_defaults(func=run_trigger, _runtime=runtime)

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
    runtime._add_safety_config_argument(trigger_abort_parser)
    runtime._add_backend_argument(trigger_abort_parser)
    runtime._add_timeout_argument(trigger_abort_parser)
    trigger_abort_parser.add_argument("--log-scpi", action="store_true", help="Print SCPI commands and responses to stderr.")
    trigger_abort_parser.set_defaults(func=run_trigger, _runtime=runtime)


def run_trigger(args: argparse.Namespace) -> int:
    return args._runtime._run_core_trigger(args)
