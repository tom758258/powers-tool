export function defaultTriggerListStep() {
  return { voltage: 0, current: 0.05, dwell: 0.01, bost: false, eost: false };
}

export function defaultTriggerListChannels() {
  return Object.fromEntries(["1", "2", "3"].map((channel) => [channel, {
    count: 1,
    steps: [defaultTriggerListStep()]
  }]));
}

export function defaultTriggerListControls() {
  return {
    source: "immediate",
    fire: false,
    wait_complete: true,
    trigger_output_pins: [],
    trigger_output_polarity: "positive",
    exclusive_pins: false,
    poll_ms: 200,
    wait_timeout_ms: null,
    leave_trigger_configured: false
  };
}

export function triggerListWorkspaceDocument(state) {
  return {
    kind: "powers-tool-trigger-list-workspace",
    version: 1,
    active_channel: state.triggerListActiveChannel,
    controls: {
      ...state.triggerListControls,
      trigger_output_pins: [...state.triggerListControls.trigger_output_pins]
    },
    channels: Object.fromEntries(["1", "2", "3"].map((channel) => [channel, {
      count: state.triggerListChannels[channel].count,
      steps: state.triggerListChannels[channel].steps.map((step) => ({ ...step }))
    }]))
  };
}

export function validateTriggerListWorkspace(document) {
  const exact = (object, fields, label) => {
    if (!object || typeof object !== "object" || Array.isArray(object) || Object.keys(object).some((field) => !fields.includes(field)) || fields.some((field) => !(field in object))) {
      throw new Error(`${label} contains unknown or missing fields.`);
    }
  };
  exact(document, ["kind", "version", "active_channel", "controls", "channels"], "Trigger List workspace");
  if (document.kind !== "powers-tool-trigger-list-workspace" || document.version !== 1 || ![1, 2, 3].includes(document.active_channel)) {
    throw new Error("Invalid Trigger List workspace kind, version, or active channel.");
  }
  const fields = ["source", "fire", "wait_complete", "trigger_output_pins", "trigger_output_polarity", "exclusive_pins", "poll_ms", "wait_timeout_ms", "leave_trigger_configured"];
  exact(document.controls, fields, "Trigger List controls");
  const controls = document.controls;
  if (!["immediate", "bus"].includes(controls.source)
    || typeof controls.fire !== "boolean" || typeof controls.wait_complete !== "boolean"
    || typeof controls.exclusive_pins !== "boolean" || typeof controls.leave_trigger_configured !== "boolean"
    || !Array.isArray(controls.trigger_output_pins)
    || controls.trigger_output_pins.some((pin) => ![1, 2, 3].includes(pin))
    || new Set(controls.trigger_output_pins).size !== controls.trigger_output_pins.length
    || !["positive", "negative"].includes(controls.trigger_output_polarity)
    || !Number.isInteger(controls.poll_ms) || controls.poll_ms < 50
    || !(controls.wait_timeout_ms === null || (Number.isInteger(controls.wait_timeout_ms) && controls.wait_timeout_ms > 0))) {
    throw new Error("Trigger List controls are invalid.");
  }
  exact(document.channels, ["1", "2", "3"], "Trigger List channels");
  const channels = {};
  ["1", "2", "3"].forEach((channel) => {
    const draft = document.channels[channel];
    exact(draft, ["count", "steps"], `Channel ${channel}`);
    if (!Number.isInteger(draft.count) || draft.count < 1 || draft.count > 256 || !Array.isArray(draft.steps) || draft.steps.length < 1 || draft.steps.length > 100) {
      throw new Error(`Channel ${channel} has invalid count or step count.`);
    }
    channels[channel] = {
      count: draft.count,
      steps: draft.steps.map((step, index) => {
        exact(step, ["voltage", "current", "dwell", "bost", "eost"], `Channel ${channel} step ${index + 1}`);
        if (![step.voltage, step.current, step.dwell].every((value) => typeof value === "number" && Number.isFinite(value)) || step.voltage < 0 || step.current < 0 || step.dwell < 0.01 || step.dwell > 3600 || typeof step.bost !== "boolean" || typeof step.eost !== "boolean") {
          throw new Error(`Channel ${channel} step ${index + 1} is invalid.`);
        }
        return { ...step };
      })
    };
  });
  return {
    activeChannel: document.active_channel,
    controls: { ...controls, trigger_output_pins: [...controls.trigger_output_pins] },
    channels
  };
}
