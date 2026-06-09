"""Job queue, single-hardware-lock, and SSE event buffer management."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional


class JobStatus(str, Enum):
    ACCEPTED = "accepted"
    STARTED = "started"
    PROGRESS = "progress"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Commands that simulate Live Data behavior in the WebUI
# These read-only commands can run even when hardware is locked by a write job
LIVE_DATA_SIMULATE_COMMANDS = {
    "measure",
    "measure-all",
    "read-status",
    "readback",
    "protection-status",
}


class Job:
    def __init__(
        self,
        job_id: str,
        command: str,
        runtime: Dict[str, Any],
        parameters: Dict[str, Any],
        artifacts: Optional[Dict[str, Any]] = None,
    ):
        self.job_id = job_id
        self.command = command
        self.runtime = runtime
        self.parameters = parameters
        self.artifacts = artifacts or {}
        self.status = JobStatus.ACCEPTED
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self.cancel_requested = False
        self.created_at = time.time()
        self.updated_at = time.time()
        self._event_counter = 0

    @property
    def requires_hardware_lock(self) -> bool:
        if bool(self.runtime.get("simulate", False)) or bool(self.runtime.get("dry_run", False)):
            return False
        return self.command != "live-data"

    def add_event(self, event_type: str, data: Dict[str, Any]) -> None:
        self._event_counter += 1
        event = {
            "id": self._event_counter,
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self.events.append(event)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "command": self.command,
            "runtime": self.runtime,
            "parameters": self.parameters,
            "artifacts": self.artifacts,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.active_job_id: Optional[str] = None
        self._lock = asyncio.Lock()
        self._hardware_io_lock = threading.Lock()

    @asynccontextmanager
    async def hardware_io(self) -> AsyncIterator[None]:
        if not self._hardware_io_lock.acquire(blocking=False):
            await asyncio.to_thread(self._hardware_io_lock.acquire)
        try:
            yield
        finally:
            self._hardware_io_lock.release()

    async def submit_job(
        self,
        command: str,
        runtime: Dict[str, Any],
        parameters: Dict[str, Any],
        artifacts: Optional[Dict[str, Any]] = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        job = Job(job_id, command, runtime, parameters, artifacts)
        job.add_event("accepted", {"message": f"Job {command} accepted"})
        async with self._lock:
            self.jobs[job_id] = job
        return job_id

    async def start_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job.requires_hardware_lock:
                if self.active_job_id is not None:
                    return False
                self.active_job_id = job_id
            job.status = JobStatus.STARTED
            job.add_event("started", {"message": "Job started"})
            return True

    async def update_progress(self, job_id: str, data: Dict[str, Any]) -> None:
        async with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status in (JobStatus.STARTED, JobStatus.PROGRESS):
                job.status = JobStatus.PROGRESS
                job.add_event("progress", data)

    async def finish_job(self, job_id: str, result: Dict[str, Any]) -> None:
        async with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job.status = JobStatus.FINISHED
                job.result = result
                job.add_event("finished", {"result": result})
            if self.active_job_id == job_id:
                self.active_job_id = None

    async def fail_job(self, job_id: str, error: str) -> None:
        async with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = error
                job.add_event("failed", {"error": error})
            if self.active_job_id == job_id:
                self.active_job_id = None

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status in (JobStatus.ACCEPTED, JobStatus.STARTED, JobStatus.PROGRESS):
                job.cancel_requested = True
                job.status = JobStatus.CANCELLED
                job.add_event("cancelled", {"message": "Job cancelled"})
                if self.active_job_id == job_id:
                    self.active_job_id = None
                return True
            return False

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            job = self.jobs.get(job_id)
            return job.to_dict() if job else None

    async def get_job_events(self, job_id: str, last_event_id: int = 0) -> List[Dict[str, Any]]:
        async with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return []
            return [e for e in job.events if e["id"] > last_event_id]

    def is_hardware_locked(self) -> bool:
        return self.active_job_id is not None

    def request_cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.status in (JobStatus.STARTED, JobStatus.PROGRESS):
            job.cancel_requested = True
            return True
        return False


# Global singleton instance
job_manager = JobManager()
