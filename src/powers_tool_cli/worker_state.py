"""Thread-safe state container for Powers Tool worker daemon."""

from __future__ import annotations

import threading
import datetime
from typing import Any, TYPE_CHECKING
import uuid

from powers_tool_cli.worker_protocol import RUNTIME_FEATURES, WORKER_SCHEMA_VERSION

if TYPE_CHECKING:
    from powers_tool_cli.worker_http import WorkerHTTPServer


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
        self.job_cancel_event = threading.Event()
        self.next_job: dict[str, Any] | None = None
        self.pending_terminal_event: tuple[str, dict[str, Any]] | None = None
        self.shutdown_flag = False
        self.server: WorkerHTTPServer | None = None
        self.run_id = str(uuid.uuid4())
        config["_worker_run_id"] = self.run_id
        self.cleanup_results: list[dict[str, str]] = []
        self.cleanup_failed = False

        if config["mode"] == "simulate":
            from powers_tool_core.testing.simulator import SimulatedResourceManager

            self.sim_mgr = SimulatedResourceManager()
        else:
            self.sim_mgr = None

    def status_snapshot(self) -> dict[str, Any]:
        """Read the in-memory lifecycle and job state without touching the device."""
        with self.lock:
            base = f"http://127.0.0.1:{self.port}"
            worker_state = "running"
            if self.status == "error":
                worker_state = "failed"
            elif self.status == "stopping" or self.stop_event.is_set():
                worker_state = "stopping"
            return {
                "schema_version": WORKER_SCHEMA_VERSION,
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "run_id": self.run_id,
                "worker_state": worker_state,
                "fatal_error": self.fatal_error,
                "status": self.status,
                "service": "powers-tool",
                "status_url": f"{base}/status",
                "command_url": f"{base}/command",
                "stop_url": f"{base}/stop",
                "cancel_url": f"{base}/cancel",
                "features": RUNTIME_FEATURES,
                "queue_size": 1 if self.next_job is not None else 0,
                "active_job": self.active_job,
                "last_job": self.last_job,
            }
