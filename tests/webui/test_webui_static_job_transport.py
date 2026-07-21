"""Direct behavior checks for Job HTTP and SSE transport helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_job_transport_module_preserves_post_and_sse_binding_contract() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    job_transport_js = read_static_javascript("jobs.js")

    assert 'from "./jobs.js"' in app_js
    assert "export function renderHistory" in job_transport_js
    assert "fetch(" not in job_transport_js

    run_webui_module_assertions(
        r"""
const transport = globalThis.webuiJobTransport;
const requests = [];
const fetchJson = async (path, options) => { requests.push({ path, options }); return { job_id: "job-1" }; };
const payload = { command: "snapshot", parameters: {} };
await transport.submitJob(fetchJson, payload);
strictAssert.deepEqual(requests, [{ path: "/api/jobs", options: { method: "POST", body: JSON.stringify(payload) } }]);
const listeners = {};
const source = { addEventListener: (type, handler) => { listeners[type] = handler; }, onerror: null };
let closed = 0;
const events = [];
const opened = transport.openJobEvents({ jobId: "job 1", baseUrl: "/api/events", closeEvents: () => { closed += 1; }, onEvent: (jobId, event) => events.push({ jobId, event }), onError: (jobId) => events.push({ error: jobId }), eventSourceFactory: (url) => { strictAssert.equal(url, "/api/events?job_id=job%201"); return source; } });
strictAssert.equal(opened, source);
strictAssert.equal(closed, 1);
listeners.progress({ data: '{"type":"progress"}' });
source.onerror();
strictAssert.deepEqual(events, [{ jobId: "job 1", event: { type: "progress" } }, { error: "job 1" }]);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("jobs.js",),
    )
