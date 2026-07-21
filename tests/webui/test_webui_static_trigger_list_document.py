"""Direct behavior checks for Trigger List workspace document helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_trigger_list_document_module_is_pure_and_preserves_workspace_contract() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    trigger_list_js = read_static_javascript("trigger-list.js")

    assert 'from "./trigger-list.js"' in app_js
    assert "getElementById" not in trigger_list_js
    assert "createElement" not in trigger_list_js
    assert "querySelector" not in trigger_list_js
    assert "fetch(" not in trigger_list_js
    assert "EventSource" not in trigger_list_js

    run_webui_module_assertions(
        r"""
const trigger = globalThis.webuiTriggerListDocument;
strictAssert.deepEqual(trigger.defaultTriggerListStep(), { voltage: 0, current: 0.05, dwell: 0.01, bost: false, eost: false });
strictAssert.deepEqual(Object.keys(trigger.defaultTriggerListChannels()), ["1", "2", "3"]);
strictAssert.deepEqual(trigger.defaultTriggerListControls(), { source: "immediate", fire: false, wait_complete: true, trigger_output_pins: [], trigger_output_polarity: "positive", exclusive_pins: false, poll_ms: 200, wait_timeout_ms: null, leave_trigger_configured: false });
const state = { triggerListActiveChannel: 2, triggerListControls: trigger.defaultTriggerListControls(), triggerListChannels: trigger.defaultTriggerListChannels() };
state.triggerListControls.trigger_output_pins = [1, 3];
const saved = trigger.triggerListWorkspaceDocument(state);
strictAssert.equal(saved.kind, "powers-tool-trigger-list-workspace");
strictAssert.equal(saved.version, 1);
strictAssert.deepEqual(trigger.validateTriggerListWorkspace(saved), { activeChannel: 2, controls: state.triggerListControls, channels: state.triggerListChannels });
strictAssert.throws(() => trigger.validateTriggerListWorkspace({ ...saved, channels: { ...saved.channels, "1": { ...saved.channels["1"], steps: [] } } }), /invalid count or step count/);
strictAssert.throws(() => trigger.validateTriggerListWorkspace({ ...saved, controls: { ...saved.controls, unknown: true } }), /unknown or missing fields/);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("trigger-list.js",),
    )
