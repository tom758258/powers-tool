"""Static output-control, command-panel, and result-panel WebUI tests."""

from __future__ import annotations

import textwrap

from _webui_shared import (
    assert_static_id,
    extract_js_function,
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
)

def test_static_e3646a_basic_global_output_dom_and_accessibility_contract():
    index_html, app_js, styles_css = read_static_texts()

    assert app_js.count('const E3646A_MODEL_ID = "keysight-e3646a";') == 1
    assert index_html.count('id="basic-output-all"') == 1
    assert index_html.count("data-basic-all-output") == 1
    assert_static_id(index_html, "basic-output-all-header-slot")
    assert_static_id(index_html, "basic-output-all-global-slot")
    assert_static_id(index_html, "basic-e3646a-output-row")
    assert_static_id(index_html, "basic-output-capability-status")
    assert_static_id(index_html, "e3646a-global-output-description")

    explanation = (
        "E3646A uses global output control. Enabling or disabling output switches "
        "CH1 and CH2 together; voltage and current setpoints remain independently adjustable."
    )
    assert index_html.count(explanation) == 3
    for channel in ("1", "2"):
        assert f'<span class="basic-output-status unknown" data-basic-output-status="{channel}" role="status" hidden>UNKNOWN</span>' in index_html
        assert f'data-basic-output-info="{channel}" role="note" tabindex="0"' in index_html
    assert "data-basic-output-status" in index_html
    assert "data-basic-output-status=\"1\" aria-pressed" not in index_html
    assert "data-basic-output-status=\"2\" aria-pressed" not in index_html
    assert ".basic-toggle[hidden]" in styles_css
    assert ".basic-output-status[hidden]" in styles_css
    assert ".basic-output-info[hidden]" in styles_css
    assert ".basic-e3646a-output-row[hidden]" in styles_css
    assert 'document.querySelector("[data-basic-all-output]").addEventListener("click", runBasicOutputAll);' in app_js


def test_frontend_e3646a_identity_and_capability_gate_uses_actual_resource():
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = new Map([
          ["resource", { value: "RESOURCE-A" }],
          ["expected-model-id", { value: "keysight-e3646a" }]
        ]);
        document.getElementById = (id) => elements.get(id) || null;

        state.commandSupportByModel = {
          "keysight-e36312a": {},
          "keysight-e3646a": {},
          "keysight-edu36311a": {}
        };
        state.channelCapabilitiesByModel = {
          "keysight-e36312a": { channels: [1, 2, 3], output_control_scope: "per_channel" },
          "keysight-e3646a": { channels: [1, 2], output_control_scope: "global" },
          "keysight-edu36311a": { channels: [1, 2, 3], output_control_scope: "per_channel" }
        };
        state.resourceModels = {};
        state.resourceChannelModels = {};
        state.resourceDisplayModels = { "RESOURCE-A": "E3646A" };
        state.resourceLiveSupport = null;
        state.resourceLiveSupportContext = null;
        state.livePanel = {
          resource: "RESOURCE-A",
          stale: false,
          model: "E3646A",
          model_id: null,
          channels: []
        };

        strictAssert.equal(actualCurrentResourceModel(), null);
        strictAssert.equal(basicOutputPresentation().mode, "ordinary");

        state.resourceModels["RESOURCE-A"] = "keysight-e36312a";
        state.resourceChannelModels["RESOURCE-A"] = "keysight-e36312a";
        strictAssert.equal(basicOutputPresentation().mode, "ordinary");

        elements.get("expected-model-id").value = "";
        state.resourceModels["RESOURCE-A"] = "keysight-e3646a";
        state.resourceChannelModels["RESOURCE-A"] = "keysight-e3646a";
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-global");
        strictAssert.deepEqual(basicOutputPresentation().capability.channels, [1, 2]);

        delete state.channelCapabilitiesByModel["keysight-e3646a"];
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-disabled");
        state.channelCapabilitiesByModel["keysight-e3646a"] = {
          channels: [1, 2],
          output_control_scope: "per_channel"
        };
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-disabled");
        state.channelCapabilitiesByModel["keysight-e3646a"] = {
          channels: [1, 2, 3],
          output_control_scope: "global"
        };
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-disabled");
        state.channelCapabilitiesByModel["keysight-e3646a"] = {
          channels: [1, 2],
          output_control_scope: "global"
        };

        state.livePanel.model_id = "keysight-edu36311a";
        strictAssert.equal(actualCurrentResourceModel(), "keysight-edu36311a");
        strictAssert.equal(basicOutputPresentation().mode, "ordinary");
        state.livePanel.stale = true;
        state.livePanel.model_id = "keysight-e3646a";
        state.resourceModels = {};
        state.resourceChannelModels = {};
        strictAssert.equal(actualCurrentResourceModel(), null);

        state.livePanel = null;
        state.resourceLiveSupport = { evaluated: true, model_id: "keysight-e3646a" };
        state.resourceLiveSupportContext = { resource: "RESOURCE-A", model_id: "keysight-e3646a" };
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-global");

        elements.get("resource").value = "RESOURCE-B";
        state.resourceModels["RESOURCE-B"] = "keysight-e36312a";
        state.resourceChannelModels["RESOURCE-B"] = "keysight-e36312a";
        strictAssert.equal(basicOutputPresentation().mode, "ordinary");
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_e3646a_basic_output_presentation_and_tri_state_readback():
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeElement {
          constructor(tagName = "div") {
            this.tagName = tagName.toUpperCase();
            this.children = [];
            this.parentNode = null;
            this.attributes = {};
            this.listeners = {};
            this.className = "";
            this.hidden = false;
            this.disabled = false;
            this.textContent = "";
            this.title = "";
            this.classList = {
              add: (...names) => this.updateClasses((values) => names.forEach((name) => values.add(name))),
              remove: (...names) => this.updateClasses((values) => names.forEach((name) => values.delete(name))),
              toggle: (name, force) => {
                let result = false;
                this.updateClasses((values) => {
                  result = force === undefined ? !values.has(name) : Boolean(force);
                  if (result) values.add(name); else values.delete(name);
                });
                return result;
              },
              contains: (name) => this.className.split(/\s+/).filter(Boolean).includes(name)
            };
          }

          updateClasses(update) {
            const values = new Set(this.className.split(/\s+/).filter(Boolean));
            update(values);
            this.className = [...values].join(" ");
          }

          appendChild(child) {
            if (child.parentNode) {
              child.parentNode.children = child.parentNode.children.filter((item) => item !== child);
            }
            child.parentNode = this;
            this.children.push(child);
            return child;
          }

          addEventListener(type, listener) {
            (this.listeners[type] ||= []).push(listener);
          }

          setAttribute(name, value) {
            this.attributes[name] = String(value);
          }

          getAttribute(name) {
            return this.attributes[name] ?? null;
          }
        }

        const resource = { value: "RESOURCE-E3646A" };
        const expected = { value: "" };
        const headerSlot = new FakeElement("span");
        const globalSlot = new FakeElement("span");
        const globalRow = new FakeElement("div");
        const capabilityStatus = new FakeElement("div");
        const allButton = new FakeElement("button");
        allButton.className = "basic-toggle off";
        allButton.addEventListener("click", runBasicOutputAll);
        headerSlot.appendChild(allButton);
        const outputButtons = Object.fromEntries([1, 2, 3].map((channel) => {
          const button = new FakeElement("button");
          button.className = "basic-toggle off";
          return [channel, button];
        }));
        const outputStatuses = Object.fromEntries([1, 2].map((channel) => {
          const status = new FakeElement("span");
          status.className = "basic-output-status unknown";
          status.hidden = true;
          return [channel, status];
        }));
        const outputInfo = Object.fromEntries([1, 2].map((channel) => {
          const info = new FakeElement("span");
          info.hidden = true;
          return [channel, info];
        }));
        const setpointControls = [new FakeElement("input"), new FakeElement("input"), new FakeElement("button")];

        const ids = new Map([
          ["resource", resource],
          ["expected-model-id", expected],
          ["basic-output-all-header-slot", headerSlot],
          ["basic-output-all-global-slot", globalSlot],
          ["basic-e3646a-output-row", globalRow],
          ["basic-output-capability-status", capabilityStatus]
        ]);
        document.getElementById = (id) => ids.get(id) || null;
        document.querySelector = (selector) => {
          if (selector === "[data-basic-all-output]") return allButton;
          let match = selector.match(/^\[data-basic-output="(\d)"\]$/);
          if (match) return outputButtons[Number(match[1])];
          match = selector.match(/^\[data-basic-output-status="(\d)"\]$/);
          if (match) return outputStatuses[Number(match[1])] || null;
          match = selector.match(/^\[data-basic-output-info="(\d)"\]$/);
          if (match) return outputInfo[Number(match[1])] || null;
          return null;
        };

        state.commands = { "output-on": {}, "output-off": {} };
        state.commandSupportByModel = {
          "keysight-e36312a": { "output-on": { real: true }, "output-off": { real: true } },
          "keysight-e3646a": { "output-on": { real: true }, "output-off": { real: true } }
        };
        state.liveSupportByModel = {};
        state.channelCapabilitiesByModel = {
          "keysight-e36312a": { channels: [1, 2, 3], output_control_scope: "per_channel" },
          "keysight-e3646a": { channels: [1, 2], output_control_scope: "global" }
        };
        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-e3646a", display_name: "Keysight E3646A" }
        ];
        state.resourceModels = { "RESOURCE-E3646A": "keysight-e3646a" };
        state.resourceChannelModels = { "RESOURCE-E3646A": "keysight-e3646a" };
        state.resourceLiveSupport = null;
        state.resourceLiveSupportContext = null;
        state.basicActionStates = {};
        state.livePanel = {
          resource: "RESOURCE-E3646A",
          model_id: "keysight-e3646a",
          stale: false,
          channels: [
            { channel: 1, output_enabled: true },
            { channel: 2, output_enabled: true }
          ]
        };

        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputButton(1, state.livePanel.channels[0], true);
        renderBasicOutputButton(2, state.livePanel.channels[1], true);
        renderBasicOutputControlState(1);
        strictAssert.equal(allButton.parentNode, globalSlot);
        strictAssert.equal(globalRow.hidden, false);
        strictAssert.equal(outputButtons[1].hidden, true);
        strictAssert.equal(outputButtons[1].disabled, true);
        strictAssert.equal(outputButtons[2].hidden, true);
        strictAssert.equal(outputStatuses[1].hidden, false);
        strictAssert.equal(outputStatuses[1].textContent, "ON");
        strictAssert.equal(outputStatuses[1].getAttribute("aria-pressed"), null);
        strictAssert.equal(outputStatuses[2].textContent, "ON");
        strictAssert.equal(outputInfo[1].hidden, false);
        strictAssert.equal(outputInfo[1].title, E3646A_GLOBAL_OUTPUT_DESCRIPTION);
        strictAssert.equal(allButton.textContent, "Turn outputs off");
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "true");
        strictAssert.equal(allButton.disabled, false);

        state.livePanel.channels[0].output_enabled = false;
        state.livePanel.channels[1].output_enabled = false;
        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputButton(1, state.livePanel.channels[0], true);
        strictAssert.equal(allButton.textContent, "Turn outputs on");
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "false");
        strictAssert.equal(allButton.disabled, false);
        strictAssert.equal(outputStatuses[1].textContent, "OFF");

        state.livePanel.channels[0].output_enabled = null;
        renderBasicOutputButton(1, state.livePanel.channels[0], true);
        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputControlState("all");
        strictAssert.equal(outputStatuses[1].textContent, "UNKNOWN");
        strictAssert.equal(outputStatuses[1].getAttribute("aria-pressed"), null);
        strictAssert.equal(allButton.textContent, "Output state unknown");
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "mixed");
        strictAssert.equal(allButton.disabled, true);
        state.livePanel.channels[0].output_enabled = true;
        renderBasicAllOutputButton(state.livePanel.channels);
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "mixed");
        strictAssert.equal(allButton.disabled, true);
        state.livePanel.stale = true;
        renderBasicAllOutputButton(state.livePanel.channels);
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "mixed");
        strictAssert.equal(allButton.disabled, true);
        state.livePanel.stale = false;

        let submissions = [];
        submitBasicJob = async (...args) => { submissions.push(args); };
        runBasicOutputAll();
        strictAssert.equal(submissions.length, 0);

        state.livePanel.channels[0].output_enabled = false;
        runBasicOutputAll();
        strictAssert.equal(submissions.length, 1);
        strictAssert.equal(submissions[0][0], "output-on");
        strictAssert.deepEqual(submissions[0][1], { channel: "all" });
        state.livePanel.channels[0].output_enabled = true;
        state.livePanel.channels[1].output_enabled = true;
        runBasicOutputAll();
        strictAssert.equal(submissions.length, 2);
        strictAssert.equal(submissions[1][0], "output-off");
        strictAssert.deepEqual(submissions[1][1], { channel: "all" });

        state.basicActionStates = {
          "output:all": {
            status: "pending",
            awaitingReadback: true,
            desiredOutput: true
          }
        };
        state.livePanel.channels[0].output_enabled = true;
        state.livePanel.channels[1].output_enabled = false;
        clearResolvedBasicErrors(1, state.livePanel.channels[0], true);
        strictAssert.equal(state.basicActionStates["output:all"].status, "pending");
        state.livePanel.channels[1].output_enabled = true;
        clearResolvedBasicErrors(1, state.livePanel.channels[0], true);
        strictAssert.equal(state.basicActionStates["output:all"].status, "success");
        state.basicActionStates = {};

        const originalListener = allButton.listeners.click[0];
        applyBasicOutputPresentation();
        applyBasicOutputPresentation();
        strictAssert.equal(globalSlot.children.filter((node) => node === allButton).length, 1);
        strictAssert.equal(allButton.listeners.click.length, 1);
        strictAssert.equal(allButton.listeners.click[0], originalListener);

        state.channelCapabilitiesByModel["keysight-e3646a"] = {
          channels: [1, 2],
          output_control_scope: "per_channel"
        };
        applyBasicOutputPresentation();
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-disabled");
        strictAssert.equal(allButton.parentNode, headerSlot);
        strictAssert.equal(outputButtons[1].hidden, false);
        strictAssert.equal(outputButtons[1].disabled, true);
        strictAssert.equal(capabilityStatus.textContent, E3646A_CAPABILITY_ERROR);

        delete state.channelCapabilitiesByModel["keysight-e3646a"];
        applyBasicOutputPresentation();
        strictAssert.equal(allButton.parentNode, headerSlot);
        strictAssert.equal(globalRow.hidden, true);
        strictAssert.equal(capabilityStatus.hidden, false);
        strictAssert.equal(capabilityStatus.textContent, E3646A_CAPABILITY_ERROR);
        strictAssert.equal(allButton.disabled, true);
        strictAssert.equal(allButton.title, E3646A_CAPABILITY_ERROR);
        for (const channel of [1, 2, 3]) {
          strictAssert.equal(outputButtons[channel].disabled, true);
          strictAssert.equal(outputButtons[channel].title, E3646A_CAPABILITY_ERROR);
        }
        setpointControls.forEach((control) => strictAssert.equal(control.disabled, false));

        resource.value = "RESOURCE-E36312A";
        state.resourceModels["RESOURCE-E36312A"] = "keysight-e36312a";
        state.resourceChannelModels["RESOURCE-E36312A"] = "keysight-e36312a";
        state.livePanel = {
          resource: "RESOURCE-E36312A",
          model_id: "keysight-e36312a",
          stale: false,
          channels: [
            { channel: 1, output_enabled: false },
            { channel: 2, output_enabled: false },
            { channel: 3, output_enabled: false }
          ]
        };
        for (const channel of [1, 2, 3]) {
          renderBasicOutputButton(channel, state.livePanel.channels[channel - 1], true);
        }
        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputActionStates();
        strictAssert.equal(allButton.parentNode, headerSlot);
        strictAssert.equal(allButton.textContent, "ALL ON");
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "false");
        strictAssert.equal(allButton.disabled, false);
        strictAssert.equal(outputButtons[1].hidden, false);
        strictAssert.equal(outputButtons[1].disabled, false);
        strictAssert.equal(outputStatuses[1].hidden, true);
        strictAssert.equal(capabilityStatus.hidden, true);
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_live_channel_status_uses_led_indicators():
    _index_html, app_js, styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")
    render_channel = extract_js_function(app_js, "renderChannelCard")
    normal_render_channel = render_channel[render_channel.index("const outputClass"):]
    protection_badge = extract_js_function(live_data_js, "protectionBadge")

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
    command_form_js = read_static_javascript("command-form.js")

    submit_basic = extract_js_function(app_js, "submitBasicJob")
    run_set = extract_js_function(app_js, "runBasicSet")
    run_output = extract_js_function(app_js, "runBasicOutput")
    run_all = extract_js_function(app_js, "runBasicOutputAll")
    handle_job = extract_js_function(read_static_javascript("jobs.js"), "handleJobEvent")

    assert 'command: "set"' not in run_set
    assert 'await submitBasicJob("set"' in run_set
    assert "{ channel, ...values.parameters }" in run_set
    assert "parameters.voltage = voltage" in command_form_js
    assert "parameters.current = current" in command_form_js
    assert "requires V, A, or both" in command_form_js
    assert '"output-off"' in run_output
    assert '"output-on"' in run_output
    assert 'channel: "all"' in run_all
    assert '"apply"' not in run_set
    assert '"apply"' not in run_output
    assert '"apply"' not in run_all
    assert "runtime: runtimePayload()" in submit_basic
    assert "Enable real hardware writes" in submit_basic
    assert "submitJob(payload)" in submit_basic
    assert "tripGuardReason(command, parameters)" in submit_basic
    assert "electricalRatingGuardReason(command, parameters)" in submit_basic
    assert "state.basicJobActions[response.job_id]" in submit_basic
    assert "updateBasicActionFromJob(jobId, event, job);" in handle_job


def test_static_basic_command_error_state_contract():
    _index_html, app_js, styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    basic_controls_js = read_static_javascript("basic-controls.js")

    assert "basicActionStates: {}" in state_js
    assert "basicJobActions: {}" in state_js
    assert 'setBasicActionState(actionKey, "error"' in app_js
    assert 'button.classList.toggle("basic-action-error"' in basic_controls_js
    assert 'card.classList.toggle("basic-action-error"' in basic_controls_js
    assert "clearResolvedBasicErrors(channel, liveChannel, fresh);" in basic_controls_js
    assert "liveSetpointsMatchBasicInputs(channel, liveChannel)" in basic_controls_js
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
    state_js = read_static_javascript("state.js")
    catalog_js = read_static_javascript("command-catalog.js")
    command_form_js = read_static_javascript("command-form.js")

    assert 'activeCategory: "output"' in state_js
    assert 'export const COMMAND_CATEGORIES = ["output", "workflow", "protection", "trigger", "artifact", "discovery"];' in catalog_js

    render_commands = command_form_js[command_form_js.index("function renderCommands()"):command_form_js.index("function selectCommand")]
    assert 'const categories = document.getElementById("command-categories");' in render_commands
    assert "commandCatalog.COMMAND_CATEGORIES.forEach((category)" in render_commands
    assert 'state.activeCategory = category;' in render_commands
    assert '(meta.category || "discovery") === state.activeCategory' in render_commands


def test_result_panel_is_collapsible():
    index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")

    assert 'id="result-panel" class="result-panel collapsed"' in index_html
    assert 'id="result-toggle"' in index_html
    assert 'aria-expanded="false"' in index_html
    assert 'resultCollapsed: true' in state_js
    assert 'document.getElementById("result-toggle").addEventListener("click"' in app_js
    assert 'classList.toggle("collapsed"' in app_js
    assert 'setAttribute("aria-expanded"' in app_js


def test_job_result_is_expanded_collapsible_and_clearable():
    index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")

    assert 'id="job-result-panel" class="job-result-panel"' in index_html
    assert 'id="job-result-clear"' in index_html
    assert 'id="job-result-toggle"' in index_html
    assert 'aria-expanded="true"' in index_html
    assert "jobResultCollapsed: false" in state_js
    assert 'document.getElementById("job-result-toggle").addEventListener("click", toggleJobResultPanel);' in app_js
    assert 'document.getElementById("job-result-clear").addEventListener("click", clearJobResults);' in app_js
    clear_block = app_js[app_js.index("function clearJobResults()"):app_js.index("async function startLive")]
    assert "state.jobs = [];" in clear_block
    assert 'document.getElementById("result").textContent' not in clear_block


def test_static_ramp_list_editor_contract():
    _index_html, app_js, styles_css = read_static_texts()
    json_files_js = read_static_javascript("json-files.js")
    ramp_list_js = read_static_javascript("ramp-list.js")
    workflows_js = read_static_javascript("workflows.js")

    assert '"ramp-list": []' in app_js
    for field in ("channel", "current", "start_voltage", "stop_voltage", "step_voltage", "delay_ms", "hold_ms"):
        assert f'name: "{field}"' in ramp_list_js
    assert "state.rampListSegments.length >= 10" in workflows_js
    assert "if (state.rampListSegments.length <= 1) return;" in workflows_js
    assert "start_voltage: previous.stop_voltage" in workflows_js
    assert "stop_voltage: previous.stop_voltage" in workflows_js
    assert 'kind: "powers-tool-ramp-list"' in ramp_list_js
    ramp_document = extract_js_function(ramp_list_js, "rampListDocument")
    assert "version: 4" in ramp_document
    assert "enable_output: state.rampListEnableOutput" in ramp_document
    validator = extract_js_function(ramp_list_js, "validateRampListDocument")
    assert 'document.kind !== "powers-tool-ramp-list"' in validator
    assert "![2, 3, 4].includes(document.version)" in validator
    assert 'typeof document.enable_output !== "boolean"' in validator
    assert "document.version !== 1" not in validator
    assert "return webuiRampListDocument.rampListDocument(state);" in workflows_js
    assert "return webuiRampListDocument.validateRampListDocument(document);" in workflows_js
    assert "window.showOpenFilePicker" in json_files_js
    assert "window.showSaveFilePicker" in json_files_js
    assert "const normalized = validateRampListDocument(JSON.parse(text));" in workflows_js
    assert "state.rampListSegments = normalized.segments;" in workflows_js
    assert "state.rampListCompletionPulse = normalized.completionPulse;" in workflows_js
    assert "state.rampListEnableOutput = normalized.enableOutput;" in workflows_js
    assert 'name: "completion_pulse_timing"' in app_js
    assert 'name: "completion_pulse_step"' not in app_js
    assert 'name: "completion_pulse_segment"' not in app_js
    assert "state.rampListCompletionPulse = normalized.completionPulse;" in workflows_js
    assert "document.completion_pulse" in ramp_list_js
    assert '"trigger-pulse": [channel()' in workflows_js
    assert 'const REAR_PIN_OPTIONS = ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"];' in app_js
    assert 'option.textContent = definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value);' in workflows_js
    assert 'definition.name === "timing" && value === "step" && stepPulseBlocked' not in app_js
    assert "rampListStepPulseBlocked()" not in app_js
    assert ".ramp-list-pulse-hint { grid-column: 1 / -1; }" in styles_css
    assert 'if (state.selected === "ramp-list") return { document: rampListDocument() };' in read_static_javascript("command-form.js")
    assert 'command === "ramp-list"' in app_js


def test_static_compact_output_enable_layout_and_accessibility_contracts():
    _index_html, app_js, styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")
    workflows_js = read_static_javascript("workflows.js")

    assert "Output behavior" not in app_js
    assert "output-behavior" not in app_js
    assert ".output-behavior" not in styles_css
    assert ".visually-hidden {" in styles_css
    checkbox_builder = extract_js_function(command_form_js, "createCheckboxField")
    assert 'label.classList.add("checkbox-field", ...classNames);' in checkbox_builder
    assert 'visibleText.className = "checkbox-label-text";' in checkbox_builder
    assert "label.append(input, visibleText);" in checkbox_builder
    assert "cloneNode" not in checkbox_builder
    assert "createCheckboxField(input, param.label)" in extract_js_function(command_form_js, "renderForm")
    assert "webuiCommandForm.createCheckboxField(input, definition.label)" in extract_js_function(workflows_js, "triggerListControlField")
    assert "webuiCommandForm.createCheckboxField(enableInput, \"Enable each channel\"" in extract_js_function(workflows_js, "renderRampListForm")
    assert "webuiCommandForm.createCheckboxField(restoreStateCheck, \"Restore previous output ON/OFF state\")" in extract_js_function(workflows_js, "renderRestoreForm")
    assert "webuiCommandForm.createCheckboxField(input, definition.label)" in extract_js_function(workflows_js, "sequenceStepFields")

    checkbox_css = styles_css[
        styles_css.index(".form-grid .checkbox-field {"):styles_css.index(".form-grid .pulse-toggle-field {")
    ]
    assert "display: grid;" in checkbox_css
    assert "grid-template-columns: 16px minmax(0, 1fr);" in checkbox_css
    assert "column-gap: 8px;" in checkbox_css
    assert "row-gap: 0;" in checkbox_css
    assert "width: 16px;" in checkbox_css
    assert "min-width: 16px;" in checkbox_css
    assert "max-width: 16px;" in checkbox_css
    assert "height: 16px;" in checkbox_css
    assert "grid-column: 1;" in checkbox_css
    assert "grid-row: 1;" in checkbox_css
    assert "align-self: center;" in checkbox_css
    visible_text_css = checkbox_css[
        checkbox_css.index(".form-grid .checkbox-label-text {"):checkbox_css.index(".form-grid .checkbox-field .field-description {")
    ]
    description_css = checkbox_css[checkbox_css.index(".form-grid .checkbox-field .field-description {"):]
    assert "grid-column: 2;" in visible_text_css
    assert "grid-row: 1;" in visible_text_css
    assert "grid-column: 2;" in description_css
    assert "grid-row: 2;" in description_css
    assert "width: 100%;" not in checkbox_css

    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeElement {
          constructor(tagName) {
            this.tagName = tagName.toUpperCase();
            this.children = [];
            this.parentNode = null;
            this.dataset = {};
            this.attributes = {};
            this.listeners = {};
            this.className = "";
            this.id = "";
            this.textContent = "";
            this.title = "";
            this.style = {};
            this.classList = {
              add: (...names) => {
                const values = new Set(this.className.split(/\s+/).filter(Boolean));
                names.forEach((name) => values.add(name));
                this.className = [...values].join(" ");
              },
              contains: (name) => this.className.split(/\s+/).filter(Boolean).includes(name),
              remove: (...names) => {
                const removed = new Set(names);
                this.className = this.className.split(/\s+/).filter((name) => name && !removed.has(name)).join(" ");
              }
            };
          }

          get options() {
            return this.children;
          }

          set innerHTML(value) {
            strictAssert.equal(value, "");
            this.textContent = "";
            this.children = [];
          }

          appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            return child;
          }

          append(...children) {
            children.forEach((child) => this.appendChild(child));
          }

          addEventListener(type, listener) {
            (this.listeners[type] ||= []).push(listener);
          }

          setAttribute(name, value) {
            this.attributes[name] = String(value);
          }

          getAttribute(name) {
            return this.attributes[name] ?? null;
          }

          querySelector(selector) {
            if (!selector.startsWith(".")) return null;
            return descendants(this).find((node) => node !== this && node.classList.contains(selector.slice(1))) || null;
          }

          remove() {
            if (!this.parentNode) return;
            this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
            this.parentNode = null;
          }
        }

        const commandForm = new FakeElement("form");
        commandForm.id = "command-form";
        document.createElement = (tagName) => new FakeElement(tagName);
        const descendants = (root) => [
          root,
          ...root.children.flatMap((child) => descendants(child))
        ];
        const byId = (root, id) => descendants(root).find((node) => node.id === id);
        const byClass = (root, className) => descendants(root).filter(
          (node) => node.classList.contains(className)
        );
        document.getElementById = (id) => {
          if (id === "command-form") return commandForm;
          if (["expected-model-id", "resource"].includes(id)) return { value: "" };
          return byId(commandForm, id);
        };
        document.querySelectorAll = () => [];
        applyParameterConstraint = () => {};
        applyElectricalRatingConstraint = () => {};
        applyWorkflowPulseControlState = () => {};
        isChannelSupported = () => true;
        updatePulseChildVisibility = () => {};
        updateSelectedCommandState = () => {};

        const assertCompactControl = (root, inputId, helpId, labelText, ariaLabel, helpText) => {
          const input = byId(root, inputId);
          const label = input.parentNode;
          const help = byId(root, helpId);
          strictAssert.equal(label.tagName, "LABEL");
          strictAssert.equal(label.children[0], input);
          strictAssert.equal(label.children[1].tagName, "SPAN");
          strictAssert.equal(label.children[1].classList.contains("checkbox-label-text"), true);
          strictAssert.equal(label.children[1].textContent, labelText);
          strictAssert.equal(label.children[2], help);
          strictAssert.equal(label.getAttribute("for"), inputId);
          strictAssert.equal(label.title, helpText);
          strictAssert.equal(input.title, helpText);
          strictAssert.equal(input.getAttribute("aria-label"), ariaLabel);
          strictAssert.equal(input.getAttribute("aria-describedby"), helpId);
          strictAssert.equal(help.textContent, helpText);
          strictAssert.equal(help.classList.contains("visually-hidden"), true);
          return { input, label, help };
        };

        const existingInput = document.createElement("input");
        existingInput.type = "checkbox";
        existingInput.id = "existing-checkbox";
        existingInput.checked = true;
        existingInput.disabled = true;
        existingInput.dataset.example = "preserved";
        existingInput.addEventListener("change", () => {});
        const existingLabel = webuiCommandForm.createCheckboxField(existingInput, "Existing checkbox");
        strictAssert.equal(existingLabel.children[0], existingInput);
        strictAssert.equal(existingLabel.children[1].tagName, "SPAN");
        strictAssert.equal(existingLabel.children[1].classList.contains("checkbox-label-text"), true);
        strictAssert.equal(existingLabel.children[1].textContent, "Existing checkbox");
        strictAssert.equal(existingInput.id, "existing-checkbox");
        strictAssert.equal(existingInput.checked, true);
        strictAssert.equal(existingInput.disabled, true);
        strictAssert.equal(existingInput.dataset.example, "preserved");
        strictAssert.equal(existingInput.listeners.change.length, 1);

        const rampHelp = "Output is enabled only after the first safe setpoint is written and verified. It remains ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation.";
        state.selected = "ramp";
        renderForm("ramp");
        const rampParts = assertCompactControl(
          commandForm,
          "param-enable_output",
          "ramp-enable-output-help",
          "Enable output",
          "Enable output after first setpoint",
          rampHelp
        );
        const loopControl = byId(commandForm, "param-loop_enabled").parentNode.parentNode;
        const channel = byId(commandForm, "param-channel").parentNode;
        strictAssert.equal(commandForm.children.indexOf(rampParts.label), 0);
        strictAssert.equal(commandForm.children.indexOf(loopControl), 1);
        strictAssert.equal(commandForm.children.indexOf(channel), 2);
        strictAssert.equal(byId(commandForm, "param-loop_count"), undefined);
        const rampLoopEnabled = byId(commandForm, "param-loop_enabled");
        rampLoopEnabled.checked = true;
        rampLoopEnabled.listeners.change.forEach((listener) => listener());
        const rampLoopCount = byId(commandForm, "param-loop_count");
        strictAssert.equal(rampLoopCount.value, "2");
        strictAssert.equal(rampLoopCount.min, "2");
        strictAssert.equal(rampLoopCount.max, "255");
        strictAssert.equal(rampLoopCount.step, "1");
        strictAssert.equal(rampLoopCount.required, true);
        const rampTiming = byId(commandForm, "param-completion_pulse_timing");
        strictAssert.deepEqual(rampTiming.children.map((option) => option.textContent), [
          "None", "Every step", "Ramp complete", "Loop complete"
        ]);
        rampTiming.value = "loop";
        rampLoopEnabled.checked = false;
        rampLoopEnabled.listeners.change.forEach((listener) => listener());
        strictAssert.equal(byId(commandForm, "param-loop_count"), undefined);
        strictAssert.equal(rampTiming.value, "");
        strictAssert.equal(rampParts.input.listeners.change.length, 1);
        strictAssert.equal(rampParts.input.listeners.input.length, 1);

        renderForm("ramp");
        strictAssert.equal(descendants(commandForm).filter((node) => node.id === "param-enable_output").length, 1);
        strictAssert.equal(descendants(commandForm).filter((node) => node.id === "ramp-enable-output-help").length, 1);
        strictAssert.equal(byClass(commandForm, "output-behavior").length, 0);

        const rampListHelp = "Each channel is enabled only after its first safe segment setpoint is written and verified. Outputs remain ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation.";
        state.selected = "ramp-list";
        state.rampListEnableOutput = true;
        renderForm("ramp-list");
        const editor = commandForm.children[0];
        const toolbar = byClass(editor, "ramp-list-toolbar")[0];
        const rampListParts = assertCompactControl(
          editor,
          "ramp-list-enable-output",
          "ramp-list-enable-output-help",
          "Enable each channel",
          "Enable each channel at its first segment",
          rampListHelp
        );
        const pulseFields = editor.children.find(
          (child) => byId(child, "ramp-list-pulse-timing")
            && byId(child, "ramp-list-pulse-pins")
            && byId(child, "ramp-list-pulse-polarity")
        );
        const segmentCard = byClass(editor, "ramp-segment-card")[0];
        strictAssert.equal(editor.children.indexOf(toolbar), 0);
        strictAssert.equal(editor.children.indexOf(rampListParts.label), 1);
        strictAssert.equal(editor.children.indexOf(byId(editor, "ramp-list-loop-enabled").parentNode.parentNode), 2);
        strictAssert.equal(editor.children.indexOf(pulseFields), 3);
        strictAssert.equal(editor.children.indexOf(segmentCard), 4);
        strictAssert.equal(byId(editor, "ramp-list-loop-count"), undefined);
        const rampListTiming = byId(editor, "ramp-list-pulse-timing");
        strictAssert.deepEqual(rampListTiming.children.map((option) => option.textContent), [
          "None", "Every step", "Segment complete", "Loop complete"
        ]);
        strictAssert.equal(rampListTiming.children[3].disabled, true);
        strictAssert.equal(rampListParts.input.checked, true);
        strictAssert.equal(rampListParts.input.listeners.change.length, 1);

        renderForm("ramp-list");
        strictAssert.equal(descendants(commandForm).filter((node) => node.id === "ramp-list-enable-output").length, 1);
        strictAssert.equal(descendants(commandForm).filter((node) => node.id === "ramp-list-enable-output-help").length, 1);
        strictAssert.equal(byClass(commandForm, "output-behavior").length, 0);
        let rerenderedEditor = commandForm.children[0];
        let rampListLoopEnabled = byId(rerenderedEditor, "ramp-list-loop-enabled");
        rampListLoopEnabled.checked = true;
        rampListLoopEnabled.listeners.change.forEach((listener) => listener());
        let rerenderedTiming = byId(rerenderedEditor, "ramp-list-pulse-timing");
        strictAssert.equal(rerenderedTiming.children[3].disabled, false);
        rerenderedTiming.value = "loop";
        rerenderedTiming.listeners.change.forEach((listener) => listener());
        rerenderedEditor = commandForm.children[0];
        let rampListLoopCount = byId(rerenderedEditor, "ramp-list-loop-count");
        rampListLoopCount.value = "1.5";
        rampListLoopCount.listeners.input.forEach((listener) => listener());
        rerenderedTiming = byId(rerenderedEditor, "ramp-list-pulse-timing");
        strictAssert.equal(state.rampListCompletionPulse.timing, "loop");
        strictAssert.equal(rerenderedTiming.value, "loop");
        strictAssert.equal(rerenderedTiming.children[3].disabled, true);
        renderForm("ramp-list");
        rerenderedEditor = commandForm.children[0];
        rampListLoopEnabled = byId(rerenderedEditor, "ramp-list-loop-enabled");
        rampListLoopCount = byId(rerenderedEditor, "ramp-list-loop-count");
        rerenderedTiming = byId(rerenderedEditor, "ramp-list-pulse-timing");
        strictAssert.equal(rampListLoopEnabled.checked, true);
        strictAssert.equal(rampListLoopCount.value, "1.5");
        strictAssert.equal(rerenderedTiming.value, "loop");
        strictAssert.equal(rerenderedTiming.children[3].disabled, true);
        const invalidRampRun = { disabled: false };
        strictAssert.equal(updateWorkflowDocumentValidity("ramp-list", invalidRampRun), false);
        strictAssert.equal(invalidRampRun.disabled, true);
        strictAssert.equal(byId(rerenderedEditor, "save-ramp-list").disabled, true);
        rampListLoopCount.value = "3";
        rampListLoopCount.listeners.input.forEach((listener) => listener());
        strictAssert.equal(rerenderedTiming.value, "loop");
        strictAssert.equal(rerenderedTiming.children[3].disabled, false);
        strictAssert.equal(state.rampListCompletionPulse.timing, "loop");
        const validRampRun = { disabled: false };
        strictAssert.equal(updateWorkflowDocumentValidity("ramp-list", validRampRun), true);
        strictAssert.equal(validRampRun.disabled, false);
        strictAssert.equal(byId(rerenderedEditor, "save-ramp-list").disabled, false);

        state.selected = "sequence";
        state.sequenceLoopEnabled = false;
        state.sequenceLoopCountDraft = "2";
        renderForm("sequence");
        const sequenceEditor = commandForm.children[0];
        strictAssert.equal(byClass(sequenceEditor, "sequence-toolbar")[0], sequenceEditor.children[0]);
        strictAssert.equal(byId(sequenceEditor, "sequence-loop-enabled").parentNode.parentNode, sequenceEditor.children[1]);
        strictAssert.equal(byClass(sequenceEditor, "sequence-step-card")[0], sequenceEditor.children[2]);
        strictAssert.equal(byId(sequenceEditor, "sequence-loop-count"), undefined);
        const sequenceLoopEnabled = byId(sequenceEditor, "sequence-loop-enabled");
        sequenceLoopEnabled.checked = true;
        sequenceLoopEnabled.listeners.change[0]();
        strictAssert.equal(state.sequenceLoopEnabled, true);
        strictAssert.equal(state.sequenceLoopCountDraft, "2");
        strictAssert.equal(byId(sequenceEditor, "sequence-loop-count").value, "2");
        let sequenceLoopCount = byId(sequenceEditor, "sequence-loop-count");
        sequenceLoopCount.value = "256";
        sequenceLoopCount.listeners.input.forEach((listener) => listener());
        renderForm("sequence");
        const rerenderedSequenceEditor = commandForm.children[0];
        strictAssert.equal(byId(rerenderedSequenceEditor, "sequence-loop-enabled").checked, true);
        sequenceLoopCount = byId(rerenderedSequenceEditor, "sequence-loop-count");
        strictAssert.equal(sequenceLoopCount.value, "256");
        const invalidSequenceRun = { disabled: false };
        strictAssert.equal(updateWorkflowDocumentValidity("sequence", invalidSequenceRun), false);
        strictAssert.equal(invalidSequenceRun.disabled, true);
        strictAssert.equal(byId(rerenderedSequenceEditor, "save-sequence").disabled, true);
        sequenceLoopCount.value = "4";
        sequenceLoopCount.listeners.input.forEach((listener) => listener());
        const validSequenceRun = { disabled: false };
        strictAssert.equal(updateWorkflowDocumentValidity("sequence", validSequenceRun), true);
        strictAssert.equal(validSequenceRun.disabled, false);
        strictAssert.equal(byId(rerenderedSequenceEditor, "save-sequence").disabled, false);

        state.triggerListControls.source = "immediate";
        const triggerLabel = triggerListControlField({ name: "fire", label: "Fire", type: "checkbox" });
        const triggerInput = triggerLabel.children[0];
        strictAssert.equal(triggerInput.parentNode, triggerLabel);
        strictAssert.equal(triggerLabel.children[1].tagName, "SPAN");
        strictAssert.equal(triggerLabel.children[1].classList.contains("checkbox-label-text"), true);
        strictAssert.equal(triggerLabel.children[1].textContent, "Fire");
        strictAssert.equal(triggerInput.disabled, true);
        strictAssert.equal(triggerInput.listeners.change.length, 1);
        strictAssert.equal(triggerInput.listeners.input.length, 1);

        const sequenceFields = sequenceStepFields(
          defaultSequenceStep("trigger-pulse"),
          0,
          new FakeElement("article"),
          new FakeElement("strong"),
          new FakeElement("span")
        );
        const sequenceInput = descendants(sequenceFields).find(
          (node) => node.dataset.sequenceField === "leave_trigger_configured"
        );
        const sequenceLabel = sequenceInput.parentNode;
        strictAssert.equal(sequenceLabel.children[0], sequenceInput);
        strictAssert.equal(sequenceLabel.children[1].tagName, "SPAN");
        strictAssert.equal(sequenceLabel.children[1].classList.contains("checkbox-label-text"), true);
        strictAssert.equal(sequenceLabel.children[2].classList.contains("field-description"), true);
        strictAssert.equal(sequenceInput.listeners.change.length, 1);
        strictAssert.equal(sequenceInput.listeners.input.length, 1);

        renderRestorePlanPreview = () => {};
        isLoadedRestoreSnapshotValid = () => false;
        const restoreForm = new FakeElement("form");
        renderRestoreForm(restoreForm);
        const restoreInput = byId(restoreForm, "param-restore_output_state");
        const restoreLabel = restoreInput.parentNode;
        strictAssert.equal(restoreLabel.children[0], restoreInput);
        strictAssert.equal(restoreLabel.children[1].tagName, "SPAN");
        strictAssert.equal(restoreLabel.children[1].classList.contains("checkbox-label-text"), true);
        strictAssert.equal(restoreLabel.children[1].textContent, "Restore previous output ON/OFF state");
        strictAssert.equal(restoreInput.listeners.change.length, 1);
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_workflow_run_button_state_contract():
    index_html, app_js, styles_css = read_static_texts()
    jobs_js = read_static_javascript("jobs.js")

    assert 'id="run" type="button" aria-label="Run"' in index_html
    assert 'const STOPPABLE_WORKFLOWS = new Set(["ramp", "ramp-list", "sequence"]);' in app_js
    assert '"Stop the active workflow and safely turn all outputs off."' in app_js
    workflow_button = extract_js_function(app_js, "updateWorkflowRunButton")
    for label in ('"Run"', '"Starting..."', '"Stop"', '"Stopping..."'):
        assert label in workflow_button
    assert 'button.classList.toggle("workflow-stop"' in workflow_button
    assert 'webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`' in extract_js_function(
        app_js, "stopActiveWorkflow"
    )
    assert 'event.type === "cancel_requested"' in extract_js_function(jobs_js, "handleJobEvent")
    assert "Waiting for safe-off and cleanup" in jobs_js
    assert "Failed  cleanup_failed" in jobs_js
    assert "button#run.workflow-stop" in styles_css


