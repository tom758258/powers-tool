"""Safe command line interface for Keysight power supplies."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import importlib.util
import json
import math
import platform
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from keysight_power.cli_io import (
    JsonSaveError,
    emit_json_error,
    emit_json_success,
    set_json_save_path,
)
from keysight_power.connection import DEFAULT_TIMEOUT_MS, list_resources, open_resource
from keysight_power.drivers.e36312a import E36312APowerSupply
from keysight_power.drivers.edu36311a import EDU36311APowerSupply
from keysight_power.drivers.generic_scpi import GenericScpiPowerSupply
from keysight_power.errors import VisaConnectionError
from keysight_power.factory import create_power_supply, select_driver
from keysight_power.models import parse_idn, resource_interface
from keysight_power.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    load_safety_config_document,
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
PROGRAMMED_VOLTAGE_QUERY = "VOLT?"
PROGRAMMED_CURRENT_QUERY = "CURR?"
OVP_TRIP_QUERY = "VOLT:PROT:TRIP?"
OCP_TRIP_QUERY = "CURR:PROT:TRIP?"
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
        "smoke-output",
        "trigger-pulse",
        "status",
        "readback",
        "protection-status",
        "protection-set",
        "clear-protection",
        "identify",
        "snapshot",
        "log",
        "sequence",
        "doctor",
        "capabilities",
        "safety",
    }
)

LOG_CSV_FIELDS = (
    "timestamp",
    "resource",
    "resource_alias",
    "model",
    "serial",
    "channel",
    "programmed_voltage",
    "programmed_current",
    "measured_voltage",
    "measured_current",
    "output_enabled",
    "errors",
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
    _add_backend_argument(safe_off_parser)
    _add_timeout_argument(safe_off_parser)
    safe_off_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
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
        type=_apply_channel,
        help="Positive integer output channel or 'all'.",
    )
    apply_parser.add_argument("--voltage", required=True, type=float, help="Voltage setpoint.")
    apply_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    apply_parser.add_argument(
        "--no-output",
        action="store_true",
        help="Set voltage/current without enabling output.",
    )
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

    smoke_output_parser = subparsers.add_parser(
        "smoke-output",
        help="Run a guarded E36312A single-channel output smoke sequence.",
    )
    _add_output_resource_arguments(smoke_output_parser)
    smoke_output_parser.add_argument(
        "--channel",
        required=True,
        type=_e36312a_channel,
        help="E36312A output channel: 1, 2, or 3.",
    )
    smoke_output_parser.add_argument("--voltage", required=True, type=float, help="Voltage setpoint.")
    smoke_output_parser.add_argument("--current", required=True, type=float, help="Current limit.")
    _add_json_argument(smoke_output_parser)
    _add_simulate_argument(smoke_output_parser)
    _add_dry_run_argument(smoke_output_parser)
    _add_duration_argument(smoke_output_parser)
    _add_safety_config_argument(smoke_output_parser)
    _add_backend_argument(smoke_output_parser)
    _add_timeout_argument(smoke_output_parser)
    smoke_output_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for smoke output.",
    )
    smoke_output_parser.set_defaults(func=_run_output_plan)

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
        "--channel",
        type=_e36312a_channel,
        default=1,
        help="E36312A output channel to arm for the BUS trigger: 1, 2, or 3.",
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

    readback_parser = subparsers.add_parser(
        "readback",
        help="Read programmed voltage and current setpoints for E36312A channels.",
    )
    _add_output_resource_arguments(readback_parser)
    _add_channel_or_all_argument(readback_parser)
    _add_json_argument(readback_parser)
    _add_simulate_argument(readback_parser)
    _add_safety_config_argument(readback_parser)
    _add_backend_argument(readback_parser)
    _add_timeout_argument(readback_parser)
    readback_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    readback_parser.set_defaults(func=_run_readback)

    protection_parser = subparsers.add_parser(
        "protection-status",
        help="Read E36312A protection trip flags and output states.",
    )
    _add_output_resource_arguments(protection_parser)
    _add_channel_or_all_argument(protection_parser)
    _add_json_argument(protection_parser)
    _add_simulate_argument(protection_parser)
    _add_safety_config_argument(protection_parser)
    _add_backend_argument(protection_parser)
    _add_timeout_argument(protection_parser)
    protection_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    protection_parser.set_defaults(func=_run_protection_status)

    protection_set_parser = subparsers.add_parser(
        "protection-set",
        help="Set E36312A over-voltage and over-current protection parameters.",
    )
    _add_output_resource_arguments(protection_set_parser)
    _add_channel_or_all_argument(protection_set_parser)
    protection_set_parser.add_argument(
        "--ovp-voltage",
        type=float,
        help="Over-voltage protection level.",
    )
    protection_set_parser.add_argument(
        "--ocp",
        choices=("on", "off"),
        help="Enable or disable over-current protection.",
    )
    protection_set_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real hardware protection setup.",
    )
    _add_json_argument(protection_set_parser)
    _add_simulate_argument(protection_set_parser)
    _add_dry_run_argument(protection_set_parser)
    _add_safety_config_argument(protection_set_parser)
    _add_backend_argument(protection_set_parser)
    _add_timeout_argument(protection_set_parser)
    protection_set_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    protection_set_parser.set_defaults(func=_run_protection_set)

    clear_protection_parser = subparsers.add_parser(
        "clear-protection",
        help="Clear E36312A output protection for one channel or all channels.",
    )
    _add_output_resource_arguments(clear_protection_parser)
    clear_protection_parser.add_argument(
        "--channel",
        default=None,
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    clear_protection_parser.add_argument(
        "--all",
        action="store_true",
        help="Clear protection on all E36312A output channels.",
    )
    clear_protection_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real hardware protection clearing.",
    )
    _add_json_argument(clear_protection_parser)
    _add_simulate_argument(clear_protection_parser)
    _add_dry_run_argument(clear_protection_parser)
    _add_safety_config_argument(clear_protection_parser)
    _add_backend_argument(clear_protection_parser)
    _add_timeout_argument(clear_protection_parser)
    clear_protection_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    clear_protection_parser.set_defaults(func=_run_clear_protection)

    identify_parser = subparsers.add_parser(
        "identify",
        help="Read IDN, options, SCPI version, and remote/local state.",
    )
    _add_output_resource_arguments(identify_parser)
    _add_json_argument(identify_parser)
    _add_simulate_argument(identify_parser)
    _add_safety_config_argument(identify_parser)
    _add_backend_argument(identify_parser)
    _add_timeout_argument(identify_parser)
    identify_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    identify_parser.set_defaults(func=_run_identify)

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="Read E36312A errors, outputs, readback, measurements, and protection flags.",
    )
    _add_output_resource_arguments(snapshot_parser)
    snapshot_parser.add_argument(
        "--max-errors",
        type=_positive_max_errors,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    _add_json_argument(snapshot_parser)
    _add_simulate_argument(snapshot_parser)
    _add_safety_config_argument(snapshot_parser)
    _add_backend_argument(snapshot_parser)
    _add_timeout_argument(snapshot_parser)
    snapshot_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    snapshot_parser.set_defaults(func=_run_snapshot)

    log_parser = subparsers.add_parser(
        "log",
        help="Log read-only channel telemetry to CSV.",
    )
    _add_output_resource_arguments(log_parser)
    log_channel_group = log_parser.add_mutually_exclusive_group(required=True)
    log_channel_group.add_argument(
        "--channel",
        type=_log_channel,
        help="Positive integer output channel, or 'all'.",
    )
    log_channel_group.add_argument(
        "--channels",
        type=_channels_list,
        help="Comma-separated positive output channels.",
    )
    log_parser.add_argument(
        "--interval-sec",
        required=True,
        type=_positive_float,
        help="Seconds between samples.",
    )
    log_parser.add_argument("--csv", required=True, help="CSV output path.")
    log_parser.add_argument("--jsonl", help="Optional JSONL output path.")
    log_parser.add_argument(
        "--append",
        action="store_true",
        help="Append to an existing CSV/JSONL file.",
    )
    log_parser.add_argument(
        "--samples",
        type=_positive_int,
        help="Number of samples to collect.",
    )
    log_parser.add_argument(
        "--duration-sec",
        type=_positive_float,
        help="Collection duration in seconds.",
    )
    _add_json_argument(log_parser)
    _add_simulate_argument(log_parser)
    _add_safety_config_argument(log_parser)
    _add_backend_argument(log_parser)
    _add_timeout_argument(log_parser)
    log_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    log_parser.set_defaults(func=_run_log)

    sequence_parser = subparsers.add_parser(
        "sequence",
        help="Run a conservative software sequence from a YAML or JSON file.",
    )
    _add_output_resource_arguments(sequence_parser)
    sequence_parser.add_argument("--file", required=True, help="YAML or JSON sequence file.")
    _add_json_argument(sequence_parser)
    _add_simulate_argument(sequence_parser)
    _add_dry_run_argument(sequence_parser)
    _add_safety_config_argument(sequence_parser)
    _add_backend_argument(sequence_parser)
    _add_timeout_argument(sequence_parser)
    sequence_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    sequence_parser.set_defaults(func=_run_sequence)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Report Python, package, PyVISA, simulator, and backend diagnostics.",
    )
    _add_json_argument(doctor_parser)
    _add_simulate_argument(doctor_parser)
    _add_backend_argument(doctor_parser)
    _add_timeout_argument(doctor_parser)
    doctor_parser.add_argument("--resource", help="Optional resource to identify.")
    doctor_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    doctor_parser.set_defaults(func=_run_doctor)

    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="Report selected driver capabilities for a resource.",
    )
    _add_output_resource_arguments(capabilities_parser)
    _add_json_argument(capabilities_parser)
    _add_simulate_argument(capabilities_parser)
    _add_backend_argument(capabilities_parser)
    _add_timeout_argument(capabilities_parser)
    capabilities_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    capabilities_parser.set_defaults(func=_run_capabilities)

    safety_parser = subparsers.add_parser(
        "safety",
        help="Inspect safety configuration.",
    )
    safety_subparsers = safety_parser.add_subparsers(
        dest="safety_command",
        required=True,
        parser_class=JsonCliArgumentParser,
    )
    safety_inspect_parser = safety_subparsers.add_parser(
        "inspect",
        help="Inspect effective safety limits for a resource or alias.",
    )
    _add_output_resource_arguments(safety_inspect_parser)
    safety_inspect_parser.add_argument("--channel", type=_positive_channel)
    safety_inspect_parser.add_argument("--model")
    _add_json_argument(safety_inspect_parser)
    _add_safety_config_argument(safety_inspect_parser)
    safety_inspect_parser.set_defaults(func=_run_safety_inspect)

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
    if getattr(args, "save_json", None) is not None and not args.json:
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
            request=_request_for_args(args),
            error_type="validation",
            code="argument_error",
            message="--save-json requires --json",
            retryable=False,
        )
        return 2
    set_json_save_path(getattr(args, "save_json", None))
    try:
        return int(args.func(args))
    except JsonSaveError as exc:
        set_json_save_path(None)
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
            request=_request_for_args(args),
            error_type="connection",
            code="json_save_failed",
            message=f"Could not save JSON: {exc}",
            retryable=False,
        )
        return 1
    finally:
        set_json_save_path(None)


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
    parser.add_argument(
        "--save-json",
        help="Write the same JSON envelope to a UTF-8 file. Requires --json.",
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


def _add_channel_or_all_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--channel",
        default="all",
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Read all E36312A output channels.",
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

    scpi = _trigger_pulse_scpi(args.pin, args.polarity, args.channel)
    if args.dry_run:
        plan = dry_run_plan(
            command=args.command,
            resource=args.resource,
            scpi=scpi,
            description=(
                "Preview configuring an E36312A rear digital trigger output pin "
                "then arming a channel with TRIG:SOUR BUS and INIT before "
                "issuing *TRG. *TRG may also trigger any already armed "
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
            voltage = power_supply.programmed_voltage(channel=args.channel)
            current = power_supply.programmed_current(channel=args.channel)
            power_supply.configure_trigger_output_pin(args.pin, args.polarity)
            power_supply.enable_trigger_output_bus(True)
            power_supply.set_triggered_current(channel=args.channel, current=current)
            power_supply.set_triggered_voltage(channel=args.channel, voltage=voltage)
            power_supply.set_current_trigger_mode_step(args.channel)
            power_supply.set_voltage_trigger_mode_step(args.channel)
            power_supply.configure_output_trigger_source_bus(args.channel)
            power_supply.trigger_pulse(channel=args.channel)
            _raise_on_instrument_errors(power_supply, "trigger-pulse")
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
        "channel": args.channel,
        "polarity": args.polarity,
        "triggered": True,
        "trigger_setpoints": {
            "current": _json_safe_number(current),
            "voltage": _json_safe_number(voltage),
        },
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
            channels = power_supply.capabilities.channels if selected_channel == "all" else (selected_channel,)
            for channel in channels:
                _validate_read_only_channel(power_supply, channel, command_label="status")
            errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
            outputs = [
                {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
                for channel in channels
            ]
    except _ReadOnlyModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_status",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _ReadOnlyChannelError as exc:
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


def _run_readback(args: argparse.Namespace) -> int:
    result = _run_read_only_command(
        args,
        command_label="readback",
        unsupported_code="unsupported_model_for_readback",
        failure_code="readback_failed",
        operation=_collect_readback,
    )
    if result is None:
        return 1
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0
    print(f"Resource: {data['resource']}")
    for channel in data["channels"]:
        setpoints = channel["setpoints"]
        print(
            f"Channel {channel['channel']}: "
            f"{_format_text_value(setpoints['voltage'])} V, "
            f"{_format_text_value(setpoints['current'])} A"
        )
    return 0


def _run_read_only_command(
    args: argparse.Namespace,
    *,
    command_label: str,
    unsupported_code: str,
    failure_code: str,
    operation: Any,
) -> tuple[int, dict[str, Any]]:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )

    selected_channel = "all" if getattr(args, "all", False) else getattr(args, "channel", "all")
    try:
        _read_only_channels_from_selection(selected_channel, (1, 2, 3))
    except _ReadOnlyChannelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )
    opened = False
    try:
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, (E36312APowerSupply, EDU36311APowerSupply)):
                raise _ReadOnlyModelError(
                    f"{command_label} is only supported for E36312A or EDU36311A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = _read_only_channels_from_selection(
                selected_channel,
                power_supply.capabilities.channels,
            )
            return 0, operation(args, power_supply, idn, channels)
    except _ReadOnlyModelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=unsupported_code,
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except _ReadOnlyChannelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except VisaConnectionError as exc:
        code = failure_code if opened else "connection_failed"
        message = (
            f"{command_label} failed: {exc}"
            if opened
            else f"Could not open resource for {command_label}: {exc}"
        )
        return (
            _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message),
            {},
        )
    except ValueError as exc:
        return (
            _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code=failure_code,
                message=f"{command_label} failed: {exc}",
            ),
            {},
        )


def _run_protection_status(args: argparse.Namespace) -> int:
    result = _run_e36312a_read_command(
        args,
        command_label="protection-status",
        unsupported_code="unsupported_model_for_protection_status",
        failure_code="protection_status_failed",
        operation=_collect_protection_status,
    )
    if result is None:
        return 1
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0
    protection = data["protection"]
    print(f"Resource: {data['resource']}")
    print(f"Over-voltage tripped: {str(protection['over_voltage_tripped']).lower()}")
    print(f"Over-current tripped: {str(protection['over_current_tripped']).lower()}")
    for output in data["outputs"]:
        print(
            f"Channel {output['channel']}: "
            f"Output enabled: {str(output['enabled']).lower()}, "
            f"disabled with protection: {str(output['disabled_with_protection']).lower()}"
        )
    return 0


def _run_clear_protection(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    if not args.all and args.channel is None:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="clear-protection requires --channel N or --all",
            retryable=False,
        )
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
    try:
        channels = _channels_from_selection(selected_channel, E36312APowerSupply.capabilities.channels)
    except _E36312AChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )
    if args.dry_run:
        plan = dry_run_plan(
            command=args.command,
            resource=args.resource,
            scpi=_clear_protection_scpi(channels),
            description="Preview clearing E36312A output protection for selected channels.",
        )
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    if not args.simulate and not args.confirm:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="confirmation_required",
            message="clear-protection real execution requires --confirm",
            retryable=False,
            hardware_intent=True,
        )

    opened = False
    try:
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _ClearProtectionModelError(
                    "clear-protection is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = _channels_from_selection(selected_channel, power_supply.capabilities.channels)
            for channel in channels:
                power_supply.clear_output_protection(channel=channel)
            _raise_on_instrument_errors(power_supply, "clear-protection")
    except _ClearProtectionModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_clear_protection",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _E36312AChannelError as exc:
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
        code = "clear_protection_failed" if opened else "connection_failed"
        message = (
            f"clear-protection failed: {exc}"
            if opened
            else f"Could not open resource for clear-protection: {exc}"
        )
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message)
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="clear_protection_failed",
            message=f"clear-protection failed: {exc}",
        )

    data = {"resource": args.resource, "cleared_channels": list(channels)}
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    print(f"Resource: {args.resource}")
    print("Cleared channels: " + ", ".join(str(channel) for channel in channels))
    return 0


def _run_protection_set(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    if args.ovp_voltage is None and args.ocp is None:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="protection-set requires --ovp-voltage or --ocp",
            retryable=False,
        )
    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        channels = _channels_from_selection(args.channel, E36312APowerSupply.capabilities.channels)
        for channel in channels:
            validate_channel(channel, safety_limits)
            if args.ovp_voltage is not None:
                validate_setpoint(channel=channel, voltage=args.ovp_voltage, limits=safety_limits)
    except (SafetyConfigError, SafetyValidationError, _E36312AChannelError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    if args.dry_run:
        plan = dry_run_plan(
            command=args.command,
            resource=args.resource,
            scpi=_protection_set_scpi(channels, args.ovp_voltage, args.ocp),
            description="Preview setting E36312A output protection for selected channels.",
        )
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    if not args.simulate and not args.confirm:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="confirmation_required",
            message="protection-set real execution requires --confirm",
            retryable=False,
            hardware_intent=True,
        )

    opened = False
    try:
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _ProtectionSetModelError(
                    "protection-set is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = _channels_from_selection(args.channel, power_supply.capabilities.channels)
            for channel in channels:
                if args.ovp_voltage is not None:
                    power_supply.set_over_voltage_protection(
                        channel=channel,
                        voltage=args.ovp_voltage,
                    )
                if args.ocp is not None:
                    power_supply.set_over_current_protection_enabled(
                        channel=channel,
                        enabled=args.ocp == "on",
                    )
            _raise_on_instrument_errors(power_supply, "protection-set")
    except _ProtectionSetModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_protection_set",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _E36312AChannelError as exc:
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
        code = "protection_set_failed" if opened else "connection_failed"
        message = (
            f"protection-set failed: {exc}"
            if opened
            else f"Could not open resource for protection-set: {exc}"
        )
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message)
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="protection_set_failed",
            message=f"protection-set failed: {exc}",
        )

    data = {
        "resource": args.resource,
        "channels": [
            {
                "channel": channel,
                "protection": {
                    "ovp_voltage": (
                        _json_safe_number(args.ovp_voltage)
                        if args.ovp_voltage is not None
                        else None
                    ),
                    "ocp_enabled": (args.ocp == "on" if args.ocp is not None else None),
                },
            }
            for channel in channels
        ],
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    print(f"Resource: {args.resource}")
    for channel in data["channels"]:
        protection = channel["protection"]
        print(
            f"Channel {channel['channel']}: "
            f"OVP={_format_text_value(protection['ovp_voltage'])}, "
            f"OCP={_format_text_value(protection['ocp_enabled'])}"
        )
    return 0


def _run_identify(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)

    opened = False
    try:
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            options = session.query("*OPT?").strip()
            scpi_version = session.query("SYST:VERS?").strip()
            remote_lockout = session.query("SYST:COMM:RLST?").strip()
    except VisaConnectionError as exc:
        code = "identify_failed" if opened else "connection_failed"
        message = f"identify failed: {exc}" if opened else f"Could not open resource for identify: {exc}"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message)
    except ValueError as exc:
        return _emit_safe_io_error(args, request=request, execution=execution, code="identify_failed", message=f"identify failed: {exc}")

    data = {
        "resource": args.resource,
        "idn": parse_idn(idn).to_dict(),
        "options": options,
        "scpi_version": scpi_version,
        "remote_lockout_state": remote_lockout,
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    print(f"Resource: {args.resource}")
    print(f"IDN: {idn}")
    print(f"Options: {options}")
    print(f"SCPI version: {scpi_version}")
    print(f"Remote/local state: {remote_lockout}")
    return 0


def _run_snapshot(args: argparse.Namespace) -> int:
    result = _run_e36312a_read_command(
        args,
        command_label="snapshot",
        unsupported_code="unsupported_model_for_snapshot",
        failure_code="snapshot_failed",
        operation=_collect_snapshot,
    )
    if result is None:
        return 1
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0
    print(f"Resource: {data['resource']}")
    print(f"Model: {data['idn']['model']}")
    print(f"Errors: {len(data['errors'])}")
    for output in data["outputs"]:
        print(f"Channel {output['channel']}: Output enabled: {str(output['enabled']).lower()}")
    return 0


def _run_log(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        _validate_log_request(args)
    except (SafetyConfigError, ValueError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        result = _collect_log_samples(args, manager, backend=args.backend, timeout_ms=args.timeout_ms)
    except _ReadOnlyModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_log",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _ReadOnlyChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except (OSError, VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="log_failed",
            message=f"log failed: {exc}",
        )

    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=result,
        )
        return 0

    print(f"Resource: {args.resource}")
    print(f"CSV: {args.csv}")
    print(f"Samples written: {result['samples_written']}")
    print(f"Stopped: {str(result['stopped']).lower()}")
    return 0


def _run_sequence(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        document = _load_sequence_document(args.file)
        plan = _sequence_plan(args, document)
    except (SafetyConfigError, SafetyValidationError, ValueError, OSError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    if args.dry_run:
        data = {
            "sequence_version": plan["version"],
            "resource": args.resource,
            "resource_alias": args.resource_alias,
            "plan": plan,
            "status": "planned",
            "completed_steps": 0,
            "failed_step": None,
            "stopped": False,
            "cleanup": {"safe_off_attempted": False},
        }
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data=data)
        else:
            _print_sequence_summary(data)
        return 0

    try:
        data = _execute_sequence(args, plan, manager)
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="sequence_failed",
            message=f"sequence failed: {exc}",
        )
    except (SafetyValidationError, ValueError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )

    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        _print_sequence_summary(data)
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=bool(args.resource))
    manager = _resource_manager_for_args(args)
    pyvisa_available = importlib.util.find_spec("pyvisa") is not None
    data: dict[str, Any] = {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "package": {"name": "keysight-power", "version": _package_version()},
        "pyvisa": {"available": pyvisa_available, "backend": args.backend},
        "simulator": {
            "available": True,
            "resources": list(SimulatedResourceManager().list_resources()),
        },
        "real_resource_manager": {
            "checked": not args.simulate,
            "available": None,
            "error": None,
        },
        "resource": None,
    }
    if not args.simulate:
        try:
            _list_resources(None, backend=args.backend)
            data["real_resource_manager"]["available"] = True
        except VisaConnectionError as exc:
            data["real_resource_manager"]["available"] = False
            data["real_resource_manager"]["error"] = str(exc)

    if args.resource:
        try:
            with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
                session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
                idn = session.query(IDN_QUERY)
            data["resource"] = _resource_payload(
                args.resource,
                simulated=args.simulate,
                reachable=True,
                idn_raw=idn,
            )
        except VisaConnectionError as exc:
            return _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code="doctor_resource_failed",
                message=f"doctor resource check failed: {exc}",
            )

    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print(f"Python: {data['python']['version']}")
        print(f"Package: {data['package']['version']}")
        print(f"PyVISA: {str(pyvisa_available).lower()}")
        print(f"Simulator resources: {len(data['simulator']['resources'])}")
    return 0


def _run_capabilities(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn_raw = session.query(IDN_QUERY)
        selection = select_driver(idn_raw)
    except SafetyConfigError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="capabilities_failed",
            message=f"capabilities failed: {exc}",
        )

    caps = selection.capabilities
    data = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "driver": {
            "class": selection.driver_class.__name__,
            "reason": selection.reason,
        },
        "channels": list(caps.channels),
        "measure_channels": {
            "simulate": list(caps.simulated_measure_channels),
            "real": list(caps.real_measure_channels),
        },
        "read_only_commands": ["identify", "measure", "output-state", "readback", "status", "log", "sequence"],
        "output_commands": ["set", "output-on", "output-off", "safe-off", "cycle-output", "apply", "smoke-output"],
        "e36312a_only_commands": ["measure-all", "protection-status", "protection-set", "clear-protection", "snapshot", "trigger-pulse"],
        "hardware_validation": _hardware_validation_status(selection.idn.model),
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print(f"Driver: {data['driver']['class']}")
        print(f"Channels: {', '.join(str(channel) for channel in data['channels'])}")
    return 0


def _run_safety_inspect(args: argparse.Namespace) -> int:
    args.command = "safety inspect"
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        if args.safety_config is None:
            raise SafetyConfigError("safety inspect requires --safety-config")
        resolution = resolve_safety_config(
            args.safety_config,
            resource=args.resource,
            resource_alias=args.resource_alias,
            model=args.model,
            channel=args.channel,
        )
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )
    limits = resolution.limits
    data = {
        "resource": resolution.resource,
        "resource_alias": resolution.resource_alias,
        "model": args.model,
        "channel": args.channel,
        "limits": _safety_limits_payload(limits),
        "sources": resolution.sources or {},
        "output_affecting_allowed": _output_affecting_allowed(args.channel, limits),
    }
    if args.json:
        emit_json_success(command="safety inspect", execution=execution, request=request, data=data)
    else:
        print(f"Resource: {data['resource']}")
        print(f"Limits: {data['limits']}")
        print(f"Output allowed: {str(data['output_affecting_allowed']).lower()}")
    return 0


def _load_sequence_document(path: str) -> dict[str, Any]:
    sequence_path = Path(path)
    try:
        text = sequence_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"could not read sequence file {sequence_path}: {exc}") from exc
    stripped = text.lstrip()
    if stripped.startswith("{"):
        parsed = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError:
            parsed = _parse_simple_sequence_yaml(text)
        else:
            parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("sequence file must contain a mapping")
    return parsed


def _parse_simple_sequence_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_steps = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", maxsplit=1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped == "steps:":
            in_steps = True
            data["steps"] = steps
            continue
        if not in_steps:
            if ":" not in stripped:
                raise ValueError(f"unsupported sequence YAML line: {raw_line}")
            key, value = stripped.split(":", maxsplit=1)
            data[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if stripped.startswith("- "):
            current = {}
            steps.append(current)
            item = stripped[2:].strip()
            if item:
                if ":" not in item:
                    current["action"] = item
                else:
                    key, value = item.split(":", maxsplit=1)
                    current[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if current is None or ":" not in stripped:
            raise ValueError(f"unsupported sequence YAML line: {raw_line}")
        key, value = stripped.split(":", maxsplit=1)
        current[key.strip()] = _parse_sequence_scalar(value.strip())
    return data


def _parse_sequence_scalar(value: str) -> Any:
    if value == "":
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() == "all":
        return "all"
    try:
        if any(marker in value for marker in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("'\"")


def _sequence_plan(args: argparse.Namespace, document: dict[str, Any]) -> dict[str, Any]:
    version = document.get("version", 1)
    if version not in (1, "1"):
        raise ValueError(f"unsupported sequence version: {version}")
    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("sequence requires a non-empty steps list")
    steps = []
    for index, raw_step in enumerate(raw_steps, start=1):
        step = _normalize_sequence_step(index, raw_step)
        _validate_sequence_step(args, step)
        steps.append(step)
    return {
        "version": 1,
        "operation": {"name": "sequence"},
        "target": {"resource": args.resource, "resource_alias": args.resource_alias},
        "steps": steps,
        "hardware_touched": False,
    }


def _normalize_sequence_step(index: int, raw_step: Any) -> dict[str, Any]:
    if isinstance(raw_step, str):
        return {"index": index, "action": raw_step, "parameters": {}}
    if not isinstance(raw_step, dict):
        raise ValueError(f"sequence step {index} must be a mapping")
    if "action" in raw_step or "type" in raw_step:
        action = str(raw_step.get("action", raw_step.get("type")))
        parameters = {key: value for key, value in raw_step.items() if key not in {"action", "type"}}
    elif len(raw_step) == 1:
        action, value = next(iter(raw_step.items()))
        parameters = value if isinstance(value, dict) else {}
    else:
        raise ValueError(f"sequence step {index} requires action")
    if action not in _SEQUENCE_ACTIONS:
        raise ValueError(f"unsupported sequence step {index} action: {action}")
    return {"index": index, "action": action, "parameters": parameters}


_SEQUENCE_ACTIONS = {
    "measure",
    "readback",
    "output-state",
    "log",
    "wait",
    "safe-off",
    "set",
    "output-on",
    "output-off",
    "apply",
}


_SEQUENCE_OUTPUT_ACTIONS = {"safe-off", "set", "output-on", "output-off", "apply"}


def _validate_sequence_step(args: argparse.Namespace, step: dict[str, Any]) -> None:
    action = step["action"]
    parameters = step["parameters"]
    if action in {"measure", "readback", "output-state", "safe-off", "output-on", "output-off"}:
        _sequence_channel(parameters.get("channel", 1), allow_all=(action == "safe-off"))
    if action == "wait":
        seconds = float(parameters.get("seconds", parameters.get("duration_sec", 0)))
        if seconds < 0:
            raise ValueError("wait seconds must be non-negative")
    if action in {"set", "apply"}:
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
        voltage = float(parameters["voltage"])
        current = float(parameters["current"])
        safety_limits = _safety_limits_for_args(args)
        channels = (1, 2, 3) if channel == "all" else (channel,)
        for selected_channel in channels:
            validate_setpoint(
                channel=selected_channel,
                voltage=voltage,
                current=current,
                limits=safety_limits,
            )
    elif action in {"output-on", "output-off"}:
        safety_limits = _safety_limits_for_args(args)
        validate_channel(parameters.get("channel", 1), safety_limits)


def _sequence_channel(value: Any, *, allow_all: bool = False) -> int | str:
    if allow_all and isinstance(value, str) and value.lower() == "all":
        return "all"
    try:
        channel = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("sequence channel must be a positive integer") from exc
    if channel < 1:
        raise ValueError("sequence channel must be a positive integer")
    return channel


def _execute_sequence(
    args: argparse.Namespace,
    plan: dict[str, Any],
    manager: SimulatedResourceManager | None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    completed_steps = 0
    failed_step: dict[str, Any] | None = None
    stopped = False
    safe_off_attempted = False
    idn_raw: str | None = None
    with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
        session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
        idn_raw = session.query(IDN_QUERY)
        power_supply = create_power_supply(session, idn_raw)
        for step in plan["steps"]:
            try:
                result = _execute_sequence_step(args, power_supply, step)
                results.append(result)
                completed_steps += 1
            except KeyboardInterrupt:
                stopped = True
                failed_step = {"index": step["index"], "action": step["action"], "code": "interrupted"}
                break
            except (VisaConnectionError, ValueError, SafetyValidationError) as exc:
                failed_step = {
                    "index": step["index"],
                    "action": step["action"],
                    "code": "step_failed",
                    "message": str(exc),
                }
                break
        if stopped or failed_step is not None:
            safe_off_attempted = _sequence_cleanup_safe_off(power_supply)

    status = "stopped" if stopped else ("failed" if failed_step is not None else "completed")
    return {
        "sequence_version": plan["version"],
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "resource_alias": args.resource_alias,
        "plan": plan,
        "status": status,
        "results": results,
        "completed_steps": completed_steps,
        "failed_step": failed_step,
        "stopped": stopped,
        "cleanup": {"safe_off_attempted": safe_off_attempted},
    }


def _execute_sequence_step(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    step: dict[str, Any],
) -> dict[str, Any]:
    action = step["action"]
    parameters = step["parameters"]
    if action in _SEQUENCE_OUTPUT_ACTIONS and not args.simulate and not isinstance(power_supply, E36312APowerSupply):
        raise ValueError("real output-affecting sequence steps are enabled only for E36312A")
    if action in {"measure", "readback", "output-state"}:
        _validate_read_only_channel(power_supply, _sequence_channel(parameters.get("channel", 1)), command_label="sequence")
    if action == "measure":
        channel = _sequence_channel(parameters.get("channel", 1))
        return {
            "index": step["index"],
            "action": action,
            "channel": channel,
            "measurements": {
                "voltage": power_supply.measure_voltage(channel=channel),
                "current": power_supply.measure_current(channel=channel),
            },
        }
    if action == "readback":
        channel = _sequence_channel(parameters.get("channel", 1))
        return {
            "index": step["index"],
            "action": action,
            "channel": channel,
            "setpoints": {
                "voltage": power_supply.programmed_voltage(channel=channel),
                "current": power_supply.programmed_current(channel=channel),
            },
        }
    if action == "output-state":
        channel = _sequence_channel(parameters.get("channel", 1))
        return {"index": step["index"], "action": action, "channel": channel, "enabled": power_supply.output_state(channel=channel)}
    if action == "log":
        return {"index": step["index"], "action": action, "message": str(parameters.get("message", ""))}
    if action == "wait":
        seconds = float(parameters.get("seconds", parameters.get("duration_sec", 0)))
        time.sleep(seconds)
        return {"index": step["index"], "action": action, "seconds": seconds}
    if action == "safe-off":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in _sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "output-off":
        channel = _sequence_channel(parameters.get("channel", 1))
        power_supply.output_off(channel=channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "output-on":
        channel = _sequence_channel(parameters.get("channel", 1))
        power_supply.output_on(channel=channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action in {"set", "apply"}:
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
        voltage = float(parameters["voltage"])
        current = float(parameters["current"])
        for selected_channel in _sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.set_current_limit(channel=selected_channel, current=current)
            power_supply.set_voltage(channel=selected_channel, voltage=voltage)
            if action == "apply" and not parameters.get("no_output", False):
                power_supply.output_on(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel, "voltage": voltage, "current": current}
    raise ValueError(f"unsupported sequence action: {action}")


def _sequence_channels(channel: int | str, supported_channels: tuple[int, ...]) -> tuple[int, ...]:
    if channel == "all":
        return supported_channels
    if int(channel) not in supported_channels:
        raise ValueError(f"channel {channel} is not supported; supported: {supported_channels}")
    return (int(channel),)


def _sequence_cleanup_safe_off(power_supply: GenericScpiPowerSupply) -> bool:
    attempted = False
    for channel in power_supply.capabilities.channels:
        try:
            power_supply.output_off(channel=channel)
            attempted = True
        except Exception:
            continue
    return attempted


def _print_sequence_summary(data: dict[str, Any]) -> None:
    print(f"Resource: {data['resource'] if isinstance(data['resource'], str) else data['resource'].get('name')}")
    print(f"Status: {data['status']}")
    print(f"Completed steps: {data['completed_steps']}")


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
            "smoke-output": _run_smoke_output_real,
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


def _collect_log_samples(
    args: argparse.Namespace,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
) -> dict[str, Any]:
    samples_written = 0
    idn_raw: str | None = None
    interrupted = False
    with _open_resource(
        args.resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
        idn_raw = session.query(IDN_QUERY)
        idn = parse_idn(idn_raw)
        power_supply = create_power_supply(session, idn_raw)
        channels = _log_channels_for_power_supply(args, power_supply)

        csv_path = Path(args.csv)
        if csv_path.parent != Path("."):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_file = _open_jsonl_log(args)
        mode = "a" if args.append else "w"
        write_header = (not args.append) or (not csv_path.exists()) or csv_path.stat().st_size == 0
        with csv_path.open(mode, newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=LOG_CSV_FIELDS)
            if write_header:
                writer.writeheader()
            start = time.monotonic()
            try:
                while True:
                    if not _should_collect_log_sample(args, samples_written, start):
                        break
                    try:
                        for channel in channels:
                            row = _read_log_row(args, power_supply, idn, channel=channel)
                            writer.writerow(row)
                            if jsonl_file is not None:
                                jsonl_file.write(json.dumps({"event": "sample", "sample": row}, sort_keys=True) + "\n")
                        csv_file.flush()
                        if jsonl_file is not None:
                            jsonl_file.flush()
                        samples_written += 1
                        if not _should_collect_log_sample(args, samples_written, start):
                            break
                        time.sleep(args.interval_sec)
                    except KeyboardInterrupt:
                        interrupted = True
                        break
            finally:
                if jsonl_file is not None:
                    jsonl_file.write(
                        json.dumps(
                            {
                                "event": "summary",
                                "samples_written": samples_written,
                                "channels": list(channels),
                                "stopped": interrupted,
                                "stop_reason": "interrupted" if interrupted else "completed",
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    jsonl_file.close()

    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "resource_alias": args.resource_alias,
        "csv": args.csv,
        "jsonl": args.jsonl,
        "append": args.append,
        "channel": args.channel,
        "channels": list(channels),
        "samples_requested": args.samples,
        "duration_sec": args.duration_sec,
        "interval_sec": args.interval_sec,
        "samples_written": samples_written,
        "stopped": interrupted,
        "stop_reason": "interrupted" if interrupted else "completed",
    }


def _should_collect_log_sample(args: argparse.Namespace, samples_written: int, start: float) -> bool:
    if args.samples is not None and samples_written >= args.samples:
        return False
    if args.duration_sec is not None and samples_written > 0:
        return (time.monotonic() - start) < args.duration_sec
    return True


def _log_channels_for_power_supply(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
) -> tuple[int, ...]:
    requested = args.channels if args.channels is not None else args.channel
    if requested == "all":
        channels = power_supply.capabilities.channels
    elif isinstance(requested, tuple):
        channels = requested
    else:
        channels = (requested,)
    for channel in channels:
        _validate_read_only_channel(power_supply, channel, command_label="log")
    return tuple(int(channel) for channel in channels)


def _open_jsonl_log(args: argparse.Namespace):
    if args.jsonl is None:
        return None
    path = Path(args.jsonl)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    return path.open(mode, encoding="utf-8")


def _read_log_row(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn: Any,
    *,
    channel: int,
) -> dict[str, Any]:
    errors = power_supply.check_errors(20)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resource": args.resource,
        "resource_alias": args.resource_alias or "",
        "model": idn.model or "",
        "serial": idn.serial or "",
        "channel": channel,
        "programmed_voltage": power_supply.programmed_voltage(channel=channel),
        "programmed_current": power_supply.programmed_current(channel=channel),
        "measured_voltage": power_supply.measure_voltage(channel=channel),
        "measured_current": power_supply.measure_current(channel=channel),
        "output_enabled": power_supply.output_state(channel=channel),
        "errors": "; ".join(errors),
    }


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


def _validate_log_request(args: argparse.Namespace) -> None:
    if args.samples is None and args.duration_sec is None:
        raise ValueError("log requires --samples or --duration-sec")
    if args.samples is not None and args.duration_sec is not None:
        raise ValueError("log accepts either --samples or --duration-sec, not both")


def _validate_read_only_channel(
    power_supply: GenericScpiPowerSupply,
    channel: int,
    *,
    command_label: str,
) -> None:
    if not isinstance(power_supply, (E36312APowerSupply, EDU36311APowerSupply)):
        raise _ReadOnlyModelError(
            f"{command_label} is only supported for E36312A or EDU36311A; "
            f"found {type(power_supply).__name__} from *IDN? response"
        )
    if channel not in power_supply.capabilities.channels:
        raise _ReadOnlyChannelError(
            f"channel {channel} is not supported for {command_label}; "
            f"supported: {power_supply.capabilities.channels}"
        )


def _resolve_optional_resource_alias(args: argparse.Namespace) -> None:
    if getattr(args, "resource_alias", None) is None:
        return
    _safety_limits_for_args(args)


def _trigger_pulse_scpi(pin: int, polarity: str, channel: int) -> tuple[str, ...]:
    polarity_command = "POS" if polarity == "positive" else "NEG"
    return (
        f"DIG:PIN{pin}:FUNC TOUT",
        f"DIG:PIN{pin}:POL {polarity_command}",
        "DIG:TOUT:BUS ON",
        f"CURR:TRIG <current-readback>,(@{channel})",
        f"VOLT:TRIG <voltage-readback>,(@{channel})",
        f"CURR:MODE STEP,(@{channel})",
        f"VOLT:MODE STEP,(@{channel})",
        f"TRIG:SOUR BUS,(@{channel})",
        f"INIT (@{channel})",
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


def _raise_on_instrument_errors(
    power_supply: GenericScpiPowerSupply,
    operation: str,
    *,
    max_reads: int = 20,
) -> None:
    errors, _ = _read_error_queue_from_driver(power_supply, max_reads)
    if errors:
        raise ValueError(
            f"{operation} left instrument error queue entries: "
            + "; ".join(errors)
        )


def _run_e36312a_read_command(
    args: argparse.Namespace,
    *,
    command_label: str,
    unsupported_code: str,
    failure_code: str,
    operation: Any,
) -> tuple[int, dict[str, Any]]:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )

    selected_channel = "all" if getattr(args, "all", False) else getattr(args, "channel", "all")
    try:
        _channels_from_selection(selected_channel, E36312APowerSupply.capabilities.channels)
    except _E36312AChannelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )
    opened = False
    try:
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _E36312AOnlyError(
                    f"{command_label} is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = _channels_from_selection(selected_channel, power_supply.capabilities.channels)
            return 0, operation(args, power_supply, idn, channels)
    except _E36312AOnlyError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=unsupported_code,
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except _E36312AChannelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except VisaConnectionError as exc:
        code = failure_code if opened else "connection_failed"
        message = (
            f"{command_label} failed: {exc}"
            if opened
            else f"Could not open resource for {command_label}: {exc}"
        )
        return (
            _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message),
            {},
        )
    except ValueError as exc:
        return (
            _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code=failure_code,
                message=f"{command_label} failed: {exc}",
            ),
            {},
        )


def _collect_readback(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    return {
        "resource": args.resource,
        "channels": [
            {
                "channel": channel,
                "setpoints": {
                    "voltage": power_supply.programmed_voltage(channel=channel),
                    "current": power_supply.programmed_current(channel=channel),
                },
            }
            for channel in channels
        ],
    }


def _collect_protection_status(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    protection = _protection_payload(power_supply)
    tripped = protection["over_voltage_tripped"] or protection["over_current_tripped"]
    return {
        "resource": args.resource,
        "protection": protection,
        "outputs": [
            {
                "channel": channel,
                "enabled": (enabled := power_supply.output_state(channel=channel)),
                "disabled_with_protection": (not enabled) and tripped,
            }
            for channel in channels
        ],
    }


def _collect_snapshot(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    channels = power_supply.capabilities.channels
    errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
    return {
        "resource": args.resource,
        "idn": parse_idn(idn_raw).to_dict(),
        "errors": errors,
        "read_count": read_count,
        "outputs": [
            {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
            for channel in channels
        ],
        "readback": [
            {
                "channel": channel,
                "setpoints": {
                    "voltage": power_supply.programmed_voltage(channel=channel),
                    "current": power_supply.programmed_current(channel=channel),
                },
            }
            for channel in channels
        ],
        "measurements": [
            {
                "channel": channel,
                "measurements": {
                    "voltage": power_supply.measure_voltage(channel=channel),
                    "current": power_supply.measure_current(channel=channel),
                },
            }
            for channel in channels
        ],
        "protection": _protection_payload(power_supply),
    }


def _protection_payload(power_supply: E36312APowerSupply) -> dict[str, bool]:
    return {
        "over_voltage_tripped": power_supply.over_voltage_protection_tripped(),
        "over_current_tripped": power_supply.over_current_protection_tripped(),
    }


def _validate_readback_for_output_on(
    channel: int,
    setpoints: dict[str, float],
    safety_limits: SafetyLimits,
) -> None:
    validate_setpoint(
        channel=channel,
        voltage=setpoints["voltage"],
        current=setpoints["current"],
        limits=safety_limits,
    )


def _channels_from_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    if selected_channel == "all":
        return supported_channels
    if selected_channel not in supported_channels:
        raise _E36312AChannelError(
            f"channel {selected_channel} is not supported; supported: {supported_channels}"
        )
    return (int(selected_channel),)


def _read_only_channels_from_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    if selected_channel == "all":
        return supported_channels
    if selected_channel not in supported_channels:
        raise _ReadOnlyChannelError(
            f"channel {selected_channel} is not supported; supported: {supported_channels}"
        )
    return (int(selected_channel),)


def _clear_protection_scpi(channels: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"OUTP:PROT:CLE (@{channel})" for channel in channels)


def _protection_set_scpi(
    channels: tuple[int, ...],
    ovp_voltage: float | None,
    ocp: str | None,
) -> tuple[str, ...]:
    commands: list[str] = []
    for channel in channels:
        if ovp_voltage is not None:
            commands.append(f"VOLT:PROT {_format_text_value(ovp_voltage)},(@{channel})")
        if ocp is not None:
            commands.append(f"CURR:PROT:STAT {ocp.upper()},(@{channel})")
    return tuple(commands)


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


def _package_version() -> str:
    try:
        return importlib.metadata.version("keysight-power")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _hardware_validation_status(model: str | None) -> dict[str, Any]:
    normalized = (model or "").upper()
    if normalized == "E36312A":
        return {
            "read_only": "validated",
            "output": "validated",
            "protection": "validated",
            "trigger": "validated",
        }
    if normalized == "EDU36311A":
        return {
            "read_only": "pending_real_hardware",
            "output": "not_enabled",
            "protection": "not_enabled",
            "trigger": "not_applicable",
        }
    return {
        "read_only": "generic_channel_1_only",
        "output": "not_enabled",
        "protection": "not_enabled",
        "trigger": "not_enabled",
    }


def _safety_limits_payload(limits: SafetyLimits) -> dict[str, Any]:
    return {
        "max_voltage": limits.max_voltage,
        "max_current": limits.max_current,
        "allowed_channels": (
            list(limits.allowed_channels)
            if limits.allowed_channels is not None
            else None
        ),
    }


def _output_affecting_allowed(channel: int | None, limits: SafetyLimits) -> bool:
    if channel is not None:
        try:
            validate_channel(channel, limits)
        except SafetyValidationError:
            return False
    return True


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


class _SmokeOutputModelError(ValueError):
    """Raised when smoke-output is attempted on a non-E36312A model."""


class _SmokeOutputChannelError(ValueError):
    """Raised when smoke-output channel is outside E36312A capability (1,2,3)."""


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


class _ReadOnlyModelError(ValueError):
    """Raised when read-only model-specific commands see an unsupported model."""


class _ReadOnlyChannelError(ValueError):
    """Raised when read-only model-specific commands receive an unsupported channel."""


class _E36312AOnlyError(ValueError):
    """Raised when an E36312A-only command sees a different model."""


class _E36312AChannelError(ValueError):
    """Raised when an E36312A command receives an unsupported channel."""


class _ClearProtectionModelError(ValueError):
    """Raised when clear-protection sees a non-E36312A model."""


class _ProtectionSetModelError(ValueError):
    """Raised when protection-set sees a non-E36312A model."""


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
            _raise_on_instrument_errors(power_supply, "set")
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
            _validate_read_only_channel(power_supply, args.channel, command_label="output-state")
            output_enabled = power_supply.output_state(channel=args.channel)
    except _ReadOnlyModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_output_state",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _ReadOnlyChannelError as exc:
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
            _raise_on_instrument_errors(power_supply, "cycle-output")
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
            channels = _channels_from_selection(args.channel, power_supply.capabilities.channels)
            if args.channel == "all" and not isinstance(power_supply, E36312APowerSupply):
                raise _ApplyChannelError(
                    f"channel {args.channel} is not supported for apply; "
                    f"supported: {power_supply.capabilities.channels}"
                )
            for channel in channels:
                power_supply.set_current_limit(channel=channel, current=args.current)
                power_supply.set_voltage(channel=channel, voltage=args.voltage)
            if not args.no_output:
                for channel in channels:
                    power_supply.output_on(channel=channel)
            _raise_on_instrument_errors(power_supply, "apply")
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
    except (_ApplyChannelError, _E36312AChannelError) as exc:
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

    resource_data = _apply_resource_payload(args, idn, channels)
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
    print(f"Output enabled: {str(not args.no_output)}")
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
            readback = {
                "setpoints": {
                    "voltage": power_supply.programmed_voltage(channel=args.channel),
                    "current": power_supply.programmed_current(channel=args.channel),
                },
                "safety_checked": safety_limits is not None,
            }
            if safety_limits is not None:
                _validate_readback_for_output_on(args.channel, readback["setpoints"], safety_limits)
            power_supply.output_on(channel=args.channel)
            _raise_on_instrument_errors(power_supply, "output-on")
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
    except SafetyValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="safety",
            code="unsafe_output_setpoint",
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

    resource_data = _output_on_resource_payload(args, idn, readback)
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
            _raise_on_instrument_errors(power_supply, "output-off")
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
                    outputs.append(
                        {
                            "channel": channel,
                            "enabled": power_supply.output_state(channel=channel),
                        }
                    )
            else:
                if args.channel not in power_supply.capabilities.channels:
                    raise _SafeOffChannelError(
                        f"channel {args.channel} is not supported for safe-off; "
                        f"supported: {power_supply.capabilities.channels}"
                    )
                power_supply.output_off(channel=args.channel)
                outputs = [
                    {
                        "channel": args.channel,
                        "enabled": power_supply.output_state(channel=args.channel),
                    }
                ]
            _raise_on_instrument_errors(power_supply, "safe-off")
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
        print(f"Channel {output['channel']}: Output enabled: {output['enabled']}")
    return 0


def _run_smoke_output_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    backend = getattr(args, "backend", None)
    timeout_ms = getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS)
    safe_off_attempted = False

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
        with _open_resource(args.resource, manager, backend=backend, timeout_ms=timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _SmokeOutputModelError(
                    "smoke-output real execution is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            if args.channel not in power_supply.capabilities.channels:
                raise _SmokeOutputChannelError(
                    f"channel {args.channel} is not supported for smoke-output; "
                    f"supported: {power_supply.capabilities.channels}"
                )
            output_was_enabled = False
            try:
                power_supply.set_current_limit(channel=args.channel, current=args.current)
                power_supply.set_voltage(channel=args.channel, voltage=args.voltage)
                power_supply.output_on(channel=args.channel)
                output_was_enabled = True
                time.sleep(args.duration_ms / 1000)
                measurements = {
                    "voltage": power_supply.measure_voltage(channel=args.channel),
                    "current": power_supply.measure_current(channel=args.channel),
                }
            finally:
                if output_was_enabled:
                    safe_off_attempted = True
                    power_supply.output_off(channel=args.channel)
            final_enabled = power_supply.output_state(channel=args.channel)
            _raise_on_instrument_errors(power_supply, "smoke-output")
    except _SmokeOutputModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_smoke_output",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _SmokeOutputChannelError as exc:
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
        code = "smoke_output_failed" if opened else "connection_failed"
        message = (
            f"smoke-output failed: {exc}"
            if opened
            else f"Could not open resource for smoke-output: {exc}"
        )
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message)
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="smoke_output_failed",
            message=f"smoke-output failed: {exc}",
        )

    resource_data = _smoke_output_resource_payload(
        args,
        idn,
        measurements=measurements,
        final_enabled=final_enabled,
        safe_off_attempted=safe_off_attempted,
    )
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=resource_data)
        return 0

    print(f"Resource: {args.resource}")
    print(f"Channel: {args.channel}")
    print(f"Measured voltage: {_format_text_value(measurements['voltage'])} V")
    print(f"Measured current: {_format_text_value(measurements['current'])} A")
    print(f"Final output enabled: {final_enabled}")
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


def _smoke_output_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    *,
    measurements: dict[str, float],
    final_enabled: bool,
    safe_off_attempted: bool,
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
        "setpoints": {
            "current": _json_safe_number(args.current),
            "voltage": _json_safe_number(args.voltage),
        },
        "measurements": {
            "voltage": _json_safe_number(measurements["voltage"]),
            "current": _json_safe_number(measurements["current"]),
        },
        "output": {
            "final_enabled": final_enabled,
        },
        "safe_off_attempted": safe_off_attempted,
    }


def _apply_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    payload = {
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
            "enabled": not args.no_output,
        },
    }
    if args.channel == "all":
        payload["channels"] = [
            {
                "channel": channel,
                "setpoints": {
                    "current": _json_safe_number(args.current),
                    "voltage": _json_safe_number(args.voltage),
                },
            }
            for channel in channels
        ]
    return payload


def _output_on_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    readback: dict[str, Any],
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
        "readback": readback,
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
    if getattr(args, "simulate", False):
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
    if args.command == "safety":
        return {
            "subcommand": getattr(args, "safety_command", None),
            "resource": getattr(args, "resource", None),
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "model": getattr(args, "model", None),
            "safety_config": getattr(args, "safety_config", None),
        }
    if args.command == "safety inspect":
        return {
            "resource": getattr(args, "resource", None),
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "model": getattr(args, "model", None),
            "safety_config": getattr(args, "safety_config", None),
        }
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
            "no_output": getattr(args, "no_output", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "smoke-output":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "voltage": _json_safe_number(args.voltage),
            "current": _json_safe_number(args.current),
            "duration_ms": args.duration_ms,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "trigger-pulse":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "pin": args.pin,
            "channel": getattr(args, "channel", 1),
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
    if args.command in {"readback", "protection-status"}:
        channel = "all" if getattr(args, "all", False) else args.channel
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "protection-set":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "ovp_voltage": (
                _json_safe_number(args.ovp_voltage)
                if args.ovp_voltage is not None
                else None
            ),
            "ocp": args.ocp,
            "confirm": getattr(args, "confirm", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "clear-protection":
        channel = "all" if getattr(args, "all", False) else args.channel
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "confirm": getattr(args, "confirm", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "identify":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "snapshot":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "max_errors": args.max_errors,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "log":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "channels": getattr(args, "channels", None),
            "interval_sec": args.interval_sec,
            "csv": args.csv,
            "jsonl": getattr(args, "jsonl", None),
            "append": getattr(args, "append", False),
            "samples": args.samples,
            "duration_sec": args.duration_sec,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "sequence":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "file": args.file,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "doctor":
        return {
            "resource": getattr(args, "resource", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "capabilities":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    return {}


def _request_from_argv(command: str, argv: Sequence[str]) -> dict[str, Any]:
    if command == "safety":
        return {
            "subcommand": "inspect" if "inspect" in argv else None,
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "model": _option_value(argv, "--model"),
            "safety_config": _option_value(argv, "--safety-config"),
        }
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
            "channel": _status_channel_from_argv(argv),
            "voltage": _number_from_argv(argv, "--voltage"),
            "current": _number_from_argv(argv, "--current"),
            "no_output": "--no-output" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "smoke-output":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "voltage": _number_from_argv(argv, "--voltage"),
            "current": _number_from_argv(argv, "--current"),
            "duration_ms": _duration_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "trigger-pulse":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "pin": _pin_from_argv(argv),
            "channel": _channel_from_argv(argv) or 1,
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
    if command in {"readback", "protection-status"}:
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "protection-set":
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "ovp_voltage": _number_from_argv(argv, "--ovp-voltage"),
            "ocp": _option_value(argv, "--ocp"),
            "confirm": "--confirm" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "clear-protection":
        channel = "all" if "--all" in argv else _status_channel_from_argv(argv)
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "confirm": "--confirm" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "identify":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "snapshot":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "max_errors": _max_errors_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "log":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "channels": _option_value(argv, "--channels"),
            "interval_sec": _number_from_argv(argv, "--interval-sec"),
            "csv": _option_value(argv, "--csv"),
            "jsonl": _option_value(argv, "--jsonl"),
            "append": "--append" in argv,
            "samples": _int_from_argv(argv, "--samples"),
            "duration_sec": _number_from_argv(argv, "--duration-sec"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "sequence":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "file": _option_value(argv, "--file"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "doctor":
        return {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "capabilities":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
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


def _int_from_argv(argv: Sequence[str], option: str) -> int | str | None:
    value = _option_value(argv, option)
    if value is None:
        return None
    try:
        return int(value)
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


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive number")
    return parsed


def _log_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _channels_list(value: str) -> tuple[int, ...]:
    channels: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise argparse.ArgumentTypeError("channels must be comma-separated positive integers")
        channels.append(_positive_channel(item))
    return tuple(channels)


def _safe_off_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _status_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _apply_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _e36312a_channel(value: str) -> int:
    channel = _positive_channel(value)
    if channel not in (1, 2, 3):
        raise argparse.ArgumentTypeError("channel must be 1, 2, or 3")
    return channel


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
    if args.command in {"set", "apply", "smoke-output"}:
        channels = (1, 2, 3) if args.channel == "all" else (args.channel,)
        for channel in channels:
            validate_setpoint(
                channel=channel,
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
        channels = (1, 2, 3) if channel == "all" else (channel,)
        steps = []
        index = 1
        for selected_channel in channels:
            steps.append(
                _driver_step(
                    index,
                    "set_current_limit",
                    channel=selected_channel,
                    current=_json_safe_number(args.current),
                )
            )
            index += 1
            steps.append(
                _driver_step(
                    index,
                    "set_voltage",
                    channel=selected_channel,
                    voltage=_json_safe_number(args.voltage),
                )
            )
            index += 1
        if not args.no_output:
            for selected_channel in channels:
                steps.append(_driver_step(index, "output_on", channel=selected_channel))
                index += 1
        plan["steps"] = steps
    elif args.command == "smoke-output":
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
            _driver_step(4, "sleep", duration_ms=args.duration_ms),
            _driver_step(5, "measure_voltage", channel=channel),
            _driver_step(6, "measure_current", channel=channel),
            _driver_step(7, "output_off", channel=channel),
            _driver_step(8, "output_state", channel=channel),
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
        "smoke-output": "Preview a guarded set, output, measure, and safe-off sequence.",
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
