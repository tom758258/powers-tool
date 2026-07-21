export function createCommandSupport({
  state,
  defaultChannels,
  isNoHardwareMode,
  selectedPlanningIdentity,
  physicalModelDisplayName,
  selectedCommandModel,
  valueOrNull,
  detectedCommandModelForResource,
  selectedChannelModel
}) {
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
  if (!capability || !capability.channels.length) return [...defaultChannels];
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


  return {
    currentExactLiveSupport,
    selectedModelLiveSupport,
    commandMeta,
    exactCommandSupportText,
    selectedCommandSupport,
    currentResourceModel,
    supportedModelKey,
    commandDisabledReason,
    exactSupportContextSummary,
    liveSupportSummary,
    transportScopeLabel,
    backendScopeLabel,
    supportedChannelsForCurrentModel,
    isChannelSupported,
    isNumericChannel,
    channelUnsupportedReason,
    channelCapabilityForCurrentModel,
    channelCapabilityForModel,
    currentChannelCapabilityModel,
    channelModelKey,
    channelAvailabilityGuardReason,
    selectedChannelsForCommand,
    outputControlTitle,
    outputAllControlTitle,
    outputControlScopeForCurrentModel,
    globalOutputHintText
  };
}
