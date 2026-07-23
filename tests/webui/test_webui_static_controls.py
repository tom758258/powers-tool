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
    assert "basic-output-all-global-slot" not in index_html
    assert "basic-e3646a-output-row" not in index_html
    assert index_html.index('id="basic-output-all-header-slot"') < index_html.index('id="advanced-command-toggle"')
    assert_static_id(index_html, "basic-output-capability-status")
    assert_static_id(index_html, "e3646a-global-output-description")

    explanation = (
        "E3646A does not support independent channel output switching. "
        "Use ALL to turn CH1 and CH2 on or off together."
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
    assert ".basic-e3646a-output-row" not in styles_css
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
        const capabilityStatus = new FakeElement("div");
        const basicStatus = new FakeElement("div");
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
          ["basic-output-capability-status", capabilityStatus],
          ["basic-command-status", basicStatus]
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
        strictAssert.equal(allButton.parentNode, headerSlot);
        strictAssert.equal(outputButtons[1].hidden, false);
        strictAssert.equal(outputButtons[1].disabled, true);
        strictAssert.equal(outputButtons[1].textContent, "Controlled by ALL");
        strictAssert.equal(outputButtons[2].hidden, false);
        strictAssert.equal(outputButtons[2].disabled, true);
        strictAssert.equal(outputButtons[2].textContent, "Controlled by ALL");
        strictAssert.equal(outputStatuses[1].hidden, true);
        strictAssert.equal(outputStatuses[2].hidden, true);
        strictAssert.equal(outputInfo[1].hidden, false);
        strictAssert.equal(outputInfo[1].title, "E3646A does not support independent channel output switching. Use ALL to turn CH1 and CH2 on or off together.");
        strictAssert.equal(allButton.textContent, "ALL ON");
        strictAssert.equal(allButton.classList.contains("on"), true);
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "true");
        strictAssert.equal(allButton.getAttribute("aria-label"), "All outputs on");
        strictAssert.equal(allButton.disabled, false);

        state.livePanel.channels[0].output_enabled = false;
        state.livePanel.channels[1].output_enabled = false;
        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputButton(1, state.livePanel.channels[0], true);
        strictAssert.equal(allButton.textContent, "ALL ON");
        strictAssert.equal(allButton.classList.contains("off"), true);
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "false");
        strictAssert.equal(allButton.getAttribute("aria-label"), "Not all outputs on");
        strictAssert.equal(allButton.disabled, false);
        strictAssert.equal(outputButtons[1].textContent, "Controlled by ALL");

        state.livePanel.channels[0].output_enabled = null;
        renderBasicOutputButton(1, state.livePanel.channels[0], true);
        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputControlState("all");
        strictAssert.equal(outputButtons[1].textContent, "Controlled by ALL");
        strictAssert.equal(allButton.textContent, "ALL ON");
        strictAssert.equal(allButton.classList.contains("unknown"), true);
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "mixed");
        strictAssert.equal(allButton.getAttribute("aria-label"), "Not all outputs on");
        strictAssert.equal(allButton.disabled, false);
        state.livePanel.channels[0].output_enabled = true;
        renderBasicAllOutputButton(state.livePanel.channels);
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "mixed");
        strictAssert.equal(allButton.disabled, false);
        state.livePanel.stale = true;
        renderBasicAllOutputButton(state.livePanel.channels);
        renderBasicOutputControlState("all");
        strictAssert.equal(allButton.getAttribute("aria-pressed"), "mixed");
        strictAssert.equal(allButton.disabled, false);
        state.livePanel.stale = false;

        let submissions = [];
        submitBasicJob = async (...args) => { submissions.push(args); };
        runBasicOutputAll();
        strictAssert.equal(submissions.length, 1);
        strictAssert.equal(submissions[0][0], "output-on");
        strictAssert.deepEqual(submissions[0][1], { channel: "all" });

        state.livePanel.channels[0].output_enabled = false;
        runBasicOutputAll();
        strictAssert.equal(submissions.length, 2);
        strictAssert.equal(submissions[1][0], "output-on");
        strictAssert.deepEqual(submissions[1][1], { channel: "all" });
        state.livePanel.channels[0].output_enabled = true;
        state.livePanel.channels[1].output_enabled = true;
        runBasicOutputAll();
        strictAssert.equal(submissions.length, 3);
        strictAssert.equal(submissions[2][0], "output-off");
        strictAssert.deepEqual(submissions[2][1], { channel: "all" });

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
        strictAssert.equal(headerSlot.children.filter((node) => node === allButton).length, 1);
        strictAssert.equal(allButton.listeners.click.length, 1);
        strictAssert.equal(allButton.listeners.click[0], originalListener);
        const allButtonIdentity = allButton;
        const livePanelIdentity = state.livePanel;
        setpointControls[0].value = "1.234";
        setpointControls[0].dataset = { basicDirty: "true" };
        let basicFetchCalls = 0;
        webuiApi.fetchJson = async () => { basicFetchCalls += 1; };
        setBasicActionState("output:all", "pending", { key: "basic_controls.status.waiting_readback" }, {
          desiredOutput: true,
          awaitingReadback: true
        });
        const pendingActionIdentity = state.basicActionStates["output:all"];
        setLocale("zh-TW");
        refreshBasicControlsPresentation();
        strictAssert.equal(allButton, allButtonIdentity);
        strictAssert.equal(state.livePanel, livePanelIdentity);
        strictAssert.equal(allButton.textContent, "全部開啟");
        strictAssert.equal(allButton.getAttribute("aria-label"), "所有輸出皆開啟");
        strictAssert.equal(outputButtons[1].textContent, "由 ALL 控制");
        strictAssert.equal(outputButtons[1].getAttribute("aria-label"), "CH1 輸出 由 ALL 控制");
        strictAssert.equal(outputInfo[1].getAttribute("aria-label"), "E3646A 全域輸出資訊");
        strictAssert.equal(outputInfo[1].title, "E3646A 不支援個別通道輸出開關，請使用 ALL 同時開啟或關閉 CH1 與 CH2。");
        strictAssert.equal(basicStatus.textContent, "正在等待即時資料讀回。");
        strictAssert.equal(allButton.title, "正在等待即時資料讀回。");
        strictAssert.equal(allButton.disabled, true);
        strictAssert.equal(state.basicActionStates["output:all"], pendingActionIdentity);
        strictAssert.equal(pendingActionIdentity.desiredOutput, true);
        strictAssert.equal(pendingActionIdentity.awaitingReadback, true);
        strictAssert.equal(setpointControls[0].value, "1.234");
        strictAssert.equal(setpointControls[0].dataset.basicDirty, "true");
        strictAssert.equal(allButton.listeners.click.length, 1);
        strictAssert.equal(allButton.listeners.click[0], originalListener);
        setBasicActionState("output:all", "error", "VISA <raw> detail", {
          desiredOutput: true,
          awaitingReadback: false
        });
        refreshBasicControlsPresentation();
        strictAssert.equal(basicStatus.textContent, "VISA <raw> detail");
        strictAssert.equal(allButton.title, "VISA <raw> detail");
        strictAssert.equal(basicFetchCalls, 0);
        state.basicActionStates = {};
        setLocale("en");
        refreshBasicControlsPresentation();
        strictAssert.equal(allButton.textContent, "ALL ON");

        state.channelCapabilitiesByModel["keysight-e3646a"] = {
          channels: [1, 2],
          output_control_scope: "per_channel"
        };
        applyBasicOutputPresentation();
        strictAssert.equal(basicOutputPresentation().mode, "e3646a-disabled");
        strictAssert.equal(allButton.parentNode, headerSlot);
        strictAssert.equal(outputButtons[1].hidden, false);
        strictAssert.equal(outputButtons[1].disabled, true);
        strictAssert.equal(capabilityStatus.textContent, "E3646A output controls are disabled because global-output capability metadata is missing or inconsistent.");

        delete state.channelCapabilitiesByModel["keysight-e3646a"];
        applyBasicOutputPresentation();
        strictAssert.equal(allButton.parentNode, headerSlot);
        strictAssert.equal(capabilityStatus.hidden, false);
        strictAssert.equal(capabilityStatus.textContent, "E3646A output controls are disabled because global-output capability metadata is missing or inconsistent.");
        strictAssert.equal(allButton.disabled, true);
        strictAssert.equal(allButton.title, "E3646A output controls are disabled because global-output capability metadata is missing or inconsistent.");
        for (const channel of [1, 2, 3]) {
          strictAssert.equal(outputButtons[channel].disabled, true);
          strictAssert.equal(outputButtons[channel].title, "E3646A output controls are disabled because global-output capability metadata is missing or inconsistent.");
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
    render_channel = extract_js_function(live_data_js, "renderChannelCard")
    replace_card = extract_js_function(live_data_js, "replaceCardContent")
    protection_badge = extract_js_function(live_data_js, "protectionBadge")

    assert "innerHTML" not in render_channel
    assert "innerHTML" not in replace_card
    assert "replaceCardContent(card, channel" in render_channel
    assert "`status-badge status-indicator output-status ${presentation.outputClass}`" in replace_card
    assert 'element("div", "live-control-section")' in replace_card
    assert 'element("div", "live-protection-section")' in replace_card
    assert 'element("div", "live-protection-badges")' in replace_card
    assert 'protectionBadge("OVP", presentation.overVoltageTripped)' in replace_card
    assert 'protectionBadge("OCP", presentation.overCurrentTripped)' in replace_card
    assert 'element("span", `protection-badge status-indicator ${stateClass}`)' in protection_badge
    assert 'element("span", "indicator-text", `${label} ${stateText}`)' in protection_badge
    assert ".output-status .indicator-dot" in styles_css
    assert ".output-status.off" in styles_css
    assert ".live-control-section" in styles_css
    assert ".live-protection-section" in styles_css


def test_static_cached_live_presentation_refresh_has_no_operational_side_effects():
    _index_html, app_js, _styles_css = read_static_texts()
    refresh = extract_js_function(app_js, "refreshLiveDataPresentation")

    assert "state.livePanel" in refresh
    assert "renderChannelCard" in refresh
    assert "drawTrend()" in refresh
    for forbidden in (
        "fetch",
        "EventSource",
        "state.samples.push",
        "state.samples =",
        "startLive",
        "stopLive",
        "closeEventSource",
        "state.liveJobId =",
    ):
        assert forbidden not in refresh


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
    clear_block = extract_js_function(app_js, "clearJobResults")
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
    assert 'localizedOption(option, value, definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value), definition.name === "pins");' in workflows_js
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

          get firstChild() {
            if (this.textContent) {
              const owner = this;
              return {
                nodeType: 3,
                get textContent() { return owner.textContent; },
                set textContent(value) { owner.textContent = value; }
              };
            }
            return this.children[0];
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

          querySelectorAll(selector) {
            if (selector === "label[data-i18n-param]") {
              return descendants(this).filter((node) => node.tagName === "LABEL" && node.dataset.i18nParam);
            }
            if (selector === "option[data-i18n-option]") {
              return descendants(this).filter((node) => node.tagName === "OPTION" && node.dataset.i18nOption !== undefined);
            }
            if (selector === "[data-i18n-loop]") {
              return descendants(this).filter((node) => node.dataset.i18nLoop);
            }
                if (selector === "[data-workflow-i18n]") {
                  return descendants(this).filter((node) => node.dataset.workflowI18n);
                }
                if (selector === "[data-workflow-compact-help-description]") {
                  return descendants(this).filter((node) => node.dataset.workflowCompactHelpDescription);
                }
                return [];
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
        const rampStart = byId(commandForm, "param-start_voltage");
        rampStart.value = "0.375";
        const rampCountIdentity = rampLoopCount;
        const rampCheckboxIdentity = rampLoopEnabled;
        const timingDisabled = rampTiming.disabled;
        const countListeners = {
          input: rampLoopCount.listeners.input.length,
          change: rampLoopCount.listeners.change.length
        };
        setLocale("zh-TW");
        refreshCommandFormPresentation();
        strictAssert.equal(byId(commandForm, "param-loop_enabled"), rampCheckboxIdentity);
        strictAssert.equal(byId(commandForm, "param-loop_count"), rampCountIdentity);
        strictAssert.equal(rampCheckboxIdentity.checked, true);
        strictAssert.equal(rampCountIdentity.value, "2");
        strictAssert.equal(rampCountIdentity.min, "2");
        strictAssert.equal(rampCountIdentity.max, "255");
        strictAssert.equal(rampCountIdentity.step, "1");
        strictAssert.equal(rampCountIdentity.required, true);
        strictAssert.deepEqual({
          input: rampCountIdentity.listeners.input.length,
          change: rampCountIdentity.listeners.change.length
        }, countListeners);
        strictAssert.equal(rampStart.value, "0.375");
        strictAssert.equal(rampTiming.value, "loop");
        strictAssert.equal(rampTiming.disabled, timingDisabled);
        strictAssert.equal(byClass(commandForm, "checkbox-label-text").find((node) => node.parentNode === rampCheckboxIdentity.parentNode).textContent, "啟用迴圈");
        strictAssert.equal(byClass(commandForm, "loop-count-label-text")[0].textContent, "迴圈次數");
        strictAssert.deepEqual(rampTiming.children.map((option) => option.textContent), [
          "無", "每個步驟", "斜坡完成", "迴圈完成"
        ]);
        const rampPins = byId(commandForm, "param-completion_pulse_pins");
        strictAssert.equal(rampPins.children[0].textContent, "接腳 1");
        strictAssert.equal(rampPins.children[0].value, "1");
        strictAssert.equal(rampPins.children.find((option) => option.value === "1,2").textContent, "接腳 1 + 2");
        const rampPolarity = byId(commandForm, "param-completion_pulse_polarity");
        strictAssert.deepEqual(rampPolarity.children.map((option) => option.textContent), ["正極性", "負極性"]);
        strictAssert.deepEqual(rampPolarity.children.map((option) => option.value), ["positive", "negative"]);
        const rampChannel = byId(commandForm, "param-channel");
        strictAssert.deepEqual(rampChannel.children.map((option) => option.textContent), ["1", "2", "3"]);
        strictAssert.deepEqual(rampChannel.children.map((option) => option.value), ["1", "2", "3"]);
        setLocale("en");
        refreshCommandFormPresentation();
        strictAssert.equal(byClass(commandForm, "checkbox-label-text").find((node) => node.parentNode === rampCheckboxIdentity.parentNode).textContent, "Enable loop");
        strictAssert.equal(byClass(commandForm, "loop-count-label-text")[0].textContent, "Loop count");
        strictAssert.deepEqual(rampTiming.children.map((option) => option.textContent), [
          "None", "Every step", "Ramp complete", "Loop complete"
        ]);
        rampLoopEnabled.checked = false;
        rampLoopEnabled.listeners.change.forEach((listener) => listener());
        strictAssert.equal(byId(commandForm, "param-loop_count"), undefined);
        strictAssert.equal(rampTiming.value, "");
        strictAssert.equal(rampParts.input.listeners.change.length, 1);
        strictAssert.equal(rampParts.input.listeners.input.length, 1);

        rampParts.input.checked = true;
        const formIdentity = commandForm;
        const selectedBeforeRefresh = state.selected;
        refreshCommandFormPresentation();
        strictAssert.equal(document.getElementById("command-form"), formIdentity);
        strictAssert.equal(state.selected, selectedBeforeRefresh);
        strictAssert.equal(rampStart.value, "0.375");
        strictAssert.equal(rampParts.input.checked, true);
        strictAssert.equal(rampTiming.value, "");
        strictAssert.equal(rampParts.input.listeners.change.length, 1);
        strictAssert.equal(rampParts.input.listeners.input.length, 1);

        renderForm("ramp");
        strictAssert.equal(descendants(commandForm).filter((node) => node.id === "param-enable_output").length, 1);
        strictAssert.equal(descendants(commandForm).filter((node) => node.id === "ramp-enable-output-help").length, 1);
        strictAssert.equal(byClass(commandForm, "output-behavior").length, 0);

        state.selected = "trigger-step";
        renderForm("trigger-step");
        const triggerVoltage = byId(commandForm, "param-voltage");
        const triggerCurrent = byId(commandForm, "param-current");
        strictAssert.equal(triggerVoltage.parentNode.textContent, "Triggered voltage(V)");
        strictAssert.equal(triggerCurrent.parentNode.textContent, "Triggered current(A)");
        triggerVoltage.value = "1.25";
        triggerCurrent.value = "0.2";
        const triggerSource = byId(commandForm, "param-source");
        const triggerChannel = byId(commandForm, "param-channel");
        const sourceValues = triggerSource.children.map((option) => option.value);
        setLocale("zh-TW");
        refreshCommandFormPresentation();
        strictAssert.equal(triggerVoltage.parentNode.textContent, "觸發電壓 (V)");
        strictAssert.equal(triggerCurrent.parentNode.textContent, "觸發電流 (A)");
        strictAssert.deepEqual(triggerChannel.children.map((option) => option.textContent), ["1", "2", "3"]);
        strictAssert.deepEqual(triggerChannel.children.map((option) => option.value), ["1", "2", "3"]);
        strictAssert.deepEqual(triggerSource.children.map((option) => option.textContent), ["BUS", "Immediate"]);
        strictAssert.deepEqual(triggerSource.children.map((option) => option.value), sourceValues);
        const triggerPayload = parameterPayload();
        strictAssert.equal(triggerPayload.voltage, 1.25);
        strictAssert.equal(triggerPayload.current, 0.2);
        strictAssert.equal(Object.hasOwn(triggerPayload, "triggered_voltage"), false);
        strictAssert.equal(Object.hasOwn(triggerPayload, "triggered_current"), false);
        setLocale("en");
        refreshCommandFormPresentation();
        strictAssert.equal(triggerVoltage.parentNode.textContent, "Triggered voltage(V)");
        strictAssert.equal(triggerCurrent.parentNode.textContent, "Triggered current(A)");

        state.selected = "trigger-fire";
        renderForm("trigger-fire");
        const triggerFireChannel = byId(commandForm, "param-channel");
        const triggerFireLabel = triggerFireChannel.parentNode;
        const triggerFireIdentity = triggerFireChannel;
        const triggerFireListeners = {
          input: triggerFireChannel.listeners.input.length,
          change: triggerFireChannel.listeners.change.length
        };
        const triggerFireOptionValues = triggerFireChannel.children.map((option) => option.value);
        strictAssert.equal(triggerFireLabel.textContent, "Abort target channel");
        strictAssert.equal(triggerFireChannel.id, "param-channel");
        strictAssert.equal(triggerFireChannel.dataset.i18nParam, "channel");
        strictAssert.deepEqual(triggerFireOptionValues, ["", "1", "2", "3"]);
        strictAssert.deepEqual(triggerFireChannel.children.map((option) => option.textContent), ["None", "1", "2", "3"]);
        triggerFireChannel.value = "2";
        setLocale("zh-TW");
        refreshCommandFormPresentation();
        strictAssert.equal(byId(commandForm, "param-channel"), triggerFireIdentity);
        strictAssert.equal(triggerFireLabel.textContent, "中止目標通道");
        strictAssert.equal(triggerFireChannel.value, "2");
        strictAssert.deepEqual({
          input: triggerFireChannel.listeners.input.length,
          change: triggerFireChannel.listeners.change.length
        }, triggerFireListeners);
        strictAssert.deepEqual(triggerFireChannel.children.map((option) => option.value), triggerFireOptionValues);
        strictAssert.deepEqual(triggerFireChannel.children.map((option) => option.textContent), ["無", "1", "2", "3"]);
        const triggerFirePayload = parameterPayload();
        strictAssert.equal(triggerFirePayload.channel, 2);
        strictAssert.equal(Object.hasOwn(triggerFirePayload, "trigger_fire_channel"), false);
        setLocale("en");
        refreshCommandFormPresentation();
        strictAssert.equal(triggerFireLabel.textContent, "Abort target channel");
        strictAssert.equal(triggerFireChannel.children[0].textContent, "None");
        strictAssert.equal(triggerFireChannel.children[0].value, "");

        state.selected = "protection-set";
        renderForm("protection-set");
        const protectionOcp = byId(commandForm, "param-ocp");
        const protectionDelayTrigger = byId(commandForm, "param-ocp_delay_trigger");
        const protectionOcpValues = protectionOcp.children.map((option) => option.value);
        const protectionDelayValues = protectionDelayTrigger.children.map((option) => option.value);
        strictAssert.equal(protectionOcp.children[0].textContent, "None");
        strictAssert.equal(protectionOcp.children[0].value, "");
        strictAssert.equal(protectionDelayTrigger.children[0].textContent, "None");
        strictAssert.equal(protectionDelayTrigger.children[0].value, "");
        setLocale("zh-TW");
        refreshCommandFormPresentation();
        strictAssert.equal(protectionOcp.children[0].textContent, "無");
        strictAssert.equal(protectionDelayTrigger.children[0].textContent, "無");
        strictAssert.deepEqual(protectionOcp.children.map((option) => option.value), protectionOcpValues);
        strictAssert.deepEqual(protectionDelayTrigger.children.map((option) => option.value), protectionDelayValues);
        setLocale("en");

        state.selected = "apply";
        renderForm("apply");
        const applyChannel = byId(commandForm, "param-channel");
        setLocale("zh-TW");
        refreshCommandFormPresentation();
        strictAssert.equal(applyChannel.children[0].textContent, "全部");
        strictAssert.equal(applyChannel.children[0].value, "all");
        setLocale("en");

        const rampListHelp = "Each channel is enabled only after its first safe segment setpoint is written and verified. Outputs remain ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation.";
        state.selected = "ramp-list";
        state.rampListEnableOutput = true;
        renderForm("ramp-list");
        const editor = commandForm.children[0];
        const toolbar = byClass(editor, "ramp-list-toolbar")[0];
        const loadRampListButton = toolbar.children[0];
        const p4RampListTiming = byId(editor, "ramp-list-pulse-timing");
        const rampListTimingValues = p4RampListTiming.children.map((option) => option.value);
        const rampDraftInput = descendants(editor).find((node) => node.dataset.rampField === "start_voltage");
        rampDraftInput.value = "invalid draft";
        const rampDraftIdentity = rampDraftInput;
        setLocale("zh-TW");
        webuiWorkflows.refreshWorkflowPresentation(editor);
        strictAssert.equal(commandForm.children[0], editor);
        strictAssert.equal(toolbar.children[0], loadRampListButton);
        strictAssert.equal(loadRampListButton.textContent, "載入斜坡清單");
        strictAssert.equal(rampDraftInput, rampDraftIdentity);
        strictAssert.equal(rampDraftInput.value, "invalid draft");
        strictAssert.deepEqual(p4RampListTiming.children.map((option) => option.value), rampListTimingValues);
        strictAssert.deepEqual(p4RampListTiming.children.map((option) => option.textContent), ["無", "每個步驟", "區段完成", "迴圈完成"]);
        setLocale("en");
        webuiWorkflows.refreshWorkflowPresentation(editor);
        strictAssert.equal(loadRampListButton.textContent, "Load Ramp List");
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
        const invalidEditorIdentity = rerenderedEditor;
        const invalidEnableParts = {
          input: byId(rerenderedEditor, "ramp-list-enable-output"),
          label: byId(rerenderedEditor, "ramp-list-enable-output").parentNode,
          help: byId(rerenderedEditor, "ramp-list-enable-output-help")
        };
        const invalidSegmentIdentity = byClass(rerenderedEditor, "ramp-segment-card")[0];
        const invalidPulseIdentity = rerenderedTiming;
        const invalidLoopIdentity = rampListLoopCount;
        const invalidEnableChecked = invalidEnableParts.input.checked;
        const invalidEnableListeners = invalidEnableParts.input.listeners.change.length;
        setLocale("zh-TW");
        webuiWorkflows.refreshWorkflowPresentation(rerenderedEditor);
        strictAssert.equal(commandForm.children[0], invalidEditorIdentity);
        strictAssert.equal(byId(rerenderedEditor, "ramp-list-enable-output"), invalidEnableParts.input);
        strictAssert.equal(byId(rerenderedEditor, "ramp-list-enable-output-help"), invalidEnableParts.help);
        strictAssert.equal(byClass(rerenderedEditor, "ramp-segment-card")[0], invalidSegmentIdentity);
        strictAssert.equal(byId(rerenderedEditor, "ramp-list-loop-count"), invalidLoopIdentity);
        strictAssert.equal(byId(rerenderedEditor, "ramp-list-pulse-timing"), invalidPulseIdentity);
        strictAssert.equal(invalidEnableParts.input.checked, invalidEnableChecked);
        strictAssert.equal(invalidEnableParts.input.listeners.change.length, invalidEnableListeners);
        strictAssert.equal(rampListLoopCount.value, "1.5");
        strictAssert.equal(rerenderedTiming.value, "loop");
        strictAssert.equal(invalidEnableParts.label.querySelector(".checkbox-label-text").textContent, "啟用各通道");
        strictAssert.equal(invalidEnableParts.label.title, "各通道只會在第一個安全區段設定值寫入並驗證後啟用。正常完成後輸出會維持 ON。停止工作流程會關閉儀器的所有輸出。實機硬體仍需確認。");
        strictAssert.equal(invalidEnableParts.input.title, invalidEnableParts.label.title);
        strictAssert.equal(invalidEnableParts.input.getAttribute("aria-label"), "在各通道的第一個區段啟用通道");
        strictAssert.equal(invalidEnableParts.help.textContent, invalidEnableParts.label.title);
        setLocale("en");
        webuiWorkflows.refreshWorkflowPresentation(rerenderedEditor);
        strictAssert.equal(invalidEnableParts.input.getAttribute("aria-label"), "Enable each channel at its first segment");
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
    _index_html, app_js, styles_css = read_static_texts()
    jobs_js = read_static_javascript("jobs.js")

    assert 'const STOPPABLE_WORKFLOWS = new Set(["ramp", "ramp-list", "sequence"]);' in app_js
    assert 'webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`' in extract_js_function(
        app_js, "stopActiveWorkflow"
    )
    assert 'event.type === "cancel_requested"' in extract_js_function(jobs_js, "handleJobEvent")
    assert "button#run.workflow-stop" in styles_css

    run_frontend_javascript_assertions(
        r"""
        const strictAssert = require("node:assert/strict");
        const button = {
          textContent: "",
          title: "",
          disabled: false,
          attrs: {},
          classList: { toggle() {} },
          setAttribute(name, value) { this.attrs[name] = String(value); },
          getAttribute(name) { return this.attrs[name] ?? null; }
        };
        const guidance = { textContent: "", hidden: true };
        document.getElementById = (id) => id === "run" ? button : id === "command-guidance" ? guidance : null;
        let fetchCalls = 0;
        webuiApi.fetchJson = async () => { fetchCalls += 1; };

        const assertPhase = (phase, expectedText, expectedTitle, expectedGuidance = "") => {
          state.workflowControl = {
            phase,
            command: phase === "idle" ? null : "ramp",
            jobId: phase === "idle" || phase === "submitting" ? null : "job-raw"
          };
          const rawControl = state.workflowControl;
          refreshWorkflowOperationalPresentation();
          strictAssert.equal(state.workflowControl, rawControl);
          strictAssert.equal(button.textContent, expectedText);
          strictAssert.equal(button.title, expectedTitle);
          strictAssert.equal(button.attrs["aria-label"], expectedTitle || expectedText);
          if (expectedGuidance) {
            strictAssert.equal(guidance.textContent, expectedGuidance);
            strictAssert.equal(guidance.hidden, false);
          }
        };

        assertPhase("idle", "Run", "");
        assertPhase("submitting", "Starting...", "");
        assertPhase(
          "active",
          "Stop",
          "Stop the active workflow and safely turn all outputs off.",
          "Stop the active workflow and safely turn all outputs off."
        );
        assertPhase(
          "stopping",
          "Stopping...",
          "Stop the active workflow and safely turn all outputs off.",
          "Waiting for safe-off and cleanup"
        );

        const stoppingControl = state.workflowControl;
        setLocale("zh-TW");
        refreshWorkflowOperationalPresentation();
        strictAssert.equal(state.workflowControl, stoppingControl);
        strictAssert.equal(button.textContent, "正在停止...");
        strictAssert.equal(button.title, "停止作用中的工作流程，並安全關閉所有輸出。");
        strictAssert.equal(button.attrs["aria-label"], "停止作用中的工作流程，並安全關閉所有輸出。");
        strictAssert.equal(guidance.textContent, "正在等待安全關閉輸出與清理");
        strictAssert.equal(fetchCalls, 0);
        setLocale("en");
        """
    )


