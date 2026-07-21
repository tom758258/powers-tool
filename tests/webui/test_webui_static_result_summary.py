"""Static and direct behavior checks for WebUI job-result summaries."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_frontend_result_summary_module_preserves_job_and_status_text() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    result_summary_js = read_static_javascript("results.js")

    assert 'from "./results.js"' in app_js
    assert "export function renderWorkspaceJob" in result_summary_js
    assert "fetch" not in result_summary_js
    assert "EventSource" not in result_summary_js

    run_webui_module_assertions(
        r"""
const summary = globalThis.webuiResultSummary;
strictAssert.equal(summary.statusSummary("accepted"), "Accepted");
strictAssert.equal(summary.statusSummary("cancel_requested"), "Waiting for safe-off and cleanup");
strictAssert.equal(summary.statusLabel("finished"), "Success");
strictAssert.equal(summary.statusClass("failed"), "failed");
strictAssert.equal(summary.eventSummary({ type: "failed", data: { code: "cleanup_failed" } }), "Failed  cleanup_failed");
strictAssert.equal(summary.jobSummary({ status: "cancelled" }), "Cancelled");
strictAssert.equal(summary.successfulJobSummary({
  command: "readback",
  result: { channels: [{ channel: 1, setpoints: { voltage: 1, current: 0.1 } }] }
}), "1 channel - CH1 1V/0.1A");
strictAssert.equal(summary.successfulJobSummary({
  command: "identify",
  result: { idn: { model: "E36312A", serial: "SN" } }
}), "E36312A - serial SN");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("results.js",),
    )
