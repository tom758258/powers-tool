from __future__ import annotations

import pytest

from powers_tool_core.core import StopCleanupError
from powers_tool_core.stop_cleanup import StopCleanupResult, stop_aware_opener


class FakeSession:
    def __init__(self, events: list[str], *, release_error: Exception | None = None) -> None:
        self.events = events
        self.release_error = release_error

    def release_to_local(self) -> None:
        self.events.append("release_to_local")
        if self.release_error is not None:
            raise self.release_error


class FakeContext:
    def __init__(self, events: list[str], session: FakeSession, *, close_error: Exception | None = None) -> None:
        self.events = events
        self.session = session
        self.close_error = close_error

    def __enter__(self) -> FakeSession:
        self.events.append("open")
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error


def _opener(events: list[str], session: FakeSession):
    def open_session(*args, **kwargs):
        return FakeContext(events, session)

    return open_session


def test_normal_completion_only_closes_session() -> None:
    events: list[str] = []
    reports: list[StopCleanupResult] = []
    opener = stop_aware_opener(
        _opener(events, FakeSession(events)),
        stop_requested=lambda: False,
        simulated=False,
        reporter=reports.append,
    )

    with opener("GPIB0::1::INSTR"):
        events.append("work")

    assert events == ["open", "work", "close"]
    assert reports == []


def test_gpib_stop_releases_before_close_and_reports_post_cleanup() -> None:
    events: list[str] = []
    reports: list[StopCleanupResult] = []
    opener = stop_aware_opener(
        _opener(events, FakeSession(events)),
        stop_requested=lambda: True,
        simulated=False,
        reporter=reports.append,
    )

    with opener("GPIB0::1::INSTR"):
        events.append("work")

    assert events == ["open", "work", "release_to_local", "close"]
    assert [(result.operation, result.status) for result in reports] == [
        ("release_to_local", "succeeded"),
        ("close_session", "succeeded"),
        ("cleanup_release_to_local", "succeeded"),
    ]


@pytest.mark.parametrize(
    ("resource", "simulated", "status"),
    [
        ("USB0::FAKE::INSTR", False, "unsupported"),
        ("TCPIP0::FAKE::INSTR", False, "unsupported"),
        ("GPIB0::1::INSTR", True, "not_applicable"),
    ],
)
def test_non_gpib_and_simulated_stop_do_not_release(resource: str, simulated: bool, status: str) -> None:
    events: list[str] = []
    reports: list[StopCleanupResult] = []
    opener = stop_aware_opener(
        _opener(events, FakeSession(events)),
        stop_requested=lambda: True,
        simulated=simulated,
        reporter=reports.append,
    )

    with opener(resource):
        pass

    assert events == ["open", "close"]
    assert reports[0].status == status


def test_release_failure_still_closes_and_finishes_post_cleanup() -> None:
    events: list[str] = []
    reports: list[StopCleanupResult] = []
    opener = stop_aware_opener(
        _opener(events, FakeSession(events, release_error=RuntimeError("release failed"))),
        stop_requested=lambda: True,
        simulated=False,
        reporter=reports.append,
    )

    with pytest.raises(StopCleanupError):
        with opener("GPIB0::1::INSTR"):
            pass

    assert events == ["open", "release_to_local", "close"]
    assert [(result.operation, result.status) for result in reports] == [
        ("release_to_local", "failed"),
        ("close_session", "succeeded"),
        ("cleanup_release_to_local", "succeeded"),
    ]


def test_close_failure_still_finishes_post_cleanup() -> None:
    events: list[str] = []
    reports: list[StopCleanupResult] = []

    def opener(*args, **kwargs):
        return FakeContext(events, FakeSession(events), close_error=RuntimeError("close failed"))

    wrapped = stop_aware_opener(
        opener,
        stop_requested=lambda: True,
        simulated=False,
        reporter=reports.append,
    )

    with pytest.raises(StopCleanupError):
        with wrapped("GPIB0::1::INSTR"):
            pass

    assert events == ["open", "release_to_local", "close"]
    assert [(result.operation, result.status) for result in reports] == [
        ("release_to_local", "succeeded"),
        ("close_session", "failed"),
        ("cleanup_release_to_local", "succeeded"),
    ]
