"""Static and direct behavior checks for WebUI Job History presentation."""

from __future__ import annotations

from _webui_shared import (
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
    run_webui_module_assertions,
)


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
for (let index = 2; index <= 21; index += 1) {
  history.addHistory(state, `job-${index}`, "set", "accepted", "Set", helpers);
}
strictAssert.equal(state.jobs.length, 20);
strictAssert.equal(state.jobs[0].jobId, "job-21");
strictAssert.equal(state.jobs.at(-1).jobId, "job-2");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("jobs.js",),
    )


def test_app_job_history_adapters_supply_complete_render_dependencies() -> None:
    run_frontend_javascript_assertions(
        r"""
const strictAssert = require("node:assert/strict");
const elements = new Map();
const historyNode = {
  _innerHTML: "",
  children: [],
  get innerHTML() { return this._innerHTML; },
  set innerHTML(value) { this._innerHTML = value; this.children = []; },
  appendChild(child) { this.children.push(child); }
};
const resultNode = { textContent: "" };
elements.set("job-history", historyNode);
elements.set("result", resultNode);
document.getElementById = (id) => elements.get(id) || { value: "" };
document.createElement = () => ({
  className: "",
  textContent: "",
  children: [],
  append(...children) { this.children.push(...children); }
});

isNoHardwareMode = () => false;
runtimePayload = () => ({ simulate: false, dry_run: false });
updateExecutionModeUi = () => {};
let subscribedJobId = null;
subscribeToJob = (jobId) => { subscribedJobId = jobId; };
webuiApi.fetchJson = async () => ({ job_id: "scan-job" });

(async () => {
  await scanResources();
  strictAssert.equal(subscribedJobId, "scan-job");
  strictAssert.equal(state.jobs[0].label, "Scan Device");
  strictAssert.equal(state.jobs[0].status, "accepted");
  strictAssert.match(historyNode.children[0].children[2].className, /running/);

  updateHistory("scan-job", "started");
  strictAssert.equal(state.jobs[0].status, "started");
  strictAssert.equal(historyNode.children[0].children[2].textContent, "Started");

  updateJobResult("scan-job", "finished", "Scan complete");
  strictAssert.equal(state.jobs[0].summary, "Scan complete");
  strictAssert.equal(historyNode.children[0].children[2].textContent, "Success");

  renderClientResult("Scan Device", "failed", "Client failure", { error: "detail survives" });
  strictAssert.equal(state.jobs[0].summary, "Client failure");
  strictAssert.equal(resultNode.textContent, JSON.stringify({ error: "detail survives" }, null, 2));

  clearJobResults();
  strictAssert.deepEqual(state.jobs, []);
  strictAssert.equal(historyNode.children.length, 0);
  renderHistory();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    )
