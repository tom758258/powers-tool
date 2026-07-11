from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
import threading
from pathlib import Path
import pytest

import keysight_power_cli.worker as worker_mod
import keysight_power_cli.cli as cli
from keysight_power_cli.worker import WorkerState, _run_job_impl, _write_json_artifact_atomic, load_worker_config, run_worker
from keysight_power_cli.cli import build_parser


@pytest.mark.parametrize("field", ["support_policy_mode", "validation_allow_pending_live_support"])
def test_worker_rejects_validation_mode_request_arguments(field: str) -> None:
    state = WorkerState(
        {
            "id": "test",
            "type": "power",
            "enabled": True,
            "mode": "live",
            "control_host": "127.0.0.1",
            "control_port": 0,
            "artifacts_dir": ".tmp_tests/worker",
            "events_jsonl": None,
            "settings": {"resource": "USB0::FAKE::E36312A::INSTR"},
        },
        0,
    )
    status, payload = worker_mod._validate_command_body(
        {"command": "measure", "arguments": {"channel": 1, field: "validation"}},
        state,
    )
    assert status == 400
    assert payload["error"]["code"] == "argument_error"


@pytest.mark.parametrize("field", ["support_policy_mode", "validation_allow_pending_live_support"])
def test_worker_rejects_validation_mode_setting(field: str) -> None:
    config = {
        "id": "test",
        "type": "power",
        "enabled": True,
        "mode": "live",
        "control_host": "127.0.0.1",
        "control_port": 0,
        "artifacts_dir": ".tmp_tests/worker",
        "events_jsonl": None,
        "settings": {"resource": "USB0::FAKE::E36312A::INSTR", field: "validation"},
    }
    with pytest.raises(ValueError, match="validation support policy mode"):
        worker_mod._validate_worker_config(config)


def _wait_for_json_file(path: Path, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                last_error = exc
        time.sleep(0.05)
    if last_error is not None:
        raise AssertionError(f"{path} did not contain parseable JSON within {timeout}s") from last_error
    raise AssertionError(f"{path} was not created within {timeout}s")


def _last_stdout_json(capsys) -> dict:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _run_worker_job_for_test(tmp_path: Path, *, command: str, arguments: dict, config: dict | None = None) -> dict:
    job_dir = tmp_path / f"job_{command.replace('-', '_')}_{len(list(tmp_path.iterdir()))}"
    job_dir.mkdir()
    state = WorkerState(
        config
        or {
            "id": "test",
            "type": "power",
            "enabled": True,
            "mode": "live",
            "control_host": "127.0.0.1",
            "control_port": 0,
            "artifacts_dir": str(tmp_path),
            "events_jsonl": None,
            "settings": {"resource": "USB0::FAKE::E36312A::INSTR"},
        },
        0,
    )
    _run_job_impl(
        state,
        {
            "job_id": None,
            "worker_job_id": job_dir.name,
            "command": command,
            "arguments": arguments,
            "dir": job_dir,
        },
    )
    return json.loads((job_dir / "result.json").read_text(encoding="utf-8"))


class FakeWorkerLiveSession:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def query(self, command: str) -> str:
        self.queries.append(command)
        return {
            "*IDN?": "KEYSIGHT,E36312A,SERIAL0000,1.0",
            "MEAS:VOLT?": "1.0",
            "MEAS:CURR?": "0.05",
        }[command]

    def write(self, command: str) -> None:
        self.writes.append(command)


def test_worker_live_requests_use_core_exact_scope_and_policy_error_code(tmp_path, monkeypatch):
    accepted_session = FakeWorkerLiveSession()
    monkeypatch.setattr(worker_mod, "open_resource", lambda *args, **kwargs: accepted_session)

    accepted = _run_worker_job_for_test(
        tmp_path,
        command="measure",
        arguments={"channel": 1},
    )

    assert accepted["ok"] is True
    assert accepted_session.queries == ["*IDN?", "MEAS:VOLT?", "MEAS:CURR?"]
    assert accepted_session.closed is True

    rejected_session = FakeWorkerLiveSession()
    monkeypatch.setattr(worker_mod, "open_resource", lambda *args, **kwargs: rejected_session)

    rejected = _run_worker_job_for_test(
        tmp_path,
        command="measure-all",
        arguments={},
    )

    assert rejected["ok"] is False
    assert rejected["error"]["type"] == "validation"
    assert rejected["error"]["code"] == "unsupported_live_scope"
    assert rejected_session.queries == ["*IDN?"]
    assert rejected_session.writes == []
    assert rejected_session.closed is True


def test_write_json_artifact_atomic_publishes_complete_json_and_cleans_temp(tmp_path):
    result_path = tmp_path / "result.json"
    payload = {"ok": True, "data": {"value": 1}}

    _write_json_artifact_atomic(result_path, payload)

    assert json.loads(result_path.read_text(encoding="utf-8")) == payload
    assert not list(tmp_path.glob(".result.json.*.tmp"))

def test_worker_config_overrides():
    # Test that explicit CLI arguments override config file values
    parser = build_parser()
    args = parser.parse_args(["worker", "--id", "custom_id", "--mode", "live", "--control-port", "9999"])
    config = load_worker_config(args)
    assert config["id"] == "custom_id"
    assert config["mode"] == "live"
    assert config["control_port"] == 9999
    assert config["control_host"] == "127.0.0.1"


def test_worker_serial_settings_pass_through_to_runtime(tmp_path, monkeypatch):
    config = {
        "id": "power_1",
        "type": "power",
        "enabled": True,
        "mode": "live",
        "control_host": "127.0.0.1",
        "control_port": 0,
        "artifacts_dir": str(tmp_path),
        "events_jsonl": None,
        "settings": {
            "resource": "ASRL1::INSTR",
            "backend": None,
            "timeout_ms": 5000,
            "serial_options": {
                "baud_rate": 9600,
                "data_bits": 8,
                "read_termination": "CRLF",
                "write_termination": "LF",
            },
            "serial_remote": True,
            "serial_local_on_close": True,
            "safety_config": None,
            "allow_output_writes": False,
        },
    }
    state = WorkerState(config, 0)
    captured = {}

    def fake_run_core_command(request, **kwargs):
        captured["runtime"] = request.runtime
        return {"ok": True}

    monkeypatch.setattr(worker_mod, "run_core_command", fake_run_core_command)

    _run_job_impl(
        state,
        {
            "job_id": None,
            "worker_job_id": "job_serial",
            "command": "identify",
            "arguments": {},
            "dir": tmp_path,
        },
    )

    runtime = captured["runtime"]
    assert runtime.serial_options.baud_rate == 9600
    assert runtime.serial_options.data_bits == 8
    assert runtime.serial_options.read_termination == "\r\n"
    assert runtime.serial_options.write_termination == "\n"
    assert runtime.serial_remote is True
    assert runtime.serial_local_on_close is True


@pytest.fixture
def running_worker(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    events_jsonl = tmp_path / "events.jsonl"
    
    parser = build_parser()
    args = parser.parse_args([
        "worker",
        "--id", "test_worker_1",
        "--mode", "simulate",
        "--resource", "USB0::SIM::E36312A::INSTR",
        "--control-port", "0",
        "--artifacts-dir", str(artifacts_dir),
        "--events-jsonl", str(events_jsonl)
    ])
    
    worker_thread = threading.Thread(target=run_worker, args=(args,), daemon=True)
    worker_thread.start()
    
    actual_port = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if events_jsonl.exists():
            lines = events_jsonl.read_text(encoding="utf-8").splitlines()
            for line in lines:
                try:
                    data = json.loads(line)
                    if data.get("event") == "ready":
                        status_url = data.get("status_url")
                        actual_port = int(status_url.split(":")[-1].split("/")[0])
                        break
                except Exception:
                    pass
        if actual_port is not None:
            break
        time.sleep(0.05)
        
    if actual_port is None:
        raise RuntimeError("Worker failed to start or did not emit ready event within timeout")
        
    yield {
        "port": actual_port,
        "artifacts_dir": artifacts_dir,
        "events_jsonl": events_jsonl,
        "thread": worker_thread,
    }
    
    # Graceful stop
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{actual_port}/stop",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as res:
            res.read()
    except Exception:
        pass
    worker_thread.join(timeout=1.5)


def test_worker_status_endpoint(running_worker):
    port = running_worker["port"]
    url = f"http://127.0.0.1:{port}/status"
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data["service"] == "keysight-power"
        assert data["status"] == "ready"
        assert data["queue_size"] == 0
        assert "command_url" in data
        assert "trigger_url" not in data


def test_worker_command_execution(running_worker):
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    events_jsonl = running_worker["events_jsonl"]
    
    url = f"http://127.0.0.1:{port}/command"
    payload = {
        "command": "read-status",
        "arguments": {"channel": "1"}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    with urllib.request.urlopen(req) as response:
        assert response.status == 202
        data = json.loads(response.read().decode("utf-8"))
        assert data["status"] == "accepted"
        job_id = data["worker_job_id"]
        assert Path(data["artifact_path"]).name == job_id
        assert not data["artifact_path"].endswith("result.json")
        
    result_file = artifacts_dir / "jobs" / job_id / "result.json"
    request_file = artifacts_dir / "jobs" / job_id / "request.json"
    
    assert request_file.exists()
    assert "job_id" not in json.loads(request_file.read_text(encoding="utf-8"))
    result_data = _wait_for_json_file(result_file)
    assert result_data["ok"] is True
    assert result_data["worker_job_id"] == job_id
    assert result_data["command"]["name"] == "read-status"
    assert result_data["status"] == "succeeded"


def test_worker_trigger_endpoint_removed(running_worker):
    port = running_worker["port"]
    url = f"http://127.0.0.1:{port}/trigger"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 404


def test_worker_invalid_command(running_worker):
    port = running_worker["port"]
    url = f"http://127.0.0.1:{port}/command"
    payload = {
        "command": "invalid_command_name"
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


@pytest.mark.parametrize("field", ["completion_pulse_mode", "completion_pulse_dwell_ms", "wait_timeout_ms", "poll_ms"])
def test_worker_rejects_removed_ramp_native_fields_before_artifact(running_worker, field):
    url = f"http://127.0.0.1:{running_worker['port']}/command"
    payload = {
        "command": "ramp",
        "arguments": {
            "dry_run": True,
            "channel": 1,
            "start_voltage": 0,
            "stop_voltage": 1,
            "step_voltage": 0.5,
            "current": 0.1,
            field: "native" if field == "completion_pulse_mode" else 10,
        },
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 400
    jobs_dir = running_worker["artifacts_dir"] / "jobs"
    assert not jobs_dir.exists() or not list(jobs_dir.iterdir())


def test_cli_send_command_dry_run_does_not_send_http(capsys):
    exit_code = cli.main(["send-command", "--command", "read-status", "--arguments-json", "{\"dry_run\": true}", "--dry-run", "--json"])
    payload = _last_stdout_json(capsys)
    assert exit_code == 0
    assert payload["request"]["command"] == "read-status"
    assert payload["request"]["arguments"]["dry_run"] is True


def test_cli_lifecycle_status_reads_worker(running_worker, capsys):
    port = str(running_worker["port"])
    exit_code = cli.main(["status", "--port", port, "--json"])
    payload = _last_stdout_json(capsys)
    assert exit_code == 0
    assert payload["service"] == "keysight-power"
    assert payload["status"] == "ready"
    assert "command_url" in payload
    assert "trigger_url" not in payload


def test_cli_send_command_accepts_and_reports_worker_artifact(running_worker, capsys):
    port = str(running_worker["port"])
    exit_code = cli.main([
        "send-command",
        "--port",
        port,
        "--command",
        "read-status",
        "--arguments-json",
        "{\"dry_run\": true}",
        "--json",
    ])
    payload = _last_stdout_json(capsys)
    assert exit_code == 0
    assert payload["status"] == "accepted"
    assert payload["command"] == "read-status"
    assert payload["job_id"] is None
    assert payload["worker_job_id"]
    assert not payload["artifact_path"].endswith("result.json")
    assert payload["ok"] is True
    assert payload["http_status"] == 202
    assert payload["request_sent"] is True


def test_worker_readonly_dry_run_does_not_open_live_resource(tmp_path, monkeypatch):
    artifacts_dir = tmp_path / "artifacts"
    events_jsonl = tmp_path / "events.jsonl"

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("read-only dry-run must not open VISA")

    monkeypatch.setattr(worker_mod, "open_resource", fail_open_resource)
    parser = build_parser()
    args = parser.parse_args([
        "worker",
        "--id", "live_dry_run_worker",
        "--mode", "live",
        "--resource", "USB0::FAKE::E36312A::INSTR",
        "--control-port", "0",
        "--artifacts-dir", str(artifacts_dir),
        "--events-jsonl", str(events_jsonl),
    ])

    worker_thread = threading.Thread(target=run_worker, args=(args,), daemon=True)
    worker_thread.start()

    actual_port = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if events_jsonl.exists():
            for line in events_jsonl.read_text(encoding="utf-8").splitlines():
                data = json.loads(line)
                if data.get("event") == "ready":
                    actual_port = int(data["status_url"].split(":")[-1].split("/")[0])
                    break
        if actual_port is not None:
            break
        time.sleep(0.05)

    try:
        assert actual_port is not None
        req = urllib.request.Request(
            f"http://127.0.0.1:{actual_port}/command",
            data=json.dumps({"command": "read-status", "arguments": {"dry_run": True, "model_profile": "E36312A"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as res:
            job_id = json.loads(res.read().decode("utf-8"))["worker_job_id"]

        result_file = artifacts_dir / "jobs" / job_id / "result.json"
        result_data = _wait_for_json_file(result_file)
        assert result_data["ok"] is True
        assert result_data["execution"]["mode"] == "live"
        assert result_data["execution"]["dry_run"] is True
        assert result_data["execution"]["hardware_touched"] is False
        assert result_data["data"]["plan"]["hardware_touched"] is False
    finally:
        if actual_port is not None:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{actual_port}/stop", data=b"{}", timeout=1.0)
            except Exception:
                pass
        worker_thread.join(timeout=1.0)


def test_worker_measure_all_rejects_channel_filter(running_worker):
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=json.dumps({"command": "measure-all", "arguments": {"channel": 1}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400
    result_data = json.loads(exc_info.value.read().decode("utf-8"))
    assert result_data["error"]["code"] == "argument_error"
    assert "all channels" in result_data["error"]["message"]


@pytest.mark.parametrize("command", ["output-on", "output-off", "output-state", "cycle-output"])
def test_worker_output_commands_accept_all_channel_dry_run(running_worker, command):
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    arguments = {"channel": "all", "dry_run": True, "model_profile": "E36312A"}
    if command == "cycle-output":
        arguments["duration_ms"] = 250
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=json.dumps({"command": command, "arguments": arguments}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req) as res:
        assert res.status == 202
        job_id = json.loads(res.read().decode("utf-8"))["worker_job_id"]

    result_data = _wait_for_json_file(artifacts_dir / "jobs" / job_id / "result.json")
    assert result_data["ok"] is True
    assert result_data["request"]["arguments"]["channel"] == "all"
    assert result_data["request"]["arguments"]["model_profile"] == "E36312A"
    plan = result_data["data"].get("plan", result_data["data"])
    assert plan["target"]["channel"] == "all"
    assert plan["target"]["model_profile"] == "E36312A"


def test_worker_dry_run_missing_model_profile_does_not_default_to_e36312a(tmp_path):
    result = _run_worker_job_for_test(
        tmp_path,
        command="output-on",
        arguments={"channel": 1, "dry_run": True},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "validation"
    assert result["error"]["code"] == "argument_error"
    assert "--dry-run and --simulate require --model or a known deterministic SIM resource" in result["error"]["message"]


def test_worker_dry_run_explicit_e36312a_model_profile_still_works(tmp_path):
    result = _run_worker_job_for_test(
        tmp_path,
        command="output-on",
        arguments={"channel": 1, "dry_run": True, "model_profile": "E36312A"},
    )

    assert result["ok"] is True
    assert result["data"]["target"]["model_profile"] == "E36312A"
    assert result["data"]["target"]["channel"] == 1


def test_worker_dry_run_explicit_e3646a_uses_e3646a_channel_rules(tmp_path):
    result = _run_worker_job_for_test(
        tmp_path,
        command="output-on",
        arguments={"channel": 3, "dry_run": True, "model_profile": "E3646A"},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "validation"
    assert result["error"]["code"] == "argument_error"
    assert "channel 3 is not supported" in result["error"]["message"]
    assert "(1, 2)" in result["error"]["message"]


def test_worker_simulate_model_profile_resource_mismatch_fails(tmp_path):
    result = _run_worker_job_for_test(
        tmp_path,
        command="output-on",
        arguments={"channel": 1, "model_profile": "E3646A"},
        config={
            "id": "test",
            "type": "power",
            "enabled": True,
            "mode": "simulate",
            "control_host": "127.0.0.1",
            "control_port": 0,
            "artifacts_dir": str(tmp_path),
            "events_jsonl": None,
            "settings": {"resource": "USB0::SIM::E36312A::INSTR"},
        },
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "validation"
    assert result["error"]["code"] == "argument_error"
    assert "--model E3646A does not match SIM resource model E36312A" in result["error"]["message"]


def test_worker_result_artifact_write_failure_reports_artifact_error_without_fake_path(tmp_path, monkeypatch):
    config = {
        "id": "artifact_worker",
        "type": "power",
        "enabled": True,
        "mode": "simulate",
        "control_host": "127.0.0.1",
        "control_port": 0,
        "artifacts_dir": str(tmp_path / "artifacts"),
        "events_jsonl": str(tmp_path / "events.jsonl"),
        "settings": {
            "resource": "USB0::SIM::E36312A::INSTR",
        },
    }
    state = WorkerState(config, 0)
    job_dir = tmp_path / "jobs" / "job_artifact_error"
    job_dir.mkdir(parents=True)
    job = {
        "job_id": None,
        "worker_job_id": "job_artifact_error",
        "command": "read-status",
        "arguments": {"dry_run": True},
        "dir": job_dir,
    }

    def fail_artifact_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(worker_mod, "_write_json_artifact_atomic", fail_artifact_write)

    _run_job_impl(state, job)

    assert state.last_job["status"] == "failed"
    assert state.last_job["error"]["code"] == "artifact_error"
    assert state.last_job["artifact_available"] is False
    assert "artifact_path" not in state.last_job
    assert state.last_job["artifact_error"]["code"] == "artifact_error"


def test_worker_rejects_invalid_config_mode(tmp_path):
    cfg = tmp_path / "worker.json"
    cfg.write_text(json.dumps({"mode": "preview"}), encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(["worker", "--config", str(cfg)])

    with pytest.raises(ValueError, match="Worker mode"):
        load_worker_config(args)


def test_worker_rejects_invalid_default_action(tmp_path):
    cfg = tmp_path / "worker.json"
    cfg.write_text(
        json.dumps({"settings": {"default_action": {"command": "sequence", "parameters": {}}}}),
        encoding="utf-8",
    )
    parser = build_parser()
    args = parser.parse_args(["worker", "--config", str(cfg)])

    with pytest.raises(ValueError, match="default_action is not supported"):
        load_worker_config(args)


def test_worker_live_output_sequence_validation(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    events_jsonl = tmp_path / "events.jsonl"
    
    parser = build_parser()
    args = parser.parse_args([
        "worker",
        "--id", "live_worker_1",
        "--mode", "live",
        "--resource", "USB0::SIM::E36312A::INSTR",
        "--control-port", "0",
        "--artifacts-dir", str(artifacts_dir),
        "--events-jsonl", str(events_jsonl)
    ])
    
    worker_thread = threading.Thread(target=run_worker, args=(args,), daemon=True)
    worker_thread.start()
    
    actual_port = None
    for _ in range(50):
        if events_jsonl.exists():
            lines = events_jsonl.read_text(encoding="utf-8").splitlines()
            for line in lines:
                data = json.loads(line)
                if data.get("event") == "ready":
                    actual_port = int(data.get("status_url").split(":")[-1].split("/")[0])
                    break
        if actual_port:
            break
        time.sleep(0.05)
        
    try:
        url = f"http://127.0.0.1:{actual_port}/command"
        payload = {
            "command": "sequence",
            "arguments": {
                "document": {
                    "version": 1,
                    "steps": [
                        {"index": 1, "action": "set", "channel": 1, "voltage": 2.0, "current": 0.1}
                    ]
                }
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 409
        result_data = json.loads(exc_info.value.read().decode("utf-8"))
        assert result_data["reason"] == "output_changes_not_allowed"
        
    finally:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{actual_port}/stop", data=b"{}", timeout=1.0)
        except Exception:
            pass
        worker_thread.join(timeout=1.0)


def test_worker_simulate_numeric_parity(running_worker):
    # Verify simulate mode queries values from the core simulator (1.1, 2.2, 3.3 V for measure-all)
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    
    url = f"http://127.0.0.1:{port}/command"
    payload = {
        "command": "measure-all"
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as res:
        assert res.status == 202
        job_id = json.loads(res.read().decode("utf-8"))["worker_job_id"]
        
    result_file = artifacts_dir / "jobs" / job_id / "result.json"
    result_data = _wait_for_json_file(result_file)
    assert result_data["ok"] is True
    assert result_data["status"] == "succeeded"
    
    # Parity check: channel measurements match exactly the simulated responses of SimulatedResource
    channels = result_data["data"]["channels"]
    assert len(channels) == 3
    assert channels[0]["channel"] == 1
    assert channels[0]["measurements"]["voltage"] == 1.1
    assert channels[1]["channel"] == 2
    assert channels[1]["measurements"]["voltage"] == 2.2
    assert channels[2]["channel"] == 3
    assert channels[2]["measurements"]["voltage"] == 3.3


def test_worker_model_unsupported_error_mapping(running_worker):
    # Verify unsupported models correctly propagate validation/unsupported error rather than connection_failed
    # EDU36311A does not support measure-all command!
    # Let's change the worker config's resource dynamically, or start an EDU36311A simulated worker
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    
    # Start separate worker for EDU36311A simulate
    parser = build_parser()
    edu_art_dir = artifacts_dir / "edu_art"
    args = parser.parse_args([
        "worker",
        "--id", "edu_worker",
        "--mode", "simulate",
        "--resource", "USB0::SIM::EDU36311A::INSTR",
        "--control-port", "0",
        "--artifacts-dir", str(edu_art_dir)
    ])
    
    edu_thread = threading.Thread(target=run_worker, args=(args,), daemon=True)
    edu_thread.start()
    
    # Find actual port of EDU worker
    edu_port = None
    deadline = time.monotonic() + 5.0
    edu_jsonl = edu_art_dir / "events.jsonl"
    while time.monotonic() < deadline:
        if edu_jsonl.exists():
            lines = edu_jsonl.read_text(encoding="utf-8").splitlines()
            for line in lines:
                try:
                    data = json.loads(line)
                    if data.get("event") == "ready":
                        edu_port = int(data.get("status_url").split(":")[-1].split("/")[0])
                        break
                except Exception:
                    pass
        if edu_port is not None:
            break
        time.sleep(0.05)
        
    try:
        url = f"http://127.0.0.1:{edu_port}/command"
        payload = {"command": "measure-all"}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as res:
            job_id = json.loads(res.read().decode("utf-8"))["worker_job_id"]
            
        result_file = edu_art_dir / "jobs" / job_id / "result.json"
        result_data = _wait_for_json_file(result_file)
        assert result_data["ok"] is False
        assert result_data["status"] == "failed"
        assert result_data["error"]["type"] == "validation"
        assert result_data["error"]["code"] == "unsupported_model_for_measure_all"
        
    finally:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{edu_port}/stop", data=b"{}", timeout=1.0)
        except Exception:
            pass
        edu_thread.join(timeout=1.0)


def test_worker_stop_shutdown_lifecycle(tmp_path):
    # Verify POST /stop terminates the server gracefully and shuts down the worker process
    artifacts_dir = tmp_path / "artifacts"
    events_jsonl = tmp_path / "events.jsonl"
    
    parser = build_parser()
    args = parser.parse_args([
        "worker",
        "--id", "lifecycle_worker",
        "--mode", "simulate",
        "--control-port", "0",
        "--artifacts-dir", str(artifacts_dir),
        "--events-jsonl", str(events_jsonl)
    ])
    
    worker_thread = threading.Thread(target=run_worker, args=(args,), daemon=True)
    worker_thread.start()
    
    actual_port = None
    for _ in range(50):
        if events_jsonl.exists():
            lines = events_jsonl.read_text(encoding="utf-8").splitlines()
            for line in lines:
                data = json.loads(line)
                if data.get("event") == "ready":
                    actual_port = int(data.get("status_url").split(":")[-1].split("/")[0])
                    break
        if actual_port:
            break
        time.sleep(0.05)
        
    # Query status (should work)
    url = f"http://127.0.0.1:{actual_port}/status"
    with urllib.request.urlopen(url) as res:
        assert res.status == 200
        
    # Send stop
    stop_url = f"http://127.0.0.1:{actual_port}/stop"
    req = urllib.request.Request(stop_url, data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        
    # Thread should join cleanly within a very short time
    worker_thread.join(timeout=2.0)
    assert not worker_thread.is_alive()

    events = [
        json.loads(line)
        for line in events_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cleanup_events = [event for event in events if event["event"] == "power_cleanup"]
    assert [(event["cleanup"]["operation"], event["cleanup"]["status"]) for event in cleanup_events] == [
        ("release_to_local", "not_applicable"),
        ("close_session", "not_applicable"),
        ("cleanup_release_to_local", "succeeded"),
    ]
    assert events[-1]["event"] == "summary"
    assert events[-1]["ok"] is True
    
    # Connection should now fail
    with pytest.raises(Exception):
        urllib.request.urlopen(url, timeout=0.1)


def test_sequence_stop_wait_interrupt(running_worker):
    # Verify sequence wait steps can be interrupted quickly by stop requests
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    
    url = f"http://127.0.0.1:{port}/command"
    payload = {
        "command": "sequence",
        "arguments": {
            "document": {
                "version": 1,
                "steps": [
                    {"index": 1, "action": "wait", "seconds": 10.0} # Long 10s wait
                ]
            }
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as res:
        job_id = json.loads(res.read().decode("utf-8"))["worker_job_id"]
        
    # Wait briefly for job to start
    time.sleep(0.2)
    
    # Trigger stop immediately
    stop_url = f"http://127.0.0.1:{port}/stop"
    stop_req = urllib.request.Request(stop_url, data=b"{}", headers={"Content-Type": "application/json"})
    start_time = time.perf_counter()
    with urllib.request.urlopen(stop_req, timeout=1.0) as res:
        assert res.status == 200
        
    result_file = artifacts_dir / "jobs" / job_id / "result.json"
    result_data = _wait_for_json_file(result_file)

    duration = time.perf_counter() - start_time
    # It must have stopped extremely quickly, way before the 10 seconds timeout!
    assert duration < 1.5
    
    assert result_data["ok"] is False
    assert result_data["status"] == "cancelled"
    assert result_data["error"]["code"] == "stopped"


def test_worker_ramp_list_requires_document_or_file():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": "ramp-list", "arguments": {}},
        state,
    )

    assert status == 400
    assert payload["error"]["code"] == "argument_error"


def test_worker_rejects_invalid_static_parameter_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": "set", "arguments": {"channel": 1, "voltage": -1, "current": 0.1}},
        state,
    )

    assert status == 400
    assert "voltage" in payload["error"]["message"]
    assert state.next_job is None


def test_worker_accepts_partial_set_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": "set", "arguments": {"channel": 1, "voltage": 1.0, "dry_run": True}},
        state,
    )

    assert status == 202
    assert payload["arguments"]["voltage"] == 1.0
    assert "current" not in payload["arguments"]


def test_worker_rejects_empty_set_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": "set", "arguments": {"channel": 1, "dry_run": True}},
        state,
    )

    assert status == 400
    assert "set requires voltage, current, or both" in payload["error"]["message"]
    assert state.next_job is None


def test_worker_rejects_arm_only_trigger_list_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": "trigger-list", "arguments": {"channel": 1, "source": "bus"}},
        state,
    )

    assert status == 400
    assert payload["error"]["code"] == "argument_error"
    assert "leave_trigger_configured=true" in payload["error"]["message"]
    assert state.next_job is None


@pytest.mark.parametrize(
    ("command", "arguments", "message"),
    [
        ("trigger-step", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-list", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-step", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "immediate"}, "started without wait_complete=true"),
        ("trigger-list", {"source": "bus", "fire": True}, "started without wait_complete=true"),
    ],
)
def test_worker_rejects_invalid_trigger_control_before_enqueue(command, arguments, message):
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": command, "arguments": {"channel": 1, **arguments}},
        state,
    )

    assert status == 400
    assert payload["error"]["code"] == "argument_error"
    assert message in payload["error"]["message"]
    assert state.next_job is None


def test_worker_rejects_trigger_fire_wait_without_abort_target_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {"command": "trigger-fire", "arguments": {"wait_complete": True}},
        state,
    )

    assert status == 400
    assert payload["error"]["code"] == "argument_error"
    assert "abort target" in payload["error"]["message"]
    assert state.next_job is None


def test_worker_rejects_trigger_list_pulse_without_output_pins_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {
            "command": "trigger-list",
            "arguments": {
                "channel": 1, "source": "immediate", "wait_complete": True,
                "voltage_list": [0, 1], "current_list": [0.05, 0.05], "dwell_list": [0.01, 0.01],
                "bost_list": [True, False], "eost_list": [False, False],
            },
        },
        state,
    )

    assert status == 400
    assert payload["error"]["code"] == "argument_error"
    assert "explicit trigger_output_pins" in payload["error"]["message"]
    assert state.next_job is None


def test_worker_ramp_list_rejects_invalid_document_before_enqueue():
    config = {"mode": "simulate", "settings": {}, "id": "test", "artifacts_dir": "."}
    state = WorkerState(config, 0)

    status, payload = worker_mod._validate_command_body(
        {
            "command": "ramp-list",
            "arguments": {
                "document": {
                    "kind": "keysight-power-ramp-list",
                    "version": 1,
                    "segments": [],
                }
            },
        },
        state,
    )

    assert status == 400
    assert payload["error"]["code"] == "argument_error"
    assert state.next_job is None


def test_worker_live_ramp_list_requires_output_confirmation():
    config = {
        "mode": "live",
        "settings": {"allow_output_writes": True},
        "id": "test",
        "artifacts_dir": ".",
    }
    state = WorkerState(config, 0)
    status, payload = worker_mod._validate_command_body(
        {
            "command": "ramp-list",
            "arguments": {
                "document": {
                    "kind": "keysight-power-ramp-list",
                    "version": 1,
                    "segments": [
                        {
                            "channel": 1,
                            "current": 0.1,
                            "start_voltage": 0,
                            "stop_voltage": 1,
                            "step_voltage": 0.5,
                            "delay_ms": 0,
                            "hold_ms": 0,
                        }
                    ],
                }
            },
        },
        state,
    )

    assert status == 409
    assert payload["reason"] == "output_confirmation_required"


def test_worker_simulate_ramp_list_document(running_worker):
    port = running_worker["port"]
    artifacts_dir = running_worker["artifacts_dir"]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=json.dumps(
            {
                "command": "ramp-list",
                "arguments": {
                    "document": {
                        "kind": "keysight-power-ramp-list",
                        "version": 1,
                        "segments": [
                            {
                                "channel": 1,
                                "current": 0.1,
                                "start_voltage": 0,
                                "stop_voltage": 1,
                                "step_voltage": 0.5,
                                "delay_ms": 0,
                                "hold_ms": 0,
                            }
                        ],
                    }
                },
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        worker_job_id = json.loads(response.read().decode("utf-8"))["worker_job_id"]

    result = _wait_for_json_file(artifacts_dir / "jobs" / worker_job_id / "result.json")

    assert result["ok"] is True
    assert result["command"] == {"name": "ramp-list"}
    assert result["data"]["status"] == "planned"
    assert result["data"]["segment_count"] == 1
