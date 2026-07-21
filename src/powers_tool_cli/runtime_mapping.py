"""Runtime and execution metadata mapping for CLI arguments."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from powers_tool_core.connection import SerialOptions, normalize_serial_termination
from powers_tool_core.support_policy import (
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
)


def runtime_identity_for_args(args: argparse.Namespace) -> dict[str, str | None]:
    model_id = getattr(args, "model", None)
    profile_id = getattr(args, "profile", None)
    if getattr(args, "simulate", False) or getattr(args, "dry_run", False):
        return {
            "planning_model_id": model_id,
            "expected_model_id": None,
            "planning_profile_id": profile_id,
        }
    return {
        "planning_model_id": None,
        "expected_model_id": model_id,
        "planning_profile_id": profile_id,
    }


def mode_for_args(args: argparse.Namespace) -> str:
    if getattr(args, "simulate", False):
        return "simulate"
    return "real"


def execution_for_args(
    args: argparse.Namespace,
    *,
    hardware_intent: bool,
) -> dict[str, Any]:
    existing = getattr(args, "_execution_state", None)
    if isinstance(existing, dict):
        mode = mode_for_args(args)
        existing.update(
            {
                "mode": mode,
                "dry_run": bool(getattr(args, "dry_run", False)),
                "hardware_touched": bool(hardware_intent and mode == "real" and not getattr(args, "dry_run", False)),
            }
        )
        return existing
    existing = getattr(args, "_candidate_admission_state", None)
    dry_run = bool(getattr(args, "dry_run", False))
    mode = mode_for_args(args)
    execution = existing if isinstance(existing, dict) else {}
    execution.update(
        {
            "mode": mode,
            "dry_run": dry_run,
            "hardware_touched": bool(hardware_intent and mode == "real" and not dry_run),
        }
    )
    setattr(args, "_execution_state", execution)
    return execution


def validation_execution_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    return {
        "mode": "simulate" if "--simulate" in argv else "real",
        "dry_run": "--dry-run" in argv,
        "hardware_touched": False,
    }


def with_serial_request_fields(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    serial_options = {
        "baud_rate": getattr(args, "serial_baud_rate", None),
        "data_bits": getattr(args, "serial_data_bits", None),
        "parity": getattr(args, "serial_parity", None),
        "stop_bits": getattr(args, "serial_stop_bits", None),
        "flow_control": getattr(args, "serial_flow_control", None),
        "read_termination": getattr(args, "serial_read_termination", None),
        "write_termination": getattr(args, "serial_write_termination", None),
    }
    serial_options = {key: value for key, value in serial_options.items() if value is not None}
    if serial_options:
        payload["serial_options"] = serial_options
    if getattr(args, "serial_remote", False):
        payload["serial_remote"] = True
    if getattr(args, "serial_local_on_close", False):
        payload["serial_local_on_close"] = True
    return payload


def support_policy_mode_for_args(args: argparse.Namespace) -> str:
    return (
        SUPPORT_POLICY_MODE_VALIDATION
        if getattr(args, "validation_allow_pending_live_support", False)
        else SUPPORT_POLICY_MODE_PRODUCT
    )


def serial_options_for_args(args: argparse.Namespace) -> SerialOptions | None:
    options = SerialOptions(
        baud_rate=getattr(args, "serial_baud_rate", None),
        data_bits=getattr(args, "serial_data_bits", None),
        parity=getattr(args, "serial_parity", None),
        stop_bits=getattr(args, "serial_stop_bits", None),
        flow_control=getattr(args, "serial_flow_control", None),
        read_termination=normalize_serial_termination(getattr(args, "serial_read_termination", None)),
        write_termination=normalize_serial_termination(getattr(args, "serial_write_termination", None)),
    )
    return options if options.has_explicit_values() else None
