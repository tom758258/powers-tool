"""Shared command capability metadata for the CLI and future adapters."""

from __future__ import annotations

from typing import Any

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
        "smoke-output",
    }
)
E36312A_ONLY_COMMANDS = (
    "measure-all",
    "snapshot",
    "trigger-pulse",
    "trigger-status",
    "trigger-list",
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
        "protection-set",
        "clear-protection",
        "restore-from-snapshot",
        "trigger-pulse",
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
            "trigger": {
                "step": "planning_only",
                "native_list": "not_supported_by_model",
                "real": False,
            },
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
    edu36311a_planning_trigger = {"trigger-step", "trigger-fire", "trigger-abort"}
    commands = sorted(READ_ONLY_COMMANDS | OUTPUT_COMMANDS | _E36312A_EXTRA_COMMANDS | OFFLINE_COMMANDS)
    support: dict[str, dict[str, Any]] = {}
    for command in commands:
        entry = {
            "real": False,
            "simulate": True,
            "dry_run": command in OUTPUT_COMMANDS or command in _DRY_RUN_TRIGGER_COMMANDS,
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
                entry["hardware_validation"] = "validated"
            if command in {"output-on", "cycle-output", "apply", "smoke-output"}:
                entry["hardware_validation"] = "validated_confirm_threshold_conditional"
        elif normalized == "EDU36311A":
            if command in edu36311a_real:
                entry["real"] = True
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
            if command in edu36311a_planning_trigger:
                entry.update(
                    {
                        "real": False,
                        "simulate": True,
                        "dry_run": True,
                        "requires_confirm": False,
                        "hardware_validation": "planning_only",
                    }
                )
            if command in {"trigger-list", "trigger-pulse"}:
                entry.update(
                    {
                        "real": False,
                        "simulate": False,
                        "dry_run": False,
                        "requires_confirm": False,
                        "hardware_validation": "not_supported_by_model",
                    }
                )
        else:
            if command in {"identify", "measure", "doctor", "capabilities"}:
                entry["real"] = True
                entry["hardware_validation"] = "generic_channel_1_only"
        support[command] = entry
    return support


def known_capability_commands() -> set[str]:
    """Return all commands accepted by the capabilities command filter."""

    return set(command_support("E36312A")) | set(command_support("EDU36311A")) | set(command_support(None))


def capabilities_static_groups() -> dict[str, list[str]]:
    """Return stable command group lists used by the capabilities JSON payload."""

    return {
        "read_only_commands": ["identify", "measure", "output-state", "readback", "read-status", "log", "sequence"],
        "output_commands": ["set", "output-on", "output-off", "safe-off", "cycle-output", "apply", "ramp", "smoke-output"],
        "e36312a_only_commands": list(E36312A_ONLY_COMMANDS),
    }
