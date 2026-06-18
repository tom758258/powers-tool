import pytest

from keysight_power_core.command_runner import run_core_command
from keysight_power_core.core import CoreExecutionError, CoreValidationError, RuntimeOptions, TriggerRequest, TriggerWaitTimeout
from keysight_power_core.trigger import (
    _raise_on_instrument_errors,
    trigger_list_scpi,
    trigger_plan,
    trigger_pulse_scpi,
    trigger_result_payload,
    trigger_step_scpi,
    validate_real_trigger_source,
    validate_trigger_request,
    wait_for_trigger_completion,
)


def test_trigger_pulse_dry_run_scpi_preview_unchanged() -> None:
    scpi = trigger_pulse_scpi((1,), "positive", 1, exclusive_pins=True)

    assert scpi == (
        "DIG:PIN2:FUNC DIO",
        "DIG:PIN3:FUNC DIO",
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:TOUT:BUS ON",
        "CURR:TRIG <current-readback>,(@1)",
        "VOLT:TRIG <voltage-readback>,(@1)",
        "CURR:MODE FIX,(@1)",
        "VOLT:MODE FIX,(@1)",
        "CURR:MODE STEP,(@1)",
        "VOLT:MODE STEP,(@1)",
        "TRIG:SOUR BUS,(@1)",
        "INIT (@1)",
        "*TRG",
    )


def test_trigger_step_preview_with_wait_complete() -> None:
    scpi = trigger_step_scpi(
        channel=1,
        source="bus",
        voltage=1.2,
        current=0.2,
        pins=(2,),
        polarity="negative",
        fire=True,
        wait_complete=True,
    )

    assert scpi[-5:] == ("*TRG", "*CLS", "*ESE 1", "*OPC", "*ESR?")
    assert "DIG:PIN2:POL NEG" in scpi


def test_trigger_list_length_boundary() -> None:
    trigger_list_scpi(
        channel=1,
        source="bus",
        voltages=tuple(float(index) for index in range(100)),
        currents=(0.1,) * 100,
        dwell=(0.01,) * 100,
    )

    with pytest.raises(CoreValidationError):
        trigger_list_scpi(
            channel=1,
            source="bus",
            voltages=tuple(float(index) for index in range(101)),
            currents=(0.1,) * 101,
            dwell=(0.01,) * 101,
        )


def test_real_pin_ext_trigger_input_gate() -> None:
    request = TriggerRequest(
        command="trigger-step",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=False, simulate=False),
        parameters={},
    )

    with pytest.raises(CoreValidationError):
        validate_real_trigger_source(request, "pin1")


def test_trigger_dry_run_plan_shape() -> None:
    request = TriggerRequest(
        command="trigger-list",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True),
        parameters={
            "channel": 1,
            "voltage_list": (0.0, 1.0),
            "current_list": (0.1,),
            "dwell_list": (0.01,),
            "completion_pulse_pins": (1,),
            "leave_trigger_configured": True,
        },
    )

    plan = trigger_plan(request)

    assert plan["operation"] == {"name": "trigger-list"}
    assert plan["hardware_touched"] is False
    assert plan["steps"][0]["command"] == "ABOR (@1)"


def test_trigger_list_explicit_bost_eost_plan() -> None:
    request = TriggerRequest(
        command="trigger-list",
        runtime=RuntimeOptions(dry_run=True),
        parameters={
            "channel": 2,
            "source": "immediate",
            "wait_complete": True,
            "voltage_list": [0.0, 1.0],
            "current_list": [0.05, 0.05],
            "dwell_list": [0.01, 0.02],
            "bost_list": [True, False],
            "eost_list": [False, True],
            "trigger_output_pins": [1, 3],
            "trigger_output_polarity": "negative",
        },
    )

    commands = [step["command"] for step in trigger_plan(request)["steps"]]

    assert "LIST:TOUT:BOST 1,0,(@2)" in commands
    assert "LIST:TOUT:EOST 0,1,(@2)" in commands
    assert "DIG:PIN1:POL NEG" in commands
    assert "DIG:PIN3:POL NEG" in commands


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"bost_list": [True]}, "BOST list length"),
        ({"eost_list": [False]}, "EOST list length"),
        ({"bost_list": [True, False], "eost_list": [False, False]}, "explicit trigger_output_pins"),
        ({"bost_list": [False, False], "trigger_output_pins": [4]}, "rear pins 1, 2, or 3"),
        ({"bost_list": [False, False], "completion_pulse_pins": [1]}, "cannot be mixed"),
    ],
)
def test_trigger_list_canonical_validation_rejects_before_opener(parameters, message) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True

    request = TriggerRequest(
        command="trigger-list",
        runtime=RuntimeOptions(resource="USB0::FAKE::INSTR"),
        parameters={
            "channel": 1, "source": "immediate", "wait_complete": True,
            "voltage_list": [0.0, 1.0], "current_list": [0.05, 0.05], "dwell_list": [0.01, 0.01],
            **parameters,
        },
    )

    with pytest.raises(CoreValidationError, match=message):
        run_core_command(request, opener=opener)
    assert opened is False


@pytest.mark.parametrize(
    ("command", "parameters", "message"),
    [
        ("trigger-step", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-list", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-step", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "bus"}, "arm-only requires leave_trigger_configured=true"),
        (
            "trigger-list",
            {"source": "immediate"},
            "started without wait_complete=true requires leave_trigger_configured=true",
        ),
        (
            "trigger-list",
            {"source": "bus", "fire": True},
            "started without wait_complete=true requires leave_trigger_configured=true",
        ),
    ],
)
def test_invalid_trigger_controls_rejected_before_opener(command: str, parameters: dict[str, object], message: str) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("opener must not run")

    request = TriggerRequest(
        command=command,
        runtime=RuntimeOptions(resource="USB0::FAKE::INSTR"),
        parameters={"channel": 1, **parameters},
    )

    with pytest.raises(CoreValidationError, match=message):
        run_core_command(request, opener=opener)

    assert opened is False


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("trigger-step", {"source": "bus"}),
        ("trigger-step", {"source": "immediate", "wait_complete": True}),
        ("trigger-list", {"source": "bus", "leave_trigger_configured": True}),
        ("trigger-list", {"source": "bus", "fire": True, "wait_complete": True}),
        ("trigger-list", {"source": "bus", "fire": True, "leave_trigger_configured": True}),
        ("trigger-list", {"source": "immediate", "wait_complete": True}),
        ("trigger-list", {"source": "immediate", "leave_trigger_configured": True}),
    ],
)
def test_valid_trigger_controls_are_accepted(command: str, parameters: dict[str, object]) -> None:
    request = TriggerRequest(
        command=command,
        parameters=parameters,
    )

    validate_trigger_request(request)


def test_trigger_step_and_list_previews_switch_through_fix() -> None:
    step = trigger_step_scpi(channel=1, source="bus", voltage=1.0, current=0.1)
    list_commands = trigger_list_scpi(
        channel=1,
        source="bus",
        voltages=(0.0, 1.0),
        currents=(0.1, 0.1),
        dwell=(0.01, 0.01),
    )

    assert step.index("CURR:MODE FIX,(@1)") < step.index("CURR:MODE STEP,(@1)")
    assert step.index("VOLT:MODE FIX,(@1)") < step.index("VOLT:MODE STEP,(@1)")
    assert list_commands.index("CURR:MODE FIX,(@1)") < list_commands.index("CURR:MODE LIST,(@1)")
    assert list_commands.index("VOLT:MODE FIX,(@1)") < list_commands.index("VOLT:MODE LIST,(@1)")


def test_trigger_fire_wait_complete_requires_abort_target_before_opener() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("opener must not run")

    request = TriggerRequest(
        command="trigger-fire",
        runtime=RuntimeOptions(resource="USB0::FAKE::INSTR"),
        parameters={"wait_complete": True},
    )

    with pytest.raises(CoreValidationError, match="abort target"):
        run_core_command(request, opener=opener)

    assert opened is False


def test_trigger_fire_result_can_report_no_abort_target() -> None:
    result = trigger_result_payload(mode="fire", native=True, channel=None, fired=True)

    assert result["channel"] is None
    assert result["fired"] is True


def test_trigger_fire_ignored_error_preserves_error_and_adds_hint() -> None:
    class IgnoredTriggerPowerSupply:
        def read_error_queue(self, max_errors):
            return ['-211,"Trigger ignored"'], 1

    with pytest.raises(CoreExecutionError) as exc_info:
        _raise_on_instrument_errors(IgnoredTriggerPowerSupply(), "trigger-fire")

    message = str(exc_info.value)
    assert '-211,"Trigger ignored"' in message
    assert "no armed BUS trigger" in message


class NeverCompletePowerSupply:
    def __init__(self) -> None:
        self.prepared = False

    def prepare_operation_complete_wait(self) -> None:
        self.prepared = True

    def operation_complete_event(self) -> bool:
        return False


def test_trigger_wait_timeout_cleanup_signal() -> None:
    psu = NeverCompletePowerSupply()

    with pytest.raises(TriggerWaitTimeout):
        wait_for_trigger_completion(psu, timeout_ms=0, poll_ms=50, sleep=lambda seconds: None)

    assert psu.prepared is True
