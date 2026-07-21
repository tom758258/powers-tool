export function liveStateText(status, timestamp, message = "", stale = false) {
  const lastUpdate = timestamp ? new Date(timestamp * 1000).toLocaleTimeString() : "never";
  return `${status}${stale ? " stale" : ""} - last update ${lastUpdate}${message ? ` - ${message}` : ""}`;
}

export function liveStateClass(status, stale = false) {
  if (status === "error") return "state-error";
  if (stale || status === "busy") return "state-warning";
  return "state-ok";
}

export function blankLiveChannels(channels) {
  return channels.map((channel) => ({
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

export function mergeLiveChannels(channels, previousChannels, preservePreviousValues, defaultChannels) {
  const byChannel = new Map((Array.isArray(previousChannels) ? previousChannels : []).map((item) => [Number(item.channel), item]));
  const blanks = blankLiveChannels(defaultChannels);
  (Array.isArray(channels) ? channels : []).forEach((item) => {
    const existing = byChannel.get(Number(item.channel));
    byChannel.set(Number(item.channel), mergeLiveChannel(existing, item, preservePreviousValues));
  });
  return defaultChannels.map((channel, index) => byChannel.get(channel) || blanks[index]);
}

export function mergeLiveChannel(previous, incoming, preservePreviousValues) {
  if (!preservePreviousValues || !previous) return { ...previous, ...incoming };
  const next = { ...previous, ...incoming };
  [
    "output_enabled", "measured_voltage", "measured_current", "set_voltage", "set_current",
    "over_voltage_tripped", "over_current_tripped", "protection_tripped",
    "over_voltage_protection_level", "over_current_protection_enabled"
  ].forEach((key) => {
    if (incoming[key] === null || incoming[key] === undefined) next[key] = previous[key];
  });
  return next;
}

export function normalizeMeasurements(sample) {
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

export function renderChannelCard(channel, sample, helpers) {
  const card = document.querySelector(`[data-channel-card="${channel.channel}"]`);
  if (!card) return;
  const unsupported = helpers.channelUnsupportedReason(channel.channel);
  if (unsupported) {
    card.className = "live-card unsupported";
    card.setAttribute("aria-disabled", "true");
    card.title = unsupported;
    card.innerHTML = `<div class="live-card-head"><strong>CH${channel.channel}</strong><span class="status-badge status-indicator output-status unknown"><span class="indicator-dot" aria-hidden="true"></span><span class="indicator-text">Unsupported</span></span></div><div class="live-output-section"><div class="live-measured"><div><span>N/A</span><small>OUT V</small></div><div><span>N/A</span><small>OUT A</small></div></div></div><div class="live-control-section"><div class="live-setpoints"><div><span>N/A</span><small>SET V</small></div><div><span>N/A</span><small>SET A</small></div></div><div class="live-protection-section"><div class="live-protection-badges"><span class="protection-badge status-indicator unknown"><span class="indicator-dot" aria-hidden="true"></span><span class="indicator-text">Unsupported</span></span></div></div></div>`;
    return;
  }
  card.setAttribute("aria-disabled", "false");
  card.title = "";
  const outputClass = channel.output_enabled === true ? "on" : channel.output_enabled === false ? "off" : "unknown";
  const outputText = channel.output_enabled === true ? "ON" : channel.output_enabled === false ? "OFF" : "--";
  const protectionClass = channel.protection_tripped === true ? "protection-tripped" : "";
  card.className = `live-card ${sample.stale ? "stale" : ""} ${sample.status === "error" ? "error" : ""} ${protectionClass}`;
  card.innerHTML = `<div class="live-card-head"><strong>CH${channel.channel}</strong><span class="status-badge status-indicator output-status ${outputClass}"><span class="indicator-dot" aria-hidden="true"></span><span class="indicator-text">OUT ${outputText}</span></span></div><div class="live-output-section"><div class="live-measured"><div><span>${helpers.formatNum(channel.measured_voltage)}</span><small>OUT V</small></div><div><span>${helpers.formatNum(channel.measured_current)}</span><small>OUT A</small></div></div></div><div class="live-control-section"><div class="live-setpoints"><div><span>${helpers.formatNum(channel.set_voltage)}</span><small>SET V</small></div><div><span>${helpers.formatNum(channel.set_current)}</span><small>SET A</small></div></div><div class="live-protection-section"><div class="live-protection-badges">${protectionBadge("OVP", channel.over_voltage_tripped)}${protectionBadge("OCP", channel.over_current_tripped)}</div><div class="protection-settings"><div><span>${helpers.formatProtectionVoltage(channel.over_voltage_protection_level)}</span><small>OVP</small></div><div><span>${helpers.formatProtectionState(channel.over_current_protection_enabled)}</span><small>OCP</small></div></div></div></div>${channel.protection_tripped === true && !sample.stale ? `<button type="button" class="clear-protection-shortcut" data-clear-protection-channel="${channel.channel}">Clear Protection</button>` : ""}`;
  const shortcut = card.querySelector("[data-clear-protection-channel]");
  if (shortcut) shortcut.addEventListener("click", () => helpers.openClearProtection(channel.channel));
}

export function protectionBadge(label, tripped) {
  const stateClass = tripped === true ? "trip" : tripped === false ? "ok" : "unknown";
  const stateText = tripped === true ? "TRIP" : tripped === false ? "CLEAR" : "--";
  return `<span class="protection-badge status-indicator ${stateClass}"><span class="indicator-dot" aria-hidden="true"></span><span class="indicator-text">${label} ${stateText}</span></span>`;
}

export function createLiveDataController({ state, isNoHardwareMode, renderBlankLivePanel, runtimePayload, fetchJson, updateLiveMonitorButton, closeEventSource, renderLivePanel, setLiveState, liveStateText, stopLivePreviewSnapshot }) {
  async function startLive() {
    if (isNoHardwareMode()) { renderBlankLivePanel("error", "Live Data is available only in Real hardware mode."); return; }
    const payload = { runtime: runtimePayload(), parameters: { interval_ms: 5000 } };
    if (!payload.runtime.resource) { renderLivePanel({ status: "error", stale: true, message: "Select or enter a hardware resource before starting Live Data." }); return; }
    try {
      stopLivePreviewSnapshot(); updateLiveMonitorButton(false, true);
      const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) });
      state.liveJobId = response.job_id; updateLiveMonitorButton(true, false); closeEventSource("liveEvents");
      state.liveEvents = new EventSource(response.events_url);
      state.liveEvents.addEventListener("progress", (event) => renderLivePanel(JSON.parse(event.data).data));
      state.liveEvents.addEventListener("finished", () => { state.liveJobId = null; updateLiveMonitorButton(false, false); setLiveState("Not monitoring", "state-idle", "Live Data monitor is stopped."); closeEventSource("liveEvents"); });
      state.liveEvents.addEventListener("failed", (event) => { const message = JSON.parse(event.data).data?.error || "Live Data monitor failed."; renderLivePanel({ status: "error", stale: true, message }); state.liveJobId = null; updateLiveMonitorButton(false, false); closeEventSource("liveEvents"); });
    } catch (error) { renderLivePanel({ status: "error", stale: true, message: error.message || String(error) }); state.liveJobId = null; updateLiveMonitorButton(false, false); }
  }
  async function toggleLiveMonitor() { if (state.liveJobId || state.liveEvents) await stopLive(); else await startLive(); }
  async function stopLive() {
    if (!state.liveJobId) return; updateLiveMonitorButton(true, true);
    try { const jobId = state.liveJobId; await fetchJson(`/api/live/${jobId}/stop`, { method: "POST" }); closeEventSource("liveEvents"); await waitForLiveTerminal(jobId); state.liveJobId = null; updateLiveMonitorButton(false, false); setLiveState("Not monitoring", "state-idle", "Live Data monitor is stopped."); }
    catch (error) { renderLivePanel({ status: "error", stale: true, message: error.message || String(error) }); updateLiveMonitorButton(true, false); }
  }
  async function startLivePreviewSnapshot(healthState, resource = null) {
    if (isNoHardwareMode()) return; stopLivePreviewSnapshot(); setLiveState("Refreshing once...", "state-warning", "Refreshing Live Data once after command completion.");
    if (!healthState?.serverReady || !healthState?.deviceIdle) { renderBlankLivePanel("error", "Server or hardware is not ready."); setLiveState("Refresh blocked", "state-error", "Server or command path is not ready for a one-shot Live Data refresh."); return; }
    const payload = { runtime: runtimePayload(), parameters: { interval_ms: 1000 } }; if (resource) payload.runtime.resource = resource;
    if (!payload.runtime.resource) { renderBlankLivePanel(); setLiveState("Not monitoring", "state-idle", "No hardware resource is selected."); return; }
    try {
      const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) }); state.previewJobId = response.job_id; let handledFreshSample = false; state.previewEvents = new EventSource(response.events_url);
      state.previewEvents.addEventListener("progress", (event) => { if (handledFreshSample) return; const sample = JSON.parse(event.data).data; renderLivePanel(sample); if (!isFreshLivePreviewSample(sample)) return; handledFreshSample = true; stopLivePreviewSnapshot(); });
      state.previewEvents.addEventListener("failed", (event) => { const error = JSON.parse(event.data).data?.error || "Snapshot preview failed."; renderBlankLivePanel("error", error); setLiveState(liveStateText("error", Date.now() / 1000, error), "state-error", error); stopLivePreviewSnapshot(); });
    } catch (error) { const message = error.message || String(error); renderBlankLivePanel("error", message); setLiveState(liveStateText("error", Date.now() / 1000, message), "state-error", message); }
  }
  function isFreshLivePreviewSample(sample) { return Boolean(sample && sample.stale === false && sample.status !== "busy" && sample.status !== "error" && Array.isArray(sample.channels)); }
  async function waitForLiveTerminal(jobId) { const deadline = Date.now() + 15000; while (Date.now() < deadline) { const job = await fetchJson(`/api/jobs/${jobId}`); if (["cancelled", "finished", "failed"].includes(job.status)) return job; await new Promise((resolve) => setTimeout(resolve, 100)); } throw new Error("Live Data stop timed out while waiting for the backend job to finish."); }
  return { startLive, toggleLiveMonitor, stopLive, startLivePreviewSnapshot, isFreshLivePreviewSample, waitForLiveTerminal };
}
