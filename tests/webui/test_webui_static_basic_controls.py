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
