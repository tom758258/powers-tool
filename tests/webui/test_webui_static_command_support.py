"""Direct behavior checks for command-support presentation helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_command_support_module_preserves_planning_and_channel_guards() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")

    assert 'from "./command-support.js"' in app_js
    assert "fetch(" not in command_support_js
    assert "EventSource" not in command_support_js

    run_webui_module_assertions(
        r"""
const state = {
  executionMode: "simulate",
  commands: { set: { description: "Set output" } },
  planningProfiles: {},
  commandSupportByModel: { "model-a": { set: { simulate: true } } },
  channelCapabilitiesByModel: { "model-a": { channels: [1, 2], output_control_scope: "per_channel" } },
  liveSupportByModel: {},
  resourceLiveSupport: null,
  resourceLiveSupportContext: null
};
const support = globalThis.webuiCommandSupport.createCommandSupport({
  state,
  defaultChannels: [1, 2, 3],
  isNoHardwareMode: () => true,
  selectedPlanningIdentity: () => "model-a",
  physicalModelDisplayName: (model) => model,
  selectedCommandModel: () => "model-a",
  valueOrNull: () => "RESOURCE-A",
  detectedCommandModelForResource: () => "model-a",
  selectedChannelModel: () => "model-a"
});
strictAssert.equal(support.commandMeta("set").disabled, undefined);
strictAssert.equal(support.commandMeta("set").live_support_status, "Simulation supported");
strictAssert.deepEqual(support.supportedChannelsForCurrentModel(), [1, 2]);
strictAssert.equal(support.channelUnsupportedReason(3), "model-a does not support channel 3");
strictAssert.equal(support.channelAvailabilityGuardReason("set", { channel: "3" }), "model-a does not support channel 3");
strictAssert.equal(support.transportScopeLabel("tcpip"), "TCPIP");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-support.js",),
    )
