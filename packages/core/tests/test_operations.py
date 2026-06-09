import pytest

from keysight_power_core.core import CommandCancelled, ConfirmationRequiredError, CoreValidationError, OperationRequest, RuntimeOptions
from keysight_power_core.operations import output_plan, run_operation


class FakeSession:
    def __init__(self, idn: str = "KEYSIGHT,E36312A,SERIAL0000,1.0", responses: dict[str, str] | None = None) -> None:
        self.idn = idn
        self.responses = responses or {}
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        responses = {
            "*IDN?": self.idn,
            "SYST:ERR?": '0,"No error"',
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.1",
            "OUTP? (@1)": "0",
            "MEAS:VOLT? (@1)": "1.0",
            "MEAS:CURR? (@1)": "0.1",
        }
        responses.update(self.responses)
        return responses.get(command, '0,"No error"')


def request(command: str, **parameters):
    return OperationRequest(
        command=command,
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True),
        parameters={
            "channel": 1,
            "voltage": 1.0,
            "current": 0.1,
            "duration_ms": 1,
            "settle_ms": 0,
            "verify_after_write": False,
            **parameters,
        },
    )


def test_operations_dry_run_does_not_open_visa() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_operation(request("set"), opener=opener)

    assert opened is False
    assert data["operation"] == {"name": "set"}
    assert [step["action"] for step in data["steps"]] == ["set_current_limit", "set_voltage"]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("set", ["CURR 0.1,(@1)", "VOLT 1,(@1)"]),
        ("apply", ["CURR 0.1,(@1)", "VOLT 1,(@1)", "OUTP ON,(@1)"]),
        ("output-off", ["OUTP OFF,(@1)"]),
        ("safe-off", ["OUTP OFF,(@1)"]),
        ("smoke-output", ["CURR 0.1,(@1)", "VOLT 1,(@1)", "OUTP ON,(@1)", "OUTP OFF,(@1)"]),
    ],
)
def test_output_real_scpi_order(command: str, expected: list[str]) -> None:
    session = FakeSession()
    params = request(command, no_output=False).parameters
    core_request = OperationRequest(
        command=command,
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    write_positions = [session.writes.index(command_text) for command_text in expected]
    assert write_positions == sorted(write_positions)


def test_cycle_output_cancellation_preserves_output_off_cleanup() -> None:
    session = FakeSession()
    cancelled = False

    def sleep(_seconds: float) -> None:
        nonlocal cancelled
        cancelled = True

    core_request = OperationRequest(
        command="cycle-output",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=request("cycle-output", duration_ms=500).parameters,
    )

    with pytest.raises(CommandCancelled):
        run_operation(
            core_request,
            opener=lambda *args, **kwargs: session,
            sleep=sleep,
            stop_requested=lambda: cancelled,
        )

    assert session.writes == ["OUTP ON,(@1)", "OUTP OFF,(@1)"]


def test_real_output_affecting_operation_requires_confirm_above_config_threshold(tmp_path) -> None:
    safety_config = tmp_path / "safety.toml"
    safety_config.write_text(
        "[safety]\nconfirm_above_voltage = 0.5\nconfirm_above_current = 0.05\n",
        encoding="utf-8",
    )
    core_request = OperationRequest(
        command="output-on",
        runtime=RuntimeOptions(
            resource="USB0::SIM::E36312A::INSTR",
            safety_config=str(safety_config),
            confirm=False,
        ),
        parameters=request("set").parameters,
    )

    with pytest.raises(ConfirmationRequiredError):
        run_operation(core_request, opener=lambda *args, **kwargs: FakeSession())


def test_output_plan_apply_shape_unchanged() -> None:
    plan = output_plan(request("apply", channel="all", no_output=False))

    assert plan["operation"] == {"name": "apply"}
    assert plan["target"]["channel"] == "all"
    assert [step["parameters"]["channel"] for step in plan["steps"] if "channel" in step["parameters"]] == [
        1,
        1,
        2,
        2,
        3,
        3,
        1,
        2,
        3,
    ]


def test_output_plan_all_channel_output_commands_expand_once() -> None:
    assert [step["action"] for step in output_plan(request("output-on", channel="all"))["steps"]] == [
        "output_on",
        "output_on",
        "output_on",
    ]
    assert [step["action"] for step in output_plan(request("output-off", channel="all"))["steps"]] == [
        "output_off",
        "output_off",
        "output_off",
    ]
    assert [step["action"] for step in output_plan(request("output-state", channel="all"))["steps"]] == [
        "output_state",
        "output_state",
        "output_state",
    ]
    cycle_steps = output_plan(request("cycle-output", channel="all", duration_ms=250))["steps"]
    assert [step["action"] for step in cycle_steps] == [
        "output_on",
        "output_on",
        "output_on",
        "sleep",
        "output_off",
        "output_off",
        "output_off",
    ]
    assert cycle_steps[3]["parameters"] == {"duration_ms": 250}


def test_output_on_all_checks_readbacks_before_writes() -> None:
    session = FakeSession(
        responses={
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.1",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.2",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.3",
        }
    )
    core_request = OperationRequest(
        command="output-on",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=request("output-on", channel="all").parameters,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert session.queries[:7] == [
        "*IDN?",
        "VOLT? (@1)",
        "CURR? (@1)",
        "VOLT? (@2)",
        "CURR? (@2)",
        "VOLT? (@3)",
        "CURR? (@3)",
    ]
    assert session.writes == ["OUTP ON,(@1)", "OUTP ON,(@2)", "OUTP ON,(@3)"]
    assert data["channel"] == "all"
    assert [output["channel"] for output in data["outputs"]] == [1, 2, 3]


def test_cycle_output_all_turns_on_all_then_sleeps_once_then_off() -> None:
    session = FakeSession()
    sleeps: list[float] = []
    core_request = OperationRequest(
        command="cycle-output",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=request("cycle-output", channel="all", duration_ms=250).parameters,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=sleeps.append)

    assert session.writes == [
        "OUTP ON,(@1)",
        "OUTP ON,(@2)",
        "OUTP ON,(@3)",
        "OUTP OFF,(@1)",
        "OUTP OFF,(@2)",
        "OUTP OFF,(@3)",
    ]
    assert sleeps == [0.25]
    assert data["outputs"] == [
        {"channel": 1, "cycled": True, "final_enabled": False},
        {"channel": 2, "cycled": True, "final_enabled": False},
        {"channel": 3, "cycled": True, "final_enabled": False},
    ]


def test_ramp_real_native_completion_uses_list_before_software_voltage_writes() -> None:
    session = FakeSession(responses=_trigger_snapshot_responses())
    params = request(
        "ramp",
        start_voltage=0.0,
        stop_voltage=1.0,
        step_voltage=0.5,
        current=0.05,
        delay_ms=0,
        completion_pulse_pins=(1,),
        completion_pulse_mode="native",
        completion_pulse_dwell_ms=10,
        completion_pulse_polarity="positive",
        leave_trigger_configured=False,
        poll_ms=200,
    ).parameters
    core_request = OperationRequest(
        command="ramp",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert "LIST:VOLT 0,0.5,1,(@1)" in session.writes
    assert "LIST:TOUT:EOST 0,0,1,(@1)" in session.writes
    assert "VOLT 0,(@1)" not in session.writes
    assert data["trigger"]["mode"] == "ramp"
    assert data["trigger"]["native"] is True


def test_ramp_real_native_completion_over_100_steps_rejects_before_writes() -> None:
    session = FakeSession()
    params = request(
        "ramp",
        start_voltage=0.0,
        stop_voltage=1.0,
        step_voltage=0.005,
        current=0.05,
        completion_pulse_pins=(1,),
        completion_pulse_mode="native",
    ).parameters
    core_request = OperationRequest(
        command="ramp",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    with pytest.raises(CoreValidationError, match="native ramp LIST supports at most 100 steps"):
        run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert session.writes == []


def _trigger_snapshot_responses() -> dict[str, str]:
    return {
        "DIG:PIN1:FUNC?": "TOUT",
        "DIG:PIN1:POL?": "POS",
        "DIG:PIN2:FUNC?": "TOUT",
        "DIG:PIN2:POL?": "POS",
        "DIG:PIN3:FUNC?": "DIO",
        "DIG:PIN3:POL?": "POS",
        "DIG:TOUT:BUS?": "0",
        "TRIG:SOUR? (@1)": "BUS",
        "TRIG:DEL? (@1)": "+0.00000000E+00",
        "VOLT:MODE? (@1)": "FIX",
        "CURR:MODE? (@1)": "FIX",
        "VOLT:TRIG? (@1)": "+0.00000000E+00",
        "CURR:TRIG? (@1)": "+2.00000000E-03",
        "LIST:VOLT? (@1)": "+0.00000000E+00",
        "LIST:CURR? (@1)": "+2.00000000E-03",
        "LIST:DWEL? (@1)": "+1.00000000E-02",
        "LIST:TOUT:BOST? (@1)": "0",
        "LIST:TOUT:EOST? (@1)": "0",
        "LIST:COUN? (@1)": "+1",
        "LIST:STEP? (@1)": "AUTO",
        "LIST:TERM:LAST? (@1)": "0",
        "*ESR?": "+1",
    }
