"""keysight-power worker daemon implementation."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import os
import time
import uuid
import threading
from pathlib import Path
from typing import Any, Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from keysight_power_core.connection import open_resource
from keysight_power_core.core import (
    RuntimeOptions,
    OperationRequest,
    TriggerRequest,
    SequenceRequest,
    CoreValidationError,
    UnsupportedModelError,
    UnsupportedChannelError,
    ConfirmationRequiredError,
    CommandCancelled,
    CoreIoError,
    StopCleanupError,
)
from keysight_power_core.command_runner import run_core_command
from keysight_power_core.ramp_list import ramp_list_document_for_request, ramp_list_plan
from keysight_power_core.sequence import load_sequence_document, sequence_plan
from keysight_power_core.stop_cleanup import StopCleanupResult

READ_ONLY_COMMANDS = {
    "identify",
    "read-status",
    "readback",
    "measure",
    "measure-all",
    "output-state",
    "protection-status",
    "error",
    "snapshot",
}
OUTPUT_COMMANDS = {
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "cycle-output",
    "ramp",
    "ramp-list",
    "smoke-output",
}
PROTECTION_COMMANDS = {"protection-set", "clear-protection", "restore-from-snapshot", "sequence"}
TRIGGER_COMMANDS = {
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
}
ALLOWED_COMMANDS = READ_ONLY_COMMANDS | OUTPUT_COMMANDS | PROTECTION_COMMANDS | TRIGGER_COMMANDS
OUTPUT_AFFECTING_COMMANDS = OUTPUT_COMMANDS | {"protection-set", "clear-protection", "restore-from-snapshot", "sequence"}
REQUEST_KEYS = {"command", "arguments", "job_id"}

_event_lock = threading.Lock()
_sequence_counter = 1


class WorkerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def emit_event(config: dict[str, Any], event_name: str, extra: dict[str, Any] | None = None) -> None:
    """Thread-safe event logger writing both to stdout and to events_jsonl file."""
    global _sequence_counter
    with _event_lock:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": 1,
            "event": event_name,
            "worker_id": config["id"],
            "type": "power",
            "timestamp_utc": timestamp,
            "sequence": _sequence_counter,
        }
        if extra:
            payload.update(extra)
        _sequence_counter += 1

        encoded = json.dumps(payload, sort_keys=True)
        print(encoded, flush=True)

        events_file = config.get("events_jsonl")
        if events_file:
            try:
                p = Path(events_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(encoded + "\n")
            except Exception as exc:
                print(f"worker event log write failed: {exc}", file=sys.stderr, flush=True)


def _write_json_artifact_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Publish a JSON artifact only after its full contents are durable."""
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _command_response(status: str, command: Any, job_id: Any, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "command": command, "job_id": job_id}
    payload.update(extra)
    return payload


def _validate_command_body(body: Any, state: "WorkerState") -> tuple[int, dict[str, Any]]:
    if not isinstance(body, dict):
        return 400, _command_response(
            "error",
            None,
            None,
            error={"code": "invalid_request", "message": "POST /command body must be a JSON object"},
        )
    unknown = sorted(set(body) - REQUEST_KEYS)
    command = body.get("command")
    job_id = body.get("job_id")
    if unknown:
        return 400, _command_response(
            "error",
            command if isinstance(command, str) else None,
            job_id if isinstance(job_id, str) else None,
            error={"code": "unknown_field", "message": f"Unknown top-level field(s): {', '.join(unknown)}"},
        )
    if not isinstance(command, str) or not command:
        return 400, _command_response(
            "error",
            command if isinstance(command, str) else None,
            job_id if isinstance(job_id, str) else None,
            error={"code": "missing_command", "message": "POST /command requires a non-empty string command"},
        )
    if command not in ALLOWED_COMMANDS:
        return 400, _command_response(
            "error",
            command,
            job_id if isinstance(job_id, str) else None,
            error={"code": "invalid_command", "message": f"Command {command!r} is not allowed. Supported: {sorted(ALLOWED_COMMANDS)}"},
        )
    arguments = body.get("arguments", {})
    if not isinstance(arguments, dict):
        return 400, _command_response(
            "error",
            command,
            job_id if isinstance(job_id, str) else None,
            error={"code": "invalid_arguments", "message": "arguments must be a JSON object"},
        )
    if job_id is not None and not isinstance(job_id, str):
        return 400, _command_response(
            "error",
            command,
            None,
            error={"code": "invalid_job_id", "message": "job_id must be a string when provided"},
        )
    if "dry_run" in arguments and not isinstance(arguments["dry_run"], bool):
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "arguments.dry_run must be boolean"})
    if "confirm_output" in arguments and not isinstance(arguments["confirm_output"], bool):
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "arguments.confirm_output must be boolean"})
    if "channel" in arguments:
        channel = arguments["channel"]
        if channel != "all":
            try:
                parsed = int(channel)
            except (TypeError, ValueError):
                return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "channel must be a positive integer or 'all'"})
            if parsed <= 0:
                return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "channel must be a positive integer or 'all'"})
            arguments = {**arguments, "channel": parsed}
    if command == "measure-all" and "channel" in arguments:
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "measure-all always reads all channels and does not accept channel"})
    if command == "sequence" and "file" not in arguments and "document" not in arguments:
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "sequence requires file or document argument"})
    if command == "ramp-list" and "file" not in arguments and "document" not in arguments:
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "ramp-list requires file or document argument"})
    if command == "ramp-list":
        settings = state.config.get("settings", {})
        validation_request = OperationRequest(
            command="ramp-list",
            runtime=RuntimeOptions(
                resource=settings.get("resource"),
                resource_alias=settings.get("resource_alias"),
                safety_config=settings.get("safety_config"),
                dry_run=True,
            ),
            parameters={key: value for key, value in arguments.items() if key not in {"dry_run", "confirm_output"}},
        )
        try:
            ramp_list_plan(validation_request, ramp_list_document_for_request(validation_request))
        except (CoreValidationError, OSError, ValueError) as exc:
            return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": str(exc)})
    if command == "restore-from-snapshot" and "snapshot" not in arguments and "document" not in arguments:
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "restore-from-snapshot requires snapshot or document argument"})
    dry_run = bool(arguments.get("dry_run", False))
    confirm_output = bool(arguments.get("confirm_output", False))
    if command in OUTPUT_AFFECTING_COMMANDS and state.config["mode"] == "live" and not dry_run:
        if not state.config.get("settings", {}).get("allow_output_writes", False):
            return 409, _command_response("rejected", command, job_id, reason="output_changes_not_allowed", error={"code": "output_changes_not_allowed", "message": "live output-affecting commands require settings.allow_output_writes=true"})
        if not confirm_output:
            return 409, _command_response("rejected", command, job_id, reason="output_confirmation_required", error={"code": "output_confirmation_required", "message": "live output-affecting commands require arguments.confirm_output=true"})
    return 202, {"command": command, "arguments": arguments, **({"job_id": job_id} if job_id is not None else {})}


class WorkerState:
    """Thread-safe worker daemon state tracker."""
    def __init__(self, config: dict[str, Any], port: int) -> None:
        self.config = config
        self.port = port
        self.status = "ready"  # ready|busy|stopping|error
        self.active_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.fatal_error: dict[str, Any] | None = None
        self.lock = threading.Condition()
        self.shutdown_event = threading.Event()
        self.stop_event = threading.Event()
        self.next_job: dict[str, Any] | None = None
        self.shutdown_flag = False
        self.server: WorkerHTTPServer | None = None
        self.run_id = str(uuid.uuid4())
        self.cleanup_results: list[dict[str, str]] = []
        self.cleanup_failed = False

        if config["mode"] == "simulate":
            from keysight_power_core.testing.simulator import SimulatedResourceManager
            self.sim_mgr = SimulatedResourceManager()
        else:
            self.sim_mgr = None


class WorkerHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for local control API endpoints."""
    protocol_version = "HTTP/1.1"
    server: WorkerHTTPServer

    @property
    def state(self) -> WorkerState:
        return self.server.state

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default server log to keep stdout clean for JSONL events
        pass

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        try:
            body = json.dumps(data, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
        except Exception:
            pass

    def do_GET(self) -> None:
        state = self.state
        if self.path == "/status":
            with state.lock:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                res = {
                    "schema_version": 1,
                    "service": "keysight-power",
                    "run_id": state.run_id,
                    "status": state.status,
                    "command_url": f"http://127.0.0.1:{state.port}/command",
                    "stop_url": f"http://127.0.0.1:{state.port}/stop",
                    "status_url": f"http://127.0.0.1:{state.port}/status",
                    "queue_size": 1 if state.next_job is not None else 0,
                    "active_job": state.active_job,
                    "last_job": state.last_job,
                    "fatal_error": state.fatal_error,
                    "timestamp_utc": now,
                }
            self._send_json(200, res)
        else:
            self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "Endpoint not found"}})

    def do_POST(self) -> None:
        state = self.state
        content_length = int(self.headers.get("Content-Length", 0))
        body_data: dict[str, Any] = {}
        if content_length > 0:
            try:
                body_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": {"code": "invalid_json", "message": f"Invalid JSON body: {exc}"}})
                return

        if self.path == "/stop":
            # The handler only publishes cooperative stop state and wakes the runner.
            reason = body_data.get("reason", "manual stop")
            state.stop_event.set()
            emit_event(state.config, "stop_requested", {"reason": reason})
            with state.lock:
                state.shutdown_flag = True
                state.lock.notify_all()
            self._send_json(200, {"ok": True, "message": "Stop requested"})
            return

        if self.path == "/command":
            validation = _validate_command_body(body_data, state)
            if validation[0] != 202:
                self._send_json(validation[0], validation[1])
                return
            body_data = validation[1]
            cmd = body_data["command"]
            arguments = body_data["arguments"]
            client_job_id = body_data.get("job_id")

            with state.lock:
                if state.status != "ready":
                    self._send_json(409, {
                        "status": "rejected",
                        "command": cmd,
                        "job_id": client_job_id,
                        "reason": "busy",
                        "error": {"code": "busy", "message": "Worker is currently busy processing a job"},
                        "active_job": state.active_job
                    })
                    return

                # Save request artifact immediately (strictly block if fails)
                worker_job_id = f"job_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                job_dir = Path(state.config["artifacts_dir"]) / "jobs" / worker_job_id
                try:
                    job_dir.mkdir(parents=True, exist_ok=True)
                    artifact_request = {"command": cmd, "arguments": arguments}
                    (job_dir / "request.json").write_text(json.dumps(artifact_request, indent=2, sort_keys=True), encoding="utf-8")
                except Exception as exc:
                    self._send_json(500, {"status": "error", "command": cmd, "job_id": client_job_id, "error": {"code": "artifact_error", "message": f"Could not create job directory or request artifact: {exc}"}})
                    return

                # Transition to busy
                state.status = "busy"
                artifact_path = str(job_dir.resolve())
                now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                state.active_job = {
                    "job_id": client_job_id,
                    "worker_job_id": worker_job_id,
                    "command": cmd,
                    "status": "queued",
                    "artifact_path": artifact_path,
                    "accepted_at": now,
                }

                state.next_job = {
                    "job_id": client_job_id,
                    "worker_job_id": worker_job_id,
                    "command": cmd,
                    "arguments": arguments,
                    "dir": job_dir,
                }
                state.lock.notify_all()

            emit_event(state.config, "job_accepted", {"job_id": client_job_id, "worker_job_id": worker_job_id, "command": cmd, "run_id": state.run_id})
            self._send_json(202, {
                "status": "accepted",
                "command": cmd,
                "job_id": client_job_id,
                "worker_job_id": worker_job_id,
                "artifact_path": str(job_dir.resolve()),
            })
        else:
            self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "Endpoint not found"}})


def request_worker_shutdown(server: WorkerHTTPServer, state: WorkerState) -> None:
    """Helper to cleanly stop the server loop from any thread without deadlocking."""
    with state.lock:
        if state.status != "stopping":
            state.status = "stopping"
            emit_event(state.config, "worker_stopping")
    threading.Thread(target=server.shutdown, daemon=True).start()


def record_cleanup_result(state: WorkerState, result: StopCleanupResult) -> None:
    payload = result.to_dict()
    with state.lock:
        state.cleanup_results.append(payload)
        if result.status == "failed":
            state.cleanup_failed = True
            state.status = "error"
    emit_event(state.config, "power_cleanup", {"run_id": state.run_id, "cleanup": payload})


def record_no_session_stop_cleanup(state: WorkerState) -> None:
    if state.cleanup_results:
        return
    record_cleanup_result(
        state,
        StopCleanupResult("release_to_local", "not_applicable", "no open VISA session"),
    )
    record_cleanup_result(
        state,
        StopCleanupResult("close_session", "not_applicable", "no open VISA session"),
    )
    record_cleanup_result(
        state,
        StopCleanupResult("cleanup_release_to_local", "succeeded", "post-close cleanup recorded release_to_local=not_applicable"),
    )


def get_opener(state: WorkerState) -> Callable[..., Any]:
    """Return a connection opener that correctly utilizes simulated or live PyVISA resources."""
    if state.sim_mgr is not None:
        def opener(resource: str, resource_manager: Any = None, *, backend: str | None = None, timeout_ms: int = 5000) -> Any:
            return open_resource(resource, state.sim_mgr, backend=backend, timeout_ms=timeout_ms)
        return opener
    else:
        def opener(resource: str, resource_manager: Any = None, *, backend: str | None = None, timeout_ms: int = 5000) -> Any:
            return open_resource(resource, backend=backend, timeout_ms=timeout_ms)
        return opener


def job_runner(state: WorkerState) -> None:
    """Asynchronous job processing loop running in a dedicated background thread."""
    while not state.shutdown_event.is_set():
        job = None
        with state.lock:
            while state.next_job is None and not state.shutdown_event.is_set() and not state.shutdown_flag:
                state.lock.wait(timeout=0.05)
            if state.shutdown_event.is_set():
                break
            if state.shutdown_flag and state.next_job is None:
                record_no_session_stop_cleanup(state)
                request_worker_shutdown(state.server, state)
                break
            job = state.next_job
            state.next_job = None

        if job:
            state.stop_event.clear()
            _run_job_impl(state, job)

            should_shutdown = False
            with state.lock:
                state.active_job = None
                if state.cleanup_failed:
                    state.status = "error"
                elif state.status == "busy":
                    state.status = "ready"
                should_shutdown = state.shutdown_flag

            if should_shutdown:
                record_no_session_stop_cleanup(state)
                request_worker_shutdown(state.server, state)


def _run_job_impl(state: WorkerState, job: dict[str, Any]) -> None:
    config = state.config
    settings = config.get("settings", {})
    cmd = job["command"]
    client_job_id = job.get("job_id")
    worker_job_id = job.get("worker_job_id", client_job_id)
    arguments = job.get("arguments", {})
    job_dir: Path = job["dir"]

    with state.lock:
        if state.active_job is not None and state.active_job.get("worker_job_id") == worker_job_id:
            state.active_job = {
                **state.active_job,
                "status": "running",
                "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
    emit_event(config, "job_started", {"job_id": client_job_id, "worker_job_id": worker_job_id, "command": cmd, "run_id": state.run_id})

    params = {key: value for key, value in arguments.items() if key not in {"dry_run", "confirm_output"}}
    confirm_req = bool(arguments.get("confirm_output", False))
    dry_run_req = bool(arguments.get("dry_run", False))

    # Initialize RuntimeOptions
    runtime = RuntimeOptions(
        resource=settings.get("resource"),
        resource_alias=settings.get("resource_alias"),
        safety_config=settings.get("safety_config"),
        simulate=(config["mode"] == "simulate"),
        dry_run=dry_run_req,
        backend=settings.get("backend"),
        timeout_ms=settings.get("timeout_ms", 5000),
        confirm=confirm_req,
    )

    opener = get_opener(state)
    start_perf = time.perf_counter()
    result_data: dict[str, Any] | None = None
    warnings: list[dict[str, str]] = []
    error_payload: dict[str, Any] | None = None
    ok = True
    exc_obj: Exception | None = None
    final_status = "succeeded"
    cleanup_results: list[dict[str, str]] = []

    def report_cleanup(result: StopCleanupResult) -> None:
        payload = result.to_dict()
        cleanup_results.append(payload)
        record_cleanup_result(state, result)
        if result.status == "unsupported":
            warnings.append({"code": "cleanup_unsupported", "message": result.message})

    try:
        if cmd == "sequence":
            doc = params.get("document")
            if doc is None:
                fp = params.get("file")
                if fp is not None:
                    doc = load_sequence_document(str(fp))
                else:
                    raise CoreValidationError("sequence requires file or document parameter")

            # Output-affecting double-confirmation check
            if doc is not None:
                plan_req = SequenceRequest(command="sequence", runtime=runtime, parameters=params)
                plan = sequence_plan(plan_req, doc)
                has_writes = any(
                    step.get("action") in {
                        "set", "apply", "output-on", "output-off", "safe-off", "cycle-output", "ramp", "smoke-output", "trigger-pulse"
                    }
                    for step in plan.get("steps", [])
                )

                if has_writes and config["mode"] == "live" and not runtime.dry_run:
                    allow_writes = settings.get("allow_output_writes", False)
                    if not allow_writes or not confirm_req:
                        raise ConfirmationRequiredError(
                            "live output-affecting sequence requires both config allow_output_writes=true "
                            "and request confirm=true"
                        )

            req = SequenceRequest(command="sequence", runtime=runtime, parameters=params)
        elif cmd.startswith("trigger-"):
            req = TriggerRequest(command=cmd, runtime=runtime, parameters=params)
        else:
            req = OperationRequest(command=cmd, runtime=runtime, parameters=params)

        result_data = run_core_command(
            req,
            opener=opener,
            stop_requested=lambda: state.stop_event.is_set(),
            cleanup_reporter=report_cleanup,
        )
        if cmd == "sequence":
            if result_data.get("status") == "stopped":
                raise KeyboardInterrupt("sequence wait interrupted")
            if result_data.get("status") == "failed":
                failed_step = result_data.get("failed_step") or {}
                msg = failed_step.get("message", "step failed")
                raise ValueError(f"sequence step failed: {msg}")
        if cmd == "ramp-list":
            if result_data.get("status") == "stopped":
                raise KeyboardInterrupt("ramp-list execution interrupted")
            if result_data.get("status") == "failed":
                failed_segment = result_data.get("failed_segment") or {}
                msg = failed_segment.get("message", "segment failed")
                raise ValueError(f"ramp-list segment {failed_segment.get('index')} failed: {msg}")

    except (Exception, KeyboardInterrupt) as exc:
        ok = False
        exc_obj = exc
        err_type = "execution"
        code = "execution_failed"
        retryable = True

        # Mapping core exceptions correctly using isinstance
        if isinstance(exc, CoreValidationError):
            err_type = "validation"
            if isinstance(exc, ConfirmationRequiredError):
                code = "confirmation_required"
            elif isinstance(exc, UnsupportedModelError):
                code = f"unsupported_model_for_{cmd.replace('-', '_')}"
            elif isinstance(exc, UnsupportedChannelError):
                code = "argument_error"
            else:
                code = "argument_error"
            retryable = False
        elif isinstance(exc, CoreIoError):
            err_type = "io"
            code = "io_failed"
            if getattr(exc, "opened", False) is False:
                code = "connection_failed"
            retryable = True
        elif isinstance(exc, StopCleanupError):
            err_type = "io"
            code = "cleanup_failed"
            retryable = True
        elif isinstance(exc, (CommandCancelled, KeyboardInterrupt)) or exc.__class__.__name__ in {"TriggerInterrupted", "SequenceStopped"} or state.stop_event.is_set():
            err_type = "execution"
            code = "stopped"
            retryable = True

        error_payload = {
            "type": err_type,
            "code": code,
            "message": "Execution was stopped by user request" if isinstance(exc, KeyboardInterrupt) else str(exc),
            "retryable": retryable,
        }
        final_status = "cancelled" if code == "stopped" else "failed"

    duration_ms = round((time.perf_counter() - start_perf) * 1000, 3)

    # Determine hardware_touched
    hardware_touched = False
    if config["mode"] == "live" and not runtime.dry_run:
        if ok:
            hardware_touched = True
        elif cmd == "ramp-list" and result_data is not None:
            hardware_touched = True
        elif exc_obj is not None:
            # Touched hardware only if we opened the VISA connection successfully
            if not isinstance(exc_obj, CoreValidationError) and getattr(exc_obj, "opened", False):
                hardware_touched = True

    # Compile CLI JSON contract compliant envelope
    envelope = {
        "schema_version": 1,
        "run_id": state.run_id,
        "worker_job_id": worker_job_id,
        "ok": ok,
        "status": final_status,
        "command": {"name": cmd},
        "execution": {
            "mode": config["mode"],
            "dry_run": runtime.dry_run,
            "hardware_touched": hardware_touched,
        },
        "request": {"command": cmd, "arguments": arguments},
        "data": result_data if ok else None,
        "warnings": warnings,
        "error": error_payload,
        "metadata": {
            "duration_ms": duration_ms,
            "cleanup": cleanup_results,
        },
    }

    # Write result artifact. If the write fails, do not advertise an artifact path.
    result_path = job_dir / "result.json"
    artifact_path: str | None = str(result_path.resolve())
    artifact_error: dict[str, Any] | None = None
    try:
        _write_json_artifact_atomic(result_path, envelope)
    except Exception as exc:
        ok = False
        artifact_error = {
            "type": "io",
            "code": "artifact_error",
            "message": f"Could not write job result artifact: {exc}",
            "retryable": False,
        }
        error_payload = artifact_error
        envelope["ok"] = False
        envelope["status"] = "failed"
        envelope["error"] = error_payload
        final_status = "failed"
        try:
            _write_json_artifact_atomic(result_path, envelope)
        except Exception:
            artifact_path = None

    # Emit completion events
    artifact_dir = str(job_dir.resolve())
    if ok:
        event_payload = {
            "job_id": client_job_id,
            "worker_job_id": worker_job_id,
            "command": cmd,
            "artifact_available": artifact_path is not None,
        }
        if artifact_path is not None:
            event_payload["artifact_path"] = artifact_dir
        with state.lock:
            state.last_job = {
                "job_id": client_job_id,
                "worker_job_id": worker_job_id,
                "command": cmd,
                "status": "succeeded",
                "artifact_available": artifact_path is not None,
                "artifact_path": artifact_dir,
            }
        emit_event(config, "job_finished", event_payload)
    else:
        event_payload = {
            "job_id": client_job_id,
            "worker_job_id": worker_job_id,
            "command": cmd,
            "error": error_payload,
            "artifact_available": artifact_path is not None and artifact_error is None,
        }
        if artifact_error is not None:
            event_payload["artifact_error"] = artifact_error
        elif artifact_path is not None:
            event_payload["artifact_path"] = artifact_dir
        with state.lock:
            state.last_job = {
                "job_id": client_job_id,
                "worker_job_id": worker_job_id,
                "command": cmd,
                "status": final_status,
                "error": error_payload,
                "artifact_available": artifact_path is not None and artifact_error is None,
            }
            if artifact_error is not None:
                state.last_job["artifact_error"] = artifact_error
            elif artifact_path is not None:
                state.last_job["artifact_path"] = artifact_dir
        emit_event(config, "job_cancelled" if final_status == "cancelled" else "job_failed", event_payload)


def load_worker_config(args: argparse.Namespace) -> dict[str, Any]:
    """Load configuration from config path and apply CLI argument overrides."""
    config: dict[str, Any] = {
        "id": "power_1",
        "type": "power",
        "enabled": True,
        "mode": "simulate",
        "control_host": "127.0.0.1",
        "control_port": 0,
        "artifacts_dir": ".tmp_tests/power_worker/power_1",
        "events_jsonl": None,
        "settings": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "resource_alias": None,
            "backend": None,
            "timeout_ms": 5000,
            "safety_config": None,
            "allow_output_writes": False,
        }
    }

    if getattr(args, "config", None):
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            raise FileNotFoundError(f"Config file not found: {args.config}")
        with open(cfg_path, encoding="utf-8") as f:
            file_cfg = json.load(f)

        for k in ["id", "type", "enabled", "mode", "control_host", "control_port", "artifacts_dir", "events_jsonl"]:
            if k in file_cfg:
                config[k] = file_cfg[k]

        if "settings" in file_cfg:
            for k, v in file_cfg["settings"].items():
                config["settings"][k] = v

    if getattr(args, "id", None) is not None:
        config["id"] = args.id
    if getattr(args, "mode", None) is not None:
        config["mode"] = args.mode
    if getattr(args, "control_port", None) is not None:
        config["control_port"] = args.control_port
    if getattr(args, "artifacts_dir", None) is not None:
        config["artifacts_dir"] = args.artifacts_dir
    else:
        if not getattr(args, "config", None):
            config["artifacts_dir"] = f".tmp_tests/power_worker/{config['id']}"

    if getattr(args, "events_jsonl", None) is not None:
        config["events_jsonl"] = args.events_jsonl
    else:
        if not getattr(args, "config", None):
            config["events_jsonl"] = f"{config['artifacts_dir']}/events.jsonl"

    if not config.get("events_jsonl"):
        config["events_jsonl"] = f"{config['artifacts_dir']}/events.jsonl"

    if getattr(args, "resource", None) is not None:
        config["settings"]["resource"] = args.resource
    _validate_worker_config(config)
    return config


def _validate_worker_config(config: dict[str, Any]) -> None:
    if config["type"] != "power":
        raise ValueError(f"Worker type must be 'power', got {config['type']!r}")

    if not isinstance(config.get("enabled"), bool):
        raise ValueError(f"Worker enabled must be a boolean, got {config.get('enabled')!r}")
    if config["enabled"] is False:
        raise ValueError("Worker enabled=false is not runnable")

    if config.get("mode") not in {"simulate", "live"}:
        raise ValueError(f"Worker mode must be 'simulate' or 'live', got {config.get('mode')!r}")

    host = config["control_host"]
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"Control host {host!r} is not allowed. Bind host must be localhost (127.0.0.1) in v1.")

    port = config.get("control_port")
    if not isinstance(port, int) or isinstance(port, bool) or not (0 <= port <= 65535):
        raise ValueError(f"Control port must be an integer from 0 to 65535, got {port!r}")

    settings = config.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("Worker settings must be an object")
    if "default_action" in settings:
        raise ValueError("settings.default_action is not supported; use POST /command")


def _validate_event_sink(config: dict[str, Any]) -> None:
    events_file = config.get("events_jsonl")
    if not events_file:
        return
    p = Path(events_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8"):
        pass


def run_worker(args: argparse.Namespace) -> int:
    """Entry point for worker subcommand execution."""
    try:
        config = load_worker_config(args)
        _validate_event_sink(config)
    except Exception as exc:
        print(f"Configuration validation failed: {exc}", file=sys.stderr)
        return 1

    art_dir = Path(config["artifacts_dir"])
    art_dir.mkdir(parents=True, exist_ok=True)

    host = config["control_host"]
    req_port = config["control_port"]

    try:
        server = WorkerHTTPServer((host, req_port), WorkerHTTPHandler)
    except Exception as exc:
        print(f"Failed to bind HTTP server on {host}:{req_port}: {exc}", file=sys.stderr)
        return 1

    actual_port = server.server_address[1]
    state = WorkerState(config, actual_port)

    # Cross reference references
    server.state = state
    state.server = server

    runner_thread = threading.Thread(target=job_runner, args=(state,), daemon=True)
    runner_thread.start()

    emit_event(config, "ready", {
        "run_id": state.run_id,
        "service": "keysight-power",
        "host": "127.0.0.1",
        "port": actual_port,
        "command_url": f"http://127.0.0.1:{actual_port}/command",
        "stop_url": f"http://127.0.0.1:{actual_port}/stop",
        "status_url": f"http://127.0.0.1:{actual_port}/status",
        "artifacts_dir": str(art_dir.resolve()),
        "allowed_commands": sorted(list(ALLOWED_COMMANDS)),
    })

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.stop_event.set()
        with state.lock:
            state.shutdown_flag = True
            state.lock.notify_all()
        request_worker_shutdown(server, state)
        state.shutdown_event.set()
        with state.lock:
            state.lock.notify_all()
        runner_thread.join()
        ok = state.status != "error" and not state.cleanup_failed
        emit_event(
            config,
            "summary",
            {
                "run_id": state.run_id,
                "ok": ok,
                "last_job": state.last_job,
                "cleanup": state.cleanup_results,
            },
        )

    return 0 if ok else 3
