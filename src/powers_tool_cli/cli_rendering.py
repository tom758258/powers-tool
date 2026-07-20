"""Pure human-readable text formatters for CLI success paths."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


__all__ = [
    "format_core_output_result",
    "format_core_trigger_result",
    "format_output_plan",
    "format_scpi_plan",
    "format_sequence_summary",
]


def format_core_output_result(
    *,
    command: str,
    resource: str,
    channel: int | str,
    current: object,
    voltage: object,
    no_output: bool,
    resource_data: Mapping[str, Any],
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    lines = [f"Resource: {resource}", f"Channel: {channel}"]
    if command == "set":
        lines.extend(
            [
                f"Current limit: {value_to_text(current)} A",
                f"Voltage: {value_to_text(voltage)} V",
            ]
        )
    elif command == "apply":
        lines.extend(
            [
                f"Current limit: {value_to_text(current)} A",
                f"Voltage: {value_to_text(voltage)} V",
                f"Output enabled: {str(not no_output).lower()}",
            ]
        )
    elif command == "output-on":
        lines.append("Output enabled: True")
    elif command == "output-off":
        lines.append("Output enabled: False")
    elif command == "safe-off":
        lines.extend(
            f"Channel {output['channel']}: Output enabled: {output['enabled']}"
            for output in resource_data["outputs"]
        )
    elif command == "output-state":
        if channel == "all":
            lines.extend(
                f"Channel {output['channel']}: Output enabled: {str(output['enabled']).lower()}"
                for output in resource_data["outputs"]
            )
        else:
            lines.append(f"Output enabled: {str(resource_data['output_enabled']).lower()}")
    elif command == "cycle-output":
        lines.append("Cycle complete: true")
    elif command == "ramp":
        lines.append(f"Steps: {resource_data['steps']}")
    elif command == "smoke-output":
        measurements = resource_data["measurements"]
        lines.extend(
            [
                f"Measured voltage: {value_to_text(measurements['voltage'])} V",
                f"Measured current: {value_to_text(measurements['current'])} A",
                f"Final output enabled: {resource_data['output']['final_enabled']}",
            ]
        )
    else:
        raise ValueError(f"unsupported core output command: {command}")
    return tuple(lines)


def format_core_trigger_result(
    *,
    command: str,
    resource: str,
    channel: int | str | None,
    mode: str,
    data: Mapping[str, Any],
) -> tuple[str, ...]:
    if "plan" in data:
        return format_scpi_plan(data["plan"], mode=mode, dry_run=True)
    if command == "trigger-pulse":
        return tuple(
            [
                f"Resource: {resource}",
                "Pins: " + ", ".join(str(pin) for pin in data["pins"]),
                f"Exclusive pins: {str(data['exclusive_pins']).lower()}",
                f"Polarity: {data['polarity']}",
                "Triggered: True",
            ]
        )
    if command == "trigger-status":
        return tuple([f"Resource: {resource}", f"Channel: {data['channel']}"])
    if command == "trigger-list":
        return tuple([f"Resource: {resource}", f"Steps: {data['steps']}"])
    if command == "trigger-step":
        return tuple(
            [
                f"Resource: {resource}",
                f"Triggered: {str(data['trigger']['completed']).lower()}",
            ]
        )
    if command == "trigger-fire":
        return tuple(["Triggered: true"])
    if command == "trigger-abort":
        return tuple([f"Channel {channel}: aborted"])
    return ()


def format_output_plan(
    plan: Mapping[str, Any],
    *,
    mode: str,
    dry_run: bool,
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    label = "Dry-run" if dry_run else "Simulation"
    lines = [
        f"{label} plan for {plan['operation']['name']}",
        f"Mode: {mode}",
        f"Resource: {plan['target']['resource']}",
        f"Channel: {plan['target']['channel']}",
        f"Hardware touched: {str(plan['hardware_touched']).lower()}",
        "Steps:",
    ]
    for step in plan["steps"]:
        parameters = " ".join(
            f"{name}={value_to_text(value)}"
            for name, value in step["parameters"].items()
        )
        lines.append(f"{step['index']}. {step['action']} {parameters}".rstrip())
    return tuple(lines)


def format_scpi_plan(
    plan: Mapping[str, Any],
    *,
    mode: str,
    dry_run: bool,
) -> tuple[str, ...]:
    label = "Dry-run" if dry_run else "Simulation"
    lines = [
        f"{label} plan for {plan['operation']['name']}",
        f"Mode: {mode}",
        f"Resource: {plan['target']['resource']}",
        f"Hardware touched: {str(plan['hardware_touched']).lower()}",
        "Steps:",
    ]
    lines.extend(f"{step['index']}. {step['command']}" for step in plan["steps"])
    return tuple(lines)


def format_sequence_summary(data: Mapping[str, Any]) -> tuple[str, ...]:
    resource = data["resource"]
    resource_name = resource if isinstance(resource, str) else resource.get("name")
    return tuple(
        [
            f"Resource: {resource_name}",
            f"Status: {data['status']}",
            f"Completed steps: {data['completed_steps']}",
        ]
    )
