const state = {
  commands: {},
  commandSupportByModel: {},
  resourceModels: {},
  activeCategory: "output",
  selected: null,
  jobs: [],
  events: null,
  liveEvents: null,
  liveJobId: null,
  previewEvents: null,
  previewJobId: null,
  samples: [],
  livePanel: null,
  resultCollapsed: true,
  jobResultCollapsed: false,
  rampListSegments: [defaultRampSegment()],
  latestSnapshotDocument: null,
  latestSnapshotMetadata: null,
  loadedSnapshotDocument: null,
  loadedSnapshotFilename: "",
  sequenceFilename: "",
  sequenceTextareaValue: undefined,
  restoreChannel: "all",
  restoreOutputState: false,
  restorePlanPreview: null,
  restorePlanPreviewStatus: "idle"
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

const PARAMS = {
  "list-resources": [{ name: "live_only", type: "checkbox", label: "Live only" }],
  verify: [],
  clear: [],
  error: [{ name: "max_reads", type: "number", label: "Max reads", value: 20 }],
  readback: [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  set: baseOutputParams(),
  apply: [...applyOutputParams(), { name: "no_output", type: "checkbox", label: "Do not enable output" }],
  "output-on": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "output-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "safe-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  "cycle-output": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }, { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 }],
  ramp: [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 },
    { name: "start_voltage", type: "number", label: "Start voltage(V)", value: 0 },
    { name: "stop_voltage", type: "number", label: "Stop voltage(V)", value: 1 },
    { name: "step_voltage", type: "number", label: "Step voltage(V)", value: 0.1 },
    { name: "delay_ms", type: "number", label: "Delay(ms)", value: 0 }
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
    { name: "pins", type: "text", label: "Pins", value: "1", parser: "intList" },
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive" },
    { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins" }
  ],
  "trigger-status": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  "trigger-step": triggerStepParams(),
  "trigger-list": triggerListParams(),
  "trigger-fire": [
    { name: "channel", type: "select", label: "Channel", options: ["", "1", "2", "3"], value: "", optional: true },
    { name: "wait_complete", type: "checkbox", label: "Wait complete" },
    ...triggerWaitParams()
  ],
  "trigger-abort": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" },
    { name: "max_errors", type: "number", label: "Max errors", value: 20 }
  ],
  identify: [],
  snapshot: [{
    name: "max_errors",
    type: "number",
    label: "Max errors",
    value: 20,
    description: "Limits how many times the snapshot reads the instrument error queue. Reading stops early when the instrument reports no error. Each reported error is removed from the instrument queue."
  }],
  sequence: [{ name: "document", type: "textarea", label: "Sequence document", value: "{}" }]
};

function baseOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 }
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
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Triggered voltage(V)", optional: true },
    { name: "current", type: "number", label: "Triggered current(A)", optional: true },
    { name: "source", type: "select", label: "Source", options: ["bus", "immediate", "pin1", "pin2", "pin3", "ext"], value: "bus" },
    { name: "fire", type: "checkbox", label: "Fire now" },
    { name: "wait_complete", type: "checkbox", label: "Wait complete" },
    ...triggerWaitParams(),
    { name: "leave_trigger_configured", type: "checkbox", label: "Leave configured" }
  ];
}

function triggerListParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage_list", type: "text", label: "Voltage list(V)", value: "0,1", parser: "numberList" },
    { name: "current_list", type: "text", label: "Current list(A)", value: "0.05", parser: "numberList" },
    { name: "dwell_list", type: "text", label: "Dwell list(s)", value: "0.01", parser: "numberList" },
    { name: "count", type: "number", label: "Count", value: 1 },
    { name: "source", type: "select", label: "Source", options: ["bus", "immediate", "pin1", "pin2", "pin3", "ext"], value: "bus" },
    { name: "fire", type: "checkbox", label: "Fire now" },
    { name: "wait_complete", type: "checkbox", label: "Wait complete" },
    { name: "completion_pulse_pins", type: "text", label: "Pulse pins", optional: true, parser: "intList" },
    { name: "completion_pulse_polarity", type: "select", label: "Pulse polarity", options: ["positive", "negative"], value: "positive" },
    { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins" },
    ...triggerWaitParams(),
    { name: "leave_trigger_configured", type: "checkbox", label: "Leave configured" }
  ];
}

function triggerWaitParams() {
  return [
    { name: "poll_ms", type: "number", label: "Poll(ms)", value: 200 },
    { name: "wait_timeout_ms", type: "number", label: "Timeout(ms)", optional: true }
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
  document.getElementById("command-filter").addEventListener("input", renderCommands);
  document.getElementById("live-start").addEventListener("click", startLive);
  document.getElementById("live-stop").addEventListener("click", stopLive);
  document.getElementById("result-toggle").addEventListener("click", toggleResultPanel);
  document.getElementById("job-result-toggle").addEventListener("click", toggleJobResultPanel);
  document.getElementById("job-result-clear").addEventListener("click", clearJobResults);
}

async function refreshHealth() {
  try {
    const health = await fetchJson("/api/health");
    const serverReady = health.status === "ok";
    const deviceIdle = !health.hardware_locked;
    const serverState = serverReady ? "Server ready" : `Server ${health.status}`;
    const hardwareState = deviceIdle ? "hardware idle" : "hardware locked by a job";
    document.getElementById("server-state").textContent = serverState;
    document.getElementById("device-state").textContent = hardwareState;
    return { serverReady, deviceIdle };
  } catch (error) {
    document.getElementById("server-state").textContent = "Server error";
    document.getElementById("device-state").textContent = "hardware unknown";
    renderBlankLivePanel("error", error.message || String(error));
    return { serverReady: false, deviceIdle: false, error };
  }
}

async function loadCommands() {
  const payload = await fetchJson("/api/commands");
  state.commands = payload.commands || {};
  state.commandSupportByModel = payload.command_support_by_model || {};
  renderCommands();
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
      button.disabled = Boolean(effectiveMeta.disabled);
      button.innerHTML = `<span>${commandDisplayName(name)}</span><small>${effectiveMeta.disabled_reason || ""}</small>`;
      button.addEventListener("click", () => selectCommand(name));
      list.appendChild(button);
    });
}

function selectCommand(name) {
  state.selected = name;
  document.getElementById("selected-command").textContent = commandDisplayName(name);
  renderForm(name);
  prefillClearProtectionChannel();
  updateSelectedCommandState();
  renderCommands();
}

function renderForm(command) {
  const form = document.getElementById("command-form");
  form.innerHTML = "";
  if (command === "ramp-list") {
    renderRampListForm(form);
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
    const label = document.createElement("label");
    if (param.type === "checkbox") label.classList.add("checkbox-field");
    label.textContent = param.label;
    let input;
    if (param.type === "select") {
      input = document.createElement("select");
      param.options.forEach((option) => {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = optionDisplayName(option);
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
    input.addEventListener("change", updateSelectedCommandState);
    label.appendChild(input);
    appendFieldDescription(label, param);
    form.appendChild(label);
  });
}

function appendFieldDescription(label, param) {
  if (!param.description) return;
  const description = document.createElement("small");
  description.className = "field-description";
  description.textContent = param.description;
  label.appendChild(description);
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
    button.disabled = text === "Add Ramp Segment" && state.rampListSegments.length >= 10;
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  editor.appendChild(toolbar);
  state.rampListSegments.forEach((segment, index) => editor.appendChild(rampSegmentCard(segment, index)));
  form.appendChild(editor);
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

function rampListDocument() {
  return {
    kind: "keysight-power-ramp-list",
    version: 1,
    segments: state.rampListSegments.map((segment) => ({ ...segment }))
  };
}

function validateRampListDocument(document) {
  if (!document || document.kind !== "keysight-power-ramp-list" || document.version !== 1) {
    throw new Error("Invalid Ramp List kind or version.");
  }
  if (Object.keys(document).some((field) => !["kind", "version", "segments"].includes(field))) {
    throw new Error("Ramp List contains unsupported fields.");
  }
  if (!Array.isArray(document.segments) || document.segments.length < 1 || document.segments.length > 10) {
    throw new Error("Ramp List requires 1 to 10 segments.");
  }
  const fields = rampSegmentDefinitions().map((item) => item.name);
  return document.segments.map((segment, index) => {
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
}

async function loadRampList() {
  try {
    const { text } = await openJsonFile({
      description: "Ramp List JSON",
      extensions: RAMP_LIST_JSON_EXTENSIONS
    });
    const segments = validateRampListDocument(JSON.parse(text));
    state.rampListSegments = segments;
    renderForm("ramp-list");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult("ramp-list", "failed", error.message || String(error), { error: "Ramp List load failed", detail: error.message || String(error) });
  }
}

async function saveRampList() {
  const documentText = `${JSON.stringify(rampListDocument(), null, 2)}\n`;
  try {
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

/* ==========================================
   Shared JSON File Helpers
   ========================================== */

const JSON_MIME_TYPE = "application/json";
const SNAPSHOT_JSON_EXTENSIONS = [".snapshot.json", ".json"];
const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];
const RAMP_LIST_JSON_EXTENSIONS = [".ramp-list.json", ".json"];

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
      description: "Keysight Power Snapshot JSON",
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

  let model = meta?.model || doc?.idn?.model;
  let serial = meta?.serial || doc?.idn?.serial;

  const clean = (str) => {
    if (!str) return "";
    return String(str).replace(/[<>:"/\\|?*]/g, "").trim();
  };

  model = clean(model);
  serial = clean(serial);

  if (model && serial) {
    return `keysight-power-${model}-${serial}-${timestamp}.snapshot.json`;
  }
  return `keysight-power-snapshot-${timestamp}.snapshot.json`;
}

function validateSnapshotDocument(doc) {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("Snapshot document must be a JSON object.");
  }
  if (!doc.idn || typeof doc.idn !== "object" || Array.isArray(doc.idn)) {
    throw new Error("Snapshot must contain a valid 'idn' object.");
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
  const restoreStateLabel = document.createElement("label");
  restoreStateLabel.className = "checkbox-field";
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

  restoreStateLabel.appendChild(restoreStateCheck);
  restoreStateLabel.appendChild(document.createTextNode(" Restore previous output ON/OFF state"));
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
      description: "Keysight Power Snapshot JSON",
      extensions: SNAPSHOT_JSON_EXTENSIONS
    });
    const rawDoc = JSON.parse(text);
    const unwrapped = unwrapSnapshot(rawDoc);
    validateRestoreSnapshot(unwrapped);

    state.loadedSnapshotDocument = unwrapped;
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

function unwrapSnapshot(doc) {
  if (!doc || typeof doc !== "object") {
    throw new Error("Invalid Snapshot format.");
  }
  if (doc.command === "snapshot" && doc.result && typeof doc.result === "object" && !Array.isArray(doc.result)) {
    return doc.result;
  }
  if (doc.data && typeof doc.data === "object" && !Array.isArray(doc.data)) {
    return doc.data;
  }
  return doc;
}

function validateRestoreSnapshot(doc) {
  validateSnapshotDocument(doc);
  if (!doc.idn.model) {
    throw new Error("Snapshot must contain a valid 'idn' object with 'model'.");
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

  if (doc.idn.model !== "E36312A") {
    throw new Error(`Snapshot model '${doc.idn.model}' is not supported. Only 'E36312A' is supported for restore.`);
  }
}

/* ==========================================
   Sequence Feature
   ========================================== */

function renderSequenceForm(form) {
  const editor = document.createElement("div");
  editor.className = "artifact-editor";

  const toolbar = document.createElement("div");
  toolbar.className = "artifact-toolbar";

  const loadBtn = document.createElement("button");
  loadBtn.type = "button";
  loadBtn.className = "secondary";
  loadBtn.id = "btn-load-sequence";
  loadBtn.textContent = "Load Sequence";
  loadBtn.addEventListener("click", loadSequenceFile);
  toolbar.appendChild(loadBtn);

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "secondary";
  saveBtn.id = "btn-save-sequence";
  saveBtn.textContent = "Save Sequence";
  saveBtn.addEventListener("click", saveSequenceFile);
  toolbar.appendChild(saveBtn);

  const fileStatus = document.createElement("span");
  fileStatus.id = "sequence-file-status";
  fileStatus.className = "artifact-file-status";
  fileStatus.textContent = state.sequenceFilename
    ? `Loaded: ${state.sequenceFilename}`
    : "";
  toolbar.appendChild(fileStatus);
  editor.appendChild(toolbar);

  const textLabel = document.createElement("label");
  textLabel.textContent = "Sequence document";
  const textarea = document.createElement("textarea");
  textarea.id = "param-document";
  textarea.className = "artifact-preview";

  const paramDef = PARAMS["sequence"][0];
  textarea.value = state.sequenceTextareaValue !== undefined ? state.sequenceTextareaValue : paramDef.value;

  const onInput = (e) => {
    state.sequenceTextareaValue = e.target.value;
    updateSelectedCommandState();
  };
  textarea.addEventListener("input", onInput);
  textarea.addEventListener("change", onInput);

  textLabel.appendChild(textarea);
  editor.appendChild(textLabel);

  form.appendChild(editor);
}

async function loadSequenceFile() {
  try {
    const { text, filename } = await openJsonFile({
      description: "Keysight Power Sequence JSON",
      extensions: SEQUENCE_JSON_EXTENSIONS
    });
    const rawDoc = JSON.parse(text);
    validateSequenceDocument(rawDoc);

    state.sequenceTextareaValue = JSON.stringify(rawDoc, null, 2);
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
  const rawVal = document.getElementById("param-document")?.value || "{}";
  try {
    const rawDoc = JSON.parse(rawVal);
    validateSequenceDocument(rawDoc);

    const prettyDocument = JSON.stringify(rawDoc, null, 2);
    state.sequenceTextareaValue = prettyDocument;
    const textarea = document.getElementById("param-document");
    if (textarea) textarea.value = prettyDocument;
    const documentText = `${prettyDocument}\n`;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const suggestedName = `keysight-power-sequence-${timestamp}.sequence.json`;

    await saveJsonFile(documentText, {
      description: "Keysight Power Sequence JSON",
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

function validateSequenceDocument(doc) {
  const allowedActions = new Set([
    "measure",
    "readback",
    "output-state",
    "log",
    "wait",
    "safe-off",
    "set",
    "output-on",
    "output-off",
    "cycle-output",
    "apply"
  ]);

  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("Sequence document must be a JSON object.");
  }
  if (doc.version !== undefined && doc.version !== 1 && doc.version !== "1") {
    throw new Error("Sequence version must be 1.");
  }
  if (!doc.steps || !Array.isArray(doc.steps) || doc.steps.length === 0) {
    throw new Error("Sequence document must contain a non-empty 'steps' array.");
  }

  doc.steps.forEach((step, index) => {
    if (!step) {
      throw new Error(`Sequence step at index ${index} is null or empty.`);
    }

    // 1. String action format.
    if (typeof step === "string") {
      if (!allowedActions.has(step)) {
        if (step === "delay") {
          throw new Error(`Unsupported sequence action "delay" at step ${index + 1}. Did you mean "wait"?`);
        }
        throw new Error(`Unsupported sequence action string "${step}" at step ${index + 1}.`);
      }
      return;
    }

    // 2. Object action/type format.
    if (typeof step === "object" && !Array.isArray(step)) {
      const keys = Object.keys(step);

      const hasAction = "action" in step;
      const hasType = "type" in step;

      if (hasAction || hasType) {
        if (hasAction && hasType && step.action !== step.type) {
          throw new Error(`Step ${index + 1} has conflicting 'action' ("${step.action}") and 'type' ("${step.type}") values.`);
        }
        const action = step.action ?? step.type;
        if (!allowedActions.has(action)) {
          if (action === "delay") {
            throw new Error(`Unsupported sequence action "delay" at step ${index + 1}. Did you mean "wait"?`);
          }
          throw new Error(`Unsupported sequence action "${action}" at step ${index + 1}.`);
        }
        return;
      }

      // Shorthand format.
      if (keys.length === 1) {
        const key = keys[0];
        if (allowedActions.has(key)) {
          return;
        }
        if (key === "delay") {
          throw new Error(`Unsupported sequence action "delay" at step ${index + 1}. Did you mean "wait"?`);
        }
        throw new Error(`Unsupported shorthand sequence action "${key}" at step ${index + 1}.`);
      }

      throw new Error(`Step ${index + 1} is invalid. Objects with multiple keys must contain an 'action' or 'type' property.`);
    }

    throw new Error(`Invalid step format at index ${index + 1}.`);
  });
}

function sequenceDocumentFromEditor() {
  const rawVal = document.getElementById("param-document")?.value || "{}";
  const parsed = JSON.parse(rawVal);
  validateSequenceDocument(parsed);
  return parsed;
}

async function scanResources() {
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

async function runSelected() {
  if (!state.selected) return;

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
  if (meta.requires_confirm && !payload.runtime.confirm) {
    renderClientResult(state.selected, "failed", "This command affects real hardware output. Check confirmation before running.", {
      error: "Confirmation required",
      detail: "This command affects real hardware output. Check confirmation before running.",
      command: state.selected,
      runtime: { confirm: false }
    });
    return;
  }
  const response = await submitJob(payload);
  addHistory(response.job_id, state.selected, "accepted");
  if (state.selected === "snapshot") {
    refreshSnapshotFormIfVisible(response.job_id);
  }
  subscribeToJob(response.job_id, "/api/events");
}

function runtimePayload() {
  return {
    resource: valueOrNull("resource"),
    backend: null,
    timeout_ms: 5000,
    safety_config: null,
    simulate: false,
    dry_run: false,
    confirm: document.getElementById("confirm").checked
  };
}

function parameterPayload() {
  if (state.selected === "ramp-list") return { document: rampListDocument() };
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
  return payload;
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
    clear: "Clear Status / Errors"
  };
  if (overrides[name]) return overrides[name];
  const spaced = name.replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
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
  ["accepted", "started", "progress", "finished", "failed", "cancelled", "error"].forEach((type) => {
    state.events.addEventListener(type, (event) => handleJobEvent(jobId, JSON.parse(event.data)));
  });
}

async function handleJobEvent(jobId, event) {
  updateHistory(jobId, event.type);
  if (jobCommand(jobId) === "snapshot" && (event.type === "accepted" || event.type === "started" || event.type === "progress")) {
    refreshSnapshotFormIfVisible(jobId);
  }
  if (event.type === "finished" || event.type === "failed" || event.type === "cancelled") {
    const job = await renderJobDetail(jobId, event);
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
    }
    if (jobCommand(jobId) === "snapshot") {
      refreshSnapshotFormIfVisible(jobId);
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
    && runtime.dry_run === false
    && !state.liveEvents;
}

function renderResult(data) {
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
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
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
}

function resourceLabel(resource, name) {
  if (!resource || typeof resource === "string") return name;
  const model = resource.idn?.model;
  const manufacturer = resource.idn?.manufacturer;
  return [name, manufacturer, model].filter(Boolean).join(" - ");
}

function syncSelectedResource() {
  const value = document.getElementById("resource-select").value;
  if (value) document.getElementById("resource").value = value;
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
}

function updateResourceModels(resources) {
  if (!Array.isArray(resources)) return;
  resources.forEach((resource) => {
    if (!resource || typeof resource === "string") return;
    const name = resource.name;
    if (!name) return;
    updateResourceModel(name, resource.idn?.model);
  });
}

function updateResourceModelFromJob(job) {
  const result = job?.result || {};
  const resultResource = result.resource;
  const resourceName = resultResource?.name || (typeof resultResource === "string" ? resultResource : job?.runtime?.resource);
  const model = resultResource?.idn?.model || result.idn?.model || result.model || result.driver?.model;
  if (updateResourceModel(resourceName, model)) {
    if (state.selected) selectCommand(state.selected);
    else renderCommands();
  }
}

function updateResourceModel(resource, model) {
  if (!resource || typeof model !== "string" || !model.trim()) return false;
  const next = supportedModelKey(model);
  if (state.resourceModels[resource] === next) return false;
  state.resourceModels[resource] = next;
  return true;
}

function commandMeta(name) {
  const meta = state.commands[name] || {};
  const support = selectedCommandSupport(name);
  if (!support || support.real !== false) return meta;
  return {
    ...meta,
    disabled: true,
    disabled_reason: meta.disabled_reason || commandDisabledReason(support, currentResourceModel())
  };
}

function selectedCommandSupport(name) {
  const model = currentResourceModel();
  if (!model) return null;
  return state.commandSupportByModel?.[model]?.[name] || null;
}

function currentResourceModel() {
  const resource = valueOrNull("resource");
  if (!resource) return null;
  return state.resourceModels[resource] || null;
}

function supportedModelKey(model) {
  const normalized = String(model || "").trim().toUpperCase();
  if (state.commandSupportByModel[normalized]) return normalized;
  return "GENERIC";
}

function commandDisabledReason(support, model) {
  const validation = support?.hardware_validation;
  if (validation === "planning_only") return `Planning only on ${model}`;
  if (validation === "not_supported_by_model") return `Not supported on ${model}`;
  return `Unavailable on ${model}`;
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
  const payload = { runtime: runtimePayload(), parameters: { interval_ms: 15000 } };
  if (!payload.runtime.resource) {
    renderLivePanel({ status: "error", stale: true, message: "Select or enter a hardware resource before starting Live Data." });
    return;
  }
  try {
    stopLivePreviewSnapshot();
    const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) });
    state.liveJobId = response.job_id;
    document.getElementById("live-start").disabled = true;
    document.getElementById("live-stop").disabled = false;
    closeEventSource("liveEvents");
    state.liveEvents = new EventSource(response.events_url);
    state.liveEvents.addEventListener("progress", (event) => renderLivePanel(JSON.parse(event.data).data));
    state.liveEvents.addEventListener("finished", () => {
      document.getElementById("live-start").disabled = false;
      document.getElementById("live-stop").disabled = true;
      setLiveState("Not monitoring");
      closeEventSource("liveEvents");
    });
    state.liveEvents.addEventListener("failed", (event) => {
      renderLivePanel({ status: "error", stale: true, message: JSON.parse(event.data).data?.error });
      document.getElementById("live-start").disabled = false;
      document.getElementById("live-stop").disabled = true;
      closeEventSource("liveEvents");
    });
  } catch (error) {
    renderLivePanel({ status: "error", stale: true, message: error.message || String(error) });
    document.getElementById("live-start").disabled = false;
    document.getElementById("live-stop").disabled = true;
  }
}

async function stopLive() {
  if (!state.liveJobId) return;
  await fetchJson(`/api/live/${state.liveJobId}/stop`, { method: "POST" });
  closeEventSource("liveEvents");
  document.getElementById("live-start").disabled = false;
  document.getElementById("live-stop").disabled = true;
  setLiveState("Not monitoring");
}

async function startLivePreviewSnapshot(healthState, resource = null) {
  if (state.liveEvents) return;
  stopLivePreviewSnapshot();
  setLiveState("Not monitoring");
  if (!healthState?.serverReady || !healthState?.deviceIdle) {
    renderBlankLivePanel("error", "Server or hardware is not ready.");
    return;
  }
  const payload = { runtime: runtimePayload(), parameters: { interval_ms: 1000 } };
  if (resource) payload.runtime.resource = resource;
  if (!payload.runtime.resource) {
    renderBlankLivePanel();
    return;
  }
  try {
    const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) });
    state.previewJobId = response.job_id;
    let handledFirstSample = false;
    state.previewEvents = new EventSource(response.events_url);
    state.previewEvents.addEventListener("progress", (event) => {
      if (handledFirstSample) return;
      handledFirstSample = true;
      renderLivePanel(JSON.parse(event.data).data);
      stopLivePreviewSnapshot();
    });
    state.previewEvents.addEventListener("failed", (event) => {
      const error = JSON.parse(event.data).data?.error || "Snapshot preview failed.";
      renderBlankLivePanel("error", error);
      setLiveState(liveStateText("error", Date.now() / 1000, error));
      stopLivePreviewSnapshot();
    });
  } catch (error) {
    const message = error.message || String(error);
    renderBlankLivePanel("error", message);
    setLiveState(liveStateText("error", Date.now() / 1000, message));
  }
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

function renderLivePanel(data) {
  const previous = state.livePanel;
  const resource = data.resource || previous?.resource || "";
  const sameResource = previous?.resource === resource;
  const next = {
    timestamp: data.timestamp || previous?.timestamp || Date.now() / 1000,
    resource,
    model: data.model || (sameResource ? previous?.model : null),
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
  const modelChanged = !next.stale && updateResourceModel(next.resource, next.model);

  setLiveState(liveStateText(next.status, next.timestamp, next.message, next.stale));

  next.channels.forEach((channel) => renderChannelCard(channel, next));
  if (modelChanged) renderCommands();
  if (state.selected) updateSelectedCommandState();
  drawTrend();
}

function setLiveState(text) {
  document.getElementById("live-state").textContent = text;
}

function liveStateText(status, timestamp, message = "", stale = false) {
  const lastUpdate = timestamp ? new Date(timestamp * 1000).toLocaleTimeString() : "never";
  return `${status}${stale ? " stale" : ""} - last update ${lastUpdate}${message ? ` - ${message}` : ""}`;
}

function renderBlankLivePanel(status = "ok", message = "") {
  const panel = {
    timestamp: Date.now() / 1000,
    resource: valueOrNull("resource") || "",
    model: null,
    stale: false,
    status,
    message,
    channels: blankLiveChannels()
  };
  state.livePanel = panel;
  panel.channels.forEach((channel) => renderChannelCard(channel, panel));
  drawTrend();
}

function blankLiveChannels() {
  return [1, 2, 3].map((channel) => ({
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
  return [1, 2, 3].map((channel) => byChannel.get(channel) || blankChannels[channel - 1]);
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
  const outputClass = channel.output_enabled === true ? "on" : channel.output_enabled === false ? "off" : "unknown";
  const outputText = channel.output_enabled === true ? "ON" : channel.output_enabled === false ? "OFF" : "--";
  const protectionClass = channel.protection_tripped === true ? "protection-tripped" : "";
  card.className = `live-card ${sample.stale ? "stale" : ""} ${sample.status === "error" ? "error" : ""} ${protectionClass}`;
  card.innerHTML = `
    <div class="live-card-head">
      <strong>CH${channel.channel}</strong>
      <div class="live-status-badges">
        ${protectionBadge("OVP", channel.over_voltage_tripped)}
        ${protectionBadge("OCP", channel.over_current_tripped)}
        <span class="status-badge ${outputClass}">${outputText}</span>
      </div>
    </div>
    <div class="live-measured">
      <div><span>${formatNum(channel.measured_voltage)}</span><small>OUT V</small></div>
      <div><span>${formatNum(channel.measured_current)}</span><small>OUT A</small></div>
    </div>
    <div class="live-setpoints">
      <div><span>${formatNum(channel.set_voltage)}</span><small>SET V</small></div>
      <div><span>${formatNum(channel.set_current)}</span><small>SET A</small></div>
    </div>
    <div class="protection-settings">
      <div><span>${formatProtectionVoltage(channel.over_voltage_protection_level)}</span><small>OVP</small></div>
      <div><span>${formatProtectionState(channel.over_current_protection_enabled)}</span><small>OCP</small></div>
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
  return `<span class="protection-badge ${stateClass}">${label} ${stateText}</span>`;
}

function openClearProtection(channel) {
  state.activeCategory = "discovery";
  selectCommand("clear-protection");
  const input = document.getElementById("param-channel");
  if (input) input.value = String(channel);
  updateSelectedCommandState();
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
  const meta = commandMeta(state.selected);
  let parameters = {};
  try {
    parameters = parameterPayload();
  } catch (e) {
    // Keep the form responsive while artifact editors contain invalid JSON.
  }
  const tripGuard = tripGuardReason(state.selected, parameters);
  const tripWarning = tripContextWarning(state.selected);
  const runButton = document.getElementById("run");
  const commandDescription = document.getElementById("command-description");
  const descriptionText = [meta.description, tripGuard || tripWarning].filter(Boolean).join(" ");
  commandDescription.textContent = descriptionText;
  commandDescription.title = descriptionText;
  runButton.disabled = Boolean(meta.disabled || tripGuard);
  if (state.selected === "restore-from-snapshot") {
    const restoreValid = isLoadedRestoreSnapshotValid();
    runButton.disabled ||= !restoreValid;
    const previewButton = document.getElementById("btn-preview-restore-plan");
    if (previewButton) previewButton.disabled = !restoreValid || state.restorePlanPreviewStatus === "running";
  }
  if (state.selected === "sequence") {
    try {
      sequenceDocumentFromEditor();
    } catch (e) {
      runButton.disabled = true;
    }
  }
  document.getElementById("confirm-banner").classList.toggle("visible", Boolean(meta.requires_confirm));
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
}

function updateHistory(jobId, status) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (job) {
    job.status = status;
    job.summary = statusSummary(status);
  }
  renderHistory();
}

function updateJobResult(jobId, status, summary) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (!job) return;
  job.status = status;
  job.summary = summary || statusSummary(status);
  renderHistory();
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
  if (status === "failed") return job?.error || event?.data?.error || "Command failed";
  if (status === "cancelled") return "Job cancelled";
  if (status !== "finished") return statusSummary(status);
  return successfulJobSummary(job);
}

function eventSummary(event) {
  if (event?.type === "failed") return event.data?.error || "Command failed";
  if (event?.type === "cancelled") return "Job cancelled";
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
  if (status === "cancelled") return "Job cancelled";
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
