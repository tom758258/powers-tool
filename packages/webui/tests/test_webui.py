"""WebUI tests: smoke, guard, API, SSE, and safety rules."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


WEBUI_COMMAND_NAMES = {
    "verify", "clear", "error", "capabilities", "safety inspect",
    "measure", "measure-all", "read-status", "readback", "identify", "protection-status",
    "set", "apply", "output-on", "output-off", "safe-off", "output-state", "cycle-output",
    "ramp", "smoke-output", "protection-set", "clear-protection", "trigger-pulse",
    "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort",
    "sequence", "snapshot", "restore-from-snapshot",
}

WEBUI_HIDDEN_UNSUPPORTED_COMMANDS = {
    "doctor", "validate-readonly", "log", "snapshot-diff", "hardware-report",
}

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "keysight_power_webui" / "static"


# Guard test: Ensure webui does not import keysight_power_cli
def test_guard_no_cli_import():
    assert "keysight_power_cli" not in sys.modules
    from keysight_power_webui import app, jobs, commands, server
    assert "keysight_power_cli" not in sys.modules


def test_import_smoke():
    """Verify WebUI runtime is importable."""
    from keysight_power_webui.app import app
    from keysight_power_webui.jobs import job_manager, JobStatus
    from keysight_power_webui.commands import execute_job_command
    from keysight_power_webui.server import main
    assert app is not None
    assert job_manager is not None


def test_static_top_bar_uses_live_resource_defaults():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    for label in ("Mode", "Backend", "Timeout", "Safety"):
        assert f">{label}<" not in index_html
        assert f">{label}\n" not in index_html

    assert 'id="resource"' in index_html
    assert 'placeholder="Waiting Scan"' in index_html
    assert 'id="resource" value=' not in index_html
    assert 'id="resource" value="USB0::SIM::E36312A::INSTR"' not in index_html
    assert 'id="resource-select"' in index_html
    assert 'id="scan"' in index_html
    assert 'id="server-state">Checking server</strong>' in index_html
    assert 'id="device-state">hardware unknown</strong>' in index_html
    assert 'id="live-state">Not monitoring</strong>' in index_html
    assert 'id="health"' not in index_html
    assert '<span id="health">checking</span>' not in index_html

    assert 'resource: valueOrNull("resource")' in app_js
    assert 'resource: document.getElementById("resource").value' not in app_js
    assert "simulate: false" in app_js
    assert "dry_run: false" in app_js
    assert "timeout_ms: 5000" in app_js
    assert "backend: null" in app_js
    assert "safety_config: null" in app_js
    assert '"Server ready"' in app_js
    assert '"hardware idle"' in app_js
    assert '"hardware locked by a job"' in app_js
    assert ".resource-row label { color: var(--accent-strong); }" in styles_css
    assert ".live-state-row" in styles_css
    assert ".live-state-field" in styles_css


def test_scan_resources_handles_missing_live_only_checkbox():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'command: "list-resources"' in app_js
    assert "parameters: { live_only: true }" in app_js
    assert 'addHistory(response.job_id, "list-resources", "accepted", "Scan Device")' in app_js
    assert "startLivePreviewSnapshot(healthState)" in app_js
    assert "function startLivePreviewSnapshot(healthState, resource = null)" in app_js
    assert "renderBlankLivePanel" in app_js
    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in app_js
    assert 'console.error("Scan resources failed", error)' in app_js
    assert 'selectCommand("list-resources")' not in app_js
    assert 'const liveOnly = document.getElementById("param-live_only")' not in app_js
    assert 'document.getElementById("param-live_only").checked = true' not in app_js


def test_static_finished_real_command_refreshes_live_snapshot():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    handle_job = app_js[app_js.index("async function handleJobEvent"):app_js.index("async function renderJobDetail")]
    refresh_guard = app_js[app_js.index("function shouldRefreshLiveAfterCommand"):app_js.index("function renderResult")]
    preview = app_js[app_js.index("async function startLivePreviewSnapshot"):app_js.index("function stopLivePreviewSnapshot")]

    assert "const job = await renderJobDetail(jobId, event);" in handle_job
    assert "shouldRefreshLiveAfterCommand(event, job)" in handle_job
    assert "startLivePreviewSnapshot(healthState, job.runtime.resource)" in handle_job
    assert "job?.command !== \"list-resources\"" in refresh_guard
    assert "Boolean(runtime?.resource)" in refresh_guard
    assert "runtime.simulate === false" in refresh_guard
    assert "runtime.dry_run === false" in refresh_guard
    assert "!state.liveEvents" in refresh_guard
    assert "async function startLivePreviewSnapshot(healthState, resource = null)" in app_js
    assert "if (resource) payload.runtime.resource = resource;" in preview


def test_static_live_data_uses_three_channel_panel_contract():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'id="live-cards"' in index_html
    assert 'Live State:' in index_html
    for channel in ("1", "2", "3"):
        assert f'data-channel-card="{channel}"' in index_html
    assert 'id="live-table"' not in index_html

    start_live = app_js[app_js.index("async function startLive()"):app_js.index("async function stopLive()")]
    assert 'parameters: { interval_ms: 15000 }' in start_live
    assert 'read_command: "measure-all"' not in start_live
    assert 'channel: "all"' not in start_live
    assert 'if (!payload.runtime.resource)' in start_live
    assert 'Select or enter a hardware resource before starting Live Data.' in start_live
    assert 'simulate: true' not in start_live
    assert 'function formatNum(value)' in app_js
    assert 'typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "--"' in app_js
    assert "function blankLiveChannels()" in app_js
    assert 'mergeLiveChannels(data.channels, previous?.channels, Boolean(data.stale))' in app_js
    assert "if (incoming[key] === null || incoming[key] === undefined) next[key] = previous[key];" in app_js
    assert "function renderLivePanel(data)" in app_js
    for field in ("output_enabled", "measured_voltage", "measured_current", "set_voltage", "set_current", "stale", "error"):
        assert field in app_js
    render_channel_card = app_js[app_js.index("function renderChannelCard(channel, sample)"):app_js.index("function drawTrend()")]
    assert "live-card-foot" not in render_channel_card
    assert "sample.timestamp" not in render_channel_card
    assert "last update" in app_js

    assert ".live-cards" in styles_css
    assert ".live-card-foot" not in styles_css
    assert ".status-badge.on" in styles_css
    assert ".live-card.stale" in styles_css
    assert ".live-state-field strong" in styles_css


def test_static_live_data_note_and_header_styles_are_scoped():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'class="live-data-section"' in index_html
    assert 'class="secondary live-start-button">Start Monitor</button>' in index_html
    assert (
        "Live Data monitor updates every 15 seconds. When the monitor is stopped, "
        "successful real hardware commands refresh this panel once after completion."
    ) in index_html
    assert 'id="live-start" class="secondary" style=' not in index_html
    assert '<div style=' not in index_html
    assert ".live-data-section .section-head { border-bottom: 0; }" in styles_css
    assert "\n.section-head { border-bottom: 0;" not in styles_css
    assert ".live-data-note" in styles_css


def test_static_layout_stacks_results_in_main_column():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'class="workspace"' in index_html
    assert 'class="rail"' in index_html
    assert 'class="rightbar"' not in index_html
    assert "display: flex;" in styles_css
    assert "flex-direction: column;" in styles_css


def test_result_panel_is_light_and_collapsible():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'id="result-panel" class="result-panel"' in index_html
    assert 'id="result-toggle"' in index_html
    assert 'aria-label="Collapse result"' in index_html
    assert 'document.getElementById("result-toggle").addEventListener("click", toggleResultPanel)' in app_js
    assert "function toggleResultPanel()" in app_js
    assert 'button.textContent = state.resultCollapsed ? "+" : "-";' in app_js
    assert "background: var(--panel-soft);" in styles_css
    assert "color: var(--text);" in styles_css
    assert ".result-panel.collapsed pre { display: none; }" in styles_css


def test_static_channel_confirmation_and_job_detail_contracts():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    base_output_params = app_js[app_js.index("function baseOutputParams()"):app_js.index("function applyOutputParams()")]
    apply_output_params = app_js[app_js.index("function applyOutputParams()"):app_js.index('document.addEventListener("DOMContentLoaded"')]

    assert 'set: baseOutputParams()' in app_js
    assert 'apply: [...applyOutputParams(), { name: "no_output", type: "checkbox", label: "Do not enable output" }]' in app_js
    assert 'options: ["1", "2", "3"], value: "1"' in base_output_params
    assert 'options: ["all", "1", "2", "3"]' in apply_output_params
    assert 'value: "1"' in apply_output_params
    for command in ("output-on", "output-off", "output-state", "cycle-output"):
        assert f'"{command}": [{{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }}' in app_js
    assert '"smoke-output": [...baseOutputParams()' in app_js

    assert 'param.name === "channel" ? normalizeChannelValue(input.value) : input.value' in app_js
    assert "function normalizeChannelValue(value)" in app_js
    assert 'if (value === "all") return value;' in app_js
    assert 'return /^[1-9]\\d*$/.test(value) ? Number(value) : value;' in app_js

    assert "const meta = state.commands[state.selected] || {};" in app_js
    assert "if (meta.requires_confirm && !payload.runtime.confirm)" in app_js
    assert 'error: "Confirmation required"' in app_js
    assert "runtime: { confirm: false }" in app_js
    assert "function submitJob(payload)" in app_js
    assert "const response = await submitJob(payload);" in app_js

    assert "async function renderJobDetail(jobId, event)" in app_js
    assert "const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);" in app_js
    for key in ("job_id", "command", "status", "runtime", "parameters", "result", "error"):
        assert f"{key}: job.{key}" in app_js


def test_static_form_has_no_advanced_json_injection():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    readme = (STATIC_DIR.parents[2] / "README.md").read_text(encoding="utf-8")

    assert "Advanced JSON" not in index_html
    assert "advanced-json" not in index_html
    assert "advanced-json" not in app_js
    assert "Object.assign(payload" not in app_js
    assert ".advanced" not in styles_css
    assert "advanced JSON editor" not in readme
    assert "typed controls and sequence-document JSON input" in readme


@pytest.fixture
def client():
    from keysight_power_webui.app import app
    from keysight_power_webui.jobs import job_manager
    job_manager.jobs.clear()
    job_manager.active_job_id = None
    return TestClient(app)


def test_index_uses_cache_busted_assets_and_no_store(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert '/static/styles.css?v=' in response.text
    assert '/static/app.js?v=' in response.text


def test_static_assets_accept_query_string_and_no_store(client: TestClient):
    response = client.get("/static/app.js?v=test")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "async function scanResources()" in response.text


def test_health_check(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["package"] == "keysight-power-webui"


def test_commands_metadata(client: TestClient):
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    
    # Check a few expected commands
    cmds = data["commands"]
    assert "set" in cmds
    assert cmds["set"]["requires_confirm"] is True
    assert "read-status" in cmds
    assert cmds["read-status"]["requires_confirm"] is False
    assert "list-resources" not in cmds
    
    # Check output-affecting commands are marked correctly
    assert cmds["output-on"]["requires_confirm"] is True
    assert cmds["output-off"]["requires_confirm"] is True


def test_command_coverage(client: TestClient):
    """Verify WebUI command list hides CLI-only/debug commands."""
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    webui_commands = set(data["commands"].keys())

    assert WEBUI_COMMAND_NAMES <= webui_commands
    assert "list-resources" not in webui_commands
    assert not (WEBUI_HIDDEN_UNSUPPORTED_COMMANDS & webui_commands)


def test_hidden_list_resources_direct_submit_succeeds(client: TestClient):
    payload = {
        "command": "list-resources",
        "runtime": {"simulate": True},
        "parameters": {},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.05)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert "resources" in job_data["result"]


def test_post_job_simulate_set(client: TestClient):
    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "timeout_ms": 5000,
            "confirm": False
        },
        "parameters": {"channel": 1, "voltage": 5.0, "current": 1.0}
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "job_id" in data
    
    # Wait for job to finish (simulate is fast)
    job_id = data["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)
    
    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert "operation" in job_data["result"]


def test_post_job_simulate_set_normalizes_string_channel(client: TestClient):
    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "timeout_ms": 5000,
            "confirm": False,
        },
        "parameters": {"channel": "3", "voltage": 5.0, "current": 1.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert job_data["result"]["target"]["channel"] == 3
    assert job_data["result"]["steps"][0]["parameters"]["channel"] == 3


def test_post_job_simulate_apply_preserves_all_channel(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from keysight_power_webui import commands

    captured: list[Any] = []

    def fake_run_core_command(request, *, stop_requested=None):
        captured.append(request)
        return {"ok": True, "parameters": request.parameters}

    monkeypatch.setattr(commands, "run_core_command", fake_run_core_command)

    payload = {
        "command": "apply",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "timeout_ms": 5000,
            "confirm": False,
        },
        "parameters": {"channel": "all", "voltage": 5.0, "current": 1.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert captured[0].command == "apply"
    assert captured[0].parameters["channel"] == "all"
    assert job_data["result"]["parameters"]["channel"] == "all"


def test_adapter_normalizes_channel_for_core_requests(monkeypatch: pytest.MonkeyPatch):
    from keysight_power_core.core import RuntimeOptions
    from keysight_power_webui import commands
    from keysight_power_webui.jobs import Job

    captured: list[Any] = []

    def fake_run_core_command(request, *, stop_requested=None):
        captured.append(request)
        return {"ok": True}

    monkeypatch.setattr(commands, "run_core_command", fake_run_core_command)

    runtime = {"resource": "USB0::SIM::E36312A::INSTR", "simulate": True}
    commands.execute_job_command(Job("set-job", "set", runtime, {"channel": "3", "voltage": 1.0, "current": 0.1}))
    commands.execute_job_command(Job("on-job", "output-on", runtime, {"channel": "3"}))
    commands.execute_job_command(Job("safe-job", "safe-off", runtime, {"channel": "all"}))

    assert captured[0].parameters["channel"] == 3
    assert captured[1].parameters["channel"] == 3
    assert captured[2].parameters["channel"] == "all"

    request = commands._request_for_job("read-status", RuntimeOptions(simulate=True), {"channel": "bad"})
    assert request.parameters["channel"] == "bad"


def test_post_job_real_output_without_confirm_fails(client: TestClient):
    payload = {
        "command": "output-on",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "timeout_ms": 5000,
            "confirm": False  # Missing confirm!
        },
        "parameters": {"channel": 1}
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200  # Job is accepted
    data = response.json()
    job_id = data["job_id"]
    
    # Wait for job to fail
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)
    
    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "requires explicit confirmation" in job_data["error"]


def test_post_job_real_apply_all_without_confirm_fails(client: TestClient):
    payload = {
        "command": "apply",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "timeout_ms": 5000,
            "confirm": False,
        },
        "parameters": {"channel": "all", "voltage": 5.0, "current": 1.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "requires explicit confirmation" in job_data["error"]


def test_hidden_unsupported_command_direct_submit_fails(client: TestClient):
    payload = {
        "command": "doctor",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
        },
        "parameters": {},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.05)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "not_implemented_in_webui: doctor" in job_data["error"]


def test_hardware_lock_prevents_concurrent_jobs(client: TestClient):
    """Test that non-simulate/non-dry-run jobs are rejected when hardware is locked."""
    from keysight_power_webui.jobs import job_manager
    job_manager.active_job_id = "fake-active-job"
    
    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "confirm": True
        },
        "parameters": {"channel": 1, "voltage": 5.0, "current": 1.0}
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 409
    assert "Hardware is currently locked" in response.json()["detail"]
    
    # Cleanup
    job_manager.active_job_id = None


def test_hardware_lock_allows_simulate_jobs(client: TestClient):
    """Test that simulate jobs can still run when hardware is locked."""
    from keysight_power_webui.jobs import job_manager
    job_manager.active_job_id = "fake-active-job"
    
    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::SIM::INSTR",
            "simulate": True,  # Simulate mode should bypass lock
            "confirm": False
        },
        "parameters": {"channel": 1, "voltage": 5.0, "current": 1.0}
    }
    response = client.post("/api/jobs", json=payload)
    # Should succeed even when hardware is locked (simulate mode)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    
    # Cleanup
    job_manager.active_job_id = None


def test_sequence_lint_dry_run(client: TestClient):
    payload = {
        "command": "sequence",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True
        },
        "parameters": {
            "lint": True,
            "document": {
                "version": 1,
                "steps": [
                    {"action": "set", "channel": 1, "voltage": 5.0, "current": 1.0},
                    {"action": "output-on", "channel": 1},
                    {"action": "wait", "seconds": 0.1},
                    {"action": "safe-off", "channel": "all"}
                ]
            }
        }
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    data = response.json()
    job_id = data["job_id"]
    
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)
        
    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert job_data["result"]["status"] == "valid"


def test_sse_event_order(client: TestClient):
    payload = {
        "command": "read-status",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True
        },
        "parameters": {}
    }
    response = client.post("/api/jobs", json=payload)
    job_id = response.json()["job_id"]
    
    # Check job events array directly
    from keysight_power_webui.jobs import job_manager
    import asyncio
    
    async def check_events():
        events = await job_manager.get_job_events(job_id)
        types = [e["type"] for e in events]
        assert "accepted" in types
        assert "started" in types
        assert "finished" in types or "failed" in types

    asyncio.run(check_events())


def test_live_data_missing_resource_fails(client: TestClient):
    response = client.post(
        "/api/live",
        json={"runtime": {"simulate": False}, "parameters": {"interval_ms": 50}},
    )
    assert response.status_code == 400
    assert "requires a selected hardware resource" in response.json()["detail"]


def test_live_data_simulate_fails(client: TestClient):
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 400
    assert "simulate mode is not supported" in response.json()["detail"]


def test_live_data_start_and_stop(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _patch_live_panel(monkeypatch)
    payload = {
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False
        },
        "parameters": {
            "interval_ms": 100
        }
    }
    response = client.post("/api/live", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    job_id = data["job_id"]
    
    time.sleep(0.3) # Let it generate a few events
    
    # Stop it
    stop_response = client.post(f"/api/live/{job_id}/stop")
    assert stop_response.status_code == 200
    
    # Verify it stopped
    from keysight_power_webui.jobs import job_manager
    job = job_manager.jobs.get(job_id)
    assert job.cancel_requested is True


def test_live_data_live_panel_emits_three_channel_panel_sample(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        calls.append((runtime, parameters))
        return _fake_live_panel(runtime.resource)

    from keysight_power_webui import commands

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    payload = {
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
        },
        "parameters": {
            "interval_ms": 50,
        },
    }
    response = client.post("/api/live", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    event = _wait_for_live_progress(job_id)
    sample = event["data"]
    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["resource"] == "USB0::FAKE::E36312A::INSTR"
    assert sample["mode"] == "live"
    assert [channel["channel"] for channel in sample["channels"]] == [1, 2, 3]
    assert [channel["measured_voltage"] for channel in sample["channels"]] == [1.1, 2.2, 3.3]
    assert [channel["measured_current"] for channel in sample["channels"]] == [0.11, 0.22, 0.33]
    assert [channel["set_voltage"] for channel in sample["channels"]] == [1.0, 2.0, 3.0]
    assert [channel["set_current"] for channel in sample["channels"]] == [0.1, 0.2, 0.3]
    assert [channel["output_enabled"] for channel in sample["channels"]] == [True, False, True]
    assert calls
    assert calls[0][0].simulate is False
    assert calls[0][1] == {}

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


@pytest.mark.parametrize("envelope_key", ["result", "data"])
def test_live_data_live_panel_unwraps_envelope(client: TestClient, monkeypatch: pytest.MonkeyPatch, envelope_key: str):
    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        return {envelope_key: _fake_e36312a_live_panel(runtime.resource)}

    from keysight_power_webui import commands

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    sample = _wait_for_live_progress(job_id)["data"]
    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["mode"] == "live"
    assert sample["channels"][0]["measured_voltage"] == 1.000237
    assert sample["channels"][0]["measured_current"] == 0.000019
    assert sample["channels"][0]["set_voltage"] == 1.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert sample["channels"][1]["set_voltage"] == 0.0
    assert sample["channels"][2]["measured_current"] == 0.0

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


def test_live_data_live_panel_with_no_panel_records_is_stale_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        return {"resource": runtime.resource, "model": "E36312A"}

    from keysight_power_webui import commands

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    sample = _wait_for_live_progress(job_id)["data"]
    assert sample["status"] == "error"
    assert sample["stale"] is True
    assert "did not include output, readback, or measurement records" in sample["message"]
    assert [channel["measured_voltage"] for channel in sample["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


def test_live_data_panel_sample_normalizes_numeric_values():
    from keysight_power_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "outputs": [{"channel": 1, "enabled": True}],
            "readback": [
                {"channel": 1, "setpoints": {"voltage": "1", "current": "0.1"}},
                {"channel": 2, "setpoints": {"voltage": "", "current": None}},
            ],
            "measurements": [
                {"channel": 1, "measurements": {"voltage": "1.000237", "current": "0.000019"}},
                {"channel": 2, "measurements": {"voltage": "nan", "current": "inf"}},
            ],
        },
        {"resource": "USB0::FAKE::E36312A::INSTR"},
    )

    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["channels"][0]["measured_voltage"] == 1.000237
    assert sample["channels"][0]["measured_current"] == 0.000019
    assert sample["channels"][0]["set_voltage"] == 1.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert sample["channels"][1]["measured_voltage"] is None
    assert sample["channels"][1]["measured_current"] is None
    assert sample["channels"][1]["set_voltage"] is None
    assert sample["channels"][1]["set_current"] is None


def test_live_data_real_mode_reports_busy_without_live_panel_call(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from keysight_power_webui import commands
    from keysight_power_webui.jobs import job_manager

    def fail_live_panel(*args, **kwargs):
        raise AssertionError("live data must not read hardware while another real job owns the lock")

    monkeypatch.setattr(commands, "execute_live_panel_read", fail_live_panel)
    job_manager.active_job_id = "write-job"

    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    event = _wait_for_live_progress(job_id)
    assert event["data"]["status"] == "busy"
    assert event["data"]["stale"] is True
    assert [channel["channel"] for channel in event["data"]["channels"]] == [1, 2, 3]
    assert [channel["measured_voltage"] for channel in event["data"]["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200
    job_manager.active_job_id = None


def test_real_command_waits_for_inflight_live_panel_without_overlap(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from keysight_power_webui import app as web_app
    from keysight_power_webui import commands
    from keysight_power_webui.jobs import job_manager

    job_manager.jobs.clear()
    job_manager.active_job_id = None

    live_entered = threading.Event()
    release_live = threading.Event()
    live_active = threading.Event()
    command_entered = threading.Event()
    overlap: list[str] = []

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        live_active.set()
        live_entered.set()
        release_live.wait(timeout=2)
        live_active.clear()
        return _fake_live_panel(runtime.resource)

    def fake_execute_job(job):
        command_entered.set()
        if live_active.is_set():
            overlap.append("command overlapped live panel read")
        return {"operation": job.command}

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    monkeypatch.setattr(web_app, "execute_job_command", fake_execute_job)

    async def run_check() -> None:
        live_job_id = await job_manager.submit_job(
            command="live-data",
            runtime={
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            parameters={"interval_ms": 50},
        )
        live_task = asyncio.create_task(web_app._execute_live_data_background(live_job_id))
        assert await asyncio.to_thread(live_entered.wait, 2)

        command_job_id = await job_manager.submit_job(
            command="read-status",
            runtime={
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            parameters={"channel": 1},
        )
        command_task = asyncio.create_task(web_app._execute_job_background(command_job_id))
        await asyncio.sleep(0.15)
        assert not command_entered.is_set()

        release_live.set()
        assert await asyncio.to_thread(command_entered.wait, 2)
        await command_task
        assert job_manager.jobs[command_job_id].status.value == "finished"
        assert overlap == []

        await job_manager.cancel_job(live_job_id)
        await live_task

    asyncio.run(run_check())


def test_live_data_stop_terminates_progress_events(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _patch_live_panel(monkeypatch)
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    _wait_for_live_progress(job_id)

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200
    _wait_for_live_terminal_status(job_id)

    from keysight_power_webui.jobs import job_manager
    job = job_manager.jobs[job_id]
    progress_count = sum(1 for event in job.events if event["type"] == "progress")
    time.sleep(0.15)
    assert sum(1 for event in job.events if event["type"] == "progress") == progress_count


def _wait_for_live_progress(job_id: str) -> dict[str, Any]:
    from keysight_power_webui.jobs import job_manager

    for _ in range(30):
        job = job_manager.jobs[job_id]
        progress = [event for event in job.events if event["type"] == "progress"]
        if progress:
            return progress[-1]
        time.sleep(0.05)
    raise AssertionError("live progress event was not emitted")


def _wait_for_live_terminal_status(job_id: str) -> None:
    from keysight_power_webui.jobs import job_manager

    for _ in range(30):
        if job_manager.jobs[job_id].status.value in {"finished", "failed", "cancelled"}:
            return
        time.sleep(0.05)
    raise AssertionError("live job did not stop")


def _patch_live_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    from keysight_power_webui import commands

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        assert runtime.simulate is False
        return _fake_live_panel(runtime.resource)

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)


def _fake_live_panel(resource: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": True},
        ],
        "readback": [
            {"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.1}},
            {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.2}},
            {"channel": 3, "setpoints": {"voltage": 3.0, "current": 0.3}},
        ],
        "measurements": [
            {"channel": 1, "measurements": {"voltage": 1.1, "current": 0.11}},
            {"channel": 2, "measurements": {"voltage": 2.2, "current": 0.22}},
            {"channel": 3, "measurements": {"voltage": 3.3, "current": 0.33}},
        ],
    }


def _fake_e36312a_live_panel(resource: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
        "readback": [
            {"channel": 1, "setpoints": {"voltage": "1", "current": "0.1"}},
            {"channel": 2, "setpoints": {"voltage": "0", "current": "0.1"}},
            {"channel": 3, "setpoints": {"voltage": "0", "current": "0.1"}},
        ],
        "measurements": [
            {"channel": 1, "measurements": {"voltage": "1.000237", "current": "0.000019"}},
            {"channel": 2, "measurements": {"voltage": "0.000108", "current": "0.000000"}},
            {"channel": 3, "measurements": {"voltage": "0.0", "current": "0.0"}},
        ],
    }


def test_webui_commands_simulate_mode(client: TestClient):
    """Test WebUI-specific commands work in simulate mode."""
    commands_to_test = [
        ("capabilities", {}),
        ("safety inspect", {}),
        ("measure", {"channel": 1}),
        ("snapshot", {}),
    ]
    
    for cmd, params in commands_to_test:
        payload = {
            "command": cmd,
            "runtime": {"simulate": True},
            "parameters": params
        }
        response = client.post("/api/jobs", json=payload)
        assert response.status_code == 200, f"Command {cmd} failed to submit"
        
        job_id = response.json()["job_id"]
        for _ in range(20):
            res = client.get(f"/api/jobs/{job_id}")
            if res.json()["status"] in ("finished", "failed"):
                break
            time.sleep(0.05)
        
        job_data = client.get(f"/api/jobs/{job_id}").json()
        assert job_data["status"] == "finished", f"Command {cmd} failed: {job_data.get('error')}"


def test_readonly_commands_simulate_with_resource(client: TestClient):
    """Test read-only commands work in simulate mode with resource."""
    for cmd in ["read-status", "readback"]:
        payload = {
            "command": cmd,
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True
            },
            "parameters": {}
        }
        response = client.post("/api/jobs", json=payload)
        assert response.status_code == 200, f"Command {cmd} failed to submit"
        
        job_id = response.json()["job_id"]
        for _ in range(20):
            res = client.get(f"/api/jobs/{job_id}")
            if res.json()["status"] in ("finished", "failed"):
                break
            time.sleep(0.05)
        
        job_data = client.get(f"/api/jobs/{job_id}").json()
        assert job_data["status"] == "finished", f"Command {cmd} failed: {job_data.get('error')}"


def test_output_commands_simulate(client: TestClient):
    """Test output commands work in simulate mode."""
    commands_to_test = [
        ("set", {"channel": 1, "voltage": 5.0, "current": 1.0}),
        ("output-on", {"channel": 1}),
        ("output-off", {"channel": 1}),
        ("safe-off", {"channel": "all"}),
    ]
    
    for cmd, params in commands_to_test:
        payload = {
            "command": cmd,
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True
            },
            "parameters": params
        }
        response = client.post("/api/jobs", json=payload)
        assert response.status_code == 200, f"Command {cmd} failed to submit"
        
        job_id = response.json()["job_id"]
        for _ in range(20):
            res = client.get(f"/api/jobs/{job_id}")
            if res.json()["status"] in ("finished", "failed"):
                break
            time.sleep(0.05)
        
        job_data = client.get(f"/api/jobs/{job_id}").json()
        assert job_data["status"] == "finished", f"Command {cmd} failed: {job_data.get('error')}"


def test_confirm_policy_enforced(client: TestClient):
    """Test that output-affecting commands without confirm fail for non-simulate."""
    payload = {
        "command": "output-on",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "confirm": False  # Missing!
        },
        "parameters": {"channel": 1}
    }
    response = client.post("/api/jobs", json=payload)
    job_id = response.json()["job_id"]
    
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.05)
    
    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "confirmation" in job_data["error"].lower()


def test_job_get_not_found(client: TestClient):
    """Test GET /api/jobs/{job_id} returns 404 for unknown job."""
    response = client.get("/api/jobs/non-existent-id")
    assert response.status_code == 404


def test_job_cancel_not_found(client: TestClient):
    """Test cancel returns 400 for non-existent job."""
    response = client.post("/api/jobs/non-existent-id/cancel")
    assert response.status_code == 400
