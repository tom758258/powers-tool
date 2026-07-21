"""Native-module contracts for initial frontend state."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_state_module_owns_initial_state_without_browser_dependencies() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")

    assert 'from "./state.js"' in app_js
    assert "const state = {" not in app_js
    assert "document" not in state_js
    assert "fetch(" not in state_js
    assert "EventSource" not in state_js


def test_state_module_preserves_page_local_initial_values() -> None:
    run_webui_module_assertions(
        r"""
const first = globalThis.webuiState.createInitialState({
  rampListSegments: [{ channel: 1 }],
  triggerListControls: { source: "immediate" },
  triggerListChannels: { "1": { count: 1 } },
  sequenceSteps: [{ action: "wait", seconds: 0 }]
});
const second = globalThis.webuiState.createInitialState({
  rampListSegments: [{ channel: 2 }],
  triggerListControls: { source: "bus" },
  triggerListChannels: { "2": { count: 2 } },
  sequenceSteps: [{ action: "set", channel: 1 }]
});
strictAssert.equal(first.executionMode, "real");
strictAssert.deepEqual(first.realIdentityCache, { expectedModelId: "", resource: "", serial: {} });
strictAssert.deepEqual(first.planningIdentityCache, { simulate: "", "dry-run": "" });
strictAssert.equal(first.realWriteAuthorization, null);
strictAssert.equal(first.rampListSegments[0].channel, 1);
strictAssert.equal(second.rampListSegments[0].channel, 2);
strictAssert.notStrictEqual(first.realIdentityCache, second.realIdentityCache);
strictAssert.notStrictEqual(first.planningIdentityCache, second.planningIdentityCache);
strictAssert.notStrictEqual(first.sequenceExpanded, second.sequenceExpanded);
strictAssert.deepEqual(first.workflowControl, { phase: "idle", jobId: null, command: null });
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("state.js",),
    )
