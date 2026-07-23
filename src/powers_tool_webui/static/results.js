import { t } from "./i18n.js";

export function jobSummary(job, event = null) {
  const status = job?.status || event?.type;
  if (status === "failed") {
    const error = job?.error || event?.data?.error;
    const errorCode = job?.error_code || event?.data?.code;
    if (errorCode === "cleanup_failed") return t("job.summary.cleanup_failed");
    if (error) return error;
    if (errorCode) return t("job.summary.failed_detail", { detail: errorCode });
    return t("job.summary.failed");
  }
  if (status === "cancelled") return t("status.cancelled");
  if (status !== "finished") return statusSummary(status);
  return successfulJobSummary(job);
}

export function eventSummary(event) {
  if (event?.type === "cancel_requested") return t("job.summary.waiting_cleanup");
  if (event?.type === "failed") {
    if (event.data?.code === "cleanup_failed") return t("job.summary.cleanup_failed");
    if (event.data?.error) return event.data.error;
    if (event.data?.code) return t("job.summary.failed_detail", { detail: event.data.code });
    return t("job.summary.failed");
  }
  if (event?.type === "cancelled") return t("status.cancelled");
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
    return t(count === 1 ? "result.summary.resource_one" : "result.summary.resource_many", { count });
  }
  if (runtime.dry_run || result.dry_run || result.plan) return t("result.summary.plan_generated");
  const resource = result.resource || result;
  const model = resource?.idn?.model || result.driver?.model;
  if (resource?.name || model || result.command_support || result.driver) {
    return model ? t("result.summary.connected_model", { model }) : t("result.summary.connected_resource");
  }
  return t("job.summary.completed");
}

export function capabilitiesSummary(result) {
  const resource = result.resource;
  const model = resource?.idn?.model || result.driver?.model;
  const driver = result.driver?.class;
  if (resource?.name || model || driver) {
    return compactParts([
      model ? t("result.summary.connected_model", { model }) : t("result.summary.connected_resource"),
      driver
    ]).join(" - ");
  }
  if (result.models && typeof result.models === "object") {
    const count = Object.keys(result.models).length;
    return t(count === 1 ? "result.summary.model_one" : "result.summary.model_many", { count });
  }
  return t("job.summary.completed");
}

export function identifySummary(result) {
  const idn = result.idn || result.resource?.idn || {};
  const parts = compactParts([
    idn.model,
    idn.serial ? t("result.summary.serial", { serial: idn.serial }) : "",
    idn.firmware ? t("result.summary.firmware", { firmware: idn.firmware }) : ""
  ]);
  return parts.length ? parts.join(" - ") : t("result.summary.identification_read");
}

export function verifySummary(result) {
  const resource = result.resource || {};
  const model = resource.idn?.model;
  if (model && resource.name) return t("result.summary.reachable_model_resource", { model, resource: resource.name });
  if (model) return t("result.summary.reachable_model", { model });
  if (resource.name) return t("result.summary.reachable_resource", { resource: resource.name });
  return t("result.summary.resource_reachable");
}

export function readStatusSummary(result) {
  const outputText = outputStatesSummary(result.outputs);
  return compactParts([outputText, errorQueueSummary(result, "")]).join(" - ") || t("result.summary.status_read");
}

export function readbackSummary(result) {
  const channels = Array.isArray(result.channels) ? result.channels : [];
  const count = channels.length;
  return compactParts([
    t(count === 1 ? "result.summary.channel_one" : "result.summary.channel_many", { count }),
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
    t(channelCount === 1 ? "result.summary.channel_one" : "result.summary.channel_many", { count: channelCount }),
    outputCount ? t(outputCount === 1 ? "result.summary.output_one" : "result.summary.output_many", { count: outputCount }) : "",
    t(tripped ? "result.summary.protection_tripped" : "result.summary.protection_ok"),
    errorQueueSummary(result, "")
  ]).join(" - ");
}

export function safetyInspectSummary(result) {
  return t(result.safety_config_loaded ? "result.summary.safety_loaded" : "result.summary.safety_not_loaded");
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
  if (errors.length === 0) return t(noun ? "result.summary.no_instrument_errors" : "result.summary.no_errors");
  return t(
    noun
      ? errors.length === 1 ? "result.summary.instrument_error_one" : "result.summary.instrument_error_many"
      : errors.length === 1 ? "result.summary.error_one" : "result.summary.error_many",
    { count: errors.length }
  );
}

export function compactParts(parts) {
  return parts.filter((part) => part !== null && part !== undefined && part !== "");
}

export function statusSummary(status) {
  const known = status === "progress" ? "running" : status === "error" ? "failed" : status;
  if (["accepted", "started", "running", "cancel_requested", "cancelled", "failed", "finished"].includes(known)) {
    return t(`job.summary.${known}`);
  }
  return status || t("status.pending");
}

export function statusLabel(status) {
  const known = status === "finished" ? "success" : status === "error" ? "failed" : status === "progress" ? "running" : status;
  if (["success", "failed", "cancel_requested", "cancelled", "running", "started", "accepted"].includes(known)) {
    return t(`status.${known}`);
  }
  return status || t("status.pending");
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
      ["workspace.field.command", helpers.commandDisplayName(job.command)],
      ["workspace.field.channel", trigger.channel ?? "--"],
      ["workspace.field.steps", job.result.steps ?? "--"],
      ["workspace.field.completed", booleanDisplay(trigger.completed)],
      ["workspace.field.previous_list_restored", booleanDisplay(trigger.restored)]
    ]);
    return;
  }
  appendWorkspaceFields(container, [
    ["workspace.field.command", helpers.commandDisplayName(job.command)],
    ["workspace.field.execution_mode", context.executionMode],
    ["workspace.field.resource", context.executionMode === "real" ? context.resource || t("workspace.value.no_resource") : t("workspace.value.not_used")],
    ["workspace.field.summary", helpers.successfulJobSummary(job)]
  ]);
}

export function renderCapabilitiesWorkspaceSummary(container, result, helpers) {
  const resource = result.resource || {};
  const model = resource.idn?.model || result.driver?.model;
  if (resource.name || model) {
    const support = result.command_support || {};
    const liveSupport = result.live_support || {};
    appendWorkspaceFields(container, [
      ["workspace.field.model", model || "--"],
      ["workspace.field.resource", resource.name || "--"],
      ["workspace.field.transport", helpers.transportScopeLabel(liveSupport.transport_scope)],
      ["workspace.field.backend", helpers.backendScopeLabel(liveSupport.backend_scope)],
      ["workspace.field.product_live_support", helpers.liveSupportSummary(liveSupport)],
      ["workspace.field.output_channels", channelList(result.channels)],
      ["workspace.field.measurement_channels", channelList(result.measure_channels?.real)],
      ["workspace.field.output", featureAvailability(support, ["set", "apply", "output-on", "output-off"])],
      ["workspace.field.protection", featureAvailability(support, ["protection-set", "clear-protection", "protection-status"])],
      ["workspace.field.trigger", featureAvailability(support, ["trigger-status", "trigger-step", "trigger-list", "trigger-fire"])]
    ]);
    return;
  }
  const models = result.models || {};
  const fields = Object.entries(models).map(([name, details]) => [
    name,
    t("workspace.value.model_channels", { count: Array.isArray(details.channels) ? details.channels.length : 0, channels: channelList(details.channels) })
  ]);
  appendWorkspaceFields(container, fields.length ? fields : [["workspace.field.supported_models", "--"]]);
}

export function renderIdentifyWorkspaceSummary(container, result) {
  const idn = result.idn || result.resource?.idn || {};
  const resource = typeof result.resource === "string" ? result.resource : result.resource?.name;
  appendWorkspaceFields(container, [
    ["workspace.field.manufacturer", idn.manufacturer || "--"],
    ["workspace.field.model", idn.model || "--"],
    ["workspace.field.serial_number", idn.serial || "--"],
    ["workspace.field.firmware", idn.firmware || "--"],
    ["workspace.field.installed_options", result.options || "--"],
    ["workspace.field.scpi_version", result.scpi_version || "--"],
    ["workspace.field.resource", resource || "--"]
  ]);
}

export function renderTriggerStatusWorkspaceSummary(container, result, formatNum) {
  const pins = Array.isArray(result.digital_pins) ? result.digital_pins : [];
  const channels = Array.isArray(result.channels) ? result.channels : [];
  const fields = [
    ["workspace.field.trigger_output_bus", enabledDisplay(result.trigger_output_bus_enabled)],
    ["workspace.field.rear_pins", pins.length ? pins.map((pin) => `P${pin.pin} ${pin.function}/${pin.polarity}`).join(", ") : "--"]
  ];
  channels.forEach((channel) => {
    const trigger = channel.trigger || {};
    const list = channel.list || {};
    const steps = Array.isArray(list.voltage) ? list.voltage.length : 0;
    fields.push(
      [t("workspace.field.channel_trigger", { channel: channel.channel }), `${trigger.source || "--"}; V ${trigger.voltage_mode || "--"}; I ${trigger.current_mode || "--"}`],
      [t("workspace.field.channel_triggered_level", { channel: channel.channel }), `${formatNum(trigger.triggered_voltage)} V / ${formatNum(trigger.triggered_current)} A`],
      [t("workspace.field.channel_list", { channel: channel.channel }), t("workspace.value.list_summary", { steps, count: list.count ?? "--", mode: list.step_mode || "--", terminate: onOffDisplay(list.terminate_last) })]
    );
  });
  appendWorkspaceFields(container, fields);
}

export function appendWorkspaceFields(container, fields) {
  fields.forEach(([labelText, valueText]) => {
    const field = document.createElement("div");
    field.className = "workspace-summary-field";
    const label = document.createElement("small");
    label.textContent = labelText.startsWith?.("workspace.") ? t(labelText) : labelText;
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
  return t(commands.some((command) => support[command]?.real === true) ? "status.available" : "status.unavailable");
}

function booleanDisplay(value) {
  return value === true ? t("common.yes") : value === false ? t("common.no") : "--";
}

function enabledDisplay(value) {
  return value === true ? t("status.enabled") : value === false ? t("status.disabled") : "--";
}

function onOffDisplay(value) {
  return value === true ? t("status.on") : value === false ? t("status.off") : "--";
}
