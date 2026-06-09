from keysight_power_core.core import SequenceRequest, RuntimeOptions
from keysight_power_core.sequence import run_sequence


class FakeSession:
    capabilities = type("Capabilities", (), {"channels": (1, 2, 3)})()

    def __init__(self, *, fail_safe_off_channels: tuple[int, ...] = ()) -> None:
        self.writes: list[str] = []
        self.fail_safe_off_channels = fail_safe_off_channels

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        responses = {
            "*IDN?": "KEYSIGHT,E36312A,SERIAL0000,1.0",
            "MEAS:VOLT? (@1)": "1.0",
            "MEAS:CURR? (@1)": "0.1",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.1",
            "OUTP? (@1)": "0",
        }
        return responses.get(command, '0,"No error"')


def request(document, **runtime):
    return SequenceRequest(
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", **runtime),
        parameters={"document": document},
    )


def test_sequence_lint_does_not_open_visa() -> None:
    opened = False
    core_request = request({"version": 1, "steps": [{"action": "measure", "channel": 1}]})
    core_request = SequenceRequest(runtime=core_request.runtime, parameters={**core_request.parameters, "lint": True})

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_sequence(core_request, opener=opener)

    assert opened is False
    assert data["status"] == "valid"
    assert data["step_count"] == 1


def test_sequence_dry_run_does_not_open_visa_and_adds_preview() -> None:
    opened = False
    core_request = request(
        {"version": 1, "steps": [{"action": "set", "channel": 1, "voltage": 1.0, "current": 0.1}]},
        dry_run=True,
    )

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_sequence(core_request, opener=opener)

    assert opened is False
    assert data["status"] == "planned"
    assert data["plan"]["steps"][0]["preview"]["commands"] == ["CURR 0.1,(@1)", "VOLT 1,(@1)"]


def test_sequence_keyboard_interrupt_safe_off_cleanup() -> None:
    session = FakeSession()
    core_request = request(
        {"version": 1, "steps": [{"action": "wait", "seconds": 1}, {"action": "measure", "channel": 1}]}
    )

    def interrupting_sleep(seconds: float) -> None:
        raise KeyboardInterrupt

    data = run_sequence(core_request, opener=lambda *args, **kwargs: session, sleep=interrupting_sleep)

    assert data["status"] == "stopped"
    assert data["failed_step"] == {"index": 1, "action": "wait", "code": "interrupted"}
    assert data["cleanup"]["safe_off_attempted"] is True
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]


def test_sequence_cleanup_errors_do_not_replace_original_failure() -> None:
    session = FakeSession()
    original_write = session.write

    def write(command: str) -> None:
        if command == "OUTP ON,(@1)":
            raise ValueError("output on failed")
        if command == "OUTP OFF,(@2)":
            raise ValueError("cleanup channel 2 failed")
        original_write(command)

    session.write = write  # type: ignore[method-assign]
    core_request = request({"version": 1, "steps": [{"action": "output-on", "channel": 1}]})

    data = run_sequence(core_request, opener=lambda *args, **kwargs: session)

    assert data["status"] == "failed"
    assert data["failed_step"]["index"] == 1
    assert data["failed_step"]["message"] == "output on failed"
    assert data["cleanup"]["errors"] == [{"channel": 2, "message": "cleanup channel 2 failed"}]
