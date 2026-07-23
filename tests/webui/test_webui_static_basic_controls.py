"""Direct behavior checks for Basic control presentation helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_basic_controls_module_has_explicit_dependencies_and_preserves_action_labels() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")

    assert 'from "./basic-controls.js"' in app_js
    assert "fetch(" not in basic_controls_js
    assert "EventSource" not in basic_controls_js
    assert "createBasicControls" in basic_controls_js

    run_webui_module_assertions(
        r"""
const basic = globalThis.webuiBasicControls.createBasicControls({
  state: { livePanel: null, basicActionStates: {}, basicJobActions: {}, executionMode: "simulate" },
  defaultChannels: [1, 2, 3],
  e3646aCapabilityError: "capability error",
  e3646aGlobalOutputDescription: "global output",
  valueOrNull: () => null,
  basicOutputPresentation: () => ({ mode: "normal", capability: { channels: [1, 2, 3] } }),
  supportedChannelsForCurrentModel: () => [1, 2, 3],
  channelUnsupportedReason: () => "",
  commandMeta: () => ({ disabled: false }),
  outputControlTitle: () => "",
  outputAllControlTitle: () => "",
  basicSetpointValues: () => ({ ok: false }),
  refreshBasicInputConstraints: () => {},
  validateBasicInput: () => {},
  eventSummary: () => "event"
});
strictAssert.equal(basic.basicActionKey("output", "all"), "output:all");
strictAssert.equal(basic.basicActionDisplayName("set:2"), "Basic CH2 Set");
strictAssert.equal(basic.basicActionDisplayName("output:all"), "Basic All Output");
strictAssert.equal(basic.basicStatusText("success"), "Basic command completed.");
strictAssert.equal(basic.basicStatusText("error"), "Basic command failed. See Result Detail.");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("basic-controls.js",),
    )


def test_basic_controls_refresh_uses_explicit_current_action_and_preserves_set_title() -> None:
    run_webui_module_assertions(
        r"""
const { setLocale } = await import(moduleUrls["i18n.js"]);
const statusNode = { textContent: "" };
const setButton = {
  disabled: false,
  title: "",
  classList: { toggle() {} }
};
const card = {
  title: "",
  classList: { toggle() {} },
  setAttribute() {},
  querySelector(selector) {
    return selector === "[data-basic-set]" ? setButton : null;
  }
};
globalThis.document = {
  getElementById(id) {
    return id === "basic-command-status" ? statusNode : null;
  },
  querySelector(selector) {
    if (selector === '[data-basic-channel="1"]') return card;
    if (selector === '[data-basic-set="1"]') return setButton;
    return null;
  }
};
const state = {
  livePanel: null,
  basicActionStates: {},
  basicJobActions: {},
  basicStatusActionKey: null,
  executionMode: "simulate"
};
const basic = globalThis.webuiBasicControls.createBasicControls({
  state,
  defaultChannels: [1],
  valueOrNull: () => null,
  basicOutputPresentation: () => ({ mode: "normal", capability: { channels: [1] } }),
  supportedChannelsForCurrentModel: () => [1],
  channelUnsupportedReason: () => "",
  commandMeta: () => ({ disabled: false, live_support_status: "raw support" }),
  outputControlTitle: () => "",
  outputAllControlTitle: () => "",
  basicSetpointValues: () => ({ ok: false }),
  refreshBasicInputConstraints: () => {},
  validateBasicInput: () => {},
  eventSummary: () => "event"
});

basic.setBasicActionState("set:1", "success", { key: "basic_controls.status.completed" });
const completedIdentity = state.basicActionStates["set:1"];
basic.setBasicActionState("output:2", "pending", { key: "basic_controls.status.waiting_readback" }, {
  desiredOutput: true,
  awaitingReadback: true
});
const pendingIdentity = state.basicActionStates["output:2"];
strictAssert.equal(state.basicStatusActionKey, "output:2");
strictAssert.equal(statusNode.textContent, "Waiting for Live Data readback.");

setLocale("zh-TW");
basic.refreshBasicControlsPresentation();
strictAssert.equal(statusNode.textContent, "正在等待即時資料讀回。");
strictAssert.equal(state.basicActionStates["set:1"], completedIdentity);
strictAssert.equal(state.basicActionStates["output:2"], pendingIdentity);
strictAssert.equal(pendingIdentity.desiredOutput, true);
strictAssert.equal(pendingIdentity.awaitingReadback, true);
strictAssert.equal(pendingIdentity.status, "pending");

basic.setBasicActionState("set:1", "success", { key: "basic_controls.status.completed" });
strictAssert.equal(setButton.title, "基本命令已完成。");
basic.refreshBasicControlsPresentation();
strictAssert.equal(setButton.title, "基本命令已完成。");
basic.setBasicActionState("set:1", "error", "VISA <raw> detail");
basic.refreshBasicControlsPresentation();
strictAssert.equal(setButton.title, "VISA <raw> detail");

basic.clearBasicActionState("set:1");
strictAssert.equal(state.basicStatusActionKey, null);
strictAssert.equal(statusNode.textContent, "即時資料仍是儀器狀態的依據。");
strictAssert.equal(state.basicActionStates["output:2"], pendingIdentity);
setLocale("en");
""",
        ("basic-controls.js", "i18n.js"),
    )


def test_basic_output_tooltips_translate_without_changing_machine_state() -> None:
    run_webui_module_assertions(
        r"""
const { setLocale } = await import(moduleUrls["i18n.js"]);
const state = {
  commands: {},
  commandSupportByModel: { "keysight-model": {} },
  channelCapabilitiesByModel: {
    "keysight-model": { channels: [1, 2], output_control_scope: "per_channel" }
  }
};
let selectedModel = "keysight-model";
const support = globalThis.webuiCommandSupport.createCommandSupport({
  state,
  defaultChannels: [1, 2],
  isNoHardwareMode: () => false,
  selectedPlanningIdentity: () => null,
  physicalModelDisplayName: () => "Model <raw>",
  selectedCommandModel: () => "keysight-model",
  valueOrNull: () => "RESOURCE",
  detectedCommandModelForResource: () => "keysight-model",
  selectedChannelModel: () => selectedModel
});
strictAssert.equal(support.outputControlTitle(1, true, true), "CH1 output is ON.");
strictAssert.equal(support.outputControlTitle(1, false, true), "CH1 output is OFF.");
strictAssert.equal(support.outputControlTitle(1, false, false), "CH1 output state is unknown.");
strictAssert.equal(support.outputAllControlTitle(true), "All supported outputs are ON.");
strictAssert.equal(support.outputAllControlTitle(false), "One or more supported outputs are OFF or unknown.");

state.channelCapabilitiesByModel["keysight-model"].output_control_scope = "global";
strictAssert.equal(
  support.globalOutputHintText(),
  "Model <raw> output enable is global for supported channels."
);
selectedModel = null;
strictAssert.equal(support.globalOutputHintText(), "Output enable is global for supported channels.");
selectedModel = "keysight-model";
setLocale("zh-TW");
strictAssert.equal(support.outputControlTitle(1, true, true), "CH1 輸出為 ON。 Model <raw> 對支援通道採用全域輸出啟用。");
strictAssert.equal(support.outputControlTitle(1, false, true), "CH1 輸出為 OFF。 Model <raw> 對支援通道採用全域輸出啟用。");
strictAssert.equal(support.outputControlTitle(1, false, false), "CH1 輸出狀態未知。 Model <raw> 對支援通道採用全域輸出啟用。");
strictAssert.equal(support.outputAllControlTitle(true), "所有支援的輸出皆為 ON。 Model <raw> 對支援通道採用全域輸出啟用。");
strictAssert.equal(support.outputAllControlTitle(false), "一個或多個支援的輸出為 OFF 或狀態未知。 Model <raw> 對支援通道採用全域輸出啟用。");
strictAssert.equal(state.channelCapabilitiesByModel["keysight-model"].output_control_scope, "global");
setLocale("en");
""",
        ("command-support.js", "i18n.js"),
    )
