"""WebUI tests: smoke, guard, API, SSE, and safety rules."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


WEBUI_COMMAND_NAMES = {
    "clear", "error", "capabilities", "identify",
    "set", "apply", "output-on", "output-off", "safe-off", "cycle-output",
    "ramp", "ramp-list", "smoke-output", "protection-set", "clear-protection", "trigger-pulse",
    "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort",
    "sequence", "snapshot", "restore-from-snapshot",
}

WEBUI_HIDDEN_UNSUPPORTED_COMMANDS = {
    "doctor", "validate-readonly", "log", "snapshot-diff", "hardware-report",
}

WEBUI_HIDDEN_LIVE_DATA_COMMANDS = {
    "measure", "measure-all", "read-status", "protection-status", "output-state",
}

WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS = {"verify", "readback", "safety inspect"}

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"


def read_static_texts() -> tuple[str, str, str]:
    return (
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        (STATIC_DIR / "app.js").read_text(encoding="utf-8"),
        (STATIC_DIR / "styles.css").read_text(encoding="utf-8"),
    )


def static_tag_with_id(html: str, element_id: str) -> str:
    match = re.search(rf"<[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>", html)
    if not match:
        raise AssertionError(f'Missing element id="{element_id}"')
    return match.group(0)


def assert_static_id(html: str, element_id: str) -> None:
    static_tag_with_id(html, element_id)


def assert_static_attr(html: str, element_id: str, attr: str, value: str | None = None) -> None:
    tag = static_tag_with_id(html, element_id)
    if value is None:
        assert re.search(rf"\b{re.escape(attr)}(?:\s|=|>|$)", tag), tag
    else:
        assert re.search(rf"\b{re.escape(attr)}=\"{re.escape(value)}\"", tag), tag


def extract_param_block(app_js: str, command_name: str) -> str:
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function baseOutputParams()")]
    match = re.search(rf'(?m)^\s*(?:"{re.escape(command_name)}"|{re.escape(command_name)}):', params_block)
    if not match:
        raise AssertionError(f"Missing PARAMS entry for {command_name}")
    start = match.start()
    next_match = re.search(r'(?m)^\s*(?:"[^"]+"|[A-Za-z_$][\w$-]*):', params_block[match.end():])
    end = match.end() + next_match.start() if next_match else len(params_block)
    return params_block[start:end]


def assert_param_contract(
    block: str,
    name: str,
    type_: str | None = None,
    options: list[str] | None = None,
) -> None:
    assert f'name: "{name}"' in block
    if type_ is not None:
        assert f'type: "{type_}"' in block
    if options is not None:
        quoted = ", ".join(f'"{option}"' for option in options)
        assert f"options: [{quoted}]" in block


def extract_js_function(app_js: str, function_name: str) -> str:
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(function_name)}\s*\(",
        app_js,
    )
    if not match:
        raise AssertionError(f"Missing function {function_name}")
    parameter_depth = 1
    index = match.end()
    while index < len(app_js):
        if app_js[index] == "(":
            parameter_depth += 1
        elif app_js[index] == ")":
            parameter_depth -= 1
            if parameter_depth == 0:
                break
        index += 1
    if parameter_depth != 0:
        raise AssertionError(f"Could not parse signature for {function_name}")
    brace = app_js.index("{", index)
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = brace
    while index < len(app_js):
        char = app_js[index]
        next_char = app_js[index + 1] if index + 1 < len(app_js) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue

        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return app_js[match.start():index + 1]
        index += 1
    raise AssertionError(f"Could not extract function {function_name}")


# Guard test: Ensure webui does not import powers_tool_cli
def test_guard_no_cli_import():
    assert "powers_tool_cli" not in sys.modules
    from powers_tool_webui import app, jobs, commands, server
    assert "powers_tool_cli" not in sys.modules


def test_import_smoke():
    """Verify WebUI runtime is importable."""
    from powers_tool_webui.app import app
    from powers_tool_webui.jobs import job_manager, JobStatus
    from powers_tool_webui.commands import execute_job_command
    from powers_tool_webui.server import main
    assert app is not None
    assert job_manager is not None
    assert JobStatus is not None
    assert execute_job_command is not None
    assert main is not None


def test_static_ui_exposes_advanced_serial_controls():
    html, app_js, styles_css = read_static_texts()
    serial_control_ids = (
        "serial-baud-rate",
        "serial-data-bits",
        "serial-parity",
        "serial-stop-bits",
        "serial-flow-control",
        "serial-read-termination",
        "serial-write-termination",
        "serial-remote",
        "serial-local-on-close",
    )

    assert 'class="device-resource-section"' in html
    assert_static_id(html, "device-resource-body")
    assert_static_id(html, "device-options-toggle")
    assert_static_id(html, "device-options-panel")
    assert_static_id(html, "toggle-device-resource")
    assert_static_id(html, "resource")
    assert_static_id(html, "resource-select")
    assert_static_id(html, "scan")
    assert_static_attr(html, "device-options-toggle", "aria-label", "Device options")
    assert_static_attr(html, "device-options-toggle", "aria-controls", "device-options-panel")
    assert_static_attr(html, "device-options-toggle", "aria-expanded", "false")
    assert_static_attr(html, "toggle-device-resource", "aria-controls", "device-resource-body")
    assert_static_attr(html, "toggle-device-resource", "aria-expanded", "true")
    assert_static_id(html, "expected-model-id")

    panel_index = html.index('id="device-options-panel"')
    body_index = html.index('id="device-resource-body"')
    assert panel_index < html.index('id="expected-model-id"') < body_index
    for element_id in serial_control_ids:
        assert_static_id(html, element_id)
        assert panel_index < html.index(f'id="{element_id}"') < body_index

    assert "Expected model" in html
    assert "Model / expected model" not in html
    assert "Auto-detect uses the connected instrument IDN" in html
    assert "Select a model only when you want to require a specific one" in html
    assert "detected IDN model remains the runtime driver" in html
    assert 'option value="keysight-' not in html
    assert "renderExpectedModelOptions" in app_js
    assert 'model.model_id' in app_js
    for unvalidated_model in ("E36103B", "E36232A"):
        assert f'<option value="{unvalidated_model}">{unvalidated_model}</option>' not in html
    assert '<option value="GENERIC">GENERIC</option>' not in html
    assert "Optional ASRL/serial overrides" in html
    assert "serial-panel" not in html
    assert ".serial-panel" not in styles_css
    assert "No resource / not scanned / Auto-detect" in html
    assert "Expected Auto" not in html
    assert 'id="dry-run"' not in html
    assert 'id="simulate"' not in html
    assert "Dry-run" not in html
    assert "Simulate" not in html

    runtime_block = extract_js_function(app_js, "runtimePayload")
    assert 'const expectedModelId = valueOrNull("expected-model-id");' in runtime_block
    assert "if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;" in runtime_block
    assert "serialOptionsPayload()" in runtime_block
    assert "runtime.serial_options = serialOptions" in runtime_block
    assert "runtime.serial_remote = true" in runtime_block
    assert "runtime.serial_local_on_close = true" in runtime_block
    assert ".serial-grid" in styles_css


def test_static_normal_model_dropdown_policy() -> None:
    html, app_js, _styles_css = read_static_texts()
    model_select = html[html.index('id="expected-model-id"'):html.index("</select>", html.index('id="expected-model-id"'))]

    assert '<option value="">Auto-detect</option>' in model_select
    assert 'option value="keysight-' not in model_select
    renderer = extract_js_function(app_js, "renderExpectedModelOptions")
    assert "state.physicalModels.forEach" in renderer
    assert "model.model_id" in renderer
    for unvalidated_model in ("E36103B", "E36232A"):
        assert unvalidated_model not in model_select
    assert "Auto-detect uses the connected instrument IDN" in html


def test_static_device_resource_summary_uses_model_wording():
    _html, app_js, _styles_css = read_static_texts()
    summary = extract_js_function(app_js, "updateDeviceResourceSummary")
    live_summary = extract_js_function(app_js, "liveResourceSummary")
    expected_summary = extract_js_function(app_js, "expectedModelSummary")

    assert "Auto-detect" in expected_summary
    assert "Manual" not in summary
    assert "const liveText = liveResourceSummary(resource, select);" in summary
    assert "const expectedText = expectedModelSummary();" in summary
    assert '[resourceText, liveText, expectedText, supportText].filter(Boolean).join(" / ")' in summary
    assert "exactSupportContextSummary(resource)" in summary
    assert "detectedResourceModel(resource)" in live_summary
    assert "return `live ${detected}`;" in live_summary
    assert 'return expected ? `Require ${expected}` : "Auto-detect";' in expected_summary
    assert "resourceDisplayModels: {}" in app_js
    assert "state.resourceDisplayModels[resource] = detectedModel;" in app_js


def test_static_model_profile_change_refreshes_effective_ui_model():
    _html, app_js, _styles_css = read_static_texts()
    bind = extract_js_function(app_js, "bind")
    handler = extract_js_function(app_js, "handleExpectedModelChanged")
    selected_expected = extract_js_function(app_js, "selectedExpectedModel")
    selected_expected_label = extract_js_function(app_js, "selectedExpectedModelLabel")
    selected_command = extract_js_function(app_js, "selectedCommandModel")
    selected_channel = extract_js_function(app_js, "selectedChannelModel")
    runtime_block = extract_js_function(app_js, "runtimePayload")

    assert 'document.getElementById("expected-model-id")?.addEventListener("change", handleExpectedModelChanged);' in bind
    assert 'return valueOrNull("expected-model-id");' in selected_expected
    assert 'return expected ? `Require ${expected}` : "Auto-detect";' in selected_expected_label
    assert "state.commandSupportByModel?.[expected]" in selected_command
    assert "return detectedCommandModelForResource(valueOrNull(\"resource\"));" in selected_command
    assert "state.channelCapabilitiesByModel?.[expected]" in selected_channel
    assert "return detectedChannelModelForResource(valueOrNull(\"resource\"));" in selected_channel
    assert "updateDeviceResourceSummary();" in handler
    assert "refreshBasicInputConstraints();" in handler
    assert "syncBasicFromLivePanel(state.livePanel);" in handler
    assert "refreshElectricalRatingConstraints();" in handler
    assert "renderWorkspaceSummary();" in handler
    assert "updateSelectedCommandState();" in handler
    assert "resourceModels" not in handler
    assert "resourceChannelModels" not in handler
    assert "resourceDisplayModels" not in handler
    assert 'const expectedModelId = valueOrNull("expected-model-id");' in runtime_block
    assert "if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;" in runtime_block
    assert 'runtime.expected_model_id = ""' not in runtime_block


def test_static_commands_payload_stores_setpoint_range_metadata():
    _html, app_js, _styles_css = read_static_texts()
    load_commands = extract_js_function(app_js, "loadCommands")

    assert "setpointRangesByModel: {}" in app_js
    assert "state.setpointRangesByModel = payload.setpoint_ranges_by_model_id || {};" in load_commands


def test_static_device_options_popover_behavior():
    _html, app_js, _styles_css = read_static_texts()
    bind = extract_js_function(app_js, "bind")
    options = extract_js_function(app_js, "setDeviceOptionsExpanded")

    assert "panel.hidden = !expanded;" in options
    assert 'button.setAttribute("aria-expanded", String(expanded));' in options
    assert 'document.getElementById("device-options-toggle").addEventListener("click", (event) => {' in bind
    assert 'setDeviceOptionsExpanded(document.getElementById("device-options-toggle").getAttribute("aria-expanded") !== "true");' in bind
    assert 'document.addEventListener("click", () => setDeviceOptionsExpanded(false));' in bind
    assert 'document.addEventListener("keydown", (event) => {' in bind

    keydown_block = bind[bind.index('document.addEventListener("keydown", (event) => {'):]
    assert 'event.key === "Escape"' in keydown_block
    assert "setDeviceOptionsExpanded(false);" in keydown_block
    assert "button.focus();" in keydown_block

    panel_click = bind[
        bind.index('document.getElementById("device-options-panel")'):
        bind.index('document.getElementById("toggle-device-resource")')
    ]
    assert "event.stopPropagation();" in panel_click


def test_static_device_resource_collapse_behavior():
    _html, app_js, _styles_css = read_static_texts()
    bind = extract_js_function(app_js, "bind")
    collapse = extract_js_function(app_js, "setDeviceResourceExpanded")

    assert "body.hidden = !expanded;" in collapse
    assert 'button.textContent = expanded ? "-" : "+";' in collapse
    assert 'button.setAttribute("aria-expanded", String(expanded));' in collapse
    assert 'document.getElementById("toggle-device-resource").addEventListener("click", () => {' in bind
    assert 'setDeviceResourceExpanded(document.getElementById("toggle-device-resource").getAttribute("aria-expanded") !== "true");' in bind


def test_static_top_bar_uses_live_resource_defaults():
    index_html, app_js, _styles_css = read_static_texts()

    for label in ("Mode", "Backend", "Timeout", "Safety"):
        assert f">{label}<" not in index_html
        assert f">{label}\n" not in index_html

    assert_static_id(index_html, "resource")
    assert 'id="resource" value=' not in index_html
    assert 'id="resource" value="USB0::SIM::E36312A::INSTR"' not in index_html
    assert_static_id(index_html, "resource-select")
    assert_static_id(index_html, "scan")
    assert "Unofficial Tool v__WEBUI_VERSION__" in index_html
    assert_static_id(index_html, "server-state")
    assert_static_id(index_html, "device-state")
    assert_static_id(index_html, "live-state")
    assert "WebUI State:" in index_html
    assert "Command State:" in index_html
    assert "Live State:" in index_html
    assert "Server State:" not in index_html
    assert "Device State:" not in index_html
    assert 'id="health"' not in index_html
    assert '<span id="health">checking</span>' not in index_html

    assert 'resource: valueOrNull("resource")' in app_js
    assert 'resource: document.getElementById("resource").value' not in app_js
    assert "simulate: false" in app_js
    assert "dry_run: false" in app_js
    assert "timeout_ms: 5000" in app_js
    assert "backend: null" in app_js
    assert "safety_config: null" in app_js


def test_static_resource_selection_refreshes_live_preview():
    index_html, app_js, _styles_css = read_static_texts()
    sync_selected = extract_js_function(app_js, "syncSelectedResource")
    refresh_preview = extract_js_function(app_js, "refreshSelectedResourcePreview")

    assert_static_id(index_html, "resource")
    assert_static_id(index_html, "resource-select")
    assert 'document.getElementById("resource-select").addEventListener("change", syncSelectedResource);' in app_js

    assert "const input = document.getElementById(\"resource\");" in sync_selected
    assert "const previous = input.value;" in sync_selected
    assert "const value = document.getElementById(\"resource-select\").value;" in sync_selected
    assert "input.value = value;" in sync_selected
    assert "if (value !== previous) await refreshSelectedResourcePreview(value);" in sync_selected

    assert "fetchJson(\"/api/live\"" not in refresh_preview
    assert "stopLivePreviewSnapshot();" in refresh_preview
    assert "renderBlankLivePanel();" in refresh_preview
    assert "if (!resource)" in refresh_preview
    assert 'setLiveState("Not monitoring", "state-idle", "No hardware resource is selected.");' in refresh_preview
    assert "const healthState = await refreshHealth();" in refresh_preview
    assert "await startLivePreviewSnapshot(healthState, resource);" in refresh_preview
    assert refresh_preview.index("stopLivePreviewSnapshot();") < refresh_preview.index("renderBlankLivePanel();")
    assert refresh_preview.index("renderBlankLivePanel();") < refresh_preview.index("const healthState = await refreshHealth();")
    assert refresh_preview.index("const healthState = await refreshHealth();") < refresh_preview.index(
        "await startLivePreviewSnapshot(healthState, resource);"
    )


def test_static_state_indicators_show_webui_command_and_live_state():
    index_html, app_js, _styles_css = read_static_texts()
    refresh_health = extract_js_function(app_js, "refreshHealth")
    preview = extract_js_function(app_js, "startLivePreviewSnapshot")
    stop_live = extract_js_function(app_js, "stopLive")
    monitor_button = extract_js_function(app_js, "updateLiveMonitorButton")

    for hook in ('class="state-dot"', 'class="state-text"', 'class="state-indicator'):
        assert hook in index_html

    assert 'setStateIndicator("server-state"' in refresh_health
    assert 'serverReady ? "Ready" : "Error"' in refresh_health
    assert 'setStateIndicator("device-state"' in refresh_health
    assert 'serverReady ? (deviceIdle ? "Ready" : "Busy") : "Unknown"' in refresh_health
    assert 'serverReady ? (deviceIdle ? "state-ok" : "state-warning") : "state-idle"' in refresh_health

    assert 'setLiveState("Refreshing once...", "state-warning"' in preview
    assert 'setLiveState("Refresh blocked", "state-error"' in preview
    assert 'setLiveState("Not monitoring", "state-idle"' in stop_live
    assert "button.textContent = monitoring ?" in monitor_button
    assert 'button.setAttribute("aria-pressed", String(monitoring));' in monitor_button
    assert 'button.classList.toggle("on", monitoring);' in monitor_button


def test_scan_resources_handles_missing_live_only_checkbox():
    _index_html, app_js, _styles_css = read_static_texts()

    assert 'command: "list-resources"' in app_js
    assert "parameters: { live_only: true }" in app_js
    assert 'fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in app_js
    assert 'selectCommand("list-resources")' not in app_js
    assert 'const liveOnly = document.getElementById("param-live_only")' not in app_js
    assert 'document.getElementById("param-live_only").checked = true' not in app_js


def test_static_finished_real_command_refreshes_live_snapshot():
    _index_html, app_js, _styles_css = read_static_texts()
    refresh = extract_js_function(app_js, "shouldRefreshLiveAfterCommand")
    preview = extract_js_function(app_js, "startLivePreviewSnapshot")
    fresh_preview = extract_js_function(app_js, "isFreshLivePreviewSample")

    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson(`/api/live/${state.liveJobId}/stop`, { method: "POST" })' in app_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in app_js
    assert "job.runtime.resource" in app_js
    assert "runtime.simulate === false" in refresh
    assert "runtime.dry_run === false" in refresh
    assert "!state.liveEvents" not in refresh
    assert "state.liveEvents" not in preview
    assert 'closeEventSource("liveEvents")' not in preview
    assert 'setLiveState("Refreshing once...", "state-warning"' in preview
    assert "handledFreshSample" in preview
    assert "handledFirstSample" not in preview
    assert "renderLivePanel(sample);" in preview
    assert "if (!isFreshLivePreviewSample(sample)) return;" in preview
    assert "sample.stale === false" in fresh_preview
    assert 'sample.status !== "busy"' in fresh_preview
    assert 'sample.status !== "error"' in fresh_preview
    assert "Array.isArray(sample.channels)" in fresh_preview
    assert 'stopLivePreviewSnapshot();\n  setLiveState("Not monitoring"' not in preview


def test_static_live_data_uses_three_channel_panel_contract():
    index_html, app_js, _styles_css = read_static_texts()

    assert 'id="live-cards"' in index_html
    for channel in ("1", "2", "3"):
        assert f'data-channel-card="{channel}"' in index_html
    assert 'id="live-table"' not in index_html

    start_live = app_js[app_js.index("async function startLive()"):app_js.index("async function stopLive()")]
    assert 'parameters: { interval_ms: 5000 }' in start_live
    assert 'class="live-data-note"' in index_html
    assert "Live Data monitor" in index_html
    assert "5 seconds" in index_html
    assert "Successful real hardware commands" in index_html
    assert 'read_command: "measure-all"' not in start_live
    assert 'channel: "all"' not in start_live
    assert 'if (!payload.runtime.resource)' in start_live
    assert 'simulate: true' not in start_live
    assert "sameResource ? previous?.channels : []" in app_js
    assert "Boolean(data.stale && sameResource)" in app_js
    for field in (
        "output_enabled",
        "measured_voltage",
        "measured_current",
        "set_voltage",
        "set_current",
        "over_voltage_tripped",
        "over_current_tripped",
        "protection_tripped",
        "over_voltage_protection_level",
        "over_current_protection_enabled",
        "stale",
        "error",
    ):
        assert field in app_js


def test_static_live_data_exposes_start_control():
    index_html, app_js, _styles_css = read_static_texts()

    assert_static_attr(index_html, "live-start", "type", "button")
    assert_static_attr(index_html, "live-start", "aria-pressed", "false")
    assert 'id="live-stop"' not in index_html
    assert 'document.getElementById("live-start").addEventListener("click", toggleLiveMonitor);' in app_js
    assert 'document.getElementById("live-stop")' not in app_js


def test_static_layout_exposes_stable_structural_hooks():
    index_html, _app_js, _styles_css = read_static_texts()
    for element_id in (
        "basic-command",
        "advanced-command-toggle",
        "advanced-commands",
        "command-categories",
        "command-list",
        "job-result-panel",
        "job-history",
        "result-panel",
        "job-result-clear",
        "job-result-toggle",
        "result-toggle",
        "command-form",
        "workspace-summary-content",
    ):
        assert_static_id(index_html, element_id)
    assert_static_attr(index_html, "advanced-commands", "hidden")
    assert 'class="rightbar"' not in index_html


def test_static_basic_command_panel_contract():
    index_html, app_js, _styles_css = read_static_texts()

    assert_static_id(index_html, "basic-command")
    assert_static_id(index_html, "basic-command-status")
    assert 'data-basic-all-output' in index_html
    assert_static_attr(index_html, "advanced-command-toggle", "aria-controls", "advanced-commands")
    assert_static_attr(index_html, "advanced-command-toggle", "aria-expanded", "false")
    assert 'panel.hidden = !expanded;' in app_js

    for channel in ("1", "2", "3"):
        assert f'data-basic-channel="{channel}"' in index_html
        assert f'data-basic-voltage="{channel}"' in index_html
        assert f'data-basic-current="{channel}"' in index_html
        assert f'data-basic-set="{channel}"' in index_html
        assert f'data-basic-output="{channel}"' in index_html


def test_static_basic_output_buttons_label_on_and_use_lit_state():
    index_html, app_js, _styles_css = read_static_texts()
    output_button = extract_js_function(app_js, "renderBasicOutputButton")
    all_button = extract_js_function(app_js, "renderBasicAllOutputButton")

    assert "All OFF" not in index_html
    assert 'button.textContent = "ON";' in output_button
    assert 'button.textContent = "ALL ON";' in all_button
    assert 'button.textContent = enabled ? "ON" : "OFF";' not in output_button
    assert 'button.textContent = allOn ? "All ON" : "All OFF";' not in all_button
    assert 'button.classList.toggle("on", enabled);' in output_button
    assert 'button.classList.toggle("off", !enabled);' in output_button
    assert 'button.classList.toggle("on", allOn);' in all_button
    assert 'button.classList.toggle("off", !allOn);' in all_button


def test_static_basic_output_buttons_lock_until_matching_readback():
    _index_html, app_js, _styles_css = read_static_texts()
    set_action = extract_js_function(app_js, "setBasicActionState")
    run_output = extract_js_function(app_js, "runBasicOutput")
    run_all = extract_js_function(app_js, "runBasicOutputAll")
    update_basic = extract_js_function(app_js, "updateBasicActionFromJob")
    render_states = extract_js_function(app_js, "renderBasicOutputActionStates")
    render_control = extract_js_function(app_js, "renderBasicOutputControlState")
    lock_action = extract_js_function(app_js, "basicOutputLockAction")
    clear_resolved = extract_js_function(app_js, "clearResolvedBasicErrors")
    render_channel = extract_js_function(app_js, "renderBasicChannelActionState")

    assert 'state.basicActionStates[actionKey] = { ...context, status, message };' in set_action
    assert 'state.basicActionStates[actionKey] = { status, message, ...context };' not in set_action
    assert 'if (basicOutputLockAction(channel)) return;' in run_output
    assert 'if (basicOutputLockAction("all")) return;' in run_all
    assert 'awaitingReadback: true' in update_basic
    assert 'setBasicActionState(action.actionKey, "pending"' in update_basic
    assert 'button.disabled = Boolean(unsupported || lockAction || commandMetaForState.disabled);' in render_control
    assert 'button.classList.toggle("basic-action-pending", Boolean(lockAction));' in render_control
    assert 'DEFAULT_CHANNELS.forEach((channel) => renderBasicOutputControlState(channel));' in render_states
    assert 'renderBasicOutputControlState("all");' in render_states
    assert 'const allAction = state.basicActionStates[basicActionKey("output", "all")];' in lock_action
    assert 'if (allAction?.status === "pending") return allAction;' in lock_action
    assert 'target === "all"' in lock_action
    assert 'state.basicActionStates[basicActionKey("output", channel)]' in lock_action
    assert 'setBasicActionState(outputKey, "success"' in clear_resolved
    assert 'setBasicActionState(basicActionKey("output", "all"), "success"' in clear_resolved
    assert "outputAction" in clear_resolved
    assert "allAction" in clear_resolved
    assert 'allOutputState === "pending"' in render_channel


def test_static_live_channel_status_uses_led_indicators():
    _index_html, app_js, styles_css = read_static_texts()
    render_channel = extract_js_function(app_js, "renderChannelCard")
    normal_render_channel = render_channel[render_channel.index("const outputClass"):]
    protection_badge = extract_js_function(app_js, "protectionBadge")

    assert 'class="status-badge status-indicator output-status ${outputClass}"' in normal_render_channel
    assert 'class="indicator-dot"' in normal_render_channel
    assert "OUT ${outputText}" in normal_render_channel
    assert '<div class="live-status-badges">' not in normal_render_channel
    assert '<div class="live-control-section">' in normal_render_channel
    assert '<div class="live-protection-section">' in normal_render_channel
    assert '<div class="live-protection-badges">' in normal_render_channel
    assert '${protectionBadge("OVP", channel.over_voltage_tripped)}' in normal_render_channel
    assert '${protectionBadge("OCP", channel.over_current_tripped)}' in normal_render_channel
    assert normal_render_channel.index('class="status-badge status-indicator output-status ${outputClass}"') < normal_render_channel.index('<div class="live-control-section">')
    assert render_channel.index('<div class="live-protection-badges">') < render_channel.index('${protectionBadge("OVP", channel.over_voltage_tripped)}')
    assert 'class="protection-badge status-indicator ${stateClass}"' in protection_badge
    assert "${label} ${stateText}" in protection_badge
    assert ".output-status .indicator-dot" in styles_css
    assert ".output-status.off" in styles_css
    assert ".live-control-section" in styles_css
    assert ".live-protection-section" in styles_css


def test_static_basic_command_submission_reuses_existing_jobs():
    _index_html, app_js, _styles_css = read_static_texts()

    submit_basic = extract_js_function(app_js, "submitBasicJob")
    run_set = extract_js_function(app_js, "runBasicSet")
    run_output = extract_js_function(app_js, "runBasicOutput")
    run_all = extract_js_function(app_js, "runBasicOutputAll")
    handle_job = extract_js_function(app_js, "handleJobEvent")

    assert 'command: "set"' not in run_set
    assert 'await submitBasicJob("set"' in run_set
    assert "{ channel, ...values.parameters }" in run_set
    assert "parameters.voltage = voltage" in app_js
    assert "parameters.current = current" in app_js
    assert "requires V, A, or both" in app_js
    assert '"output-off"' in run_output
    assert '"output-on"' in run_output
    assert 'channel: "all"' in run_all
    assert '"apply"' not in run_set
    assert '"apply"' not in run_output
    assert '"apply"' not in run_all
    assert "...runtimePayload()" in submit_basic
    assert "confirm: true" in submit_basic
    assert "submitJob(payload)" in submit_basic
    assert "tripGuardReason(command, parameters)" in submit_basic
    assert "electricalRatingGuardReason(command, parameters)" in submit_basic
    assert "state.basicJobActions[response.job_id]" in submit_basic
    assert "updateBasicActionFromJob(jobId, event, job);" in handle_job


def test_static_basic_command_error_state_contract():
    _index_html, app_js, styles_css = read_static_texts()

    assert "basicActionStates: {}" in app_js
    assert "basicJobActions: {}" in app_js
    assert 'setBasicActionState(actionKey, "error"' in app_js
    assert 'button.classList.toggle("basic-action-error"' in app_js
    assert 'card.classList.toggle("basic-action-error"' in app_js
    assert "clearResolvedBasicErrors(channel, liveChannel, fresh);" in app_js
    assert "liveSetpointsMatchBasicInputs(channel, liveChannel)" in app_js
    assert ".basic-action-error" in styles_css
    assert "background: #fdecea" in styles_css


def test_static_command_panel_exposes_description():
    index_html, app_js, _styles_css = read_static_texts()
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert 'id="selected-command"' in index_html
    assert 'id="command-description"' in index_html
    assert "commandDescription.textContent = descriptionText;" in update_selected
    assert "commandDescription.title = descriptionText;" in update_selected


def test_static_commands_use_category_navigation():
    _index_html, app_js, _styles_css = read_static_texts()

    assert 'activeCategory: "output"' in app_js
    assert 'const COMMAND_CATEGORIES = ["output", "workflow", "protection", "trigger", "artifact", "discovery"];' in app_js

    render_commands = app_js[app_js.index("function renderCommands()"):app_js.index("function selectCommand")]
    assert 'const categories = document.getElementById("command-categories");' in render_commands
    assert "COMMAND_CATEGORIES.forEach((category)" in render_commands
    assert 'state.activeCategory = category;' in render_commands
    assert '(meta.category || "discovery") === state.activeCategory' in render_commands


def test_result_panel_is_collapsible():
    index_html, app_js, _styles_css = read_static_texts()

    assert 'id="result-panel" class="result-panel collapsed"' in index_html
    assert 'id="result-toggle"' in index_html
    assert 'aria-expanded="false"' in index_html
    assert 'resultCollapsed: true' in app_js
    assert 'document.getElementById("result-toggle").addEventListener("click"' in app_js
    assert 'classList.toggle("collapsed"' in app_js
    assert 'setAttribute("aria-expanded"' in app_js


def test_job_result_is_expanded_collapsible_and_clearable():
    index_html, app_js, _styles_css = read_static_texts()

    assert 'id="job-result-panel" class="job-result-panel"' in index_html
    assert 'id="job-result-clear"' in index_html
    assert 'id="job-result-toggle"' in index_html
    assert 'aria-expanded="true"' in index_html
    assert "jobResultCollapsed: false" in app_js
    assert 'document.getElementById("job-result-toggle").addEventListener("click", toggleJobResultPanel);' in app_js
    assert 'document.getElementById("job-result-clear").addEventListener("click", clearJobResults);' in app_js
    clear_block = app_js[app_js.index("function clearJobResults()"):app_js.index("async function startLive")]
    assert "state.jobs = [];" in clear_block
    assert 'document.getElementById("result").textContent' not in clear_block


def test_static_ramp_list_editor_contract():
    _index_html, app_js, styles_css = read_static_texts()

    assert '"ramp-list": []' in app_js
    for field in ("channel", "current", "start_voltage", "stop_voltage", "step_voltage", "delay_ms", "hold_ms"):
        assert f'name: "{field}"' in app_js
    assert "state.rampListSegments.length >= 10" in app_js
    assert "if (state.rampListSegments.length <= 1) return;" in app_js
    assert "start_voltage: previous.stop_voltage" in app_js
    assert "stop_voltage: previous.stop_voltage" in app_js
    assert 'kind: "keysight-power-ramp-list"' in app_js
    assert "window.showOpenFilePicker" in app_js
    assert "window.showSaveFilePicker" in app_js
    assert "const normalized = validateRampListDocument(JSON.parse(text));" in app_js
    assert "state.rampListSegments = normalized.segments;" in app_js
    assert "state.rampListCompletionPulse = normalized.completionPulse;" in app_js
    assert 'name: "completion_pulse_segment"' in app_js
    assert 'name: "completion_pulse_step"' in app_js
    assert "state.rampListCompletionPulse = normalized.completionPulse;" in app_js
    assert "document.completion_pulse" in app_js
    assert '"trigger-pulse": [channel()' in app_js
    assert 'const REAR_PIN_OPTIONS = ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"];' in app_js
    assert 'option.textContent = definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value);' in app_js
    assert 'definition.name === "timing" && value === "step" && stepPulseBlocked' not in app_js
    assert "rampListStepPulseBlocked()" not in app_js
    assert ".ramp-list-pulse-hint { grid-column: 1 / -1; }" in styles_css
    assert 'if (state.selected === "ramp-list") return { document: rampListDocument() };' in app_js
    assert 'command === "ramp-list"' in app_js


def test_static_pulse_child_fields_and_rear_pin_select_contracts():
    _index_html, app_js, styles_css = read_static_texts()

    cycle = extract_param_block(app_js, "cycle-output")
    ramp = extract_param_block(app_js, "ramp")
    trigger_pulse = extract_param_block(app_js, "trigger-pulse")
    trigger_list = extract_js_function(app_js, "triggerListParams")
    sequence_definitions = extract_js_function(app_js, "sequenceActionDefinitions")
    normalize_sequence = extract_js_function(app_js, "normalizeSequenceStep")

    assert 'name: "completion_pulse_enabled", type: "checkbox"' in cycle
    assert 'name: "completion_pulse_pins", type: "select"' in cycle
    assert cycle.count("pulseChild: true") == 2
    assert 'name: "completion_pulse_pins", type: "select"' in ramp
    assert ramp.count("pulseChild: true") == 2
    assert 'payload.completion_pulse_mode = "post-action";' not in app_js
    assert 'name: "pins", type: "select", label: "Rear pins"' in trigger_pulse
    assert 'name: "completion_pulse_pins", type: "select"' in trigger_list
    assert 'name: "pins", label: "Rear pins", type: "select"' in sequence_definitions
    assert "if (action === \"trigger-pulse\") normalized.pins = parseRearPins(normalized.pins);" in normalize_sequence
    assert ".form-grid .pulse-child-field.visible { display: block; }" in styles_css
    assert "function updatePulseChildVisibility(command)" in app_js


def test_static_frontend_uses_command_support_to_disable_unsupported_model_commands():
    _index_html, app_js, _styles_css = read_static_texts()
    command_meta = extract_js_function(app_js, "commandMeta")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")
    selected_command = extract_js_function(app_js, "selectedCommandModel")

    assert "const support = selectedCommandSupport(name);" in command_meta
    assert "support?.real === false" in command_meta
    assert "disabled: true" in command_meta
    assert "commandDisabledReason(support, selectedCommandModel())" in command_meta
    assert "runButton.disabled = Boolean(meta.disabled" in update_selected
    assert "state.commandSupportByModel?.[expected]" in selected_command


def test_static_frontend_policy_for_edu_and_e3646a_disabled_controls():
    _index_html, app_js, _styles_css = read_static_texts()
    command_meta = extract_js_function(app_js, "commandMeta")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert '"trigger-step"' in app_js
    assert '"trigger-list"' in app_js
    assert '"snapshot"' in app_js
    assert '"restore-from-snapshot"' in app_js
    assert '"protection-set"' in app_js
    assert '"trigger-pulse"' in app_js
    assert "support?.real === false" in command_meta
    assert "disabled: true" in command_meta
    assert "runButton.disabled = Boolean(meta.disabled" in update_selected


def test_static_e3646a_ramp_list_and_sequence_wording_does_not_imply_native_list_support():
    index_html, app_js, _styles_css = read_static_texts()

    assert "native LIST" not in index_html
    assert "native LIST" not in extract_param_block(app_js, "ramp-list")
    assert "Native LIST" not in extract_param_block(app_js, "ramp-list")


def test_static_job_result_summary_contract():
    _index_html, app_js, _styles_css = read_static_texts()

    render_job_detail = app_js[app_js.index("async function renderJobDetail"):app_js.index("function shouldRefreshLiveAfterCommand")]

    assert "updateJobResult(job.job_id, job.status, jobSummary(job, event));" in render_job_detail
    assert "renderResult({" in render_job_detail
    assert 'if (command === "capabilities") return capabilitiesSummary(result);' in app_js
    assert 'if (command === "identify") return identifySummary(result);' in app_js
    assert 'if (command === "verify") return verifySummary(result);' in app_js
    assert 'if (command === "read-status") return readStatusSummary(result);' in app_js
    assert 'if (command === "readback") return readbackSummary(result);' in app_js
    assert 'if (command === "snapshot") return snapshotSummary(result);' in app_js
    assert 'if (command === "error") return errorQueueSummary(result, "instrument");' in app_js
    assert 'if (command === "safety inspect") return safetyInspectSummary(result);' in app_js
    assert "outputStatesSummary(result.outputs)" in app_js
    assert "setpointSummary(channels)" in app_js
    assert "result.resources.length" in app_js


def test_static_workspace_summary_keeps_latest_success_by_command_and_resource():
    index_html, app_js, _styles_css = read_static_texts()

    capture = extract_js_function(app_js, "captureWorkspaceResult")
    render = extract_js_function(app_js, "renderWorkspaceSummary")

    assert 'id="workspace-summary-content"' in index_html
    assert "workspaceResults: {}" in app_js
    assert 'job.status !== "finished"' in capture
    assert "workspaceResultKey(job.command, resource)" in capture
    assert "state.workspaceResults[workspaceResultKey(state.selected, resource)]" in render
    assert "renderCapabilitiesWorkspaceSummary(container, job.result);" in render
    assert "renderIdentifyWorkspaceSummary(container, job.result);" in render
    assert "captureWorkspaceResult(job);" in app_js


def test_static_workspace_capabilities_and_identify_use_result_fields():
    _index_html, app_js, _styles_css = read_static_texts()

    capabilities = extract_js_function(app_js, "renderCapabilitiesWorkspaceSummary")
    identify = extract_js_function(app_js, "renderIdentifyWorkspaceSummary")

    for field in ("model", "resource", "channels", "measure_channels", "command_support", "models"):
        assert field in capabilities
    assert "featureAvailability(" in capabilities
    assert "details.channels.length" in capabilities
    for field in ("manufacturer", "model", "serial", "firmware", "options", "scpi_version", "resource"):
        assert field in identify


def test_static_command_keys_are_used_for_selection_and_submission():
    _index_html, app_js, _styles_css = read_static_texts()

    render_commands = app_js[app_js.index("function renderCommands()"):app_js.index("function selectCommand")]

    assert "Object.entries(state.commands)" in render_commands
    assert "<span>${commandDisplayName(name)}</span>" in render_commands
    assert "button.addEventListener(\"click\", () => selectCommand(name));" in render_commands
    assert "command: state.selected" in app_js
    assert "renderForm(name);" in app_js
    assert "selectCommand(commandDisplayName(name))" not in app_js


def test_static_command_display_names_preserve_machine_command_keys():
    _index_html, app_js, _styles_css = read_static_texts()

    render_commands = app_js[app_js.index("function renderCommands()"):app_js.index("function selectCommand")]

    assert 'name.includes(filter) || commandDisplayName(name).toLowerCase().includes(filter)' in render_commands
    assert 'commandDisplayName(a[0]).localeCompare(commandDisplayName(b[0]))' in render_commands


def test_static_command_select_options_use_human_labels_and_machine_values():
    _index_html, app_js, _styles_css = read_static_texts()

    render_form = extract_js_function(app_js, "renderForm")
    render_restore = extract_js_function(app_js, "renderRestoreForm")
    display_name = extract_js_function(app_js, "optionDisplayName")

    assert "item.value = option;" in render_form
    assert 'item.textContent = param.parser === "intList" ? rearPinDisplayName(option) : optionDisplayName(option);' in render_form
    assert "opt.value = ch;" in render_restore
    assert "opt.textContent = optionDisplayName(ch);" in render_restore
    assert 'value.replace(/-/g, " ")' in display_name
    assert 'return `Pin ${value}`' not in display_name


def test_static_commands_disable_by_selected_resource_model():
    _index_html, app_js, _styles_css = read_static_texts()

    assert "commandSupportByModel: {}" in app_js
    assert "channelCapabilitiesByModel: {}" in app_js
    assert "resourceModels: {}" in app_js
    assert "resourceChannelModels: {}" in app_js
    assert "state.commandSupportByModel = payload.command_support_by_model_id || {};" in app_js
    assert "state.channelCapabilitiesByModel = payload.channel_capabilities_by_model_id || {};" in app_js
    assert "updateResourceModels(resources);" in app_js
    assert "resource.model_id" in app_js
    assert "function selectedCommandModel()" in app_js
    assert "function detectedCommandModelForResource(resource)" in app_js
    assert "state.commandSupportByModel?.[model]?.[name]" in app_js
    assert "const model = selectedCommandModel();" in extract_js_function(app_js, "selectedCommandSupport")
    assert "const next = supportedModelKey(modelId);" in app_js
    assert "!next.stale && updateResourceModel(next.resource, next.model_id, next.model)" in app_js
    assert "support?.real === false" in app_js
    assert "button.disabled = Boolean(effectiveMeta.disabled);" in app_js
    assert "runButton.disabled = Boolean(meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard);" in app_js
    assert 'error: "Command unavailable"' in app_js


def test_static_frontend_consumes_exact_live_support_without_exposing_validation_controls():
    index_html, app_js, _styles_css = read_static_texts()
    load_commands = extract_js_function(app_js, "loadCommands")
    command_meta = extract_js_function(app_js, "commandMeta")
    capture_support = extract_js_function(app_js, "captureResourceLiveSupport")
    capture_workspace = extract_js_function(app_js, "captureWorkspaceResult")
    clear_stale = extract_js_function(app_js, "clearStaleResourceLiveSupport")
    update_model = extract_js_function(app_js, "updateResourceModel")
    model_changed = extract_js_function(app_js, "handleExpectedModelChanged")
    runtime_payload = extract_js_function(app_js, "runtimePayload")
    render_basic = extract_js_function(app_js, "renderBasicChannelActionState")
    render_basic_output = extract_js_function(app_js, "renderBasicOutputControlState")

    assert "liveSupportByModel: {}" in app_js
    assert "resourceLiveSupport: null" in app_js
    assert "resourceLiveSupportContext: null" in app_js
    assert "state.liveSupportByModel = payload.live_support_by_model_id || {};" in load_commands
    assert '["capabilities", "identify", "verify"].includes(job.command)' in capture_workspace
    assert "captureResourceLiveSupport(job, resource);" in capture_workspace
    assert "liveSupport.evaluated !== true" in capture_support
    unevaluated_branch = capture_support[:capture_support.index("state.resourceLiveSupport = liveSupport;")]
    assert "state.resourceLiveSupportContext?.resource === resource" in unevaluated_branch
    assert "state.resourceLiveSupport = null;" in unevaluated_branch
    assert "state.resourceLiveSupportContext = null;" in unevaluated_branch
    assert unevaluated_branch.index("state.resourceLiveSupport = null;") < unevaluated_branch.rindex("return false;")
    assert "model_id: liveSupport.model_id || null" in capture_support
    assert "transport_scope: liveSupport.transport_scope" in capture_support
    assert "backend_scope: liveSupport.backend_scope" in capture_support
    assert "state.resourceLiveSupportContext.resource === resource" in clear_stale
    assert "state.resourceLiveSupport = null;" in clear_stale
    assert "state.resourceLiveSupportContext.model_id !== modelId" in update_model
    assert "state.resourceLiveSupport = null;" in update_model
    assert "exactCommand.product_open !== true" in command_meta
    assert "exactCommand.policy_exempt" in command_meta
    assert "commandSupport.offline_only" in app_js
    assert "Offline utility; live exact scope is not applicable." in app_js
    assert "Connection scope not evaluated" in command_meta
    assert "Pending live validation:" in app_js
    assert "No product-open live scope is registered" in app_js
    assert "Identity/status diagnostic; exact model feature scope is not required." in app_js
    assert "state.resourceLiveSupport" not in model_changed
    assert 'const setMeta = commandMeta("set");' in render_basic
    assert "setButton.disabled = Boolean(unsupported || setMeta.disabled);" in render_basic
    assert 'commandMeta(enabled ? "output-off" : "output-on")' in render_basic_output
    assert "commandMetaForState.disabled" in render_basic_output
    assert "support_policy_mode" not in runtime_payload
    assert "validation" not in runtime_payload
    assert "backend-selector" not in index_html
    assert "validation-allow-pending-live-support" not in index_html
    assert "validation-allow-pending-live-support" not in app_js


def test_static_channel_capability_guards_use_metadata():
    _index_html, app_js, styles_css = read_static_texts()

    assert "const DEFAULT_CHANNELS = [1, 2, 3];" in app_js
    assert "function supportedChannelsForCurrentModel()" in app_js
    assert "if (!capability || !capability.channels.length) return [...DEFAULT_CHANNELS];" in app_js
    assert "function channelCapabilityForCurrentModel()" in app_js
    assert "function channelCapabilityForModel(model)" in app_js
    assert "function selectedChannelModel()" in app_js
    assert "function detectedChannelModelForResource(resource)" in app_js
    assert "metadata.channels" in app_js
    assert "metadata.output_control_scope" in app_js
    assert "Array.isArray(metadata)" in app_js
    assert "? modelId : null" in extract_js_function(app_js, "supportedModelKey")
    assert "function currentChannelCapabilityModel()" in app_js
    assert "return selectedChannelModel();" in extract_js_function(app_js, "currentChannelCapabilityModel")
    assert "function channelModelKey(model)" in app_js
    assert "state.resourceChannelModels[resource] = nextChannelModel;" in app_js
    assert "channelAvailabilityGuardReason(state.selected, parameters)" in app_js
    assert "channelAvailabilityGuardReason(state.selected, payload.parameters)" in app_js
    assert "item.disabled = true;" in app_js
    assert "channelUnsupportedReason(option)" in app_js
    assert 'error: "Unsupported channel"' in app_js
    assert ".basic-channel-card.unsupported" in styles_css
    assert ".live-card.unsupported" in styles_css


def test_static_basic_and_live_disable_unsupported_channels():
    _index_html, app_js, _styles_css = read_static_texts()

    run_set = extract_js_function(app_js, "runBasicSet")
    run_output = extract_js_function(app_js, "runBasicOutput")
    render_live = extract_js_function(app_js, "renderChannelCard")
    render_basic = extract_js_function(app_js, "renderBasicChannelActionState")
    all_on = extract_js_function(app_js, "basicAllOutputsOn")
    clear_errors = extract_js_function(app_js, "clearResolvedBasicErrors")

    assert "const unsupported = channelUnsupportedReason(channel);" in run_set
    assert 'failBasicAction(actionKey, "Unsupported channel"' in run_set
    assert "const unsupported = channelUnsupportedReason(channel);" in run_output
    assert 'failBasicAction(basicActionKey("output", channel), "Unsupported channel"' in run_output
    assert 'card.className = "live-card unsupported";' in render_live
    assert 'card.setAttribute("aria-disabled", "true");' in render_live
    assert "<span>N/A</span><small>OUT V</small>" in render_live
    assert "Unsupported" in render_live
    assert 'card.classList.toggle("unsupported", Boolean(unsupported));' in render_basic
    assert 'card.setAttribute("aria-disabled", String(Boolean(unsupported)));' in render_basic
    assert "setButton.disabled = Boolean(unsupported || setMeta.disabled);" in render_basic
    assert "supportedChannelsForCurrentModel().every" in all_on
    assert "supportedChannelsForCurrentModel().every" in clear_errors


def test_static_e3646a_output_hint_is_global_for_supported_channels():
    _index_html, app_js, _styles_css = read_static_texts()

    output_title = extract_js_function(app_js, "outputControlTitle")
    all_title = extract_js_function(app_js, "outputAllControlTitle")

    assert 'outputControlScopeForCurrentModel() === "global"' in output_title
    assert 'outputControlScopeForCurrentModel() === "global"' in all_title
    assert "globalOutputHintText()" in output_title
    assert "globalOutputHintText()" in all_title
    assert 'model === "E3646A"' not in output_title
    assert 'model === "E3646A"' not in all_title
    assert "function outputControlScopeForCurrentModel()" in app_js
    assert "output_control_scope" in extract_js_function(app_js, "outputControlScopeForCurrentModel")
    assert "output enable is global for supported channels." in extract_js_function(app_js, "globalOutputHintText")


def test_static_trip_guard_and_clear_protection_recovery_contract():
    _index_html, app_js, _styles_css = read_static_texts()

    clear_block = extract_param_block(app_js, "clear-protection")
    assert_param_contract(clear_block, "channel", "select", ["", "all", "1", "2", "3"])
    assert 'value: ""' in clear_block
    assert 'const TRIP_GUARDED_COMMANDS = new Set(["output-on", "cycle-output", "ramp", "ramp-list", "smoke-output", "apply"]);' in app_js
    assert 'if (command === "apply" && parameters.no_output === true) return "";' in app_js
    assert "if (!panel || panel.stale || !resource || panel.resource !== resource) return [];" in app_js
    assert "function setAdvancedCommandsExpanded(expanded)" in app_js
    assert "setAdvancedCommandsExpanded(panel.hidden);" in app_js
    assert "setAdvancedCommandsExpanded(true);" in app_js
    assert 'state.activeCategory = "protection";' in app_js
    assert 'selectCommand("clear-protection");' in app_js
    assert 'data-clear-protection-channel="${channel.channel}"' in app_js
    assert 'workspace.scrollIntoView({ behavior: "smooth", block: "nearest" });' in app_js
    assert "focusTarget.focus({ preventScroll: true });" in app_js
    assert 'input.value = channels.length === 1 ? String(channels[0]) : "";' in app_js
    assert 'const stateText = tripped === true ? "TRIP" : tripped === false ? "CLEAR" : "--";' in app_js


def test_static_channel_confirmation_and_job_detail_contracts():
    _index_html, app_js, styles_css = read_static_texts()

    assert 'set: setOutputParams()' in app_js
    assert 'function setOutputParams()' in app_js
    assert "{ ...params[1], optional: true }" in app_js
    assert "{ ...params[2], optional: true }" in app_js
    assert "const SET_PARTIAL_GUIDANCE =" in app_js
    render_form = extract_js_function(app_js, "renderForm")
    append_set_guidance = extract_js_function(app_js, "appendSetGuidance")
    render_guidance = extract_js_function(app_js, "renderCommandGuidance")
    assert 'if (command === "set" && param.name === "current") appendSetGuidance(label);' in render_form
    assert 'guidance.className = "field-description set-field-guidance";' in append_set_guidance
    assert "guidance.textContent = SET_PARTIAL_GUIDANCE;" in append_set_guidance
    assert "SET_PARTIAL_GUIDANCE" not in render_guidance
    field_description_css = styles_css[styles_css.index(".field-description {"):styles_css.index(".command-notes {")]
    assert "text-transform: none;" in field_description_css
    assert "setRequiresSetpointGuardReason(state.selected, parameters)" in app_js
    assert '"smoke-output": smokeOutputParams()' in app_js
    assert_param_contract(app_js, "channel", "select", ["1", "2", "3"])
    assert_param_contract(app_js, "voltage", "number")
    assert_param_contract(app_js, "current", "number")
    assert_param_contract(app_js, "no_output", "checkbox")
    assert_param_contract(app_js, "duration_ms", "number")
    for command in ("output-on", "output-off", "cycle-output"):
        assert_param_contract(extract_param_block(app_js, command), "channel", "select", ["all", "1", "2", "3"])
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function baseOutputParams()")]
    assert '"protection-set"' in params_block
    protection_block = extract_param_block(app_js, "protection-set")
    assert_param_contract(protection_block, "ocp_delay", "number")
    assert_param_contract(protection_block, "ocp_delay_trigger", "select", ["", "setting-change", "cc-transition"])
    for command in WEBUI_HIDDEN_LIVE_DATA_COMMANDS:
        assert f'"{command}"' not in params_block

    assert 'if (param.name === "channel")' in app_js
    assert 'if (param.parser === "intList")' in app_js
    assert 'if (param.parser === "numberList")' in app_js
    assert 'if (value === "all") return value;' in app_js
    assert 'return /^[1-9]\\d*$/.test(value) ? Number(value) : value;' in app_js

    assert "const meta = commandMeta(state.selected);" in app_js
    assert "if (meta.requires_confirm && !payload.runtime.confirm)" in app_js
    assert 'error: "Confirmation required"' in app_js
    assert "runtime: { confirm: false }" in app_js

    assert "const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);" in app_js
    for key in ("job_id", "command", "status", "runtime", "parameters", "result", "error"):
        assert f"{key}: job.{key}" in app_js


def test_static_form_has_no_advanced_json_injection():
    index_html, app_js, _styles_css = read_static_texts()

    assert "Advanced JSON" not in index_html
    assert "advanced-json" not in index_html
    assert "advanced-json" not in app_js
    assert "Object.assign(payload" not in app_js


def test_static_trigger_forms_have_advanced_parameters():
    _index_html, app_js, _styles_css = read_static_texts()
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function baseOutputParams()")]

    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert f'"{command}"' in params_block

    assert_param_contract(extract_param_block(app_js, "trigger-pulse"), "pins", "select")
    assert 'parser: "intList"' in app_js
    assert_param_contract(app_js, "voltage_list", "text")
    assert_param_contract(app_js, "current_list", "text")
    assert_param_contract(app_js, "dwell_list", "text")
    assert 'parser: "numberList"' in app_js
    assert_param_contract(extract_js_function(app_js, "triggerListParams"), "completion_pulse_pins", "select")
    assert_param_contract(extract_js_function(app_js, "triggerStepParams"), "source", "select", ["bus", "immediate"])
    assert_param_contract(extract_js_function(app_js, "triggerListParams"), "source", "select", ["bus", "immediate"])
    assert_param_contract(app_js, "wait_timeout_ms", "number")
    assert_param_contract(app_js, "leave_trigger_configured", "checkbox")


def test_static_trigger_forms_document_behavior_and_key_fields():
    _index_html, app_js, styles_css = read_static_texts()

    summaries = {
        "trigger-pulse": "Configures the selected rear pins as trigger outputs",
        "trigger-status": "Read-only E36312A query",
        "trigger-step": "Configures and arms a STEP transient",
        "trigger-list": "Configures and arms a LIST waveform",
        "trigger-fire": "Used only to abort this output channel",
        "trigger-abort": "Aborts Trigger/LIST execution",
    }
    blocks = {
        "trigger-pulse": extract_param_block(app_js, "trigger-pulse"),
        "trigger-status": extract_param_block(app_js, "trigger-status"),
        "trigger-step": extract_js_function(app_js, "triggerStepParams"),
        "trigger-list": extract_js_function(app_js, "triggerListParams"),
        "trigger-fire": extract_param_block(app_js, "trigger-fire"),
        "trigger-abort": extract_param_block(app_js, "trigger-abort"),
    }
    for command, summary in summaries.items():
        assert summary in blocks[command]
        assert "description:" in blocks[command]

    for field in ("source", "fire", "wait_complete", "poll_ms", "wait_timeout_ms",
                  "exclusive_pins", "leave_trigger_configured"):
        field_start = app_js.index(f'name: "{field}"')
        assert "description:" in app_js[field_start:field_start + 500]
    for field in ("voltage_list", "current_list", "dwell_list", "count", "completion_pulse_pins"):
        assert f'name: "{field}"' in blocks["trigger-list"]
        field_start = blocks["trigger-list"].index(f'name: "{field}"')
        assert "description:" in blocks["trigger-list"][field_start:field_start + 450]

    assert "pin1" not in extract_js_function(app_js, "triggerStepParams")
    assert "pin1" not in extract_js_function(app_js, "triggerListParams")
    assert 'label: "Abort target channel"' in blocks["trigger-fire"]
    assert "It does not turn outputs off" in blocks["trigger-abort"]
    assert "instrument error-queue entries" in blocks["trigger-abort"]

    render_form = extract_js_function(app_js, "renderForm")
    append_notes = extract_js_function(app_js, "appendCommandNotes")
    assert "if (!TRIGGER_COMMANDS.has(command)) appendFieldDescription(label, param);" in render_form
    assert "if (TRIGGER_COMMANDS.has(command)) appendCommandNotes(form, command, PARAMS[command] || []);" in render_form
    assert 'notes.className = "command-notes";' in append_notes
    assert 'title.textContent = "Command notes";' in append_notes
    assert "summary.textContent = commandMeta(command).description || \"\";" in append_notes
    assert "const descriptions = params.filter((param) => param.description);" in append_notes
    assert "term.textContent = param.label;" in append_notes
    assert "detail.textContent = param.description;" in append_notes
    assert ".command-notes {" in styles_css
    assert "grid-column: 1 / -1;" in styles_css[styles_css.index(".command-notes {"):styles_css.index(".ramp-list-editor {")]


def test_static_sequence_trigger_pulse_leave_configured_documents_restore_semantics():
    _index_html, app_js, styles_css = read_static_texts()

    definitions = extract_js_function(app_js, "sequenceActionDefinitions")
    sequence_fields = extract_js_function(app_js, "sequenceStepFields")

    assert 'name: "leave_trigger_configured"' in definitions
    assert "It does not keep a trigger armed." in definitions
    assert "may affect later Sequence steps or other BUS triggers" in definitions
    assert "appendFieldDescription(label, definition);" in sequence_fields
    assert ".sequence-step-fields .checkbox-field .field-description { flex-basis: 100%; }" in styles_css


def test_static_trigger_controls_disable_invalid_combinations_and_immediate_fire():
    _index_html, app_js, _styles_css = read_static_texts()

    update_state = extract_js_function(app_js, "updateSelectedCommandState")
    sync = extract_js_function(app_js, "syncTriggerImmediateControls")
    guard = extract_js_function(app_js, "triggerControlGuardReason")

    assert "syncTriggerImmediateControls(state.selected)" in update_state
    assert "triggerControlGuardReason(state.selected, parameters)" in update_state
    assert "meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard" in update_state
    assert "triggerArmOnlyGuardReason" not in app_js
    assert '["trigger-step", "trigger-list"]' in guard
    assert "fire.checked = false" in sync
    assert "fire.disabled = immediate" in sync
    assert "BUS Wait complete requires Fire now in the same command." in guard
    assert "A started LIST without Wait complete requires Leave configured." in guard


def test_static_trigger_guidance_explains_global_fire_and_wait_semantics():
    index_html, app_js, styles_css = read_static_texts()

    guidance = extract_js_function(app_js, "renderCommandGuidance")
    fire_guard = extract_js_function(app_js, "triggerFireWaitGuardReason")

    assert 'id="command-guidance"' in index_html
    assert index_html.index('id="command-guidance"') < index_html.index('id="command-form"')
    assert "global *TRG" in guidance
    assert "instrument-wide operation-complete event" in guidance
    assert "Abort target channel does not limit Fire or Wait" in guidance
    assert "Wait complete requires an Abort target channel." in fire_guard
    assert ".command-guidance {" in styles_css
    command_guidance_css = styles_css[styles_css.index(".command-guidance {"):styles_css.index(".trigger-list-editor {")]
    assert "text-transform: none;" in command_guidance_css


def test_static_trigger_status_has_human_readable_workspace_summary():
    _index_html, app_js, _styles_css = read_static_texts()

    render = extract_js_function(app_js, "renderWorkspaceSummary")
    summary = extract_js_function(app_js, "renderTriggerStatusWorkspaceSummary")

    assert "renderTriggerStatusWorkspaceSummary(container, job.result);" in render
    for field in ("digital_pins", "trigger_output_bus_enabled", "triggered_voltage", "triggered_current", "step_mode", "terminate_last"):
        assert field in summary


def test_static_trigger_list_uses_three_channel_workspace_editor():
    _index_html, app_js, styles_css = read_static_texts()

    render = extract_js_function(app_js, "renderTriggerListForm")
    payload = extract_js_function(app_js, "parameterPayload")
    validator = extract_js_function(app_js, "validateTriggerListWorkspace")

    for text in ("Load Trigger List", "Save Trigger List", "Add Step", "Channel ${channel}", "BOST", "EOST"):
        assert text in render
    assert "button.dataset.triggerListChannel = String(channel);" in render
    assert "steps.push({ ...steps[steps.length - 1] })" in app_js
    assert "steps.length >= 100" in app_js
    assert "steps.length <= 1" in app_js
    assert 'if (input.type === "number") input.step = "any";' in app_js
    for field in ("bost_list", "eost_list", "trigger_output_pins", "trigger_output_polarity"):
        assert field in payload
    assert "keysight-power-trigger-list-workspace" in validator
    assert 'exact(document.channels, ["1", "2", "3"]' in validator
    assert "contains unknown or missing fields" in validator
    assert ".trigger-list-editor {" in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="1"]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="2"]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="3"]' in styles_css


def test_static_trigger_list_documents_restore_and_pulse_pin_guard():
    _index_html, app_js, _styles_css = read_static_texts()

    guidance = extract_js_function(app_js, "renderCommandGuidance")
    guard = extract_js_function(app_js, "triggerControlGuardReason")

    assert "writes back the pre-run Trigger settings and LIST table" in guidance
    assert "select Leave configured to retain the new LIST table" in guidance
    assert "BOST/EOST pulses require LIST output pins." in guard


@pytest.fixture
def client():
    from powers_tool_webui.app import app
    from powers_tool_webui.jobs import job_manager
    job_manager.jobs.clear()
    job_manager.active_job_id = None
    return TestClient(app)


class FakeCoreSession:
    def __init__(self, idn: str, *, query_responses: dict[str, str] | None = None) -> None:
        self.idn = idn
        self.query_responses = query_responses or {}
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeCoreSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        if command == "INST:NSEL?":
            return self.query_responses.get(command, "1")
        if command == "SYST:ERR?":
            return self.query_responses.get(command, '0,"No error"')
        if command in self.query_responses:
            return self.query_responses[command]
        raise AssertionError(f"unexpected query {command!r}")


def wait_for_job(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(20):
        job_data = client.get(f"/api/jobs/{job_id}").json()
        if job_data["status"] in ("finished", "failed"):
            return job_data
        time.sleep(0.05)
    return client.get(f"/api/jobs/{job_id}").json()


def patch_core_opener(monkeypatch: pytest.MonkeyPatch, session: FakeCoreSession) -> None:
    from powers_tool_core.command_runner import run_core_command as real_run_core_command
    from powers_tool_webui import commands

    def fake_opener(*args: Any, **kwargs: Any) -> FakeCoreSession:
        return session

    def fake_run_core_command(request: Any, **kwargs: Any) -> dict[str, Any]:
        return real_run_core_command(request, opener=fake_opener, **kwargs)

    monkeypatch.setattr(commands, "run_core_command", fake_run_core_command)


def assert_direct_job_rejected(client: TestClient, payload: dict[str, Any], *message_fragments: str) -> None:
    response = client.post("/api/jobs", json=payload)
    if response.status_code == 400:
        detail = response.json()["detail"]
        for fragment in message_fragments:
            assert fragment in detail
        return

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed", job_data.get("result")
    error = job_data.get("error") or ""
    for fragment in message_fragments:
        assert fragment in error


def policy_snapshot_document(model: str) -> dict[str, Any]:
    return {
        "idn": {
            "raw": f"KEYSIGHT,{model},SERIAL0000,1.0",
            "manufacturer": "KEYSIGHT",
            "model": model,
            "serial": "SERIAL0000",
            "firmware": "1.0",
            "parse_ok": True,
        },
        "outputs": [{"channel": 1, "enabled": False}],
        "readback": [{"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.05}}],
        "protection_settings": [{"channel": 1, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True}}],
    }


def test_index_uses_cache_busted_assets_and_no_store(client: TestClient):
    from powers_tool_webui import __version__

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert '/static/styles.css?v=' in response.text
    assert '/static/app.js?v=' in response.text
    assert f"Unofficial Tool v{__version__}" in response.text
    assert "__WEBUI_VERSION__" not in response.text


def test_static_assets_accept_query_string_and_no_store(client: TestClient):
    response = client.get("/static/app.js?v=test")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "async function scanResources()" in response.text


def test_health_check(client: TestClient):
    from powers_tool_webui import __version__

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["package"] == "powers-tool-webui"
    assert data["version"] == __version__


def test_commands_metadata(client: TestClient):
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert "command_support_by_model_id" in data
    assert "live_support_by_model_id" in data
    channel_capabilities = data["channel_capabilities_by_model_id"]
    assert channel_capabilities["keysight-e36312a"]["channels"] == [1, 2, 3]
    assert channel_capabilities["keysight-e36312a"]["output_control_scope"] == "per_channel"
    assert channel_capabilities["keysight-edu36311a"]["channels"] == [1, 2, 3]
    assert channel_capabilities["keysight-edu36311a"]["output_control_scope"] == "per_channel"
    assert channel_capabilities["keysight-e3646a"]["channels"] == [1, 2]
    assert channel_capabilities["keysight-e3646a"]["output_control_scope"] == "global"
    assert "generic-scpi" not in channel_capabilities
    assert data["planning_profiles"]["generic-scpi"]["channels"] == [1]
    assert data["electrical_ratings_by_model_id"]["keysight-e36312a"]["channels"][0] == {
        "channel": 1,
        "max_voltage": 6.0,
        "max_current": 5.0,
    }
    setpoint_ranges = data["setpoint_ranges_by_model_id"]
    assert set(setpoint_ranges) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    }
    e3646a_ch1_ranges = setpoint_ranges["keysight-e3646a"]["channels"][0]["ranges"]
    assert e3646a_ch1_ranges[0]["name"] == "LOW"
    assert e3646a_ch1_ranges[0]["voltage_max"] == 8.24
    assert e3646a_ch1_ranges[0]["current_max"] == 3.09
    assert e3646a_ch1_ranges[1]["name"] == "HIGH"
    assert e3646a_ch1_ranges[1]["voltage_max"] == 20.6
    assert e3646a_ch1_ranges[1]["current_max"] == 1.545
    assert data["parameter_constraints"]["delay_ms"]["min"] == 0
    assert data["parameter_constraints"]["poll_ms"]["min"] == 50

    # Check a few expected commands
    cmds = data["commands"]
    assert "set" in cmds
    assert cmds["set"]["requires_confirm"] is True
    assert not (WEBUI_HIDDEN_LIVE_DATA_COMMANDS & set(cmds))
    assert "list-resources" not in cmds
    expected_categories = {
        "output": {"set", "apply", "output-on", "output-off", "safe-off"},
        "workflow": {"cycle-output", "ramp", "ramp-list", "sequence", "smoke-output"},
        "protection": {"protection-set", "clear-protection"},
        "trigger": {"trigger-pulse", "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort"},
        "artifact": {"snapshot", "restore-from-snapshot"},
        "discovery": {"clear", "error", "capabilities", "identify"},
    }
    actual_categories = {
        category: {name for name, metadata in cmds.items() if metadata["category"] == category}
        for category in expected_categories
    }
    assert actual_categories == expected_categories
    assert set(cmds) == set().union(*expected_categories.values())
    assert cmds["smoke-output"]["category"] == "workflow"
    for command in (
        "smoke-output",
        "safe-off",
        "identify",
        "error",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert isinstance(cmds[command]["description"], str)
        assert cmds[command]["description"].strip()
    assert cmds["identify"]["category"] == "discovery"
    assert not (WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS & set(cmds))
    assert cmds["clear-protection"]["category"] == "protection"
    assert cmds["clear-protection"]["requires_confirm"] is True
    assert "does not clear OVP/OCP protection latches" in cmds["clear"]["description"]
    assert cmds["sequence"]["max_steps"] == 250

    # Check output-affecting commands are marked correctly
    assert cmds["output-on"]["requires_confirm"] is True
    assert cmds["output-off"]["requires_confirm"] is True
    assert cmds["smoke-output"]["requires_confirm"] is True
    assert "smoke-output" in data["output_affecting_commands"]
    assert "ramp-list" in data["output_affecting_commands"]


def test_api_rejects_invalid_static_parameter_before_creating_job(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {"simulate": True},
            "parameters": {"channel": 1, "voltage": -1, "current": 0.1},
        },
    )

    assert response.status_code == 400
    assert "voltage" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("field", ["model_profile", "model"])
def test_api_rejects_legacy_runtime_identity_before_creating_job(
    client: TestClient,
    field: str,
):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "measure",
            "runtime": {"simulate": True, field: "E36312A"},
            "parameters": {"channel": 1},
        },
    )

    assert response.status_code == 400
    assert "legacy runtime identity fields are not allowed" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_api_rejects_arm_only_trigger_list_before_creating_job(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "trigger-list",
            "runtime": {"simulate": True},
            "parameters": {"channel": 1, "source": "bus"},
        },
    )

    assert response.status_code == 400
    assert "leave_trigger_configured=true" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


@pytest.mark.parametrize(
    ("command", "parameters", "message"),
    [
        ("trigger-step", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-list", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-step", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "immediate"}, "started without wait_complete=true"),
        ("trigger-list", {"source": "bus", "fire": True}, "started without wait_complete=true"),
    ],
)
def test_api_rejects_invalid_trigger_control_before_creating_job(
    client: TestClient,
    command: str,
    parameters: dict[str, object],
    message: str,
):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {"simulate": True},
            "parameters": {"channel": 1, **parameters},
        },
    )

    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_api_rejects_trigger_fire_wait_without_abort_target_before_creating_job(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "trigger-fire",
            "runtime": {"simulate": True},
            "parameters": {"wait_complete": True},
        },
    )

    assert response.status_code == 400
    assert "abort target" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_commands_metadata_includes_model_aware_support(client: TestClient):
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    support = data["command_support_by_model_id"]

    assert set(support) == {"keysight-e36312a", "keysight-e3646a", "keysight-edu36311a"}
    assert support["keysight-e36312a"]["trigger-list"]["real"] is True
    assert support["keysight-edu36311a"]["trigger-list"]["real"] is False
    assert support["keysight-edu36311a"]["trigger-list"]["hardware_validation"] == "not_supported_by_model"
    assert "trigger/native LIST workflows are disabled in live, simulate, and dry-run" in support["keysight-edu36311a"]["trigger-list"]["disabled_reason"]
    assert "E36312A-only" in support["keysight-edu36311a"]["snapshot"]["disabled_reason"]
    assert support["keysight-e3646a"]["identify"]["real"] is True
    assert support["keysight-e3646a"]["set"]["real"] is True
    assert support["keysight-e3646a"]["set"]["hardware_validation"] == "validated"
    assert "protection workflows are disabled until separately validated" in support["keysight-e3646a"]["protection-set"]["disabled_reason"]
    assert "software workflows, not native LIST" in support["keysight-e3646a"]["trigger-list"]["disabled_reason"]
    assert "snapshot/restore workflows are disabled until separately validated" in support["keysight-e3646a"]["restore-from-snapshot"]["disabled_reason"]
    assert "completion-pulse workflows are disabled" in support["keysight-e3646a"]["trigger-pulse"]["disabled_reason"]
    assert "disabled_reason" not in support["keysight-e3646a"]["ramp-list"]
    assert "disabled_reason" not in support["keysight-e3646a"]["sequence"]
    generic_support = data["planning_profiles"]["generic-scpi"]["command_support"]
    assert generic_support["set"]["real"] is False
    for model in support:
        assert support[model]["clear"]["real"] is True
        assert support[model]["error"]["real"] is True
        assert "verify" not in support[model]
        assert "readback" not in support[model]
        assert "safety inspect" not in support[model]


def test_commands_metadata_includes_safe_exact_live_support_projection(
    client: TestClient,
) -> None:
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()

    assert {
        "commands",
        "command_support_by_model_id",
        "live_support_by_model_id",
        "channel_capabilities_by_model_id",
        "electrical_ratings_by_model_id",
        "setpoint_ranges_by_model_id",
        "parameter_constraints",
        "output_affecting_commands",
    } <= set(data)
    live_support = data["live_support_by_model_id"]
    assert set(live_support) == {"keysight-e36312a", "keysight-edu36311a", "keysight-e3646a"}

    e36312a_set = live_support["keysight-e36312a"]["commands"]["set"]
    assert {
        (scope["transport_scope"], scope["backend_scope"], scope["validation_status"])
        for scope in e36312a_set["scopes"]
    } == {
        ("usb", "system_visa", "live_validated_full_suite"),
        ("tcpip", "system_visa", "live_validated_full_suite"),
        ("tcpip", "pyvisa_py", "transport_pending"),
    }
    assert live_support["keysight-edu36311a"]["commands"]["trigger-list"]["profile_supported"] is False
    assert live_support["keysight-edu36311a"]["commands"]["trigger-list"]["scopes"] == []
    e3646a_set = live_support["keysight-e3646a"]["commands"]["set"]
    assert [(scope["transport_scope"], scope["backend_scope"]) for scope in e3646a_set["scopes"]] == [
        ("asrl", "system_visa")
    ]
    assert live_support["keysight-e3646a"]["commands"]["trigger-list"]["profile_supported"] is False
    generic_live = data["planning_profiles"]["generic-scpi"]["live_support"]
    assert generic_live["live_capable"] is False
    assert generic_live["schema_version"] == 2
    assert generic_live["evaluated"] is False
    assert generic_live["model_id"] is None
    assert generic_live["commands"]["set"]["scopes"] == []
    for command in {"list-resources", "verify", "identify", "error", "clear"}:
        entry = generic_live["commands"][command]
        assert entry["policy_exempt"] is True
        assert entry["offline_only"] is False
        assert entry["scopes"] == []
    assert generic_live["commands"]["identify"]["profile_supported"] is True
    assert live_support["keysight-e36312a"]["commands"]["clear"]["policy_exempt"] is True
    assert live_support["keysight-e36312a"]["commands"]["clear"]["scopes"] == []
    sequence_scope = next(
        scope
        for scope in live_support["keysight-e36312a"]["commands"]["sequence"]["scopes"]
        if scope["transport_scope"] == "usb"
    )
    assert {feature["feature_kind"] for feature in sequence_scope["features"]} == {
        "sequence_action"
    }
    assert all(feature["product_open"] for feature in sequence_scope["features"])
    pending_sequence_scope = next(
        scope
        for scope in live_support["keysight-e36312a"]["commands"]["sequence"]["scopes"]
        if scope["backend_scope"] == "pyvisa_py"
    )
    assert all(
        feature["validation_status"] == "feature_pending"
        and feature["product_open"] is False
        for feature in pending_sequence_scope["features"]
    )

    serialized = json.dumps(live_support)
    assert ".tmp_tests" not in serialized
    assert '"artifact"' not in serialized
    assert '"evidence"' not in serialized
    assert '"serial"' not in serialized


def test_product_model_selector_excludes_catalog_candidate_and_descoped_models() -> None:
    index_html, app_js, _styles_css = read_static_texts()
    assert '<option value="">Auto-detect</option>' in index_html
    assert "payload.physical_models" in app_js
    assert "model.model_id" in app_js
    for model in ("E36313A", "E36233A", "E36441A", "E36155A", "E36103B", "E36232A"):
        assert f'<option value="{model}">' not in index_html


def test_command_coverage(client: TestClient):
    """Verify WebUI command list hides CLI-only/debug commands."""
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    webui_commands = set(data["commands"].keys())

    assert WEBUI_COMMAND_NAMES <= webui_commands
    assert "list-resources" not in webui_commands
    assert not (WEBUI_HIDDEN_LIVE_DATA_COMMANDS & webui_commands)
    assert not (WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS & webui_commands)
    assert not (WEBUI_HIDDEN_UNSUPPORTED_COMMANDS & webui_commands)
    for model_support in data["command_support_by_model_id"].values():
        assert set(model_support) <= webui_commands


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("trigger-pulse", {"pins": [1], "channel": 1, "polarity": "positive", "exclusive_pins": False}),
        ("trigger-status", {"channel": "all"}),
        ("trigger-step", {"channel": 1, "source": "bus", "fire": True, "wait_complete": False, "poll_ms": 200}),
        (
            "trigger-list",
            {
                "channel": 1,
                "voltage_list": [0.0, 1.0],
                "current_list": [0.05],
                "dwell_list": [0.01],
                "count": 1,
                "source": "bus",
                "fire": True,
                "wait_complete": False,
                "completion_pulse_pins": [1],
                "completion_pulse_polarity": "positive",
                "exclusive_pins": False,
                "poll_ms": 200,
                "leave_trigger_configured": True,
            },
        ),
        ("trigger-fire", {"channel": 1, "wait_complete": False, "poll_ms": 200}),
        ("trigger-abort", {"channel": "all", "max_errors": 20}),
    ],
)
def test_trigger_commands_submit_in_dry_run(client: TestClient, command: str, parameters: dict[str, Any]):
    payload = {
        "command": command,
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "dry_run": True,
            "simulate": False,
            "planning_model_id": "keysight-e36312a",
        },
        "parameters": parameters,
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
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["plan"]["operation"]["name"] == command


def test_trigger_dry_run_with_fake_resource_requires_model_profile(client: TestClient):
    payload = {
        "command": "trigger-step",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "dry_run": True,
            "simulate": False,
        },
        "parameters": {
            "channel": 1,
            "source": "bus",
            "fire": True,
            "wait_complete": False,
            "poll_ms": 200,
        },
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
    error = job_data.get("error") or ""
    assert "require --model" in error or "known deterministic SIM resource" in error


def test_trigger_dry_run_with_e36312a_sim_resource_infers_model(client: TestClient):
    payload = {
        "command": "trigger-step",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "dry_run": True,
            "simulate": False,
        },
        "parameters": {
            "channel": 1,
            "source": "bus",
            "fire": True,
            "wait_complete": False,
            "poll_ms": 200,
        },
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
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["plan"]["target"]["planning_model_id"] == "keysight-e36312a"


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


def test_post_job_simulate_set_accepts_voltage_only(client: TestClient):
    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "timeout_ms": 5000,
            "confirm": False,
        },
        "parameters": {"channel": 1, "voltage": 5.0},
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
    assert [step["action"] for step in job_data["result"]["steps"]] == ["set_voltage"]
    assert job_data["parameters"] == {"channel": 1, "voltage": 5.0}


def test_post_job_rejects_set_without_setpoints(client: TestClient):
    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "timeout_ms": 5000,
            "confirm": False,
        },
        "parameters": {"channel": 1},
    }
    response = client.post("/api/jobs", json=payload)

    assert response.status_code == 400
    assert "set requires voltage, current, or both" in response.json()["detail"]


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
    from powers_tool_webui import commands

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
    from powers_tool_core.core import RuntimeOptions
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import Job

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


def test_webui_raw_live_expected_model_match_uses_idn_driver(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "ASRL1::INSTR",
                "simulate": False,
                "dry_run": False,
                "confirm": True,
                "expected_model_id": "keysight-e3646a",
            },
            "parameters": {"channel": 1, "voltage": 1, "current": 0.05},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["idn"]["model"] == "E3646A"
    assert session.queries[0] == "*IDN?"
    assert "INST:NSEL 1" in session.writes
    assert "CURR 0.05" in session.writes
    assert "VOLT 1" in session.writes
    assert "CURR 0.05,(@1)" not in session.writes
    assert "VOLT 1,(@1)" not in session.writes


def test_webui_resource_capabilities_enforces_exact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import Job

    session = FakeCoreSession("KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(commands, "open_resource", lambda *args, **kwargs: session)

    result = commands.execute_job_command(
        Job(
            "capabilities-live",
            "capabilities",
            {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            {},
        )
    )

    assert result["driver"]["class"] == "E36312APowerSupply"
    assert result["live_support"]["evaluated"] is True
    assert result["live_support"]["schema_version"] == 2
    assert result["live_support"]["model_id"] == "keysight-e36312a"
    assert "model" not in result["live_support"]
    assert result["live_support"]["transport_scope"] == "usb"
    assert result["live_support"]["backend_scope"] == "system_visa"
    assert result["live_support"]["policy_mode"] == "product"
    assert result["live_support"]["commands"]["set"]["product_open"] is True
    assert result["live_support"]["commands"]["output-on"]["product_open"] is False
    sequence_features = result["live_support"]["commands"]["sequence"]["features"]
    assert {feature["feature_kind"] for feature in sequence_features} == {
        "sequence_action"
    }
    assert all(feature["product_open"] for feature in sequence_features)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_resource_capabilities_rejects_pending_backend_after_idn(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import commands

    session = FakeCoreSession("KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(commands, "open_resource", lambda *args, **kwargs: session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "capabilities",
            "runtime": {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "simulate": False,
                "dry_run": False,
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "transport_pending" in job_data["error"]
    assert "policy_mode=product" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_identify_returns_pending_exact_metadata_without_opening_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import Job

    session = FakeCoreSession(
        "KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    result = commands.execute_job_command(
        Job(
            "identify-pending",
            "identify",
            {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "expected_model_id": "keysight-e36312a",
                "simulate": False,
                "dry_run": False,
            },
            {},
        )
    )

    live_support = result["live_support"]
    assert live_support["evaluated"] is True
    assert live_support["schema_version"] == 2
    assert live_support["model_id"] == "keysight-e36312a"
    assert "model" not in live_support
    assert live_support["transport_scope"] == "tcpip"
    assert live_support["backend_scope"] == "pyvisa_py"
    assert live_support["policy_mode"] == "product"
    assert live_support["commands"]["set"]["exact_scope_validation_status"] == "transport_pending"
    assert live_support["commands"]["set"]["product_open"] is False
    assert live_support["commands"]["identify"]["policy_exempt"] is True
    assert live_support["commands"]["identify"]["product_open"] is True
    assert live_support["commands"]["snapshot-diff"]["offline_only"] is True
    assert live_support["commands"]["snapshot-diff"]["product_open"] is False
    serialized = json.dumps(live_support)
    assert ".tmp_tests" not in serialized
    assert "SERIAL0000" not in serialized
    assert "192.0.2.1" not in serialized
    assert '"artifact"' not in serialized
    assert '"evidence"' not in serialized
    assert session.queries == ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize("command", ["identify", "verify"])
@pytest.mark.parametrize("manufacturer", ["OTHER_VENDOR", "Agilent Technologies"])
def test_webui_diagnostic_wrong_vendor_known_model_has_no_exact_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    manufacturer: str,
) -> None:
    session = FakeCoreSession(
        f"{manufacturer},E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {"resource": "USB0::FAKE::INSTR"},
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    result = job_data["result"]
    detected_idn = result["idn"] if command == "identify" else result["resource"]["idn"]
    assert detected_idn["manufacturer"] == manufacturer
    assert detected_idn["model"] == "E36312A"
    assert result["live_support"]["evaluated"] is False
    assert result["live_support"]["commands"] == {}
    assert "manufacturer and model" in result["live_support"]["reason"]
    assert session.writes == []


@pytest.mark.parametrize("command", ["identify", "verify"])
def test_webui_diagnostic_narrow_e3646a_alias_has_exact_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    session = FakeCoreSession(
        "Agilent Technologies,E3646A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {"resource": "ASRL1::INSTR"},
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    live_support = job_data["result"]["live_support"]
    assert live_support["evaluated"] is True
    assert live_support["schema_version"] == 2
    assert live_support["model_id"] == "keysight-e3646a"
    assert "model" not in live_support
    assert live_support["transport_scope"] == "asrl"
    assert live_support["backend_scope"] == "system_visa"
    assert live_support["commands"][command]["product_open"] is True
    assert session.writes == []


def test_webui_diagnostic_expected_model_cannot_override_wrong_vendor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession(
        "OTHER_VENDOR,E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "identify",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "resolved to unknown" in job_data["error"]
    assert session.writes == []


@pytest.mark.parametrize("command", ["identify", "verify"])
def test_webui_diagnostic_wrong_vendor_different_model_preserves_expected_guard(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    session = FakeCoreSession("OTHER_VENDOR,E36312A,SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "expected_model_id": "keysight-e3646a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e3646a" in job_data["error"]
    assert "resolved to unknown" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize("command", ["identify", "verify"])
@pytest.mark.parametrize("model", ["UNKNOWN_MODEL", "E36103B"])
def test_webui_diagnostic_unknown_or_descoped_model_returns_neutral_live_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    model: str,
) -> None:
    session = FakeCoreSession(
        f"KEYSIGHT,{model},SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    result = job_data["result"]
    detected_idn = result["idn"] if command == "identify" else result["resource"]["idn"]
    assert detected_idn["model"] == model
    assert result["live_support"] == {
        "schema_version": 2,
        "evaluated": False,
        "model_id": None,
        "reported_manufacturer": "KEYSIGHT",
        "reported_model": model,
        "transport_scope": "usb",
        "backend_scope": "system_visa",
        "policy_mode": "product",
        "commands": {},
        "reason": (
            "The reported manufacturer and model do not resolve to active "
            "exact live-support metadata."
        ),
    }
    serialized = json.dumps(result["live_support"])
    assert "SERIAL0000" not in serialized
    assert "USB0::FAKE::INSTR" not in serialized
    assert '"evidence"' not in serialized
    assert '"artifact"' not in serialized
    expected_queries = (
        ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
        if command == "identify"
        else ["*IDN?"]
    )
    assert session.queries == expected_queries
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize("command", ["identify", "verify"])
def test_webui_diagnostic_expected_model_mismatch_remains_a_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e36312a" in job_data["error"]
    assert "keysight-e3646a" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_unknown_model_normal_live_command_remains_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("KEYSIGHT,UNKNOWN_MODEL,SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "read-status",
            "runtime": {"resource": "USB0::FAKE::INSTR"},
            "parameters": {"channel": 1},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "unknown live support-policy model_id for reported model 'UNKNOWN_MODEL'" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_pending_command_remains_product_rejected_after_identify_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("KEYSIGHT,E36312A,SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "expected_model_id": "keysight-e36312a",
                "confirm": True,
            },
            "parameters": {"channel": 1, "voltage": 1.0, "current": 0.05},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "transport_pending" in job_data["error"]
    assert "policy_mode=product" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_identify_expected_model_mismatch_precedes_extended_identity_queries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "identify",
            "runtime": {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e36312a" in job_data["error"]
    assert "keysight-e3646a" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_simulated_identify_does_not_claim_evaluated_live_support(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "identify",
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True,
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["live_support"]["evaluated"] is False
    assert job_data["result"]["live_support"]["commands"] == {}
    assert "real hardware only" in job_data["result"]["live_support"]["reason"]


@pytest.mark.parametrize(
    "field",
    ["support_policy_mode", "validation_allow_pending_live_support", "validation-allow-pending-live-support"],
)
def test_webui_rejects_forged_validation_mode_fields(client: TestClient, field: str) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "measure",
            "runtime": {"resource": "TCPIP0::192.0.2.1::INSTR", field: "validation"},
            "parameters": {"channel": 1},
        },
    )
    assert response.status_code == 400
    assert "validation support policy fields are not allowed" in response.json()["detail"]


def test_webui_runtime_options_are_always_product_mode() -> None:
    from powers_tool_webui.commands import build_runtime_options

    runtime = build_runtime_options(
        {"resource": "TCPIP0::192.0.2.1::INSTR", "support_policy_mode": "validation"}
    )
    assert runtime.support_policy_mode == "product"


def test_webui_raw_live_expected_model_mismatch_fails_before_output_writes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
                "confirm": True,
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {"channel": 1, "voltage": 1, "current": 0.05},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e36312a" in job_data["error"]
    assert "resolved to keysight-e3646a" in job_data["error"]
    assert "does not override" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []


@pytest.mark.parametrize("model", ["E36103B", "E36232A"])
def test_webui_live_job_blocks_descoped_idn_before_generic_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    session = FakeCoreSession(f"KEYSIGHT,{model},SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "read-status",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            "parameters": {"channel": 1},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert model in job_data["error"]
    assert "de-scoped and not active supported" in job_data["error"]
    assert "blocked from generic fallback" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_webui_raw_no_hardware_model_profile_behavior_is_unchanged(client: TestClient) -> None:
    explicit = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "resource": "USB0::FAKE::E3646A::INSTR",
                "dry_run": True,
                "simulate": False,
                "planning_model_id": "keysight-e3646a",
            },
            "parameters": {"channel": "all"},
        },
    )
    assert explicit.status_code == 200
    explicit_job = wait_for_job(client, explicit.json()["job_id"])
    assert explicit_job["status"] == "finished", explicit_job.get("error")
    assert explicit_job["result"]["target"]["planning_model_id"] == "keysight-e3646a"
    assert [step["parameters"]["channel"] for step in explicit_job["result"]["steps"]] == [1, 2]

    inferred = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "resource": "ASRL1::SIM::E3646A::INSTR",
                "dry_run": True,
                "simulate": False,
            },
            "parameters": {"channel": "all"},
        },
    )
    assert inferred.status_code == 200
    inferred_job = wait_for_job(client, inferred.json()["job_id"])
    assert inferred_job["status"] == "finished", inferred_job.get("error")
    assert inferred_job["result"]["target"]["planning_model_id"] == "keysight-e3646a"

    missing = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "resource": "USB0::FAKE::E3646A::INSTR",
                "dry_run": True,
                "simulate": False,
            },
            "parameters": {"channel": 1},
        },
    )
    assert missing.status_code == 200
    missing_job = wait_for_job(client, missing.json()["job_id"])
    assert missing_job["status"] == "failed"
    assert "require planning_model_id" in missing_job["error"]

    missing_simulate = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "simulate": True,
            },
            "parameters": {"channel": 1},
        },
    )
    assert missing_simulate.status_code == 200
    missing_simulate_job = wait_for_job(client, missing_simulate.json()["job_id"])
    assert missing_simulate_job["status"] == "failed"
    assert "require planning_model_id" in missing_simulate_job["error"]


@pytest.mark.parametrize("model", ["keysight-e36103b", "keysight-e36232a"])
@pytest.mark.parametrize("runtime_mode", ["dry_run", "simulate", "live"])
def test_webui_direct_jobs_reject_descoped_model_profiles(
    client: TestClient,
    model: str,
    runtime_mode: str,
) -> None:
    runtime: dict[str, Any] = {}
    if runtime_mode == "dry_run":
        runtime["dry_run"] = True
        runtime["planning_model_id"] = model
    elif runtime_mode == "simulate":
        runtime["simulate"] = True
        runtime["planning_model_id"] = model
    else:
        runtime["resource"] = "USB0::FAKE::INSTR"
        runtime["confirm"] = True
        runtime["expected_model_id"] = model

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": runtime,
            "parameters": {"channel": 1, "voltage": 1, "current": 0.05},
        },
    )

    assert response.status_code == 400
    assert "not active or candidate" in response.json()["detail"]
    assert model in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "fragments"),
    [
        (
            {
                "command": "trigger-step",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
                "parameters": {"channel": 1, "source": "bus", "fire": True},
            },
            ("E36312A",),
        ),
        (
            {
                "command": "trigger-list",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
                "parameters": {
                    "channel": 1,
                    "source": "bus",
                    "fire": True,
                    "wait_complete": True,
                    "voltage_list": [0.0, 1.0],
                    "current_list": [0.05, 0.05],
                    "dwell_list": [0.01, 0.01],
                },
            },
            ("E36312A",),
        ),
        (
            {
                "command": "snapshot",
                "runtime": {"simulate": True, "resource": "USB0::SIM::EDU36311A::INSTR"},
                "parameters": {},
            },
            ("E36312A",),
        ),
        (
            {
                "command": "restore-from-snapshot",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
                "parameters": {"document": policy_snapshot_document("EDU36311A"), "channel": 1},
            },
            ("E36312A",),
        ),
    ],
)
def test_webui_direct_jobs_reject_edu36311a_disabled_workflows(
    client: TestClient,
    payload: dict[str, Any],
    fragments: tuple[str, ...],
) -> None:
    assert_direct_job_rejected(client, payload, *fragments)


@pytest.mark.parametrize(
    ("payload", "fragments"),
    [
        (
            {
                "command": "protection-set",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1, "ovp_voltage": 5.0},
            },
            ("not",),
        ),
        (
            {
                "command": "clear-protection",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1},
            },
            ("E3646A", "protection workflows are disabled"),
        ),
        (
            {
                "command": "trigger-pulse",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1, "pins": [1], "polarity": "positive"},
            },
            ("E3646A", "completion-pulse workflows are disabled"),
        ),
        (
            {
                "command": "trigger-step",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1, "source": "bus", "fire": True},
            },
            ("E3646A", "native LIST and trigger workflows are disabled"),
        ),
        (
            {
                "command": "trigger-list",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {
                    "channel": 1,
                    "source": "bus",
                    "fire": True,
                    "wait_complete": True,
                    "voltage_list": [0.0, 1.0],
                    "current_list": [0.05, 0.05],
                    "dwell_list": [0.01, 0.01],
                },
            },
            ("E3646A", "software workflows, not native LIST"),
        ),
        (
            {
                "command": "snapshot",
                "runtime": {"simulate": True, "resource": "ASRL1::SIM::E3646A::INSTR"},
                "parameters": {},
            },
            ("E3646A", "snapshot/restore workflows are disabled"),
        ),
        (
            {
                "command": "restore-from-snapshot",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"document": policy_snapshot_document("E3646A"), "channel": 1},
            },
            ("E3646A", "snapshot/restore workflows are disabled"),
        ),
        (
            {
                "command": "sequence",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"document": {"version": 1, "steps": [{"action": "trigger-pulse", "channel": 1, "pins": [1]}]}},
            },
            ("E36312A",),
        ),
    ],
)
def test_webui_direct_jobs_reject_e3646a_disabled_workflows(
    client: TestClient,
    payload: dict[str, Any],
    fragments: tuple[str, ...],
) -> None:
    assert_direct_job_rejected(client, payload, *fragments)


def test_webui_direct_jobs_reject_edu36311a_sequence_trigger_pulse(client: TestClient) -> None:
    assert_direct_job_rejected(
        client,
        {
            "command": "sequence",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
            "parameters": {
                "document": {
                    "version": 1,
                    "steps": [{"action": "trigger-pulse", "channel": 1, "pins": [1]}],
                }
            },
        },
        "keysight-edu36311a",
        "E36312A",
    )


@pytest.mark.parametrize(
    "action",
    [
        "protection-set",
        "clear-protection",
        "trigger-pulse",
        "trigger-list",
        "snapshot",
        "restore-from-snapshot",
        "native-list",
        "completion-pulse",
    ],
)
def test_webui_direct_jobs_reject_e3646a_unsupported_sequence_steps(
    client: TestClient,
    action: str,
) -> None:
    assert_direct_job_rejected(
        client,
        {
            "command": "sequence",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
            "parameters": {
                "document": {
                    "version": 1,
                    "steps": [{"action": action, "channel": 1, "pins": [1]}],
                }
            },
        },
        "unsupported" if action != "trigger-pulse" else "E36312A",
    )


def test_webui_direct_e3646a_sequence_validated_read_only_and_output_steps_allowed(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "sequence",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
            "parameters": {
                "document": {
                    "version": 1,
                    "steps": [
                        {"action": "readback", "channel": 1},
                        {"action": "set", "channel": 2, "voltage": 1.0, "current": 0.05},
                        {"action": "output-off", "channel": 2},
                    ],
                }
            },
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["plan"]["target"]["planning_model_id"] == "keysight-e3646a"


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
    from powers_tool_webui.jobs import job_manager
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
    from powers_tool_webui.jobs import job_manager
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


def test_ramp_list_lint_dry_run(client: TestClient):
    payload = {
        "command": "ramp-list",
        "runtime": {"simulate": True, "dry_run": True, "resource": "USB0::SIM::E36312A::INSTR"},
        "parameters": {
            "lint": True,
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
                        "delay_ms": 100,
                        "hold_ms": 0,
                    }
                ],
            },
        },
    }

    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(20):
        job_data = client.get(f"/api/jobs/{job_id}").json()
        if job_data["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    assert job_data["status"] == "finished"
    assert job_data["result"]["status"] == "valid"
    assert job_data["result"]["segment_count"] == 1


def test_api_accepts_zero_delay_ramp_list_step_pulse(client: TestClient):
    payload = {
        "command": "ramp-list",
        "runtime": {"simulate": True, "dry_run": True},
        "parameters": {
            "document": {
                "kind": "keysight-power-ramp-list",
                "version": 1,
                "completion_pulse": {"timing": "step", "pins": [1], "polarity": "positive"},
                "segments": [{
                    "channel": 1, "current": 0.1, "start_voltage": 0, "stop_voltage": 1,
                    "step_voltage": 0.5, "delay_ms": 0, "hold_ms": 0,
                }],
            },
        },
    }

    response = client.post("/api/jobs", json=payload)

    assert response.status_code == 200


@pytest.mark.parametrize("field", ["completion_pulse_mode", "completion_pulse_dwell_ms", "wait_timeout_ms", "poll_ms"])
def test_api_rejects_removed_ramp_native_fields_before_creating_job(client: TestClient, field: str):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp",
            "runtime": {"simulate": True},
            "parameters": {
                "channel": 1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 0.5,
                "current": 0.1,
                field: "native" if field == "completion_pulse_mode" else 10,
            },
        },
    )

    assert response.status_code == 400
    assert field in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


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
    from powers_tool_webui.jobs import job_manager
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
    from powers_tool_webui.jobs import job_manager
    job = job_manager.jobs.get(job_id)
    assert job.cancel_requested is True


def test_live_data_live_panel_emits_three_channel_panel_sample(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        calls.append((runtime, parameters))
        return _fake_live_panel(runtime.resource)

    from powers_tool_webui import commands

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
    assert sample["model"] == "E36312A"
    assert sample["mode"] == "live"
    assert [channel["channel"] for channel in sample["channels"]] == [1, 2, 3]
    assert [channel["measured_voltage"] for channel in sample["channels"]] == [1.1, 2.2, 3.3]
    assert [channel["measured_current"] for channel in sample["channels"]] == [0.11, 0.22, 0.33]
    assert [channel["set_voltage"] for channel in sample["channels"]] == [1.0, 2.0, 3.0]
    assert [channel["set_current"] for channel in sample["channels"]] == [0.1, 0.2, 0.3]
    assert [channel["output_enabled"] for channel in sample["channels"]] == [True, False, True]
    assert [channel["over_voltage_tripped"] for channel in sample["channels"]] == [False, False, False]
    assert [channel["over_current_tripped"] for channel in sample["channels"]] == [True, False, False]
    assert [channel["protection_tripped"] for channel in sample["channels"]] == [True, False, False]
    assert [channel["over_voltage_protection_level"] for channel in sample["channels"]] == [5.0, 6.0, 7.0]
    assert [channel["over_current_protection_enabled"] for channel in sample["channels"]] == [True, False, True]
    assert calls
    assert calls[0][0].simulate is False
    assert calls[0][1] == {}

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


@pytest.mark.parametrize("envelope_key", ["result", "data"])
def test_live_data_live_panel_unwraps_envelope(envelope_key: str):
    from powers_tool_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {envelope_key: _fake_e36312a_live_panel("USB0::FAKE::E36312A::INSTR")},
        {"resource": "USB0::FAKE::E36312A::INSTR"},
    )

    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["mode"] == "live"
    assert sample["channels"][0]["measured_voltage"] == 1.000237
    assert sample["channels"][0]["measured_current"] == 0.000019
    assert sample["channels"][0]["set_voltage"] == 1.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert sample["channels"][0]["over_voltage_tripped"] is False
    assert sample["channels"][0]["over_current_tripped"] is False
    assert sample["channels"][0]["protection_tripped"] is False
    assert sample["channels"][0]["over_voltage_protection_level"] == 5.0
    assert sample["channels"][0]["over_current_protection_enabled"] is True
    assert sample["channels"][1]["set_voltage"] == 0.0
    assert sample["channels"][1]["over_current_protection_enabled"] is False
    assert sample["channels"][2]["measured_current"] == 0.0


def test_live_data_live_panel_with_no_panel_records_is_stale_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        return {"resource": runtime.resource, "model": "E36312A"}

    from powers_tool_webui import commands

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
    assert [channel["protection_tripped"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["over_voltage_protection_level"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["over_current_protection_enabled"] for channel in sample["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


def test_live_data_panel_sample_normalizes_numeric_values():
    from powers_tool_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "idn": {"model": "E36312A"},
            "outputs": [
                {"channel": 1, "enabled": "0"},
                {"channel": 2, "enabled": "OFF"},
                {"channel": 3, "enabled": 2},
            ],
            "readback": [
                {"channel": 1, "setpoints": {"voltage": "1", "current": "0.1"}},
                {"channel": 2, "setpoints": {"voltage": "", "current": None}},
            ],
            "measurements": [
                {"channel": 1, "measurements": {"voltage": "1.000237", "current": "0.000019"}},
                {"channel": 2, "measurements": {"voltage": "nan", "current": "inf"}},
            ],
            "channels": [
                {
                    "channel": 1,
                    "output_enabled": "ON",
                    "over_voltage_tripped": "0",
                    "over_current_tripped": "1",
                    "over_voltage_protection_level": "5.5",
                    "over_current_protection_enabled": "on",
                },
                {
                    "channel": 2,
                    "output_enabled": "unknown",
                    "over_voltage_tripped": None,
                    "over_current_tripped": None,
                    "protection_tripped": "false",
                    "over_voltage_protection_level": "nan",
                    "over_current_protection_enabled": "off",
                },
            ],
        },
        {"resource": "USB0::FAKE::E36312A::INSTR"},
    )

    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["model"] == "E36312A"
    assert sample["channels"][0]["measured_voltage"] == 1.000237
    assert sample["channels"][0]["measured_current"] == 0.000019
    assert sample["channels"][0]["set_voltage"] == 1.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert [channel["output_enabled"] for channel in sample["channels"]] == [True, False, None]
    assert sample["channels"][1]["measured_voltage"] is None
    assert sample["channels"][1]["measured_current"] is None
    assert sample["channels"][1]["set_voltage"] is None
    assert sample["channels"][1]["set_current"] is None
    assert sample["channels"][0]["over_voltage_tripped"] is False
    assert sample["channels"][0]["over_current_tripped"] is True
    assert sample["channels"][0]["protection_tripped"] is True
    assert sample["channels"][0]["over_voltage_protection_level"] == 5.5
    assert sample["channels"][0]["over_current_protection_enabled"] is True
    assert sample["channels"][1]["protection_tripped"] is False
    assert sample["channels"][1]["over_voltage_protection_level"] is None
    assert sample["channels"][1]["over_current_protection_enabled"] is False


def test_live_data_real_mode_reports_busy_without_live_panel_call(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import job_manager

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
    assert [channel["protection_tripped"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["over_voltage_protection_level"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["over_current_protection_enabled"] for channel in event["data"]["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200
    job_manager.active_job_id = None


def test_real_command_waits_for_inflight_live_panel_without_overlap(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from powers_tool_webui import app as web_app
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import job_manager

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

    from powers_tool_webui.jobs import job_manager
    job = job_manager.jobs[job_id]
    progress_count = sum(1 for event in job.events if event["type"] == "progress")
    time.sleep(0.15)
    assert sum(1 for event in job.events if event["type"] == "progress") == progress_count


def _wait_for_live_progress(job_id: str) -> dict[str, Any]:
    from powers_tool_webui.jobs import job_manager

    for _ in range(30):
        job = job_manager.jobs[job_id]
        if job.status.value in {"failed", "cancelled"}:
            raise AssertionError(f"live job ended before progress: {job.status.value}: {job.error}")
        progress = [event for event in job.events if event["type"] == "progress"]
        if progress:
            return progress[-1]
        time.sleep(0.05)
    raise AssertionError("live progress event was not emitted")


def _wait_for_live_terminal_status(job_id: str) -> None:
    from powers_tool_webui.jobs import job_manager

    for _ in range(30):
        if job_manager.jobs[job_id].status.value in {"finished", "failed", "cancelled"}:
            return
        time.sleep(0.05)
    raise AssertionError("live job did not stop")


def _patch_live_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    from powers_tool_webui import commands

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        assert runtime.simulate is False
        return _fake_live_panel(runtime.resource)

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)


def _fake_live_panel(resource: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "idn": {"model": "E36312A"},
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
        "channels": [
            {
                "channel": 1,
                "over_voltage_tripped": False,
                "over_current_tripped": True,
                "over_voltage_protection_level": 5.0,
                "over_current_protection_enabled": True,
            },
            {
                "channel": 2,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": 6.0,
                "over_current_protection_enabled": False,
            },
            {
                "channel": 3,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": 7.0,
                "over_current_protection_enabled": True,
            },
        ],
    }


def _fake_e36312a_live_panel(resource: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "idn": {"model": "E36312A"},
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
        "channels": [
            {
                "channel": 1,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": "5.0",
                "over_current_protection_enabled": "1",
            },
            {
                "channel": 2,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": "5.0",
                "over_current_protection_enabled": "0",
            },
            {
                "channel": 3,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": "5.0",
                "over_current_protection_enabled": "1",
            },
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
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
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


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("verify", {}),
        ("readback", {"channel": "all"}),
        ("safety inspect", {}),
    ],
)
def test_hidden_diagnostic_commands_remain_directly_submittable(client: TestClient, command: str, parameters: dict[str, Any]):
    payload = {
        "command": command,
        "runtime": {
            "simulate": True,
            "resource": "USB0::SIM::E36312A::INSTR",
        },
        "parameters": parameters,
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        job_data = client.get(f"/api/jobs/{job_id}").json()
        if job_data["status"] in ("finished", "failed"):
            break
        time.sleep(0.05)

    assert job_data["status"] == "finished", job_data.get("error")


def test_webui_capabilities_rejects_explicit_sim_resource_mismatch(client: TestClient):
    payload = {
        "command": "capabilities",
        "runtime": {
            "simulate": True,
            "resource": "USB0::SIM::EDU36311A::INSTR",
            "planning_model_id": "keysight-e36312a",
        },
        "parameters": {},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "does not match deterministic SIM" in response.json()["detail"]


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


def test_running_cancel_keeps_hardware_lock_until_cleanup_completes():
    import asyncio

    from powers_tool_webui.jobs import JobManager, JobStatus

    async def check_lifecycle() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "output-on",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"channel": 1},
        )
        assert await manager.start_job(job_id) is True
        assert manager.active_job_id == job_id

        assert await manager.cancel_job(job_id) is True
        assert manager.jobs[job_id].status == JobStatus.CANCEL_REQUESTED
        assert manager.active_job_id == job_id

        await manager.complete_cancel(job_id)
        assert manager.jobs[job_id].status == JobStatus.CANCELLED
        assert manager.active_job_id is None

    asyncio.run(check_lifecycle())


def test_static_json_artifact_file_helpers_have_cancel_and_accept_contracts():
    _index_html, app_js, _styles_css = read_static_texts()

    open_json = extract_js_function(app_js, "openJsonFile")
    choose_json = extract_js_function(app_js, "chooseJsonFile")
    save_json = extract_js_function(app_js, "saveJsonFile")
    build_accept = extract_js_function(app_js, "buildJsonFileAccept")
    build_native_accept = extract_js_function(app_js, "buildNativeJsonPickerAccept")

    assert 'const JSON_MIME_TYPE = "application/json";' in app_js
    assert 'const SNAPSHOT_JSON_EXTENSIONS = [".snapshot.json", ".json"];' in app_js
    assert 'const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];' in app_js
    assert 'const RAMP_LIST_JSON_EXTENSIONS = [".ramp-list.json", ".json"];' in app_js
    assert 'return { [JSON_MIME_TYPE]: [".json"] };' in build_native_accept
    assert "const acceptMap = buildNativeJsonPickerAccept();" in open_json
    assert "const acceptMap = buildNativeJsonPickerAccept();" in save_json
    assert "{ [JSON_MIME_TYPE]: extensions }" not in open_json
    assert "{ [JSON_MIME_TYPE]: extensions }" not in save_json
    assert "chooseJsonFile(buildJsonFileAccept(extensions))" in open_json
    assert 'return [...extensions, JSON_MIME_TYPE].join(",");' in build_accept
    assert 'input.addEventListener("cancel", abort);' in choose_json
    assert 'window.addEventListener("focus", onWindowFocus, { once: true });' in choose_json
    assert 'abortError("File selection cancelled.")' in choose_json
    assert "document.body.appendChild(link);" in save_json
    assert "window.setTimeout(() => URL.revokeObjectURL(url), 0);" in save_json

def test_static_json_artifact_abort_errors_do_not_render_client_failures():
    _index_html, app_js, _styles_css = read_static_texts()

    for function_name in (
        "loadRampList",
        "saveRampList",
        "saveSnapshot",
        "loadRestoreSnapshot",
        "loadSequenceFile",
        "saveSequenceFile",
    ):
        block = extract_js_function(app_js, function_name)
        assert "catch (error)" in block
        catch_block = block[block.index("catch (error)"):]
        assert "if (isAbortError(error)) return;" in catch_block
        assert catch_block.index("if (isAbortError(error)) return;") < catch_block.index("renderClientResult(")


def test_static_snapshot_completion_validates_finished_result_before_saving_state():
    _index_html, app_js, _styles_css = read_static_texts()

    handle_job_event = extract_js_function(app_js, "handleJobEvent")
    capture_snapshot = extract_js_function(app_js, "captureLatestSnapshotDocument")

    assert "captureLatestSnapshotDocument(job);" in handle_job_event
    assert "state.latestSnapshotDocument = job.result;" not in handle_job_event
    assert 'job.command !== "snapshot"' in capture_snapshot
    assert 'job.status !== "finished"' in capture_snapshot
    assert "!job.result" in capture_snapshot
    assert "validateSnapshotDocument(job.result);" in capture_snapshot
    assert capture_snapshot.index("validateSnapshotDocument(job.result);") < capture_snapshot.index("state.latestSnapshotDocument = job.result;")
    assert "return false;" in capture_snapshot


def test_static_snapshot_save_validator_is_independent_from_restore_validator():
    _index_html, app_js, _styles_css = read_static_texts()

    snapshot_validator = extract_js_function(app_js, "validateSnapshotDocument")
    restore_validator = extract_js_function(app_js, "validateRestoreSnapshot")
    save_snapshot = extract_js_function(app_js, "saveSnapshot")

    assert "validateRestoreSnapshot" not in snapshot_validator
    assert "Array.isArray(doc)" in snapshot_validator
    assert "doc.idn" in snapshot_validator
    assert "doc.readback" in snapshot_validator
    assert "doc.outputs" in snapshot_validator
    assert "setpoints" not in snapshot_validator
    assert "E36312A" not in snapshot_validator

    assert "validateSnapshotDocument(doc);" in restore_validator
    assert "setpoints" in restore_validator
    assert "E36312A" in restore_validator
    assert "JSON.stringify(state.latestSnapshotDocument, null, 2)" in save_snapshot


def test_static_restore_payload_preflights_and_normalizes_channel():
    _index_html, app_js, _styles_css = read_static_texts()

    run_selected = extract_js_function(app_js, "runSelected")
    parameter_payload = extract_js_function(app_js, "parameterPayload")
    restore_parameters = extract_js_function(app_js, "restoreSnapshotParameters")
    normalize_restore_channel = extract_js_function(app_js, "normalizeRestoreChannel")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert "let validatedRestoreDocument = null;" in run_selected
    assert 'state.selected === "restore-from-snapshot"' in run_selected
    assert "validateRestoreSnapshot(state.loadedSnapshotDocument);" in run_selected
    assert "restoreSnapshotParameters(validatedRestoreDocument)" in run_selected
    assert run_selected.index('state.selected === "restore-from-snapshot"') < run_selected.index("const response = await submitJob(payload);")
    assert "restoreSnapshotParameters(state.loadedSnapshotDocument)" in parameter_payload
    assert "channel: normalizeRestoreChannel(state.restoreChannel)" in restore_parameters
    assert "file:" not in restore_parameters
    assert "snapshot:" not in restore_parameters
    assert 'return value === "all" ? "all" : normalizeChannelValue(value);' in normalize_restore_channel
    assert "isLoadedRestoreSnapshotValid();" in update_selected


def test_static_restore_plan_preview_reuses_dry_run_job():
    _index_html, app_js, _styles_css = read_static_texts()

    render_restore = extract_js_function(app_js, "renderRestoreForm")
    preview_restore = extract_js_function(app_js, "previewRestorePlan")
    handle_job_event = extract_js_function(app_js, "handleJobEvent")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert 'previewPlanBtn.id = "btn-preview-restore-plan";' in render_restore
    assert "previewPlanBtn.textContent =" in render_restore
    assert 'previewPlanBtn.disabled = !isLoadedRestoreSnapshotValid() || state.restorePlanPreviewStatus === "running";' in render_restore
    assert "Loaded snapshot JSON" not in render_restore
    assert "Snapshot JSON Preview" not in render_restore
    assert "restore-preview" not in render_restore
    assert 'command: "restore-from-snapshot"' in preview_restore
    assert "dry_run: true" in preview_restore
    assert "confirm: true" in preview_restore
    assert "parameters: restoreSnapshotParameters(state.loadedSnapshotDocument)" in preview_restore
    assert 'addHistory(response.job_id, "restore-from-snapshot", "accepted"' in preview_restore
    assert "subscribeToJob(response.job_id, \"/api/events\");" in preview_restore
    assert "jobLabel(jobId) ===" in handle_job_event
    assert "captureRestorePlanPreview(job);" in handle_job_event
    assert 'document.getElementById("btn-preview-restore-plan")' in update_selected


def test_static_restore_plan_preview_is_safe_and_structured():
    _index_html, app_js, _styles_css = read_static_texts()

    render_restore = extract_js_function(app_js, "renderRestoreForm")
    render_preview = extract_js_function(app_js, "renderRestorePlanPreview")
    capture_preview = extract_js_function(app_js, "captureRestorePlanPreview")

    assert 'planPreview.id = "restore-plan-preview";' in render_restore
    assert "plan.steps.forEach((step)" in render_preview
    assert "step.command" in render_preview
    assert "command.textContent = step.command || \"\";" in render_preview
    assert "innerHTML" not in render_preview
    assert 'state.restorePlanPreviewStatus = "finished";' in capture_preview


def test_static_snapshot_max_errors_documents_destructive_queue_reads():
    _index_html, app_js, _styles_css = read_static_texts()

    render_snapshot = extract_js_function(app_js, "renderSnapshotForm")
    append_description = extract_js_function(app_js, "appendFieldDescription")

    assert 'snapshot: [{' in app_js
    assert 'name: "max_errors"' in app_js
    assert "appendFieldDescription(label, param);" in render_snapshot
    assert 'description.className = "field-description";' in append_description
    assert "description.textContent = param.description;" in append_description


def test_static_safe_off_channel_documents_behavior():
    _index_html, app_js, _styles_css = read_static_texts()

    safe_off_block = app_js[app_js.index('"safe-off": ['):app_js.index('"cycle-output": [')]
    assert 'name: "channel"' in safe_off_block
    assert 'description:' in safe_off_block
    assert 'options: ["all", "1", "2", "3"]' in safe_off_block
    assert 'value: "all"' in safe_off_block


def test_static_restore_load_unwrap_contract():
    _index_html, app_js, _styles_css = read_static_texts()

    load_restore = extract_js_function(app_js, "loadRestoreSnapshot")
    unwrap_snapshot = extract_js_function(app_js, "unwrapSnapshot")

    assert "extensions: SNAPSHOT_JSON_EXTENSIONS" in load_restore
    assert "const rawDoc = JSON.parse(text);" in load_restore
    assert "const unwrapped = unwrapSnapshot(rawDoc);" in load_restore
    assert "validateRestoreSnapshot(unwrapped);" in load_restore
    assert 'doc.command === "snapshot"' in unwrap_snapshot
    assert "doc.result" in unwrap_snapshot
    assert "!Array.isArray(doc.result)" in unwrap_snapshot
    assert "doc.data" in unwrap_snapshot
    assert "!Array.isArray(doc.data)" in unwrap_snapshot


def test_static_sequence_json_artifact_flow_contracts():
    _index_html, app_js, _styles_css = read_static_texts()

    sequence_fields = extract_js_function(app_js, "sequenceStepFields")

    assert 'const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];' in app_js
    assert "dataset.sequenceStepIndex" in app_js
    assert "input.dataset.sequenceField" in app_js
    assert "state.sequenceSteps" in app_js
    assert 'command: "sequence"' in app_js
    assert "{ document: validatedSequenceDocument }" in app_js
    assert "param-document" not in app_js
    assert "option.value = action;" in sequence_fields
    assert "option.textContent = optionDisplayName(action);" in sequence_fields
    assert "option.value = value;" in sequence_fields
    assert 'option.textContent = definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value);' in sequence_fields


def test_api_sequence_webui_step_limit(client: TestClient, tmp_path):
    from powers_tool_webui.jobs import job_manager

    steps_250 = [{"action": "wait", "seconds": 0}] * 250
    payload = {
        "command": "sequence",
        "runtime": {"simulate": True, "dry_run": True},
        "parameters": {"document": {"version": 1, "steps": steps_250}},
    }

    accepted = client.post("/api/jobs", json=payload)
    assert accepted.status_code == 200

    jobs_before = len(job_manager.jobs)
    payload["parameters"]["document"]["steps"].append({"action": "wait", "seconds": 0})
    rejected = client.post("/api/jobs", json=payload)
    assert rejected.status_code == 400
    assert len(job_manager.jobs) == jobs_before

    sequence_file = tmp_path / "too-large.sequence.json"
    sequence_file.write_text(
        json.dumps({"version": 1, "steps": payload["parameters"]["document"]["steps"]}),
        encoding="utf-8",
    )
    payload["parameters"] = {"file": str(sequence_file)}
    rejected_file = client.post("/api/jobs", json=payload)
    assert rejected_file.status_code == 400
    assert len(job_manager.jobs) == jobs_before


def test_api_restore_from_snapshot_dry_run(client: TestClient):
    """Test restore preview dry-run produces the complete plan without taking the hardware lock."""

    snapshot_doc = {
        "resource": "USB0::SIM::E36312A::INSTR",
        "idn": {
            "raw": "KEYSIGHT,E36312A,MY12345678,3.0.0",
            "manufacturer": "KEYSIGHT",
            "model": "E36312A",
            "serial": "MY12345678",
            "firmware": "3.0.0",
            "parse_ok": True
        },
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False}
        ],
        "readback": [
            {
                "channel": 1,
                "setpoints": {
                    "voltage": 5.0,
                    "current": 1.0
                }
            },
            {
                "channel": 2,
                "setpoints": {
                    "voltage": 3.3,
                    "current": 0.5
                }
            },
            {
                "channel": 3,
                "setpoints": {
                    "voltage": 12.0,
                    "current": 2.0
                }
            }
        ],
        "measurements": [],
        "protection": {
            "over_voltage_tripped": False,
            "over_current_tripped": False
        },
        "protection_settings": []
    }

    payload = {
        "command": "restore-from-snapshot",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": False,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": snapshot_doc,
            "channel": "all",
            "restore_output_state": True
        }
    }

    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert client.get("/api/health").json()["hardware_locked"] is False

    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.05)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert "error" not in job_data or job_data["error"] is None

    result = job_data["result"]
    assert "plan" in result
    assert "OUTP ON,(@1)" in [step["command"] for step in result["plan"]["steps"]]
    assert client.get("/api/health").json()["hardware_locked"] is False
    assert result["restored_channels"] == [1, 2, 3]


def test_api_sequence_execution(client: TestClient):
    """Test sequence execution with valid steps and verify non-existent action rejection."""

    valid_sequence = {
        "version": 1,
        "steps": [
            {
                "action": "set",
                "channel": 1,
                "voltage": 2.5,
                "current": 0.5
            },
            {
                "action": "wait",
                "seconds": 0.1
            },
            {
                "action": "output-off",
                "channel": 1
            }
        ]
    }

    payload = {
        "command": "sequence",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": valid_sequence
        }
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
    assert "plan" in job_data["result"]


def test_api_sequence_rejects_delay_action(client: TestClient):
    """Verify that sequence submission rejects unsupported 'delay' action on the API level."""
    invalid_sequence = {
        "version": 1,
        "steps": [
            {
                "action": "delay",
                "duration_ms": 100
            }
        ]
    }
    payload = {
        "command": "sequence",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": invalid_sequence
        }
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "unsupported sequence step" in response.json()["detail"]


def test_api_restore_from_snapshot_rejects_missing_setpoints(client: TestClient):
    """Verify that restore rejects snapshot document missing required setpoints on the API level."""
    invalid_snapshot = {
        "resource": "USB0::SIM::E36312A::INSTR",
        "idn": {
            "raw": "KEYSIGHT,E36312A,MY12345678,3.0.0",
            "manufacturer": "KEYSIGHT",
            "model": "E36312A",
            "serial": "MY12345678",
            "firmware": "3.0.0",
            "parse_ok": True
        },
        "outputs": [
            {"channel": 1, "enabled": True}
        ],
        "readback": [
            # ?? setpoints!
            {
                "channel": 1
            }
        ]
    }
    payload = {
        "command": "restore-from-snapshot",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": invalid_snapshot,
            "channel": "all"
        }
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    import time
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}").json()
        if res["status"] in ("finished", "failed"):
            break
        time.sleep(0.05)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "setpoints" in job_data["error"].lower()
