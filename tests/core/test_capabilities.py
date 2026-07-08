from __future__ import annotations

import pytest

import keysight_power_core.capabilities as capabilities


def test_hardware_validation_status_e36312a_shape() -> None:
    assert capabilities.hardware_validation_status("E36312A") == {
        "read_only": "validated",
        "output": "validated",
        "protection": "validated",
        "trigger": "validated",
    }


def test_hardware_validation_status_edu36311a_trigger_boundary() -> None:
    assert capabilities.hardware_validation_status("EDU36311A") == {
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


def test_command_support_e36312a_output_protection_and_trigger_real() -> None:
    support = capabilities.command_support("E36312A")

    assert support["output-on"]["real"] is True
    assert support["output-on"]["hardware_validation"] == "validated_confirm_threshold_conditional"
    assert support["protection-set"]["real"] is True
    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is True
        assert support[command]["simulate"] is True
        assert support[command]["dry_run"] is True
        assert support[command]["hardware_validation"] == "validated"


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
    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is False
        assert support[command]["simulate"] is False
        assert support[command]["dry_run"] is False
        assert support[command]["hardware_validation"] == "not_supported_by_model"


@pytest.mark.parametrize("command", ["trigger-step", "trigger-list"])
def test_command_support_e36312a_native_trigger_policy(command: str) -> None:
    support = capabilities.command_support("E36312A")

    assert support[command]["real"] is True
    assert support[command]["simulate"] is True
    assert support[command]["dry_run"] is True
    assert support[command]["hardware_validation"] == "validated"


@pytest.mark.parametrize("command", ["snapshot", "restore-from-snapshot"])
def test_command_support_edu36311a_snapshot_restore_disabled(command: str) -> None:
    support = capabilities.command_support("EDU36311A")

    assert support[command]["real"] is False
    assert support[command]["simulate"] is False
    assert support[command]["dry_run"] is False
    assert support[command]["hardware_validation"] == "not_supported_by_model"


def test_command_support_generic_fallback() -> None:
    support = capabilities.command_support(None)

    assert support["identify"]["real"] is True
    assert support["identify"]["hardware_validation"] == "generic_channel_1_only"
    assert support["measure"]["real"] is True
    assert support["set"]["real"] is False
    assert support["set"]["hardware_validation"] == "not_enabled"


@pytest.mark.parametrize("model", [None, "UNKNOWN"])
def test_command_support_non_e36312a_models_disable_trigger_no_hardware(model: str | None) -> None:
    support = capabilities.command_support(model)

    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is False
        assert support[command]["simulate"] is False
        assert support[command]["dry_run"] is False


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
        "trigger-status",
        "trigger-pulse",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
        "snapshot",
    ):
        assert support[command]["real"] is False
        if command.startswith("trigger-"):
            assert support[command]["simulate"] is False
            assert support[command]["dry_run"] is False
        assert support[command]["hardware_validation"] == "not_enabled"


@pytest.mark.parametrize(
    "command",
    [
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
    ],
)
def test_command_support_e3646a_unsupported_mutating_and_native_workflows_disabled(command: str) -> None:
    support = capabilities.command_support("E3646A")

    assert support[command]["real"] is False
    assert support[command]["simulate"] is False
    assert support[command]["dry_run"] is False
    assert support[command]["hardware_validation"] == "not_enabled"


@pytest.mark.parametrize("command", ["ramp-list", "sequence"])
def test_command_support_e3646a_software_workflows_remain_allowed(command: str) -> None:
    support = capabilities.command_support("E3646A")

    assert support[command]["real"] is True
    assert support[command]["simulate"] is True
    assert support[command]["hardware_validation"] == "validated"


@pytest.mark.parametrize("model", ["UNKNOWN", "FUTURE123"])
def test_command_support_unknown_models_do_not_enable_mutating_workflows(model: str) -> None:
    support = capabilities.command_support(model)

    for command in (
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "ramp-list",
        "smoke-output",
        "sequence",
        "protection-set",
        "clear-protection",
        "snapshot",
        "restore-from-snapshot",
        "trigger-pulse",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is False, command


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
            "trigger-step",
            "trigger-list",
            "trigger-fire",
            "trigger-abort",
        ],
    }


def _unsupported_message(command: str, model: str, mode: str) -> str:
    with pytest.raises(Exception) as exc:
        capabilities.ensure_command_supported(command, model, mode)
    return str(exc.value)


def test_edu36311a_trigger_error_explains_feature_lock() -> None:
    message = _unsupported_message("trigger-step", "EDU36311A", "dry-run")

    assert "trigger-step" in message
    assert "EDU36311A" in message
    assert "dry-run mode" in message
    assert "disabled in live, simulate, and dry-run" in message
    assert "Use E36312A" in message


@pytest.mark.parametrize("command", ["snapshot", "restore-from-snapshot"])
def test_edu36311a_snapshot_restore_error_explains_e36312a_only(command: str) -> None:
    message = _unsupported_message(command, "EDU36311A", "simulate")

    assert command in message
    assert "EDU36311A" in message
    assert "simulate mode" in message
    assert "E36312A-only" in message
    assert "hardware validated" in message


@pytest.mark.parametrize("command", ["protection-set", "trigger-list", "snapshot", "restore-from-snapshot", "trigger-pulse"])
def test_e3646a_disabled_workflow_errors_explain_validation_boundary(command: str) -> None:
    message = _unsupported_message(command, "E3646A", "live")

    assert command in message
    assert "E3646A" in message
    assert "live mode" in message
    assert "disabled until separately validated" in message
    if command in {"trigger-list", "trigger-pulse"}:
        assert "software workflows, not native LIST" in message


@pytest.mark.parametrize("model", ["UNKNOWN", "FUTURE123"])
def test_unknown_model_mutating_error_explains_feature_lock(model: str) -> None:
    message = _unsupported_message("output-on", model, "live")

    assert "output-on" in message
    assert model in message
    assert "live mode" in message
    assert "E36312A-only" in message
