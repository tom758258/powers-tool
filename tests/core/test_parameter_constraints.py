import pytest

from keysight_power_core.command_runner import run_core_command
from keysight_power_core.core import CoreValidationError, OperationRequest, RuntimeOptions, TriggerRequest
from keysight_power_core.parameter_constraints import parameter_constraints_metadata


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
