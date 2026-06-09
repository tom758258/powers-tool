const state = {
  commands: {},
  commandSupportByModel: {},
  resourceModels: {},
  selected: null,
  jobs: [],
  events: null,
  liveEvents: null,
  liveJobId: null,
  previewEvents: null,
  previewJobId: null,
  samples: [],
  livePanel: null,
  resultCollapsed: false
};

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
  "cycle-output": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }, { name: "duration_ms", type: "number", label: "Duration ms", value: 100 }],
  ramp: [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "current", type: "number", label: "Current", value: 0.1 },
    { name: "start_voltage", type: "number", label: "Start voltage", value: 0 },
    { name: "stop_voltage", type: "number", label: "Stop voltage", value: 1 },
    { name: "step_voltage", type: "number", label: "Step voltage", value: 0.1 },
    { name: "delay_ms", type: "number", label: "Delay ms", value: 0 }
  ],
  "smoke-output": smokeOutputParams(),
  "protection-set": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "ovp_voltage", type: "number", label: "OVP voltage", value: 5 },
    { name: "ocp", type: "select", label: "OCP", options: ["", "on", "off"], value: "" }
  ],
  "clear-protection": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
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
  snapshot: [{ name: "max_errors", type: "number", label: "Max errors", value: 20 }],
  sequence: [{ name: "document", type: "textarea", label: "Sequence document", value: "{}" }]
};

function baseOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage", value: 1 },
    { name: "current", type: "number", label: "Current", value: 0.1 }
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
    { name: "voltage", type: "number", label: "Voltage", value: 1 },
    { name: "current", type: "number", label: "Current", value: 0.1 },
    { name: "duration_ms", type: "number", label: "Duration ms", value: 100 }
  ];
}

function triggerStepParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Triggered V", optional: true },
    { name: "current", type: "number", label: "Triggered A", optional: true },
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
    { name: "voltage_list", type: "text", label: "Voltage list", value: "0,1", parser: "numberList" },
    { name: "current_list", type: "text", label: "Current list", value: "0.05", parser: "numberList" },
    { name: "dwell_list", type: "text", label: "Dwell list", value: "0.01", parser: "numberList" },
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
    { name: "poll_ms", type: "number", label: "Poll ms", value: 200 },
    { name: "wait_timeout_ms", type: "number", label: "Timeout ms", optional: true }
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
  const list = document.getElementById("command-list");
  list.innerHTML = "";

  const CATEGORIES = ["output", "trigger", "artifact", "discovery"];
  const CATEGORY_LABELS = {
    "output": "Output",
    "trigger": "Trigger",
    "artifact": "Workflows & State",
    "discovery": "Advanced Diagnostics"
  };

  const columns = {};
  CATEGORIES.forEach((cat) => {
    const colDiv = document.createElement("div");
    colDiv.className = "command-category-column";

    const header = document.createElement("div");
    header.className = "category-title";
    header.textContent = CATEGORY_LABELS[cat];
    colDiv.appendChild(header);

    const buttonsDiv = document.createElement("div");
    buttonsDiv.className = "category-buttons";
    colDiv.appendChild(buttonsDiv);

    list.appendChild(colDiv);
    columns[cat] = {
      column: colDiv,
      buttonsContainer: buttonsDiv,
      hasVisibleCommands: false
    };
  });

  Object.entries(state.commands)
    .filter(([name]) => !filter || name.includes(filter))
    .sort((a, b) => a[0].localeCompare(b[0]))
    .forEach(([name, meta]) => {
      const cat = meta.category || "discovery";
      if (columns[cat]) {
        const effectiveMeta = commandMeta(name);
        const button = document.createElement("button");
        button.className = `command-button${state.selected === name ? " active" : ""}`;
        button.disabled = Boolean(effectiveMeta.disabled);
        button.innerHTML = `<span>${commandDisplayName(name)}</span><small>${effectiveMeta.disabled_reason || ""}</small>`;
        button.addEventListener("click", () => selectCommand(name));
        columns[cat].buttonsContainer.appendChild(button);
        columns[cat].hasVisibleCommands = true;
      }
    });

  CATEGORIES.forEach((cat) => {
    if (filter && !columns[cat].hasVisibleCommands) {
      columns[cat].column.style.display = "none";
    } else {
      columns[cat].column.style.display = "flex";
    }
  });
}

function selectCommand(name) {
  state.selected = name;
  const meta = commandMeta(name);
  document.getElementById("selected-command").textContent = commandDisplayName(name);
  document.getElementById("command-description").textContent = meta.description || "";
  document.getElementById("run").disabled = Boolean(meta.disabled);
  document.getElementById("confirm-banner").classList.toggle("visible", Boolean(meta.requires_confirm));
  renderForm(name);
  renderCommands();
}

function renderForm(command) {
  const form = document.getElementById("command-form");
  form.innerHTML = "";
  (PARAMS[command] || []).forEach((param) => {
    const label = document.createElement("label");
    label.textContent = param.label;
    let input;
    if (param.type === "select") {
      input = document.createElement("select");
      param.options.forEach((option) => {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = option || "none";
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
    label.appendChild(input);
    form.appendChild(label);
  });
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
    document.getElementById("result").textContent = JSON.stringify({
      error: "Scan resources failed",
      detail: error.message || String(error)
    }, null, 2);
  }
}

async function runSelected() {
  if (!state.selected) return;
  const meta = commandMeta(state.selected);
  if (meta.disabled) {
    renderResult({
      error: "Command unavailable",
      detail: meta.disabled_reason || "This command is not available for the selected resource.",
      command: state.selected
    });
    return;
  }
  const payload = {
    command: state.selected,
    runtime: runtimePayload(),
    parameters: parameterPayload()
  };
  if (meta.requires_confirm && !payload.runtime.confirm) {
    renderResult({
      error: "Confirmation required",
      detail: "This command affects real hardware output. Check confirmation before running.",
      command: state.selected,
      runtime: { confirm: false }
    });
    return;
  }
  const response = await submitJob(payload);
  addHistory(response.job_id, state.selected, "accepted");
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
  const payload = {};
  (PARAMS[state.selected] || []).forEach((param) => {
    const input = document.getElementById(`param-${param.name}`);
    if (!input) return;
    const parsed = parameterValue(param, input);
    if (parsed !== undefined) payload[param.name] = parsed;
  });
  return payload;
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
  if (name === "capabilities") return "Capabilities";
  return name.charAt(0).toUpperCase() + name.slice(1);
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
    if (event.type === "finished") updateResourceModelFromJob(job);
    closeEventSource("events");
    if (!healthState) refreshHealth();
  }
}

async function renderJobDetail(jobId, event) {
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
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

function jobCommand(jobId) {
  return state.jobs.find((item) => item.jobId === jobId)?.command || null;
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
    state.resourceModels[name] = supportedModelKey(resource.idn?.model);
  });
}

function updateResourceModelFromJob(job) {
  const resource = job?.result?.resource;
  if (resource?.name) {
    state.resourceModels[resource.name] = supportedModelKey(resource.idn?.model);
    if (state.selected) selectCommand(state.selected);
    else renderCommands();
  }
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
  const normalized = String(model || "").toUpperCase();
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
  const panel = document.getElementById("result-panel");
  const button = document.getElementById("result-toggle");
  panel.classList.toggle("collapsed", state.resultCollapsed);
  button.textContent = state.resultCollapsed ? "+" : "-";
  button.setAttribute("aria-label", state.resultCollapsed ? "Expand result" : "Collapse result");
  button.setAttribute("aria-expanded", String(!state.resultCollapsed));
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
  const next = {
    timestamp: data.timestamp || previous?.timestamp || Date.now() / 1000,
    resource: data.resource || previous?.resource || "",
    stale: Boolean(data.stale),
    status: data.status || "ok",
    message: data.message || data.error || "",
    channels: mergeLiveChannels(data.channels, previous?.channels, Boolean(data.stale))
  };
  state.livePanel = next;
  state.samples.push({ timestamp: next.timestamp, data: next });
  state.samples = state.samples.slice(-60);

  setLiveState(liveStateText(next.status, next.timestamp, next.message, next.stale));

  next.channels.forEach((channel) => renderChannelCard(channel, next));
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
  `;
}

function protectionBadge(label, tripped) {
  const stateClass = tripped === true ? "trip" : tripped === false ? "ok" : "unknown";
  const stateText = tripped === true ? "TRIP" : tripped === false ? "OK" : "--";
  return `<span class="protection-badge ${stateClass}">${label} ${stateText}</span>`;
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
  state.jobs.unshift({ jobId, command, label: displayLabel, status });
  state.jobs = state.jobs.slice(0, 20);
  renderHistory();
}

function updateHistory(jobId, status) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (job) job.status = status;
  renderHistory();
}

function renderHistory() {
  const history = document.getElementById("job-history");
  history.innerHTML = "";
  state.jobs.forEach((job) => {
    const item = document.createElement("div");
    item.className = "history-item";
    item.textContent = `${job.label} - ${job.status}`;
    history.appendChild(item);
  });
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
