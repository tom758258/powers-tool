"""Output-family parser registration and runner adapters."""

from __future__ import annotations

import argparse
from typing import Any


OUTPUT_COMMANDS = frozenset(
    {
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "output-state",
        "cycle-output",
        "apply",
        "ramp",
        "ramp-list",
        "smoke-output",
    }
)


def register_commands(subparsers: argparse._SubParsersAction[Any], runtime: Any) -> None:
    set_parser = subparsers.add_parser(
        "set",
        help="Preview safe voltage/current setpoint changes.",
    )
    runtime._add_output_resource_arguments(set_parser)
    set_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._positive_channel,
        help="Positive integer output channel.",
    )
    set_parser.add_argument("--voltage", type=float, help="Voltage setpoint. Omit to leave voltage unchanged.")
    set_parser.add_argument("--current", type=float, help="Current limit. Omit to leave current unchanged.")
    runtime._add_write_verification_arguments(set_parser)
    runtime._add_json_argument(set_parser)
    runtime._add_simulate_argument(set_parser)
    runtime._add_dry_run_argument(set_parser)
    runtime._add_model_argument(set_parser, allow_profile=True)
    runtime._add_safety_config_argument(set_parser)
    runtime._add_backend_argument(set_parser)
    runtime._add_timeout_argument(set_parser)
    runtime._add_serial_arguments(set_parser)
    runtime._add_completion_pulse_arguments(set_parser)
    runtime._add_trigger_restore_argument(set_parser)
    set_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    set_parser.set_defaults(func=run_output, _runtime=runtime)

    output_on_parser = subparsers.add_parser(
        "output-on",
        help="Preview enabling one output channel.",
    )
    runtime._add_output_resource_arguments(output_on_parser)
    output_on_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._output_channel,
        help="Positive integer output channel or 'all'.",
    )
    runtime._add_json_argument(output_on_parser)
    runtime._add_simulate_argument(output_on_parser)
    runtime._add_dry_run_argument(output_on_parser)
    runtime._add_model_argument(output_on_parser, allow_profile=True)
    runtime._add_safety_config_argument(output_on_parser)
    runtime._add_backend_argument(output_on_parser)
    runtime._add_timeout_argument(output_on_parser)
    runtime._add_serial_arguments(output_on_parser)
    runtime._add_write_verification_arguments(output_on_parser)
    runtime._add_completion_pulse_arguments(output_on_parser)
    runtime._add_trigger_restore_argument(output_on_parser)
    output_on_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    output_on_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real output enable when configured thresholds require it.",
    )
    output_on_parser.set_defaults(func=run_output, _runtime=runtime)

    output_off_parser = subparsers.add_parser(
        "output-off",
        help="Disable or preview disabling one output channel.",
    )
    runtime._add_output_resource_arguments(output_off_parser)
    output_off_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._output_channel,
        help="Positive integer output channel or 'all'.",
    )
    runtime._add_json_argument(output_off_parser)
    runtime._add_simulate_argument(output_off_parser)
    runtime._add_dry_run_argument(output_off_parser)
    runtime._add_model_argument(output_off_parser, allow_profile=True)
    runtime._add_safety_config_argument(output_off_parser)
    runtime._add_backend_argument(output_off_parser)
    runtime._add_timeout_argument(output_off_parser)
    runtime._add_serial_arguments(output_off_parser)
    runtime._add_write_verification_arguments(output_off_parser)
    runtime._add_completion_pulse_arguments(output_off_parser)
    runtime._add_trigger_restore_argument(output_off_parser)
    output_off_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    output_off_parser.set_defaults(func=run_output, _runtime=runtime)

    safe_off_parser = subparsers.add_parser(
        "safe-off",
        help="Preview a conservative output-off action for one channel or all channels.",
    )
    runtime._add_output_resource_arguments(safe_off_parser)
    safe_off_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._safe_off_channel,
        help="Positive integer output channel or 'all'.",
    )
    runtime._add_json_argument(safe_off_parser)
    runtime._add_simulate_argument(safe_off_parser)
    runtime._add_dry_run_argument(safe_off_parser)
    runtime._add_model_argument(safe_off_parser, allow_profile=True)
    runtime._add_safety_config_argument(safe_off_parser)
    runtime._add_backend_argument(safe_off_parser)
    runtime._add_timeout_argument(safe_off_parser)
    runtime._add_serial_arguments(safe_off_parser)
    runtime._add_completion_pulse_arguments(safe_off_parser)
    runtime._add_trigger_restore_argument(safe_off_parser)
    safe_off_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    safe_off_parser.set_defaults(func=run_output, _runtime=runtime)

    output_state_parser = subparsers.add_parser(
        "output-state",
        help="Read the enabled state of one output channel.",
    )
    runtime._add_output_resource_arguments(output_state_parser)
    output_state_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._output_channel,
        help="Positive integer output channel or 'all'.",
    )
    runtime._add_json_argument(output_state_parser)
    runtime._add_simulate_argument(output_state_parser)
    runtime._add_dry_run_argument(output_state_parser)
    runtime._add_model_argument(output_state_parser, allow_profile=True)
    runtime._add_backend_argument(output_state_parser)
    runtime._add_timeout_argument(output_state_parser)
    runtime._add_serial_arguments(output_state_parser)
    output_state_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    output_state_parser.set_defaults(func=run_output, _runtime=runtime)

    cycle_output_parser = subparsers.add_parser(
        "cycle-output",
        help="Enable output briefly, then disable it again.",
    )
    runtime._add_output_resource_arguments(cycle_output_parser)
    cycle_output_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._output_channel,
        help="Positive integer output channel or 'all'.",
    )
    cycle_output_parser.add_argument(
        "--duration-ms",
        type=runtime._positive_duration_ms,
        default=500,
        help="Enable duration in milliseconds.",
    )
    runtime._add_json_argument(cycle_output_parser)
    runtime._add_simulate_argument(cycle_output_parser)
    runtime._add_dry_run_argument(cycle_output_parser)
    runtime._add_model_argument(cycle_output_parser, allow_profile=True)
    runtime._add_safety_config_argument(cycle_output_parser)
    runtime._add_backend_argument(cycle_output_parser)
    runtime._add_timeout_argument(cycle_output_parser)
    runtime._add_serial_arguments(cycle_output_parser)
    runtime._add_completion_pulse_arguments(cycle_output_parser)
    runtime._add_trigger_restore_argument(cycle_output_parser)
    cycle_output_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    cycle_output_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real output enable when configured thresholds require it.",
    )
    cycle_output_parser.set_defaults(func=run_output, _runtime=runtime)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Set low output values and enable output.",
    )
    runtime._add_output_resource_arguments(apply_parser)
    apply_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._apply_channel,
        help="Positive integer output channel or 'all'.",
    )
    apply_parser.add_argument("--voltage", required=True, type=float, help="Voltage setpoint.")
    apply_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    apply_parser.add_argument(
        "--no-output",
        action="store_true",
        help="Set voltage/current without enabling output.",
    )
    runtime._add_write_verification_arguments(apply_parser)
    runtime._add_json_argument(apply_parser)
    runtime._add_simulate_argument(apply_parser)
    runtime._add_dry_run_argument(apply_parser)
    runtime._add_model_argument(apply_parser, allow_profile=True)
    runtime._add_safety_config_argument(apply_parser)
    runtime._add_backend_argument(apply_parser)
    runtime._add_timeout_argument(apply_parser)
    runtime._add_serial_arguments(apply_parser)
    runtime._add_completion_pulse_arguments(apply_parser)
    runtime._add_trigger_restore_argument(apply_parser)
    apply_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    apply_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real output enable when configured thresholds require it.",
    )
    apply_parser.set_defaults(func=run_output, _runtime=runtime)

    ramp_parser = subparsers.add_parser(
        "ramp",
        help="Set current limit, then step voltage setpoints without changing output state.",
    )
    runtime._add_output_resource_arguments(ramp_parser)
    ramp_parser.add_argument("--channel", required=True, type=runtime._positive_channel, help="Positive integer output channel.")
    ramp_parser.add_argument("--start-voltage", required=True, type=float, help="Starting voltage setpoint.")
    ramp_parser.add_argument("--stop-voltage", required=True, type=float, help="Final voltage setpoint.")
    ramp_parser.add_argument("--step-voltage", required=True, type=runtime._positive_float, help="Positive voltage step size.")
    ramp_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    ramp_parser.add_argument("--delay-ms", type=runtime._nonnegative_int, default=0, help="Additional delay after each voltage step before starting the next step.")
    ramp_parser.add_argument(
        "--enable-output",
        action="store_true",
        help="Enable output after the first validated setpoint and verify it is on.",
    )
    ramp_parser.add_argument("--loop-count", type=runtime._positive_int, help="Total ramp iterations (1 to 255).")
    ramp_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real output enable when configured thresholds require it.",
    )
    runtime._add_json_argument(ramp_parser)
    runtime._add_simulate_argument(ramp_parser)
    runtime._add_dry_run_argument(ramp_parser)
    runtime._add_model_argument(ramp_parser, allow_profile=True)
    runtime._add_safety_config_argument(ramp_parser)
    runtime._add_backend_argument(ramp_parser)
    runtime._add_timeout_argument(ramp_parser)
    runtime._add_serial_arguments(ramp_parser)
    runtime._add_write_verification_arguments(ramp_parser)
    runtime._add_ramp_completion_pulse_arguments(ramp_parser)
    runtime._add_trigger_restore_argument(ramp_parser)
    ramp_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    ramp_parser.set_defaults(func=run_output, _runtime=runtime)

    smoke_output_parser = subparsers.add_parser(
        "smoke-output",
        help="Run a guarded E36312A single-channel output smoke sequence.",
    )
    runtime._add_output_resource_arguments(smoke_output_parser)
    smoke_output_parser.add_argument(
        "--channel",
        required=True,
        type=runtime._e36312a_channel,
        help="E36312A output channel: 1, 2, or 3.",
    )
    smoke_output_parser.add_argument("--voltage", required=True, type=float, help="Voltage setpoint.")
    smoke_output_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    runtime._add_json_argument(smoke_output_parser)
    runtime._add_simulate_argument(smoke_output_parser)
    runtime._add_dry_run_argument(smoke_output_parser)
    runtime._add_model_argument(smoke_output_parser, allow_profile=True)
    runtime._add_duration_argument(smoke_output_parser)
    runtime._add_safety_config_argument(smoke_output_parser)
    runtime._add_backend_argument(smoke_output_parser)
    runtime._add_timeout_argument(smoke_output_parser)
    runtime._add_serial_arguments(smoke_output_parser)
    runtime._add_completion_pulse_arguments(smoke_output_parser)
    runtime._add_trigger_restore_argument(smoke_output_parser)
    smoke_output_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for smoke output.",
    )
    smoke_output_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real output enable when configured thresholds require it.",
    )
    smoke_output_parser.set_defaults(func=run_output, _runtime=runtime)


def run_output(args: argparse.Namespace) -> int:
    return args._runtime._run_output_plan(args)
