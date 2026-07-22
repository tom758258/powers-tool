"""Static workflow, capability, workspace, and trigger WebUI tests."""

from __future__ import annotations

import re
import textwrap

from _webui_shared import (
    WEBUI_HIDDEN_LIVE_DATA_COMMANDS,
    assert_param_contract,
    extract_js_function,
    extract_param_block,
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
)

def test_static_pulse_child_fields_and_rear_pin_select_contracts():
    _index_html, app_js, styles_css = read_static_texts()
    sequence_document_js = read_static_javascript("sequence.js")
    command_form_js = read_static_javascript("command-form.js")
    workflows_js = read_static_javascript("workflows.js")

    cycle = extract_param_block(app_js, "cycle-output")
    ramp = extract_param_block(app_js, "ramp")
    trigger_pulse = extract_param_block(app_js, "trigger-pulse")
    trigger_list = extract_js_function(command_form_js, "triggerListParams")
    sequence_definitions = extract_js_function(workflows_js, "sequenceActionDefinitions")
    normalize_sequence = extract_js_function(sequence_document_js, "normalizeSequenceStep")

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
    assert "return webuiSequenceDocument.normalizeSequenceDocument(doc," in workflows_js
    assert "return webuiSequenceDocument.sequenceDocumentFromEditor(state," in workflows_js
    assert ".form-grid .pulse-child-field.visible { display: block; }" in styles_css
    assert "function updatePulseChildVisibility(command)" in command_form_js


def test_frontend_workflow_pulse_model_behavior_uses_canonical_ids() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const testElements = new Map([
          ["expected-model-id", { value: "" }],
          ["resource", { value: "" }],
          ["resource-select", { value: "", options: [{ textContent: "" }] }],
          ["device-resource-summary", { textContent: "", title: "" }]
        ]);
        document.getElementById = (id) => testElements.get(id) || { value: "" };

        const modelMetadata = [
          { model_id: "keysight-e36312a", model_name: "E36312A", display_name: "Keysight E36312A" },
          { model_id: "keysight-edu36311a", model_name: "EDU36311A", display_name: "Keysight EDU36311A" },
          { model_id: "keysight-e3646a", model_name: "E3646A", display_name: "Keysight E3646A" }
        ];
        const modelIds = modelMetadata.map((model) => model.model_id);
        state.physicalModels = modelMetadata;
        state.commands = { "trigger-pulse": { description: "Standalone trigger pulse" } };
        state.commandSupportByModel = Object.fromEntries(modelIds.map((modelId) => [modelId, {
          "trigger-pulse": { real: modelId === "keysight-e36312a" },
          probe: { marker: modelId }
        }]));
        state.channelCapabilitiesByModel = Object.fromEntries(modelIds.map((modelId) => [modelId, {
          channels: modelId === "keysight-e3646a" ? [1, 2] : [1, 2, 3],
          output_control_scope: modelId === "keysight-e3646a" ? "global" : "per_channel"
        }]));
        state.electricalRatingsByModel = Object.fromEntries(modelIds.map((modelId) => [modelId, {
          channels: [{ channel: 1, max_voltage: modelId === "keysight-e3646a" ? 20 : 6, max_current: 1 }]
        }]));

        function setExpected(modelId) {
          testElements.get("expected-model-id").value = modelId || "";
        }

        function setUndetectedResource(resource) {
          testElements.get("resource").value = resource;
          testElements.get("resource-select").value = resource;
          delete state.resourceModels[resource];
          delete state.resourceChannelModels[resource];
          delete state.resourceDisplayModels[resource];
        }

        function setDetectedResource(resource, modelId, reportedModel) {
          testElements.get("resource").value = resource;
          testElements.get("resource-select").value = resource;
          state.resourceModels[resource] = modelId && state.commandSupportByModel[modelId] ? modelId : null;
          state.resourceChannelModels[resource] = modelId && state.channelCapabilitiesByModel[modelId] ? modelId : null;
          state.resourceDisplayModels[resource] = reportedModel;
        }

        const workflowPulseRequests = {
          "cycle-output": { completion_pulse_pins: [1] },
          ramp: { completion_pulse_pins: [1] },
          "ramp-list": { document: { completion_pulse: { timing: "segment", pins: [1], polarity: "positive" } } },
          sequence: { document: { steps: [{ action: "trigger-pulse", pins: [1], polarity: "positive" }] } }
        };
        const workflowSurfaces = ["cycle-output", "ramp", "ramp-list", "sequence"];

        setExpected("keysight-e36312a");
        setUndetectedResource("USB0::EXPECTED::INSTR");
        strictAssert.equal(selectedCommandModel(), "keysight-e36312a");
        strictAssert.equal(selectedChannelModel(), "keysight-e36312a");
        strictAssert.equal(selectedElectricalRatingModel(), "keysight-e36312a");
        strictAssert.equal(selectedCommandSupport("probe").marker, "keysight-e36312a");
        strictAssert.equal(channelCapabilityForCurrentModel().channels.length, 3);
        strictAssert.equal(selectedChannelRatingFor("1").max_voltage, 6);
        strictAssert.equal(pulseControlsUnavailableReason(), "");
        for (const surface of workflowSurfaces) {
          const input = { disabled: true, title: "stale" };
          applyWorkflowPulseControlState(input);
          strictAssert.equal(input.disabled, false, `${surface} control should be enabled for E36312A`);
          strictAssert.equal(input.title, "");
          strictAssert.equal(workflowPulseGuardReason(surface, workflowPulseRequests[surface]), "");
        }
        strictAssert.equal(commandRequestsPulse("trigger-pulse", { pins: [1] }), false);
        strictAssert.notEqual(commandMeta("trigger-pulse").disabled, true);

        setExpected("");
        setDetectedResource("USB0::DETECTED::INSTR", "keysight-e36312a", "E36312A");
        strictAssert.equal(selectedChannelModel(), "keysight-e36312a");
        strictAssert.equal(pulseControlsUnavailableReason(), "");
        for (const surface of workflowSurfaces) {
          strictAssert.equal(workflowPulseGuardReason(surface, workflowPulseRequests[surface]), "");
        }

        for (const [modelId, displayName] of [
          ["keysight-edu36311a", "Keysight EDU36311A"],
          ["keysight-e3646a", "Keysight E3646A"]
        ]) {
          setExpected(modelId);
          setUndetectedResource(`USB0::${modelId}::INSTR`);
          const reason = pulseControlsUnavailableReason();
          strictAssert.match(reason, new RegExp(displayName));
          strictAssert.equal(reason.includes(modelId), false);
          const input = { disabled: false, title: "" };
          applyWorkflowPulseControlState(input);
          strictAssert.equal(input.disabled, true);
          strictAssert.equal(input.title, reason);
          for (const surface of workflowSurfaces) {
            strictAssert.equal(Boolean(workflowPulseGuardReason(surface, workflowPulseRequests[surface])), true);
          }
        }

        setExpected("");
        setDetectedResource("USB0::UNKNOWN::INSTR", null, "UNKNOWN");
        strictAssert.match(pulseControlsUnavailableReason(), /no supported model is selected or detected/);
        for (const surface of workflowSurfaces) {
          strictAssert.equal(Boolean(workflowPulseGuardReason(surface, workflowPulseRequests[surface])), true);
        }

        setExpected("keysight-e36312a");
        setDetectedResource("USB0::MISMATCH::INSTR", "keysight-edu36311a", "EDU36311A");
        const mismatchReason = pulseControlsUnavailableReason();
        strictAssert.match(mismatchReason, /Keysight E36312A/);
        strictAssert.match(mismatchReason, /Keysight EDU36311A/);
        strictAssert.equal(mismatchReason.includes("keysight-"), false);
        updateDeviceResourceSummary();
        strictAssert.match(testElements.get("device-resource-summary").title, /does not match/);

        setDetectedResource("USB0::MISMATCH::INSTR", "keysight-e36312a", "E36312A");
        updateDeviceResourceSummary();
        strictAssert.equal(testElements.get("device-resource-summary").title.includes("does not match"), false);
        strictAssert.equal(pulseControlsUnavailableReason(), "");

        setExpected("");
        setDetectedResource("USB0::SWITCH-A::INSTR", "keysight-e3646a", "E3646A");
        strictAssert.equal(Boolean(pulseControlsUnavailableReason()), true);
        setDetectedResource("USB0::SWITCH-B::INSTR", "keysight-e36312a", "E36312A");
        strictAssert.equal(selectedChannelModel(), "keysight-e36312a");
        strictAssert.equal(pulseControlsUnavailableReason(), "");
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_workflow_pulse_gates_do_not_compare_display_model_names() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")
    command_form_js = read_static_javascript("command-form.js")

    assert 'const REAR_TRIGGER_PULSE_MODEL_ID = "keysight-e36312a";' in app_js
    for display_name in ("E36312A", "EDU36311A", "E3646A"):
        assert not re.search(
            rf'(?:===|!==)\s*["\']{display_name}["\']|["\']{display_name}["\']\s*(?:===|!==)',
            app_js,
        )
    assert "applyWorkflowPulseControlState(input);" in extract_js_function(command_form_js, "renderForm")
    assert "applyWorkflowPulseControlState(input, prerequisiteReason);" in extract_js_function(workflows_js, "renderRampListForm")
    assert "applyWorkflowPulseControlState(input);" in extract_js_function(workflows_js, "sequenceStepFields")
    assert "workflowPulseGuardReason(state.selected, parameters)" in extract_js_function(app_js, "updateSelectedCommandState")
    assert 'command === "trigger-pulse"' not in extract_js_function(app_js, "commandRequestsPulse")


def test_static_frontend_uses_command_support_to_disable_unsupported_model_commands():
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")
    device_js = read_static_javascript("device-resource.js")
    command_meta = extract_js_function(command_support_js, "commandMeta")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")
    selected_command = extract_js_function(device_js, "selectedCommandModel")

    assert "const support = selectedCommandSupport(name);" in command_meta
    assert "support?.real === false" in command_meta
    assert "disabled: true" in command_meta
    assert "commandDisabledReason(support, selectedCommandModel())" in command_meta
    assert "runButton.disabled = Boolean(meta.disabled" in update_selected
    assert "state.commandSupportByModel?.[expected]" in selected_command


def test_static_frontend_policy_for_edu_and_e3646a_disabled_controls():
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")
    command_meta = extract_js_function(command_support_js, "commandMeta")
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
    result_summary_js = read_static_javascript("results.js")

    render_job_detail = app_js[app_js.index("async function renderJobDetail"):app_js.index("function shouldRefreshLiveAfterCommand")]

    assert "updateJobResult(job.job_id, job.status, webuiResults.jobSummary(job, event));" in render_job_detail
    assert "renderResult({" in render_job_detail
    assert 'if (command === "capabilities") return capabilitiesSummary(result);' in result_summary_js
    assert 'if (command === "identify") return identifySummary(result);' in result_summary_js
    assert 'if (command === "verify") return verifySummary(result);' in result_summary_js
    assert 'if (command === "read-status") return readStatusSummary(result);' in result_summary_js
    assert 'if (command === "readback") return readbackSummary(result);' in result_summary_js
    assert 'if (command === "snapshot") return snapshotSummary(result);' in result_summary_js
    assert 'if (command === "error") return errorQueueSummary(result, "instrument");' in result_summary_js
    assert 'if (command === "safety inspect") return safetyInspectSummary(result);' in result_summary_js
    assert "outputStatesSummary(result.outputs)" in result_summary_js
    assert "setpointSummary(channels)" in result_summary_js
    assert "result.resources.length" in result_summary_js


def test_static_workspace_summary_keeps_latest_success_by_complete_execution_context():
    index_html, app_js, _styles_css = read_static_texts()
    context_js = read_static_javascript("execution-context.js")
    state_js = read_static_javascript("state.js")
    workspace_js = read_static_javascript("results.js")

    capture = extract_js_function(app_js, "captureWorkspaceResult")
    render = extract_js_function(app_js, "renderWorkspaceSummary")
    current_context = extract_js_function(app_js, "currentWorkspaceResultContext")

    assert 'id="workspace-summary-content"' in index_html
    assert "workspaceResults: {}" in state_js
    assert "buildWorkspaceResultEntry(job, {" in capture
    assert "if (!entry) return false;" in capture
    assert "state.workspaceResults[entry.key] = entry.job;" in capture
    assert "currentWorkspaceResultContext(state.selected)" in render
    assert "findWorkspaceResult(state.workspaceResults, context)" in render
    assert '"Choose a command to view its latest successful result."' in render
    assert '"Run this command to see its latest successful result for the active execution context."' in render
    assert "webuiResults.renderWorkspaceJob(container, job, context, {" in render
    assert "renderCapabilitiesWorkspaceSummary(container, job.result, helpers);" in workspace_js
    assert "renderIdentifyWorkspaceSummary(container, job.result);" in workspace_js
    assert "captureWorkspaceResult(job);" in app_js
    assert "function buildWorkspaceResultKey(context)" not in app_js
    assert "function buildWorkspaceResultKey(context)" in context_js
    assert "function buildWorkspaceResultContextForJob(job, modelMaps = {})" in context_js
    assert "function buildCurrentWorkspaceResultContext(snapshot)" in context_js
    assert "function buildWorkspaceResultEntry(job, modelMaps = {})" in context_js
    assert "function findWorkspaceResult(workspaceResults, context)" in context_js
    assert "webuiContext.buildCurrentWorkspaceResultContext({" in current_context


def test_frontend_workspace_result_keys_isolate_complete_execution_context() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = new Map([
          ["resource", { value: "RESOURCE-A" }],
          ["expected-model-id", { value: "keysight-e36312a" }]
        ]);
        document.getElementById = (id) => elements.get(id) || null;
        state.livePanel = null;
        state.resourceLiveSupport = null;
        state.resourceLiveSupportContext = null;
        state.resourceModels = { "RESOURCE-A": "keysight-e36312a" };
        state.resourceChannelModels = { "RESOURCE-A": "keysight-e36312a" };

        const realJob = (resource, expected, modelId) => ({
          status: "finished",
          command: "identify",
          runtime: {
            resource,
            simulate: false,
            dry_run: false,
            ...(expected ? { expected_model_id: expected } : {})
          },
          result: { resource: { name: resource, model_id: modelId } }
        });
        const keyForJob = (job) => webuiContext.buildWorkspaceResultEntry(job, {
          commandModelByResource: state.resourceModels,
          channelModelByResource: state.resourceChannelModels
        }).key;

        state.executionMode = "real";
        const realA = realJob("RESOURCE-A", "keysight-e36312a", "keysight-e36312a");
        const realAKey = keyForJob(realA);
        strictAssert.equal(
          realAKey,
          webuiContext.buildWorkspaceResultKey(currentWorkspaceResultContext("identify")),
          "identical Real context must restore its result"
        );
        strictAssert.notEqual(realAKey, keyForJob(realJob("RESOURCE-B", "keysight-e36312a", "keysight-e36312a")));
        strictAssert.notEqual(realAKey, keyForJob(realJob("RESOURCE-A", "", "keysight-e36312a")));
        strictAssert.notEqual(realAKey, keyForJob(realJob("RESOURCE-A", "keysight-e36312a", "keysight-edu36311a")));

        state.executionMode = "simulate";
        elements.get("expected-model-id").value = "keysight-e36312a";
        const simulateA = {
          status: "finished",
          command: "identify",
          runtime: { resource: "PRESERVED-A", simulate: true, dry_run: false, planning_model_id: "keysight-e36312a" },
          result: {}
        };
        const simulateAWithOtherPreservedResource = {
          ...simulateA,
          runtime: { ...simulateA.runtime, resource: "PRESERVED-B" }
        };
        strictAssert.equal(keyForJob(simulateA), keyForJob(simulateAWithOtherPreservedResource));
        strictAssert.equal(keyForJob(simulateA), webuiContext.buildWorkspaceResultKey(currentWorkspaceResultContext("identify")));
        strictAssert.notEqual(keyForJob(simulateA), keyForJob({
          ...simulateA,
          runtime: { ...simulateA.runtime, planning_model_id: "keysight-edu36311a" }
        }));
        strictAssert.notEqual(realAKey, keyForJob(simulateA));

        state.executionMode = "dry-run";
        elements.get("expected-model-id").value = "profile:generic-scpi";
        const dryProfile = {
          status: "finished",
          command: "identify",
          runtime: { simulate: false, dry_run: true, planning_profile_id: "generic-scpi" },
          result: {}
        };
        strictAssert.equal(keyForJob(dryProfile), webuiContext.buildWorkspaceResultKey(currentWorkspaceResultContext("identify")));
        strictAssert.notEqual(keyForJob(dryProfile), keyForJob({
          ...dryProfile,
          runtime: { simulate: false, dry_run: true, planning_model_id: "keysight-e36312a" }
        }));
        strictAssert.notEqual(keyForJob(dryProfile), keyForJob(simulateA));
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_workspace_capture_keeps_helper_and_lifecycle_boundaries() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        state.workspaceResults = Object.create(null);
        state.resourceModels = { "RESOURCE-A": "keysight-e36312a" };
        state.resourceChannelModels = { "RESOURCE-A": "keysight-edu36311a" };
        const liveSupportCalls = [];
        const renderCalls = [];
        captureResourceLiveSupport = (job, resource) => {
          liveSupportCalls.push({ job, resource });
          return true;
        };
        renderWorkspaceSummary = () => renderCalls.push("rendered");
        const jobFor = (command, result = { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } }) => ({
          status: "finished",
          command,
          runtime: {
            resource: "RESOURCE-A",
            simulate: false,
            dry_run: false,
            expected_model_id: "keysight-e36312a"
          },
          result
        });

        for (const invalidJob of [
          null,
          undefined,
          { ...jobFor("set"), status: "failed" },
          { ...jobFor("set"), status: "cancelled" },
          { ...jobFor("set"), command: "" },
          { ...jobFor("set"), result: null }
        ]) {
          strictAssert.equal(captureWorkspaceResult(invalidJob), false);
        }
        strictAssert.deepEqual(Reflect.ownKeys(state.workspaceResults), []);
        strictAssert.deepEqual(liveSupportCalls, []);
        strictAssert.deepEqual(renderCalls, []);

        const first = jobFor("set", {});
        const firstBefore = JSON.parse(JSON.stringify(first));
        strictAssert.equal(captureWorkspaceResult(first), true);
        const firstEntry = webuiContext.buildWorkspaceResultEntry(first, {
          commandModelByResource: state.resourceModels,
          channelModelByResource: state.resourceChannelModels
        });
        strictAssert.strictEqual(state.workspaceResults[firstEntry.key], first);
        strictAssert.deepEqual(first, firstBefore);
        strictAssert.deepEqual(renderCalls, ["rendered"]);

        const later = jobFor("set", { marker: "later" });
        strictAssert.equal(captureWorkspaceResult(later), true);
        strictAssert.strictEqual(state.workspaceResults[firstEntry.key], later);
        strictAssert.deepEqual(renderCalls, ["rendered", "rendered"]);

        for (const command of ["capabilities", "identify", "verify"]) {
          const job = jobFor(command);
          strictAssert.equal(captureWorkspaceResult(job), true);
          strictAssert.strictEqual(liveSupportCalls.at(-1).job, job);
          strictAssert.equal(liveSupportCalls.at(-1).resource, "RESOURCE-A");
        }
        const liveSupportCount = liveSupportCalls.length;
        strictAssert.equal(captureWorkspaceResult(jobFor("trigger-status")), true);
        strictAssert.equal(liveSupportCalls.length, liveSupportCount);
        strictAssert.equal(renderCalls.length, 6);
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_execution_mode_transition_refreshes_selected_context_once() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        (async () => {

        class FakeClassList {
          add() {}
          toggle() {}
        }

        class FakeSelect {
          constructor(value = "") {
            this.value = value;
            this.options = [];
            this.children = [];
            this.classList = new FakeClassList();
          }
          replaceChildren() {
            this.value = "";
            this.options = [];
            this.children = [];
          }
          add(option) {
            this.options.push(option);
            this.children.push(option);
          }
          append(...children) {
            this.children.push(...children);
            children.forEach((child) => this.options.push(...(child.children || [])));
          }
        }

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

        const createControl = (value = "") => ({
          value,
          checked: false,
          disabled: false,
          hidden: false,
          title: "",
          textContent: "",
          className: "",
          classList: new FakeClassList(),
          parentElement: { hidden: false },
          firstChild: { textContent: "" }
        });
        const identity = new FakeSelect("keysight-e36312a");
        const elements = new Map([
          ["expected-model-id", identity],
          ["resource", createControl("RESOURCE-REAL")],
          ["resource-select", new FakeSelect("RESOURCE-REAL")],
          ["real-write-enabled", createControl()],
          ["execution-mode-badge", createControl()],
          ["execution-mode-help", createControl()],
          ["identity-model-label", createControl()],
          ["device-resource-summary", createControl()],
          ["command-form", createControl()],
          ["workspace-summary-content", createControl()]
        ]);
        ["scan", "live-start", "serial-baud-rate", "serial-data-bits", "serial-parity", "serial-stop-bits", "serial-flow-control", "serial-read-termination", "serial-write-termination", "serial-remote", "serial-local-on-close"].forEach((id) => elements.set(id, createControl()));
        const radios = ["real", "simulate", "dry-run"].map((value) => ({ value, checked: value === "real", disabled: false, title: "" }));

        globalThis.Option = function Option(text, value) { return { textContent: text, value: String(value) }; };
        document.getElementById = (id) => elements.get(id) || null;
        document.createElement = () => ({ children: [], append(...children) { this.children.push(...children); } });
        document.querySelectorAll = (selector) => selector === 'input[name="execution-mode"]' ? radios : [];
        document.querySelector = (selector) => {
          const match = selector.match(/\[value="([^"]+)"\]/);
          return match ? radios.find((radio) => radio.value === match[1]) || null : null;
        };

        state.executionMode = "real";
        state.executionModeTransition = false;
        state.workflowControl = { phase: "idle" };
        state.basicActionStates = {};
        state.jobs = [];
        state.selected = "set";
        state.realIdentityCache = { expectedModelId: "keysight-e36312a" };
        state.planningIdentityCache = { simulate: "keysight-e3646a", "dry-run": "profile:generic-scpi" };
        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-e3646a", display_name: "Keysight E3646A" }
        ];
        state.planningProfiles = {
          "generic-scpi": { profile_id: "generic-scpi", display_name: "Generic SCPI" }
        };
        state.parameterConstraints = {
          voltage: { min: 0, max: 100, step: 0.1, description: "Generic voltage guidance" }
        };
        state.electricalRatingsByModel = {
          "keysight-e36312a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }] },
          "keysight-e3646a": { channels: [{ channel: 1, max_voltage: 20, max_current: 1 }] }
        };
        state.resourceModels = { "RESOURCE-REAL": "keysight-e3646a" };
        state.resourceChannelModels = { "RESOURCE-REAL": "keysight-e3646a" };
        state.livePanel = null;
        state.workspaceResults = {};

        const realJob = {
          status: "finished",
          command: "set",
          runtime: { resource: "RESOURCE-REAL", simulate: false, dry_run: false, expected_model_id: "keysight-e36312a" },
          result: { resource: { name: "RESOURCE-REAL", model_id: "keysight-e3646a" } }
        };
        const realKey = webuiContext.buildWorkspaceResultEntry(realJob, {
          commandModelByResource: state.resourceModels,
          channelModelByResource: state.resourceChannelModels
        }).key;
        state.workspaceResults[realKey] = { marker: "real" };

        const selectedCalls = [];
        const formLimits = [];
        const workspaceViews = [];
        const clientFailures = [];
        stopRealLiveJobsAndWait = async () => {};
        renderBlankLivePanel = () => {};
        renderClientResult = (...args) => clientFailures.push(args);
        updateDeviceResourceSummary = () => {};
        syncBasicFromLivePanel = () => {};
        renderCommands = () => {};
        selectCommand = (name) => {
          selectedCalls.push(name);
          const input = new FakeInput();
          refreshInputElectricalConstraints(input, "voltage");
          formLimits.push({ mode: state.executionMode, max: input.max, title: input.title });
          const context = currentWorkspaceResultContext(name);
          workspaceViews.push({ context, marker: webuiContext.findWorkspaceResult(state.workspaceResults, context)?.marker || null });
        };
        renderWorkspaceSummary = () => {
          const context = currentWorkspaceResultContext(state.selected);
          workspaceViews.push({ context, marker: webuiContext.findWorkspaceResult(state.workspaceResults, context)?.marker || null });
        };

        await handleExecutionModeChange({ target: radios[1] });
        strictAssert.equal(identity.value, "keysight-e3646a");
        strictAssert.deepEqual(formLimits.at(-1), { mode: "simulate", max: "20", title: "Official independent-channel DC output rating: maximum 20 V." });
        strictAssert.equal(workspaceViews.at(-1).context.executionMode, "simulate");
        strictAssert.equal(workspaceViews.at(-1).marker, null, "Simulate must not show the Real result");

        const simulateContext = currentWorkspaceResultContext("set");
        state.workspaceResults[webuiContext.buildWorkspaceResultKey(simulateContext)] = { marker: "simulate" };
        await handleExecutionModeChange({ target: radios[2] });
        strictAssert.equal(identity.value, "profile:generic-scpi");
        strictAssert.deepEqual(formLimits.at(-1), { mode: "dry-run", max: "100", title: "Generic voltage guidance" });
        strictAssert.equal(workspaceViews.at(-1).context.executionMode, "dry-run");
        strictAssert.equal(workspaceViews.at(-1).marker, null, "Dry-run must not show the Simulate result");

        await handleExecutionModeChange({ target: radios[0] });
        strictAssert.equal(identity.value, "keysight-e36312a");
        strictAssert.deepEqual(formLimits.at(-1), { mode: "real", max: "6", title: "Official independent-channel DC output rating: maximum 6 V." });
        const realContext = workspaceViews.at(-1).context;
        strictAssert.equal(realContext.resource, "RESOURCE-REAL");
        strictAssert.equal(realContext.expectedModelGuard, "keysight-e36312a");
        strictAssert.equal(realContext.canonicalModelId, "keysight-e3646a");
        strictAssert.notEqual(realContext.expectedModelGuard, realContext.canonicalModelId);
        strictAssert.equal(workspaceViews.at(-1).marker, "real");
        strictAssert.equal(webuiContext.buildWorkspaceResultKey(realContext), realKey);
        strictAssert.deepEqual(selectedCalls, ["set", "set", "set"]);

        state.liveJobId = "live-stop-failure";
        webuiApi.fetchJson = async () => { throw new Error("Live stop failed"); };
        await handleExecutionModeChange({ target: radios[1] });
        strictAssert.equal(state.executionMode, "real");
        strictAssert.deepEqual(selectedCalls, ["set", "set", "set"]);
        strictAssert.equal(clientFailures.length, 1);
        })().catch((error) => {
          console.error(error);
          process.exitCode = 1;
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_workspace_capabilities_and_identify_use_result_fields():
    _index_html, app_js, _styles_css = read_static_texts()
    workspace_js = read_static_javascript("results.js")

    capabilities = extract_js_function(workspace_js, "renderCapabilitiesWorkspaceSummary")
    identify = extract_js_function(workspace_js, "renderIdentifyWorkspaceSummary")

    for field in ("model", "resource", "channels", "measure_channels", "command_support", "models"):
        assert field in capabilities
    assert "featureAvailability(" in capabilities
    assert "details.channels.length" in capabilities
    for field in ("manufacturer", "model", "serial", "firmware", "options", "scpi_version", "resource"):
        assert field in identify


def test_static_command_keys_are_used_for_selection_and_submission():
    _index_html, app_js, _styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")

    render_commands = command_form_js[command_form_js.index("function renderCommands()"):command_form_js.index("function selectCommand")]

    assert "Object.entries(state.commands)" in render_commands
    assert "<span>${commandDisplayName(name)}</span>" in render_commands
    assert "button.addEventListener(\"click\", () => selectCommand(name));" in render_commands
    assert "command: state.selected" in app_js
    assert "renderForm(name);" in command_form_js
    assert "selectCommand(commandDisplayName(name))" not in app_js


def test_static_command_display_names_preserve_machine_command_keys():
    _index_html, app_js, _styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")

    render_commands = command_form_js[command_form_js.index("function renderCommands()"):command_form_js.index("function selectCommand")]

    assert 'name.includes(filter) || commandDisplayName(name).toLowerCase().includes(filter)' in render_commands
    assert 'commandDisplayName(a[0]).localeCompare(commandDisplayName(b[0]))' in render_commands


def test_static_command_select_options_use_human_labels_and_machine_values():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")
    command_form_js = read_static_javascript("command-form.js")

    render_form = extract_js_function(command_form_js, "renderForm")
    render_restore = extract_js_function(workflows_js, "renderRestoreForm")
    display_name = extract_js_function(command_form_js, "optionDisplayName")

    assert "item.value = option;" in render_form
    assert 'item.textContent = param.parser === "intList"' in render_form
    assert '? rearPinDisplayName(option)' in render_form
    assert ': pulseTimingDisplayName(command, option);' in render_form
    assert "opt.value = ch;" in render_restore
    assert "opt.textContent = optionDisplayName(ch);" in render_restore
    assert 'value.replace(/-/g, " ")' in display_name
    assert 'return `Pin ${value}`' not in display_name


def test_frontend_loop_document_round_trips_use_external_schemas() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        state.commands.sequence = { max_steps: 250 };

        const v1 = normalizeSequenceDocument({
          version: 1,
          steps: [{ action: "wait", seconds: 0 }]
        });
        strictAssert.equal(v1.loopCount, 1);
        const v2 = normalizeSequenceDocument({
          version: 2,
          loop_count: 4,
          steps: [{ action: "wait", seconds: 0 }]
        });
        strictAssert.equal(v2.loopCount, 4);
        strictAssert.throws(
          () => normalizeSequenceDocument({ version: 2, steps: [{ action: "wait", seconds: 0 }] }),
          /loop_count/
        );
        strictAssert.throws(
          () => normalizeSequenceDocument({ version: 1, loop_count: 2, steps: [{ action: "wait", seconds: 0 }] }),
          /unsupported fields/
        );

        state.sequenceLoopEnabled = true;
        state.sequenceLoopCountDraft = "4";
        state.sequenceSteps = [{ action: "wait", seconds: 0 }];
        const serialized = sequenceDocumentFromEditor();
        strictAssert.deepEqual(Object.keys(serialized), ["version", "loop_count", "steps"]);
        strictAssert.equal(serialized.version, 2);
        strictAssert.equal(serialized.loop_count, 4);
        strictAssert.equal(Object.hasOwn(serialized, "loopCount"), false);

        state.rampListEnableOutput = false;
        state.rampListLoopEnabled = false;
        state.rampListLoopCountDraft = "2";
        state.rampListCompletionPulse = null;
        state.rampListSegments = [{
          channel: 1, current: 0.1, start_voltage: 0, stop_voltage: 1,
          step_voltage: 1, delay_ms: 0, hold_ms: 0
        }];
        const rampList = rampListDocument();
        strictAssert.equal(rampList.version, 4);
        strictAssert.equal(rampList.loop_count, 1);
        strictAssert.equal(validateRampListDocument({
          kind: "powers-tool-ramp-list",
          version: 2,
          segments: rampList.segments
        }).loopCount, 1);
        strictAssert.equal(validateRampListDocument(rampList).loopCount, 1);
        strictAssert.throws(
          () => validateRampListDocument({ ...rampList, completion_pulse: { timing: "loop", pins: [1], polarity: "positive" } }),
          /requires loop_count of at least 2/
        );
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_invalid_enabled_loop_counts_disable_run_and_save_without_serializing() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = {
          "save-ramp-list": { disabled: false },
          "save-sequence": { disabled: false }
        };
        document.getElementById = (id) => elements[id] || null;
        state.rampListEnableOutput = false;
        state.rampListCompletionPulse = null;
        state.rampListSegments = [{
          channel: 1, current: 0.1, start_voltage: 0, stop_voltage: 1,
          step_voltage: 1, delay_ms: 0, hold_ms: 0
        }];
        state.sequenceSteps = [{ action: "wait", seconds: 0 }];
        let saveCalls = 0;
        let serializedNullLoopCount = false;
        saveJsonFile = async () => { saveCalls += 1; };
        renderClientResult = () => {};
        const originalStringify = JSON.stringify;
        JSON.stringify = (value, ...args) => {
          const serialized = originalStringify(value, ...args);
          if (serialized?.includes('"loop_count": null')) serializedNullLoopCount = true;
          return serialized;
        };

        (async () => {
          for (const invalid of ["", "1.5", "1", "0", "-1", "256"]) {
            state.rampListLoopEnabled = true;
            state.rampListLoopCountDraft = invalid;
            const rampRun = { disabled: false };
            strictAssert.equal(updateWorkflowDocumentValidity("ramp-list", rampRun), false);
            strictAssert.equal(rampRun.disabled, true);
            strictAssert.equal(elements["save-ramp-list"].disabled, true);
            await saveRampList();

            state.sequenceLoopEnabled = true;
            state.sequenceLoopCountDraft = invalid;
            const sequenceRun = { disabled: false };
            strictAssert.equal(updateWorkflowDocumentValidity("sequence", sequenceRun), false);
            strictAssert.equal(sequenceRun.disabled, true);
            strictAssert.equal(elements["save-sequence"].disabled, true);
            await saveSequenceFile();
          }
          strictAssert.equal(saveCalls, 0);
          strictAssert.equal(serializedNullLoopCount, false);
        })().catch((error) => {
          process.nextTick(() => { throw error; });
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_snapshot_has_no_sequence_loop_state_or_control() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")
    snapshot = extract_js_function(workflows_js, "renderSnapshotForm")
    sequence = extract_js_function(workflows_js, "renderSequenceForm")

    assert "loop" not in snapshot.lower()
    assert "sequenceLoopCount" not in snapshot
    assert sequence.index("editor.appendChild(toolbar)") < sequence.index("renderLoopControl({")
    assert sequence.index("renderLoopControl({") < sequence.index("state.sequenceSteps.forEach")


def test_static_commands_disable_by_selected_resource_model():
    _index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    command_support_js = read_static_javascript("command-support.js")
    command_form_js = read_static_javascript("command-form.js")
    device_js = read_static_javascript("device-resource.js")

    assert "commandSupportByModel: {}" in state_js
    assert "channelCapabilitiesByModel: {}" in state_js
    assert "resourceModels: {}" in state_js
    assert "resourceChannelModels: {}" in state_js
    assert "state.commandSupportByModel = payload.command_support_by_model_id || {};" in command_form_js
    assert "state.channelCapabilitiesByModel = payload.channel_capabilities_by_model_id || {};" in command_form_js
    assert "updateResourceModels(resources);" in app_js
    assert "resource.model_id" in app_js
    assert "function selectedCommandModel()" in device_js
    assert "function detectedCommandModelForResource(resource)" in device_js
    assert "state.commandSupportByModel?.[model]?.[name]" in command_support_js
    assert "const model = selectedCommandModel();" in extract_js_function(command_support_js, "selectedCommandSupport")
    assert "const next = supportedModelKey(modelId);" in app_js
    assert "!next.stale && updateResourceModel(next.resource, next.model_id, next.model)" in app_js
    assert "support?.real === false" in command_support_js
    assert 'button.disabled = Boolean(effectiveMeta.disabled || state.workflowControl.phase !== "idle");' in command_form_js
    assert "runButton.disabled = Boolean(meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard || workflowPulseGuard);" in app_js
    assert 'error: "Command unavailable"' in app_js


def test_static_frontend_consumes_exact_live_support_without_exposing_validation_controls():
    index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    basic_controls_js = read_static_javascript("basic-controls.js")
    command_support_js = read_static_javascript("command-support.js")
    command_form_js = read_static_javascript("command-form.js")
    device_js = read_static_javascript("device-resource.js")
    load_commands = extract_js_function(command_form_js, "loadCommands")
    command_meta = extract_js_function(command_support_js, "commandMeta")
    capture_support = extract_js_function(app_js, "captureResourceLiveSupport")
    capture_workspace = extract_js_function(app_js, "captureWorkspaceResult")
    clear_stale = extract_js_function(app_js, "clearStaleResourceLiveSupport")
    update_model = extract_js_function(app_js, "updateResourceModel")
    model_changed = extract_js_function(device_js, "handleExpectedModelChanged")
    runtime_payload = extract_js_function(command_form_js, "runtimePayload")
    render_basic = extract_js_function(basic_controls_js, "renderBasicChannelActionState")
    render_basic_output = extract_js_function(basic_controls_js, "renderBasicOutputControlState")

    assert "liveSupportByModel: {}" in state_js
    assert "resourceLiveSupport: null" in state_js
    assert "resourceLiveSupportContext: null" in state_js
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
    assert "commandSupport.offline_only" in command_support_js
    assert "Offline utility; live exact scope is not applicable." in command_support_js
    assert "Connection scope not evaluated" in command_meta
    assert "Pending live validation:" in command_support_js
    assert "No product-open live scope is registered" in command_support_js
    assert "Identity/status diagnostic; exact model feature scope is not required." in command_support_js
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
    command_support_js = read_static_javascript("command-support.js")
    device_js = read_static_javascript("device-resource.js")
    command_form_js = read_static_javascript("command-form.js")

    assert "const DEFAULT_CHANNELS = [1, 2, 3];" in app_js
    assert "function supportedChannelsForCurrentModel()" in command_support_js
    assert "if (!capability || !capability.channels.length) return [...defaultChannels];" in command_support_js
    assert "function channelCapabilityForCurrentModel()" in command_support_js
    assert "function channelCapabilityForModel(model)" in command_support_js
    assert "function selectedChannelModel()" in device_js
    assert "function detectedChannelModelForResource(resource)" in device_js
    assert "metadata.channels" in command_support_js
    assert "metadata.output_control_scope" in command_support_js
    assert "Array.isArray(metadata)" in command_support_js
    assert "? modelId : null" in extract_js_function(command_support_js, "supportedModelKey")
    assert "function currentChannelCapabilityModel()" in command_support_js
    assert "return selectedChannelModel();" in extract_js_function(command_support_js, "currentChannelCapabilityModel")
    assert "function channelModelKey(model)" in command_support_js
    assert "state.resourceChannelModels[resource] = nextChannelModel;" in app_js
    assert "channelAvailabilityGuardReason(state.selected, parameters)" in app_js
    assert "channelAvailabilityGuardReason(state.selected, payload.parameters)" in app_js
    assert "item.disabled = true;" in command_form_js
    assert "channelUnsupportedReason(option)" in command_form_js
    assert 'error: "Unsupported channel"' in app_js
    assert ".basic-channel-card.unsupported" in styles_css
    assert ".live-card.unsupported" in styles_css


def test_static_basic_and_live_disable_unsupported_channels():
    _index_html, app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")

    run_set = extract_js_function(app_js, "runBasicSet")
    run_output = extract_js_function(app_js, "runBasicOutput")
    render_live = extract_js_function(app_js, "renderChannelCard")
    render_basic = extract_js_function(basic_controls_js, "renderBasicChannelActionState")
    all_on = extract_js_function(basic_controls_js, "basicAllOutputsOn")
    clear_errors = extract_js_function(basic_controls_js, "clearResolvedBasicErrors")

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
    command_support_js = read_static_javascript("command-support.js")

    output_title = extract_js_function(command_support_js, "outputControlTitle")
    all_title = extract_js_function(command_support_js, "outputAllControlTitle")

    assert 'outputControlScopeForCurrentModel() === "global"' in output_title
    assert 'outputControlScopeForCurrentModel() === "global"' in all_title
    assert "globalOutputHintText()" in output_title
    assert "globalOutputHintText()" in all_title
    assert 'model === "E3646A"' not in output_title
    assert 'model === "E3646A"' not in all_title
    assert "function outputControlScopeForCurrentModel()" in command_support_js
    assert "output_control_scope" in extract_js_function(command_support_js, "outputControlScopeForCurrentModel")
    assert "output enable is global for supported channels." in extract_js_function(command_support_js, "globalOutputHintText")


def test_static_trip_guard_and_clear_protection_recovery_contract():
    _index_html, app_js, _styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")

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
    assert 'const stateText = tripped === true ? "TRIP" : tripped === false ? "CLEAR" : "--";' in live_data_js


def test_static_channel_confirmation_and_job_detail_contracts():
    _index_html, app_js, styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")
    workflows_js = read_static_javascript("workflows.js")

    assert 'set: webuiCommandForm.setOutputParams()' in app_js
    assert 'export function setOutputParams()' in command_form_js
    assert "{ ...params[1], optional: true }" in command_form_js
    assert "{ ...params[2], optional: true }" in command_form_js
    assert "const SET_PARTIAL_GUIDANCE =" in command_form_js
    render_form = extract_js_function(command_form_js, "renderForm")
    append_set_guidance = extract_js_function(command_form_js, "appendSetGuidance")
    render_guidance = extract_js_function(command_form_js, "renderCommandGuidance")
    assert 'if (command === "set" && param.name === "current") appendSetGuidance(label);' in render_form
    assert 'guidance.className = "field-description set-field-guidance";' in append_set_guidance
    assert "guidance.textContent = SET_PARTIAL_GUIDANCE;" in append_set_guidance
    assert "SET_PARTIAL_GUIDANCE" not in render_guidance
    field_description_css = styles_css[styles_css.index(".field-description {"):styles_css.index(".command-notes {")]
    assert "text-transform: none;" in field_description_css
    assert "setRequiresSetpointGuardReason(state.selected, parameters)" in app_js
    assert '"smoke-output": webuiCommandForm.smokeOutputParams()' in app_js
    assert_param_contract(app_js, "channel", "select", ["1", "2", "3"])
    assert_param_contract(workflows_js, "voltage", "number")
    assert_param_contract(workflows_js, "current", "number")
    assert_param_contract(workflows_js, "no_output", "checkbox")
    assert_param_contract(workflows_js, "duration_ms", "number")
    for command in ("output-on", "output-off", "cycle-output"):
        assert_param_contract(extract_param_block(app_js, command), "channel", "select", ["all", "1", "2", "3"])
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function defaultRampSegment()")]
    assert '"protection-set"' in params_block
    protection_block = extract_param_block(app_js, "protection-set")
    assert_param_contract(protection_block, "ocp_delay", "number")
    assert_param_contract(protection_block, "ocp_delay_trigger", "select", ["", "setting-change", "cc-transition"])
    for command in WEBUI_HIDDEN_LIVE_DATA_COMMANDS:
        assert f'"{command}"' not in params_block

    assert 'if (param.name === "channel")' in command_form_js
    assert 'if (param.parser === "intList")' in command_form_js
    assert 'if (param.parser === "numberList")' in command_form_js
    assert 'if (value === "all") return value;' in command_form_js
    assert 'return /^[1-9]\\d*$/.test(value) ? Number(value) : value;' in command_form_js

    assert "const meta = commandMeta(state.selected);" in app_js
    assert "meta.requires_confirm && state.executionMode === \"real\" && !payload.runtime.confirm" in app_js
    assert 'error: "Confirmation required"' in app_js
    assert "runtime: { confirm: false }" in app_js

    assert "const job = await webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);" in app_js
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
    command_form_js = read_static_javascript("command-form.js")
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function defaultRampSegment()")]

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
    assert_param_contract(command_form_js, "voltage_list", "text")
    assert_param_contract(command_form_js, "current_list", "text")
    assert_param_contract(command_form_js, "dwell_list", "text")
    assert 'parser: "numberList"' in command_form_js
    assert_param_contract(extract_js_function(command_form_js, "triggerListParams"), "completion_pulse_pins", "select")
    assert_param_contract(extract_js_function(command_form_js, "triggerStepParams"), "source", "select", ["bus", "immediate"])
    assert_param_contract(extract_js_function(command_form_js, "triggerListParams"), "source", "select", ["bus", "immediate"])
    assert_param_contract(command_form_js, "wait_timeout_ms", "number")
    assert_param_contract(command_form_js, "leave_trigger_configured", "checkbox")


def test_static_trigger_forms_document_behavior_and_key_fields():
    _index_html, app_js, styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")

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
        "trigger-step": extract_js_function(command_form_js, "triggerStepParams"),
        "trigger-list": extract_js_function(command_form_js, "triggerListParams"),
        "trigger-fire": extract_param_block(app_js, "trigger-fire"),
        "trigger-abort": extract_param_block(app_js, "trigger-abort"),
    }
    for command, summary in summaries.items():
        assert summary in blocks[command]
        assert "description:" in blocks[command]

    for field in ("source", "fire", "wait_complete", "poll_ms", "wait_timeout_ms",
                  "exclusive_pins", "leave_trigger_configured"):
        field_start = command_form_js.index(f'name: "{field}"')
        assert "description:" in command_form_js[field_start:field_start + 500]
    for field in ("voltage_list", "current_list", "dwell_list", "count", "completion_pulse_pins"):
        assert f'name: "{field}"' in blocks["trigger-list"]
        field_start = blocks["trigger-list"].index(f'name: "{field}"')
        assert "description:" in blocks["trigger-list"][field_start:field_start + 450]

    assert "pin1" not in extract_js_function(command_form_js, "triggerStepParams")
    assert "pin1" not in extract_js_function(command_form_js, "triggerListParams")
    assert 'label: "Abort target channel"' in blocks["trigger-fire"]
    assert "It does not turn outputs off" in blocks["trigger-abort"]
    assert "instrument error-queue entries" in blocks["trigger-abort"]

    render_form = extract_js_function(command_form_js, "renderForm")
    command_form_js = read_static_javascript("command-form.js")
    append_notes = extract_js_function(command_form_js, "appendCommandNotes")
    assert "if (!TRIGGER_COMMANDS.has(command) && !param.compactHelp) appendFieldDescription(label, param);" in render_form
    assert "if (TRIGGER_COMMANDS.has(command)) appendCommandNotes(form, command, PARAMS[command] || [], commandMeta);" in render_form
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
    workflows_js = read_static_javascript("workflows.js")

    definitions = extract_js_function(workflows_js, "sequenceActionDefinitions")
    sequence_fields = extract_js_function(workflows_js, "sequenceStepFields")

    assert 'name: "leave_trigger_configured"' in definitions
    assert "It does not keep a trigger armed." in definitions
    assert "may affect later Sequence steps or other BUS triggers" in definitions
    assert "webuiCommandForm.appendFieldDescription(label, definition);" in sequence_fields
    assert ".sequence-step-fields .checkbox-field" not in styles_css
    assert ".form-grid .checkbox-field .field-description" in styles_css


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

    guidance = extract_js_function(read_static_javascript("command-form.js"), "renderCommandGuidance")
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
    workspace_js = read_static_javascript("results.js")

    render = extract_js_function(app_js, "renderWorkspaceSummary")
    summary = extract_js_function(workspace_js, "renderTriggerStatusWorkspaceSummary")

    assert "webuiResults.renderWorkspaceJob(container, job, context, {" in render
    assert "renderTriggerStatusWorkspaceSummary(container, job.result, helpers.formatNum);" in workspace_js
    for field in ("digital_pins", "trigger_output_bus_enabled", "triggered_voltage", "triggered_current", "step_mode", "terminate_last"):
        assert field in summary


def test_static_trigger_list_uses_three_channel_workspace_editor():
    _index_html, app_js, styles_css = read_static_texts()
    trigger_list_js = read_static_javascript("trigger-list.js")
    workflows_js = read_static_javascript("workflows.js")
    command_form_js = read_static_javascript("command-form.js")

    render = extract_js_function(workflows_js, "renderTriggerListForm")
    payload = extract_js_function(command_form_js, "parameterPayload")
    validator = extract_js_function(trigger_list_js, "validateTriggerListWorkspace")

    for text in ("Load Trigger List", "Save Trigger List", "Add Step", "Channel ${channel}", "BOST", "EOST"):
        assert text in render
    assert "button.dataset.triggerListChannel = String(channel);" in render
    assert "steps.push({ ...steps[steps.length - 1] })" in workflows_js
    assert "steps.length >= 100" in workflows_js
    assert "steps.length <= 1" in workflows_js
    assert 'if (input.type === "number") input.step = "any";' in workflows_js
    for field in ("bost_list", "eost_list", "trigger_output_pins", "trigger_output_polarity"):
        assert field in payload
    assert "powers-tool-trigger-list-workspace" in validator
    assert 'exact(document.channels, ["1", "2", "3"]' in validator
    assert "contains unknown or missing fields" in validator
    assert "return webuiTriggerListDocument.triggerListWorkspaceDocument(state);" in workflows_js
    assert "return webuiTriggerListDocument.validateTriggerListWorkspace(document);" in workflows_js
    assert ".trigger-list-editor {" in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="1"]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="2"]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="3"]' in styles_css


def test_static_trigger_list_documents_restore_and_pulse_pin_guard():
    _index_html, app_js, _styles_css = read_static_texts()

    guidance = extract_js_function(read_static_javascript("command-form.js"), "renderCommandGuidance")
    guard = extract_js_function(app_js, "triggerControlGuardReason")

    assert "writes back the pre-run Trigger settings and LIST table" in guidance
    assert "select Leave configured to retain the new LIST table" in guidance
    assert "BOST/EOST pulses require LIST output pins." in guard

