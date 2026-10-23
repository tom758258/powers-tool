"""Focused Common v3 wire, terminal, and Worker exit conformance (no hardware)."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from powers_tool_cli import worker_execution
from powers_tool_cli import worker_http
from powers_tool_cli.worker_http import WorkerHTTPHandler, WorkerHTTPServer
from powers_tool_cli.worker_state import WorkerState
from powers_tool_core.core import CommandCancelled, CoreExecutionError


@pytest.fixture
def control_worker(tmp_path):
    config = {
        "id": "v3-test",
        "mode": "simulate",
        "artifact_mode": "memory",
        "settings": {},
        "artifacts_dir": str(tmp_path),
        "events_jsonl": None,
    }
    server = WorkerHTTPServer(("127.0.0.1", 0), WorkerHTTPHandler)
    state = WorkerState(config, server.server_address[1])
    state.server = server
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    state.shutdown_event.set()
    with state.lock:
        state.lock.notify_all()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def http(state, path, body=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{state.port}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=2)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.code, json.loads(response.read())


def test_v3_invalid_wire_requests_have_no_control_side_effects(control_worker):
    state = control_worker
    for token in ('"3"', "true", "3.0", "3e0", "2", "null"):
        for path, fields in (
            ("/command", ',"command":"identify"'),
            ("/cancel", ',"worker_job_id":"stale"'),
            ("/stop", ""),
        ):
            code, response = http(
                state, path, ('{"schema_version":' + token + fields + "}").encode()
            )
            assert code == 400
            assert type(response["schema_version"]) is int and response["schema_version"] == 3
            assert response["run_id"] == state.run_id
            assert response["status"] == "error"
            assert response["error"]["category"] == "validation"
            assert isinstance(response["error"]["details"], dict)
    for body in (b"[]", b"{", b'{"reason":null}', b'{"unknown":true}'):
        assert http(state, "/stop", body)[0] == 400
    assert state.status == "ready"
    assert state.next_job is None and state.active_job is None
    assert not state.stop_event.is_set() and not state.job_cancel_event.is_set()
    assert not state.shutdown_flag and state.cleanup_results == []
    assert list(Path(state.config["artifacts_dir"]).iterdir()) == []


def test_stop_forms_are_idempotent(control_worker, capsys):
    state = control_worker
    for body in (b"", b"{}", b'{"schema_version":3,"reason":"done"}'):
        code, response = http(state, "/stop", body)
        assert code == 200
        assert response == {
            "schema_version": 3,
            "run_id": state.run_id,
            "status": "accepted",
            "error": None,
        }
    assert state.stop_event.is_set() and state.shutdown_flag
    assert http(state, "/status")[1]["worker_state"] == "stopping"
    assert state.next_job is None and state.cleanup_results == []
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["event"] for event in events] == ["stop_requested"]
    assert events[0]["run_id"] == state.run_id


def test_handler_failures_use_common_worker_errors(control_worker, monkeypatch):
    def fail(*args):
        raise RuntimeError("injected handler failure")

    monkeypatch.setattr(control_worker, "status_snapshot", fail)
    monkeypatch.setattr(worker_http, "_validate_command_body", fail)
    for path, body in (("/status", None), ("/command", b"{}")):
        code, response = http(control_worker, path, body)
        assert code == 500 and response["status"] == "error"
        assert response["schema_version"] == 3 and response["run_id"] == control_worker.run_id
        assert response["error"]["category"] == "worker"
        assert isinstance(response["error"]["details"], dict)
    assert control_worker.next_job is None and control_worker.cleanup_results == []


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_terminal_matches_fixed_http_snapshot_and_worker_reuse(
    control_worker, monkeypatch, capsys, outcome
):
    state = control_worker
    release = threading.Event()
    called = []
    result = {
        "samples_written": 1,
        "samples_requested": 2,
        "duration_sec": None,
        "interval_sec": 1,
        "channels": [1],
        "stop_reason": "completed",
    }

    def run_command(*args, **kwargs):
        called.append(True)
        assert release.wait(2)
        if outcome == "failed":
            raise CoreExecutionError("sample failed", data=result)
        if outcome == "cancelled":
            raise CommandCancelled("cancelled", data={**result, "stop_reason": "user_cancelled"})
        return result

    monkeypatch.setattr(worker_execution, "run_core_command", run_command)
    body = json.dumps(
        {
            "schema_version": 3,
            "command": "log",
            "job_id": "client-1",
            "arguments": {"channel": 1, "samples": 2, "interval_sec": 1},
            "context": {"mode": "simulate", "planning_model_id": "keysight-e36312a"},
        }
    ).encode()
    code, accepted = http(state, "/command", body)
    assert code == 202 and accepted["kind"] == "async_job" and accepted["error"] is None
    assert accepted["run_id"] == state.run_id and accepted["worker_job_id"]
    queued = state.next_job
    code, status = http(state, "/status")
    assert code == 200 and status["active_job"]["state"] == "queued"
    assert state.next_job is queued and called == []  # Status cannot start work or touch a device.
    code, rejected = http(state, "/command", body)
    assert code == 409 and rejected["status"] == "rejected"
    assert rejected["worker_job_id"] is None and rejected["error"]["category"] == "admission"
    runner = threading.Thread(target=worker_execution.job_runner, args=(state,), daemon=True)
    runner.start()
    try:
        if outcome == "cancelled":
            code, cancel = http(
                state,
                "/cancel",
                json.dumps(
                    {"schema_version": 3, "worker_job_id": accepted["worker_job_id"]}
                ).encode(),
            )
            assert code == 202 and cancel["status"] == "accepted"
        release.set()
        deadline = time.monotonic() + 3
        while state.last_job is None or state.active_job is not None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert state.status == "ready" and not state.shutdown_flag
        _, first = http(state, "/status")
        _, second = http(state, "/status")
        assert first["last_job"] == second["last_job"]
        terminal = first["last_job"]
        assert terminal["state"] == outcome and terminal["ok"] == (outcome == "succeeded")
        assert terminal["result"]["schema_version"] == 2
        assert terminal["result"]["status"] == outcome
        if outcome == "succeeded":
            assert terminal["error"] is None
        else:
            assert terminal["error"]["details"]["domain_error"]["code"] == terminal["error"]["code"]
            assert terminal["error"]["details"]["partial_result"]
        assert (
            http(
                state,
                "/cancel",
                json.dumps(
                    {"schema_version": 3, "worker_job_id": accepted["worker_job_id"]}
                ).encode(),
            )[0]
            == 409
        )
        # The next accepted job confirms multi-job reuse after any terminal state.
        code, next_job = http(state, "/command", body)
        assert code == 202 and next_job["worker_job_id"] != accepted["worker_job_id"]
        while (
            state.last_job["worker_job_id"] != next_job["worker_job_id"]
            or state.active_job is not None
        ):
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        release.set()
        state.shutdown_event.set()
        with state.lock:
            state.lock.notify_all()
        runner.join(timeout=2)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finished = [
        event
        for event in events
        if event["event"] == "job_finished" and event["worker_job_id"] == accepted["worker_job_id"]
    ]
    assert len(finished) == 1
    assert all(finished[0][field] == terminal[field] for field in terminal)
    assert all(event["schema_version"] == 3 and event["run_id"] == state.run_id for event in events)


def test_runner_infrastructure_failure_finishes_accepted_job(control_worker, monkeypatch, capsys):
    state = control_worker
    body = json.dumps(
        {
            "schema_version": 3,
            "command": "identify",
            "context": {
                "mode": "simulate",
                "planning_model_id": "keysight-e36312a",
            },
        }
    ).encode()
    assert http(state, "/command", body)[0] == 202

    def fail_opener(*args):
        raise RuntimeError("injected runner failure")

    monkeypatch.setattr(worker_execution, "get_opener", fail_opener)
    runner = threading.Thread(target=worker_execution.job_runner, args=(state,), daemon=True)
    runner.start()
    runner.join(timeout=2)
    assert not runner.is_alive()
    assert state.status == "error" and state.fatal_error["category"] == "worker"
    assert state.active_job is None and state.last_job["state"] == "failed"
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finished = [event for event in events if event["event"] == "job_finished"]
    assert len(finished) == 1 and finished[0]["error"] == state.last_job["error"]


@pytest.mark.parametrize(
    "failure", ["config", "artifacts", "event_sink", "bind", "startup", "runtime", "cleanup", "success"]
)
def test_worker_process_exit_and_summary(tmp_path, failure):
    args = ["worker", "--mode", "simulate", "--artifact-mode", "memory", "--control-port", "0"]
    script = """
import sys
from powers_tool_cli import worker
from powers_tool_cli.cli import build_parser
from powers_tool_cli.worker_execution import record_cleanup_result
from powers_tool_core.stop_cleanup import StopCleanupResult
failure = sys.argv.pop(1)
if failure == 'startup':
    def fail_state(*args):
        raise RuntimeError('injected startup failure')
    worker.WorkerState = fail_state
if failure in ('runtime', 'cleanup'):
    class FakeServer:
        server_address = ('127.0.0.1', 12345)
        def __init__(self, *args): pass
        def server_close(self): pass
        def shutdown(self): pass
        def serve_forever(self):
            if failure == 'runtime':
                raise RuntimeError('injected runtime failure')
            if failure == 'cleanup':
                record_cleanup_result(self.state, StopCleanupResult('close_session', 'failed', 'injected cleanup failure'))
    worker.WorkerHTTPServer = FakeServer
sys.exit(worker.run_worker(build_parser().parse_args(sys.argv[1:])))
"""
    with socket.socket() as occupied:
        if failure == "bind":
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            args[-1] = str(occupied.getsockname()[1])
        if failure == "config":
            config = tmp_path / "invalid.json"
            config.write_text('{"mode":"invalid"}', encoding="utf-8")
            args = ["worker", "--config", str(config)]
        if failure == "artifacts":
            blocked = tmp_path / "not-a-directory"
            blocked.write_text("occupied", encoding="utf-8")
            args = ["worker", "--mode", "simulate", "--artifacts-dir", str(blocked)]
        if failure == "event_sink":
            args = [
                "worker", "--mode", "simulate", "--artifacts-dir", str(tmp_path / "artifacts"),
                "--events-jsonl", str(tmp_path),
            ]
        if failure == "success":
            events_file = tmp_path / "events.jsonl"
            args = [
                "worker", "--mode", "simulate", "--control-port", "0",
                "--artifacts-dir", str(tmp_path / "artifacts"),
                "--events-jsonl", str(events_file),
            ]
            with subprocess.Popen(
                [sys.executable, "-c", script, failure, *args],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ) as process:
                try:
                    ready = None
                    deadline = time.monotonic() + 5
                    while ready is None:
                        assert process.poll() is None, "Worker exited before ready"
                        assert time.monotonic() < deadline, "Worker did not become ready"
                        if events_file.exists():
                            for line in events_file.read_text(encoding="utf-8").splitlines():
                                try:
                                    event = json.loads(line)
                                except json.JSONDecodeError:
                                    continue  # The writer may still be appending this line.
                                if event["event"] == "ready":
                                    ready = event
                                    break
                        if ready is None:
                            time.sleep(0.02)
                    request = urllib.request.Request(
                        ready["stop_url"], data=b"{}", headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(request, timeout=2) as response:
                        assert response.code == 200
                        acknowledgement = json.loads(response.read())
                        assert acknowledgement["status"] == "accepted"
                        assert acknowledgement["run_id"] == ready["run_id"]
                    stdout, stderr = process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=2)
                result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        else:
            result = subprocess.run(
                [sys.executable, "-c", script, failure, *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
    assert result.returncode == (0 if failure == "success" else 2 if failure == "config" else 3), (
        result.stderr
    )
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert all(isinstance(event, dict) for event in events)
    if failure in {"config", "artifacts", "event_sink", "bind", "startup"}:
        assert events == [] and result.stderr.strip()
    else:
        assert events[0]["event"] == "ready"
        summary = events[-1]
        assert summary["event"] == "summary" and summary["exit_code"] == result.returncode
        assert summary["ok"] == (failure == "success")
        assert (summary["fatal_error"] is None) == (failure == "success")
        if failure == "runtime":
            assert result.stderr.strip()
            assert summary["fatal_error"]["code"] == "runtime_failed"
        elif failure == "cleanup":
            assert summary["fatal_error"]["code"] == "cleanup_failed"
            assert any(item["status"] == "failed" for item in summary["cleanup"])
        else:
            assert not result.stderr.strip()
            assert len([event for event in events if event["event"] == "stop_requested"]) == 1
            assert [(item["operation"], item["status"]) for item in summary["cleanup"]] == [
                ("release_to_local", "not_applicable"),
                ("close_session", "not_applicable"),
                ("cleanup_release_to_local", "succeeded"),
            ]
        assert all(
            event["schema_version"] == 3 and event["run_id"] == summary["run_id"]
            for event in events
        )
