import pytest

from keysight_power_core.core import CoreValidationError, RuntimeOptions, TriggerRequest, TriggerWaitTimeout
from keysight_power_core.trigger import (
    trigger_list_scpi,
    trigger_plan,
    trigger_pulse_scpi,
    trigger_step_scpi,
    validate_real_trigger_source,
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
