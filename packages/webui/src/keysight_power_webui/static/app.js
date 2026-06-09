const state = {
  commands: {},
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
  measure: [{ name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" }],
  "measure-all": [],
  "read-status": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  readback: [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  set: baseOutputParams(),
  apply: [...applyOutputParams(), { name: "no_output", type: "checkbox", label: "Do not enable output" }],
  "output-on": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "output-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "safe-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  "output-state": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "cycle-output": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }, { name: "duration_ms", type: "number", label: "Duration ms", value: 100 }],
  ramp: [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "current", type: "number", label: "Current", value: 0.1 },
    { name: "start_voltage", type: "number", label: "Start voltage", value: 0 },
    { name: "stop_voltage", type: "number", label: "Stop voltage", value: 1 },
    { name: "step_voltage", type: "number", label: "Step voltage", value: 0.1 },
    { name: "delay_ms", type: "number", label: "Delay ms", value: 0 }
  ],
  "smoke-output": [...baseOutputParams(), { name: "duration_ms", type: "number", label: "Duration ms", value: 100 }],
  "protection-status": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  "protection-set": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "ovp_voltage", type: "number", label: "OVP voltage", value: 5 },
    { name: "ocp", type: "select", label: "OCP", options: ["", "on", "off"], value: "" }
  ],
  "clear-protection": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  identify: [],
  snapshot: [{ name: "max_errors", type: "number", label: "Max errors", value: 20 }],
  sequence: [{ name: "document", type: "textarea", label: "Sequence document", value: "{}" }]
};

function baseOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage", value: 1 },
    { name: "current", type: "number", label: "Current", value: 0.1 },
    { name: "settle_ms", type: "number", label: "Settle ms", value: 0 },
    { name: "verify_after_write", type: "checkbox", label: "Verify after write" }
  ];
}

function applyOutputParams() {
  const params = baseOutputParams();
  params[0] = { ...params[0], options: ["all", "1", "2", "3"], value: "1" };
  return params;
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
  renderCommands();
}

function renderCommands() {
  const filter = document.getElementById("command-filter").value.toLowerCase();
  const list = document.getElementById("command-list");
  list.innerHTML = "";

  const CATEGORIES = ["output", "trigger", "read-only", "artifact", "discovery"];
  const CATEGORY_LABELS = {
    "output": "Output",
    "trigger": "Trigger",
    "read-only": "Read-Only",
    "artifact": "Artifact",
    "discovery": "Discovery"
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
        const button = document.createElement("button");
        button.className = `command-button${state.selected === name ? " active" : ""}`;
        button.disabled = Boolean(meta.disabled);
        button.innerHTML = `<span>${name === "capabilities" ? "Capabilities" : name}</span><small>${meta.disabled_reason || ""}</small>`;
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
  const meta = state.commands[name] || {};
  document.getElementById("selected-command").textContent = name === "capabilities" ? "Capabilities" : name;
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
  const payload = {
    command: state.selected,
    runtime: runtimePayload(),
    parameters: parameterPayload()
  };
  const meta = state.commands[state.selected] || {};
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
    if (param.type === "checkbox") payload[param.name] = input.checked;
    else if (param.type === "number") payload[param.name] = input.value === "" ? null : Number(input.value);
    else if (param.type === "textarea") payload[param.name] = parseMaybeJson(input.value);
    else if (input.value !== "") payload[param.name] = param.name === "channel" ? normalizeChannelValue(input.value) : input.value;
  });
  return payload;
}

function normalizeChannelValue(value) {
  if (value === "all") return value;
  return /^[1-9]\d*$/.test(value) ? Number(value) : value;
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
      setMonitorState("Not monitoring");
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
  setMonitorState("Not monitoring");
}

async function startLivePreviewSnapshot(healthState, resource = null) {
  if (state.liveEvents) return;
  stopLivePreviewSnapshot();
  setMonitorState("Not monitoring");
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
      setMonitorState("Not monitoring");
      stopLivePreviewSnapshot();
    });
    state.previewEvents.addEventListener("failed", (event) => {
      const error = JSON.parse(event.data).data?.error || "Snapshot preview failed.";
      renderBlankLivePanel("error", error);
      setMonitorState("Not monitoring");
      stopLivePreviewSnapshot();
    });
  } catch (error) {
    renderBlankLivePanel("error", error.message || String(error));
    setMonitorState("Not monitoring");
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

  const lastUpdate = next.timestamp ? new Date(next.timestamp * 1000).toLocaleTimeString() : "never";
  setMonitorState(`${next.status}${next.stale ? " stale" : ""} - last update ${lastUpdate}${next.message ? ` - ${next.message}` : ""}`);

  next.channels.forEach((channel) => renderChannelCard(channel, next));
  drawTrend();
}

function setMonitorState(text) {
  document.getElementById("monitor-state").textContent = text;
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
    set_current: null
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
  ["output_enabled", "measured_voltage", "measured_current", "set_voltage", "set_current"].forEach((key) => {
    if (incoming[key] === null || incoming[key] === undefined) next[key] = previous[key];
  });
  return next;
}

function renderChannelCard(channel, sample) {
  const card = document.querySelector(`[data-channel-card="${channel.channel}"]`);
  if (!card) return;
  const outputClass = channel.output_enabled === true ? "on" : channel.output_enabled === false ? "off" : "unknown";
  const outputText = channel.output_enabled === true ? "ON" : channel.output_enabled === false ? "OFF" : "--";
  card.className = `live-card ${sample.stale ? "stale" : ""} ${sample.status === "error" ? "error" : ""}`;
  card.innerHTML = `
    <div class="live-card-head">
      <strong>CH${channel.channel}</strong>
      <span class="status-badge ${outputClass}">${outputText}</span>
    </div>
    <div class="live-measured">
      <div><span>${formatNum(channel.measured_voltage)}</span><small>OUT V</small></div>
      <div><span>${formatNum(channel.measured_current)}</span><small>OUT A</small></div>
    </div>
    <div class="live-setpoints">
      <div><span>${formatNum(channel.set_voltage)}</span><small>SET V</small></div>
      <div><span>${formatNum(channel.set_current)}</span><small>SET A</small></div>
    </div>
  `;
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
  const displayLabel = label === "capabilities" ? "Capabilities" : label;
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
