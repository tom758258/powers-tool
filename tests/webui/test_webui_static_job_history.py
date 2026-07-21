"""Static and direct behavior checks for WebUI Job History presentation."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_frontend_job_history_module_preserves_bounded_status_history() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    history_js = read_static_javascript("jobs.js")

    assert 'from "./jobs.js"' in app_js
    assert "export function addHistory" in history_js
    assert "export function openJobEvents" in history_js

    run_webui_module_assertions(
        r"""
const history = globalThis.webuiJobTransport;
const state = { jobs: [] };
const calls = [];
const historyNode = { innerHTML: "", appendChild: () => {} };
globalThis.document = {
  getElementById: () => historyNode,
  createElement: () => ({ append: () => {} })
};
const helpers = {
  commandDisplayName: (value) => `Label ${value}`,
  statusSummary: (value) => `Summary ${value}`,
  statusLabel: (value) => `Status ${value}`,
  statusClass: (value) => `Class ${value}`,
  updateExecutionModeUi: () => calls.push("mode")
};
history.addHistory(state, "job-1", "set", "accepted", "Set", helpers);
strictAssert.deepEqual(state.jobs, [{ jobId: "job-1", command: "set", label: "Label Set", status: "accepted", summary: "Summary accepted" }]);
history.updateHistory(state, "job-1", "started", helpers);
strictAssert.equal(state.jobs[0].status, "started");
history.updateJobResult(state, "job-1", "finished", "Done", helpers);
strictAssert.equal(state.jobs[0].summary, "Done");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("jobs.js",),
    )
