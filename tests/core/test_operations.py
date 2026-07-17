import pytest

from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    UnsupportedModelError,
)
from powers_tool_core.operations import output_plan, run_operation
from powers_tool_core.support_policy import LiveSupportPolicyError


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
            "VOLT? (@2)": "1.0",
            "CURR? (@2)": "0.1",
            "VOLT? (@3)": "1.0",
            "CURR? (@3)": "0.1",
            "OUTP? (@1)": "0",
            "MEAS:VOLT? (@1)": "1.0",
            "MEAS:CURR? (@1)": "0.1",
        }
        responses.update(self.responses)
        return responses.get(command, '0,"No error"')


class OutputStateSession(FakeSession):
    def __init__(self, *, idn: str, output_enabled: bool) -> None:
        super().__init__(idn=idn)
        self.output_enabled = output_enabled
        self.events: list[str] = []

    def write(self, command: str) -> None:
        self.events.append(f"W:{command}")
        super().write(command)
        if command.startswith("OUTP ON"):
            self.output_enabled = True
        elif command.startswith("OUTP OFF"):
            self.output_enabled = False

    def query(self, command: str) -> str:
        self.events.append(f"Q:{command}")
        if command.startswith("OUTP?"):
            self.queries.append(command)
            return "1" if self.output_enabled else "0"
        return super().query(command)


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


def general_pulse_parameters(command: str, *, no_output: bool = False) -> dict:
    parameters = {
        "channel": 1,
        "completion_pulse_pins": (1,),
        "completion_pulse_polarity": "positive",
        "settle_ms": 10,
        "verify_after_write": True,
        "setpoint_voltage_tolerance": 0.001,
        "setpoint_current_tolerance": 0.001,
    }
    if command == "set":
        parameters.update(voltage=1.0, current=0.1)
    elif command == "apply":
        parameters.update(voltage=1.0, current=0.1, no_output=no_output)
    elif command == "cycle-output":
        parameters["duration_ms"] = 10
    elif command == "ramp":
        parameters.update(
            start_voltage=0.0,
            stop_voltage=1.0,
            step_voltage=0.5,
            current=0.1,
            delay_ms=10,
            completion_pulse_timing="segment",
        )
    elif command == "smoke-output":
        parameters.update(voltage=1.0, current=0.1, duration_ms=10)
    return parameters


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
    "command",
    [
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "smoke-output",
    ],
)
@pytest.mark.parametrize(
    "planning_model_id",
    ["keysight-edu36311a", "keysight-e3646a"],
)
def test_general_completion_pulse_dry_run_rejects_non_e36312a_without_opening(
    command: str,
    planning_model_id: str,
) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("dry-run must not open VISA")

    with pytest.raises(CoreValidationError, match="require planning_model_id 'keysight-e36312a'"):
        run_operation(
            OperationRequest(
                command=command,
                runtime=RuntimeOptions(
                    dry_run=True,
                    planning_model_id=planning_model_id,
                ),
                parameters=general_pulse_parameters(command),
            ),
            opener=opener,
        )

    assert opened is False


@pytest.mark.parametrize(
    ("runtime_kwargs", "message"),
    [
        (
            {"simulate": True, "resource": "USB0::SIM::EDU36311A::INSTR"},
            "require planning_model_id 'keysight-e36312a'",
        ),
        (
            {"simulate": True, "resource": "ASRL1::SIM::E3646A::INSTR"},
            "require planning_model_id 'keysight-e36312a'",
        ),
        (
            {"dry_run": True, "planning_profile_id": "generic-scpi"},
            "received 'generic-scpi'",
        ),
        (
            {"dry_run": True},
            "planning require planning_model_id, planning_profile_id",
        ),
        (
            {"dry_run": True, "planning_model_id": "unknown"},
            "invalid planning_model_id",
        ),
    ],
)
def test_general_completion_pulse_no_hardware_planning_fails_closed(
    runtime_kwargs: dict,
    message: str,
) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("no-hardware planning must not open VISA")

    with pytest.raises(CoreValidationError, match=message):
        run_operation(
            OperationRequest(
                command="apply",
                runtime=RuntimeOptions(**runtime_kwargs),
                parameters=general_pulse_parameters("apply"),
            ),
            opener=opener,
        )

    assert opened is False


@pytest.mark.parametrize(
    "command",
    [
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "smoke-output",
    ],
)
def test_general_completion_pulse_e36312a_plan_shape_is_unchanged(command: str) -> None:
    pulse_parameters = general_pulse_parameters(command)
    plain_parameters = {
        key: value
        for key, value in pulse_parameters.items()
        if not key.startswith("completion_pulse_")
    }
    runtime = RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a")

    pulse_plan = run_operation(
        OperationRequest(command=command, runtime=runtime, parameters=pulse_parameters)
    )
    plain_plan = run_operation(
        OperationRequest(command=command, runtime=runtime, parameters=plain_parameters)
    )

    assert pulse_plan == plain_plan


@pytest.mark.parametrize(
    "planning_model_id",
    ["keysight-edu36311a", "keysight-e3646a"],
)
def test_general_no_pulse_plan_for_other_models_is_unchanged(
    planning_model_id: str,
) -> None:
    parameters = general_pulse_parameters("apply")
    parameters.pop("completion_pulse_pins")
    parameters.pop("completion_pulse_polarity")

    plan = run_operation(
        OperationRequest(
            command="apply",
            runtime=RuntimeOptions(
                dry_run=True,
                planning_model_id=planning_model_id,
            ),
            parameters=parameters,
        )
    )

    assert plan["hardware_touched"] is False
    actions = [step["action"] for step in plan["steps"]]
    assert "output_on" in actions
    assert "completion_pulse" not in actions


def test_output_plan_set_accepts_voltage_only() -> None:
    params = request("set").parameters
    params.pop("current")

    plan = output_plan(OperationRequest(command="set", runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True), parameters=params))

    assert [step["action"] for step in plan["steps"]] == ["set_voltage"]
    assert plan["steps"][0]["parameters"] == {"channel": 1, "voltage": 1.0}


def test_output_plan_set_accepts_current_only() -> None:
    params = request("set").parameters
    params.pop("voltage")

    plan = output_plan(OperationRequest(command="set", runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True), parameters=params))

    assert [step["action"] for step in plan["steps"]] == ["set_current_limit"]
    assert plan["steps"][0]["parameters"] == {"channel": 1, "current": 0.1}


def test_output_plan_set_requires_one_setpoint() -> None:
    params = request("set").parameters
    params.pop("voltage")
    params.pop("current")

    with pytest.raises(CoreValidationError, match="set requires voltage, current, or both"):
        output_plan(OperationRequest(command="set", runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True), parameters=params))


def test_e3646a_output_state_all_is_read_only_real_operation() -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        responses={
            "INST:NSEL?": "1",
            "OUTP?": "0",
        },
    )
    core_request = OperationRequest(
        command="output-state",
        runtime=RuntimeOptions(resource="ASRL1::SIM::E3646A::INSTR"),
        parameters={"channel": "all"},
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session)

    assert data["channel"] == "all"
    assert data["outputs"] == [{"channel": 1, "enabled": False}, {"channel": 2, "enabled": False}]
    assert "output_enabled" not in data
    assert session.writes == ["INST:NSEL 1", "INST:NSEL 1", "INST:NSEL 2", "INST:NSEL 1"]


def test_e36312a_output_state_single_returns_only_output_enabled() -> None:
    session = FakeSession(responses={"OUTP? (@2)": "1"})
    core_request = OperationRequest(
        command="output-state",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR"),
        parameters={"channel": 2},
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session)

    assert data["channel"] == 2
    assert data["output_enabled"] is True
    assert "outputs" not in data
    assert session.queries == ["*IDN?", "OUTP? (@2)"]
    assert session.writes == []


def test_real_set_voltage_only_writes_only_voltage() -> None:
    session = FakeSession()
    params = request("set").parameters
    params.pop("current")
    core_request = OperationRequest(
        command="set",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert "CURR 0.1,(@1)" not in session.writes
    assert session.writes == ["VOLT 1,(@1)"]
    assert data["updated_setpoints"] == {"voltage": 1.0}
    assert "current" not in data


def test_real_set_current_only_writes_only_current() -> None:
    session = FakeSession()
    params = request("set").parameters
    params.pop("voltage")
    core_request = OperationRequest(
        command="set",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert session.writes == ["CURR 0.1,(@1)"]
    assert data["updated_setpoints"] == {"current": 0.1}
    assert "voltage" not in data


def test_real_set_verify_after_write_checks_only_written_field() -> None:
    session = FakeSession(responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "999"})
    params = request("set", verify_after_write=True).parameters
    params.pop("current")
    core_request = OperationRequest(
        command="set",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert "CURR? (@1)" not in session.queries
    assert data["verification"]["checks"] == [
        {
            "channel": 1,
            "expected": {"voltage": 1.0},
            "actual": {"voltage": 1.0},
            "tolerances": {"voltage": 0.001, "current": 0.001},
        }
    ]


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


@pytest.mark.parametrize(
    ("model_id", "idn", "resource", "error_type", "message"),
    [
        (
            "keysight-edu36311a",
            "KEYSIGHT,EDU36311A,SERIAL0000,1.0",
            "USB0::FAKE::EDU36311A::INSTR",
            CoreValidationError,
            "EDU36311A real execution does not support completion-pulse options",
        ),
        (
            "keysight-e3646a",
            "KEYSIGHT,E3646A,SERIAL0000,1.0",
            "ASRL1::INSTR",
            UnsupportedModelError,
            "completion-pulse options require E36312A",
        ),
    ],
)
@pytest.mark.parametrize(
    "command",
    ["set", "apply", "output-on", "cycle-output", "smoke-output"],
)
def test_unsupported_general_completion_pulse_rejects_after_idn_before_command_io(
    model_id: str,
    idn: str,
    resource: str,
    error_type: type[Exception],
    message: str,
    command: str,
) -> None:
    session = FakeSession(idn=idn)
    sleeps: list[float] = []
    core_request = OperationRequest(
        command=command,
        runtime=RuntimeOptions(resource=resource, confirm=True),
        parameters=general_pulse_parameters(command),
    )

    with pytest.raises(error_type, match=message):
        run_operation(
            core_request,
            opener=lambda *args, **kwargs: session,
            sleep=sleeps.append,
        )

    assert model_id in {"keysight-edu36311a", "keysight-e3646a"}
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert sleeps == []
    assert session.closed is True


@pytest.mark.parametrize(
    ("idn", "resource", "expected_model_id", "error_type", "message"),
    [
        (
            "KEYSIGHT,EDU36311A,SERIAL0000,1.0",
            "USB0::FAKE::EDU36311A::INSTR",
            "keysight-e36312a",
            CoreValidationError,
            "Expected model_id keysight-e36312a",
        ),
        (
            "KEYSIGHT,UNKNOWN,SERIAL0000,1.0",
            "USB0::FAKE::UNKNOWN::INSTR",
            None,
            LiveSupportPolicyError,
            "unknown live support-policy model_id",
        ),
        (
            "KEYSIGHT,E36312A,SERIAL0000,1.0",
            "ASRL1::INSTR",
            None,
            LiveSupportPolicyError,
            "no exact transport/backend scope is registered",
        ),
    ],
)
def test_general_completion_pulse_identity_and_policy_gates_remain_idn_only(
    idn: str,
    resource: str,
    expected_model_id: str | None,
    error_type: type[Exception],
    message: str,
) -> None:
    session = FakeSession(idn=idn)

    with pytest.raises(error_type, match=message):
        run_operation(
            OperationRequest(
                command="apply",
                runtime=RuntimeOptions(
                    resource=resource,
                    expected_model_id=expected_model_id,
                    confirm=True,
                ),
                parameters=general_pulse_parameters("apply"),
            ),
            opener=lambda *args, **kwargs: session,
        )

    assert session.queries == ["*IDN?"]
    assert session.writes == []


@pytest.mark.parametrize(
    ("idn", "resource", "error_type", "message"),
    [
        (
            "KEYSIGHT,EDU36311A,SERIAL0000,1.0",
            "USB0::FAKE::EDU36311A::INSTR",
            CoreValidationError,
            "EDU36311A real execution does not support completion-pulse options",
        ),
        (
            "KEYSIGHT,E3646A,SERIAL0000,1.0",
            "ASRL1::INSTR",
            UnsupportedModelError,
            "completion-pulse options require E36312A",
        ),
    ],
)
def test_apply_no_output_completion_pulse_rejects_before_setpoint_write(
    idn: str,
    resource: str,
    error_type: type[Exception],
    message: str,
) -> None:
    session = FakeSession(idn=idn)

    with pytest.raises(error_type, match=message):
        run_operation(
            OperationRequest(
                command="apply",
                runtime=RuntimeOptions(resource=resource, confirm=True),
                parameters=general_pulse_parameters("apply", no_output=True),
            ),
            opener=lambda *args, **kwargs: session,
        )

    assert session.queries == ["*IDN?"]
    assert session.writes == []


@pytest.mark.parametrize(
    ("idn", "resource", "error_type", "message"),
    [
        (
            "KEYSIGHT,EDU36311A,SERIAL0000,1.0",
            "USB0::FAKE::EDU36311A::INSTR",
            CoreValidationError,
            "EDU36311A real execution does not support completion-pulse options",
        ),
        (
            "KEYSIGHT,E3646A,SERIAL0000,1.0",
            "ASRL1::INSTR",
            UnsupportedModelError,
            "completion-pulse options require E36312A",
        ),
    ],
)
def test_ramp_unsupported_completion_pulse_still_rejects_before_write(
    idn: str,
    resource: str,
    error_type: type[Exception],
    message: str,
) -> None:
    session = FakeSession(idn=idn)

    with pytest.raises(error_type, match=message):
        run_operation(
            OperationRequest(
                command="ramp",
                runtime=RuntimeOptions(resource=resource, confirm=True),
                parameters=general_pulse_parameters("ramp"),
            ),
            opener=lambda *args, **kwargs: session,
        )

    assert session.queries == ["*IDN?"]
    assert session.writes == []


@pytest.mark.parametrize(
    ("idn", "resource", "error_type", "message"),
    [
        (
            "KEYSIGHT,EDU36311A,SERIAL0000,1.0",
            "USB0::FAKE::EDU36311A::INSTR",
            CoreValidationError,
            "EDU36311A real execution does not support completion-pulse options",
        ),
        (
            "KEYSIGHT,E3646A,SERIAL0000,1.0",
            "ASRL1::INSTR",
            UnsupportedModelError,
            "completion-pulse options require E36312A",
        ),
    ],
)
@pytest.mark.parametrize("command", ["output-off", "safe-off"])
def test_unsupported_completion_pulse_preserves_safety_first_output_off_order(
    idn: str,
    resource: str,
    error_type: type[Exception],
    message: str,
    command: str,
) -> None:
    session = OutputStateSession(idn=idn, output_enabled=True)
    sleeps: list[float] = []

    with pytest.raises(error_type, match=message):
        run_operation(
            OperationRequest(
                command=command,
                runtime=RuntimeOptions(resource=resource, confirm=True),
                parameters=general_pulse_parameters(command),
            ),
            opener=lambda *args, **kwargs: session,
            sleep=sleeps.append,
        )

    output_off_index = next(
        index for index, event in enumerate(session.events) if event.startswith("W:OUTP OFF")
    )
    output_state_index = next(
        index for index, event in enumerate(session.events) if event.startswith("Q:OUTP?")
    )
    assert output_off_index < output_state_index
    assert session.output_enabled is False
    assert "SYST:ERR?" not in session.queries
    assert sleeps == ([0.01] if command == "output-off" else [])


@pytest.mark.parametrize(
    "command",
    [
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "smoke-output",
    ],
)
def test_e36312a_general_completion_pulse_emission_remains_post_action(
    monkeypatch,
    command: str,
) -> None:
    session = OutputStateSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        output_enabled=command in {"output-off", "safe-off"},
    )
    pulse_payload = {"completed": True, "restored": True}

    def pulse(*args, **kwargs):
        session.events.append("PULSE")
        return pulse_payload

    monkeypatch.setattr("powers_tool_core.operations.run_post_action_completion_pulse", pulse)
    data = run_operation(
        OperationRequest(
            command=command,
            runtime=RuntimeOptions(resource="USB0::FAKE::E36312A::INSTR", confirm=True),
            parameters=general_pulse_parameters(command),
        ),
        opener=lambda *args, **kwargs: session,
        sleep=lambda seconds: None,
    )

    pulse_index = session.events.index("PULSE")
    if command in {"output-off", "safe-off", "smoke-output"}:
        post_action_index = max(
            index for index, event in enumerate(session.events) if event.startswith("Q:OUTP?")
        )
    elif command in {"apply", "output-on"}:
        post_action_index = max(
            index for index, event in enumerate(session.events) if event.startswith("W:OUTP ON")
        )
    elif command == "cycle-output":
        post_action_index = max(
            index for index, event in enumerate(session.events) if event.startswith("W:OUTP OFF")
        )
    else:
        post_action_index = max(
            index for index, event in enumerate(session.events) if event.startswith("W:VOLT ")
        )
    error_queue_index = session.events.index("Q:SYST:ERR?")
    assert post_action_index < pulse_index < error_queue_index
    assert data["trigger"] == pulse_payload


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

    with pytest.raises(ConfirmationRequiredError, match="output-on"):
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


def test_output_on_with_exact_evidence_executes_all_channels() -> None:
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

    run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)
    assert session.queries[0] == "*IDN?"
    assert {"VOLT? (@1)", "CURR? (@1)", "VOLT? (@2)", "CURR? (@2)", "VOLT? (@3)", "CURR? (@3)"}.issubset(session.queries)
    assert session.writes == ["OUTP ON,(@1)", "OUTP ON,(@2)", "OUTP ON,(@3)"]


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


def test_cycle_output_completion_pulse_runs_after_all_outputs_are_off(monkeypatch) -> None:
    session = FakeSession()
    writes_at_pulse: list[str] = []

    def pulse(*args, **kwargs):
        writes_at_pulse.extend(session.writes)
        return {"completed": True}

    monkeypatch.setattr("powers_tool_core.operations.run_post_action_completion_pulse", pulse)
    core_request = OperationRequest(
        command="cycle-output",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=request("cycle-output", channel="all", completion_pulse_pins=(1,)).parameters,
    )

    run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert writes_at_pulse[-3:] == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]


@pytest.mark.parametrize("step_voltage", [0.02, 0.01, 0.005])
def test_ramp_real_always_uses_software_voltage_writes(step_voltage: float) -> None:
    session = FakeSession()
    params = request(
        "ramp",
        start_voltage=0.0,
        stop_voltage=1.0,
        step_voltage=step_voltage,
        current=0.05,
        delay_ms=0,
    ).parameters
    core_request = OperationRequest(
        command="ramp",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    data = run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert session.writes[0] == "CURR 0.05,(@1)"
    assert session.writes[1] == "VOLT 0,(@1)"
    assert session.writes[-1] == "VOLT 1,(@1)"
    assert not any(command.startswith("LIST:") for command in session.writes)
    assert data["steps"] in {51, 101, 201}


@pytest.mark.parametrize("field", ["completion_pulse_mode", "completion_pulse_dwell_ms", "wait_timeout_ms", "poll_ms"])
def test_ramp_removed_native_fields_reject_before_io(field: str) -> None:
    session = FakeSession()
    params = request(
        "ramp",
        start_voltage=0.0,
        stop_voltage=1.0,
        step_voltage=0.5,
        current=0.05,
        **{field: 10 if field != "completion_pulse_mode" else "native"},
    ).parameters
    core_request = OperationRequest(
        command="ramp",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True),
        parameters=params,
    )

    with pytest.raises(CoreValidationError, match=field):
        run_operation(core_request, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert session.queries == []
    assert session.writes == []


def test_ramp_step_completion_pulses_after_every_write_including_last(monkeypatch) -> None:
    session = FakeSession()
    pulse_write_snapshots: list[list[str]] = []

    def pulse(*args, **kwargs):
        pulse_write_snapshots.append(list(session.writes))
        return {"completed": True}

    monkeypatch.setattr("powers_tool_core.operations.run_post_action_completion_pulse", pulse)
    params = request(
        "ramp",
        start_voltage=0.0,
        stop_voltage=1.0,
        step_voltage=0.5,
        current=0.05,
        delay_ms=5001,
        completion_pulse_pins=(1,),
        completion_pulse_timing="step",
    ).parameters

    data = run_operation(
        OperationRequest(command="ramp", runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", confirm=True), parameters=params),
        opener=lambda *args, **kwargs: session,
        sleep=lambda seconds: None,
    )

    assert len(data["triggers"]) == 3
    assert [item["voltage"] for item in data["triggers"]] == [0.0, 0.5, 1.0]
    assert [snapshot[-1] for snapshot in pulse_write_snapshots] == ["VOLT 0,(@1)", "VOLT 0.5,(@1)", "VOLT 1,(@1)"]


@pytest.mark.parametrize("delay_ms", [0, 5000])
def test_ramp_step_completion_pulse_accepts_nonnegative_delay(delay_ms) -> None:
    plan = output_plan(
        request(
            "ramp",
            start_voltage=0,
            stop_voltage=1,
            step_voltage=1,
            delay_ms=delay_ms,
            completion_pulse_pins=(1,),
            completion_pulse_timing="step",
        )
    )

    assert len([step for step in plan["steps"] if step["action"] == "completion_pulse"]) == 2


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


def test_e3646a_operations_fake_execution() -> None:
    idn = "KEYSIGHT,E3646A,MY12345678,1.0"
    responses = {
        "*IDN?": idn,
        "SYST:ERR?": '0,"No error"',
        "INST:NSEL?": "1",
        "VOLT?": "1.0",
        "CURR?": "0.1",
        "OUTP?": "0",
        "MEAS:VOLT?": "1.0",
        "MEAS:CURR?": "0.1",
    }

    req_set = OperationRequest(
        command="set",
        parameters={"channel": 2, "voltage": 1.5, "current": 0.05, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_set = FakeSession(idn=idn, responses=responses)
    run_operation(req_set, opener=lambda *args, **kwargs: session_set)
    assert "INST:NSEL 2" in session_set.writes
    assert "VOLT 1.5" in session_set.writes
    assert "CURR 0.05" in session_set.writes
    assert not any("(@" in w for w in session_set.writes)

    req_off = OperationRequest(
        command="output-off",
        parameters={"channel": 1, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_off = FakeSession(idn=idn, responses=responses)
    run_operation(req_off, opener=lambda *args, **kwargs: session_off)
    assert "OUTP OFF" in session_off.writes

    req_safe_all = OperationRequest(
        command="safe-off",
        parameters={"channel": "all", "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_safe_all = FakeSession(idn=idn, responses=responses)
    run_operation(req_safe_all, opener=lambda *args, **kwargs: session_safe_all)
    assert session_safe_all.writes.count("OUTP OFF") == 2

    req_on = OperationRequest(
        command="output-on",
        parameters={"channel": 2, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_on = FakeSession(idn=idn, responses=responses)
    run_operation(req_on, opener=lambda *args, **kwargs: session_on)
    assert session_on.queries[0] == "*IDN?"
    assert {"INST:NSEL?", "VOLT?", "CURR?"}.issubset(session_on.queries)
    assert "OUTP ON" in session_on.writes

    req_apply_all = OperationRequest(
        command="apply",
        parameters={"channel": "all", "voltage": 1.2, "current": 0.04, "no_output": True, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_apply_all = FakeSession(idn=idn, responses=responses)
    run_operation(req_apply_all, opener=lambda *args, **kwargs: session_apply_all)
    assert session_apply_all.writes.count("VOLT 1.2") == 2
    assert session_apply_all.writes.count("CURR 0.04") == 2
    assert "OUTP ON" not in session_apply_all.writes

    req_cycle = OperationRequest(
        command="cycle-output",
        parameters={"channel": 2, "duration_ms": 10, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_cycle = FakeSession(idn=idn, responses=responses)
    run_operation(req_cycle, opener=lambda *args, **kwargs: session_cycle)
    assert "OUTP ON" in session_cycle.writes
    assert "OUTP OFF" in session_cycle.writes

    req_smoke = OperationRequest(
        command="smoke-output",
        parameters={"channel": 1, "voltage": 1.1, "current": 0.05, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_smoke = FakeSession(idn=idn, responses=responses)
    run_operation(req_smoke, opener=lambda *args, **kwargs: session_smoke)
    assert "VOLT 1.1" in session_smoke.writes
    assert "CURR 0.05" in session_smoke.writes
    assert "OUTP ON" in session_smoke.writes
    assert "OUTP OFF" in session_smoke.writes

    req_ramp = OperationRequest(
        command="ramp",
        parameters={"channel": 1, "start_voltage": 0.5, "stop_voltage": 1.5, "step_voltage": 0.5, "current": 0.05, "delay_ms": 1, "confirm": True},
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False)
    )
    session_ramp = FakeSession(idn=idn, responses=responses)
    run_operation(req_ramp, opener=lambda *args, **kwargs: session_ramp)
    assert "CURR 0.05" in session_ramp.writes
    assert "VOLT 0.5" in session_ramp.writes
    assert "VOLT 1" in session_ramp.writes
    assert "VOLT 1.5" in session_ramp.writes
