"""FastAPI application for Keysight Power WebUI."""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .jobs import job_manager, JobStatus
from .commands import execute_job_command, MUTATING_COMMANDS, WEBUI_UNSUPPORTED_COMMANDS, webui_command_support

STATIC_DIR = Path(__file__).parent / "static"
CACHE_CONTROL_NO_STORE = "no-store"


class NoStoreStaticFiles(StaticFiles):
    """StaticFiles variant for local hardware UI assets that must not go stale."""

    async def get_response(self, path: str, scope: Dict[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = CACHE_CONTROL_NO_STORE
        return response

app = FastAPI(title="Keysight Power WebUI", version="0.1.0")

# Mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/static", NoStoreStaticFiles(directory=str(STATIC_DIR)), name="static")


COMMAND_METADATA = {
    "list-resources": {"description": "Discover available VISA resources", "requires_confirm": False, "category": "discovery"},
    "verify": {"description": "Verify connection and basic communication", "requires_confirm": False, "category": "discovery"},
    "clear": {"description": "Clear instrument error queue", "requires_confirm": False, "category": "discovery"},
    "error": {"description": "Read instrument error queue", "requires_confirm": False, "category": "discovery"},
    "doctor": {"description": "Run diagnostic checks", "requires_confirm": False, "category": "discovery"},
    "capabilities": {"description": "Get instrument capabilities", "requires_confirm": False, "category": "discovery"},
    "safety inspect": {"description": "Inspect safety configuration", "requires_confirm": False, "category": "discovery"},
    "measure": {"description": "Measure voltage/current", "requires_confirm": False, "category": "read-only"},
    "measure-all": {"description": "Measure all channels", "requires_confirm": False, "category": "read-only"},
    "read-status": {"description": "Get output status and errors", "requires_confirm": False, "category": "read-only"},
    "readback": {"description": "Read programmed setpoints", "requires_confirm": False, "category": "read-only"},
    "validate-readonly": {"description": "Validate read-only state", "requires_confirm": False, "category": "read-only"},
    "identify": {"description": "Flash instrument display", "requires_confirm": False, "category": "read-only"},
    "protection-status": {"description": "Check protection status", "requires_confirm": False, "category": "read-only"},
    "log": {"description": "Log measurement data", "requires_confirm": False, "category": "read-only"},
    "set": {"description": "Set voltage and current limits", "requires_confirm": True, "category": "output"},
    "apply": {"description": "Apply voltage, current, and enable output", "requires_confirm": True, "category": "output"},
    "output-on": {"description": "Enable output", "requires_confirm": True, "category": "output"},
    "output-off": {"description": "Disable output", "requires_confirm": True, "category": "output"},
    "safe-off": {"description": "Safely disable output", "requires_confirm": True, "category": "output"},
    "output-state": {"description": "Check output state", "requires_confirm": False, "category": "output"},
    "cycle-output": {"description": "Cycle output on then off", "requires_confirm": True, "category": "output"},
    "ramp": {"description": "Ramp voltage", "requires_confirm": True, "category": "output"},
    "smoke-output": {"description": "Run guarded output diagnostic", "requires_confirm": True, "category": "discovery"},
    "protection-set": {"description": "Set protection limits", "requires_confirm": True, "category": "output"},
    "clear-protection": {"description": "Clear protection latches", "requires_confirm": True, "category": "output"},
    "trigger-pulse": {"description": "Configure and fire trigger pulse", "requires_confirm": False, "category": "trigger"},
    "trigger-status": {"description": "Read trigger status", "requires_confirm": False, "category": "trigger"},
    "trigger-step": {"description": "Configure native STEP trigger", "requires_confirm": False, "category": "trigger"},
    "trigger-list": {"description": "Configure native LIST trigger", "requires_confirm": False, "category": "trigger"},
    "trigger-fire": {"description": "Fire armed BUS trigger", "requires_confirm": False, "category": "trigger"},
    "trigger-abort": {"description": "Abort active trigger", "requires_confirm": False, "category": "trigger"},
    "sequence": {"description": "Execute sequence document", "requires_confirm": True, "category": "artifact"},
    "snapshot": {"description": "Create hardware snapshot", "requires_confirm": False, "category": "artifact"},
    "snapshot-diff": {"description": "Compare snapshots", "requires_confirm": False, "category": "artifact"},
    "restore-from-snapshot": {"description": "Restore from snapshot", "requires_confirm": True, "category": "artifact"},
    "hardware-report": {"description": "Generate hardware report", "requires_confirm": False, "category": "artifact"},
}

WEBUI_HIDDEN_COMMANDS = {
    "list-resources",
}


@app.get("/")
async def index():
    """Serve the main WebUI page."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        html = html.replace("/static/styles.css", f"/static/styles.css?v={_asset_version('styles.css')}")
        html = html.replace("/static/app.js", f"/static/app.js?v={_asset_version('app.js')}")
        return HTMLResponse(html, headers={"Cache-Control": CACHE_CONTROL_NO_STORE})
    return {"message": "Keysight Power WebUI - Static UI not found"}


def _asset_version(filename: str) -> str:
    path = STATIC_DIR / filename
    if not path.exists():
        return "0"
    return str(path.stat().st_mtime_ns)


@app.get("/api/health")
async def health_check():
    """Server health and status check."""
    return {
        "status": "ok",
        "package": "keysight-power-webui",
        "version": "0.1.0",
        "hardware_locked": job_manager.is_hardware_locked(),
        "active_job": job_manager.active_job_id,
    }


@app.get("/api/commands")
async def get_commands():
    """Return command metadata, parameters, and capability information."""
    commands = {
        name: {
            **metadata,
            "disabled": False,
        }
        for name, metadata in COMMAND_METADATA.items()
        if name not in WEBUI_UNSUPPORTED_COMMANDS and name not in WEBUI_HIDDEN_COMMANDS
    }
    return {
        "commands": commands,
        "command_support_by_model": webui_command_support(set(commands)),
        "output_affecting_commands": list(MUTATING_COMMANDS),
    }


@app.post("/api/jobs")
async def create_job(request: Request):
    """Submit a new job for execution."""
    payload = await request.json()
    command = payload.get("command")
    runtime = payload.get("runtime", {})
    parameters = payload.get("parameters", {})
    artifacts = payload.get("artifacts")

    # Hardware lock check at submission time for non-simulate/dry-run jobs
    # Only lock jobs that touch real hardware
    simulate = bool(runtime.get("simulate", False))
    dry_run = bool(runtime.get("dry_run", False))
    if not simulate and not dry_run and command != "live-data":
        # Check lock before even submitting the job
        if job_manager.is_hardware_locked():
            raise HTTPException(
                status_code=409,
                detail="Hardware is currently locked by another job. Please wait for it to complete.",
            )

    job_id = await job_manager.submit_job(
        command=command,
        runtime=runtime,
        parameters=parameters,
        artifacts=artifacts,
    )

    job = job_manager.jobs.get(job_id)
    if job is not None and not job.requires_hardware_lock:
        await _execute_job_background(job_id)
    else:
        asyncio.create_task(_execute_job_background(job_id))

    return {
        "ok": True,
        "job_id": job_id,
        "status_url": f"/api/jobs/{job_id}",
        "events_url": f"/api/events?job_id={job_id}",
    }


async def _execute_job_background(job_id: str):
    started = await job_manager.start_job(job_id)
    if not started:
        await job_manager.fail_job(job_id, "Failed to acquire hardware lock or job not found")
        return

    job = job_manager.jobs.get(job_id)
    if not job:
        return

    try:
        await job_manager.update_progress(job_id, {"message": "Executing command..."})
        if job.requires_hardware_lock:
            async with job_manager.hardware_io():
                result = await asyncio.to_thread(execute_job_command, job)
        else:
            result = await asyncio.to_thread(execute_job_command, job)
        await job_manager.finish_job(job_id, result)
    except Exception as e:
        error_msg = str(e)
        await job_manager.fail_job(job_id, error_msg)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job_data = await job_manager.get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_data


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    success = await job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled or not found")
    return {"ok": True, "message": "Cancellation requested"}


@app.get("/api/events")
async def stream_events(job_id: str, last_event_id: int = 0):
    async def event_generator():
        nonlocal last_event_id
        while True:
            events = await job_manager.get_job_events(job_id, last_event_id)
            for event in events:
                last_event_id = event["id"]
                yield _sse(event)
            
            job_data = await job_manager.get_job(job_id)
            if not job_data:
                yield _sse({"id": last_event_id + 1, "type": "error", "data": {"message": "Job not found"}})
                break
            
            if job_data["status"] in (JobStatus.FINISHED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value):
                break
            
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Live Data endpoints
@app.post("/api/live")
async def start_live_data(request: Request):
    """Start live data monitoring."""
    payload = await request.json()
    runtime = payload.get("runtime", {})
    if bool(runtime.get("simulate", False)):
        raise HTTPException(status_code=400, detail="Live Data requires a real hardware resource; simulate mode is not supported.")
    if not str(runtime.get("resource") or "").strip():
        raise HTTPException(status_code=400, detail="Live Data requires a selected hardware resource.")

    runtime = {**runtime, "simulate": False}
    job_id = await job_manager.submit_job(
        command="live-data",
        runtime=runtime,
        parameters=payload.get("parameters", {}),
    )
    asyncio.create_task(_execute_live_data_background(job_id))
    return {"ok": True, "job_id": job_id, "events_url": f"/api/live/{job_id}/events"}


async def _execute_live_data_background(job_id: str):
    """Execute live data monitoring in background."""
    await job_manager.start_job(job_id)
    job = job_manager.jobs.get(job_id)
    if not job:
        return
    
    try:
        interval = job.parameters.get("interval_ms", 1000) / 1000.0
        runtime_opts = {**dict(job.runtime), "simulate": False}
        last_sample: dict[str, Any] | None = None
        
        while not job.cancel_requested:
            # Live Data polling reports stale data instead of touching hardware
            # while another real job owns the hardware lock.
            if _real_command_is_active(job_id):
                busy_sample = _stale_live_panel_sample(
                    runtime_opts,
                    previous=last_sample,
                    status="busy",
                    message="Hardware busy; keeping last live values.",
                )
                await job_manager.update_progress(job_id, busy_sample)
                await asyncio.sleep(interval)
                continue
            
            try:
                from .commands import build_runtime_options, execute_live_panel_read

                runtime = build_runtime_options(runtime_opts)
                async with job_manager.hardware_io():
                    if _real_command_is_active(job_id):
                        busy_sample = _stale_live_panel_sample(
                            runtime_opts,
                            previous=last_sample,
                            status="busy",
                            message="Hardware busy; keeping last live values.",
                        )
                        await job_manager.update_progress(job_id, busy_sample)
                        await asyncio.sleep(interval)
                        continue
                    result = await asyncio.to_thread(
                        execute_live_panel_read,
                        runtime,
                        {},
                    )
                sample = _live_panel_sample_from_reading(result, runtime_opts)
                last_sample = sample
                await job_manager.update_progress(job_id, sample)
            except Exception as read_err:
                # Don't fail the whole job for a single read error
                await job_manager.update_progress(
                    job_id,
                    _stale_live_panel_sample(
                        runtime_opts,
                        previous=last_sample,
                        status="error",
                        message=str(read_err),
                    ),
                )
            
            await asyncio.sleep(interval)
        if job.status != JobStatus.CANCELLED:
            await job_manager.finish_job(job_id, {"stopped": True})
    except Exception as e:
        await job_manager.fail_job(job_id, str(e))


def _real_command_is_active(live_job_id: str) -> bool:
    return job_manager.active_job_id is not None and job_manager.active_job_id != live_job_id


def _live_panel_sample_from_reading(reading: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    reading = _unwrap_live_panel_payload(reading)
    outputs = _records_by_channel(reading.get("outputs"))
    readback = _records_by_channel(reading.get("readback"))
    measurements = _records_by_channel(reading.get("measurements"))
    live_channels = _records_by_channel(reading.get("channels"))
    has_panel_records = any((outputs, readback, measurements, live_channels))
    channels = []
    for channel in (1, 2, 3):
        live_channel = live_channels.get(channel, {})
        output = outputs.get(channel, {})
        setpoints = live_channel.get("setpoints") or readback.get(channel, {}).get("setpoints") or {}
        measured = live_channel.get("measurements") or measurements.get(channel, {}).get("measurements") or {}
        channels.append(
            {
                "channel": channel,
                "output_enabled": live_channel.get("output_enabled", output.get("enabled")),
                "measured_voltage": _number_or_none(measured.get("voltage")),
                "measured_current": _number_or_none(measured.get("current")),
                "set_voltage": _number_or_none(setpoints.get("voltage")),
                "set_current": _number_or_none(setpoints.get("current")),
            }
        )
    sample = {
        "timestamp": time.time(),
        "resource": reading.get("resource") or runtime.get("resource"),
        "stale": not has_panel_records,
        "status": "ok" if has_panel_records else "error",
        "mode": "live",
        "channels": channels,
    }
    if not has_panel_records:
        sample["message"] = "Live panel read did not include output, readback, or measurement records."
    return sample


def _live_panel_sample_from_snapshot(snapshot: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    return _live_panel_sample_from_reading(snapshot, runtime)


def _unwrap_live_panel_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("result", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    return payload


def _number_or_none(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _stale_live_panel_sample(
    runtime: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
    status: str,
    message: str,
) -> dict[str, Any]:
    channels = previous.get("channels") if previous else _blank_live_channels()
    return {
        "timestamp": previous.get("timestamp") if previous else time.time(),
        "resource": (previous or {}).get("resource") or runtime.get("resource"),
        "stale": True,
        "status": status,
        "message": message,
        "channels": channels,
    }


def _blank_live_channels() -> list[dict[str, Any]]:
    return [
        {
            "channel": channel,
            "output_enabled": None,
            "measured_voltage": None,
            "measured_current": None,
            "set_voltage": None,
            "set_current": None,
        }
        for channel in (1, 2, 3)
    ]


def _records_by_channel(records: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        return {}
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            channel = int(record.get("channel"))
        except (TypeError, ValueError):
            continue
        by_channel[channel] = record
    return by_channel


@app.post("/api/live/{job_id}/stop")
async def stop_live_data(job_id: str):
    """Stop live data monitoring."""
    success = await job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Live data job not found or already stopped")
    return {"ok": True, "message": "Live data stopped"}


@app.get("/api/live/{job_id}/events")
async def stream_live_events(job_id: str, last_event_id: int = 0):
    """Stream live data events via SSE."""
    async def event_generator():
        nonlocal last_event_id
        while True:
            events = await job_manager.get_job_events(job_id, last_event_id)
            for event in events:
                last_event_id = event["id"]
                yield _sse(event)
            
            job_data = await job_manager.get_job(job_id)
            if not job_data or job_data["status"] in (JobStatus.FINISHED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value):
                break
            
            await asyncio.sleep(0.2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(event: Dict[str, Any]) -> str:
    return (
        f"id: {event.get('id', 0)}\n"
        f"event: {event.get('type', 'message')}\n"
        f"data: {json.dumps(event)}\n\n"
    )
