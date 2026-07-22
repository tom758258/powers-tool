"""Static shell, resource, live-panel, and basic-control WebUI tests."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from _webui_shared import (
    assert_static_attr,
    assert_static_id,
    extract_js_function,
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
    static_tag_with_id,
)

def test_guard_no_cli_import():
    package_root = Path(__file__).parents[2] / "src" / "powers_tool_webui"
    for source_path in package_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert not any(name == "powers_tool_cli" or name.startswith("powers_tool_cli.") for name in imported)


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
    assert 'name="execution-mode" value="simulate"' in html
    assert 'name="execution-mode" value="dry-run"' in html
    assert 'class="device-resource-title-row"' in html
    assert 'id="execution-mode-badge" class="execution-mode-badge real-locked" aria-live="polite">Real · Writes locked</span>' in html
    badge_tag = static_tag_with_id(html, "execution-mode-badge")
    assert badge_tag.startswith("<span ")
    assert "onclick" not in badge_tag
    assert 'getElementById("execution-mode-badge").addEventListener' not in app_js
    title_row = html[html.index('class="device-resource-title-row"'):html.index('</div>', html.index('class="device-resource-title-row"'))]
    title_end = title_row.index("</strong>")
    badge_start = title_row.index('id="execution-mode-badge"')
    assert 'id="device-resource-title"' in title_row
    assert title_end < badge_start
    assert 'id="real-write-enabled"' in html
    assert "Simulate" in html
    execution_mode_ui = extract_js_function(app_js, "updateExecutionModeUi")
    for text in ("Real · Writes locked", "Real · Writes enabled", "Simulate", "Dry-run"):
        assert text in execution_mode_ui
    for class_name in ("real-locked", "real-enabled", "simulate", "dry-run"):
        assert f'badge.classList.add("{class_name}")' in execution_mode_ui
    assert ".device-resource-title-row" in styles_css
    assert "flex-wrap: wrap;" in styles_css
    assert "white-space: nowrap;" in styles_css
    assert ".execution-mode-badge.real-locked" in styles_css
    assert ".execution-mode-badge.real-enabled" in styles_css
    locked_style = styles_css[styles_css.index(".execution-mode-badge.real-locked"):styles_css.index(".execution-mode-badge.simulate")]
    assert "var(--warning)" not in locked_style

    runtime_block = extract_js_function(app_js, "runtimePayload")
    assert 'const expectedModelId = valueOrNull("expected-model-id");' in runtime_block
    assert "if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;" in runtime_block
    assert "serialOptionsPayload()" in runtime_block
    assert "runtime.serial_options = serialOptions" in runtime_block
    assert "runtime.serial_remote = true" in runtime_block
    assert "runtime.serial_local_on_close = true" in runtime_block
    assert ".serial-grid" in styles_css


def test_static_command_forms_do_not_repeat_real_write_authorization_warning() -> None:
    index_html, app_js, styles_css = read_static_texts()
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")
    runtime_block = extract_js_function(app_js, "runtimePayload")
    submit_selected = extract_js_function(app_js, "runSelected")
    submit_basic = extract_js_function(app_js, "submitBasicJob")

    assert "confirm-banner" not in index_html
    assert "confirm-banner" not in app_js
    assert "confirm-banner" not in styles_css
    assert "Enable real hardware writes in Device options before running this command." not in app_js
    assert "webuiCommandForm.renderCommandGuidance(state.selected, parameters, triggerControlGuardReason, triggerFireWaitGuardReason);" in update_selected
    assert "meta.live_support_status" in update_selected
    assert "confirm: hasRealWriteAuthorization()" in runtime_block
    assert 'meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm' in submit_selected
    assert 'meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm' in submit_basic
    for function_name in (
        "clearRealWriteAuthorization",
        "handleExpectedModelChanged",
        "handleExecutionModeChange",
        "syncSelectedResource",
        "updateResourceModel",
    ):
        assert "clearRealWriteAuthorization()" in extract_js_function(app_js, function_name)


def test_static_normal_model_dropdown_policy() -> None:
    html, app_js, _styles_css = read_static_texts()
    model_select = html[html.index('id="expected-model-id"'):html.index("</select>", html.index('id="expected-model-id"'))]

    assert '<option value="">Auto-detect</option>' in model_select
    assert 'option value="keysight-' not in model_select
    renderer = extract_js_function(app_js, "populateIdentitySelector")
    assert "state.physicalModels.forEach" in renderer
    assert "model.model_id" in renderer
    for unvalidated_model in ("E36103B", "E36232A"):
        assert unvalidated_model not in model_select
    assert "Auto-detect uses the connected instrument IDN" in html


def test_static_device_resource_summary_uses_model_wording():
    _html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    summary = extract_js_function(app_js, "updateDeviceResourceSummary")
    builder = extract_js_function(app_js, "buildDeviceResourceSummary")

    assert "Manual" not in summary
    assert "buildDeviceResourceSummary(resource, select)" in summary
    assert "Real mode" in builder
    assert "Simulate mode" in builder
    assert "Dry-run mode" in builder
    assert "Expected Model guard" in builder
    assert "preserved, not used" in builder
    assert "actualCurrentResourceModel()" in builder
    assert "exactSupportContextSummary(resource)" in builder
    assert "resourceDisplayModels: {}" in state_js
    assert "state.resourceDisplayModels[resource] = detectedModel;" in app_js


def test_frontend_planning_identity_state_is_page_local_and_mode_isolated() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeContainer {
          constructor() {
            this.children = [];
            this.label = "";
          }
          append(...children) { this.children.push(...children); }
        }

        class FakeSelect extends FakeContainer {
          constructor() {
            super();
            this.value = "";
            this.options = [];
          }
          replaceChildren() {
            this.children = [];
            this.options = [];
            this.value = "";
          }
          add(option) {
            this.children.push(option);
            this.options.push(option);
          }
          append(...children) {
            super.append(...children);
            children.forEach((child) => this.options.push(...(child.children || [])));
          }
        }

        globalThis.Option = function Option(text, value) {
          return { textContent: text, value: String(value), disabled: false };
        };
        const select = new FakeSelect();
        document.createElement = (tagName) => tagName === "optgroup" ? new FakeContainer() : {};
        document.getElementById = (id) => id === "expected-model-id" ? select : null;

        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-e3646a", display_name: "Keysight E3646A" }
        ];
        state.planningProfiles = {
          "generic-scpi": { profile_id: "generic-scpi", display_name: "Generic SCPI" }
        };
        state.realIdentityCache.expectedModelId = "";
        state.planningIdentityCache = { simulate: "", "dry-run": "" };

        state.executionMode = "simulate";
        populateIdentitySelector();
        strictAssert.equal(select.value, "", "first Simulate entry must be blank");
        select.value = "keysight-e36312a";
        rememberCurrentExecutionIdentity();

        state.executionMode = "dry-run";
        populateIdentitySelector();
        strictAssert.equal(select.value, "", "first Dry-run entry must be blank");
        select.value = "profile:generic-scpi";
        rememberCurrentExecutionIdentity();

        state.executionMode = "simulate";
        populateIdentitySelector();
        strictAssert.equal(select.value, "keysight-e36312a");

        state.executionMode = "dry-run";
        populateIdentitySelector();
        strictAssert.equal(select.value, "profile:generic-scpi");

        state.executionMode = "real";
        populateIdentitySelector();
        strictAssert.equal(select.value, "", "Dry-run identity must not become Expected Model");
        select.value = "keysight-e3646a";
        rememberCurrentExecutionIdentity();

        state.executionMode = "simulate";
        populateIdentitySelector();
        strictAssert.equal(select.value, "keysight-e36312a", "Real guard must not replace Simulate identity");
        """
    )
    run_frontend_javascript_assertions(assertions)

    _html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    assert 'planningIdentityCache: { simulate: "", "dry-run": "" }' in state_js
    assert "localStorage" not in app_js
    assert "sessionStorage" not in app_js
    assert "rememberCurrentExecutionIdentity();" in extract_js_function(app_js, "handleExecutionModeChange")
    assert "rememberCurrentExecutionIdentity();" in extract_js_function(app_js, "handleExpectedModelChanged")


def test_frontend_planning_electrical_constraints_restore_base_values() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeInput {
          constructor() {
            this.type = "number";
            this.dataset = {};
            this.attributes = {};
            for (const name of ["min", "max", "step", "title"]) {
              Object.defineProperty(this, name, {
                get: () => this.attributes[name] ?? "",
                set: (value) => { this.attributes[name] = String(value); }
              });
            }
          }
          setAttribute(name, value) { this.attributes[name] = String(value); }
          getAttribute(name) { return this.attributes[name] ?? null; }
          hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
          removeAttribute(name) { delete this.attributes[name]; }
        }

        const identity = { value: "keysight-e36312a" };
        const channel = { value: "1" };
        document.getElementById = (id) => ({
          "expected-model-id": identity,
          "param-channel": channel
        })[id] || null;

        state.executionMode = "simulate";
        state.parameterConstraints = {
          voltage: { min: 0, max: 100, step: 0.1, description: "Generic voltage guidance" }
        };
        state.electricalRatingsByModel = {
          "keysight-e36312a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }] },
          "keysight-e3646a": { channels: [{ channel: 1, max_voltage: 20, max_current: 1 }] }
        };

        const input = new FakeInput();
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.min, "0");
        strictAssert.equal(input.max, "6");
        strictAssert.equal(input.step, "0.1");
        strictAssert.match(input.title, /maximum 6 V/);

        input.min = "1";
        input.step = "2";
        identity.value = "profile:generic-scpi";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(selectedElectricalRatingModel(), null);
        strictAssert.equal(input.min, "0");
        strictAssert.equal(input.max, "100");
        strictAssert.equal(input.step, "0.1");
        strictAssert.equal(input.title, "Generic voltage guidance");
        strictAssert.equal(input.dataset.electricalBaseConstraints, undefined);

        identity.value = "keysight-e3646a";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.max, "20");
        strictAssert.match(input.title, /maximum 20 V/);

        identity.value = "";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.min, "0");
        strictAssert.equal(input.max, "100");
        strictAssert.equal(input.step, "0.1");
        strictAssert.equal(input.title, "Generic voltage guidance");
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_device_resource_summary_is_mode_and_identity_aware() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = new Map([
          ["resource", { value: "USB0::KEPT::INSTR" }],
          ["resource-select", { value: "USB0::KEPT::INSTR", options: [{ textContent: "USB0::KEPT::INSTR" }] }],
          ["expected-model-id", { value: "keysight-e36312a" }],
          ["device-resource-summary", { textContent: "", title: "" }]
        ]);
        document.getElementById = (id) => elements.get(id) || null;

        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-edu36311a", display_name: "Keysight EDU36311A" }
        ];
        state.planningProfiles = {
          "generic-scpi": { profile_id: "generic-scpi", display_name: "Generic SCPI" }
        };
        state.resourceModels = { "USB0::KEPT::INSTR": "keysight-edu36311a" };
        state.resourceChannelModels = { "USB0::KEPT::INSTR": "keysight-edu36311a" };
        state.resourceDisplayModels = { "USB0::KEPT::INSTR": "EDU36311A" };
        state.resourceLiveSupport = {
          evaluated: true,
          model_id: "keysight-edu36311a",
          transport_scope: "usb",
          backend_scope: "system_visa",
          commands: {
            set: { product_open: true, policy_exempt: false },
            ramp: { product_open: false, policy_exempt: false, exact_scope_validation_status: "feature_pending" }
          }
        };
        state.resourceLiveSupportContext = {
          resource: "USB0::KEPT::INSTR",
          model_id: "keysight-edu36311a"
        };

        state.executionMode = "real";
        updateDeviceResourceSummary();
        const summary = elements.get("device-resource-summary");
        strictAssert.match(summary.textContent, /Real mode/);
        strictAssert.match(summary.textContent, /VISA resource: USB0::KEPT::INSTR/);
        strictAssert.match(summary.textContent, /Detected model: Keysight EDU36311A/);
        strictAssert.match(summary.textContent, /Expected Model guard: Require Keysight E36312A/);
        strictAssert.match(summary.textContent, /1 validated, 1 pending/);
        strictAssert.match(summary.title, /does not match/);

        state.executionMode = "simulate";
        elements.get("expected-model-id").value = "keysight-e36312a";
        updateDeviceResourceSummary();
        strictAssert.match(summary.textContent, /Simulate mode/);
        strictAssert.match(summary.textContent, /Planning model: Keysight E36312A/);
        strictAssert.match(summary.textContent, /Real VISA resource preserved, not used: USB0::KEPT::INSTR/);
        strictAssert.equal(summary.textContent.includes("Expected Model guard"), false);

        state.executionMode = "dry-run";
        elements.get("expected-model-id").value = "profile:generic-scpi";
        updateDeviceResourceSummary();
        strictAssert.match(summary.textContent, /Dry-run mode/);
        strictAssert.match(summary.textContent, /Planning profile: Generic SCPI/);
        strictAssert.match(summary.textContent, /preserved, not used/);
        """
    )
    run_frontend_javascript_assertions(assertions)


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
    assert 'valueOrNull("expected-model-id")' in selected_expected
    assert "physicalModelDisplayName(expected)" in selected_expected_label
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
    state_js = read_static_javascript("state.js")
    load_commands = extract_js_function(app_js, "loadCommands")

    assert "setpointRangesByModel: {}" in state_js
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
    assert '<span data-i18n="app.unofficial_tool">Unofficial Tool</span> v__WEBUI_VERSION__' in index_html
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

    assert "webuiApi.fetchJson(\"/api/live\"" not in refresh_preview
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
    live_data_js = read_static_javascript("live-data.js")
    refresh_health = extract_js_function(app_js, "refreshHealth")
    preview = extract_js_function(live_data_js, "startLivePreviewSnapshot")
    stop_live = extract_js_function(live_data_js, "stopLive")
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
    live_data_js = read_static_javascript("live-data.js")

    assert 'command: "list-resources"' in app_js
    assert "parameters: { live_only: true }" in app_js
    assert 'webuiApi.fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in live_data_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in live_data_js
    assert 'selectCommand("list-resources")' not in app_js
    assert 'const liveOnly = document.getElementById("param-live_only")' not in app_js
    assert 'document.getElementById("param-live_only").checked = true' not in app_js


def test_static_finished_real_command_refreshes_live_snapshot():
    _index_html, app_js, _styles_css = read_static_texts()
    jobs_js = read_static_javascript("jobs.js")
    live_data_js = read_static_javascript("live-data.js")
    refresh = extract_js_function(app_js, "shouldRefreshLiveAfterCommand")
    preview = extract_js_function(live_data_js, "startLivePreviewSnapshot")
    fresh_preview = extract_js_function(live_data_js, "isFreshLivePreviewSample")

    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in live_data_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in live_data_js
    assert "job.runtime.resource" in jobs_js
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
    live_data_js = read_static_javascript("live-data.js")

    assert 'id="live-cards"' in index_html
    for channel in ("1", "2", "3"):
        assert f'data-channel-card="{channel}"' in index_html
    assert 'id="live-table"' not in index_html

    start_live = extract_js_function(live_data_js, "startLive")
    stop_live = extract_js_function(live_data_js, "stopLive")
    wait_for_terminal = extract_js_function(live_data_js, "waitForLiveTerminal")
    assert 'parameters: { interval_ms: 5000 }' in start_live
    assert 'class="live-data-note"' in index_html
    assert "Live Data monitor" in index_html
    assert "5 seconds" in index_html
    assert "Successful real hardware commands" in index_html
    assert 'read_command: "measure-all"' not in start_live
    assert 'channel: "all"' not in start_live
    assert 'if (!payload.runtime.resource)' in start_live
    assert 'simulate: true' not in start_live
    assert 'fetchJson("/api/live", { method: "POST"' in start_live
    for event_type in ("progress", "finished", "failed"):
        assert f'addEventListener("{event_type}"' in start_live
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in stop_live
    assert "await waitForLiveTerminal(jobId);" in stop_live
    assert "Date.now() + 15000" in wait_for_terminal
    assert 'fetchJson(`/api/jobs/${jobId}`)' in wait_for_terminal
    assert 'document.getElementById("live-start").addEventListener("click", toggleLiveMonitor);' in app_js
    assert "webuiLiveData.createLiveDataController({" in app_js
    assert "var { startLive, toggleLiveMonitor, stopLive, startLivePreviewSnapshot, isFreshLivePreviewSample, waitForLiveTerminal } = liveDataController;" in app_js
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
    index_html, _app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")
    output_button = extract_js_function(basic_controls_js, "renderBasicOutputButton")
    all_button = extract_js_function(basic_controls_js, "renderBasicAllOutputButton")

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
    basic_controls_js = read_static_javascript("basic-controls.js")
    set_action = extract_js_function(basic_controls_js, "setBasicActionState")
    run_output = extract_js_function(app_js, "runBasicOutput")
    run_all = extract_js_function(app_js, "runBasicOutputAll")
    update_basic = extract_js_function(basic_controls_js, "updateBasicActionFromJob")
    render_states = extract_js_function(basic_controls_js, "renderBasicOutputActionStates")
    render_control = extract_js_function(basic_controls_js, "renderBasicOutputControlState")
    lock_action = extract_js_function(basic_controls_js, "basicOutputLockAction")
    clear_resolved = extract_js_function(basic_controls_js, "clearResolvedBasicErrors")
    render_channel = extract_js_function(basic_controls_js, "renderBasicChannelActionState")

    assert 'state.basicActionStates[actionKey] = { ...context, status, message };' in set_action
    assert 'state.basicActionStates[actionKey] = { status, message, ...context };' not in set_action
    assert 'if (basicOutputLockAction(channel)) return;' in run_output
    assert 'if (basicOutputLockAction("all")) return;' in run_all
    assert 'awaitingReadback: true' in update_basic
    assert 'setBasicActionState(action.actionKey, "pending"' in update_basic
    assert 'button.disabled = Boolean(unsupported || lockAction || commandMetaForState.disabled);' in render_control
    assert 'button.classList.toggle("basic-action-pending", Boolean(lockAction));' in render_control
    assert 'defaultChannels.forEach((channel) => renderBasicOutputControlState(channel));' in render_states
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

