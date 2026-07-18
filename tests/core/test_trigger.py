import pytest

from powers_tool_core import trigger as trigger_module
from powers_tool_core.command_runner import run_core_command
from powers_tool_core.core import CoreExecutionError, CoreValidationError, RuntimeOptions, TriggerInterrupted, TriggerRequest, TriggerWaitTimeout
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.trigger import (
    _raise_on_instrument_errors,
    run_post_action_completion_pulse,
    trigger_list_scpi,
    trigger_plan,
    trigger_pulse_scpi,
    trigger_result_payload,
    trigger_step_scpi,
    validate_real_trigger_source,
    validate_trigger_request,
    wait_for_trigger_completion,
)


class TriggerSession:
    def query(self, command: str) -> str:
        assert command == "*IDN?"
        return "KEYSIGHT,E36312A,SERIAL0000,1.0"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingPulsePowerSupply(E36312APowerSupply):
    def __init__(self) -> None:
        self.events: list[str] = []
        self.fail_pulse = False
        self.fail_fire = False
        self.fail_abort = False
        self.fail_readback = False
        self.fail_restore_channel: int | None = None
        self.interrupt_restore_channel: int | None = None
        self.queue_errors: list[str] = []

    def trigger_snapshot(self, channel: int):
        self.events.append(f"snapshot-{channel}")
        return type("Snapshot", (), {"channel": channel})()

    def programmed_voltage(self, *, channel: int) -> float:
        if self.fail_readback:
            raise RuntimeError("readback failed")
        return 1.0

    def programmed_current(self, *, channel: int) -> float:
        return 0.05

    def abort_output_trigger(self, channel: int) -> None:
        self.events.append(f"abort-{channel}")
        if self.fail_abort:
            raise RuntimeError("abort failed")

    def configure_trigger_output_pins(self, pins, polarity) -> None:
        self.events.append("configure-pins")

    def enable_trigger_output_bus(self, enabled=True) -> None:
        self.events.append("configure-bus")

    def set_triggered_current(self, *, channel: int, current: float) -> None:
        self.events.append("configure-current")

    def set_triggered_voltage(self, *, channel: int, voltage: float) -> None:
        self.events.append("configure-voltage")

    def set_trigger_modes(self, *, channel: int, current_mode: str, voltage_mode: str) -> None:
        self.events.append("configure-modes")

    def configure_output_trigger_source_bus(self, channel: int) -> None:
        self.events.append("configure-source")

    def initiate_output_trigger(self, channel: int) -> None:
        self.events.append("initiate")

    def trigger_pulse(self, *, channel: int) -> None:
        self.events.append("pulse")
        if self.fail_pulse:
            raise RuntimeError("pulse failed")

    def fire_bus_trigger(self) -> None:
        self.events.append("fire")
        if self.fail_fire:
            raise RuntimeError("fire failed")

    def _restore_trigger_channel_snapshot(self, snapshot) -> None:
        self.events.append(f"restore-{snapshot.channel}")
        if snapshot.channel == self.fail_restore_channel:
            raise RuntimeError("restore failed")
        if snapshot.channel == self.interrupt_restore_channel:
            raise KeyboardInterrupt("restore interrupted")

    def _restore_trigger_global_snapshot(self, snapshot) -> None:
        self.events.append("restore-global")

    def restore_trigger_snapshot(self, snapshot) -> None:
        self.events.append(f"restore-single-{snapshot.channel}")
        if snapshot.channel == self.fail_restore_channel:
            raise RuntimeError("restore failed")

    def read_error_queue(self, max_errors: int):
        self.events.append("error-queue")
        return list(self.queue_errors), 1

    def output_off(self, *, channel: int) -> None:
        raise AssertionError("production trigger-pulse must not safe-off outputs")


def _pulse_request() -> TriggerRequest:
    return TriggerRequest(
        command="trigger-pulse",
        runtime=RuntimeOptions(
            resource="USB0::SIM::E36312A::INSTR",
            simulate=True,
        ),
        parameters={"pin": 1, "channel": 1, "polarity": "positive"},
    )


def _run_recording_pulse(monkeypatch, power_supply: RecordingPulsePowerSupply):
    monkeypatch.setattr(trigger_module, "create_power_supply", lambda instrument, idn: power_supply)
    return trigger_module.run_trigger(
        _pulse_request(),
        opener=lambda *args, **kwargs: TriggerSession(),
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


@pytest.mark.parametrize(
    ("runtime", "message"),
    [
        (
            RuntimeOptions(dry_run=True, planning_model_id="keysight-edu36311a"),
            "trigger/native LIST workflows are disabled",
        ),
        (
            RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
            "completion-pulse workflows are disabled",
        ),
        (
            RuntimeOptions(simulate=True, resource="USB0::SIM::EDU36311A::INSTR"),
            "trigger/native LIST workflows are disabled",
        ),
        (
            RuntimeOptions(simulate=True, resource="ASRL1::SIM::E3646A::INSTR"),
            "completion-pulse workflows are disabled",
        ),
    ],
)
def test_standalone_trigger_pulse_no_hardware_gate_remains_fail_closed(
    runtime: RuntimeOptions,
    message: str,
) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("trigger planning must not open VISA")

    with pytest.raises(CoreValidationError, match=message):
        run_core_command(
            TriggerRequest(
                command="trigger-pulse",
                runtime=runtime,
                parameters={"channel": 1, "pins": [1], "polarity": "positive"},
            ),
            opener=opener,
        )

    assert opened is False


def test_trigger_pulse_snapshots_before_mutation_and_restores_all_channels(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()

    result = _run_recording_pulse(monkeypatch, power_supply)

    assert result["restored"] is True
    assert power_supply.events[:6] == [
        "snapshot-1",
        "snapshot-2",
        "snapshot-3",
        "abort-1",
        "abort-2",
        "abort-3",
    ]
    assert power_supply.events[-5:] == [
        "restore-1",
        "restore-2",
        "restore-3",
        "restore-global",
        "error-queue",
    ]


def test_trigger_pulse_command_failure_still_restores(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_pulse = True

    with pytest.raises(RuntimeError, match="pulse failed"):
        _run_recording_pulse(monkeypatch, power_supply)

    assert power_supply.events[-5:] == [
        "restore-1",
        "restore-2",
        "restore-3",
        "restore-global",
        "error-queue",
    ]


def test_trigger_pulse_exception_after_snapshot_still_restores(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_readback = True

    with pytest.raises(RuntimeError, match="readback failed"):
        _run_recording_pulse(monkeypatch, power_supply)

    assert power_supply.events[-5:] == [
        "restore-1",
        "restore-2",
        "restore-3",
        "restore-global",
        "error-queue",
    ]


def test_trigger_pulse_restore_failure_forces_command_failure(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_restore_channel = 2

    with pytest.raises(CoreExecutionError, match="channel 2"):
        _run_recording_pulse(monkeypatch, power_supply)

    assert "restore-3" in power_supply.events
    assert "restore-global" in power_supply.events


def test_trigger_pulse_restore_interruption_remains_best_effort(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.interrupt_restore_channel = 2

    with pytest.raises(CoreExecutionError, match="channel 2"):
        _run_recording_pulse(monkeypatch, power_supply)

    assert "restore-3" in power_supply.events
    assert "restore-global" in power_supply.events


def test_trigger_pulse_post_restore_error_queue_forces_command_failure(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.queue_errors = ['-200,"Execution error"']

    with pytest.raises(CoreExecutionError, match="instrument errors"):
        _run_recording_pulse(monkeypatch, power_supply)


def test_trigger_pulse_operation_and_restore_failures_are_aggregated(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_pulse = True
    power_supply.fail_restore_channel = 2

    with pytest.raises(CoreExecutionError) as exc_info:
        _run_recording_pulse(monkeypatch, power_supply)

    assert "operation failed: pulse failed" in str(exc_info.value)
    assert "restore failed: channel 2: restore failed" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "pulse failed"


def test_trigger_pulse_operation_and_error_queue_failures_are_aggregated(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_pulse = True
    power_supply.queue_errors = ['-200,"Execution error"']

    with pytest.raises(CoreExecutionError) as exc_info:
        _run_recording_pulse(monkeypatch, power_supply)

    assert "operation failed: pulse failed" in str(exc_info.value)
    assert "instrument errors" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "pulse failed"


def test_completion_pulse_result_records_terminal_action_state() -> None:
    power_supply = RecordingPulsePowerSupply()

    result = run_post_action_completion_pulse(
        power_supply,
        channel=1,
        pins=(1,),
        polarity="positive",
    )

    assert result["requested"] is True
    assert result["attempted"] is True
    assert result["fired"] is True
    assert result["completed"] is True
    assert result["restored"] is True
    assert result["restore_errors"] == []
    assert result["post_pulse_errors"] == []


def test_completion_pulse_command_failure_reports_not_fired() -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_fire = True

    with pytest.raises(CoreExecutionError) as raised:
        run_post_action_completion_pulse(power_supply, channel=1, pins=(1,), polarity="positive")

    assert raised.value.trigger["attempted"] is True
    assert raised.value.trigger["fired"] is False
    assert raised.value.trigger["completed"] is False
    assert raised.value.trigger["restored"] is True


def test_completion_pulse_restore_failure_does_not_hide_fired_state() -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_restore_channel = 1

    with pytest.raises(CoreExecutionError) as raised:
        run_post_action_completion_pulse(power_supply, channel=1, pins=(1,), polarity="positive")

    assert raised.value.trigger["fired"] is True
    assert raised.value.trigger["completed"] is True
    assert raised.value.trigger["restored"] is False
    assert raised.value.trigger["restore_errors"] == ["restore failed"]


def test_completion_pulse_post_error_is_reported_after_firing() -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.queue_errors = ['-200,"Execution error"']

    with pytest.raises(CoreExecutionError) as raised:
        run_post_action_completion_pulse(power_supply, channel=1, pins=(1,), polarity="positive")

    assert raised.value.trigger["fired"] is True
    assert raised.value.trigger["restored"] is True
    assert raised.value.trigger["post_pulse_errors"] == ['-200,"Execution error"']


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
        runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
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


@pytest.mark.parametrize("failure", [TriggerWaitTimeout("timeout"), TriggerInterrupted("interrupted")])
def test_trigger_fire_wait_failure_aborts_channel(monkeypatch, failure) -> None:
    power_supply = RecordingPulsePowerSupply()
    monkeypatch.setattr(trigger_module, "create_power_supply", lambda instrument, idn: power_supply)
    monkeypatch.setattr(trigger_module, "wait_for_trigger_completion", lambda *args, **kwargs: (_ for _ in ()).throw(failure))
    request = TriggerRequest(
        command="trigger-fire",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True),
        parameters={"channel": 1, "wait_complete": True},
    )

    with pytest.raises(type(failure)) as exc_info:
        trigger_module.run_trigger(request, opener=lambda *args, **kwargs: TriggerSession())

    assert power_supply.events == ["fire", "abort-1"]
    assert exc_info.value.trigger["fired"] is True
    assert exc_info.value.trigger["completed"] is False
    assert exc_info.value.trigger["abort_attempted"] is True
    assert exc_info.value.trigger["abort_succeeded"] is True
    assert exc_info.value.trigger["abort_errors"] == []


def test_trigger_fire_timeout_preserves_abort_failure_diagnostics(monkeypatch) -> None:
    power_supply = RecordingPulsePowerSupply()
    power_supply.fail_abort = True
    monkeypatch.setattr(trigger_module, "create_power_supply", lambda instrument, idn: power_supply)
    monkeypatch.setattr(
        trigger_module,
        "wait_for_trigger_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(TriggerWaitTimeout("timeout")),
    )
    request = TriggerRequest(
        command="trigger-fire",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True),
        parameters={"channel": 1, "wait_complete": True},
    )

    with pytest.raises(TriggerWaitTimeout) as exc_info:
        trigger_module.run_trigger(request, opener=lambda *args, **kwargs: TriggerSession())

    assert exc_info.value.trigger["abort_attempted"] is True
    assert exc_info.value.trigger["abort_succeeded"] is False
    assert exc_info.value.trigger["abort_errors"] == ["abort failed"]


@pytest.mark.parametrize(
    ("configure", "message", "fired"),
    [
        (lambda power_supply: setattr(power_supply, "fail_fire", True), "fire failed", False),
        (lambda power_supply: power_supply.queue_errors.append('-200,"Execution error"'), "instrument errors", True),
    ],
)
def test_trigger_fire_general_failure_aborts_and_preserves_cause(monkeypatch, configure, message, fired) -> None:
    power_supply = RecordingPulsePowerSupply()
    configure(power_supply)
    monkeypatch.setattr(trigger_module, "create_power_supply", lambda instrument, idn: power_supply)
    request = TriggerRequest(
        command="trigger-fire",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True),
        parameters={"channel": 1},
    )

    with pytest.raises(CoreExecutionError) as exc_info:
        trigger_module.run_trigger(request, opener=lambda *args, **kwargs: TriggerSession())

    assert message in str(exc_info.value.__cause__)
    assert exc_info.value.trigger["fired"] is fired
    assert exc_info.value.trigger["completed"] is False
    assert exc_info.value.trigger["abort_succeeded"] is True
    assert power_supply.events[-1] == "abort-1"


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
