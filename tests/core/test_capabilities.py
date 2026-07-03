from __future__ import annotations

import keysight_power_core.capabilities as capabilities


def test_hardware_validation_status_e36312a_shape() -> None:
    assert capabilities.hardware_validation_status("E36312A") == {
        "read_only": "validated",
        "output": "validated",
        "protection": "validated",
        "trigger": "validated",
    }


def test_hardware_validation_status_edu36311a_planning_boundary() -> None:
    assert capabilities.hardware_validation_status("EDU36311A") == {
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


def test_command_support_e36312a_output_protection_and_trigger_real() -> None:
    support = capabilities.command_support("E36312A")

    assert support["output-on"]["real"] is True
    assert support["output-on"]["hardware_validation"] == "validated_confirm_threshold_conditional"
    assert support["protection-set"]["real"] is True
    assert support["trigger-list"]["real"] is True
    assert support["trigger-list"]["hardware_validation"] == "validated"


def test_command_support_edu36311a_output_protection_and_trigger_boundary() -> None:
    support = capabilities.command_support("EDU36311A")

    assert support["output-on"]["real"] is True
    assert support["protection-set"] == {
        "real": True,
        "simulate": True,
        "dry_run": True,
        "requires_confirm": True,
        "hardware_validation": "validated",
    }
    assert support["trigger-step"]["hardware_validation"] == "planning_only"
    assert support["trigger-step"]["real"] is False
    assert support["trigger-list"]["hardware_validation"] == "not_supported_by_model"
    assert support["trigger-list"]["simulate"] is False


def test_command_support_generic_fallback() -> None:
    support = capabilities.command_support(None)

    assert support["identify"]["real"] is True
    assert support["identify"]["hardware_validation"] == "generic_channel_1_only"
    assert support["measure"]["real"] is True
    assert support["set"]["real"] is False
    assert support["set"]["hardware_validation"] == "not_enabled"


def test_command_support_e3646a_rs232_read_only_boundary() -> None:
    assert capabilities.hardware_validation_status("E3646A") == {
        "read_only": "rs232_read_only",
        "output": "validated",
        "protection": "not_enabled",
        "trigger": "not_enabled",
    }

    support = capabilities.command_support("E3646A")

    assert "verify" not in support
    for command in ("identify", "measure", "readback", "read-status", "output-state", "capabilities"):
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "rs232_read_only"

    validated_output_commands = (
        "set",
        "output-off",
        "safe-off",
        "ramp",
        "ramp-list",
        "sequence",
    )
    for command in validated_output_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated"

    conditional_output_commands = ("apply", "output-on", "cycle-output", "smoke-output")
    for command in conditional_output_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated_confirm_threshold_conditional"

    assert support["ramp-list"]["requires_confirm"] is False

    for command in (
        "protection-set",
        "clear-protection",
        "restore-from-snapshot",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
        "snapshot",
    ):
        assert support[command]["real"] is False
        assert support[command]["hardware_validation"] == "not_enabled"


def test_known_capability_commands_include_cli_queryable_commands() -> None:
    commands = capabilities.known_capability_commands()

    assert "verify" not in commands
    assert {
        "capabilities",
        "validate-readonly",
        "output-on",
        "protection-set",
        "trigger-step",
        "snapshot-diff",
        "safety inspect",
    } <= commands


def test_capabilities_static_groups_preserve_json_lists() -> None:
    assert capabilities.capabilities_static_groups() == {
        "read_only_commands": ["identify", "measure", "output-state", "readback", "read-status", "log", "sequence"],
        "output_commands": ["set", "output-on", "output-off", "safe-off", "cycle-output", "apply", "ramp", "ramp-list", "smoke-output"],
        "e36312a_only_commands": [
            "measure-all",
            "snapshot",
            "trigger-pulse",
            "trigger-status",
            "trigger-list",
        ],
    }
