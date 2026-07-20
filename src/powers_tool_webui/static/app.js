const webuiContext = globalThis.PowersToolWebUI?.context;
if (!webuiContext) {
  throw new Error("PowersToolWebUI.context failed to load before app.js.");
}
const { buildWorkspaceResultKey } = webuiContext;

const state = {
  executionMode: "real",
  executionModeTransition: false,
  realIdentityCache: { expectedModelId: "", resource: "", serial: {} },
  planningIdentityCache: { simulate: "", "dry-run": "" },
  realWriteAuthorization: null,
  commands: {},
  commandSupportByModel: {},
  liveSupportByModel: {},
  resourceLiveSupport: null,
  resourceLiveSupportContext: null,
  channelCapabilitiesByModel: {},
  parameterConstraints: {},
  electricalRatingsByModel: {},
  setpointRangesByModel: {},
  physicalModels: [],
  planningProfiles: {},
  resourceModels: {},
  resourceDisplayModels: {},
  resourceChannelModels: {},
  activeCategory: "output",
  selected: null,
  workspaceResults: {},
  jobs: [],
  events: null,
  liveEvents: null,
  liveJobId: null,
  previewEvents: null,
  previewJobId: null,
  samples: [],
  livePanel: null,
  basicJobActions: {},
  basicActionStates: {},
  resultCollapsed: true,
  jobResultCollapsed: false,
  rampListSegments: [defaultRampSegment()],
  rampListEnableOutput: false,
  rampListLoopEnabled: false,
  rampListLoopCountDraft: "2",
  rampListCompletionPulse: null,
  triggerListActiveChannel: 1,
  triggerListControls: defaultTriggerListControls(),
  triggerListChannels: defaultTriggerListChannels(),
  latestSnapshotDocument: null,
  latestSnapshotMetadata: null,
  loadedSnapshotDocument: null,
  loadedSnapshotFilename: "",
  sequenceFilename: "",
  sequenceSteps: [{ action: "wait", seconds: 0 }],
  sequenceLoopEnabled: false,
  sequenceLoopCountDraft: "2",
  sequenceExpanded: new Set(),
  restoreChannel: "all",
  restoreOutputState: false,
  restorePlanPreview: null,
  restorePlanPreviewStatus: "idle",
  workflowControl: {
    phase: "idle",
    jobId: null,
    command: null
  }
};

const COMMAND_CATEGORIES = ["output", "workflow", "protection", "trigger", "artifact", "discovery"];
const COMMAND_CATEGORY_LABELS = {
  output: "Output",
  workflow: "Output Workflows",
  protection: "Protection",
  trigger: "Trigger",
  artifact: "Snapshot",
  discovery: "Advanced Diagnostics"
};
const TRIP_GUARDED_COMMANDS = new Set(["output-on", "cycle-output", "ramp", "ramp-list", "smoke-output", "apply"]);
const TRIP_WARNING_COMMANDS = new Set([
  "sequence",
  "restore-from-snapshot",
  "trigger-pulse",
  "trigger-step",
  "trigger-list",
  "trigger-fire"
]);
const REAR_PIN_OPTIONS = ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"];
const OPTIONAL_REAR_PIN_OPTIONS = ["", ...REAR_PIN_OPTIONS];
const TRIGGER_COMMANDS = new Set([
  "trigger-pulse",
  "trigger-status",
  "trigger-step",
  "trigger-list",
  "trigger-fire",
  "trigger-abort"
]);
const STATE_CLASS_NAMES = ["state-ok", "state-warning", "state-error", "state-idle"];
const DEFAULT_CHANNELS = [1, 2, 3];
const REAR_TRIGGER_PULSE_MODEL_ID = "keysight-e36312a";
const E3646A_MODEL_ID = "keysight-e3646a";
const E3646A_GLOBAL_OUTPUT_DESCRIPTION = "E3646A uses global output control. Enabling or disabling output switches CH1 and CH2 together; voltage and current setpoints remain independently adjustable.";
const E3646A_CAPABILITY_ERROR = "E3646A output controls are disabled because global-output capability metadata is missing or inconsistent.";
const STOPPABLE_WORKFLOWS = new Set(["ramp", "ramp-list", "sequence"]);
const WORKFLOW_STOP_DESCRIPTION = "Stop the active workflow and safely turn all outputs off.";
const ELECTRICAL_CONSTRAINT_ATTRIBUTES = ["min", "max", "step", "title"];

const PARAMS = {
  "list-resources": [{ name: "live_only", type: "checkbox", label: "Live only" }],
  verify: [],
  clear: [],
  error: [{ name: "max_reads", type: "number", label: "Max reads", value: 20 }],
  readback: [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  set: setOutputParams(),
  apply: [...applyOutputParams(), { name: "no_output", type: "checkbox", label: "Do not enable output" }],
  "output-on": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "output-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "safe-off": [{
    name: "channel",
    type: "select",
    label: "Channel",
    options: ["all", "1", "2", "3"],
    value: "all",
    description: "Disables the selected output, or every available output when set to all, then reads back each output state. Voltage/current setpoints and protection settings are not changed."
  }],
  "cycle-output": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 },
    { name: "completion_pulse_enabled", type: "checkbox", label: "Trigger pulse when finished", pulseToggle: true },
    { name: "completion_pulse_pins", type: "select", label: "Rear pins", options: REAR_PIN_OPTIONS, value: "1", parser: "intList", pulseChild: true },
    { name: "completion_pulse_polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive", pulseChild: true }
  ],
  ramp: [
    { name: "enable_output", type: "checkbox", label: "Enable output", ariaLabel: "Enable output after first setpoint", helpId: "ramp-enable-output-help", compactHelp: true, description: "Output is enabled only after the first safe setpoint is written and verified. It remains ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation." },
    { name: "loop_enabled", type: "checkbox", label: "Enable loop" },
    { name: "loop_count", type: "number", label: "Loop count", value: 2, conditionalLoop: true },
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 },
    { name: "start_voltage", type: "number", label: "Start voltage(V)", value: 0 },
    { name: "stop_voltage", type: "number", label: "Stop voltage(V)", value: 1 },
    { name: "step_voltage", type: "number", label: "Step voltage(V)", value: 0.1 },
    { name: "delay_ms", type: "number", label: "Delay(ms)", value: 0 },
    { name: "completion_pulse_timing", type: "select", label: "Pulse timing", options: ["", "step", "segment", "loop"], value: "" },
    { name: "completion_pulse_pins", type: "select", label: "Rear pins", options: REAR_PIN_OPTIONS, value: "1", parser: "intList", pulseChild: true },
    { name: "completion_pulse_polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive", pulseChild: true }
  ],
  "ramp-list": [],
  "smoke-output": smokeOutputParams(),
  "protection-set": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "ovp_voltage", type: "number", label: "OVP voltage(V)", value: 5 },
    { name: "ocp", type: "select", label: "OCP", options: ["", "on", "off"], value: "" },
    { name: "ocp_delay", type: "number", label: "OCP delay(s)", optional: true },
    { name: "ocp_delay_trigger", type: "select", label: "OCP delay trigger", options: ["", "setting-change", "cc-transition"], value: "" }
  ],
  "clear-protection": [{ name: "channel", type: "select", label: "Channel", options: ["", "all", "1", "2", "3"], value: "" }],
  "trigger-pulse": [
    { name: "pins", type: "select", label: "Rear pins", options: REAR_PIN_OPTIONS, value: "1", parser: "intList", description: "E36312A only. Configures the selected rear pins as trigger outputs, keeps the current programmed setpoint, and sends global *TRG. The pulse may also fire other armed BUS triggers." },
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive" },
    { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins", description: "Resets unselected rear pins before configuring the selected pulse pins." }
  ],
  "trigger-status": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all", description: "Read-only E36312A query of rear pins, trigger source, and STEP/LIST state. It does not modify instrument settings." }],
  "trigger-step": triggerStepParams(),
  "trigger-list": [],
  "trigger-fire": [
    { name: "channel", type: "select", label: "Abort target channel", options: ["", "1", "2", "3"], value: "", optional: true, description: "Used only to abort this output channel if Wait complete times out or is interrupted." },
    { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for the instrument-wide operation-complete event. Requires an Abort target channel." },
    ...triggerWaitParams()
  ],
  "trigger-abort": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all", description: "E36312A only. Aborts Trigger/LIST execution for the selected channel or all channels. It does not turn outputs off." },
    { name: "max_errors", type: "number", label: "Max errors", value: 20, description: "Limits how many instrument error-queue entries are read after aborting." }
  ],
  identify: [],
  snapshot: [{
    name: "max_errors",
    type: "number",
    label: "Max errors",
    value: 20,
    description: "Limits how many times the snapshot reads the instrument error queue. Reading stops early when the instrument reports no error. Each reported error is removed from the instrument queue."
  }],
  sequence: []
};

function baseOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 }
  ];
}

function setOutputParams() {
  const params = baseOutputParams();
  return [
    params[0],
    { ...params[1], optional: true },
    { ...params[2], optional: true }
  ];
}

function applyOutputParams() {
  const params = baseOutputParams();
  params[0] = { ...params[0], options: ["all", "1", "2", "3"], value: "1" };
  return params;
}

function smokeOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 },
    { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 }
  ];
}

function defaultRampSegment() {
  return {
    channel: 1,
    current: 0.1,
    start_voltage: 0,
    stop_voltage: 1,
    step_voltage: 0.1,
    delay_ms: 100,
    hold_ms: 0
  };
}

function triggerStepParams() {
  return [
    {
      name: "channel",
      type: "select",
      label: "Channel",
      options: ["1", "2", "3"],
      value: "1",
      description: "E36312A only. Configures and arms a STEP transient. It does not fire by default; omitted voltage or current values keep the current programmed setpoint."
    },
    { name: "voltage", type: "number", label: "Triggered voltage(V)", optional: true },
    { name: "current", type: "number", label: "Triggered current(A)", optional: true },
    { name: "source", type: "select", label: "Source", options: ["bus", "immediate"], value: "bus", description: "Selects BUS or Immediate as the trigger source." },
    { name: "fire", type: "checkbox", label: "Fire now", description: "After arming, sends global *TRG for BUS source. This may also fire other armed BUS triggers." },
    { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for the instrument-wide operation-complete event before returning." },
    ...triggerWaitParams(),
    { name: "leave_trigger_configured", type: "checkbox", label: "Leave configured", description: "Keeps the configured trigger source and transient mode instead of restoring them after execution." }
  ];
}

function triggerListParams() {
  return [
    {
      name: "channel",
      type: "select",
      label: "Channel",
      options: ["1", "2", "3"],
      value: "1",
      description: "E36312A only. Configures and arms a LIST waveform. It does not fire by default; one current or dwell value can be applied to every voltage step."
    },
    { name: "voltage_list", type: "text", label: "Voltage list(V)", value: "0,1", parser: "numberList", description: "Comma-separated voltage steps." },
    { name: "current_list", type: "text", label: "Current list(A)", value: "0.05", parser: "numberList", description: "Comma-separated current limits. A single value applies to every voltage step." },
    { name: "dwell_list", type: "text", label: "Dwell list(s)", value: "0.01", parser: "numberList", description: "Comma-separated dwell times. A single value applies to every voltage step." },
    { name: "count", type: "number", label: "Count", value: 1, description: "Number of times to repeat the complete LIST waveform." },
    { name: "source", type: "select", label: "Source", options: ["bus", "immediate"], value: "bus", description: "Selects BUS or Immediate as the trigger source." },
    { name: "fire", type: "checkbox", label: "Fire now", description: "After arming, sends global *TRG for BUS source. This may also fire other armed BUS triggers." },
    { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for all LIST steps and repeat counts to complete before returning." },
    { name: "completion_pulse_pins", type: "select", label: "Pulse pins", options: OPTIONAL_REAR_PIN_OPTIONS, value: "", optional: true, parser: "intList", description: "Optionally emits a completion pulse on the selected rear pins after LIST execution finishes." },
    { name: "completion_pulse_polarity", type: "select", label: "Pulse polarity", options: ["positive", "negative"], value: "positive" },
    { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins", description: "Resets unselected rear pins before configuring completion-pulse pins." },
    ...triggerWaitParams(),
    { name: "leave_trigger_configured", type: "checkbox", label: "Leave configured", description: "Keeps the configured trigger source and LIST mode instead of restoring them after execution." }
  ];
}

function triggerWaitParams() {
  return [
    { name: "poll_ms", type: "number", label: "Poll(ms)", value: 200, description: "Interval between completion-status polls when waiting." },
    { name: "wait_timeout_ms", type: "number", label: "Timeout(ms)", optional: true, description: "Optional maximum wait time; leave blank to use the command default." }
  ];
}

document.addEventListener("DOMContentLoaded", async () => {
  bind();
  renderBlankLivePanel();
  await refreshHealth();
  await loadCommands();
  drawTrend();
});

function bind() {
  document.getElementById("run").addEventListener("click", runSelected);
  document.getElementById("scan").addEventListener("click", scanResources);
  document.getElementById("resource-select").addEventListener("change", syncSelectedResource);
  const syncTypedResource = () => {
    clearRealWriteAuthorization();
    updateDeviceResourceSummary();
    syncBasicFromLivePanel(state.livePanel);
  };
  document.getElementById("resource").addEventListener("input", syncTypedResource);
  document.getElementById("resource").addEventListener("change", syncTypedResource);
  document.getElementById("resource-select").addEventListener("change", updateDeviceResourceSummary);
  document.getElementById("expected-model-id")?.addEventListener("change", handleExpectedModelChanged);
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => radio.addEventListener("change", handleExecutionModeChange));
  document.getElementById("real-write-enabled")?.addEventListener("change", () => {
    state.realWriteAuthorization = document.getElementById("real-write-enabled").checked ? realAuthorizationContext() : null;
    updateExecutionModeUi();
  });
  document.getElementById("device-options-toggle").addEventListener("click", (event) => {
    event.stopPropagation();
    setDeviceOptionsExpanded(document.getElementById("device-options-toggle").getAttribute("aria-expanded") !== "true");
  });
  document.getElementById("device-options-panel").addEventListener("click", (event) => {
    event.stopPropagation();
  });
  document.getElementById("toggle-device-resource").addEventListener("click", () => {
    setDeviceResourceExpanded(document.getElementById("toggle-device-resource").getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("click", () => setDeviceOptionsExpanded(false));
  document.addEventListener("keydown", (event) => {
    const button = document.getElementById("device-options-toggle");
    if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") {
      setDeviceOptionsExpanded(false);
      button.focus();
    }
  });
  document.getElementById("command-filter").addEventListener("input", renderCommands);
  document.getElementById("live-start").addEventListener("click", toggleLiveMonitor);
  document.getElementById("result-toggle").addEventListener("click", toggleResultPanel);
  document.getElementById("job-result-toggle").addEventListener("click", toggleJobResultPanel);
  document.getElementById("job-result-clear").addEventListener("click", clearJobResults);
  document.getElementById("advanced-command-toggle").addEventListener("click", toggleAdvancedCommands);
  document.querySelectorAll("[data-basic-set]").forEach((button) => {
    button.addEventListener("click", () => runBasicSet(Number(button.dataset.basicSet)));
  });
  document.querySelectorAll("[data-basic-output]").forEach((button) => {
    button.addEventListener("click", () => runBasicOutput(Number(button.dataset.basicOutput)));
  });
  document.querySelector("[data-basic-all-output]").addEventListener("click", runBasicOutputAll);
  document.querySelectorAll("[data-basic-voltage], [data-basic-current]").forEach((input) => {
    input.addEventListener("input", () => {
      input.dataset.basicDirty = "true";
      validateBasicInput(input);
    });
    input.addEventListener("blur", () => validateBasicInput(input));
  });
  setDeviceOptionsExpanded(false);
  setDeviceResourceExpanded(true);
  updateDeviceResourceSummary();
  updateExecutionModeUi();
}

function setDeviceOptionsExpanded(expanded) {
  const panel = document.getElementById("device-options-panel");
  const button = document.getElementById("device-options-toggle");
  panel.hidden = !expanded;
  button.setAttribute("aria-expanded", String(expanded));
}

function setDeviceResourceExpanded(expanded) {
  const section = document.querySelector(".device-resource-section");
  const body = document.getElementById("device-resource-body");
  const button = document.getElementById("toggle-device-resource");
  body.hidden = !expanded;
  section.classList.toggle("collapsed", !expanded);
  button.textContent = expanded ? "-" : "+";
  button.setAttribute("aria-expanded", String(expanded));
  button.setAttribute("aria-label", expanded ? "Collapse Device / Resource" : "Expand Device / Resource");
  button.title = expanded ? "Collapse Device / Resource" : "Expand Device / Resource";
}

function updateDeviceResourceSummary() {
  const summary = document.getElementById("device-resource-summary");
  const resource = document.getElementById("resource").value.trim();
  const clearedExactSupport = clearStaleResourceLiveSupport(resource);
  const select = document.getElementById("resource-select");
  const presentation = buildDeviceResourceSummary(resource, select);
  summary.textContent = presentation.text;
  summary.title = presentation.title;
  const detected = detectedCommandModelForResource(resource);
  const expected = selectedExpectedModel();
  if (expected && resourceModelDetectionRecorded(resource) && detected !== expected) {
    summary.title = "Selected expected model does not match the last scanned model. Live commands will fail before setup/write SCPI.";
  }
  if (clearedExactSupport) {
    syncBasicFromLivePanel(state.livePanel);
    if (state.selected) selectCommand(state.selected);
    else renderCommands();
  }
}

function buildDeviceResourceSummary(resource, select) {
  if (isNoHardwareMode()) {
    const mode = state.executionMode === "simulate" ? "Simulate mode" : "Dry-run mode";
    const planning = planningIdentitySummary(selectedPlanningIdentity());
    const realContext = resource
      ? `Real VISA resource preserved, not used: ${resource}`
      : "Real VISA resource not used";
    const text = [mode, planning, realContext].join(" / ");
    return { text, title: text };
  }

  const canonicalModel = actualCurrentResourceModel();
  const reportedModel = detectedResourceDisplayModel(resource);
  const detection = canonicalModel
    ? `Detected model: ${physicalModelDisplayName(canonicalModel)}`
    : reportedModel
      ? `Reported model: ${reportedModel} (canonical identity unresolved)`
      : `Detection status: ${liveResourceSummary(resource, select)}`;
  const text = [
    "Real mode",
    `VISA resource: ${resource || "not selected"}`,
    detection,
    `Expected Model guard: ${expectedModelSummary()}`,
    exactSupportContextSummary(resource)
  ].join(" / ");
  return { text, title: text };
}

function planningIdentitySummary(identity) {
  if (!identity) return state.executionMode === "simulate" ? "Planning model: not selected" : "Planning target: not selected";
  if (identity.startsWith("profile:")) {
    const profileId = identity.slice("profile:".length);
    const profile = state.planningProfiles?.[profileId];
    return `Planning profile: ${profile?.display_name || profile?.model_name || profileId}`;
  }
  return `Planning model: ${physicalModelDisplayName(identity)}`;
}

function liveResourceSummary(resource, select) {
  if (!resource) return "not scanned";
  const detected = detectedResourceDisplayModel(resource);
  if (detected) return `live ${detected}`;
  const selectedLiveResource = Boolean(select.value.trim() && select.value.trim() === resource);
  if (selectedLiveResource) return "live selected";
  const firstOption = select.options[0]?.textContent?.trim() || "";
  if (firstOption === "No live resources found") return "no live resources";
  return "not scanned";
}

function expectedModelSummary() {
  const expected = selectedExpectedModel();
  return expected ? `Require ${physicalModelDisplayName(expected)}` : "Auto-detect";
}

function selectedExpectedModel() {
  return state.executionMode === "real" ? valueOrNull("expected-model-id") : null;
}

function selectedPlanningIdentity() {
  return state.executionMode === "real" ? null : valueOrNull("expected-model-id");
}

function rememberCurrentExecutionIdentity() {
  const identity = valueOrNull("expected-model-id") || "";
  if (state.executionMode === "real") {
    state.realIdentityCache.expectedModelId = identity;
  } else if (Object.prototype.hasOwnProperty.call(state.planningIdentityCache, state.executionMode)) {
    state.planningIdentityCache[state.executionMode] = identity;
  }
}

function isNoHardwareMode() {
  return webuiContext.isNoHardwareExecutionMode(state.executionMode);
}

function realAuthorizationContext() {
  return JSON.stringify({
    resource: valueOrNull("resource"),
    expected_model_id: state.realIdentityCache.expectedModelId || valueOrNull("expected-model-id"),
    connected_model_id: detectedCommandModelForResource(valueOrNull("resource"))
  });
}

function clearRealWriteAuthorization() {
  state.realWriteAuthorization = null;
  const checkbox = document.getElementById("real-write-enabled");
  if (checkbox) checkbox.checked = false;
}

function hasRealWriteAuthorization() {
  return state.executionMode === "real" && state.realWriteAuthorization === realAuthorizationContext();
}

function updateExecutionModeUi({ renderCommands: shouldRenderCommands = true } = {}) {
  const noHardware = isNoHardwareMode();
  const jobBusy = state.executionModeTransition || state.workflowControl.phase !== "idle" || Object.values(state.basicActionStates).some((action) => ["pending", "submitting", "active", "stopping"].includes(action.status)) || state.jobs.some((job) => ["accepted", "started", "progress", "running", "cancel_requested"].includes(job.status));
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => {
    radio.disabled = jobBusy;
    radio.title = jobBusy ? "Execution mode cannot change while a job is submitting, active, or stopping." : "";
  });
  const badge = document.getElementById("execution-mode-badge");
  const checkbox = document.getElementById("real-write-enabled");
  const help = document.getElementById("execution-mode-help");
  const label = document.getElementById("identity-model-label");
  const resourceControls = ["resource", "resource-select", "scan", "live-start", "serial-baud-rate", "serial-data-bits", "serial-parity", "serial-stop-bits", "serial-flow-control", "serial-read-termination", "serial-write-termination", "serial-remote", "serial-local-on-close"];
  resourceControls.forEach((id) => {
    const control = document.getElementById(id);
    if (!control) return;
    control.disabled = noHardware;
    control.classList.toggle("no-hardware-control", noHardware);
  });
  if (checkbox) {
    checkbox.disabled = noHardware || !valueOrNull("resource");
    checkbox.parentElement.hidden = noHardware;
  }
  if (label) label.firstChild.textContent = noHardware ? (state.executionMode === "simulate" ? "Simulation model" : "Planning target") : "Expected model";
  if (help) help.textContent = noHardware
    ? (state.executionMode === "simulate" ? "Select a canonical physical model. Simulation never opens VISA hardware." : "Select a physical model or a planning profile. Dry-run never opens VISA hardware.")
    : "Auto-detect uses the connected instrument IDN. Select a model only when you want to require a specific one.";
  if (badge) {
    badge.className = "execution-mode-badge";
    if (state.executionMode === "simulate") { badge.textContent = "Simulate"; badge.classList.add("simulate"); }
    else if (state.executionMode === "dry-run") { badge.textContent = "Dry-run"; badge.classList.add("dry-run"); }
    else if (hasRealWriteAuthorization()) { badge.textContent = "Real · Writes enabled"; badge.classList.add("real-enabled"); }
    else { badge.textContent = "Real · Writes locked"; badge.classList.add("real-locked"); }
  }
  populateIdentitySelector();
  updateDeviceResourceSummary();
  if (shouldRenderCommands) renderCommands();
  syncBasicFromLivePanel(state.livePanel);
}

function populateIdentitySelector() {
  const select = document.getElementById("expected-model-id");
  if (!select || !state.physicalModels.length) return;
  select.replaceChildren();
  if (state.executionMode === "real") {
    select.add(new Option("Auto-detect", ""));
    state.physicalModels.forEach((model) => select.add(new Option(model.display_name || model.model_name, model.model_id)));
    const expected = state.realIdentityCache.expectedModelId;
    select.value = state.physicalModels.some((model) => model.model_id === expected) ? expected : "";
  } else if (state.executionMode === "simulate") {
    select.add(new Option("Select simulation model", ""));
    state.physicalModels.forEach((model) => select.add(new Option(model.display_name || model.model_name, model.model_id)));
    const planned = state.planningIdentityCache.simulate;
    select.value = state.physicalModels.some((model) => model.model_id === planned) ? planned : "";
  } else {
    select.add(new Option("Select planning target", ""));
    const physical = document.createElement("optgroup"); physical.label = "Physical models";
    state.physicalModels.forEach((model) => physical.append(new Option(model.display_name || model.model_name, model.model_id)));
    select.append(physical);
    const profiles = document.createElement("optgroup"); profiles.label = "Planning profiles";
    Object.values(state.planningProfiles || {}).forEach((profile) => {
      const profileId = profile.profile_id || profile.planning_profile_id;
      if (profileId) profiles.append(new Option(profile.display_name || profile.model_name || profileId, `profile:${profileId}`));
    });
    select.append(profiles);
    const planned = state.planningIdentityCache["dry-run"];
    const physicalMatch = state.physicalModels.some((model) => model.model_id === planned);
    const profileMatch = planned.startsWith("profile:") && Boolean(state.planningProfiles?.[planned.slice("profile:".length)]);
    select.value = physicalMatch || profileMatch ? planned : "";
  }
}

async function handleExecutionModeChange(event) {
  const requested = event.target.value;
  if (requested === state.executionMode || state.executionModeTransition) return;
  let modeChanged = false;
  event.target.checked = false;
  document.querySelector(`input[name="execution-mode"][value="${state.executionMode}"]`).checked = true;
  state.executionModeTransition = true;
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => radio.disabled = true);
  try {
    await stopRealLiveJobsAndWait();
    rememberCurrentExecutionIdentity();
    if (state.executionMode === "real") {
      clearRealWriteAuthorization();
    }
    state.executionMode = requested;
    modeChanged = true;
    if (requested === "real") clearRealWriteAuthorization();
    document.querySelector(`input[name="execution-mode"][value="${requested}"]`).checked = true;
    renderBlankLivePanel("ok", "Execution mode changed.");
  } catch (error) {
    renderClientResult("Execution mode", "failed", error.message || String(error), { error: "Mode change cancelled" });
  } finally {
    state.executionModeTransition = false;
    updateExecutionModeUi({ renderCommands: !modeChanged || !state.selected });
    if (modeChanged) {
      if (state.selected) selectCommand(state.selected);
      else renderWorkspaceSummary();
    }
  }
}

async function stopRealLiveJobsAndWait() {
  const jobs = [["liveJobId", "liveEvents"], ["previewJobId", "previewEvents"]];
  for (const [idKey, eventKey] of jobs) {
    const jobId = state[idKey];
    closeEventSource(eventKey);
    if (!jobId) continue;
    await fetchJson(`/api/live/${jobId}/stop`, { method: "POST" });
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const job = await fetchJson(`/api/jobs/${jobId}`);
      if (["cancelled", "finished", "failed"].includes(job.status)) { state[idKey] = null; break; }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (state[idKey] === jobId) throw new Error("Live Data did not reach a terminal state within 15 seconds; remaining in Real mode.");
  }
}

function selectedExpectedModelLabel() {
  const expected = selectedExpectedModel();
  return expected ? `Require ${physicalModelDisplayName(expected)}` : "Auto-detect";
}

function physicalModelDisplayName(modelId) {
  const canonicalModelId = String(modelId || "").trim();
  if (!canonicalModelId) return "Unknown model";
  const metadata = state.physicalModels.find((model) => model?.model_id === canonicalModelId);
  return metadata?.display_name || metadata?.model_name || canonicalModelId;
}

function detectedResourceDisplayModel(resource) {
  if (!resource) return null;
  return state.resourceDisplayModels[resource] || null;
}

function resourceModelDetectionRecorded(resource) {
  return Boolean(resource) && Object.prototype.hasOwnProperty.call(state.resourceChannelModels, resource);
}

function detectedCommandModelForResource(resource) {
  if (!resource) return null;
  return state.resourceModels[resource] || null;
}

function detectedChannelModelForResource(resource) {
  if (!resource) return null;
  return state.resourceChannelModels[resource] || null;
}

function selectedCommandModel() {
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    return identity?.startsWith("profile:") ? null : identity;
  }
  const expected = selectedExpectedModel();
  if (expected && state.commandSupportByModel?.[expected]) return expected;
  return detectedCommandModelForResource(valueOrNull("resource"));
}

function selectedChannelModel() {
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    return identity?.startsWith("profile:") ? null : identity;
  }
  const expected = selectedExpectedModel();
  if (expected && state.channelCapabilitiesByModel?.[expected]) return expected;
  return detectedChannelModelForResource(valueOrNull("resource"));
}

function actualCurrentResourceModel() {
  const resource = valueOrNull("resource");
  if (!resource) return null;
  const livePanel = state.livePanel;
  if (livePanel && !livePanel.stale && livePanel.resource === resource && livePanel.model_id) {
    return String(livePanel.model_id).trim() || null;
  }
  const detected = detectedCommandModelForResource(resource) || detectedChannelModelForResource(resource);
  if (detected) return detected;
  const liveSupport = currentExactLiveSupport();
  return liveSupport?.model_id ? String(liveSupport.model_id).trim() || null : null;
}

function e3646aGlobalOutputCapability() {
  const capability = channelCapabilityForModel(E3646A_MODEL_ID);
  if (!capability || capability.output_control_scope !== "global") return null;
  if (capability.channels.length !== 2 || capability.channels[0] !== 1 || capability.channels[1] !== 2) return null;
  return capability;
}

function basicOutputPresentation() {
  const model = isNoHardwareMode() ? selectedPlanningIdentity() : actualCurrentResourceModel();
  if (model !== E3646A_MODEL_ID) {
    return { mode: "ordinary", capability: null };
  }
  const capability = e3646aGlobalOutputCapability();
  return capability
    ? { mode: "e3646a-global", capability }
    : { mode: "e3646a-disabled", capability: null };
}

function selectedElectricalRatingModel() {
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    if (!identity || identity.startsWith("profile:")) return null;
    return state.electricalRatingsByModel?.[identity] ? identity : null;
  }
  const expected = selectedExpectedModel();
  if (expected && state.electricalRatingsByModel?.[expected]) return expected;
  return currentResourceModel();
}

function handleExpectedModelChanged() {
  rememberCurrentExecutionIdentity();
  if (state.executionMode === "real") {
    clearRealWriteAuthorization();
  }
  updateDeviceResourceSummary();
  refreshBasicInputConstraints();
  syncBasicFromLivePanel(state.livePanel);
  refreshElectricalRatingConstraints();
  if (state.selected) {
    selectCommand(state.selected);
  } else {
    renderCommands();
  }
  renderWorkspaceSummary();
  updateSelectedCommandState();
}

function updateLiveMonitorButton(monitoring, disabled = false) {
  const button = document.getElementById("live-start");
  if (!button) return;
  button.disabled = disabled;
  button.textContent = monitoring ? "Stop Monitor" : "Start Monitor";
  button.setAttribute("aria-pressed", String(monitoring));
  button.classList.toggle("on", monitoring);
  button.classList.toggle("off", !monitoring);
}

async function refreshHealth() {
  try {
    const health = await fetchJson("/api/health");
    const serverReady = health.status === "ok";
    const deviceIdle = serverReady && !health.hardware_locked;
    setStateIndicator(
      "server-state",
      serverReady ? "Ready" : "Error",
      serverReady ? "state-ok" : "state-error",
      serverReady ? "WebUI API is reachable." : `WebUI health status: ${health.status}`
    );
    setStateIndicator(
      "device-state",
      serverReady ? (deviceIdle ? "Ready" : "Busy") : "Unknown",
      serverReady ? (deviceIdle ? "state-ok" : "state-warning") : "state-idle",
      deviceIdle
        ? "Command path can accept real hardware jobs."
        : serverReady
          ? `Hardware lock is held by job ${health.active_job || "unknown"}.`
          : "Command state is unavailable while WebUI health is not ready."
    );
    return { serverReady, deviceIdle };
  } catch (error) {
    setStateIndicator("server-state", "Error", "state-error", error.message || String(error));
    setStateIndicator("device-state", "Unknown", "state-idle", "Command state is unavailable while WebUI health cannot be reached.");
    renderBlankLivePanel("error", error.message || String(error));
    return { serverReady: false, deviceIdle: false, error };
  }
}

function setStateIndicator(elementId, text, stateClass = "state-idle", title = "") {
  const indicator = document.getElementById(elementId);
  if (!indicator) return;
  indicator.classList.add("state-indicator");
  STATE_CLASS_NAMES.forEach((className) => indicator.classList.toggle(className, className === stateClass));
  let dot = indicator.querySelector(".state-dot");
  let textNode = indicator.querySelector(".state-text");
  if (!dot || !textNode) {
    indicator.textContent = "";
    dot = document.createElement("span");
    dot.className = "state-dot";
    dot.setAttribute("aria-hidden", "true");
    textNode = document.createElement("span");
    textNode.className = "state-text";
    indicator.append(dot, textNode);
  }
  textNode.textContent = text;
  indicator.title = title || text;
}

async function loadCommands() {
  const payload = await fetchJson("/api/commands");
  state.commands = payload.commands || {};
  state.commandSupportByModel = payload.command_support_by_model_id || {};
  state.liveSupportByModel = payload.live_support_by_model_id || {};
  state.channelCapabilitiesByModel = payload.channel_capabilities_by_model_id || {};
  state.parameterConstraints = payload.parameter_constraints || {};
  state.electricalRatingsByModel = payload.electrical_ratings_by_model_id || {};
  state.setpointRangesByModel = payload.setpoint_ranges_by_model_id || {};
  state.physicalModels = Array.isArray(payload.physical_models) ? payload.physical_models : [];
  state.planningProfiles = payload.planning_profiles || {};
  populateIdentitySelector();
  refreshBasicInputConstraints();
  renderCommands();
}

function renderExpectedModelOptions() {
  populateIdentitySelector();
}

function renderCommands() {
  const filter = document.getElementById("command-filter").value.toLowerCase();
  const categories = document.getElementById("command-categories");
  const list = document.getElementById("command-list");
  categories.innerHTML = "";
  list.innerHTML = "";

  COMMAND_CATEGORIES.forEach((category) => {
    const button = document.createElement("button");
    button.className = `category-button${state.activeCategory === category ? " active" : ""}`;
    button.type = "button";
    button.textContent = COMMAND_CATEGORY_LABELS[category];
    button.addEventListener("click", () => {
      state.activeCategory = category;
      renderCommands();
    });
    categories.appendChild(button);
  });

  Object.entries(state.commands)
    .filter(([name, meta]) => (meta.category || "discovery") === state.activeCategory)
    .filter(([name]) => !filter || name.includes(filter) || commandDisplayName(name).toLowerCase().includes(filter))
    .sort((a, b) => commandDisplayName(a[0]).localeCompare(commandDisplayName(b[0])))
    .forEach(([name]) => {
      const effectiveMeta = commandMeta(name);
      const button = document.createElement("button");
      button.className = `command-button${state.selected === name ? " active" : ""}`;
      button.disabled = Boolean(effectiveMeta.disabled || state.workflowControl.phase !== "idle");
      button.innerHTML = `<span>${commandDisplayName(name)}</span><small>${effectiveMeta.disabled_reason || effectiveMeta.live_support_status || ""}</small>`;
      button.addEventListener("click", () => selectCommand(name));
      list.appendChild(button);
    });
}

function selectCommand(name) {
  if (state.workflowControl.phase !== "idle") return;
  state.selected = name;
  document.getElementById("selected-command").textContent = commandDisplayName(name);
  renderForm(name);
  renderWorkspaceSummary();
  prefillClearProtectionChannel();
  updateSelectedCommandState();
  renderCommands();
}

const SET_PARTIAL_GUIDANCE = "Set accepts Voltage, Current, or both. Blank fields are left unchanged.";

function createCheckboxField(input, text, classNames = []) {
  const label = document.createElement("label");
  label.classList.add("checkbox-field", ...classNames);
  const visibleText = document.createElement("span");
  visibleText.className = "checkbox-label-text";
  visibleText.textContent = text;
  label.append(input, visibleText);
  return label;
}

function renderForm(command) {
  const form = document.getElementById("command-form");
  form.innerHTML = "";
  if (command === "ramp-list") {
    renderRampListForm(form);
    return;
  }
  if (command === "trigger-list") {
    renderTriggerListForm(form);
    return;
  }
  if (command === "snapshot") {
    renderSnapshotForm(form);
    return;
  }
  if (command === "restore-from-snapshot") {
    renderRestoreForm(form);
    return;
  }
  if (command === "sequence") {
    renderSequenceForm(form);
    return;
  }
  (PARAMS[command] || []).forEach((param) => {
    if (command === "ramp" && param.name === "loop_count") return;
    let input;
    if (param.type === "select") {
      input = document.createElement("select");
      param.options.forEach((option) => {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = param.parser === "intList"
          ? rearPinDisplayName(option)
          : pulseTimingDisplayName(command, option);
        if (param.name === "channel" && isNumericChannel(option) && !isChannelSupported(option)) {
          item.disabled = true;
          item.title = channelUnsupportedReason(option);
        }
        input.appendChild(item);
      });
    } else if (param.type === "textarea") {
      input = document.createElement("textarea");
    } else {
      input = document.createElement("input");
      input.type = param.type;
    }
    input.id = `param-${param.name}`;
    if (param.value !== undefined) input.value = param.value;
    applyParameterConstraint(input, param.name);
    applyElectricalRatingConstraint(input, param.name);
    if (param.name.includes("completion_pulse")) applyWorkflowPulseControlState(input);
    input.addEventListener("change", () => {
      enforcePulseFormRules(command, param.name, input);
      refreshElectricalRatingConstraints();
      updateSelectedCommandState();
    });
    input.addEventListener("input", () => {
      enforcePulseFormRules(command, param.name, input);
      updateSelectedCommandState();
    });
    const label = param.type === "checkbox"
      ? createCheckboxField(input, param.label)
      : document.createElement("label");
    if (param.type !== "checkbox") {
      label.textContent = param.label;
      label.appendChild(input);
    }
    if (command === "ramp" && param.name === "loop_enabled") {
      form.appendChild(renderLoopControl({
        prefix: "ramp",
        enabledInput: input,
        current: 1,
        countInputId: "param-loop_count",
        onValue: () => {},
        onDisable: () => {
          const timing = document.getElementById("param-completion_pulse_timing");
          if (timing?.value === "loop") timing.value = "";
          updatePulseChildVisibility("ramp");
        }
      }));
      return;
    }
    if (param.pulseToggle) label.classList.add("pulse-toggle-field");
    if (param.pulseChild) label.classList.add("pulse-child-field");
    if (command === "ramp" && param.name === "enable_output") {
      label.classList.add("ramp-enable-output-field");
    }
    if (param.conditionalLoop) {
      label.hidden = true;
      input.min = "2"; input.max = "255"; input.step = "1";
    }
    if (param.compactHelp) configureCompactCheckboxHelp(label, input, param);
    if (!TRIGGER_COMMANDS.has(command) && !param.compactHelp) appendFieldDescription(label, param);
    if (command === "set" && param.name === "current") appendSetGuidance(label);
    form.appendChild(label);
  });
  if (TRIGGER_COMMANDS.has(command)) appendCommandNotes(form, command, PARAMS[command] || []);
  updatePulseChildVisibility(command);
  refreshLoopCompleteOption(command);
}

function renderCommandGuidance(command, parameters = {}) {
  const guidance = document.getElementById("command-guidance");
  if (!guidance) return;
  const messages = {
    "trigger-step": "Immediate starts from INIT, so Fire now is unavailable. For BUS, Wait complete requires Fire now in the same command and waits for the instrument-wide operation-complete event.",
    "trigger-list": "Wait complete with Leave configured off writes back the pre-run Trigger settings and LIST table after completion. The running LIST may be briefly visible; select Leave configured to retain the new LIST table and Trigger settings.",
    "trigger-fire": "Sends global *TRG to every armed BUS trigger on the instrument. Abort target channel does not limit Fire or Wait; it is used only if Wait complete times out or is interrupted."
  };
  const guard = triggerControlGuardReason(command, parameters) || triggerFireWaitGuardReason(command, parameters);
  const text = [guard, messages[command]].filter(Boolean).join(" ");
  guidance.textContent = text;
  guidance.hidden = !text;
}

function updatePulseChildVisibility(command) {
  const enabled = command === "cycle-output"
    ? Boolean(document.getElementById("param-completion_pulse_enabled")?.checked)
    : command === "ramp"
      ? Boolean(document.getElementById("param-completion_pulse_timing")?.value)
      : true;
  document.querySelectorAll("#command-form .pulse-child-field").forEach((field) => {
    field.classList.toggle("visible", enabled);
  });
}

function appendFieldDescription(label, param) {
  if (!param.description) return;
  const description = document.createElement("small");
  description.className = "field-description";
  description.textContent = param.description;
  label.appendChild(description);
}

function configureCompactCheckboxHelp(label, input, { ariaLabel, helpId, description }) {
  label.setAttribute("for", input.id);
  label.title = description;
  input.title = description;
  input.setAttribute("aria-label", ariaLabel);
  input.setAttribute("aria-describedby", helpId);

  const help = document.createElement("span");
  help.id = helpId;
  help.className = "visually-hidden";
  help.textContent = description;
  label.appendChild(help);
}

function appendSetGuidance(label) {
  const guidance = document.createElement("small");
  guidance.className = "field-description set-field-guidance";
  guidance.textContent = SET_PARTIAL_GUIDANCE;
  label.appendChild(guidance);
}

function appendCommandNotes(form, command, params) {
  const notes = document.createElement("section");
  notes.className = "command-notes";
  const title = document.createElement("strong");
  title.textContent = "Command notes";
  notes.appendChild(title);

  const summary = document.createElement("p");
  summary.textContent = commandMeta(command).description || "";
  notes.appendChild(summary);

  const descriptions = params.filter((param) => param.description);
  if (descriptions.length) {
    const list = document.createElement("dl");
    descriptions.forEach((param) => {
      const term = document.createElement("dt");
      term.textContent = param.label;
      const detail = document.createElement("dd");
      detail.textContent = param.description;
      list.append(term, detail);
    });
    notes.appendChild(list);
  }
  form.appendChild(notes);
}

function defaultTriggerListStep() {
  return { voltage: 0, current: 0.05, dwell: 0.01, bost: false, eost: false };
}

function defaultTriggerListChannels() {
  return Object.fromEntries(["1", "2", "3"].map((channel) => [channel, { count: 1, steps: [defaultTriggerListStep()] }]));
}

function defaultTriggerListControls() {
  return { source: "immediate", fire: false, wait_complete: true, trigger_output_pins: [], trigger_output_polarity: "positive", exclusive_pins: false, poll_ms: 200, wait_timeout_ms: null, leave_trigger_configured: false };
}

function activeTriggerListDraft() {
  return state.triggerListChannels[String(state.triggerListActiveChannel)];
}

function renderTriggerListForm(form) {
  const editor = document.createElement("div");
  editor.className = "trigger-list-editor";
  const toolbar = document.createElement("div");
  toolbar.className = "trigger-list-toolbar";
  [["Load Trigger List", loadTriggerListWorkspace], ["Save Trigger List", saveTriggerListWorkspace], ["Add Step", addTriggerListStep]].forEach(([text, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    button.disabled = text === "Add Step" && activeTriggerListDraft().steps.length >= 100;
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  editor.appendChild(toolbar);
  const tabs = document.createElement("div");
  tabs.className = "trigger-list-tabs";
  [1, 2, 3].forEach((channel) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `secondary${state.triggerListActiveChannel === channel ? " active" : ""}`;
    button.dataset.triggerListChannel = String(channel);
    button.textContent = `Channel ${channel}`;
    button.addEventListener("click", () => {
      state.triggerListActiveChannel = channel;
      renderForm("trigger-list");
      updateSelectedCommandState();
    });
    tabs.appendChild(button);
  });
  editor.appendChild(tabs);
  const controls = document.createElement("div");
  controls.className = "trigger-list-controls";
  triggerListControlDefinitions().forEach((definition) => controls.appendChild(triggerListControlField(definition)));
  editor.appendChild(controls);
  const table = document.createElement("table");
  table.className = "trigger-list-table";
  table.innerHTML = "<thead><tr><th>Step</th><th>Voltage (V)</th><th>Current (A)</th><th>Dwell (s)</th><th>BOST</th><th>EOST</th><th>Actions</th></tr></thead>";
  const body = document.createElement("tbody");
  activeTriggerListDraft().steps.forEach((step, index) => body.appendChild(triggerListStepRow(step, index)));
  table.appendChild(body);
  editor.appendChild(table);
  form.appendChild(editor);
}

function triggerListControlDefinitions() {
  return [
    { name: "count", label: "Count", type: "number" }, { name: "source", label: "Source", type: "select", options: ["immediate", "bus"] },
    { name: "fire", label: "Fire", type: "checkbox" }, { name: "wait_complete", label: "Wait complete", type: "checkbox" },
    { name: "trigger_output_pins", label: "LIST output pins", type: "select", options: OPTIONAL_REAR_PIN_OPTIONS },
    { name: "trigger_output_polarity", label: "Polarity", type: "select", options: ["positive", "negative"] },
    { name: "exclusive_pins", label: "Exclusive pins", type: "checkbox" }, { name: "poll_ms", label: "Poll (ms)", type: "number" },
    { name: "wait_timeout_ms", label: "Timeout (ms)", type: "number" }, { name: "leave_trigger_configured", label: "Leave configured", type: "checkbox" }
  ];
}

function triggerListControlField(definition) {
  const input = document.createElement(definition.type === "select" ? "select" : "input");
  if (definition.type === "select") {
    definition.options.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = definition.name === "trigger_output_pins" ? rearPinDisplayName(value) : optionDisplayName(value);
      input.appendChild(option);
    });
  } else input.type = definition.type;
  const value = definition.name === "count" ? activeTriggerListDraft().count : state.triggerListControls[definition.name];
  if (definition.type === "checkbox") input.checked = Boolean(value);
  else input.value = definition.name === "trigger_output_pins" ? pinsSelectValue(value) : value ?? "";
  if (definition.name === "count") { input.min = "1"; input.max = "256"; input.step = "1"; }
  if (definition.name === "poll_ms") { input.min = "50"; input.step = "1"; }
  if (definition.name === "wait_timeout_ms") { input.min = "1"; input.step = "1"; }
  input.id = `param-${definition.name}`;
  if (definition.name === "fire" && state.triggerListControls.source === "immediate") input.disabled = true;
  input.addEventListener("change", () => updateTriggerListControl(definition, input));
  input.addEventListener("input", () => updateTriggerListControl(definition, input));
  const label = definition.type === "checkbox"
    ? createCheckboxField(input, definition.label)
    : document.createElement("label");
  if (definition.type !== "checkbox") {
    label.textContent = definition.label;
    label.appendChild(input);
  }
  return label;
}

function triggerListStepRow(step, index) {
  const row = document.createElement("tr");
  const number = document.createElement("td");
  number.textContent = String(index + 1);
  row.appendChild(number);
  ["voltage", "current", "dwell", "bost", "eost"].forEach((name) => {
    const cell = document.createElement("td");
    const input = document.createElement("input");
    input.type = ["bost", "eost"].includes(name) ? "checkbox" : "number";
    if (input.type === "checkbox") input.checked = step[name]; else input.value = String(step[name]);
    if (input.type === "number") input.step = "any";
    if (name === "voltage" || name === "current") input.min = "0";
    if (name === "dwell") { input.min = "0.01"; input.max = "3600"; }
    const update = () => { step[name] = input.type === "checkbox" ? input.checked : Number(input.value); updateSelectedCommandState(); };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
    cell.appendChild(input);
    row.appendChild(cell);
  });
  const actions = document.createElement("td");
  [["Up", -1, index === 0], ["Down", 1, index === activeTriggerListDraft().steps.length - 1], ["Remove", 0, activeTriggerListDraft().steps.length === 1]].forEach(([text, offset, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    button.disabled = disabled;
    button.addEventListener("click", () => offset === 0 ? removeTriggerListStep(index) : moveTriggerListStep(index, offset));
    actions.appendChild(button);
  });
  row.appendChild(actions);
  return row;
}

function updateTriggerListControl(definition, input) {
  const value = definition.type === "checkbox" ? input.checked : definition.type === "number" ? (input.value === "" ? null : Number(input.value)) : definition.name === "trigger_output_pins" ? parseRearPins(input.value) : input.value;
  if (definition.name === "count") activeTriggerListDraft().count = value; else state.triggerListControls[definition.name] = value;
  if (definition.name === "source" && value === "immediate") state.triggerListControls.fire = false;
  if (definition.name === "source") renderForm("trigger-list");
  updateSelectedCommandState();
}

function addTriggerListStep() {
  const steps = activeTriggerListDraft().steps;
  if (steps.length >= 100) return;
  steps.push({ ...steps[steps.length - 1] });
  renderForm("trigger-list");
  updateSelectedCommandState();
}

function removeTriggerListStep(index) {
  const steps = activeTriggerListDraft().steps;
  if (steps.length <= 1) return;
  steps.splice(index, 1);
  renderForm("trigger-list");
  updateSelectedCommandState();
}

function moveTriggerListStep(index, offset) {
  const steps = activeTriggerListDraft().steps;
  const target = index + offset;
  if (target < 0 || target >= steps.length) return;
  [steps[index], steps[target]] = [steps[target], steps[index]];
  renderForm("trigger-list");
  updateSelectedCommandState();
}

function renderRampListForm(form) {
  const editor = document.createElement("div");
  editor.className = "ramp-list-editor";
  const toolbar = document.createElement("div");
  toolbar.className = "ramp-list-toolbar";
  [
    ["Load Ramp List", loadRampList],
    ["Save Ramp List", saveRampList],
    ["Add Ramp Segment", addRampSegment]
  ].forEach(([text, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    if (text === "Save Ramp List") button.id = "save-ramp-list";
    button.disabled = text === "Add Ramp Segment" && state.rampListSegments.length >= 10;
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  editor.appendChild(toolbar);
  const enableInput = document.createElement("input");
  enableInput.type = "checkbox";
  enableInput.id = "ramp-list-enable-output";
  enableInput.checked = state.rampListEnableOutput;
  enableInput.addEventListener("change", () => {
    state.rampListEnableOutput = enableInput.checked;
    updateSelectedCommandState();
  });
  const enableLabel = createCheckboxField(enableInput, "Enable each channel", ["ramp-list-enable-output-field"]);
  configureCompactCheckboxHelp(enableLabel, enableInput, {
    ariaLabel: "Enable each channel at its first segment",
    helpId: "ramp-list-enable-output-help",
    description: "Each channel is enabled only after its first safe segment setpoint is written and verified. Outputs remain ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation."
  });
  editor.appendChild(enableLabel);
  editor.appendChild(renderLoopControl({
    prefix: "ramp-list",
    loopEnabled: state.rampListLoopEnabled,
    countDraft: state.rampListLoopCountDraft,
    onEnabled: (value) => { state.rampListLoopEnabled = value; },
    onDraft: (value) => { state.rampListLoopCountDraft = value; },
    onDisable: () => {
      if (state.rampListCompletionPulse?.timing === "loop") {
        state.rampListCompletionPulse = null;
        renderForm("ramp-list");
      }
    }
  }));
  const pulseFields = document.createElement("div");
  pulseFields.className = "ramp-segment-fields";
  [
    { name: "timing", label: "Pulse timing", type: "select", options: ["", "step", "segment", "loop"] },
    { name: "pins", label: "Rear pins", type: "select", options: REAR_PIN_OPTIONS },
    { name: "polarity", label: "Polarity", type: "select", options: ["positive", "negative"] }
  ].forEach((definition) => {
    const label = document.createElement("label");
    label.textContent = definition.label;
    const input = document.createElement(definition.type === "select" ? "select" : "input");
    if (definition.type === "select") {
      definition.options.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = definition.name === "pins"
          ? rearPinDisplayName(value)
          : pulseTimingDisplayName("ramp-list", value);
        if (definition.name === "timing" && value === "loop" && !(effectiveRampListLoopCount() >= 2)) {
          option.disabled = true;
        }
        input.appendChild(option);
      });
    } else {
      input.type = "text";
    }
    input.value = definition.name === "pins"
      ? pinsSelectValue(state.rampListCompletionPulse?.pins || [1])
      : String(state.rampListCompletionPulse?.[definition.name] || (definition.name === "polarity" ? "positive" : ""));
    input.id = `ramp-list-pulse-${definition.name}`;
    input.addEventListener("change", () => updateRampListPulse(definition.name, input.value));
    const prerequisiteReason = definition.name !== "timing" && !state.rampListCompletionPulse
      ? "Select a pulse timing to configure this field."
      : "";
    applyWorkflowPulseControlState(input, prerequisiteReason);
    label.appendChild(input);
    if (definition.name !== "timing") label.hidden = !state.rampListCompletionPulse;
    pulseFields.appendChild(label);
  });
  editor.appendChild(pulseFields);
  state.rampListSegments.forEach((segment, index) => editor.appendChild(rampSegmentCard(segment, index)));
  form.appendChild(editor);
  updateWorkflowDocumentValidity("ramp-list");
}

function rampSegmentCard(segment, index) {
  const card = document.createElement("div");
  card.className = "ramp-segment-card";
  card.dataset.rampSegmentIndex = String(index);
  const head = document.createElement("div");
  head.className = "ramp-segment-head";
  const title = document.createElement("strong");
  title.textContent = `Ramp Segment ${index + 1}`;
  const actions = document.createElement("div");
  actions.className = "ramp-segment-actions";
  [
    ["Up", () => moveRampSegment(index, -1), index === 0],
    ["Down", () => moveRampSegment(index, 1), index === state.rampListSegments.length - 1],
    ["Remove", () => removeRampSegment(index), state.rampListSegments.length === 1]
  ].forEach(([text, handler, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    button.disabled = disabled;
    button.addEventListener("click", handler);
    actions.appendChild(button);
  });
  head.append(title, actions);
  card.appendChild(head);
  const fields = document.createElement("div");
  fields.className = "ramp-segment-fields";
  rampSegmentDefinitions().forEach((definition) => {
    const label = document.createElement("label");
    label.textContent = definition.label;
    const input = document.createElement(definition.name === "channel" ? "select" : "input");
    if (definition.name === "channel") {
      ["1", "2", "3"].forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        input.appendChild(option);
      });
    } else {
      input.type = "number";
    }
    input.value = String(segment[definition.name]);
    input.dataset.rampField = definition.name;
    applyParameterConstraint(input, definition.name);
    input.addEventListener("input", () => {
      state.rampListSegments[index][definition.name] = Number(input.value);
      updateSelectedCommandState();
    });
    label.appendChild(input);
    fields.appendChild(label);
  });
  card.appendChild(fields);
  return card;
}

function rampSegmentDefinitions() {
  return [
    { name: "channel", label: "Channel" },
    { name: "current", label: "Current(A)" },
    { name: "start_voltage", label: "Start voltage(V)" },
    { name: "stop_voltage", label: "Stop voltage(V)" },
    { name: "step_voltage", label: "Step voltage(V)" },
    { name: "delay_ms", label: "Delay(ms)" },
    { name: "hold_ms", label: "Hold(ms)" }
  ];
}

function addRampSegment() {
  if (state.rampListSegments.length >= 10) return;
  const previous = state.rampListSegments[state.rampListSegments.length - 1];
  state.rampListSegments.push({
    channel: previous.channel,
    current: previous.current,
    start_voltage: previous.stop_voltage,
    stop_voltage: previous.stop_voltage,
    step_voltage: previous.step_voltage,
    delay_ms: previous.delay_ms,
    hold_ms: previous.hold_ms
  });
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function removeRampSegment(index) {
  if (state.rampListSegments.length <= 1) return;
  state.rampListSegments.splice(index, 1);
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function moveRampSegment(index, offset) {
  const target = index + offset;
  if (target < 0 || target >= state.rampListSegments.length) return;
  [state.rampListSegments[index], state.rampListSegments[target]] = [state.rampListSegments[target], state.rampListSegments[index]];
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function effectiveEnabledLoopCount(enabled, draft) {
  if (!enabled) return 1;
  const parsed = draft === "" ? Number.NaN : Number(draft);
  return Number.isInteger(parsed) && parsed >= 2 && parsed <= 255 ? parsed : Number.NaN;
}

function effectiveRampListLoopCount() {
  return effectiveEnabledLoopCount(state.rampListLoopEnabled, state.rampListLoopCountDraft);
}

function effectiveSequenceLoopCount() {
  return effectiveEnabledLoopCount(state.sequenceLoopEnabled, state.sequenceLoopCountDraft);
}

function rampListDocument() {
  const document = {
    kind: "powers-tool-ramp-list",
    version: 4,
    enable_output: state.rampListEnableOutput,
    loop_count: effectiveRampListLoopCount(),
    segments: state.rampListSegments.map((segment) => ({ ...segment }))
  };
  if (state.rampListCompletionPulse) document.completion_pulse = { ...state.rampListCompletionPulse };
  return document;
}

function validateRampListDocument(document) {
  if (!document || document.kind !== "powers-tool-ramp-list" || ![2, 3, 4].includes(document.version)) {
    throw new Error("Invalid Ramp List kind or version.");
  }
  const topLevelFields = document.version === 4
    ? ["kind", "version", "enable_output", "loop_count", "completion_pulse", "segments"]
    : document.version === 3
    ? ["kind", "version", "enable_output", "completion_pulse", "segments"]
    : ["kind", "version", "completion_pulse", "segments"];
  if (Object.keys(document).some((field) => !topLevelFields.includes(field))) {
    throw new Error("Ramp List contains unsupported fields.");
  }
  if (document.version >= 3 && typeof document.enable_output !== "boolean") {
    throw new Error("Ramp List version 3 or 4 requires boolean enable_output.");
  }
  if (!Array.isArray(document.segments) || document.segments.length < 1 || document.segments.length > 10) {
    throw new Error("Ramp List requires 1 to 10 segments.");
  }
  const fields = rampSegmentDefinitions().map((item) => item.name);
  const segments = document.segments.map((segment, index) => {
    if (!segment || Object.keys(segment).some((field) => !fields.includes(field)) || fields.some((field) => typeof segment[field] !== "number" || !Number.isFinite(segment[field]))) {
      throw new Error(`Ramp Segment ${index + 1} contains invalid fields.`);
    }
    const voltageCount = Math.ceil(Math.abs(segment.stop_voltage - segment.start_voltage) / segment.step_voltage) + 1;
    if (!Number.isInteger(segment.channel) || segment.channel < 1 || segment.channel > 3
      || segment.current < 0 || segment.start_voltage < 0 || segment.stop_voltage < 0 || segment.step_voltage <= 0
      || !Number.isInteger(segment.delay_ms) || !Number.isInteger(segment.hold_ms)
      || segment.delay_ms < 0 || segment.hold_ms < 0 || voltageCount > 1000) {
      throw new Error(`Ramp Segment ${index + 1} contains invalid limits.`);
    }
    return Object.fromEntries(fields.map((field) => [field, segment[field]]));
  });
  const loopCount = document.version === 4 ? document.loop_count : 1;
  if (!Number.isInteger(loopCount) || loopCount < 1 || loopCount > 255) throw new Error("Ramp List loop_count must be an integer from 1 to 255.");
  let completionPulse = null;
  if (document.completion_pulse !== undefined) {
    const pulse = document.completion_pulse;
    if (!pulse || !["segment", "step", "loop"].includes(pulse.timing) || !Array.isArray(pulse.pins) || !pulse.pins.length
      || pulse.pins.some((pin) => ![1, 2, 3].includes(pin)) || !["positive", "negative"].includes(pulse.polarity)) {
      throw new Error("Ramp List completion_pulse is invalid.");
    }
    if (pulse.timing === "loop" && loopCount < 2) {
      throw new Error("Ramp List Loop complete pulse requires loop_count of at least 2.");
    }
    completionPulse = { timing: pulse.timing, pins: [...pulse.pins], polarity: pulse.polarity };
  }
  return {
    segments,
    completionPulse,
    enableOutput: document.version >= 3 ? document.enable_output : false,
    loopCount
  };
}

async function loadRampList() {
  try {
    const { text } = await openJsonFile({
      description: "Ramp List JSON",
      extensions: RAMP_LIST_JSON_EXTENSIONS
    });
    const normalized = validateRampListDocument(JSON.parse(text));
    state.rampListSegments = normalized.segments;
    state.rampListCompletionPulse = normalized.completionPulse;
    state.rampListEnableOutput = normalized.enableOutput;
    state.rampListLoopEnabled = normalized.loopCount >= 2;
    state.rampListLoopCountDraft = String(normalized.loopCount >= 2 ? normalized.loopCount : 2);
    renderForm("ramp-list");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult("ramp-list", "failed", error.message || String(error), { error: "Ramp List load failed", detail: error.message || String(error) });
  }
}

async function saveRampList() {
  try {
    const document = rampListDocument();
    validateRampListDocument(document);
    const documentText = `${JSON.stringify(document, null, 2)}\n`;
    await saveJsonFile(documentText, {
      description: "Ramp List JSON",
      extensions: RAMP_LIST_JSON_EXTENSIONS,
      suggestedName: "ramp-list.ramp-list.json"
    });
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult("ramp-list", "failed", error.message || String(error), { error: "Ramp List save failed", detail: error.message || String(error) });
  }
}

function triggerListWorkspaceDocument() {
  return {
    kind: "powers-tool-trigger-list-workspace", version: 1, active_channel: state.triggerListActiveChannel,
    controls: { ...state.triggerListControls, trigger_output_pins: [...state.triggerListControls.trigger_output_pins] },
    channels: Object.fromEntries(["1", "2", "3"].map((channel) => [channel, {
      count: state.triggerListChannels[channel].count,
      steps: state.triggerListChannels[channel].steps.map((step) => ({ ...step }))
    }]))
  };
}

function validateTriggerListWorkspace(document) {
  const exact = (object, fields, label) => {
    if (!object || typeof object !== "object" || Array.isArray(object) || Object.keys(object).some((field) => !fields.includes(field)) || fields.some((field) => !(field in object))) throw new Error(`${label} contains unknown or missing fields.`);
  };
  exact(document, ["kind", "version", "active_channel", "controls", "channels"], "Trigger List workspace");
  if (document.kind !== "powers-tool-trigger-list-workspace" || document.version !== 1 || ![1, 2, 3].includes(document.active_channel)) throw new Error("Invalid Trigger List workspace kind, version, or active channel.");
  const fields = ["source", "fire", "wait_complete", "trigger_output_pins", "trigger_output_polarity", "exclusive_pins", "poll_ms", "wait_timeout_ms", "leave_trigger_configured"];
  exact(document.controls, fields, "Trigger List controls");
  const c = document.controls;
  if (!["immediate", "bus"].includes(c.source) || typeof c.fire !== "boolean" || typeof c.wait_complete !== "boolean" || typeof c.exclusive_pins !== "boolean" || typeof c.leave_trigger_configured !== "boolean" || !Array.isArray(c.trigger_output_pins) || c.trigger_output_pins.some((pin) => ![1, 2, 3].includes(pin)) || new Set(c.trigger_output_pins).size !== c.trigger_output_pins.length || !["positive", "negative"].includes(c.trigger_output_polarity) || !Number.isInteger(c.poll_ms) || c.poll_ms < 50 || !(c.wait_timeout_ms === null || (Number.isInteger(c.wait_timeout_ms) && c.wait_timeout_ms > 0))) throw new Error("Trigger List controls are invalid.");
  exact(document.channels, ["1", "2", "3"], "Trigger List channels");
  const channels = {};
  ["1", "2", "3"].forEach((channel) => {
    const draft = document.channels[channel];
    exact(draft, ["count", "steps"], `Channel ${channel}`);
    if (!Number.isInteger(draft.count) || draft.count < 1 || draft.count > 256 || !Array.isArray(draft.steps) || draft.steps.length < 1 || draft.steps.length > 100) throw new Error(`Channel ${channel} has invalid count or step count.`);
    channels[channel] = { count: draft.count, steps: draft.steps.map((step, index) => {
      exact(step, ["voltage", "current", "dwell", "bost", "eost"], `Channel ${channel} step ${index + 1}`);
      if (![step.voltage, step.current, step.dwell].every((value) => typeof value === "number" && Number.isFinite(value)) || step.voltage < 0 || step.current < 0 || step.dwell < 0.01 || step.dwell > 3600 || typeof step.bost !== "boolean" || typeof step.eost !== "boolean") throw new Error(`Channel ${channel} step ${index + 1} is invalid.`);
      return { ...step };
    }) };
  });
  return { activeChannel: document.active_channel, controls: { ...c, trigger_output_pins: [...c.trigger_output_pins] }, channels };
}

async function loadTriggerListWorkspace() {
  try {
    const { text } = await openJsonFile({ description: "Trigger List Workspace JSON", extensions: TRIGGER_LIST_WORKSPACE_JSON_EXTENSIONS });
    const normalized = validateTriggerListWorkspace(JSON.parse(text));
    state.triggerListActiveChannel = normalized.activeChannel;
    state.triggerListControls = normalized.controls;
    state.triggerListChannels = normalized.channels;
    renderForm("trigger-list");
    updateSelectedCommandState();
  } catch (error) {
    if (!isAbortError(error)) renderClientResult("trigger-list", "failed", error.message || String(error), { error: "Trigger List load failed", detail: error.message || String(error) });
  }
}

async function saveTriggerListWorkspace() {
  try {
    await saveJsonFile(`${JSON.stringify(triggerListWorkspaceDocument(), null, 2)}\n`, { description: "Trigger List Workspace JSON", extensions: TRIGGER_LIST_WORKSPACE_JSON_EXTENSIONS, suggestedName: "trigger-list.trigger-list-workspace.json" });
  } catch (error) {
    if (!isAbortError(error)) renderClientResult("trigger-list", "failed", error.message || String(error), { error: "Trigger List save failed", detail: error.message || String(error) });
  }
}

/* ==========================================
   Shared JSON File Helpers
   ========================================== */

const JSON_MIME_TYPE = "application/json";
const SNAPSHOT_JSON_EXTENSIONS = [".snapshot.json", ".json"];
const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];
const RAMP_LIST_JSON_EXTENSIONS = [".ramp-list.json", ".json"];
const TRIGGER_LIST_WORKSPACE_JSON_EXTENSIONS = [".trigger-list-workspace.json", ".json"];

function buildNativeJsonPickerAccept() {
  return { [JSON_MIME_TYPE]: [".json"] };
}

async function openJsonFile({ description, extensions }) {
  let text = "";
  let filename = "";
  const acceptMap = buildNativeJsonPickerAccept();
  if (window.showOpenFilePicker) {
    const [handle] = await window.showOpenFilePicker({
      types: [{ description, accept: acceptMap }],
      multiple: false
    });
    const file = await handle.getFile();
    text = await file.text();
    filename = file.name;
  } else {
    const fileInfo = await chooseJsonFile(buildJsonFileAccept(extensions));
    text = fileInfo.text;
    filename = fileInfo.name;
  }
  return { text, filename };
}

function buildJsonFileAccept(extensions) {
  return [...extensions, JSON_MIME_TYPE].join(",");
}

function chooseJsonFile(accept) {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    let settled = false;
    let focusTimer = null;

    const cleanup = () => {
      window.clearTimeout(focusTimer);
      input.removeEventListener("change", onChange);
      input.removeEventListener("cancel", abort);
      window.removeEventListener("focus", onWindowFocus);
      input.remove();
    };
    const settle = (callback, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback(value);
    };
    const abort = () => settle(reject, abortError("File selection cancelled."));
    const onWindowFocus = () => {
      window.clearTimeout(focusTimer);
      focusTimer = window.setTimeout(() => {
        if (!settled && (!input.files || input.files.length === 0)) abort();
      }, 0);
    };
    const onChange = async () => {
      try {
        if (!input.files?.[0]) {
          abort();
          return;
        }
        const file = input.files[0];
        const text = await file.text();
        settle(resolve, { text, name: file.name });
      } catch (error) {
        settle(reject, error);
      }
    };

    input.type = "file";
    input.accept = accept;
    input.style.display = "none";
    input.addEventListener("change", onChange);
    input.addEventListener("cancel", abort);
    window.addEventListener("focus", onWindowFocus, { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

async function saveJsonFile(text, { description, extensions, suggestedName }) {
  const acceptMap = buildNativeJsonPickerAccept();
  if (window.showSaveFilePicker) {
    const handle = await window.showSaveFilePicker({
      suggestedName,
      types: [{ description, accept: acceptMap }]
    });
    const writable = await handle.createWritable();
    await writable.write(text);
    await writable.close();
    return;
  }
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = suggestedName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function abortError(message) {
  if (typeof DOMException === "function") {
    return new DOMException(message, "AbortError");
  }
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

/* ==========================================
   Snapshot Feature
   ========================================== */

function renderSnapshotForm(form) {
  const editor = document.createElement("div");
  editor.className = "artifact-editor";

  const toolbar = document.createElement("div");
  toolbar.className = "artifact-toolbar";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "secondary";
  saveBtn.id = "btn-save-snapshot";
  saveBtn.textContent = "Save Snapshot";
  saveBtn.disabled = !state.latestSnapshotDocument;
  saveBtn.addEventListener("click", saveSnapshot);
  toolbar.appendChild(saveBtn);

  const statusNote = document.createElement("span");
  statusNote.id = "snapshot-status-note";
  statusNote.className = "artifact-file-status";

  const snapshotJob = state.jobs.find(j => j.command === "snapshot" && (j.status === "accepted" || j.status === "started" || j.status === "progress"));
  const inProgress = Boolean(snapshotJob);

  if (state.latestSnapshotDocument) {
    const meta = state.latestSnapshotMetadata;
    const timeStr = meta && meta.savedAt ? new Date(meta.savedAt).toLocaleTimeString() : "";
    if (inProgress) {
      statusNote.textContent = `Previous successful snapshot available while a new snapshot is running. (${meta?.model || "unknown"}, ${timeStr})`;
    } else {
      statusNote.textContent = `Latest successful snapshot available (${meta?.model || "unknown"}, ${timeStr})`;
    }
  } else {
    statusNote.textContent = inProgress ? "Snapshot in progress..." : "No successful snapshot captured in this session.";
  }
  toolbar.appendChild(statusNote);
  editor.appendChild(toolbar);

  (PARAMS["snapshot"] || []).forEach((param) => {
    const label = document.createElement("label");
    label.textContent = param.label;
    const input = document.createElement("input");
    input.type = param.type;
    input.id = `param-${param.name}`;
    if (param.value !== undefined) input.value = param.value;
    input.addEventListener("change", updateSelectedCommandState);
    label.appendChild(input);
    appendFieldDescription(label, param);
    editor.appendChild(label);
  });

  form.appendChild(editor);
}

function refreshSnapshotFormIfVisible(jobId = null) {
  if (state.selected !== "snapshot") return;

  if (jobId !== null && jobCommand(jobId) !== "snapshot") {
    return;
  }

  renderForm("snapshot");
  updateSelectedCommandState();
}

async function saveSnapshot() {
  if (!state.latestSnapshotDocument) {
    renderClientResult("snapshot", "failed", "No snapshot available to save.", { error: "Snapshot save failed", detail: "No snapshot available to save." });
    return;
  }
  try {
    validateSnapshotDocument(state.latestSnapshotDocument);
    const documentText = `${JSON.stringify(state.latestSnapshotDocument, null, 2)}\n`;
    const suggestedName = getSnapshotSuggestedName();
    await saveJsonFile(documentText, {
      description: "Powers Tool Snapshot JSON",
      extensions: SNAPSHOT_JSON_EXTENSIONS,
      suggestedName
    });
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "snapshot",
      "failed",
      error.message || String(error),
      {
        error: "Snapshot save failed",
        detail: error.message || String(error),
        command: "snapshot"
      }
    );
  }
}

function getSnapshotSuggestedName() {
  const doc = state.latestSnapshotDocument;
  const meta = state.latestSnapshotMetadata;
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;

  let model = meta?.model || doc?.reported_identity?.model;
  let serial = meta?.serial || doc?.reported_identity?.serial;

  const clean = (str) => {
    if (!str) return "";
    return String(str).replace(/[<>:"/\\|?*]/g, "").trim();
  };

  model = clean(model);
  serial = clean(serial);

  if (model && serial) {
    return `powers-tool-${model}-${serial}-${timestamp}.snapshot.json`;
  }
  return `powers-tool-snapshot-${timestamp}.snapshot.json`;
}

function validateSnapshotDocument(doc) {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("Snapshot document must be a JSON object.");
  }
  if (doc.schema_version !== 2 || doc.kind !== "powers-tool-snapshot") {
    throw new Error("Snapshot must use schema_version 2 and kind 'powers-tool-snapshot'.");
  }
  if (!doc.reported_identity || typeof doc.reported_identity !== "object" || Array.isArray(doc.reported_identity)) {
    throw new Error("Snapshot must contain a valid 'reported_identity' object.");
  }
  if (!doc.resolved_identity || typeof doc.resolved_identity !== "object" || Array.isArray(doc.resolved_identity)) {
    throw new Error("Snapshot must contain a valid 'resolved_identity' object.");
  }
  if (!Array.isArray(doc.readback)) {
    throw new Error("Snapshot 'readback' must be an array.");
  }
  if (!Array.isArray(doc.outputs)) {
    throw new Error("Snapshot 'outputs' must be an array.");
  }
}

/* ==========================================
   Restore from Snapshot Feature
   ========================================== */

function renderRestoreForm(form) {
  const editor = document.createElement("div");
  editor.className = "artifact-editor";

  const toolbar = document.createElement("div");
  toolbar.className = "artifact-toolbar";

  const loadBtn = document.createElement("button");
  loadBtn.type = "button";
  loadBtn.className = "secondary";
  loadBtn.id = "btn-load-snapshot";
  loadBtn.textContent = "Load Snapshot";
  loadBtn.addEventListener("click", loadRestoreSnapshot);
  toolbar.appendChild(loadBtn);

  const fileStatus = document.createElement("span");
  fileStatus.id = "restore-file-status";
  fileStatus.className = "artifact-file-status";
  fileStatus.textContent = state.loadedSnapshotFilename
    ? `Loaded file: ${state.loadedSnapshotFilename}`
    : "No snapshot loaded";
  toolbar.appendChild(fileStatus);
  editor.appendChild(toolbar);

  // Channel Select
  const channelLabel = document.createElement("label");
  channelLabel.textContent = "Channel";
  const channelSelect = document.createElement("select");
  channelSelect.id = "param-channel";
  ["all", "1", "2", "3"].forEach((ch) => {
    const opt = document.createElement("option");
    opt.value = ch;
    opt.textContent = optionDisplayName(ch);
    channelSelect.appendChild(opt);
  });
  channelSelect.value = state.restoreChannel;
  channelSelect.addEventListener("change", (e) => {
    state.restoreChannel = e.target.value;
    clearRestorePlanPreview();
    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
  });
  channelLabel.appendChild(channelSelect);
  editor.appendChild(channelLabel);

  // Restore previous output state Checkbox
  const restoreStateCheck = document.createElement("input");
  restoreStateCheck.type = "checkbox";
  restoreStateCheck.id = "param-restore_output_state";
  restoreStateCheck.checked = state.restoreOutputState;
  restoreStateCheck.addEventListener("change", (e) => {
    state.restoreOutputState = e.target.checked;
    clearRestorePlanPreview();
    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
  });
  const restoreStateLabel = createCheckboxField(restoreStateCheck, "Restore previous output ON/OFF state");
  editor.appendChild(restoreStateLabel);

  const warningNote = document.createElement("div");
  warningNote.style.color = "var(--muted)";
  warningNote.style.fontSize = "0.9em";
  warningNote.style.marginBottom = "8px";
  warningNote.textContent = "When enabled, channels that were ON in the snapshot may be turned ON after restoring settings.";
  editor.appendChild(warningNote);

  const previewPlanBtn = document.createElement("button");
  previewPlanBtn.type = "button";
  previewPlanBtn.className = "secondary";
  previewPlanBtn.id = "btn-preview-restore-plan";
  previewPlanBtn.textContent = "Preview restore plan";
  previewPlanBtn.disabled = !isLoadedRestoreSnapshotValid() || state.restorePlanPreviewStatus === "running";
  previewPlanBtn.addEventListener("click", previewRestorePlan);
  editor.appendChild(previewPlanBtn);

  const planExplanation = document.createElement("p");
  planExplanation.className = "restore-plan-explanation";
  planExplanation.textContent = "Shows the exact restore steps without opening VISA, locking hardware, or changing the instrument.";
  editor.appendChild(planExplanation);

  const planPreview = document.createElement("div");
  planPreview.id = "restore-plan-preview";
  planPreview.className = `restore-plan-preview ${state.restorePlanPreviewStatus}`;
  renderRestorePlanPreview(planPreview);
  editor.appendChild(planPreview);

  form.appendChild(editor);
}

async function loadRestoreSnapshot() {
  try {
    const { text, filename } = await openJsonFile({
      description: "Powers Tool Snapshot JSON",
      extensions: SNAPSHOT_JSON_EXTENSIONS
    });
    const rawDoc = JSON.parse(text);
    validateRestoreSnapshot(rawDoc);

    state.loadedSnapshotDocument = rawDoc;
    state.loadedSnapshotFilename = filename;
    clearRestorePlanPreview();

    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "restore-from-snapshot",
      "failed",
      error.message || String(error),
      {
        error: "Snapshot load failed",
        detail: error.message || String(error),
        command: "restore-from-snapshot"
      }
    );
  }
}

async function previewRestorePlan() {
  try {
    validateRestoreSnapshot(state.loadedSnapshotDocument);
    state.restorePlanPreviewStatus = "running";
    state.restorePlanPreview = null;
    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
    const payload = {
      command: "restore-from-snapshot",
      runtime: {
        ...runtimePayload(),
        dry_run: true,
        confirm: true
      },
      parameters: restoreSnapshotParameters(state.loadedSnapshotDocument)
    };
    const response = await submitJob(payload);
    addHistory(response.job_id, "restore-from-snapshot", "accepted", "Restore plan preview");
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    state.restorePlanPreviewStatus = "failed";
    state.restorePlanPreview = { error: error.message || String(error) };
    if (state.selected === "restore-from-snapshot") renderForm("restore-from-snapshot");
    renderClientResult(
      "Restore plan preview",
      "failed",
      error.message || String(error),
      {
        error: "Restore plan preview failed",
        detail: error.message || String(error),
        command: "restore-from-snapshot"
      }
    );
  }
}

function renderRestorePlanPreview(container) {
  if (state.restorePlanPreviewStatus === "running") {
    container.textContent = "Generating restore plan...";
    return;
  }
  if (state.restorePlanPreviewStatus === "failed") {
    container.textContent = `Could not generate restore plan: ${state.restorePlanPreview?.error || "Unknown error"}`;
    return;
  }
  const plan = state.restorePlanPreview?.plan;
  if (!plan || !Array.isArray(plan.steps)) {
    container.textContent = "No restore plan generated yet.";
    return;
  }
  const heading = document.createElement("strong");
  heading.textContent = `Restore plan: ${plan.steps.length} steps (preview only)`;
  const safety = document.createElement("p");
  safety.textContent = "No VISA connection was opened and no instrument settings were changed.";
  const list = document.createElement("ol");
  plan.steps.forEach((step) => {
    const item = document.createElement("li");
    const action = String(step.action || "action").replace(/_/g, " ");
    const actionLabel = document.createElement("span");
    actionLabel.textContent = action;
    const command = document.createElement("code");
    command.textContent = step.command || "";
    item.append(actionLabel, command);
    list.appendChild(item);
  });
  container.append(heading, safety, list);
}

function clearRestorePlanPreview() {
  state.restorePlanPreviewStatus = "idle";
  state.restorePlanPreview = null;
}

function isLoadedRestoreSnapshotValid() {
  try {
    validateRestoreSnapshot(state.loadedSnapshotDocument);
    return true;
  } catch (error) {
    return false;
  }
}

function validateRestoreSnapshot(doc) {
  validateSnapshotDocument(doc);
  if (!doc.reported_identity.model || !doc.resolved_identity.model_id) {
    throw new Error("Snapshot must contain reported and resolved model identity.");
  }
  if (doc.readback.length === 0) {
    throw new Error("Snapshot must contain at least one channel in readback.");
  }
  if (doc.outputs.length === 0) {
    throw new Error("Snapshot must contain at least one channel in outputs.");
  }
  if (doc.protection_settings && !Array.isArray(doc.protection_settings)) {
    throw new Error("Snapshot 'protection_settings' must be an array.");
  }

  // Validate readback channels and setpoints.
  const readbackChannels = new Set();
  doc.readback.forEach((item, index) => {
    if (!item || typeof item !== "object") {
      throw new Error(`Snapshot readback item at index ${index} must be an object.`);
    }
    const channel = item.channel;
    if (channel === undefined || !Number.isInteger(channel) || channel < 1 || channel > 3) {
      throw new Error(`Snapshot readback item at index ${index} must have a valid 'channel' (1, 2, or 3).`);
    }
    if (readbackChannels.has(channel)) {
      throw new Error(`Snapshot readback contains duplicate channel ${channel}.`);
    }
    readbackChannels.add(channel);

    if (!item.setpoints || typeof item.setpoints !== "object") {
      throw new Error(`Snapshot readback item at channel ${channel} is missing a valid 'setpoints' object.`);
    }
    const { voltage, current } = item.setpoints;
    if (voltage === undefined || current === undefined || typeof voltage !== "number" || typeof current !== "number" || !Number.isFinite(voltage) || !Number.isFinite(current)) {
      throw new Error(`Snapshot readback item at channel ${channel} 'setpoints' must contain finite numbers for 'voltage' and 'current'.`);
    }
  });

  // Validate outputs channels and enabled state.
  const outputsChannels = new Set();
  doc.outputs.forEach((item, index) => {
    if (!item || typeof item !== "object") {
      throw new Error(`Snapshot outputs item at index ${index} must be an object.`);
    }
    const channel = item.channel;
    if (channel === undefined || !Number.isInteger(channel) || channel < 1 || channel > 3) {
      throw new Error(`Snapshot outputs item at index ${index} must have a valid 'channel' (1, 2, or 3).`);
    }
    if (outputsChannels.has(channel)) {
      throw new Error(`Snapshot outputs contains duplicate channel ${channel}.`);
    }
    outputsChannels.add(channel);

    if (item.enabled === undefined || typeof item.enabled !== "boolean") {
      throw new Error(`Snapshot outputs item at channel ${channel} must contain a boolean 'enabled' property.`);
    }
  });

  if (doc.resolved_identity.model_id !== "keysight-e36312a") {
    throw new Error(`Snapshot model_id '${doc.resolved_identity.model_id}' is not supported. Only 'keysight-e36312a' is supported for restore.`);
  }
}

/* ==========================================
   Sequence Feature
   ========================================== */

function renderSequenceForm(form) {
  const editor = document.createElement("div");
  editor.className = "sequence-editor";
  const toolbar = document.createElement("div");
  toolbar.className = "sequence-toolbar";
  [
    ["Load Sequence", loadSequenceFile],
    ["Save Sequence", saveSequenceFile],
    ["Add Step", addSequenceStep]
  ].forEach(([text, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    if (text === "Save Sequence") button.id = "save-sequence";
    button.disabled = text === "Add Step" && state.sequenceSteps.length >= sequenceMaxSteps();
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  const count = document.createElement("span");
  count.className = "sequence-step-count";
  count.textContent = `${state.sequenceSteps.length} / ${sequenceMaxSteps()}`;
  toolbar.appendChild(count);
  if (state.sequenceFilename) {
    const fileStatus = document.createElement("span");
    fileStatus.className = "artifact-file-status";
    fileStatus.textContent = state.sequenceFilename;
    toolbar.appendChild(fileStatus);
  }
  editor.appendChild(toolbar);
  editor.appendChild(renderLoopControl({
    prefix: "sequence",
    loopEnabled: state.sequenceLoopEnabled,
    countDraft: state.sequenceLoopCountDraft,
    onEnabled: (value) => { state.sequenceLoopEnabled = value; },
    onDraft: (value) => { state.sequenceLoopCountDraft = value; }
  }));
  state.sequenceSteps.forEach((step, index) => editor.appendChild(sequenceStepCard(step, index)));
  form.appendChild(editor);
  updateWorkflowDocumentValidity("sequence");
}

const SEQUENCE_ACTIONS = [
  "measure", "readback", "output-state", "log", "wait", "safe-off",
  "set", "output-on", "output-off", "cycle-output", "apply", "trigger-pulse"
];

function sequenceMaxSteps() {
  return Number(state.commands.sequence?.max_steps) || 250;
}

function sequenceActionDefinitions(action) {
  const channel = (all = false) => ({
    name: "channel", label: "Channel", type: "select",
    options: all ? ["all", "1", "2", "3"] : ["1", "2", "3"],
    value: "1"
  });
  return {
    measure: [channel()],
    readback: [channel()],
    "output-state": [channel(true)],
    log: [{ name: "message", label: "Message", type: "text", value: "" }],
    wait: [{ name: "seconds", label: "Seconds", type: "number", value: 0 }],
    "safe-off": [channel(true)],
    set: [channel(), { name: "voltage", label: "Voltage(V)", type: "number", value: 0 }, { name: "current", label: "Current(A)", type: "number", value: 0 }],
    "output-on": [channel(true)],
    "output-off": [channel(true)],
    "cycle-output": [channel(true), { name: "duration_ms", label: "Duration(ms)", type: "number", value: 500 }],
    apply: [channel(true), { name: "voltage", label: "Voltage(V)", type: "number", value: 0 }, { name: "current", label: "Current(A)", type: "number", value: 0 }, { name: "no_output", label: "Do not enable output", type: "checkbox", value: false }],
    "trigger-pulse": [channel(), { name: "pins", label: "Rear pins", type: "select", options: REAR_PIN_OPTIONS, value: [1] }, { name: "polarity", label: "Polarity", type: "select", options: ["positive", "negative"], value: "positive" }, { name: "leave_trigger_configured", label: "Leave configured", type: "checkbox", value: false, description: "Controls whether Trigger and rear-pin settings are restored after the pulse completes. It does not keep a trigger armed. Enabling it may affect later Sequence steps or other BUS triggers." }]
  }[action] || [];
}

function defaultSequenceStep(action = "wait", previous = {}) {
  const step = { action };
  sequenceActionDefinitions(action).forEach((field) => {
    step[field.name] = field.name === "channel" && previous.channel !== undefined
      && field.options.includes(String(previous.channel))
      ? previous.channel
      : field.value;
  });
  return step;
}

function sequenceStepCard(step, index) {
  const card = document.createElement("div");
  card.className = "sequence-step-card";
  card.dataset.sequenceStepIndex = String(index);
  const head = document.createElement("div");
  head.className = "sequence-step-head";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "secondary";
  toggle.textContent = state.sequenceExpanded.has(index) ? "Collapse" : "Expand";
  toggle.addEventListener("click", () => {
    if (state.sequenceExpanded.has(index)) state.sequenceExpanded.delete(index);
    else state.sequenceExpanded.add(index);
    renderForm("sequence");
  });
  const title = document.createElement("strong");
  title.textContent = `Step ${index + 1}: ${step.action}`;
  const summary = document.createElement("span");
  summary.className = "sequence-step-summary";
  summary.textContent = sequenceStepSummary(step);
  const actions = document.createElement("div");
  actions.className = "sequence-step-actions";
  [
    ["Up", () => moveSequenceStep(index, -1), index === 0],
    ["Down", () => moveSequenceStep(index, 1), index === state.sequenceSteps.length - 1],
    ["Remove", () => removeSequenceStep(index), state.sequenceSteps.length === 1]
  ].forEach(([text, handler, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    button.disabled = disabled;
    button.addEventListener("click", handler);
    actions.appendChild(button);
  });
  head.append(toggle, title, summary, actions);
  card.appendChild(head);
  if (state.sequenceExpanded.has(index)) {
    card.appendChild(sequenceStepFields(step, index, card, title, summary));
    renderSequenceStepError(card, step, index);
  }
  return card;
}

function sequenceStepFields(step, index, card, title, summary) {
  const fields = document.createElement("div");
  fields.className = "sequence-step-fields";
  const actionLabel = document.createElement("label");
  actionLabel.textContent = "Action";
  const actionSelect = document.createElement("select");
  SEQUENCE_ACTIONS.forEach((action) => {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = optionDisplayName(action);
    actionSelect.appendChild(option);
  });
  actionSelect.value = step.action;
  actionSelect.addEventListener("change", () => {
    state.sequenceSteps[index] = defaultSequenceStep(actionSelect.value, step);
    const replacement = sequenceStepCard(state.sequenceSteps[index], index);
    card.replaceWith(replacement);
    updateSelectedCommandState();
  });
  actionLabel.appendChild(actionSelect);
  fields.appendChild(actionLabel);
  sequenceActionDefinitions(step.action).forEach((definition) => {
    const input = document.createElement(definition.type === "select" ? "select" : "input");
    if (definition.type === "select") {
      definition.options.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value);
        input.appendChild(option);
      });
    } else {
      input.type = definition.type;
    }
    if (definition.type === "checkbox") input.checked = Boolean(step[definition.name]);
    else input.value = definition.name === "pins"
      ? pinsSelectValue(step[definition.name] ?? definition.value)
      : String(step[definition.name] ?? definition.value);
    input.dataset.sequenceField = definition.name;
    applyParameterConstraint(input, definition.name);
    if (step.action === "trigger-pulse") applyWorkflowPulseControlState(input);
    input.addEventListener("input", () => {
      step[definition.name] = sequenceFieldValue(definition, input);
      summary.textContent = sequenceStepSummary(step);
      title.textContent = `Step ${index + 1}: ${step.action}`;
      renderSequenceStepError(card, step, index);
      updateSelectedCommandState();
    });
    input.addEventListener("change", () => {
      step[definition.name] = sequenceFieldValue(definition, input);
      summary.textContent = sequenceStepSummary(step);
      renderSequenceStepError(card, step, index);
      updateSelectedCommandState();
    });
    const label = definition.type === "checkbox"
      ? createCheckboxField(input, definition.label)
      : document.createElement("label");
    if (definition.type !== "checkbox") {
      label.textContent = definition.label;
      label.appendChild(input);
    }
    appendFieldDescription(label, definition);
    fields.appendChild(label);
  });
  return fields;
}

function sequenceFieldValue(definition, input) {
  if (definition.type === "checkbox") return input.checked;
  if (definition.type === "number") return Number(input.value);
  if (definition.name === "channel" && input.value !== "all") return Number(input.value);
  if (definition.name === "pins") return parseRearPins(input.value);
  return input.value;
}

function sequenceStepSummary(step) {
  return Object.entries(step)
    .filter(([key]) => key !== "action")
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
}

function renderSequenceStepError(card, step, index) {
  const previous = card.querySelector?.(".sequence-step-error");
  if (previous) previous.remove();
  try {
    validateCanonicalSequenceStep(step, index);
    card.classList?.remove("invalid");
  } catch (error) {
    card.classList?.add("invalid");
    const message = document.createElement("div");
    message.className = "sequence-step-error";
    message.textContent = error.message || String(error);
    card.appendChild(message);
  }
}

function addSequenceStep() {
  if (state.sequenceSteps.length >= sequenceMaxSteps()) return;
  state.sequenceSteps.push(defaultSequenceStep());
  renderForm("sequence");
  updateSelectedCommandState();
}

function removeSequenceStep(index) {
  if (state.sequenceSteps.length <= 1) return;
  state.sequenceSteps.splice(index, 1);
  state.sequenceExpanded = new Set();
  renderForm("sequence");
  updateSelectedCommandState();
}

function moveSequenceStep(index, offset) {
  const target = index + offset;
  if (target < 0 || target >= state.sequenceSteps.length) return;
  [state.sequenceSteps[index], state.sequenceSteps[target]] = [state.sequenceSteps[target], state.sequenceSteps[index]];
  state.sequenceExpanded = new Set();
  renderForm("sequence");
  updateSelectedCommandState();
}

async function loadSequenceFile() {
  try {
    const { text, filename } = await openJsonFile({
      description: "Powers Tool Sequence JSON",
      extensions: SEQUENCE_JSON_EXTENSIONS
    });
    const rawDoc = JSON.parse(text);
    const normalized = normalizeSequenceDocument(rawDoc);
    state.sequenceSteps = normalized.steps;
    state.sequenceLoopEnabled = normalized.loopCount >= 2;
    state.sequenceLoopCountDraft = String(normalized.loopCount >= 2 ? normalized.loopCount : 2);
    state.sequenceExpanded = new Set();
    state.sequenceFilename = filename;
    renderForm("sequence");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "sequence",
      "failed",
      error.message || String(error),
      {
        error: "Sequence load failed",
        detail: error.message || String(error),
        command: "sequence"
      }
    );
  }
}

async function saveSequenceFile() {
  try {
    const documentText = `${JSON.stringify(sequenceDocumentFromEditor(), null, 2)}\n`;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const suggestedName = `powers-tool-sequence-${timestamp}.sequence.json`;

    await saveJsonFile(documentText, {
      description: "Powers Tool Sequence JSON",
      extensions: SEQUENCE_JSON_EXTENSIONS,
      suggestedName
    });
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "sequence",
      "failed",
      error.message || String(error),
      {
        error: "Sequence save failed",
        detail: error.message || String(error),
        command: "sequence"
      }
    );
  }
}

function normalizeSequenceDocument(doc) {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new Error("Sequence document must be a JSON object.");
  if (doc.version !== undefined && doc.version !== 1 && doc.version !== "1" && doc.version !== 2) throw new Error("Sequence version must be 1 or 2.");
  const version = doc.version ?? 1;
  const allowedFields = version === 2 ? ["version", "steps", "loop_count"] : ["version", "steps"];
  if (Object.keys(doc).some((field) => !allowedFields.includes(field))) throw new Error("Sequence document contains unsupported fields.");
  if (!Array.isArray(doc.steps) || doc.steps.length === 0) throw new Error("Sequence document must contain a non-empty 'steps' array.");
  if (doc.steps.length > sequenceMaxSteps()) throw new Error(`Sequence supports at most ${sequenceMaxSteps()} steps in the WebUI.`);
  const loopCount = doc.version === 2 ? doc.loop_count : 1;
  if (!Number.isInteger(loopCount) || loopCount < 1 || loopCount > 255) throw new Error("Sequence loop_count must be an integer from 1 to 255.");
  return { version: 2, loopCount, steps: doc.steps.map(normalizeSequenceStep) };
}

function normalizeSequenceStep(step, index) {
  if (!step) throw new Error(`Sequence step at index ${index} is null or empty.`);
  let action;
  let parameters = {};
  if (typeof step === "string") {
    action = step;
  } else if (typeof step === "object" && !Array.isArray(step)) {
    const keys = Object.keys(step);
    if ("action" in step || "type" in step) {
      if ("action" in step && "type" in step && step.action !== step.type) throw new Error(`Step ${index + 1} has conflicting action and type values.`);
      action = step.action ?? step.type;
      parameters = Object.fromEntries(Object.entries(step).filter(([key]) => !["action", "type"].includes(key)));
    } else if (keys.length === 1) {
      action = keys[0];
      parameters = typeof step[action] === "object" && step[action] !== null && !Array.isArray(step[action]) ? step[action] : {};
    } else {
      throw new Error(`Step ${index + 1} is invalid. Objects with multiple keys must contain an action or type property.`);
    }
  } else {
    throw new Error(`Invalid step format at index ${index + 1}.`);
  }
  if (!SEQUENCE_ACTIONS.includes(action)) {
    if (action === "delay") throw new Error(`Unsupported sequence action "delay" at step ${index + 1}. Did you mean "wait"?`);
    throw new Error(`Unsupported shorthand sequence action "${action}" at step ${index + 1}.`);
  }
  if (action === "wait" && "duration_sec" in parameters) {
    if ("seconds" in parameters && parameters.seconds !== parameters.duration_sec) {
      throw new Error(`Sequence step ${index + 1} has conflicting seconds and duration_sec values.`);
    }
    parameters = { ...parameters, seconds: parameters.duration_sec };
    delete parameters.duration_sec;
  }
  const allowed = new Set(sequenceActionDefinitions(action).map((field) => field.name));
  if (Object.keys(parameters).some((field) => !allowed.has(field))) throw new Error(`Sequence step ${index + 1} contains unsupported fields.`);
  if (["set", "apply"].includes(action) && (!("voltage" in parameters) || !("current" in parameters))) {
    throw new Error(`Sequence step ${index + 1} requires voltage and current.`);
  }
  const normalized = defaultSequenceStep(action, parameters);
  Object.entries(parameters).forEach(([key, value]) => { normalized[key] = value; });
  if (normalized.channel !== undefined && normalized.channel !== "all") normalized.channel = Number(normalized.channel);
  if (action === "trigger-pulse") normalized.pins = parseRearPins(normalized.pins);
  validateCanonicalSequenceStep(normalized, index);
  return normalized;
}

function validateCanonicalSequenceStep(step, index) {
  const fields = sequenceActionDefinitions(step.action);
  const allowed = new Set(["action", ...fields.map((field) => field.name)]);
  if (Object.keys(step).some((field) => !allowed.has(field))) throw new Error(`Sequence step ${index + 1} contains unsupported fields.`);
  fields.forEach((field) => {
    const value = step[field.name];
    if (field.type === "number" && (typeof value !== "number" || !Number.isFinite(value))) throw new Error(`Sequence step ${index + 1} requires a finite ${field.name}.`);
    if (field.type === "select" && !field.options.includes(String(value))) throw new Error(`Sequence step ${index + 1} has an invalid ${field.name}.`);
    if (field.type === "checkbox" && typeof value !== "boolean") throw new Error(`Sequence step ${index + 1} requires a boolean ${field.name}.`);
    if (field.type === "text" && typeof value !== "string") throw new Error(`Sequence step ${index + 1} requires a string ${field.name}.`);
  });
  if (step.action === "wait" && step.seconds < 0) throw new Error(`Sequence step ${index + 1} wait seconds must be non-negative.`);
  if (step.action === "cycle-output" && step.duration_ms < 0) throw new Error(`Sequence step ${index + 1} duration_ms must be non-negative.`);
  if (step.action === "trigger-pulse" && (!Array.isArray(step.pins) || !step.pins.length || step.pins.some((pin) => ![1, 2, 3].includes(pin)))) {
    throw new Error(`Sequence step ${index + 1} rear pins must contain 1, 2, or 3.`);
  }
}

function sequenceDocumentFromEditor() {
  const normalized = normalizeSequenceDocument({
    version: 2,
    loop_count: effectiveSequenceLoopCount(),
    steps: state.sequenceSteps
  });
  return {
    version: 2,
    loop_count: normalized.loopCount,
    steps: normalized.steps
  };
}

async function scanResources() {
  if (isNoHardwareMode()) {
    renderClientResult("Scan Device", "failed", "Scan Device is available only in Real hardware mode.", { error: "Real mode required" });
    return;
  }
  try {
    const payload = {
      command: "list-resources",
      runtime: runtimePayload(),
      parameters: { live_only: true }
    };
    const response = await fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    addHistory(response.job_id, "list-resources", "accepted", "Scan Device");
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    console.error("Scan resources failed", error);
    renderClientResult("Scan Device", "failed", error.message || String(error), {
      error: "Scan resources failed",
      detail: error.message || String(error)
    });
  }
}

function toggleAdvancedCommands() {
  const panel = document.getElementById("advanced-commands");
  setAdvancedCommandsExpanded(panel.hidden);
}

function setAdvancedCommandsExpanded(expanded) {
  const panel = document.getElementById("advanced-commands");
  const button = document.getElementById("advanced-command-toggle");
  panel.hidden = !expanded;
  panel.classList.toggle("collapsed", !expanded);
  button.textContent = expanded ? "Hide commands" : "Show more commands";
  button.setAttribute("aria-expanded", String(expanded));
}

async function runBasicSet(channel) {
  const actionKey = basicActionKey("set", channel);
  const unsupported = channelUnsupportedReason(channel);
  if (unsupported) {
    failBasicAction(actionKey, "Unsupported channel", unsupported, { channel, label: `Basic CH${channel} Set` });
    return;
  }
  const values = basicSetpointValues(channel);
  if (!values.ok) {
    failBasicAction(actionKey, "Invalid setpoint", values.message, { channel, label: `Basic CH${channel} Set` });
    return;
  }
  await submitBasicJob("set", { channel, ...values.parameters }, actionKey, `Basic CH${channel} Set`);
}

async function runBasicOutput(channel) {
  const unsupported = channelUnsupportedReason(channel);
  if (unsupported) {
    failBasicAction(basicActionKey("output", channel), "Unsupported channel", unsupported, { channel, label: `Basic CH${channel} Output` });
    return;
  }
  if (basicOutputPresentation().mode !== "ordinary") return;
  if (basicOutputLockAction(channel)) return;
  const current = state.executionMode === "real" && basicLiveChannel(channel)?.output_enabled === true;
  const command = current ? "output-off" : "output-on";
  const desiredOutput = !current;
  await submitBasicJob(command, { channel }, basicActionKey("output", channel), `Basic CH${channel} ${desiredOutput ? "ON" : "OFF"}`, { desiredOutput });
}

async function runBasicOutputAll() {
  const presentation = basicOutputPresentation();
  if (presentation.mode === "e3646a-disabled") return;
  if (basicOutputLockAction("all")) return;
  const supported = presentation.mode === "e3646a-global"
    ? presentation.capability.channels
    : supportedChannelsForCurrentModel();
  if (!supported.length) return;
  const globalState = presentation.mode === "e3646a-global" ? e3646aGlobalOutputState(presentation) : null;
  if (globalState === "unknown") return;
  const allOn = state.executionMode === "real" && (globalState ? globalState === "on" : basicAllOutputsOn());
  const command = allOn ? "output-off" : "output-on";
  const desiredOutput = !allOn;
  await submitBasicJob(command, { channel: "all" }, basicActionKey("output", "all"), `Basic All ${desiredOutput ? "ON" : "OFF"}`, { desiredOutput });
}

async function submitBasicJob(command, parameters, actionKey, label, actionState = {}) {
  const meta = commandMeta(command);
  if (meta.disabled) {
    failBasicAction(actionKey, "Command unavailable", meta.disabled_reason || "This command is not available for the selected resource.", { command, parameters, label });
    return;
  }

  const ratingGuard = electricalRatingGuardReason(command, parameters);
  const tripGuard = tripGuardReason(command, parameters);
  if (ratingGuard || tripGuard) {
    failBasicAction(actionKey, ratingGuard ? "Rating guard" : "Protection trip active", ratingGuard || tripGuard, { command, parameters, label });
    return;
  }

  const payload = { command, runtime: runtimePayload(), parameters };
  if (meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm) {
    failBasicAction(actionKey, "Authorization required", "Enable real hardware writes for this resource before running this command.", { command, parameters, label });
    return;
  }

  setBasicActionState(actionKey, "pending", "Basic command running...", { command, parameters, ...actionState });
  try {
    const response = await submitJob(payload);
    state.basicJobActions[response.job_id] = { actionKey, command, parameters, ...actionState };
    addHistory(response.job_id, command, "accepted", label);
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    failBasicAction(actionKey, "Submit failed", error.message || String(error), { command, parameters, label });
  }
}

function failBasicAction(actionKey, error, detail, context = {}) {
  setBasicActionState(actionKey, "error", detail, context);
  renderClientResult(context.label || basicActionDisplayName(actionKey), "failed", detail, {
    error,
    detail,
    ...context
  });
}

async function runSelected() {
  if (!state.selected) return;
  if (state.workflowControl.phase === "active") {
    await stopActiveWorkflow();
    return;
  }
  if (state.workflowControl.phase !== "idle") return;

  let validatedSequenceDocument = null;
  if (state.selected === "sequence") {
    try {
      validatedSequenceDocument = sequenceDocumentFromEditor();
    } catch (error) {
      renderClientResult(
        "sequence",
        "failed",
        error.message || String(error),
        {
          error: "Sequence validation failed",
          detail: error.message || String(error),
          command: "sequence"
        }
      );
      return;
    }
  }

  let validatedRestoreDocument = null;
  if (state.selected === "restore-from-snapshot") {
    if (!state.loadedSnapshotDocument) {
      renderClientResult(
        "restore-from-snapshot",
        "failed",
        "Load a snapshot before running restore.",
        {
          error: "Snapshot validation failed",
          detail: "Load a snapshot before running restore.",
          command: "restore-from-snapshot"
        }
      );
      return;
    }
    try {
      validateRestoreSnapshot(state.loadedSnapshotDocument);
      validatedRestoreDocument = state.loadedSnapshotDocument;
    } catch (error) {
      renderClientResult(
        "restore-from-snapshot",
        "failed",
        error.message || String(error),
        {
          error: "Snapshot validation failed",
          detail: error.message || String(error),
          command: "restore-from-snapshot"
        }
      );
      return;
    }
  }

  const meta = commandMeta(state.selected);
  if (meta.disabled) {
    renderClientResult(state.selected, "failed", meta.disabled_reason || "This command is not available for the selected resource.", {
      error: "Command unavailable",
      detail: meta.disabled_reason || "This command is not available for the selected resource.",
      command: state.selected
    });
    return;
  }
  const payload = {
    command: state.selected,
    runtime: runtimePayload(),
    parameters: state.selected === "sequence"
      ? { document: validatedSequenceDocument }
      : state.selected === "restore-from-snapshot"
        ? restoreSnapshotParameters(validatedRestoreDocument)
      : parameterPayload()
  };
  const channelGuard = channelAvailabilityGuardReason(state.selected, payload.parameters);
  if (channelGuard) {
    renderClientResult(state.selected, "failed", channelGuard, {
      error: "Unsupported channel",
      detail: channelGuard,
      command: state.selected,
      parameters: payload.parameters
    });
    return;
  }
  const tripGuard = tripGuardReason(state.selected, payload.parameters);
  if (tripGuard) {
    renderClientResult(state.selected, "failed", tripGuard, {
      error: "Protection trip active",
      detail: tripGuard,
      command: state.selected,
      parameters: payload.parameters
    });
    return;
  }
  if (meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm) {
    renderClientResult(state.selected, "failed", "Enable real hardware writes for this resource before running.", {
      error: "Confirmation required",
      detail: "Enable real hardware writes for this resource before running.",
      command: state.selected,
      runtime: { confirm: false }
    });
    return;
  }
  const submittedCommand = state.selected;
  if (STOPPABLE_WORKFLOWS.has(submittedCommand)) {
    setWorkflowControl("submitting", { command: submittedCommand });
  }
  try {
    const response = await submitJob(payload);
    addHistory(response.job_id, submittedCommand, "accepted");
    if (submittedCommand === "snapshot") {
      refreshSnapshotFormIfVisible(response.job_id);
    }
    if (STOPPABLE_WORKFLOWS.has(submittedCommand)) {
      setWorkflowControl("active", { command: submittedCommand, jobId: response.job_id });
    }
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    if (STOPPABLE_WORKFLOWS.has(submittedCommand)) {
      setWorkflowControl("idle");
    }
    renderClientResult(submittedCommand, "failed", error.message || String(error), {
      error: "Submit failed",
      detail: error.message || String(error),
      command: submittedCommand
    });
  }
}

async function stopActiveWorkflow() {
  const control = state.workflowControl;
  if (control.phase !== "active" || !control.jobId || !STOPPABLE_WORKFLOWS.has(control.command)) return;
  const jobId = control.jobId;
  setWorkflowControl("stopping", { command: control.command, jobId });
  updateJobResult(jobId, "cancel_requested", "Waiting for safe-off and cleanup");
  try {
    await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      body: "{}"
    });
  } catch (error) {
    await reconcileWorkflowJob(jobId, error);
  }
}

function setWorkflowControl(phase, values = {}) {
  state.workflowControl = phase === "idle"
    ? { phase: "idle", jobId: null, command: null }
    : {
        phase,
        jobId: values.jobId ?? state.workflowControl.jobId,
        command: values.command ?? state.workflowControl.command
      };
  updateWorkflowRunButton();
  renderCommands();
  if (phase === "idle" && state.selected) updateSelectedCommandState();
}

function updateWorkflowRunButton() {
  const button = document.getElementById("run");
  if (!button) return;
  const { phase, command } = state.workflowControl;
  const activeWorkflow = STOPPABLE_WORKFLOWS.has(command);
  button.classList.toggle("workflow-stop", activeWorkflow && phase === "active");
  button.textContent = phase === "submitting"
    ? "Starting..."
    : phase === "active" && activeWorkflow
      ? "Stop"
      : phase === "stopping"
        ? "Stopping..."
        : "Run";
  const stopMeaning = activeWorkflow && ["active", "stopping"].includes(phase);
  button.title = stopMeaning ? WORKFLOW_STOP_DESCRIPTION : "";
  button.setAttribute("aria-label", stopMeaning ? WORKFLOW_STOP_DESCRIPTION : button.textContent);
  if (phase === "active" && activeWorkflow) button.disabled = false;
  if (phase === "submitting" || phase === "stopping") button.disabled = true;
  const guidance = document.getElementById("command-guidance");
  if (guidance && stopMeaning) {
    guidance.textContent = phase === "stopping"
      ? "Waiting for safe-off and cleanup"
      : WORKFLOW_STOP_DESCRIPTION;
    guidance.hidden = false;
  }
}

async function reconcileWorkflowJob(jobId, originalError = null) {
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (["finished", "failed", "cancelled"].includes(job.status)) {
      const code = job.error_code ? `  ${job.error_code}` : "";
      updateJobResult(jobId, job.status, job.status === "failed" ? `Failed${code}` : statusLabel(job.status));
      setWorkflowControl("idle");
      return;
    }
    if (job.status === "cancel_requested") {
      setWorkflowControl("stopping", { command: job.command, jobId });
      return;
    }
  } catch (error) {
    if (!originalError) originalError = error;
  }
  if (originalError) {
    renderClientResult(
      state.workflowControl.command || "workflow",
      "failed",
      originalError.message || String(originalError),
      { error: "Cancellation request failed", detail: originalError.message || String(originalError) }
    );
  }
}

function runtimePayload() {
  if (state.executionMode === "simulate") {
    const planningModelId = selectedPlanningIdentity();
    return planningModelId
      ? { simulate: true, dry_run: false, planning_model_id: planningModelId, confirm: false }
      : { simulate: true, dry_run: false, confirm: false };
  }
  if (state.executionMode === "dry-run") {
    const identity = selectedPlanningIdentity();
    const runtime = { simulate: false, dry_run: true, confirm: false };
    if (identity?.startsWith("profile:")) runtime.planning_profile_id = identity.slice("profile:".length);
    else if (identity) runtime.planning_model_id = identity;
    return runtime;
  }
  const runtime = {
    resource: valueOrNull("resource"),
    backend: null,
    timeout_ms: 5000,
    safety_config: null,
    simulate: false,
    dry_run: false,
    confirm: hasRealWriteAuthorization()
  };
  const serialOptions = serialOptionsPayload();
  const expectedModelId = valueOrNull("expected-model-id");
  if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;
  if (Object.keys(serialOptions).length) runtime.serial_options = serialOptions;
  if (document.getElementById("serial-remote")?.checked) runtime.serial_remote = true;
  if (document.getElementById("serial-local-on-close")?.checked) runtime.serial_local_on_close = true;
  return runtime;
}

function serialOptionsPayload() {
  const payload = {};
  const baudRate = optionalIntegerValue("serial-baud-rate");
  const dataBits = optionalIntegerValue("serial-data-bits");
  const parity = valueOrNull("serial-parity");
  const stopBits = valueOrNull("serial-stop-bits");
  const flowControl = valueOrNull("serial-flow-control");
  const readTermination = valueOrNull("serial-read-termination");
  const writeTermination = valueOrNull("serial-write-termination");
  if (baudRate !== null) payload.baud_rate = baudRate;
  if (dataBits !== null) payload.data_bits = dataBits;
  if (parity !== null) payload.parity = parity;
  if (stopBits !== null) payload.stop_bits = stopBits;
  if (flowControl !== null) payload.flow_control = flowControl;
  if (readTermination !== null) payload.read_termination = readTermination;
  if (writeTermination !== null) payload.write_termination = writeTermination;
  return payload;
}

function optionalIntegerValue(id) {
  const raw = valueOrNull(id);
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : null;
}

function parameterPayload() {
  if (state.selected === "ramp-list") return { document: rampListDocument() };
  if (state.selected === "trigger-list") {
    const draft = activeTriggerListDraft();
    return {
      channel: state.triggerListActiveChannel,
      voltage_list: draft.steps.map((step) => step.voltage),
      current_list: draft.steps.map((step) => step.current),
      dwell_list: draft.steps.map((step) => step.dwell),
      bost_list: draft.steps.map((step) => step.bost),
      eost_list: draft.steps.map((step) => step.eost),
      count: draft.count,
      ...state.triggerListControls,
      trigger_output_pins: [...state.triggerListControls.trigger_output_pins],
      trigger_output_polarity: state.triggerListControls.trigger_output_polarity
    };
  }
  if (state.selected === "restore-from-snapshot") {
    return restoreSnapshotParameters(state.loadedSnapshotDocument);
  }
  if (state.selected === "sequence") {
    return {
      document: sequenceDocumentFromEditor()
    };
  }
  const payload = {};
  (PARAMS[state.selected] || []).forEach((param) => {
    const input = document.getElementById(`param-${param.name}`);
    if (!input) return;
    const parsed = parameterValue(param, input);
    if (parsed !== undefined) payload[param.name] = parsed;
  });
  if (state.selected === "cycle-output") {
    if (!payload.completion_pulse_enabled) {
      delete payload.completion_pulse_pins;
      delete payload.completion_pulse_polarity;
    }
    delete payload.completion_pulse_enabled;
  }
  if (state.selected === "ramp") {
    if (!payload.loop_enabled) {
      if (payload.completion_pulse_timing === "loop") payload.completion_pulse_timing = "";
    } else {
      if (!Number.isInteger(payload.loop_count) || payload.loop_count < 2 || payload.loop_count > 255) {
        throw new Error("Ramp Loop count must be an integer from 2 to 255.");
      }
    }
    delete payload.loop_enabled;
    if (!payload.completion_pulse_timing) {
      delete payload.completion_pulse_timing;
      delete payload.completion_pulse_pins;
      delete payload.completion_pulse_polarity;
    }
  }
  return payload;
}

function enforcePulseFormRules(command, name, input) {
  if (command === "cycle-output") {
    updatePulseChildVisibility(command);
    return;
  }
  if (command !== "ramp") return;
  updatePulseChildVisibility(command);
  refreshLoopCompleteOption(command);
}

function applyParameterConstraint(input, name) {
  if (input.type !== "number") return;
  const constraint = state.parameterConstraints[name];
  if (!constraint) return;
  if (constraint.min !== undefined) input.min = String(constraint.min);
  if (constraint.max !== undefined) input.max = String(constraint.max);
  input.step = String(constraint.step ?? "any");
  if (constraint.exclusive_min !== undefined) input.dataset.exclusiveMin = String(constraint.exclusive_min);
  if (constraint.description) input.title = constraint.description;
}

function applyElectricalRatingConstraint(input, name) {
  if (input.type !== "number" || !["voltage", "start_voltage", "stop_voltage", "current"].includes(name)) return;
  restoreBaseElectricalConstraints(input);
  const suppliedRating = arguments.length >= 3 ? arguments[2] : undefined;
  const rating = suppliedRating === undefined ? selectedChannelRating() : suppliedRating;
  if (!rating) return;
  input.dataset.electricalBaseConstraints = JSON.stringify(Object.fromEntries(
    ELECTRICAL_CONSTRAINT_ATTRIBUTES.map((attribute) => [
      attribute,
      input.hasAttribute(attribute) ? input.getAttribute(attribute) : null
    ])
  ));
  input.setAttribute("max", String(name === "current" ? rating.max_current : rating.max_voltage));
  input.setAttribute("title", `Official independent-channel DC output rating: maximum ${input.max} ${name === "current" ? "A" : "V"}.`);
}

function restoreBaseElectricalConstraints(input) {
  const serialized = input.dataset.electricalBaseConstraints;
  if (!serialized) return;
  const base = JSON.parse(serialized);
  ELECTRICAL_CONSTRAINT_ATTRIBUTES.forEach((attribute) => {
    if (base[attribute] === null || base[attribute] === undefined) input.removeAttribute(attribute);
    else input.setAttribute(attribute, base[attribute]);
  });
  delete input.dataset.electricalBaseConstraints;
}

function refreshInputElectricalConstraints(input, name) {
  restoreBaseElectricalConstraints(input);
  applyParameterConstraint(input, name);
  if (arguments.length >= 3) applyElectricalRatingConstraint(input, name, arguments[2]);
  else applyElectricalRatingConstraint(input, name);
}

function selectedChannelRating() {
  const selected = document.getElementById("param-channel")?.value || "1";
  return selectedChannelRatingFor(selected);
}

function selectedChannelRatingFor(selected) {
  const model = selectedElectricalRatingModel();
  const ratings = state.electricalRatingsByModel?.[model]?.channels;
  if (!Array.isArray(ratings)) return null;
  const channels = selected === "all" ? ratings : ratings.filter((rating) => String(rating.channel) === String(selected));
  if (!channels.length) return null;
  return {
    max_voltage: Math.min(...channels.map((rating) => Number(rating.max_voltage))),
    max_current: Math.min(...channels.map((rating) => Number(rating.max_current)))
  };
}

function refreshElectricalRatingConstraints() {
  document.querySelectorAll("#command-form input[type=number]").forEach((input) => {
    refreshInputElectricalConstraints(input, input.id.replace("param-", ""));
  });
}

function validateConstrainedInputs() {
  let valid = true;
  document.querySelectorAll("#command-form input[type=number]").forEach((input) => {
    input.setCustomValidity("");
    const exclusiveMin = input.dataset.exclusiveMin;
    if (exclusiveMin !== undefined && input.value !== "" && Number(input.value) <= Number(exclusiveMin)) {
      input.setCustomValidity(`Value must be greater than ${exclusiveMin}.`);
    }
    valid &&= input.checkValidity();
  });
  return valid;
}

function refreshBasicInputConstraints() {
  document.querySelectorAll("[data-basic-voltage], [data-basic-current]").forEach((input) => {
    const channel = Number(input.dataset.basicVoltage || input.dataset.basicCurrent);
    const name = input.dataset.basicVoltage ? "voltage" : "current";
    const unsupported = channelUnsupportedReason(channel);
    restoreBaseElectricalConstraints(input);
    applyParameterConstraint(input, name);
    input.disabled = Boolean(unsupported);
    if (unsupported) {
      input.title = unsupported;
      input.setCustomValidity("");
      return;
    }
    const rating = selectedChannelRatingFor(channel);
    applyElectricalRatingConstraint(input, name, rating);
    validateBasicInput(input);
  });
}

function validateBasicInput(input) {
  input.setCustomValidity("");
  const exclusiveMin = input.dataset.exclusiveMin;
  if (exclusiveMin !== undefined && input.value !== "" && Number(input.value) <= Number(exclusiveMin)) {
    input.setCustomValidity(`Value must be greater than ${exclusiveMin}.`);
  }
  return input.checkValidity();
}

function basicSetpointValues(channel) {
  const voltageInput = document.querySelector(`[data-basic-voltage="${channel}"]`);
  const currentInput = document.querySelector(`[data-basic-current="${channel}"]`);
  if (!voltageInput || !currentInput) return { ok: false, message: `CH${channel} controls are missing.` };
  const valid = [voltageInput, currentInput].every((input) => validateBasicInput(input));
  if (!valid) return { ok: false, message: `CH${channel} setpoint is outside allowed limits.` };
  if (voltageInput.value === "" && currentInput.value === "") {
    return { ok: false, message: `CH${channel} requires V, A, or both.` };
  }
  const parameters = {};
  if (voltageInput.value !== "") {
    const voltage = Number(voltageInput.value);
    if (!Number.isFinite(voltage)) return { ok: false, message: `CH${channel} V must be a finite number.` };
    parameters.voltage = voltage;
  }
  if (currentInput.value !== "") {
    const current = Number(currentInput.value);
    if (!Number.isFinite(current)) return { ok: false, message: `CH${channel} A must be a finite number.` };
    parameters.current = current;
  }
  return { ok: true, parameters };
}

function updateRampListPulse(name, value) {
  if (name === "timing" && !value) {
    state.rampListCompletionPulse = null;
  } else {
    state.rampListCompletionPulse ||= { timing: "segment", pins: [1], polarity: "positive" };
    state.rampListCompletionPulse[name] = name === "pins"
      ? parseRearPins(value)
      : value;
  }
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function restoreSnapshotParameters(document) {
  return {
    document,
    channel: normalizeRestoreChannel(state.restoreChannel),
    restore_output_state: state.restoreOutputState
  };
}

function normalizeRestoreChannel(value) {
  return value === "all" ? "all" : normalizeChannelValue(value);
}

function parameterValue(param, input) {
  if (param.type === "checkbox") return input.checked;
  if (param.type === "number") {
    if (input.value === "") return param.optional ? undefined : null;
    return Number(input.value);
  }
  if (param.type === "textarea") return parseMaybeJson(input.value);
  if (input.value === "") return undefined;
  if (param.name === "channel") return normalizeChannelValue(input.value);
  if (param.parser === "intList") return parseDelimitedNumbers(input.value, true);
  if (param.parser === "numberList") return parseDelimitedNumbers(input.value, false);
  return input.value;
}

function normalizeChannelValue(value) {
  if (value === "all") return value;
  return /^[1-9]\d*$/.test(value) ? Number(value) : value;
}

function parseDelimitedNumbers(value, integerOnly) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => integerOnly ? parseInt(item, 10) : Number(item));
}

function commandDisplayName(name) {
  if (!name) return "";
  const overrides = {
    snapshot: "Create snapshot",
    "restore-from-snapshot": "Restore snapshot",
    "protection-set": "Set protection",
    clear: "Clear Status / Errors",
    capabilities: "Get capabilities",
    identify: "Read device information",
    error: "Read errors"
  };
  if (overrides[name]) return overrides[name];
  const spaced = name.replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function parseRearPins(value) {
  const source = Array.isArray(value) ? value : String(value || "").split(",");
  return source.map((item) => Number(String(item).trim())).filter((item) => [1, 2, 3].includes(item));
}

function pinsSelectValue(value) {
  return parseRearPins(value).join(",");
}

function rearPinDisplayName(value) {
  const labels = {
    "1": "Pin 1",
    "2": "Pin 2",
    "3": "Pin 3",
    "1,2": "Pins 1 + 2",
    "1,3": "Pins 1 + 3",
    "2,3": "Pins 2 + 3",
    "1,2,3": "All"
  };
  return value === "" ? "None" : labels[value] || value;
}

function optionDisplayName(value) {
  const overrides = {
    "cc-transition": "CC transition"
  };
  if (value === "") return "None";
  if (overrides[value]) return overrides[value];
  const spaced = value.replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function submitJob(payload) {
  return fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
}

function subscribeToJob(jobId, baseUrl) {
  closeEventSource("events");
  state.events = new EventSource(`${baseUrl}?job_id=${encodeURIComponent(jobId)}`);
  ["accepted", "started", "progress", "cancel_requested", "finished", "failed", "cancelled", "error"].forEach((type) => {
    state.events.addEventListener(type, (event) => handleJobEvent(jobId, JSON.parse(event.data)));
  });
  state.events.onerror = () => {
    if (state.workflowControl.jobId === jobId && state.workflowControl.phase !== "idle") {
      reconcileWorkflowJob(jobId);
    }
  };
}

async function handleJobEvent(jobId, event) {
  updateHistory(jobId, event.type);
  if (state.workflowControl.jobId === jobId) {
    if (event.type === "cancel_requested") {
      setWorkflowControl("stopping", { jobId, command: state.workflowControl.command });
      updateJobResult(jobId, "cancel_requested", "Waiting for safe-off and cleanup");
    } else if (["started", "progress"].includes(event.type) && state.workflowControl.phase !== "stopping") {
      setWorkflowControl("active", { jobId, command: state.workflowControl.command });
    }
  }
  if (jobCommand(jobId) === "snapshot" && (event.type === "accepted" || event.type === "started" || event.type === "progress")) {
    refreshSnapshotFormIfVisible(jobId);
  }
  if (event.type === "finished" || event.type === "failed" || event.type === "cancelled") {
    const job = await renderJobDetail(jobId, event);
    if (state.workflowControl.jobId === jobId && job && ["finished", "failed", "cancelled"].includes(job.status)) {
      if (job.status === "failed" && job.error_code === "cleanup_failed") {
        updateJobResult(jobId, "failed", "Failed  cleanup_failed");
      } else if (job.status === "cancelled") {
        updateJobResult(jobId, "cancelled", "Cancelled");
      }
      setWorkflowControl("idle");
    }
    let healthState = null;
    if (event.type === "finished" && jobCommand(jobId) === "list-resources") {
      populateResourceSelect(event.data?.result?.resources || []);
      healthState = await refreshHealth();
      startLivePreviewSnapshot(healthState);
    } else if (shouldRefreshLiveAfterCommand(event, job)) {
      healthState = await refreshHealth();
      startLivePreviewSnapshot(healthState, job.runtime.resource);
    }
    if (event.type === "finished" && job) {
      captureLatestSnapshotDocument(job);
      captureWorkspaceResult(job);
    }
    if (jobCommand(jobId) === "snapshot") {
      refreshSnapshotFormIfVisible(jobId);
    }
    if (state.basicJobActions[jobId]) {
      updateBasicActionFromJob(jobId, event, job);
    }
    if (event.type === "finished") updateResourceModelFromJob(job);
    if (jobLabel(jobId) === "Restore plan preview") {
      captureRestorePlanPreview(job);
      if (state.selected === "restore-from-snapshot") {
        renderForm("restore-from-snapshot");
        updateSelectedCommandState();
      }
    }
    closeEventSource("events");
    if (!healthState) refreshHealth();
  }
}

function captureLatestSnapshotDocument(job) {
  if (!job || job.command !== "snapshot" || job.status !== "finished" || !job.result) {
    return false;
  }
  try {
    validateSnapshotDocument(job.result);
  } catch (error) {
    return false;
  }
  state.latestSnapshotDocument = job.result;
  state.latestSnapshotMetadata = {
    savedAt: Date.now(),
    model: job.result.idn?.model || null,
    serial: job.result.idn?.serial || null,
    resource: job.result.resource || job.runtime?.resource || null
  };
  return true;
}

async function renderJobDetail(jobId, event) {
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    updateJobResult(job.job_id, job.status, jobSummary(job, event));
    renderResult({
      job_id: job.job_id,
      command: job.command,
      status: job.status,
      runtime: job.runtime,
      parameters: job.parameters,
      result: job.result,
      error: job.error
    });
    return job;
  } catch (error) {
    updateJobResult(jobId, event.type, eventSummary(event));
    renderResult(event.data);
    return null;
  }
}

function shouldRefreshLiveAfterCommand(event, job) {
  const runtime = job?.runtime;
  return event.type === "finished"
    && job?.command !== "list-resources"
    && Boolean(runtime?.resource)
    && runtime.simulate === false
    && runtime.dry_run === false;
}

function renderResult(data) {
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
}

function workspaceResultContextForJob(job) {
  return webuiContext.buildWorkspaceResultContextForJob(job, {
    commandModelByResource: state.resourceModels,
    channelModelByResource: state.resourceChannelModels
  });
}

function currentWorkspaceResultContext(command) {
  return webuiContext.buildCurrentWorkspaceResultContext({
    command,
    executionMode: state.executionMode,
    planningIdentity: selectedPlanningIdentity() || "",
    resource: valueOrNull("resource") || "",
    expectedModelGuard: selectedExpectedModel() || "",
    canonicalModelId: actualCurrentResourceModel() || ""
  });
}

function captureWorkspaceResult(job) {
  if (!job || job.status !== "finished" || !job.command || !job.result) return false;
  const context = workspaceResultContextForJob(job);
  const resource = context.resource || "";
  if (["capabilities", "identify", "verify"].includes(job.command)) {
    captureResourceLiveSupport(job, resource);
  }
  state.workspaceResults[buildWorkspaceResultKey(context)] = job;
  renderWorkspaceSummary();
  return true;
}

function renderWorkspaceSummary() {
  const container = document.getElementById("workspace-summary-content");
  if (!container) return;
  container.innerHTML = "";
  if (!state.selected) {
    renderWorkspaceEmpty(container, "Choose a command to view its latest successful result.");
    return;
  }
  const context = currentWorkspaceResultContext(state.selected);
  const job = state.workspaceResults[buildWorkspaceResultKey(context)];
  if (!job) {
    renderWorkspaceEmpty(container, "Run this command to see its latest successful result for the active execution context.");
    return;
  }
  if (job.command === "capabilities") {
    renderCapabilitiesWorkspaceSummary(container, job.result);
    return;
  }
  if (job.command === "identify") {
    renderIdentifyWorkspaceSummary(container, job.result);
    return;
  }
  if (job.command === "trigger-status") {
    renderTriggerStatusWorkspaceSummary(container, job.result);
    return;
  }
  if (job.command === "trigger-list") {
    const trigger = job.result.trigger || {};
    appendWorkspaceFields(container, [
      ["Command", commandDisplayName(job.command)],
      ["Channel", trigger.channel ?? "--"],
      ["Steps", job.result.steps ?? "--"],
      ["Completed", trigger.completed === true ? "Yes" : "No"],
      ["Previous LIST restored", trigger.restored === true ? "Yes" : trigger.restored === false ? "No" : "--"]
    ]);
    return;
  }
  appendWorkspaceFields(container, [
    ["Command", commandDisplayName(job.command)],
    ["Execution mode", context.executionMode],
    ["Resource", context.executionMode === "real" ? context.resource || "No resource selected" : "Not used"],
    ["Summary", successfulJobSummary(job)]
  ]);
}

function renderWorkspaceEmpty(container, message) {
  const empty = document.createElement("p");
  empty.className = "workspace-summary-empty";
  empty.textContent = message;
  container.appendChild(empty);
}

function renderCapabilitiesWorkspaceSummary(container, result) {
  const resource = result.resource || {};
  const model = resource.idn?.model || result.driver?.model;
  if (resource.name || model) {
    const support = result.command_support || {};
    const liveSupport = result.live_support || {};
    appendWorkspaceFields(container, [
      ["Model", model || "--"],
      ["Resource", resource.name || "--"],
      ["Transport", transportScopeLabel(liveSupport.transport_scope)],
      ["Backend", backendScopeLabel(liveSupport.backend_scope)],
      ["Product live support", liveSupportSummary(liveSupport)],
      ["Output channels", channelList(result.channels)],
      ["Measurement channels", channelList(result.measure_channels?.real)],
      ["Output", featureAvailability(support, ["set", "apply", "output-on", "output-off"])],
      ["Protection", featureAvailability(support, ["protection-set", "clear-protection", "protection-status"])],
      ["Trigger", featureAvailability(support, ["trigger-status", "trigger-step", "trigger-list", "trigger-fire"])]
    ]);
    return;
  }
  const models = result.models || {};
  const fields = Object.entries(models).map(([name, details]) => [
    name,
    `${Array.isArray(details.channels) ? details.channels.length : 0} channels (${channelList(details.channels)})`
  ]);
  appendWorkspaceFields(container, fields.length ? fields : [["Supported models", "--"]]);
}

function renderIdentifyWorkspaceSummary(container, result) {
  const idn = result.idn || result.resource?.idn || {};
  const resource = typeof result.resource === "string" ? result.resource : result.resource?.name;
  appendWorkspaceFields(container, [
    ["Manufacturer", idn.manufacturer || "--"],
    ["Model", idn.model || "--"],
    ["Serial number", idn.serial || "--"],
    ["Firmware", idn.firmware || "--"],
    ["Installed options", result.options || "--"],
    ["SCPI version", result.scpi_version || "--"],
    ["Resource", resource || "--"]
  ]);
}

function renderTriggerStatusWorkspaceSummary(container, result) {
  const pins = Array.isArray(result.digital_pins) ? result.digital_pins : [];
  const channels = Array.isArray(result.channels) ? result.channels : [];
  const fields = [
    ["Trigger output BUS", result.trigger_output_bus_enabled === true ? "Enabled" : result.trigger_output_bus_enabled === false ? "Disabled" : "--"],
    ["Rear pins", pins.length ? pins.map((pin) => `P${pin.pin} ${pin.function}/${pin.polarity}`).join(", ") : "--"]
  ];
  channels.forEach((channel) => {
    const trigger = channel.trigger || {};
    const list = channel.list || {};
    const steps = Array.isArray(list.voltage) ? list.voltage.length : 0;
    fields.push(
      [`CH${channel.channel} trigger`, `${trigger.source || "--"}; V ${trigger.voltage_mode || "--"}; I ${trigger.current_mode || "--"}`],
      [`CH${channel.channel} triggered level`, `${formatNum(trigger.triggered_voltage)} V / ${formatNum(trigger.triggered_current)} A`],
      [`CH${channel.channel} LIST`, `${steps} step${steps === 1 ? "" : "s"}; count ${list.count ?? "--"}; ${list.step_mode || "--"}; terminate last ${list.terminate_last === true ? "on" : list.terminate_last === false ? "off" : "--"}`]
    );
  });
  appendWorkspaceFields(container, fields);
}

function appendWorkspaceFields(container, fields) {
  fields.forEach(([labelText, valueText]) => {
    const field = document.createElement("div");
    field.className = "workspace-summary-field";
    const label = document.createElement("small");
    label.textContent = labelText;
    const value = document.createElement("span");
    value.textContent = String(valueText);
    field.append(value, label);
    container.appendChild(field);
  });
}

function channelList(channels) {
  return Array.isArray(channels) && channels.length ? channels.map((channel) => `CH${channel}`).join(", ") : "--";
}

function featureAvailability(support, commands) {
  return commands.some((command) => support[command]?.real === true) ? "Available" : "Unavailable";
}

function renderClientResult(command, status, summary, detail) {
  const jobId = `client-${Date.now()}`;
  addHistory(jobId, command, status, command);
  updateJobResult(jobId, status, summary);
  renderResult(detail);
}

function jobCommand(jobId) {
  return state.jobs.find((item) => item.jobId === jobId)?.command || null;
}

function captureRestorePlanPreview(job) {
  if (job?.status === "finished" && job.result?.plan) {
    state.restorePlanPreviewStatus = "finished";
    state.restorePlanPreview = job.result;
    return;
  }
  state.restorePlanPreviewStatus = "failed";
  state.restorePlanPreview = { error: job?.error || "Restore plan preview did not finish." };
}

function jobLabel(jobId) {
  return state.jobs.find((item) => item.jobId === jobId)?.label || null;
}

function populateResourceSelect(resources) {
  const select = document.getElementById("resource-select");
  const input = document.getElementById("resource");
  select.innerHTML = "";
  updateResourceModels(resources);
  if (!Array.isArray(resources) || resources.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No live resources found";
    select.appendChild(option);
    updateDeviceResourceSummary();
    return;
  }

  resources.forEach((resource) => {
    const name = typeof resource === "string" ? resource : resource?.name;
    if (!name) return;
    const option = document.createElement("option");
    option.value = name;
    option.textContent = resourceLabel(resource, name);
    select.appendChild(option);
  });

  if (select.options.length > 0) {
    select.selectedIndex = 0;
    input.value = select.value;
  }
  updateDeviceResourceSummary();
  refreshBasicInputConstraints();
  syncBasicFromLivePanel(state.livePanel);
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
}

function resourceLabel(resource, name) {
  if (!resource || typeof resource === "string") return name;
  const model = resource.idn?.model;
  const manufacturer = resource.idn?.manufacturer;
  return [name, manufacturer, model].filter(Boolean).join(" - ");
}

async function syncSelectedResource() {
  const input = document.getElementById("resource");
  const previous = input.value;
  const value = document.getElementById("resource-select").value;
  input.value = value;
  if (value !== previous) clearRealWriteAuthorization();
  updateDeviceResourceSummary();
  refreshBasicInputConstraints();
  syncBasicFromLivePanel(state.livePanel);
  renderWorkspaceSummary();
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
  if (value !== previous) await refreshSelectedResourcePreview(value);
}

function updateResourceModels(resources) {
  if (!Array.isArray(resources)) return;
  resources.forEach((resource) => {
    if (!resource || typeof resource === "string") return;
    const name = resource.name;
    if (!name) return;
    updateResourceModel(name, resource.model_id, resource.idn?.model);
  });
}

function updateResourceModelFromJob(job) {
  const result = job?.result || {};
  const resultResource = result.resource;
  const resourceName = resultResource?.name || (typeof resultResource === "string" ? resultResource : job?.runtime?.resource);
  const reportedModel = resultResource?.idn?.model || result.idn?.model || result.model || result.driver?.model;
  const modelId = resultResource?.model_id || result.live_support?.model_id || null;
  const updated = updateResourceModel(resourceName, modelId, reportedModel);
  if (resourceName && resourceName === valueOrNull("resource")) updateDeviceResourceSummary();
  if (updated) {
    refreshBasicInputConstraints();
    syncBasicFromLivePanel(state.livePanel);
    if (state.selected) selectCommand(state.selected);
    else renderCommands();
  }
}

function updateResourceModel(resource, modelId, reportedModel = null) {
  if (!resource) return false;
  const next = supportedModelKey(modelId);
  const nextChannelModel = channelModelKey(modelId);
  const detectedModel = typeof reportedModel === "string" ? reportedModel.trim() : null;
  if (detectedModel) state.resourceDisplayModels[resource] = detectedModel;
  if (state.resourceLiveSupportContext?.resource === resource
    && modelId
    && state.resourceLiveSupportContext.model_id !== modelId) {
    state.resourceLiveSupport = null;
    state.resourceLiveSupportContext = null;
  }
  if (state.resourceModels[resource] === next && state.resourceChannelModels[resource] === nextChannelModel) return false;
  if (resource === valueOrNull("resource")) clearRealWriteAuthorization();
  state.resourceModels[resource] = next;
  state.resourceChannelModels[resource] = nextChannelModel;
  return true;
}

function captureResourceLiveSupport(job, resource) {
  const liveSupport = job?.result?.live_support;
  if (!resource || !liveSupport || liveSupport.evaluated !== true) {
    if (state.resourceLiveSupportContext?.resource === resource) {
      state.resourceLiveSupport = null;
      state.resourceLiveSupportContext = null;
    }
    return false;
  }
  state.resourceLiveSupport = liveSupport;
  state.resourceLiveSupportContext = {
    resource,
    model_id: liveSupport.model_id || null,
    transport_scope: liveSupport.transport_scope || "unknown",
    backend_scope: liveSupport.backend_scope || "system_visa"
  };
  updateDeviceResourceSummary();
  syncBasicFromLivePanel(state.livePanel);
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
  return true;
}

function clearStaleResourceLiveSupport(resource) {
  if (!state.resourceLiveSupportContext || state.resourceLiveSupportContext.resource === resource) return false;
  state.resourceLiveSupport = null;
  state.resourceLiveSupportContext = null;
  return true;
}

function currentExactLiveSupport() {
  const resource = valueOrNull("resource");
  if (!resource || state.resourceLiveSupportContext?.resource !== resource) return null;
  return state.resourceLiveSupport?.evaluated === true ? state.resourceLiveSupport : null;
}

function selectedModelLiveSupport(name) {
  const model = selectedCommandModel();
  if (!model) return null;
  return state.liveSupportByModel?.[model]?.commands?.[name] || null;
}

function commandMeta(name) {
  const meta = state.commands[name] || {};
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    if (!identity) return { ...meta, disabled: true, disabled_reason: "Select a planning identity before running this command.", live_support_status: "Planning identity is required." };
    if (identity.startsWith("profile:")) {
      const profile = state.planningProfiles?.[identity.slice("profile:".length)];
      const support = profile?.command_support?.[name];
      if (!support || support.dry_run !== true) return { ...meta, disabled: true, disabled_reason: "This planning profile does not support the selected command." };
      return { ...meta, live_support_status: "Dry-run planning profile", requires_confirm: false };
    }
    const support = state.commandSupportByModel?.[identity]?.[name];
    const supported = state.executionMode === "simulate" ? support?.simulate : support?.dry_run;
    if (supported !== true) return { ...meta, disabled: true, disabled_reason: `${physicalModelDisplayName(identity)} does not support this command in ${state.executionMode}.` };
    return { ...meta, live_support_status: state.executionMode === "simulate" ? "Simulation supported" : "Dry-run supported", requires_confirm: false };
  }
  const support = selectedCommandSupport(name);
  const modelSupport = selectedModelLiveSupport(name);
  let effective = { ...meta };
  if (support?.real === false || (modelSupport && !modelSupport.profile_supported && !modelSupport.policy_exempt)) {
    effective = {
      ...effective,
      disabled: true,
      disabled_reason: modelSupport?.disabled_reason || meta.disabled_reason || commandDisabledReason(support, selectedCommandModel())
    };
  }
  const exactSupport = currentExactLiveSupport();
  if (!exactSupport) {
    effective.live_support_status = modelSupport?.policy_exempt
      ? modelSupport.support_reason
      : "Connection scope not evaluated";
    return effective;
  }
  const exactCommand = exactSupport.commands?.[name];
  if (!exactCommand) {
    return {
      ...effective,
      disabled: true,
      disabled_reason: "Live support metadata is missing for this command.",
      live_support_status: "Live support metadata is missing for this command."
    };
  }
  effective.live_support_status = exactCommandSupportText(exactCommand, exactSupport);
  if (!exactCommand.policy_exempt && exactCommand.product_open !== true) {
    effective.disabled = true;
    effective.disabled_reason = exactCommand.disabled_reason || effective.live_support_status;
  }
  return effective;
}

function exactCommandSupportText(commandSupport, liveSupport) {
  if (commandSupport.offline_only) {
    return "Offline utility; live exact scope is not applicable.";
  }
  if (commandSupport.policy_exempt) {
    return "Identity/status diagnostic; exact model feature scope is not required.";
  }
  const scope = `${transportScopeLabel(liveSupport.transport_scope)} / ${backendScopeLabel(liveSupport.backend_scope)}`;
  if (commandSupport.exact_scope_validation_status === "live_validated_full_suite") {
    return `Live validated: ${scope}`;
  }
  if (["transport_pending", "feature_pending"].includes(commandSupport.exact_scope_validation_status)) {
    return `Pending live validation: ${scope}`;
  }
  if (commandSupport.profile_validation_status === "not_supported_by_model") {
    return `Not supported by ${liveSupport.display_name || liveSupport.model_name || liveSupport.model_id}`;
  }
  return commandSupport.disabled_reason || `No product-open live scope is registered for ${scope}`;
}

function selectedCommandSupport(name) {
  const model = selectedCommandModel();
  if (!model) return null;
  return state.commandSupportByModel?.[model]?.[name] || null;
}

function currentResourceModel() {
  const resource = valueOrNull("resource");
  if (!resource) return null;
  return detectedCommandModelForResource(resource);
}

function supportedModelKey(model) {
  const modelId = String(model || "").trim();
  return state.commandSupportByModel[modelId] ? modelId : null;
}

function commandDisabledReason(support, model) {
  const validation = support?.hardware_validation;
  const displayModel = physicalModelDisplayName(model);
  if (validation === "planning_only") return `Planning only on ${displayModel}`;
  if (validation === "not_supported_by_model") return `Not supported on ${displayModel}`;
  return `Unavailable on ${displayModel}`;
}

function exactSupportContextSummary(resource) {
  if (!resource) return "Connection scope not evaluated";
  const liveSupport = currentExactLiveSupport();
  if (!liveSupport) return "Connection scope not evaluated";
  return liveSupportSummary(liveSupport);
}

function liveSupportSummary(liveSupport) {
  if (!liveSupport || liveSupport.evaluated !== true) return "Connection scope not evaluated";
  const commands = Object.values(liveSupport.commands || {});
  const validated = commands.filter((entry) => entry.product_open === true && !entry.policy_exempt).length;
  const pending = commands.filter((entry) => ["transport_pending", "feature_pending"].includes(entry.exact_scope_validation_status)).length;
  const unavailable = commands.filter((entry) => !entry.policy_exempt && !entry.offline_only && entry.product_open !== true && !["transport_pending", "feature_pending"].includes(entry.exact_scope_validation_status)).length;
  const scope = `${transportScopeLabel(liveSupport.transport_scope)} / ${backendScopeLabel(liveSupport.backend_scope)}`;
  return `${scope}: ${validated} validated, ${pending} pending, ${unavailable} unavailable`;
}

function transportScopeLabel(scope) {
  return ({ usb: "USB", tcpip: "TCPIP", asrl: "ASRL", gpib: "GPIB", unknown: "Unknown transport" })[scope] || "--";
}

function backendScopeLabel(scope) {
  return ({ system_visa: "system VISA", pyvisa_py: "pyvisa-py", custom_visa: "custom VISA" })[scope] || "--";
}

function supportedChannelsForCurrentModel() {
  const capability = channelCapabilityForCurrentModel();
  if (!capability || !capability.channels.length) return [...DEFAULT_CHANNELS];
  return [...capability.channels];
}

function isChannelSupported(channel) {
  if (!isNumericChannel(channel)) return true;
  return supportedChannelsForCurrentModel().includes(Number(channel));
}

function isNumericChannel(channel) {
  return /^[1-9]\d*$/.test(String(channel));
}

function channelUnsupportedReason(channel) {
  if (isChannelSupported(channel)) return "";
  const model = currentChannelCapabilityModel();
  return model ? `${physicalModelDisplayName(model)} does not support channel ${channel}` : "";
}

function channelCapabilityForCurrentModel() {
  return channelCapabilityForModel(currentChannelCapabilityModel());
}

function channelCapabilityForModel(model) {
  const modelId = String(model || "").trim();
  if (!modelId) return null;
  const metadata = state.channelCapabilitiesByModel?.[modelId];
  if (Array.isArray(metadata)) {
    return {
      channels: metadata.map(Number).filter(Number.isInteger),
      output_control_scope: "unknown"
    };
  }
  if (!metadata || typeof metadata !== "object") return null;
  const channels = Array.isArray(metadata.channels)
    ? metadata.channels.map(Number).filter(Number.isInteger)
    : [];
  return {
    channels,
    output_control_scope: typeof metadata.output_control_scope === "string" ? metadata.output_control_scope : "unknown"
  };
}

function currentChannelCapabilityModel() {
  return selectedChannelModel();
}

function channelModelKey(model) {
  const modelId = String(model || "").trim();
  return channelCapabilityForModel(modelId) ? modelId : null;
}

function channelAvailabilityGuardReason(command, parameters = {}) {
  const channels = selectedChannelsForCommand(command, parameters);
  const unsupported = channels.find((channel) => !isChannelSupported(channel));
  return unsupported === undefined ? "" : channelUnsupportedReason(unsupported);
}

function selectedChannelsForCommand(command, parameters = {}) {
  if (command === "ramp-list") {
    return [...new Set((parameters.document?.segments || []).map((segment) => Number(segment.channel)).filter(Number.isInteger))];
  }
  if (command === "trigger-list") return [Number(parameters.channel)].filter(Number.isInteger);
  if (command === "sequence") {
    return [...new Set((parameters.document?.steps || [])
      .map((step) => step.channel)
      .filter((channel) => channel !== undefined && channel !== "all")
      .map(Number)
      .filter(Number.isInteger))];
  }
  const selected = parameters.channel;
  if (selected === undefined || selected === null || selected === "" || selected === "all") return [];
  const channel = Number(selected);
  return Number.isInteger(channel) ? [channel] : [];
}

function outputControlTitle(channel, enabled, fresh) {
  const base = fresh ? `CH${channel} output is ${enabled ? "ON" : "OFF"}.` : `CH${channel} output state is unknown.`;
  return outputControlScopeForCurrentModel() === "global" ? `${base} ${globalOutputHintText()}` : base;
}

function outputAllControlTitle(allOn) {
  const base = allOn ? "All supported outputs are ON." : "One or more supported outputs are OFF or unknown.";
  return outputControlScopeForCurrentModel() === "global" ? `${base} ${globalOutputHintText()}` : base;
}

function outputControlScopeForCurrentModel() {
  return channelCapabilityForCurrentModel()?.output_control_scope || "unknown";
}

function globalOutputHintText() {
  const model = currentChannelCapabilityModel();
  return model ? `${physicalModelDisplayName(model)} output enable is global for supported channels.` : "Output enable is global for supported channels.";
}

function toggleResultPanel() {
  state.resultCollapsed = !state.resultCollapsed;
  syncResultPanelState();
}

function expandResultPanel() {
  state.resultCollapsed = false;
  syncResultPanelState();
}

function syncResultPanelState() {
  const panel = document.getElementById("result-panel");
  const button = document.getElementById("result-toggle");
  panel.classList.toggle("collapsed", state.resultCollapsed);
  button.textContent = state.resultCollapsed ? "+" : "-";
  button.setAttribute("aria-label", state.resultCollapsed ? "Expand result" : "Collapse result");
  button.setAttribute("aria-expanded", String(!state.resultCollapsed));
}

function toggleJobResultPanel() {
  state.jobResultCollapsed = !state.jobResultCollapsed;
  const panel = document.getElementById("job-result-panel");
  const button = document.getElementById("job-result-toggle");
  panel.classList.toggle("collapsed", state.jobResultCollapsed);
  button.textContent = state.jobResultCollapsed ? "+" : "-";
  button.setAttribute("aria-label", state.jobResultCollapsed ? "Expand job result" : "Collapse job result");
  button.setAttribute("aria-expanded", String(!state.jobResultCollapsed));
}

function clearJobResults() {
  state.jobs = [];
  renderHistory();
}

async function startLive() {
  if (isNoHardwareMode()) {
    renderBlankLivePanel("error", "Live Data is available only in Real hardware mode.");
    return;
  }
  const payload = { runtime: runtimePayload(), parameters: { interval_ms: 5000 } };
  if (!payload.runtime.resource) {
    renderLivePanel({ status: "error", stale: true, message: "Select or enter a hardware resource before starting Live Data." });
    return;
  }
  try {
    stopLivePreviewSnapshot();
    updateLiveMonitorButton(false, true);
    const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) });
    state.liveJobId = response.job_id;
    updateLiveMonitorButton(true, false);
    closeEventSource("liveEvents");
    state.liveEvents = new EventSource(response.events_url);
    state.liveEvents.addEventListener("progress", (event) => renderLivePanel(JSON.parse(event.data).data));
    state.liveEvents.addEventListener("finished", () => {
      state.liveJobId = null;
      updateLiveMonitorButton(false, false);
      setLiveState("Not monitoring", "state-idle", "Live Data monitor is stopped.");
      closeEventSource("liveEvents");
    });
    state.liveEvents.addEventListener("failed", (event) => {
      const message = JSON.parse(event.data).data?.error || "Live Data monitor failed.";
      renderLivePanel({ status: "error", stale: true, message });
      state.liveJobId = null;
      updateLiveMonitorButton(false, false);
      closeEventSource("liveEvents");
    });
  } catch (error) {
    renderLivePanel({ status: "error", stale: true, message: error.message || String(error) });
    state.liveJobId = null;
    updateLiveMonitorButton(false, false);
  }
}

async function toggleLiveMonitor() {
  if (state.liveJobId || state.liveEvents) {
    await stopLive();
  } else {
    await startLive();
  }
}

async function stopLive() {
  if (!state.liveJobId) return;
  updateLiveMonitorButton(true, true);
  try {
    const jobId = state.liveJobId;
    await fetchJson(`/api/live/${jobId}/stop`, { method: "POST" });
    closeEventSource("liveEvents");
    await waitForLiveTerminal(jobId);
    state.liveJobId = null;
    updateLiveMonitorButton(false, false);
    setLiveState("Not monitoring", "state-idle", "Live Data monitor is stopped.");
  } catch (error) {
    renderLivePanel({ status: "error", stale: true, message: error.message || String(error) });
    updateLiveMonitorButton(true, false);
  }
}

async function startLivePreviewSnapshot(healthState, resource = null) {
  if (isNoHardwareMode()) return;
  stopLivePreviewSnapshot();
  setLiveState("Refreshing once...", "state-warning", "Refreshing Live Data once after command completion.");
  if (!healthState?.serverReady || !healthState?.deviceIdle) {
    renderBlankLivePanel("error", "Server or hardware is not ready.");
    setLiveState("Refresh blocked", "state-error", "Server or command path is not ready for a one-shot Live Data refresh.");
    return;
  }
  const payload = { runtime: runtimePayload(), parameters: { interval_ms: 1000 } };
  if (resource) payload.runtime.resource = resource;
  if (!payload.runtime.resource) {
    renderBlankLivePanel();
    setLiveState("Not monitoring", "state-idle", "No hardware resource is selected.");
    return;
  }
  try {
    const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) });
    state.previewJobId = response.job_id;
    let handledFreshSample = false;
    state.previewEvents = new EventSource(response.events_url);
    state.previewEvents.addEventListener("progress", (event) => {
      if (handledFreshSample) return;
      const sample = JSON.parse(event.data).data;
      renderLivePanel(sample);
      if (!isFreshLivePreviewSample(sample)) return;
      handledFreshSample = true;
      stopLivePreviewSnapshot();
    });
    state.previewEvents.addEventListener("failed", (event) => {
      const error = JSON.parse(event.data).data?.error || "Snapshot preview failed.";
      renderBlankLivePanel("error", error);
      setLiveState(liveStateText("error", Date.now() / 1000, error), "state-error", error);
      stopLivePreviewSnapshot();
    });
  } catch (error) {
    const message = error.message || String(error);
    renderBlankLivePanel("error", message);
    setLiveState(liveStateText("error", Date.now() / 1000, message), "state-error", message);
  }
}

function isFreshLivePreviewSample(sample) {
  return Boolean(
    sample
    && sample.stale === false
    && sample.status !== "busy"
    && sample.status !== "error"
    && Array.isArray(sample.channels)
  );
}

async function waitForLiveTerminal(jobId) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const job = await fetchJson(`/api/jobs/${jobId}`);
    if (["cancelled", "finished", "failed"].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Live Data stop timed out while waiting for the backend job to finish.");
}

function pulseTimingDisplayName(command, value) {
  if (value === "") return "None";
  const labels = command === "ramp"
    ? { step: "Every step", segment: "Ramp complete", loop: "Loop complete" }
    : command === "ramp-list"
      ? { step: "Every step", segment: "Segment complete", loop: "Loop complete" }
      : {};
  return labels[value] || optionDisplayName(value);
}

function refreshLoopCompleteOption(command) {
  const timing = command === "ramp"
    ? document.getElementById("param-completion_pulse_timing")
    : command === "ramp-list"
      ? document.getElementById("ramp-list-pulse-timing")
      : null;
  if (!timing) return;
  const loopChecked = command === "ramp"
    ? Boolean(document.getElementById("param-loop_enabled")?.checked)
    : state.rampListLoopEnabled;
  const enabled = command === "ramp"
    ? loopChecked
    : loopChecked && effectiveRampListLoopCount() >= 2;
  const loopOption = Array.from(timing.options || []).find((option) => option.value === "loop");
  if (loopOption) {
    loopOption.disabled = !enabled;
    loopOption.title = enabled ? "" : "Enable loop to select Loop complete.";
  }
  if (!loopChecked && timing.value === "loop") timing.value = "";
}

function renderLoopControl({
  prefix,
  current = 1,
  onValue = () => {},
  onDisable = () => {},
  enabledInput = null,
  countInputId = null,
  loopEnabled = null,
  countDraft = null,
  onEnabled = () => {},
  onDraft = () => {}
}) {
  const hasExplicitState = typeof loopEnabled === "boolean";
  const wrapper = document.createElement("div");
  wrapper.className = "loop-control " + prefix + "-loop-control";
  const enabled = enabledInput || document.createElement("input");
  enabled.type = "checkbox";
  enabled.id ||= prefix + "-loop-enabled";
  enabled.checked = hasExplicitState ? loopEnabled : Number.isInteger(current) && current >= 2;
  wrapper.appendChild(createCheckboxField(enabled, "Enable loop"));

  const mountCount = (value = 2) => {
    wrapper.querySelector?.(".loop-count-field")?.remove();
    const label = document.createElement("label");
    label.className = "loop-count-field";
    label.textContent = "Loop count";
    const count = document.createElement("input");
    count.type = "number";
    count.id = countInputId || prefix + "-loop-count";
    count.min = "2";
    count.max = "255";
    count.step = "1";
    count.required = true;
    count.value = hasExplicitState
      ? String(value ?? "")
      : String(Number.isInteger(value) && value >= 2 && value <= 255 ? value : 2);
    const update = () => {
      const parsed = count.value === "" ? Number.NaN : Number(count.value);
      onDraft(count.value);
      onValue(Number.isInteger(parsed) && parsed >= 2 && parsed <= 255 ? parsed : Number.NaN);
      refreshLoopCompleteOption(prefix);
      if (["ramp-list", "sequence"].includes(prefix)) updateWorkflowDocumentValidity(prefix);
      updateSelectedCommandState();
    };
    count.addEventListener("input", update);
    count.addEventListener("change", update);
    label.appendChild(count);
    wrapper.appendChild(label);
  };

  enabled.addEventListener("change", () => {
    onEnabled(enabled.checked);
    if (enabled.checked) {
      onDraft("2");
      onValue(2);
      mountCount(2);
    } else {
      onDraft("2");
      onValue(1);
      wrapper.querySelector?.(".loop-count-field")?.remove();
      onDisable();
    }
    refreshLoopCompleteOption(prefix);
    if (["ramp-list", "sequence"].includes(prefix)) updateWorkflowDocumentValidity(prefix);
    updateSelectedCommandState();
  });
  if (enabled.checked) mountCount(hasExplicitState ? countDraft : current);
  return wrapper;
}

function stopLivePreviewSnapshot() {
  const jobId = state.previewJobId;
  closeEventSource("previewEvents");
  state.previewJobId = null;
  if (jobId) {
    fetchJson(`/api/live/${jobId}/stop`, { method: "POST" }).catch((error) => {
      console.error("Live preview stop failed", error);
    });
  }
}

async function refreshSelectedResourcePreview(resource) {
  if (isNoHardwareMode()) return;
  stopLivePreviewSnapshot();
  renderBlankLivePanel();
  if (!resource) {
    setLiveState("Not monitoring", "state-idle", "No hardware resource is selected.");
    return;
  }
  const healthState = await refreshHealth();
  await startLivePreviewSnapshot(healthState, resource);
}

function basicActionKey(action, channel) {
  return `${action}:${channel}`;
}

function basicActionDisplayName(actionKey) {
  const [kind, target] = actionKey.split(":");
  const action = kind === "set" ? "Set" : "Output";
  return target === "all" ? `Basic All ${action}` : `Basic CH${target} ${action}`;
}

function basicLiveChannel(channel) {
  const panel = state.livePanel;
  const resource = valueOrNull("resource");
  if (!panel || panel.stale || !resource || panel.resource !== resource) return null;
  return (panel.channels || []).find((item) => Number(item.channel) === Number(channel)) || null;
}

function basicChannelOutputState(channel) {
  const liveChannel = basicLiveChannel(channel);
  if (!liveChannel || liveChannel.stale || liveChannel.error || typeof liveChannel.output_enabled !== "boolean") {
    return "unknown";
  }
  return liveChannel.output_enabled ? "on" : "off";
}

function e3646aGlobalOutputState(presentation = basicOutputPresentation()) {
  if (presentation.mode !== "e3646a-global") return "unknown";
  const states = presentation.capability.channels.map((channel) => basicChannelOutputState(channel));
  if (states.every((value) => value === "on")) return "on";
  if (states.every((value) => value === "off")) return "off";
  return "unknown";
}

function basicAllOutputsOn() {
  const presentation = basicOutputPresentation();
  if (presentation.mode === "e3646a-global") {
    return e3646aGlobalOutputState(presentation) === "on";
  }
  const panel = state.livePanel;
  const resource = valueOrNull("resource");
  if (!panel || panel.stale || !resource || panel.resource !== resource) return false;
  const channels = panel.channels || [];
  return supportedChannelsForCurrentModel().every((channel) => channels.find((item) => Number(item.channel) === channel)?.output_enabled === true);
}

function setBasicActionState(actionKey, status, message = "", context = {}) {
  state.basicActionStates[actionKey] = { ...context, status, message };
  renderBasicActionState(actionKey);
  setBasicStatus(status === "pending" ? message || "Basic command running..." : message || basicStatusText(status));
}

function clearBasicActionState(actionKey) {
  delete state.basicActionStates[actionKey];
  renderBasicActionState(actionKey);
  if (!Object.keys(state.basicActionStates).length) setBasicStatus("");
}

function renderBasicActionState(actionKey) {
  const action = state.basicActionStates[actionKey];
  const [kind, target] = actionKey.split(":");
  if (kind === "output") {
    renderBasicOutputActionStates();
    if (target === "all") {
      DEFAULT_CHANNELS.forEach((channel) => renderBasicChannelActionState(channel));
    } else {
      renderBasicChannelActionState(Number(target));
    }
    return;
  }
  const selector = `[data-basic-set="${target}"]`;
  const button = document.querySelector(selector);
  if (button) {
    button.classList.toggle("basic-action-pending", action?.status === "pending");
    button.classList.toggle("basic-action-success", action?.status === "success");
    button.classList.toggle("basic-action-error", action?.status === "error");
    button.title = action?.message || "";
  }
  if (target !== "all") renderBasicChannelActionState(Number(target));
}

function renderBasicChannelActionState(channel) {
  const card = document.querySelector(`[data-basic-channel="${channel}"]`);
  if (!card) return;
  const unsupported = channelUnsupportedReason(channel);
  const setState = state.basicActionStates[basicActionKey("set", channel)]?.status;
  const outputState = state.basicActionStates[basicActionKey("output", channel)]?.status;
  const allOutputState = state.basicActionStates[basicActionKey("output", "all")]?.status;
  card.classList.toggle("unsupported", Boolean(unsupported));
  card.setAttribute("aria-disabled", String(Boolean(unsupported)));
  card.title = unsupported || "";
  const setButton = card.querySelector("[data-basic-set]");
  if (setButton) {
    const setMeta = commandMeta("set");
    setButton.disabled = Boolean(unsupported || setMeta.disabled);
    setButton.title = unsupported || setMeta.disabled_reason || setMeta.live_support_status || "";
  }
  card.classList.toggle("basic-action-error", setState === "error" || outputState === "error" || allOutputState === "error");
  card.classList.toggle("basic-action-pending", setState === "pending" || outputState === "pending" || allOutputState === "pending");
}

function updateBasicActionFromJob(jobId, event, job) {
  const action = state.basicJobActions[jobId];
  if (!action) return;
  if (event.type === "finished" && job?.status === "finished") {
    if (action.command === "set") {
      clearBasicInputDirty(action.parameters.channel);
      setBasicActionState(action.actionKey, "success", "Basic command completed.", action);
    } else if (typeof action.desiredOutput === "boolean" && state.executionMode === "real") {
      setBasicActionState(action.actionKey, "pending", "Waiting for Live Data readback.", { ...action, awaitingReadback: true });
    } else {
      setBasicActionState(action.actionKey, "success", state.executionMode === "simulate" ? "Simulation completed." : state.executionMode === "dry-run" ? "Plan generated." : "Basic command completed.", action);
    }
  } else {
    const detail = job?.error || event.data?.error || eventSummary(event);
    setBasicActionState(action.actionKey, "error", detail, action);
  }
  delete state.basicJobActions[jobId];
}

function syncBasicFromLivePanel(panel) {
  refreshBasicInputConstraints();
  const resource = valueOrNull("resource");
  const fresh = Boolean(panel && !panel.stale && resource && panel.resource === resource);
  DEFAULT_CHANNELS.forEach((channel) => {
    const liveChannel = fresh ? (panel.channels || []).find((item) => Number(item.channel) === channel) : null;
    syncBasicSetpointInput(channel, "voltage", liveChannel?.set_voltage, fresh);
    syncBasicSetpointInput(channel, "current", liveChannel?.set_current, fresh);
    renderBasicOutputButton(channel, liveChannel, fresh);
    clearResolvedBasicErrors(channel, liveChannel, fresh);
    renderBasicChannelActionState(channel);
  });
  renderBasicAllOutputButton(fresh ? panel.channels || [] : []);
  renderBasicOutputActionStates();
  applyBasicOutputPresentation();
}

function syncBasicSetpointInput(channel, kind, value, fresh) {
  const input = document.querySelector(`[data-basic-${kind}="${channel}"]`);
  if (!input) return;
  if (!fresh || typeof value !== "number" || !Number.isFinite(value)) return;
  if (input.dataset.basicDirty === "true") return;
  input.value = String(value);
  validateBasicInput(input);
}

function clearBasicInputDirty(channel) {
  document.querySelectorAll(`[data-basic-voltage="${channel}"], [data-basic-current="${channel}"]`).forEach((input) => {
    delete input.dataset.basicDirty;
  });
}

function renderBasicOutputButton(channel, liveChannel, fresh) {
  const button = document.querySelector(`[data-basic-output="${channel}"]`);
  if (!button) return;
  const unsupported = channelUnsupportedReason(channel);
  const enabled = fresh && liveChannel?.output_enabled === true;
  button.textContent = "ON";
  button.classList.toggle("on", enabled);
  button.classList.toggle("off", !enabled);
  button.setAttribute("aria-pressed", String(enabled));
  button.setAttribute("aria-label", `CH${channel} output ${enabled ? "on" : "off"}`);
  button.disabled = Boolean(unsupported);
  button.title = unsupported || outputControlTitle(channel, enabled, fresh);
  applyBasicPerChannelOutputPresentation(channel, button);
}

function renderBasicAllOutputButton(channels) {
  const button = document.querySelector("[data-basic-all-output]");
  if (!button) return;
  const presentation = basicOutputPresentation();
  if (presentation.mode === "e3646a-global") {
    const globalState = e3646aGlobalOutputState(presentation);
    button.textContent = globalState === "on"
      ? "Turn outputs off"
      : globalState === "off"
        ? "Turn outputs on"
        : "Output state unknown";
    button.classList.toggle("on", globalState === "on");
    button.classList.toggle("off", globalState === "off");
    button.classList.toggle("unknown", globalState === "unknown");
    button.setAttribute("aria-pressed", globalState === "on" ? "true" : globalState === "off" ? "false" : "mixed");
    button.setAttribute("aria-label", `All-channel output: ${button.textContent}`);
    button.disabled = globalState === "unknown";
    button.title = globalState === "unknown" ? "Fresh synchronized CH1 and CH2 output readback is required." : outputAllControlTitle(globalState === "on");
    applyBasicOutputPresentation();
    return;
  }
  const supported = supportedChannelsForCurrentModel();
  const allOn = supported.length > 0 && supported.every((channel) => channels.find((item) => Number(item.channel) === channel)?.output_enabled === true);
  button.textContent = "ALL ON";
  button.classList.toggle("on", allOn);
  button.classList.toggle("off", !allOn);
  button.classList.remove("unknown");
  button.setAttribute("aria-pressed", String(allOn));
  button.setAttribute("aria-label", `All outputs ${allOn ? "on" : "not all on"}`);
  button.title = outputAllControlTitle(allOn);
  applyBasicOutputPresentation();
}

function applyBasicPerChannelOutputPresentation(channel, button, presentation = basicOutputPresentation()) {
  const status = document.querySelector(`[data-basic-output-status="${channel}"]`);
  const info = document.querySelector(`[data-basic-output-info="${channel}"]`);
  const readOnly = presentation.mode === "e3646a-global"
    && presentation.capability.channels.includes(channel);

  button.hidden = readOnly;
  if (readOnly) button.disabled = true;
  if (presentation.mode === "e3646a-disabled") {
    button.disabled = true;
    button.title = E3646A_CAPABILITY_ERROR;
  }

  if (status) {
    status.hidden = !readOnly;
    status.classList.remove("on", "off", "unknown");
    if (readOnly) {
      const outputState = basicChannelOutputState(channel);
      status.textContent = outputState.toUpperCase();
      status.classList.add(outputState);
      status.setAttribute("aria-label", `CH${channel} output status ${status.textContent}`);
    }
  }
  if (info) {
    info.hidden = !readOnly;
    info.title = E3646A_GLOBAL_OUTPUT_DESCRIPTION;
  }
}

function applyBasicAllOutputPresentation(button, presentation = basicOutputPresentation()) {
  if (presentation.mode === "e3646a-disabled") {
    button.disabled = true;
    button.title = E3646A_CAPABILITY_ERROR;
  } else if (presentation.mode === "e3646a-global" && e3646aGlobalOutputState(presentation) === "unknown") {
    button.disabled = true;
    button.title = "Fresh synchronized CH1 and CH2 output readback is required.";
  }
}

function applyBasicOutputPresentation() {
  const presentation = basicOutputPresentation();
  const allButton = document.querySelector("[data-basic-all-output]");
  const headerSlot = document.getElementById("basic-output-all-header-slot");
  const globalSlot = document.getElementById("basic-output-all-global-slot");
  const globalRow = document.getElementById("basic-e3646a-output-row");
  const capabilityStatus = document.getElementById("basic-output-capability-status");

  if (allButton) {
    const targetSlot = presentation.mode === "e3646a-global" ? globalSlot : headerSlot;
    if (targetSlot && allButton.parentNode !== targetSlot) targetSlot.appendChild(allButton);
    applyBasicAllOutputPresentation(allButton, presentation);
  }
  if (globalRow) globalRow.hidden = presentation.mode !== "e3646a-global";
  if (capabilityStatus) {
    const disabled = presentation.mode === "e3646a-disabled";
    capabilityStatus.hidden = !disabled;
    capabilityStatus.textContent = disabled ? E3646A_CAPABILITY_ERROR : "";
  }
  DEFAULT_CHANNELS.forEach((channel) => {
    const button = document.querySelector(`[data-basic-output="${channel}"]`);
    if (button) applyBasicPerChannelOutputPresentation(channel, button, presentation);
  });
}

function renderBasicOutputActionStates() {
  DEFAULT_CHANNELS.forEach((channel) => renderBasicOutputControlState(channel));
  renderBasicOutputControlState("all");
  applyBasicOutputPresentation();
}

function renderBasicOutputControlState(target) {
  const button = target === "all"
    ? document.querySelector("[data-basic-all-output]")
    : document.querySelector(`[data-basic-output="${target}"]`);
  if (!button) return;
  const unsupported = target === "all" ? "" : channelUnsupportedReason(target);
  const actionKey = basicActionKey("output", target);
  const ownAction = state.basicActionStates[actionKey];
  const lockAction = basicOutputLockAction(target);
  const enabled = target === "all"
    ? basicAllOutputsOn()
    : basicLiveChannel(Number(target))?.output_enabled === true;
  const commandMetaForState = commandMeta(enabled ? "output-off" : "output-on");
  button.disabled = Boolean(unsupported || lockAction || commandMetaForState.disabled);
  button.classList.toggle("basic-action-pending", Boolean(lockAction));
  button.classList.toggle("basic-action-success", !lockAction && ownAction?.status === "success");
  button.classList.toggle("basic-action-error", !lockAction && ownAction?.status === "error");
  if (unsupported) {
    button.title = unsupported;
  } else if (lockAction) {
    button.title = lockAction.message || "Waiting for Live Data readback.";
  } else if (commandMetaForState.disabled) {
    button.title = commandMetaForState.disabled_reason || "This output action is unavailable for the exact live scope.";
  } else if (ownAction?.message) {
    button.title = ownAction.message;
  } else {
    button.title = commandMetaForState.live_support_status || button.title;
  }
  if (target === "all") applyBasicAllOutputPresentation(button);
  else applyBasicPerChannelOutputPresentation(Number(target), button);
}

function basicOutputLockAction(target) {
  const allAction = state.basicActionStates[basicActionKey("output", "all")];
  if (allAction?.status === "pending") return allAction;
  if (target === "all") {
    const presentation = basicOutputPresentation();
    const channels = presentation.mode === "e3646a-global"
      ? presentation.capability.channels
      : supportedChannelsForCurrentModel();
    return channels
      .map((channel) => state.basicActionStates[basicActionKey("output", channel)])
      .find((action) => action?.status === "pending") || null;
  }
  const channelAction = state.basicActionStates[basicActionKey("output", target)];
  return channelAction?.status === "pending" ? channelAction : null;
}

function clearResolvedBasicErrors(channel, liveChannel, fresh) {
  if (!fresh || !liveChannel) return;
  const setKey = basicActionKey("set", channel);
  const outputKey = basicActionKey("output", channel);
  if (state.basicActionStates[setKey]?.status === "error" && liveSetpointsMatchBasicInputs(channel, liveChannel)) {
    clearBasicActionState(setKey);
  }
  const outputAction = state.basicActionStates[outputKey];
  if (outputAction?.status === "pending" && outputAction.awaitingReadback === true && typeof outputAction.desiredOutput === "boolean" && liveChannel.output_enabled === outputAction.desiredOutput) {
    setBasicActionState(outputKey, "success", "Basic command completed.", outputAction);
  } else if (outputAction?.status === "error" && typeof outputAction.desiredOutput === "boolean" && liveChannel.output_enabled === outputAction.desiredOutput) {
    clearBasicActionState(outputKey);
  }
  const allAction = state.basicActionStates[basicActionKey("output", "all")];
  if (typeof allAction?.desiredOutput === "boolean") {
    const presentation = basicOutputPresentation();
    const globalState = presentation.mode === "e3646a-global" ? e3646aGlobalOutputState(presentation) : null;
    const channels = state.livePanel?.channels || [];
    const allMatched = presentation.mode === "e3646a-global"
      ? globalState === (allAction.desiredOutput ? "on" : "off")
      : presentation.mode === "e3646a-disabled"
        ? false
        : supportedChannelsForCurrentModel().every((item) => channels.find((entry) => Number(entry.channel) === item)?.output_enabled === allAction.desiredOutput);
    if (allMatched && allAction.status === "pending" && allAction.awaitingReadback === true) {
      setBasicActionState(basicActionKey("output", "all"), "success", "Basic command completed.", allAction);
    } else if (allMatched && allAction.status === "error") {
      clearBasicActionState(basicActionKey("output", "all"));
    }
  }
}

function liveSetpointsMatchBasicInputs(channel, liveChannel) {
  const values = basicSetpointValues(channel);
  if (!values.ok) return false;
  const expected = values.parameters;
  if (expected.voltage !== undefined && !nearlyEqual(expected.voltage, liveChannel.set_voltage)) return false;
  if (expected.current !== undefined && !nearlyEqual(expected.current, liveChannel.set_current)) return false;
  return true;
}

function nearlyEqual(left, right) {
  return typeof right === "number" && Number.isFinite(right) && Math.abs(Number(left) - right) <= 1e-9;
}

function basicStatusText(status) {
  if (status === "success") return "Basic command completed.";
  if (status === "error") return "Basic command failed. See Result Detail.";
  return "Live Data remains the source of instrument state.";
}

function setBasicStatus(text) {
  const status = document.getElementById("basic-command-status");
  if (status) status.textContent = text || "Live Data remains the source of instrument state.";
}

function renderLivePanel(data) {
  const previous = state.livePanel;
  const resource = data.resource || previous?.resource || "";
  const sameResource = previous?.resource === resource;
  const next = {
    timestamp: data.timestamp || previous?.timestamp || Date.now() / 1000,
    resource,
    model: data.model || (sameResource ? previous?.model : null),
    model_id: data.model_id || (sameResource ? previous?.model_id : null),
    stale: Boolean(data.stale),
    status: data.status || "ok",
    message: data.message || data.error || "",
    channels: mergeLiveChannels(
      data.channels,
      sameResource ? previous?.channels : [],
      Boolean(data.stale && sameResource)
    )
  };
  state.livePanel = next;
  state.samples.push({ timestamp: next.timestamp, data: next });
  state.samples = state.samples.slice(-60);
  const modelChanged = !next.stale && updateResourceModel(next.resource, next.model_id, next.model);

  setLiveState(liveStateText(next.status, next.timestamp, next.message, next.stale), liveStateClass(next.status, next.stale), next.message);

  if (next.resource && next.resource === valueOrNull("resource")) updateDeviceResourceSummary();
  next.channels.forEach((channel) => renderChannelCard(channel, next));
  syncBasicFromLivePanel(next);
  if (modelChanged) renderCommands();
  if (modelChanged) refreshBasicInputConstraints();
  if (state.selected) updateSelectedCommandState();
  drawTrend();
}

function setLiveState(text, stateClass = "state-idle", title = "") {
  setStateIndicator("live-state", text, stateClass, title || text);
}

function liveStateText(status, timestamp, message = "", stale = false) {
  const lastUpdate = timestamp ? new Date(timestamp * 1000).toLocaleTimeString() : "never";
  return `${status}${stale ? " stale" : ""} - last update ${lastUpdate}${message ? ` - ${message}` : ""}`;
}

function liveStateClass(status, stale = false) {
  if (status === "error") return "state-error";
  if (stale || status === "busy") return "state-warning";
  return "state-ok";
}

function renderBlankLivePanel(status = "ok", message = "") {
  const panel = {
    timestamp: Date.now() / 1000,
    resource: valueOrNull("resource") || "",
    model: null,
    model_id: null,
    stale: false,
    status,
    message,
    channels: blankLiveChannels()
  };
  state.livePanel = panel;
  panel.channels.forEach((channel) => renderChannelCard(channel, panel));
  syncBasicFromLivePanel(panel);
  drawTrend();
}

function blankLiveChannels() {
  return DEFAULT_CHANNELS.map((channel) => ({
    channel,
    output_enabled: null,
    measured_voltage: null,
    measured_current: null,
    set_voltage: null,
    set_current: null,
    over_voltage_tripped: null,
    over_current_tripped: null,
    protection_tripped: null,
    over_voltage_protection_level: null,
    over_current_protection_enabled: null
  }));
}

function mergeLiveChannels(channels, previousChannels = [], preservePreviousValues = false) {
  const byChannel = new Map((Array.isArray(previousChannels) ? previousChannels : []).map((item) => [Number(item.channel), item]));
  const blankChannels = blankLiveChannels();
  (Array.isArray(channels) ? channels : []).forEach((item) => {
    const existing = byChannel.get(Number(item.channel));
    byChannel.set(Number(item.channel), mergeLiveChannel(existing, item, preservePreviousValues));
  });
  return DEFAULT_CHANNELS.map((channel) => byChannel.get(channel) || blankChannels[channel - 1]);
}

function mergeLiveChannel(previous, incoming, preservePreviousValues) {
  if (!preservePreviousValues || !previous) return { ...previous, ...incoming };
  const next = { ...previous, ...incoming };
  [
    "output_enabled",
    "measured_voltage",
    "measured_current",
    "set_voltage",
    "set_current",
    "over_voltage_tripped",
    "over_current_tripped",
    "protection_tripped",
    "over_voltage_protection_level",
    "over_current_protection_enabled"
  ].forEach((key) => {
    if (incoming[key] === null || incoming[key] === undefined) next[key] = previous[key];
  });
  return next;
}

function renderChannelCard(channel, sample) {
  const card = document.querySelector(`[data-channel-card="${channel.channel}"]`);
  if (!card) return;
  const unsupported = channelUnsupportedReason(channel.channel);
  if (unsupported) {
    card.className = "live-card unsupported";
    card.setAttribute("aria-disabled", "true");
    card.title = unsupported;
    card.innerHTML = `
    <div class="live-card-head">
      <strong>CH${channel.channel}</strong>
      <span class="status-badge status-indicator output-status unknown">
        <span class="indicator-dot" aria-hidden="true"></span>
        <span class="indicator-text">Unsupported</span>
      </span>
    </div>
    <div class="live-output-section">
      <div class="live-measured">
        <div><span>N/A</span><small>OUT V</small></div>
        <div><span>N/A</span><small>OUT A</small></div>
      </div>
    </div>
    <div class="live-control-section">
      <div class="live-setpoints">
        <div><span>N/A</span><small>SET V</small></div>
        <div><span>N/A</span><small>SET A</small></div>
      </div>
      <div class="live-protection-section">
        <div class="live-protection-badges">
          <span class="protection-badge status-indicator unknown">
            <span class="indicator-dot" aria-hidden="true"></span>
            <span class="indicator-text">Unsupported</span>
          </span>
        </div>
      </div>
    </div>
  `;
    return;
  }
  card.setAttribute("aria-disabled", "false");
  card.title = "";
  const outputClass = channel.output_enabled === true ? "on" : channel.output_enabled === false ? "off" : "unknown";
  const outputText = channel.output_enabled === true ? "ON" : channel.output_enabled === false ? "OFF" : "--";
  const protectionClass = channel.protection_tripped === true ? "protection-tripped" : "";
  card.className = `live-card ${sample.stale ? "stale" : ""} ${sample.status === "error" ? "error" : ""} ${protectionClass}`;
  card.innerHTML = `
    <div class="live-card-head">
      <strong>CH${channel.channel}</strong>
      <span class="status-badge status-indicator output-status ${outputClass}">
        <span class="indicator-dot" aria-hidden="true"></span>
        <span class="indicator-text">OUT ${outputText}</span>
      </span>
    </div>
    <div class="live-output-section">
      <div class="live-measured">
        <div><span>${formatNum(channel.measured_voltage)}</span><small>OUT V</small></div>
        <div><span>${formatNum(channel.measured_current)}</span><small>OUT A</small></div>
      </div>
    </div>
    <div class="live-control-section">
      <div class="live-setpoints">
        <div><span>${formatNum(channel.set_voltage)}</span><small>SET V</small></div>
        <div><span>${formatNum(channel.set_current)}</span><small>SET A</small></div>
      </div>
      <div class="live-protection-section">
        <div class="live-protection-badges">
          ${protectionBadge("OVP", channel.over_voltage_tripped)}
          ${protectionBadge("OCP", channel.over_current_tripped)}
        </div>
        <div class="protection-settings">
          <div><span>${formatProtectionVoltage(channel.over_voltage_protection_level)}</span><small>OVP</small></div>
          <div><span>${formatProtectionState(channel.over_current_protection_enabled)}</span><small>OCP</small></div>
        </div>
      </div>
    </div>
    ${channel.protection_tripped === true && !sample.stale
      ? `<button type="button" class="clear-protection-shortcut" data-clear-protection-channel="${channel.channel}">Clear Protection</button>`
      : ""}
  `;
  const shortcut = card.querySelector("[data-clear-protection-channel]");
  if (shortcut) shortcut.addEventListener("click", () => openClearProtection(channel.channel));
}

function protectionBadge(label, tripped) {
  const stateClass = tripped === true ? "trip" : tripped === false ? "ok" : "unknown";
  const stateText = tripped === true ? "TRIP" : tripped === false ? "CLEAR" : "--";
  return `<span class="protection-badge status-indicator ${stateClass}">
    <span class="indicator-dot" aria-hidden="true"></span>
    <span class="indicator-text">${label} ${stateText}</span>
  </span>`;
}

function openClearProtection(channel) {
  setAdvancedCommandsExpanded(true);
  state.activeCategory = "protection";
  selectCommand("clear-protection");
  const input = document.getElementById("param-channel");
  if (input) input.value = String(channel);
  updateSelectedCommandState();
  const workspace = document.querySelector(".workspace");
  if (workspace) workspace.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const focusTarget = input || document.getElementById("run");
  if (focusTarget) focusTarget.focus({ preventScroll: true });
}

function prefillClearProtectionChannel() {
  if (state.selected !== "clear-protection") return;
  const input = document.getElementById("param-channel");
  if (!input) return;
  const channels = currentTripChannels();
  input.value = channels.length === 1 ? String(channels[0]) : "";
}

function updateSelectedCommandState() {
  if (!state.selected) return;
  syncTriggerImmediateControls(state.selected);
  const meta = commandMeta(state.selected);
  let parameters = {};
  try {
    parameters = parameterPayload();
  } catch (e) {
    // Keep the form responsive while artifact editors contain invalid JSON.
  }
  const tripGuard = tripGuardReason(state.selected, parameters);
  const channelGuard = channelAvailabilityGuardReason(state.selected, parameters);
  const ratingGuard = electricalRatingGuardReason(state.selected, parameters);
  const setGuard = setRequiresSetpointGuardReason(state.selected, parameters);
  const triggerControlGuard = triggerControlGuardReason(state.selected, parameters);
  const triggerFireWaitGuard = triggerFireWaitGuardReason(state.selected, parameters);
  const workflowPulseGuard = workflowPulseGuardReason(state.selected, parameters);
  const tripWarning = tripContextWarning(state.selected);
  const runButton = document.getElementById("run");
  const commandDescription = document.getElementById("command-description");
  const descriptionText = [meta.description, meta.live_support_status, channelGuard, ratingGuard, setGuard, tripGuard || tripWarning].filter(Boolean).join(" ");
  commandDescription.textContent = descriptionText;
  commandDescription.title = descriptionText;
  renderCommandGuidance(state.selected, parameters);
  if (state.workflowControl.phase !== "idle") {
    runButton.disabled = state.workflowControl.phase !== "active";
    updateWorkflowRunButton();
    return;
  }
  runButton.disabled = Boolean(meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard || workflowPulseGuard);
  runButton.disabled ||= !validateConstrainedInputs();
  if (state.selected === "restore-from-snapshot") {
    const restoreValid = isLoadedRestoreSnapshotValid();
    runButton.disabled ||= !restoreValid;
    const previewButton = document.getElementById("btn-preview-restore-plan");
    if (previewButton) previewButton.disabled = !restoreValid || state.restorePlanPreviewStatus === "running";
  }
  if (["sequence", "ramp-list"].includes(state.selected)) {
    updateWorkflowDocumentValidity(state.selected, runButton);
  }
  if (workflowPulseGuard) commandDescription.textContent = [descriptionText, workflowPulseGuard].filter(Boolean).join(" ");
}

function updateWorkflowDocumentValidity(command, runButton = null) {
  let valid = true;
  try {
    if (command === "sequence") sequenceDocumentFromEditor();
    else if (command === "ramp-list") validateRampListDocument(rampListDocument());
  } catch (e) {
    valid = false;
  }
  const saveButton = document.getElementById(command === "sequence" ? "save-sequence" : "save-ramp-list");
  if (saveButton) saveButton.disabled = !valid;
  if (runButton) runButton.disabled ||= !valid;
  return valid;
}

function syncTriggerImmediateControls(command) {
  if (!["trigger-step", "trigger-list"].includes(command)) return;
  const source = String(document.getElementById("param-source")?.value || "bus").toLowerCase();
  const fire = document.getElementById("param-fire");
  if (!fire) return;
  const immediate = ["immediate", "imm"].includes(source);
  if (immediate) fire.checked = false;
  fire.disabled = immediate;
  fire.title = immediate ? "Immediate starts when INIT is sent; Fire now does not apply." : "";
}

function triggerControlGuardReason(command, parameters) {
  if (!["trigger-step", "trigger-list"].includes(command)) return "";
  const source = String(parameters.source || "bus").toLowerCase();
  const immediate = ["immediate", "imm"].includes(source);
  if (immediate && parameters.fire) {
    return "Immediate starts from INIT and does not accept Fire now.";
  }
  if (source === "bus" && parameters.wait_complete && !parameters.fire) {
    return "BUS Wait complete requires Fire now in the same command.";
  }
  if (command === "trigger-list") {
    if ([...(parameters.bost_list || []), ...(parameters.eost_list || [])].some(Boolean) && !(parameters.trigger_output_pins || []).length) {
      return "BOST/EOST pulses require LIST output pins.";
    }
    const started = immediate || (source === "bus" && parameters.fire);
    if (!started && !parameters.leave_trigger_configured) {
      return "Arm-only LIST requires Leave configured so a later Trigger fire can start it.";
    }
    if (started && !parameters.wait_complete && !parameters.leave_trigger_configured) {
      return "A started LIST without Wait complete requires Leave configured.";
    }
  }
  return "";
}

function triggerFireWaitGuardReason(command, parameters) {
  if (command !== "trigger-fire") return "";
  if (parameters.wait_complete && parameters.channel == null) {
    return "Wait complete requires an Abort target channel.";
  }
  return "";
}

function setRequiresSetpointGuardReason(command, parameters) {
  if (command !== "set") return "";
  return parameters.voltage === undefined && parameters.current === undefined
    ? "Set requires Voltage, Current, or both."
    : "";
}

function electricalRatingGuardReason(command, parameters) {
  const model = selectedElectricalRatingModel();
  const ratings = state.electricalRatingsByModel?.[model]?.channels;
  if (!Array.isArray(ratings)) return "";
  const displayModel = physicalModelDisplayName(model);
  const check = (channel, voltage, current) => {
    const selected = channel === "all" ? ratings : ratings.filter((rating) => String(rating.channel) === String(channel));
    for (const rating of selected) {
      if (voltage !== undefined && voltage !== null && Number(voltage) > Number(rating.max_voltage)) return `Voltage ${voltage} exceeds official DC output rating ${rating.max_voltage} V for ${displayModel} channel ${rating.channel}.`;
      if (current !== undefined && current !== null && Number(current) > Number(rating.max_current)) return `Current ${current} exceeds official DC output rating ${rating.max_current} A for ${displayModel} channel ${rating.channel}.`;
    }
    return "";
  };
  if (["set", "apply", "smoke-output"].includes(command)) return check(parameters.channel, parameters.voltage, parameters.current);
  if (command === "ramp") return check(parameters.channel, Math.max(Number(parameters.start_voltage), Number(parameters.stop_voltage)), parameters.current);
  if (command === "ramp-list") for (const segment of state.rampListSegments) { const reason = check(segment.channel, Math.max(Number(segment.start_voltage), Number(segment.stop_voltage)), segment.current); if (reason) return reason; }
  if (command === "trigger-step") return check(parameters.channel, parameters.voltage, parameters.current);
  if (command === "trigger-list") for (const voltage of parameters.voltage_list || []) for (const current of parameters.current_list || []) { const reason = check(parameters.channel, voltage, current); if (reason) return reason; }
  if (command === "sequence") for (const step of state.sequenceSteps) if (["set", "apply"].includes(step.action)) { const reason = check(step.channel ?? 1, step.voltage, step.current); if (reason) return reason; }
  if (command === "restore-from-snapshot" && state.loadedSnapshotDocument) for (const record of state.loadedSnapshotDocument.readback || []) { if (state.restoreChannel !== "all" && String(record.channel) !== String(state.restoreChannel)) continue; const reason = check(record.channel, record.setpoints?.voltage, record.setpoints?.current); if (reason) return reason; }
  return "";
}

function pulseControlsUnavailableReason() {
  const resource = valueOrNull("resource");
  const expected = selectedExpectedModel();
  const detected = detectedChannelModelForResource(resource);
  const supportedModel = physicalModelDisplayName(REAR_TRIGGER_PULSE_MODEL_ID);
  if (expected && resourceModelDetectionRecorded(resource) && detected !== expected) {
    const detectedModel = detected ? physicalModelDisplayName(detected) : "an unknown model";
    return `Expected ${physicalModelDisplayName(expected)} does not match detected ${detectedModel}. Rear trigger pulse is only supported on ${supportedModel}.`;
  }
  const model = selectedChannelModel();
  if (model === REAR_TRIGGER_PULSE_MODEL_ID) return "";
  if (!model) return `Rear trigger pulse is only supported on ${supportedModel}; no supported model is selected or detected.`;
  return `Rear trigger pulse is only supported on ${supportedModel}, not ${physicalModelDisplayName(model)}.`;
}

function applyWorkflowPulseControlState(input, prerequisiteReason = "") {
  const unavailable = pulseControlsUnavailableReason();
  const unknownModel = !selectedChannelModel()
    && !(
      selectedExpectedModel()
      && resourceModelDetectionRecorded(valueOrNull("resource"))
      && detectedChannelModelForResource(valueOrNull("resource")) !== selectedExpectedModel()
    );
  const reason = (unknownModel ? "" : unavailable) || prerequisiteReason;
  input.disabled = Boolean(reason);
  input.title = reason;
}

function workflowPulseGuardReason(command, parameters) {
  return commandRequestsPulse(command, parameters) ? pulseControlsUnavailableReason() : "";
}

function commandRequestsPulse(command, parameters) {
  if (command === "cycle-output" || command === "ramp") return Boolean(parameters.completion_pulse_pins);
  if (command === "ramp-list") return Boolean(parameters.document?.completion_pulse);
  if (command === "sequence") return Boolean(parameters.document?.steps?.some((step) => step.action === "trigger-pulse"));
  return false;
}

function currentTripChannels() {
  const panel = state.livePanel;
  const resource = valueOrNull("resource");
  if (!panel || panel.stale || !resource || panel.resource !== resource) return [];
  return panel.channels
    .filter((channel) => channel.protection_tripped === true)
    .map((channel) => Number(channel.channel))
    .filter((channel) => Number.isInteger(channel));
}

function tripGuardReason(command, parameters) {
  if (!TRIP_GUARDED_COMMANDS.has(command)) return "";
  if (command === "apply" && parameters.no_output === true) return "";
  const tripped = currentTripChannels();
  if (!tripped.length) return "";
  const selected = parameters.channel;
  const rampListChannels = command === "ramp-list"
    ? [...new Set((parameters.document?.segments || []).map((segment) => Number(segment.channel)))]
    : [];
  const blocked = command === "ramp-list"
    ? tripped.filter((channel) => rampListChannels.includes(channel))
    : selected === "all" ? tripped : tripped.filter((channel) => channel === Number(selected));
  if (!blocked.length) return "";
  return `Protection TRIP active on ${blocked.map((channel) => `CH${channel}`).join(", ")}. Clear protection before running ${command}.`;
}

function tripContextWarning(command) {
  if (!TRIP_WARNING_COMMANDS.has(command)) return "";
  const tripped = currentTripChannels();
  if (!tripped.length) return "";
  return `Warning: protection TRIP active on ${tripped.map((channel) => `CH${channel}`).join(", ")}.`;
}

function formatProtectionVoltage(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "--";
}

function formatProtectionState(value) {
  return value === true ? "ON" : value === false ? "OFF" : "--";
}

function drawTrend() {
  const canvas = document.getElementById("trend");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#d7dee6";
  ctx.beginPath();
  ctx.moveTo(32, 12);
  ctx.lineTo(32, 160);
  ctx.lineTo(620, 160);
  ctx.stroke();
  const values = state.samples.map((sample) => normalizeMeasurements(sample)[0]?.voltage).filter((v) => Number.isFinite(v));
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 0.001);
  ctx.strokeStyle = "#1f7a8c";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = 36 + index * (580 / Math.max(values.length - 1, 1));
    const y = 156 - ((value - min) / span) * 136;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function normalizeMeasurements(sample) {
  const data = sample.data;
  if (data.channels) {
    return data.channels.map((item) => ({
      channel: item.channel,
      voltage: item.measured_voltage ?? item.measurements?.voltage,
      current: item.measured_current ?? item.measurements?.current
    }));
  }
  if (data.data && data.data.channels) {
    return data.data.channels.map((item) => ({ channel: item.channel, ...item.measurements }));
  }
  const entries = Object.entries(data).filter(([, value]) => value && typeof value === "object" && "voltage" in value);
  if (entries.length) return entries.map(([channel, value]) => ({ channel, ...value }));
  return [{ channel: data.channel || "all", voltage: data.voltage, current: data.current }];
}

function addHistory(jobId, command, status, label = command) {
  const displayLabel = commandDisplayName(label);
  state.jobs.unshift({ jobId, command, label: displayLabel, status, summary: statusSummary(status) });
  state.jobs = state.jobs.slice(0, 20);
  renderHistory();
  updateExecutionModeUi();
}

function updateHistory(jobId, status) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (job) {
    job.status = status;
    job.summary = statusSummary(status);
  }
  renderHistory();
  updateExecutionModeUi();
}

function updateJobResult(jobId, status, summary) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (!job) return;
  job.status = status;
  job.summary = summary || statusSummary(status);
  renderHistory();
  updateExecutionModeUi();
}

function renderHistory() {
  const history = document.getElementById("job-history");
  history.innerHTML = "";
  state.jobs.forEach((job) => {
    const item = document.createElement("div");
    item.className = "history-item";
    const label = document.createElement("strong");
    label.textContent = job.label;
    const badge = document.createElement("span");
    badge.className = `result-status ${statusClass(job.status)}`;
    badge.textContent = statusLabel(job.status);
    const summary = document.createElement("span");
    summary.className = "result-summary";
    summary.textContent = job.summary || statusSummary(job.status);
    item.append(label, " - ", badge, " - ", summary);
    history.appendChild(item);
  });
}

function jobSummary(job, event = null) {
  const status = job?.status || event?.type;
  if (status === "failed" && (job?.error_code || event?.data?.code) === "cleanup_failed") return "Failed  cleanup_failed";
  if (status === "failed") return job?.error || event?.data?.error || "Command failed";
  if (status === "cancelled") return "Cancelled";
  if (status !== "finished") return statusSummary(status);
  return successfulJobSummary(job);
}

function eventSummary(event) {
  if (event?.type === "cancel_requested") return "Waiting for safe-off and cleanup";
  if (event?.type === "failed" && event.data?.code === "cleanup_failed") return "Failed  cleanup_failed";
  if (event?.type === "failed") return event.data?.error || "Command failed";
  if (event?.type === "cancelled") return "Cancelled";
  return statusSummary(event?.type);
}

function successfulJobSummary(job) {
  const result = job?.result || {};
  const runtime = job?.runtime || {};
  const command = job?.command;
  if (command === "capabilities") return capabilitiesSummary(result);
  if (command === "identify") return identifySummary(result);
  if (command === "verify") return verifySummary(result);
  if (command === "read-status") return readStatusSummary(result);
  if (command === "readback") return readbackSummary(result);
  if (command === "snapshot") return snapshotSummary(result);
  if (command === "error") return errorQueueSummary(result, "instrument");
  if (command === "safety inspect") return safetyInspectSummary(result);
  if (Array.isArray(result.resources)) {
    const count = result.resources.length;
    return `${count} resource${count === 1 ? "" : "s"} found`;
  }
  if (runtime.dry_run || result.dry_run || result.plan) return "Plan generated";
  const resource = result.resource || result;
  const model = resource?.idn?.model || result.driver?.model;
  if (resource?.name || model || result.command_support || result.driver) {
    return model ? `Connected to ${model}` : "Connected to resource";
  }
  return "Command completed successfully";
}

function capabilitiesSummary(result) {
  const resource = result.resource;
  const model = resource?.idn?.model || result.driver?.model;
  const driver = result.driver?.class;
  if (resource?.name || model || driver) {
    return compactParts([
      model ? `Connected to ${model}` : "Connected to resource",
      driver
    ]).join(" - ");
  }
  if (result.models && typeof result.models === "object") {
    const count = Object.keys(result.models).length;
    return `${count} available model${count === 1 ? "" : "s"}`;
  }
  return "Command completed successfully";
}

function identifySummary(result) {
  const idn = result.idn || result.resource?.idn || {};
  const parts = compactParts([
    idn.model,
    idn.serial ? `serial ${idn.serial}` : "",
    idn.firmware ? `firmware ${idn.firmware}` : ""
  ]);
  return parts.length ? parts.join(" - ") : "Identification read";
}

function verifySummary(result) {
  const resource = result.resource || {};
  const model = resource.idn?.model;
  if (model && resource.name) return `Reachable ${model} at ${resource.name}`;
  if (model) return `Reachable ${model}`;
  if (resource.name) return `Reachable resource ${resource.name}`;
  return "Resource reachable";
}

function readStatusSummary(result) {
  const outputText = outputStatesSummary(result.outputs);
  return compactParts([outputText, errorQueueSummary(result, "")]).join(" - ") || "Status read";
}

function readbackSummary(result) {
  const channels = Array.isArray(result.channels) ? result.channels : [];
  const count = channels.length;
  return compactParts([
    `${count} channel${count === 1 ? "" : "s"}`,
    setpointSummary(channels)
  ]).join(" - ");
}

function snapshotSummary(result) {
  const model = result.idn?.model;
  const outputCount = Array.isArray(result.outputs) ? result.outputs.length : 0;
  const channelCount = Array.isArray(result.readback) ? result.readback.length : outputCount;
  const protection = result.protection || {};
  const tripped = protection.over_voltage_tripped === true || protection.over_current_tripped === true;
  return compactParts([
    model,
    `${channelCount} channel${channelCount === 1 ? "" : "s"}`,
    outputCount ? `${outputCount} output${outputCount === 1 ? "" : "s"}` : "",
    `protection ${tripped ? "tripped" : "OK"}`,
    errorQueueSummary(result, "")
  ]).join(" - ");
}

function safetyInspectSummary(result) {
  return result.safety_config_loaded ? "Safety config loaded" : "Safety config not loaded";
}

function outputStatesSummary(outputs) {
  if (!Array.isArray(outputs) || outputs.length === 0) return "";
  return outputs
    .map((item) => `CH${item.channel} ${item.enabled === true ? "ON" : item.enabled === false ? "OFF" : "--"}`)
    .join(", ");
}

function setpointSummary(channels) {
  if (!Array.isArray(channels) || channels.length === 0) return "";
  return channels
    .slice(0, 3)
    .map((item) => {
      const setpoints = item.setpoints || {};
      return `CH${item.channel} ${formatSetpointValue(setpoints.voltage)}V/${formatSetpointValue(setpoints.current)}A`;
    })
    .join(", ");
}

function formatSetpointValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  return String(value);
}

function errorQueueSummary(result, noun = "instrument") {
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const label = noun ? `${noun} ` : "";
  if (errors.length === 0) return `No ${label}errors`;
  return `${errors.length} ${label}error${errors.length === 1 ? "" : "s"}`;
}

function compactParts(parts) {
  return parts.filter((part) => part !== null && part !== undefined && part !== "");
}

function statusSummary(status) {
  if (status === "accepted") return "Accepted";
  if (status === "started") return "Started";
  if (status === "progress" || status === "running") return "Running";
  if (status === "cancel_requested") return "Waiting for safe-off and cleanup";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed" || status === "error") return "Command failed";
  if (status === "finished") return "Command completed successfully";
  return status || "Pending";
}

function statusLabel(status) {
  if (status === "finished") return "Success";
  if (status === "failed" || status === "error") return "Failed";
  if (status === "cancelled") return "Cancelled";
  if (status === "progress" || status === "running") return "Running";
  if (status === "started") return "Started";
  if (status === "accepted") return "Accepted";
  return status || "Pending";
}

function statusClass(status) {
  if (status === "finished") return "success";
  if (status === "failed" || status === "error") return "failed";
  if (status === "cancelled") return "cancelled";
  return "running";
}

function closeEventSource(name) {
  if (state[name]) {
    state[name].close();
    state[name] = null;
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || JSON.stringify(payload));
  return payload;
}

function parseMaybeJson(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return {};
  try { return JSON.parse(trimmed); } catch { return {}; }
}

function valueOrNull(id) {
  const value = document.getElementById(id).value.trim();
  return value || null;
}

function formatNum(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "--";
}
