export function physicalModelDisplayName(physicalModels, modelId) {
  const canonicalModelId = String(modelId || "").trim();
  if (!canonicalModelId) return "Unknown model";
  const metadata = physicalModels.find((model) => model?.model_id === canonicalModelId);
  return metadata?.display_name || metadata?.model_name || canonicalModelId;
}

export function planningIdentitySummary({ executionMode, planningProfiles, physicalModels }, identity) {
  if (!identity) return executionMode === "simulate" ? "Planning model: not selected" : "Planning target: not selected";
  if (identity.startsWith("profile:")) {
    const profileId = identity.slice("profile:".length);
    const profile = planningProfiles?.[profileId];
    return `Planning profile: ${profile?.display_name || profile?.model_name || profileId}`;
  }
  return `Planning model: ${physicalModelDisplayName(physicalModels, identity)}`;
}

export function liveResourceSummary(resourceDisplayModels, resource, select) {
  if (!resource) return "not scanned";
  const detected = resourceDisplayModels[resource] || null;
  if (detected) return `live ${detected}`;
  const selectedLiveResource = Boolean(select.value.trim() && select.value.trim() === resource);
  if (selectedLiveResource) return "live selected";
  const firstOption = select.options[0]?.textContent?.trim() || "";
  return firstOption === "No live resources found" ? "no live resources" : "not scanned";
}

export function resourceLabel(resource, name) {
  if (!resource || typeof resource === "string") return name;
  return [name, resource.idn?.manufacturer, resource.idn?.model].filter(Boolean).join(" - ");
}


export function createDeviceResourceController({
  state,
  devicePresentation,
  executionContext,
  fetchJson,
  stateClassNames,
  e3646aModelId,
  clearStaleResourceLiveSupport,
  syncBasicFromLivePanel,
  selectCommand,
  renderCommands,
  valueOrNull,
  exactSupportContextSummary,
  currentExactLiveSupport,
  channelCapabilityForModel,
  currentResourceModel,
  refreshBasicInputConstraints,
  refreshElectricalRatingConstraints,
  renderWorkspaceSummary,
  updateSelectedCommandState,
  refreshDeviceResourceSummary,
  stopLiveJobsBeforeModeChange,
  closeEventSource,
  renderClientResult,
  renderBlankLivePanel
}) {
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
  return devicePresentation.planningIdentitySummary(state, identity);
}

function liveResourceSummary(resource, select) {
  return devicePresentation.liveResourceSummary(state.resourceDisplayModels, resource, select);
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
  return executionContext.isNoHardwareExecutionMode(state.executionMode);
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
  refreshDeviceResourceSummary();
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
    await stopLiveJobsBeforeModeChange();
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
  return devicePresentation.physicalModelDisplayName(state.physicalModels, modelId);
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
  refreshDeviceResourceSummary();
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


  return {
    setDeviceOptionsExpanded,
    setDeviceResourceExpanded,
    updateDeviceResourceSummary,
    buildDeviceResourceSummary,
    planningIdentitySummary,
    liveResourceSummary,
    expectedModelSummary,
    selectedExpectedModel,
    selectedPlanningIdentity,
    rememberCurrentExecutionIdentity,
    isNoHardwareMode,
    realAuthorizationContext,
    clearRealWriteAuthorization,
    hasRealWriteAuthorization,
    updateExecutionModeUi,
    populateIdentitySelector,
    handleExecutionModeChange,
    stopRealLiveJobsAndWait,
    selectedExpectedModelLabel,
    physicalModelDisplayName,
    detectedResourceDisplayModel,
    resourceModelDetectionRecorded,
    detectedCommandModelForResource,
    detectedChannelModelForResource,
    selectedCommandModel,
    selectedChannelModel,
    actualCurrentResourceModel,
    e3646aGlobalOutputCapability,
    basicOutputPresentation,
    selectedElectricalRatingModel,
    handleExpectedModelChanged,
    updateLiveMonitorButton,
    refreshHealth,
    setStateIndicator
  };
}
