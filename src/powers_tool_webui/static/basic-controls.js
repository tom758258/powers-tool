export function createBasicControls({
  state,
  defaultChannels,
  e3646aCapabilityError,
  e3646aGlobalOutputDescription,
  valueOrNull,
  basicOutputPresentation,
  supportedChannelsForCurrentModel,
  channelUnsupportedReason,
  commandMeta,
  outputControlTitle,
  outputAllControlTitle,
  basicSetpointValues,
  refreshBasicInputConstraints,
  validateBasicInput,
  eventSummary
}) {
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
      defaultChannels.forEach((channel) => renderBasicChannelActionState(channel));
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
  defaultChannels.forEach((channel) => {
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
    button.title = e3646aCapabilityError;
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
    info.title = e3646aGlobalOutputDescription;
  }
}

function applyBasicAllOutputPresentation(button, presentation = basicOutputPresentation()) {
  if (presentation.mode === "e3646a-disabled") {
    button.disabled = true;
    button.title = e3646aCapabilityError;
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
    capabilityStatus.textContent = disabled ? e3646aCapabilityError : "";
  }
  defaultChannels.forEach((channel) => {
    const button = document.querySelector(`[data-basic-output="${channel}"]`);
    if (button) applyBasicPerChannelOutputPresentation(channel, button, presentation);
  });
}

function renderBasicOutputActionStates() {
  defaultChannels.forEach((channel) => renderBasicOutputControlState(channel));
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


  return {
    basicActionKey,
    basicActionDisplayName,
    basicLiveChannel,
    basicChannelOutputState,
    e3646aGlobalOutputState,
    basicAllOutputsOn,
    setBasicActionState,
    clearBasicActionState,
    renderBasicActionState,
    renderBasicChannelActionState,
    updateBasicActionFromJob,
    syncBasicFromLivePanel,
    syncBasicSetpointInput,
    clearBasicInputDirty,
    renderBasicOutputButton,
    renderBasicAllOutputButton,
    applyBasicPerChannelOutputPresentation,
    applyBasicAllOutputPresentation,
    applyBasicOutputPresentation,
    renderBasicOutputActionStates,
    renderBasicOutputControlState,
    basicOutputLockAction,
    clearResolvedBasicErrors,
    liveSetpointsMatchBasicInputs,
    nearlyEqual,
    basicStatusText,
    setBasicStatus
  };
}
