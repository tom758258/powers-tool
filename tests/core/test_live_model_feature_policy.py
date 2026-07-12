from __future__ import annotations

import pytest

from powers_tool_core.command_runner import run_core_command
from powers_tool_core.core import CoreValidationError, OperationRequest, RuntimeOptions, SequenceRequest, TriggerRequest


def _snapshot_document(model: str) -> dict[str, object]:
    model_ids = {
        "E36312A": "keysight-e36312a",
        "EDU36311A": "keysight-edu36311a",
        "E3646A": "keysight-e3646a",
    }
    return {
        "schema_version": 2,
        "kind": "powers-tool-snapshot",
        "reported_identity": {
            "manufacturer": "KEYSIGHT",
            "model": model,
            "serial": "SERIAL0000",
            "firmware": "1.0",
            "parse_ok": True,
        },
        "resolved_identity": {
            "vendor_id": "keysight",
            "model_id": model_ids[model],
            "model_name": model,
            "display_name": f"Keysight {model}",
        },
        "outputs": [{"channel": 1, "enabled": False}],
        "readback": [{"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.05}}],
        "protection_settings": [{"channel": 1, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True}}],
    }


@pytest.mark.parametrize(
    "runtime",
    [
        RuntimeOptions(dry_run=True, planning_model_id="keysight-edu36311a"),
        RuntimeOptions(simulate=True, resource="USB0::SIM::EDU36311A::INSTR"),
    ],
)
def test_edu36311a_trigger_step_no_hardware_rejected(runtime: RuntimeOptions) -> None:
    request = TriggerRequest(
        command="trigger-step",
        runtime=runtime,
        parameters={"channel": 1, "source": "bus", "fire": True},
    )

    with pytest.raises(CoreValidationError, match="E36312A|not supported|not enabled"):
        run_core_command(request)


@pytest.mark.parametrize(
    ("command", "core_request"),
    [
        (
            "snapshot",
            OperationRequest(
                command="snapshot",
                runtime=RuntimeOptions(simulate=True, resource="USB0::SIM::EDU36311A::INSTR"),
                parameters={},
            ),
        ),
        (
            "restore-from-snapshot",
            OperationRequest(
                command="restore-from-snapshot",
                runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-edu36311a"),
                parameters={"document": _snapshot_document("EDU36311A"), "channel": 1},
            ),
        ),
    ],
)
def test_edu36311a_snapshot_restore_rejected(command: str, core_request: OperationRequest) -> None:
    with pytest.raises(CoreValidationError, match="E36312A|not supported|not enabled"):
        run_core_command(core_request)


@pytest.mark.parametrize(
    "runtime",
    [
        RuntimeOptions(dry_run=True, planning_model_id="keysight-edu36311a"),
        RuntimeOptions(simulate=True, resource="USB0::SIM::EDU36311A::INSTR"),
    ],
)
def test_edu36311a_sequence_trigger_pulse_rejected(runtime: RuntimeOptions) -> None:
    request = SequenceRequest(
        runtime=runtime,
        parameters={"document": {"version": 1, "steps": [{"action": "trigger-pulse", "channel": 1, "pins": [1]}]}},
    )

    with pytest.raises(CoreValidationError, match="trigger-pulse|E36312A"):
        run_core_command(request)


@pytest.mark.parametrize(
    "core_request",
    [
        OperationRequest(
            command="protection-set",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
            parameters={"channel": 1, "ovp_voltage": 5.0},
        ),
        OperationRequest(
            command="snapshot",
            runtime=RuntimeOptions(simulate=True, resource="ASRL1::SIM::E3646A::INSTR"),
            parameters={},
        ),
        OperationRequest(
            command="restore-from-snapshot",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
            parameters={"document": _snapshot_document("E3646A"), "channel": 1},
        ),
        TriggerRequest(
            command="trigger-step",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
            parameters={"channel": 1, "source": "bus", "fire": True},
        ),
        TriggerRequest(
            command="trigger-list",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
            parameters={
                "channel": 1,
                "source": "bus",
                "fire": True,
                "wait_complete": True,
                "voltage_list": [0.0, 1.0],
                "current_list": [0.05, 0.05],
                "dwell_list": [0.01, 0.01],
            },
        ),
    ],
)
def test_e3646a_unsupported_core_workflows_rejected(core_request: OperationRequest | TriggerRequest) -> None:
    with pytest.raises(CoreValidationError, match="E36312A|not supported|not enabled"):
        run_core_command(core_request)


@pytest.mark.parametrize(
    "action",
    [
        "protection-set",
        "clear-protection",
        "trigger-pulse",
        "trigger-list",
        "snapshot",
        "restore-from-snapshot",
        "native-list",
        "completion-pulse",
    ],
)
def test_e3646a_sequence_unsupported_step_types_fail(action: str) -> None:
    request = SequenceRequest(
        runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
        parameters={"document": {"version": 1, "steps": [{"action": action, "channel": 1, "pins": [1]}]}},
    )

    with pytest.raises(CoreValidationError, match="unsupported|E36312A|not enabled"):
        run_core_command(request)


def test_e3646a_sequence_validated_read_only_and_output_steps_still_plan() -> None:
    request = SequenceRequest(
        runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
        parameters={
            "document": {
                "version": 1,
                "steps": [
                    {"action": "readback", "channel": 1},
                    {"action": "set", "channel": 2, "voltage": 1.0, "current": 0.05},
                    {"action": "output-off", "channel": 2},
                ],
            }
        },
    )

    result = run_core_command(request)

    assert result["status"] == "planned"
    assert result["plan"]["target"]["planning_model_id"] == "keysight-e3646a"
    assert [step["action"] for step in result["plan"]["steps"]] == ["readback", "set", "output-off"]
