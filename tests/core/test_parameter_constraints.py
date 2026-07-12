import pytest

from powers_tool_core.command_runner import run_core_command, validate_request_admission
from powers_tool_core.core import CoreValidationError, OperationRequest, RuntimeOptions, TriggerRequest
from powers_tool_core.parameter_constraints import parameter_constraints_metadata
from powers_tool_core.sequence import sequence_channel


@pytest.mark.parametrize(
    ("command", "parameters", "message"),
    [
        ("set", {"channel": 1, "voltage": -1, "current": 0.1}, "voltage"),
        ("set", {"channel": 1, "voltage": float("inf"), "current": 0.1}, "finite"),
        ("ramp", {"channel": 1, "start_voltage": 0, "stop_voltage": 1, "step_voltage": 0, "current": 0.1, "delay_ms": 0}, "step_voltage"),
        ("cycle-output", {"channel": 1, "duration_ms": 0}, "duration_ms"),
        ("error", {"max_reads": 0}, "max_reads"),
        ("trigger-fire", {"poll_ms": 49}, "poll_ms"),
        ("trigger-list", {"count": 257}, "count"),
    ],
)
def test_invalid_static_parameters_reject_before_opener(command, parameters, message) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("opener must not run")

    request_type = TriggerRequest if command.startswith("trigger-") else OperationRequest
    with pytest.raises(CoreValidationError, match=message):
        run_core_command(request_type(command=command, runtime=RuntimeOptions(resource="USB0::FAKE::INSTR"), parameters=parameters), opener=opener)

    assert opened is False


def test_constraint_metadata_describes_delay_semantics() -> None:
    delay = parameter_constraints_metadata()["delay_ms"]

    assert delay["min"] == 0
    assert delay["step"] == 1
    assert "Additional delay after each voltage step" in delay["description"]


@pytest.mark.parametrize(
    "channel",
    [True, False, 1.0, 1.9, 0.0, "1", " 1 ", None, [], {}],
)
def test_public_request_channels_reject_coercible_values(channel: object) -> None:
    with pytest.raises(CoreValidationError, match="channel must be a positive integer"):
        validate_request_admission(
            OperationRequest(
                "set",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {"channel": channel, "voltage": 1.0},
            )
        )


@pytest.mark.parametrize("channel", [1, 2, 3, "all"])
def test_all_channel_commands_accept_exact_contract_values(channel: int | str) -> None:
    validate_request_admission(
        OperationRequest(
            "apply",
            RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
            {"channel": channel, "voltage": 1.0, "current": 0.1},
        )
    )


def test_single_channel_command_rejects_all_and_measure_all_rejects_channel() -> None:
    with pytest.raises(CoreValidationError, match="channel must be a positive integer"):
        validate_request_admission(
            OperationRequest(
                "ramp",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {
                    "channel": "all",
                    "start_voltage": 0,
                    "stop_voltage": 1,
                    "step_voltage": 1,
                    "current": 0.1,
                    "delay_ms": 0,
                },
            )
        )


@pytest.mark.parametrize("channel", [True, False, 1.0, 1.9, "1", "ALL", None, [], {}])
def test_sequence_document_channels_reject_coercible_values(channel: object) -> None:
    with pytest.raises(CoreValidationError, match="sequence channel must be a positive integer"):
        sequence_channel(channel, allow_all=True)


def test_sequence_document_channel_accepts_exact_integer_and_all() -> None:
    assert sequence_channel(1) == 1
    assert sequence_channel("all", allow_all=True) == "all"
    with pytest.raises(CoreValidationError, match="does not accept channel"):
        validate_request_admission(
            OperationRequest(
                "measure-all",
                RuntimeOptions(simulate=True, resource="USB0::SIM::E36312A::INSTR"),
                {"channel": 1},
            )
        )
