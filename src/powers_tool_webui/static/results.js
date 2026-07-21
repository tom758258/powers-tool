export function jobSummary(job, event = null) {
  const status = job?.status || event?.type;
  if (status === "failed" && (job?.error_code || event?.data?.code) === "cleanup_failed") return "Failed  cleanup_failed";
  if (status === "failed") return job?.error || event?.data?.error || "Command failed";
  if (status === "cancelled") return "Cancelled";
  if (status !== "finished") return statusSummary(status);
  return successfulJobSummary(job);
}

export function eventSummary(event) {
  if (event?.type === "cancel_requested") return "Waiting for safe-off and cleanup";
  if (event?.type === "failed" && event.data?.code === "cleanup_failed") return "Failed  cleanup_failed";
  if (event?.type === "failed") return event.data?.error || "Command failed";
  if (event?.type === "cancelled") return "Cancelled";
  return statusSummary(event?.type);
}

export function successfulJobSummary(job) {
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

export function capabilitiesSummary(result) {
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

export function identifySummary(result) {
  const idn = result.idn || result.resource?.idn || {};
  const parts = compactParts([
    idn.model,
    idn.serial ? `serial ${idn.serial}` : "",
    idn.firmware ? `firmware ${idn.firmware}` : ""
  ]);
  return parts.length ? parts.join(" - ") : "Identification read";
}

export function verifySummary(result) {
  const resource = result.resource || {};
  const model = resource.idn?.model;
  if (model && resource.name) return `Reachable ${model} at ${resource.name}`;
  if (model) return `Reachable ${model}`;
  if (resource.name) return `Reachable resource ${resource.name}`;
  return "Resource reachable";
}

export function readStatusSummary(result) {
  const outputText = outputStatesSummary(result.outputs);
  return compactParts([outputText, errorQueueSummary(result, "")]).join(" - ") || "Status read";
}

export function readbackSummary(result) {
  const channels = Array.isArray(result.channels) ? result.channels : [];
  const count = channels.length;
  return compactParts([
    `${count} channel${count === 1 ? "" : "s"}`,
    setpointSummary(channels)
  ]).join(" - ");
}

export function snapshotSummary(result) {
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

export function safetyInspectSummary(result) {
  return result.safety_config_loaded ? "Safety config loaded" : "Safety config not loaded";
}

export function outputStatesSummary(outputs) {
  if (!Array.isArray(outputs) || outputs.length === 0) return "";
  return outputs
    .map((item) => `CH${item.channel} ${item.enabled === true ? "ON" : item.enabled === false ? "OFF" : "--"}`)
    .join(", ");
}

export function setpointSummary(channels) {
  if (!Array.isArray(channels) || channels.length === 0) return "";
  return channels
    .slice(0, 3)
    .map((item) => {
      const setpoints = item.setpoints || {};
      return `CH${item.channel} ${formatSetpointValue(setpoints.voltage)}V/${formatSetpointValue(setpoints.current)}A`;
    })
    .join(", ");
}

export function formatSetpointValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  return String(value);
}

export function errorQueueSummary(result, noun = "instrument") {
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const label = noun ? `${noun} ` : "";
  if (errors.length === 0) return `No ${label}errors`;
  return `${errors.length} ${label}error${errors.length === 1 ? "" : "s"}`;
}

export function compactParts(parts) {
  return parts.filter((part) => part !== null && part !== undefined && part !== "");
}

export function statusSummary(status) {
  if (status === "accepted") return "Accepted";
  if (status === "started") return "Started";
  if (status === "progress" || status === "running") return "Running";
  if (status === "cancel_requested") return "Waiting for safe-off and cleanup";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed" || status === "error") return "Command failed";
  if (status === "finished") return "Command completed successfully";
  return status || "Pending";
}

export function statusLabel(status) {
  if (status === "finished") return "Success";
  if (status === "failed" || status === "error") return "Failed";
  if (status === "cancelled") return "Cancelled";
  if (status === "progress" || status === "running") return "Running";
  if (status === "started") return "Started";
  if (status === "accepted") return "Accepted";
  return status || "Pending";
}

export function statusClass(status) {
  if (status === "finished") return "success";
  if (status === "failed" || status === "error") return "failed";
  if (status === "cancelled") return "cancelled";
  return "running";
}
export function renderWorkspaceEmpty(container, message) {
  const empty = document.createElement("p");
  empty.className = "workspace-summary-empty";
  empty.textContent = message;
  container.appendChild(empty);
}

export function renderWorkspaceJob(container, job, context, helpers) {
  if (job.command === "capabilities") {
    renderCapabilitiesWorkspaceSummary(container, job.result, helpers);
    return;
  }
  if (job.command === "identify") {
    renderIdentifyWorkspaceSummary(container, job.result);
    return;
  }
  if (job.command === "trigger-status") {
    renderTriggerStatusWorkspaceSummary(container, job.result, helpers.formatNum);
    return;
  }
  if (job.command === "trigger-list") {
    const trigger = job.result.trigger || {};
    appendWorkspaceFields(container, [
      ["Command", helpers.commandDisplayName(job.command)],
      ["Channel", trigger.channel ?? "--"],
      ["Steps", job.result.steps ?? "--"],
      ["Completed", trigger.completed === true ? "Yes" : "No"],
      ["Previous LIST restored", trigger.restored === true ? "Yes" : trigger.restored === false ? "No" : "--"]
    ]);
    return;
  }
  appendWorkspaceFields(container, [
    ["Command", helpers.commandDisplayName(job.command)],
    ["Execution mode", context.executionMode],
    ["Resource", context.executionMode === "real" ? context.resource || "No resource selected" : "Not used"],
    ["Summary", helpers.successfulJobSummary(job)]
  ]);
}

export function renderCapabilitiesWorkspaceSummary(container, result, helpers) {
  const resource = result.resource || {};
  const model = resource.idn?.model || result.driver?.model;
  if (resource.name || model) {
    const support = result.command_support || {};
    const liveSupport = result.live_support || {};
    appendWorkspaceFields(container, [
      ["Model", model || "--"],
      ["Resource", resource.name || "--"],
      ["Transport", helpers.transportScopeLabel(liveSupport.transport_scope)],
      ["Backend", helpers.backendScopeLabel(liveSupport.backend_scope)],
      ["Product live support", helpers.liveSupportSummary(liveSupport)],
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

export function renderIdentifyWorkspaceSummary(container, result) {
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

export function renderTriggerStatusWorkspaceSummary(container, result, formatNum) {
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

export function appendWorkspaceFields(container, fields) {
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

export function channelList(channels) {
  return Array.isArray(channels) && channels.length ? channels.map((channel) => `CH${channel}`).join(", ") : "--";
}

export function featureAvailability(support, commands) {
  return commands.some((command) => support[command]?.real === true) ? "Available" : "Unavailable";
}
