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

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "keysight_power_webui" / "static"


def read_static_texts() -> tuple[str, str, str]:
    return (
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        (STATIC_DIR / "app.js").read_text(encoding="utf-8"),
        (STATIC_DIR / "styles.css").read_text(encoding="utf-8"),
    )


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
    index_html, app_js, _styles_css = read_static_texts()

    for label in ("Mode", "Backend", "Timeout", "Safety"):
        assert f">{label}<" not in index_html
        assert f">{label}\n" not in index_html

    assert 'id="resource"' in index_html
    assert 'id="resource" value=' not in index_html
    assert 'id="resource" value="USB0::SIM::E36312A::INSTR"' not in index_html
    assert 'id="resource-select"' in index_html
    assert 'id="scan"' in index_html
    assert 'id="server-state"' in index_html
    assert 'id="device-state"' in index_html
    assert 'id="live-state"' in index_html
    assert 'id="health"' not in index_html
    assert '<span id="health">checking</span>' not in index_html

    assert 'resource: valueOrNull("resource")' in app_js
    assert 'resource: document.getElementById("resource").value' not in app_js
    assert "simulate: false" in app_js
    assert "dry_run: false" in app_js
    assert "timeout_ms: 5000" in app_js
    assert "backend: null" in app_js
    assert "safety_config: null" in app_js


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

    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson(`/api/live/${state.liveJobId}/stop`, { method: "POST" })' in app_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in app_js
    assert "job.runtime.resource" in app_js
    assert "runtime.simulate === false" in app_js
    assert "runtime.dry_run === false" in app_js
    assert "!state.liveEvents" in app_js


def test_static_live_data_uses_three_channel_panel_contract():
    index_html, app_js, _styles_css = read_static_texts()

    assert 'id="live-cards"' in index_html
    for channel in ("1", "2", "3"):
        assert f'data-channel-card="{channel}"' in index_html
    assert 'id="live-table"' not in index_html

    start_live = app_js[app_js.index("async function startLive()"):app_js.index("async function stopLive()")]
    assert 'parameters: { interval_ms: 15000 }' in start_live
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
    index_html, _app_js, _styles_css = read_static_texts()

    assert 'class="live-data-section"' in index_html
    assert 'id="live-start"' in index_html


def test_static_layout_exposes_stable_structural_hooks():
    index_html, _app_js, _styles_css = read_static_texts()
    assert 'class="command-workbench"' in index_html
    assert 'id="command-categories"' in index_html
    assert 'id="command-list"' in index_html
    assert 'class="command-main"' in index_html
    assert 'class="workspace"' in index_html
    assert 'class="rail"' in index_html
    assert 'id="job-result-panel"' in index_html
    assert 'id="job-history"' in index_html
    assert 'id="result-panel" class="result-panel collapsed"' in index_html
    assert 'id="command-form"' in index_html
    assert 'id="workspace-summary-content"' in index_html
    assert 'class="rightbar"' not in index_html


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
    assert "Segment complete pulse" in app_js
    assert "Every-step pulse" in app_js
    assert "Trigger pulse when finished" in app_js
    assert '"trigger-pulse": [channel()' in app_js
    assert 'const REAR_PIN_OPTIONS = ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"];' in app_js
    assert 'option.textContent = definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value);' in app_js
    assert 'definition.name === "timing" && value === "step" && stepPulseBlocked' not in app_js
    assert "Use the built-in Segment complete pulse instead" not in app_js
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
    assert "resourceModels: {}" in app_js
    assert "state.commandSupportByModel = payload.command_support_by_model || {};" in app_js
    assert "updateResourceModels(resources);" in app_js
    assert "resource.idn?.model" in app_js
    assert "state.commandSupportByModel?.[model]?.[name]" in app_js
    assert 'if (!resource || typeof model !== "string" || !model.trim()) return false;' in app_js
    assert "!next.stale && updateResourceModel(next.resource, next.model)" in app_js
    assert "support.real !== false" in app_js
    assert "button.disabled = Boolean(effectiveMeta.disabled);" in app_js
    assert "runButton.disabled = Boolean(meta.disabled || tripGuard || ratingGuard);" in app_js
    assert 'error: "Command unavailable"' in app_js


def test_static_trip_guard_and_clear_protection_recovery_contract():
    _index_html, app_js, _styles_css = read_static_texts()

    clear_block = extract_param_block(app_js, "clear-protection")
    assert_param_contract(clear_block, "channel", "select", ["", "all", "1", "2", "3"])
    assert 'value: ""' in clear_block
    assert 'const TRIP_GUARDED_COMMANDS = new Set(["output-on", "cycle-output", "ramp", "ramp-list", "smoke-output", "apply"]);' in app_js
    assert 'if (command === "apply" && parameters.no_output === true) return "";' in app_js
    assert "if (!panel || panel.stale || !resource || panel.resource !== resource) return [];" in app_js
    assert 'selectCommand("clear-protection");' in app_js
    assert 'data-clear-protection-channel="${channel.channel}"' in app_js
    assert 'input.value = channels.length === 1 ? String(channels[0]) : "";' in app_js
    assert 'const stateText = tripped === true ? "TRIP" : tripped === false ? "CLEAR" : "--";' in app_js


def test_static_channel_confirmation_and_job_detail_contracts():
    _index_html, app_js, _styles_css = read_static_texts()

    assert 'set: baseOutputParams()' in app_js
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
    assert_param_contract(app_js, "source", "select", ["bus", "immediate", "pin1", "pin2", "pin3", "ext"])
    assert_param_contract(app_js, "wait_timeout_ms", "number")
    assert_param_contract(app_js, "leave_trigger_configured", "checkbox")


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
    assert "command_support_by_model" in data
    assert data["electrical_ratings_by_model"]["E36312A"]["channels"][0] == {
        "channel": 1,
        "max_voltage": 6.0,
        "max_current": 5.0,
    }
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
    assert cmds["smoke-output"]["description"] == "Run guarded output diagnostic"
    assert cmds["safe-off"]["description"] == "Safely disable output"
    assert cmds["identify"]["category"] == "discovery"
    assert cmds["identify"]["description"] == "Read instrument identification information"
    assert not (WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS & set(cmds))
    assert cmds["error"]["description"] == "Read and remove entries from the instrument error queue"
    assert cmds["clear-protection"]["category"] == "protection"
    assert cmds["clear-protection"]["requires_confirm"] is True
    assert "does not clear OVP/OCP protection latches" in cmds["clear"]["description"]
    assert cmds["trigger-pulse"]["description"] == "Configure rear trigger output pins and emit a BUS trigger pulse"
    assert cmds["trigger-status"]["description"] == "Read digital pin, trigger source, STEP, and LIST state"
    assert cmds["trigger-step"]["description"] == "Configure a STEP transient trigger and optionally fire it"
    assert cmds["trigger-list"]["description"] == "Configure a LIST transient waveform and optionally fire it"
    assert cmds["trigger-fire"]["description"] == "Send *TRG to an already armed BUS trigger"
    assert cmds["trigger-abort"]["description"] == "Abort trigger or LIST execution for selected channels"
    assert cmds["sequence"]["max_steps"] == 250
    
    # Check output-affecting commands are marked correctly
    assert cmds["output-on"]["requires_confirm"] is True
    assert cmds["output-off"]["requires_confirm"] is True
    assert cmds["smoke-output"]["requires_confirm"] is True
    assert "smoke-output" in data["output_affecting_commands"]
    assert "ramp-list" in data["output_affecting_commands"]


def test_api_rejects_invalid_static_parameter_before_creating_job(client: TestClient):
    from keysight_power_webui.jobs import job_manager

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


def test_commands_metadata_includes_model_aware_support(client: TestClient):
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    support = data["command_support_by_model"]

    assert set(support) == {"E36312A", "EDU36311A", "GENERIC"}
    assert support["E36312A"]["trigger-list"]["real"] is True
    assert support["EDU36311A"]["trigger-list"]["real"] is False
    assert support["EDU36311A"]["trigger-list"]["hardware_validation"] == "not_supported_by_model"
    assert support["GENERIC"]["set"]["real"] is False
    for model in ("E36312A", "EDU36311A", "GENERIC"):
        assert support[model]["clear"]["real"] is True
        assert support[model]["error"]["real"] is True
        assert "verify" not in support[model]
        assert "readback" not in support[model]
        assert "safety inspect" not in support[model]


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
    for model_support in data["command_support_by_model"].values():
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
                "leave_trigger_configured": False,
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


def test_ramp_list_lint_dry_run(client: TestClient):
    payload = {
        "command": "ramp-list",
        "runtime": {"simulate": True, "dry_run": True},
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
    from keysight_power_webui.jobs import job_manager

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
    assert sample["channels"][0]["over_voltage_tripped"] is False
    assert sample["channels"][0]["over_current_tripped"] is False
    assert sample["channels"][0]["protection_tripped"] is False
    assert sample["channels"][0]["over_voltage_protection_level"] == 5.0
    assert sample["channels"][0]["over_current_protection_enabled"] is True
    assert sample["channels"][1]["set_voltage"] == 0.0
    assert sample["channels"][1]["over_current_protection_enabled"] is False
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
    assert [channel["protection_tripped"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["over_voltage_protection_level"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["over_current_protection_enabled"] for channel in sample["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


def test_live_data_panel_sample_normalizes_numeric_values():
    from keysight_power_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "idn": {"model": "E36312A"},
            "outputs": [{"channel": 1, "enabled": True}],
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
                    "over_voltage_tripped": "0",
                    "over_current_tripped": "1",
                    "over_voltage_protection_level": "5.5",
                    "over_current_protection_enabled": "on",
                },
                {
                    "channel": 2,
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
    assert [channel["protection_tripped"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["over_voltage_protection_level"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["over_current_protection_enabled"] for channel in event["data"]["channels"]] == [None, None, None]

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


def test_webui_capabilities_uses_selected_resource_model(client: TestClient):
    payload = {
        "command": "capabilities",
        "runtime": {
            "simulate": True,
            "resource": "USB0::SIM::EDU36311A::INSTR",
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
    assert job_data["status"] == "finished", job_data.get("error")
    result = job_data["result"]
    assert result["resource"]["idn"]["model"] == "EDU36311A"
    assert result["driver"]["class"] == "EDU36311APowerSupply"
    assert result["command_support"]["trigger-list"]["real"] is False
    assert result["command_support"]["protection-set"]["real"] is True


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

    from keysight_power_webui.jobs import JobManager, JobStatus

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
    assert 'previewPlanBtn.textContent = "Preview restore plan";' in render_restore
    assert 'previewPlanBtn.disabled = !isLoadedRestoreSnapshotValid() || state.restorePlanPreviewStatus === "running";' in render_restore
    assert "Loaded snapshot JSON" not in render_restore
    assert "Snapshot JSON Preview" not in render_restore
    assert "restore-preview" not in render_restore
    assert 'command: "restore-from-snapshot"' in preview_restore
    assert "dry_run: true" in preview_restore
    assert "confirm: true" in preview_restore
    assert "parameters: restoreSnapshotParameters(state.loadedSnapshotDocument)" in preview_restore
    assert 'addHistory(response.job_id, "restore-from-snapshot", "accepted", "Restore plan preview");' in preview_restore
    assert "subscribeToJob(response.job_id, \"/api/events\");" in preview_restore
    assert 'jobLabel(jobId) === "Restore plan preview"' in handle_job_event
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

    assert "instrument error queue" in app_js
    assert "removed from the instrument queue" in app_js
    assert "appendFieldDescription(label, param);" in render_snapshot
    assert 'description.className = "field-description";' in append_description
    assert "description.textContent = param.description;" in append_description


def test_static_safe_off_channel_documents_behavior():
    _index_html, app_js, _styles_css = read_static_texts()

    assert "every available output when set to all" in app_js
    assert "reads back each output state" in app_js
    assert "setpoints and protection settings are not changed" in app_js


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
    from keysight_power_webui.jobs import job_manager

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
