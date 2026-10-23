"""Powers Tool worker daemon entry point and composition root."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading

from powers_tool_cli.worker_config import (
    _validate_event_sink,
    load_worker_config,
)
from powers_tool_cli.worker_execution import (
    get_opener,
    job_runner,
    record_cleanup_result,
    record_no_session_stop_cleanup,
)
from powers_tool_cli.worker_http import (
    WorkerHTTPHandler,
    WorkerHTTPServer,
    request_worker_shutdown,
)
from powers_tool_cli.worker_io import emit_event
from powers_tool_cli.worker_protocol import (
    ALLOWED_COMMANDS,
    CONTEXT_KEYS,
    FORBIDDEN_CONTEXT_ARGUMENTS,
    OUTPUT_AFFECTING_COMMANDS,
    OUTPUT_COMMANDS,
    PROTECTION_COMMANDS,
    READ_ONLY_COMMANDS,
    REQUEST_KEYS,
    RUNTIME_ARGUMENT_KEYS,
    TRIGGER_COMMANDS,
    WORKER_SCHEMA_VERSION,
    RUNTIME_FEATURES,
    common_error,
    validate_worker_argument_context_fields,
    validate_worker_context,
)
from powers_tool_cli.worker_state import WorkerState

__all__ = [
    "ALLOWED_COMMANDS",
    "CONTEXT_KEYS",
    "FORBIDDEN_CONTEXT_ARGUMENTS",
    "OUTPUT_AFFECTING_COMMANDS",
    "OUTPUT_COMMANDS",
    "PROTECTION_COMMANDS",
    "READ_ONLY_COMMANDS",
    "REQUEST_KEYS",
    "RUNTIME_ARGUMENT_KEYS",
    "TRIGGER_COMMANDS",
    "WORKER_SCHEMA_VERSION",
    "WorkerHTTPHandler",
    "WorkerHTTPServer",
    "WorkerState",
    "emit_event",
    "get_opener",
    "job_runner",
    "load_worker_config",
    "record_cleanup_result",
    "record_no_session_stop_cleanup",
    "request_worker_shutdown",
    "run_worker",
    "validate_worker_argument_context_fields",
    "validate_worker_context",
]


def run_worker(args: argparse.Namespace) -> int:
    """Entry point for worker subcommand execution."""
    try:
        config = load_worker_config(args)
        art_dir = Path(config["artifacts_dir"])
        if config.get("events_jsonl") is not None:
            Path(config["events_jsonl"])
    except Exception as exc:
        print(f"Configuration validation failed: {exc}", file=sys.stderr)
        return 2

    memory_artifacts = config["artifact_mode"] == "memory"
    try:
        _validate_event_sink(config)
        if not memory_artifacts:
            art_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"Failed to initialize Worker artifacts/event sink: {exc}", file=sys.stderr)
        return 3

    host = config["control_host"]
    req_port = config["control_port"]

    try:
        server = WorkerHTTPServer((host, req_port), WorkerHTTPHandler)
    except Exception as exc:
        print(f"Failed to bind HTTP server on {host}:{req_port}: {exc}", file=sys.stderr)
        return 3

    actual_port = server.server_address[1]
    try:
        state = WorkerState(config, actual_port)
        server.state = state
        state.server = server
        runner_thread = threading.Thread(target=job_runner, args=(state,), daemon=True)
        runner_thread.start()
    except Exception as exc:
        server.server_close()
        print(f"Failed to start Worker runtime: {exc}", file=sys.stderr)
        return 3

    ready_extra: dict[str, object] = {
        "run_id": state.run_id,
        "service": "powers-tool",
        "host": "127.0.0.1",
        "port": actual_port,
        "command_url": f"http://127.0.0.1:{actual_port}/command",
        "stop_url": f"http://127.0.0.1:{actual_port}/stop",
        "status_url": f"http://127.0.0.1:{actual_port}/status",
        "cancel_url": f"http://127.0.0.1:{actual_port}/cancel",
        "features": RUNTIME_FEATURES,
        "allowed_commands": sorted(list(ALLOWED_COMMANDS)),
    }
    if memory_artifacts:
        ready_extra["artifact_mode"] = "memory"
    else:
        ready_extra["artifacts_dir"] = str(art_dir.resolve())
    emit_event(config, "ready", ready_extra)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        state.status = "error"
        state.fatal_error = common_error("worker", {
            "code": "runtime_failed", "message": f"Worker runtime failed: {exc}"})
        print(f"Worker runtime failed: {exc}", file=sys.stderr)
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
        server.server_close()
        ok = state.status != "error" and state.fatal_error is None and not state.cleanup_failed
        exit_code = 0 if ok else 3
        emit_event(
            config,
            "summary",
            {
                "run_id": state.run_id,
                "ok": ok,
                "fatal_error": state.fatal_error,
                "exit_code": exit_code,
                "last_job": state.last_job,
                "cleanup": state.cleanup_results,
            },
        )

    return exit_code
