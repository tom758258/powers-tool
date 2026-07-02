import pytest

from keysight_power_core.core import CoreValidationError, OperationRequest, RuntimeOptions
from keysight_power_core.ramp_list import RAMP_LIST_KIND, run_ramp_list


class FakeSession:
    def __init__(self, fail_write: str | None = None) -> None:
        self.fail_write = fail_write
        self.writes: list[str] = []
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def write(self, command: str) -> None:
        if command == self.fail_write:
            raise ValueError("injected write failure")
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return "KEYSIGHT,E36312A,SERIAL0000,1.0"
        return '0,"No error"'


def document(*segments):
    return {"kind": RAMP_LIST_KIND, "version": 1, "segments": list(segments)}


def segment(
    channel=1,
    current=0.1,
    start_voltage=0,
    stop_voltage=1,
    step_voltage=0.5,
    delay_ms=0,
    hold_ms=0,
):
    return {
        "channel": channel,
        "current": current,
        "start_voltage": start_voltage,
        "stop_voltage": stop_voltage,
        "step_voltage": step_voltage,
        "delay_ms": delay_ms,
        "hold_ms": hold_ms,
    }


def request(doc, **runtime):
    return OperationRequest(
        command="ramp-list",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", **runtime),
        parameters={"document": doc},
    )


def test_ramp_list_lint_validates_without_opening_visa() -> None:
    opened = False
    core_request = request(document(segment()))
    core_request = OperationRequest(
        command="ramp-list",
        runtime=core_request.runtime,
        parameters={**core_request.parameters, "lint": True},
    )

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_ramp_list(core_request, opener=opener)

    assert opened is False
    assert data["status"] == "valid"
    assert data["segment_count"] == 1
    assert data["segments"][0]["voltages"] == [0.0, 0.5, 1.0]


def test_ramp_list_executes_cross_channel_segments_in_one_session() -> None:
    session = FakeSession()
    opener_calls = 0

    def opener(*args, **kwargs):
        nonlocal opener_calls
        opener_calls += 1
        return session

    data = run_ramp_list(
        request(
            document(
                segment(channel=1, current=0.1, start_voltage=0, stop_voltage=1, step_voltage=0.5),
                segment(channel=2, current=0.05, start_voltage=2, stop_voltage=1, step_voltage=0.5),
            )
        ),
        opener=opener,
        sleep=lambda seconds: None,
    )

    assert opener_calls == 1
    assert session.writes == [
        "CURR 0.1,(@1)",
        "VOLT 0,(@1)",
        "VOLT 0.5,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 2,(@2)",
        "VOLT 1.5,(@2)",
        "VOLT 1,(@2)",
    ]
    assert data["status"] == "completed"
    assert data["completed_segments"] == 2


def test_ramp_list_delay_and_final_hold_are_applied() -> None:
    sleeps: list[float] = []

    run_ramp_list(
        request(document(segment(delay_ms=100, hold_ms=250))),
        opener=lambda *args, **kwargs: FakeSession(),
        sleep=sleeps.append,
    )

    assert sleeps == [0.1, 0.1, 0.25]


def test_ramp_list_invalid_later_segment_produces_no_hardware_io() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    with pytest.raises(CoreValidationError, match="segment 2"):
        run_ramp_list(
            request(document(segment(), segment(channel=2, step_voltage=0))),
            opener=opener,
        )

    assert opened is False


def test_ramp_list_model_channel_validation_happens_before_writes() -> None:
    session = FakeSession()

    with pytest.raises(CoreValidationError, match="segment 2 channel 4"):
        run_ramp_list(
            request(document(segment(), segment(channel=4))),
            opener=lambda *args, **kwargs: session,
        )

    assert session.writes == []


def test_ramp_list_safety_failure_in_later_segment_produces_no_writes(tmp_path) -> None:
    safety = tmp_path / "safety.toml"
    safety.write_text("[safety]\nmax_voltage = 1\nmax_current = 0.2\n", encoding="utf-8")
    session = FakeSession()
    core_request = OperationRequest(
        command="ramp-list",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", safety_config=str(safety)),
        parameters={"document": document(segment(), segment(channel=2, stop_voltage=2))},
    )

    with pytest.raises(CoreValidationError, match="segment 2"):
        run_ramp_list(core_request, opener=lambda *args, **kwargs: session)

    assert session.writes == []


def test_ramp_list_failure_stops_later_segments_without_output_off() -> None:
    session = FakeSession(fail_write="VOLT 0.5,(@1)")

    data = run_ramp_list(
        request(document(segment(), segment(channel=2))),
        opener=lambda *args, **kwargs: session,
        sleep=lambda seconds: None,
    )

    assert data["status"] == "failed"
    assert data["completed_segments"] == 0
    assert data["failed_segment"]["index"] == 1
    assert not any(command.startswith("OUTP") for command in session.writes)
    assert not any("(@2)" in command for command in session.writes)


def test_ramp_list_cancellation_stops_later_segments_without_output_off() -> None:
    session = FakeSession()
    cancelled = False

    def sleep(_seconds: float) -> None:
        nonlocal cancelled
        cancelled = True

    data = run_ramp_list(
        request(document(segment(delay_ms=100), segment(channel=2))),
        opener=lambda *args, **kwargs: session,
        sleep=sleep,
        stop_requested=lambda: cancelled,
    )

    assert data["status"] == "stopped"
    assert data["failed_segment"]["index"] == 1
    assert not any(command.startswith("OUTP") for command in session.writes)
    assert not any("(@2)" in command for command in session.writes)


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({"kind": "wrong", "version": 1, "segments": [segment()]}, "kind"),
        ({"kind": RAMP_LIST_KIND, "version": 2, "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "version": True, "segments": [segment()]}, "version"),
        (document(), "1 to 10"),
        (document(*(segment() for _ in range(11))), "at most 10"),
        (document(segment(delay_ms=-1)), "delay_ms"),
        (document(segment(hold_ms=-1)), "hold_ms"),
        (document(segment(channel=1.5)), "invalid numeric"),
        (document(segment(delay_ms=1.5)), "invalid numeric"),
        (document(segment(start_voltage=0, stop_voltage=1001, step_voltage=1)), "1000 voltage steps"),
    ],
)
def test_ramp_list_rejects_invalid_documents(doc, message) -> None:
    with pytest.raises(CoreValidationError, match=message):
        run_ramp_list(request(doc, dry_run=True))


def test_ramp_list_step_pulse_accepts_zero_delay() -> None:
    doc = document(segment(delay_ms=0), segment(channel=2, delay_ms=0))
    doc["completion_pulse"] = {"timing": "step", "pins": [1], "polarity": "positive"}

    data = run_ramp_list(request(doc, dry_run=True))

    assert data["plan"]["completion_pulse"]["timing"] == "step"


def test_ramp_list_segment_pulse_uses_each_segment_channel(monkeypatch) -> None:
    calls: list[int] = []

    def pulse(_power_supply, *, channel, **kwargs):
        calls.append(channel)
        return {"channel": channel, "completed": True}

    monkeypatch.setattr("keysight_power_core.ramp_list.run_post_action_completion_pulse", pulse)
    doc = document(segment(channel=1), segment(channel=2))
    doc["completion_pulse"] = {"timing": "segment", "pins": [1], "polarity": "positive"}

    data = run_ramp_list(request(doc), opener=lambda *args, **kwargs: FakeSession(), sleep=lambda seconds: None)

    assert calls == [1, 2]
    assert [item["trigger"]["channel"] for item in data["segments"]] == [1, 2]


def test_e3646a_ramp_list_unsupported_pulse() -> None:
    class E3646AFakeSession(FakeSession):
        def query(self, command: str) -> str:
            self.queries.append(command)
            if command == "*IDN?":
                return "KEYSIGHT,E3646A,MY12345678,1.0"
            return '0,"No error"'

    doc = document(segment(channel=1))
    doc["completion_pulse"] = {"timing": "segment", "pins": [1], "polarity": "positive"}

    req = OperationRequest(
        command="ramp-list",
        parameters={"document": doc, "confirm": True},
        runtime=RuntimeOptions(resource="GPIB0::1::INSTR", dry_run=False, simulate=False)
    )
    with pytest.raises(CoreValidationError, match="completion pulses are only supported for E36312A"):
        run_ramp_list(req, opener=lambda *args, **kwargs: E3646AFakeSession(), sleep=lambda seconds: None)


def test_e3646a_ramp_list_simulate_and_real_execution() -> None:
    class E3646AFakeSession(FakeSession):
        def query(self, command: str) -> str:
            self.queries.append(command)
            if command == "*IDN?":
                return "KEYSIGHT,E3646A,MY12345678,1.0"
            if command == "INST:NSEL?":
                return "1"
            return '0,"No error"'

    doc = document(segment(channel=2, current=0.05, start_voltage=0.5, stop_voltage=1.5, step_voltage=0.5, delay_ms=10, hold_ms=5))

    req_sim = OperationRequest(
        command="ramp-list",
        parameters={"document": doc},
        runtime=RuntimeOptions(resource="GPIB0::1::INSTR", dry_run=False, simulate=True)
    )
    data_sim = run_ramp_list(req_sim, opener=lambda *args, **kwargs: E3646AFakeSession(), sleep=lambda seconds: None)
    assert data_sim["status"] == "planned"

    req_real = OperationRequest(
        command="ramp-list",
        parameters={"document": doc, "confirm": True},
        runtime=RuntimeOptions(resource="GPIB0::1::INSTR", dry_run=False, simulate=False)
    )
    session = E3646AFakeSession()
    data_real = run_ramp_list(req_real, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)
    assert data_real["status"] == "completed"
    assert "INST:NSEL 2" in session.writes
    assert "CURR 0.05" in session.writes
    assert "VOLT 0.5" in session.writes
    assert "VOLT 1" in session.writes
    assert "VOLT 1.5" in session.writes
    assert not any("(@" in w for w in session.writes)
