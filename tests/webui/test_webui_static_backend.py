"""No-hardware backend selection, transition, and stale-result contracts."""

from __future__ import annotations

import json

from _webui_shared import (
    FAKE_DOM_PRIMITIVES,
    run_frontend_javascript_assertions,
    run_webui_module_assertions,
)


def test_backend_transition_preserves_drafts_revokes_writes_and_routes_real_requests():
    run_frontend_javascript_assertions(
        FAKE_DOM_PRIMITIVES + r"""
const strictAssert = require("node:assert/strict");
(async () => {
const elements = new Map();
function control(id) {
  if (!elements.has(id)) {
    const node = new FakeElement();
    node.replaceChildren = (...children) => { node.children = children; };
    node.parentElement = { hidden: false };
    elements.set(id, node);
  }
  return elements.get(id);
}
document.getElementById = control;
document.querySelectorAll = () => [];
globalThis.Option = function(text, value) { return { textContent: text, value }; };
control("resource").value = "RESOURCE-TEST";
control("expected-model-id").value = "model-a";
control("serial-baud-rate").value = "9600";
control("voltage").value = "1.25";
state.realIdentityCache.expectedModelId = "model-a";
state.commandSupportByModel = { "model-a": {} };
state.resourceModels = { "RESOURCE-TEST": "model-a" };
state.resourceChannelModels = { "RESOURCE-TEST": "model-a" };
state.resourceDisplayModels = { "RESOURCE-TEST": "Test model" };
state.resourceLiveSupportContext = { resource: "RESOURCE-TEST", backend_scope: "system_visa" };
state.resourceLiveSupport = { evaluated: true, backend_scope: "system_visa", commands: {} };
state.samples = [{ timestamp: 1 }];
state.workspaceResults = { old: {} };
state.jobs = [{ jobId: "old", command: "identify", status: "finished" }];
const history = state.jobs;
renderCommands = () => {};
refreshBasicInputConstraints = () => {};
refreshElectricalRatingConstraints = () => {};
updateSelectedCommandState = () => {};
renderWorkspaceSummary = () => {};
syncBasicFromLivePanel = () => {};
renderSupportedDevices = () => {};
renderBlankLivePanel = () => { state.livePanel = { channels: [], stale: false }; };
renderClientResult = () => {};
setLiveState = () => {};
state.realWriteAuthorization = realAuthorizationContext();
strictAssert.equal(hasRealWriteAuthorization(), true);
strictAssert.equal(runtimePayload().backend, null);
const requests = [];
let rejectStop = false;
let serverLocked = false;
webuiApi.fetchJson = async (url, options) => {
  if (url === "/api/health") return { status: "ok", hardware_locked: serverLocked };
  if (rejectStop && url.endsWith("/stop")) throw new Error("Stop failed");
  requests.push({ url, body: options?.body ? JSON.parse(options.body) : null });
  if (url.startsWith("/api/jobs/")) return { status: "finished" };
  return { job_id: "new", events_url: "/events/new" };
};
const subscriptions = [];
subscribeToJob = (id) => subscriptions.push(id);
addHistory = () => {};
const selector = control("visa-backend");
for (const busy of ["job", "submission", "live-request", "hardware-lock"]) {
  state.jobs = busy === "job" ? [{ status: "running" }] : history;
  state.realSubmissionsPending = busy === "submission" ? 1 : 0;
  state.liveRequestsPending = busy === "live-request" ? 1 : 0;
  state.health.hardwareLocked = busy === "hardware-lock";
  selector.value = "@py";
  await handleBackendChange({ target: selector });
  strictAssert.equal(state.backend, null);
  strictAssert.equal(selector.value, "");
}
state.jobs = history;
state.realSubmissionsPending = 0;
state.liveRequestsPending = 0;
state.health.hardwareLocked = false;
serverLocked = true;
selector.value = "@py";
await handleBackendChange({ target: selector });
strictAssert.equal(state.backend, null);
strictAssert.equal(state.backendGeneration, 0);
serverLocked = false;
state.liveJobId = "monitor-old";
state.previewJobId = "preview-old";
state.previewStoppingJobs.add("preview-stopping");
rejectStop = true;
selector.value = "@py";
await handleBackendChange({ target: selector });
strictAssert.equal(state.backend, null);
strictAssert.equal(state.backendGeneration, 0);
strictAssert.equal(hasRealWriteAuthorization(), true);
strictAssert.equal(state.resourceLiveSupport.backend_scope, "system_visa");
rejectStop = false;
selector.value = "@py";
await handleBackendChange({ target: selector });
strictAssert.equal(state.backend, "@py");
strictAssert.equal(state.realWriteAuthorization, null);
strictAssert.equal(hasRealWriteAuthorization(), false);
strictAssert.equal(control("real-write-enabled").checked, false);
strictAssert.equal(state.liveJobId, null);
strictAssert.equal(state.previewJobId, null);
strictAssert.equal(state.resourceLiveSupport, null);
strictAssert.deepEqual(state.resourceModels, {});
strictAssert.deepEqual(state.resourceChannelModels, {});
strictAssert.deepEqual(state.resourceDisplayModels, {});
strictAssert.deepEqual(state.workspaceResults, {});
strictAssert.deepEqual(state.samples, []);
strictAssert.equal(state.resourceScan.status, "not_scanned");
strictAssert.equal(state.jobs, history);
strictAssert.equal(control("resource").value, "RESOURCE-TEST");
strictAssert.equal(control("expected-model-id").value, "model-a");
strictAssert.equal(control("serial-baud-rate").value, "9600");
strictAssert.equal(control("voltage").value, "1.25");
for (const id of ["monitor-old", "preview-old", "preview-stopping"]) {
  strictAssert.ok(requests.some((r) => r.url === `/api/live/${id}/stop`));
  strictAssert.ok(requests.some((r) => r.url === `/api/jobs/${id}`));
}
const identify = requests.find((r) => r.body?.command === "identify");
strictAssert.equal(identify.body.runtime.backend, "@py");
strictAssert.equal(identify.body.runtime.confirm, false);
strictAssert.equal(identify.body.runtime.serial_options.baud_rate, 9600);
await scanResources();
strictAssert.equal(requests.find((r) => r.body?.command === "list-resources").body.runtime.backend, "@py");
strictAssert.equal(runtimePayload().backend, "@py");
strictAssert.equal(commandMeta("set").disabled, true);
const support = { evaluated: true, backend_scope: "pyvisa_py", commands: {} };
captureResourceLiveSupport({ runtime: { backend: "@py" }, result: { live_support: support } }, "RESOURCE-TEST");
updateResourceModelFromJob({ runtime: { backend: "@py", resource: "RESOURCE-TEST" }, result: { model_id: "model-a" } });
strictAssert.equal(hasRealWriteAuthorization(), false);
strictAssert.equal(captureResourceLiveSupport({ runtime: {}, result: { live_support: { backend_scope: "system_visa" } } }, "RESOURCE-TEST"), false);
strictAssert.equal(state.resourceLiveSupport, support);
const errors = [];
renderClientResult = (...args) => errors.push(args);
state.previewJobId = "preview-stop-error";
rejectStop = true;
stopLivePreviewSnapshot();
await new Promise((resolve) => setTimeout(resolve, 0));
strictAssert.equal(state.previewStoppingJobs.has("preview-stop-error"), true);
strictAssert.ok(errors.some((error) => error[0] === "Live preview" && error[1] === "failed"));
rejectStop = false;
state.planningIdentityCache.simulate = "model-a";
state.planningIdentityCache["dry-run"] = "model-a";
for (const mode of ["simulate", "dry-run"]) {
  state.executionMode = mode;
  const runtime = runtimePayload();
  strictAssert.equal("backend" in runtime, false);
  strictAssert.equal("resource" in runtime, false);
  strictAssert.equal("serial_options" in runtime, false);
  strictAssert.equal(runtime.confirm, false);
}
const result = control("result");
result.textContent = "current backend result";
let resolveOld;
webuiApi.fetchJson = () => new Promise((resolve) => { resolveOld = resolve; });
const staleDetail = renderJobDetail("old", { type: "finished", data: {} }, state.backendGeneration);
state.backendGeneration += 1;
resolveOld({ job_id: "old", status: "finished", command: "identify", runtime: { backend: "@py" } });
await staleDetail;
strictAssert.equal(result.textContent, "current backend result");
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    )


def test_live_backend_requests_and_late_samples_are_isolated():
    run_webui_module_assertions(
        r"""
const state = { backendGeneration: 0, liveRequestsPending: 0 };
const sources = [];
globalThis.EventSource = class {
  constructor(url) { this.listeners = {}; sources.push(this); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
};
const requests = [];
const panels = [];
const controller = webuiLiveData.createLiveDataController({
  state, isNoHardwareMode: () => false,
  runtimePayload: () => ({ resource: "RESOURCE-TEST", backend: "@py" }),
  fetchJson: async (url, options) => {
    requests.push(JSON.parse(options.body));
    return { job_id: "live", events_url: "/events/live" };
  },
  renderLivePanel: (data) => panels.push(data),
  renderBlankLivePanel: () => {}, updateLiveMonitorButton: () => {},
  closeEventSource: () => {}, setLiveState: () => {}, liveStateText: () => "",
  stopLivePreviewSnapshot: () => {}
});
await controller.startLive();
await controller.startLivePreviewSnapshot({ serverReady: true, deviceIdle: true });
strictAssert.equal(requests.length, 2);
strictAssert.ok(requests.every((request) => request.runtime.backend === "@py"));
strictAssert.equal(state.liveRequestsPending, 0);
state.backendGeneration += 1;
state.liveJobId = "new-monitor";
for (const source of sources) {
  source.listeners.progress({ data: JSON.stringify({ data: { stale: false, channels: [] } }) });
  source.listeners.failed({ data: JSON.stringify({ data: { error: "old" } }) });
  source.listeners.finished?.();
}
strictAssert.deepEqual(panels, []);
strictAssert.equal(state.liveJobId, "new-monitor");
""",
        ("live-data.js",),
    )


def test_supported_devices_uses_core_backend_command_and_feature_scopes(client):
    metadata = client.get("/api/commands").json()
    run_webui_module_assertions(
        "const metadata = " + json.dumps(metadata) + ";\n" + r"""
function node() {
  return { children: [], appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    get lastChild() { return this.children.at(-1); } };
}
const body = node();
globalThis.document = { getElementById: () => body, createElement: node };
const state = { backend: null, physicalModels: metadata.physical_models, liveSupportByModel: metadata.live_support_by_model_id };
const controller = webuiDevice.createDeviceResourceController({ state });
controller.renderSupportedDevices();
strictAssert.ok(body.children.length > 0);
strictAssert.ok(body.children.every((row) => row.children.length === 3));
state.backend = "@py";
controller.renderSupportedDevices();
strictAssert.equal(body.children.length, 2);
strictAssert.ok(body.children.every((row) => row.children.length === 3));
const names = body.children.map((row) => row.children[1].textContent).join("\n");
strictAssert.match(names, /E36312A/);
strictAssert.match(names, /EDU36311A/);
strictAssert.doesNotMatch(names, /E3646A|PSM-2010/);
// Synthetic metadata ensures the UI does not hardcode PyVISA-py as unsupported.
state.physicalModels = [{ model_id: "test-model", vendor_display_name: "Test vendor", model_name: "Test model" }];
const open = { backend_scope: "pyvisa_py", transport_scope: "tcpip", product_open: true };
state.liveSupportByModel = { "test-model": { commands: {
  set: { profile_supported: true, scopes: [open] },
  ramp: { profile_supported: true, scopes: [{ ...open, product_open: false, pending: true }] },
  unsupported: { profile_supported: false, scopes: [open] },
  exempt: { profile_supported: true, policy_exempt: true, scopes: [open] },
  pendingFeature: { profile_supported: true, scopes: [{ ...open, features: [
    { feature_kind: "mode", feature_value: "pending", product_open: false, pending: true }
  ] }] },
  sequence: { profile_supported: true, scopes: [{ ...open, features: [
    { feature_kind: "sequence_action", feature_value: "set", product_open: true },
    { feature_kind: "sequence_action", feature_value: "apply", product_open: false, pending: true }
  ] }] }
} } };
controller.renderSupportedDevices();
strictAssert.equal(body.children[0].children[1].textContent, "Test model");
const detail = body.children[0].children[2].children[0].children.slice(1).map((line) => line.textContent).join("\n");
strictAssert.match(detail, /set/);
strictAssert.match(detail, /sequence_action=set/);
strictAssert.doesNotMatch(detail, /ramp|apply|unsupported|exempt|pendingFeature/);
""",
        ("device-resource.js",),
    )
