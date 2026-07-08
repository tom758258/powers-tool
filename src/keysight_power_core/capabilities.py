"""Shared command capability metadata for the CLI and future adapters."""

from __future__ import annotations

from typing import Any

from keysight_power_core.core import CoreValidationError, UnsupportedModelError

READ_ONLY_COMMANDS = frozenset(
    {
        "identify",
        "measure",
        "output-state",
        "readback",
        "read-status",
        "validate-readonly",
        "log",
        "sequence",
        "capabilities",
    }
)
OUTPUT_COMMANDS = frozenset(
    {
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "apply",
        "ramp",
        "ramp-list",
        "smoke-output",
    }
)
E36312A_ONLY_COMMANDS = (
    "measure-all",
    "snapshot",
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
)
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
OFFLINE_COMMANDS = frozenset({"snapshot-diff", "hardware-report", "doctor", "safety inspect"})

_E36312A_EXTRA_COMMANDS = frozenset(
    {
        "measure-all",
        "protection-status",
        "protection-set",
        "clear-protection",
        "snapshot",
        "restore-from-snapshot",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }
)
_DRY_RUN_TRIGGER_COMMANDS = frozenset(
    {
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }
)


def hardware_validation_status(model: str | None) -> dict[str, Any]:
    """Return hardware validation status payload for a selected model."""

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
            "read_only": "validated",
            "output": "validated",
            "protection": {
                "dry_run": True,
                "simulate": True,
                "real": True,
                "hardware_validation": "validated",
            },
            "trigger": "not_supported_by_model",
        }
    if normalized == "E3646A":
        return {
            "read_only": "rs232_read_only",
            "output": "validated",
            "protection": "not_enabled",
            "trigger": "not_enabled",
        }
    return {
        "read_only": "generic_channel_1_only",
        "output": "not_enabled",
        "protection": "not_enabled",
        "trigger": "not_enabled",
    }


def command_support(model: str | None) -> dict[str, dict[str, Any]]:
    """Return per-command support metadata for a selected model."""

    normalized = (model or "").upper()
    edu36311a_real = READ_ONLY_COMMANDS | OUTPUT_COMMANDS | {
        "protection-status",
        "protection-set",
        "clear-protection",
    }
    e3646a_real = {"identify", "measure", "output-state", "readback", "read-status", "capabilities"}
    e3646a_output = {
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "apply",
        "ramp",
        "ramp-list",
        "smoke-output",
        "sequence",
    }
    commands = sorted(READ_ONLY_COMMANDS | OUTPUT_COMMANDS | _E36312A_EXTRA_COMMANDS | OFFLINE_COMMANDS)
    support: dict[str, dict[str, Any]] = {}
    for command in commands:
        entry = {
            "real": False,
            "simulate": False,
            "dry_run": False,
            "requires_confirm": command
            in {
                "output-on",
                "cycle-output",
                "apply",
                "smoke-output",
                "protection-set",
                "clear-protection",
                "restore-from-snapshot",
            },
            "hardware_validation": "not_enabled",
        }
        if command in OFFLINE_COMMANDS:
            entry.update(
                {
                    "real": True,
                    "simulate": True,
                    "dry_run": False,
                    "requires_confirm": False,
                    "hardware_validation": "not_applicable",
                }
            )
        elif normalized == "E36312A":
            if command in READ_ONLY_COMMANDS | OUTPUT_COMMANDS | _E36312A_EXTRA_COMMANDS:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in READ_ONLY_COMMANDS or command in OUTPUT_COMMANDS or command in _DRY_RUN_TRIGGER_COMMANDS or command in {"protection-set", "clear-protection", "restore-from-snapshot"}
                entry["hardware_validation"] = "validated"
            if command in {"output-on", "cycle-output", "apply", "smoke-output"}:
                entry["hardware_validation"] = "validated_confirm_threshold_conditional"
        elif normalized == "EDU36311A":
            if command in edu36311a_real:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in READ_ONLY_COMMANDS or command in OUTPUT_COMMANDS or command in {"protection-set", "clear-protection"}
                entry["hardware_validation"] = "validated"
            if command in {"output-on", "cycle-output", "apply", "smoke-output"}:
                entry["hardware_validation"] = "validated_confirm_threshold_conditional"
            if command in {"protection-set", "clear-protection"}:
                entry.update(
                    {
                        "real": True,
                        "simulate": True,
                        "dry_run": True,
                        "requires_confirm": True,
                        "hardware_validation": "validated",
                    }
                )
            if command in TRIGGER_COMMANDS:
                entry.update(
                    {
                        "real": False,
                        "simulate": False,
                        "dry_run": False,
                        "requires_confirm": False,
                        "hardware_validation": "not_supported_by_model",
                    }
                )
            if command in {"snapshot", "restore-from-snapshot"}:
                entry["hardware_validation"] = "not_supported_by_model"
        elif normalized == "E3646A":
            if command in e3646a_real and command not in e3646a_output:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in READ_ONLY_COMMANDS
                entry["hardware_validation"] = "rs232_read_only"
            elif command in e3646a_output:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in OUTPUT_COMMANDS or command == "sequence"
                entry["hardware_validation"] = "validated"
                if command in {"apply", "output-on", "cycle-output", "smoke-output"}:
                    entry["hardware_validation"] = "validated_confirm_threshold_conditional"
        else:
            if command in {"identify", "measure", "doctor", "capabilities"}:
                entry["real"] = True
                entry["simulate"] = True
                entry["hardware_validation"] = "generic_channel_1_only"
            if normalized == "GENERIC" and command in READ_ONLY_COMMANDS | OUTPUT_COMMANDS:
                entry["simulate"] = True
                entry["dry_run"] = True
                entry["hardware_validation"] = "generic_channel_1_only"
        if normalized not in {"E36312A", "EDU36311A"} and command in TRIGGER_COMMANDS:
            entry.update(
                {
                    "real": False,
                    "simulate": False,
                    "dry_run": False,
                    "requires_confirm": False,
                    "hardware_validation": "not_enabled",
                }
            )
        support[command] = entry
    return support


def ensure_command_supported(command: str, model: str | None, mode: str) -> None:
    """Raise if the command is disabled for the selected model and runtime mode."""

    mode_key = "dry_run" if mode == "dry-run" else mode
    support = command_support(model).get(command)
    if support is None:
        raise CoreValidationError(f"unsupported core command {command!r}")
    if support.get(mode_key) is True:
        return
    model_label = model or "GENERIC"
    mode_label = "dry-run" if mode_key == "dry_run" else mode_key
    detail = f"{command} is not supported for {model_label} in {mode_label} mode"
    e36312a_support = command_support("E36312A").get(command, {})
    if e36312a_support.get(mode_key) is True:
        detail += "; only supported for E36312A in this mode"
    if mode_key in {"dry_run", "simulate"}:
        detail += "; --model is not a feature unlock and does not enable unsupported commands"
    raise UnsupportedModelError(detail)


def known_capability_commands() -> set[str]:
    """Return all commands accepted by the capabilities command filter."""

    return set(command_support("E36312A")) | set(command_support("E3646A")) | set(command_support("EDU36311A")) | set(command_support(None))


def capabilities_static_groups() -> dict[str, list[str]]:
    """Return stable command group lists used by the capabilities JSON payload."""

    return {
        "read_only_commands": ["identify", "measure", "output-state", "readback", "read-status", "log", "sequence"],
        "output_commands": ["set", "output-on", "output-off", "safe-off", "cycle-output", "apply", "ramp", "ramp-list", "smoke-output"],
        "e36312a_only_commands": list(E36312A_ONLY_COMMANDS),
    }
