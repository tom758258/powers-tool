import pytest

from keysight_power_core.command_runner import run_core_command
from keysight_power_core.connection import InstrumentSession
from keysight_power_core.core import CoreValidationError, OperationRequest, RuntimeOptions, SequenceRequest, TriggerRequest
from keysight_power_core.operations import output_plan, run_operation
from keysight_power_core.protection import run_protection
from keysight_power_core.ramp_list import RAMP_LIST_KIND, run_ramp_list
from keysight_power_core.sequence import run_sequence
from keysight_power_core.testing.simulator import SimulatedResourceManager


def test_runtime_options_model_profile_defaults_to_none() -> None:
    assert RuntimeOptions().model_profile is None


def test_dry_run_requires_model_or_known_sim_resource() -> None:
    with pytest.raises(CoreValidationError, match="require --model"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(dry_run=True),
                parameters={"channel": 1},
            )
        )


def test_model_profile_is_case_insensitive_and_generic_dry_run_is_single_channel() -> None:
    plan = output_plan(
        OperationRequest(
            command="output-on",
            runtime=RuntimeOptions(dry_run=True, model_profile="generic"),
            parameters={"channel": "all"},
        )
    )

    assert plan["target"]["model_profile"] == "GENERIC"
    assert [step["parameters"]["channel"] for step in plan["steps"]] == [1]


def test_simulate_derives_resource_from_model_and_rejects_generic() -> None:
    plan = output_plan(
        OperationRequest(
            command="output-on",
            runtime=RuntimeOptions(simulate=True, model_profile="E36312A"),
            parameters={"channel": 1},
        )
    )

    assert plan["target"]["resource"] == "USB0::SIM::E36312A::INSTR"
    with pytest.raises(CoreValidationError, match="no deterministic simulator"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(simulate=True, model_profile="GENERIC"),
                parameters={"channel": 1},
            )
        )


def test_simulate_rejects_explicit_non_sim_resource() -> None:
    with pytest.raises(CoreValidationError, match="requires a deterministic SIM resource"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(
                    resource="ASRL7::INSTR",
                    simulate=True,
                    model_profile="E3646A",
                ),
                parameters={"channel": 1},
            )
        )


def test_sim_resource_infers_model_and_mismatch_is_rejected() -> None:
    plan = output_plan(
        OperationRequest(
            command="output-on",
            runtime=RuntimeOptions(resource="ASRL1::SIM::E3646A::INSTR", dry_run=True),
            parameters={"channel": "all"},
        )
    )

    assert plan["target"]["model_profile"] == "E3646A"
    assert [step["parameters"]["channel"] for step in plan["steps"]] == [1, 2]
    with pytest.raises(CoreValidationError, match="does not match"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(
                    resource="USB0::SIM::E36312A::INSTR",
                    simulate=True,
                    model_profile="E3646A",
                ),
                parameters={"channel": 1},
            )
        )


def test_live_model_profile_is_rejected_before_opening() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("must not open")

    with pytest.raises(CoreValidationError, match="only supported with --dry-run or --simulate"):
        run_operation(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", model_profile="E36312A"),
                parameters={"channel": 1},
            ),
            opener=opener,
        )

    assert opened is False


def test_e3646a_no_hardware_channel_three_is_rejected_across_planners() -> None:
    runtime = RuntimeOptions(dry_run=True, model_profile="E3646A")

    with pytest.raises(CoreValidationError, match="channel 3"):
        output_plan(OperationRequest(command="output-on", runtime=runtime, parameters={"channel": 3}))

    ramp_document = {
        "kind": RAMP_LIST_KIND,
        "version": 1,
        "segments": [
            {
                "channel": 3,
                "current": 0.1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 1,
                "delay_ms": 0,
                "hold_ms": 0,
            }
        ],
    }
    with pytest.raises(CoreValidationError, match="channel 3"):
        run_ramp_list(OperationRequest(command="ramp-list", runtime=runtime, parameters={"document": ramp_document}))

    sequence_document = {"version": 1, "steps": [{"action": "output-on", "channel": 3}]}
    with pytest.raises(CoreValidationError, match="channel 3"):
        run_sequence(SequenceRequest(runtime=runtime, parameters={"document": sequence_document}))

    with pytest.raises(CoreValidationError, match="channel 3"):
        run_protection(
            OperationRequest(
                command="clear-protection",
                runtime=runtime,
                parameters={"channel": 3},
            )
        )


def test_sequence_and_protection_e3646a_all_expand_to_two_channels() -> None:
    runtime = RuntimeOptions(dry_run=True, model_profile="E3646A")

    sequence_data = run_sequence(
        SequenceRequest(
            runtime=runtime,
            parameters={"document": {"version": 1, "steps": [{"action": "output-off", "channel": "all"}]}},
        )
    )
    assert sequence_data["plan"]["target"]["model_profile"] == "E3646A"
    assert sequence_data["plan"]["steps"][0]["preview"]["commands"] == ["OUTP OFF,(@1)", "OUTP OFF,(@2)"]

    protection_data = run_protection(
        OperationRequest(
            command="clear-protection",
            runtime=runtime,
            parameters={"channel": "all"},
        )
    )
    assert protection_data["plan"]["target"]["model_profile"] == "E3646A"
    assert [step["command"] for step in protection_data["plan"]["steps"]] == [
        "OUTP:PROT:CLE (@1)",
        "OUTP:PROT:CLE (@2)",
    ]


def test_trigger_dry_run_requires_e36312a_model_or_known_sim_resource() -> None:
    with pytest.raises(CoreValidationError, match="require --model"):
        run_core_command(
            TriggerRequest(
                command="trigger-fire",
                runtime=RuntimeOptions(dry_run=True),
            )
        )

    data = run_core_command(
        TriggerRequest(
            command="trigger-fire",
            runtime=RuntimeOptions(dry_run=True, model_profile="E36312A"),
        )
    )
    assert data["plan"]["target"]["model_profile"] == "E36312A"


@pytest.mark.parametrize("model", ["EDU36311A", "E3646A", "E36103B", "E36232A", "GENERIC"])
@pytest.mark.parametrize("mode", ["dry_run", "simulate"])
def test_trigger_no_hardware_rejects_unsupported_models(model: str, mode: str) -> None:
    runtime = RuntimeOptions(
        dry_run=mode == "dry_run",
        simulate=mode == "simulate",
        model_profile=model,
    )

    with pytest.raises(CoreValidationError, match="only supported for E36312A|deterministic simulator"):
        run_core_command(
            TriggerRequest(
                command="trigger-fire",
                runtime=runtime,
            )
        )


def test_trigger_sim_resource_infers_e36312a_and_rejects_edu36311a() -> None:
    data = run_core_command(
        TriggerRequest(
            command="trigger-status",
            runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True),
            parameters={"channel": "all"},
        )
    )

    assert data["plan"]["target"]["model_profile"] == "E36312A"

    with pytest.raises(CoreValidationError, match="only supported for E36312A"):
        run_core_command(
            TriggerRequest(
                command="trigger-status",
                runtime=RuntimeOptions(resource="USB0::SIM::EDU36311A::INSTR", dry_run=True),
                parameters={"channel": "all"},
            )
        )


def test_trigger_simulate_model_derives_e36312a_resource() -> None:
    opened: list[str] = []
    manager = SimulatedResourceManager()

    def opener(resource: str, **kwargs):
        opened.append(resource)
        return InstrumentSession(manager.open_resource(resource), resource_name=resource)

    data = run_core_command(
        TriggerRequest(
            command="trigger-status",
            runtime=RuntimeOptions(simulate=True, model_profile="E36312A"),
            parameters={"channel": 1},
        ),
        opener=opener,
    )

    assert opened == ["USB0::SIM::E36312A::INSTR"]
    assert data["idn"].split(",")[1] == "E36312A"


def test_trigger_live_model_profile_is_rejected_before_opening() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("must not open")

    with pytest.raises(CoreValidationError, match="only supported with --dry-run or --simulate"):
        run_core_command(
            TriggerRequest(
                command="trigger-status",
                runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", model_profile="E36312A"),
                parameters={"channel": 1},
            ),
            opener=opener,
        )

    assert opened is False


def test_trigger_status_and_abort_all_dry_run_expand_e36312a_channels() -> None:
    status_data = run_core_command(
        TriggerRequest(
            command="trigger-status",
            runtime=RuntimeOptions(dry_run=True, model_profile="E36312A"),
            parameters={"channel": "all"},
        )
    )
    status_commands = [step["command"] for step in status_data["plan"]["steps"]]
    assert "TRIG:SOUR? (@1)" in status_commands
    assert "TRIG:SOUR? (@2)" in status_commands
    assert "TRIG:SOUR? (@3)" in status_commands

    abort_data = run_core_command(
        TriggerRequest(
            command="trigger-abort",
            runtime=RuntimeOptions(dry_run=True, model_profile="E36312A"),
            parameters={"channel": "all"},
        )
    )
    assert [step["command"] for step in abort_data["plan"]["steps"]] == [
        "ABOR (@1)",
        "ABOR (@2)",
        "ABOR (@3)",
    ]
