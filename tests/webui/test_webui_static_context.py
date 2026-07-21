"""Native-module contracts for pure WebUI execution-context helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_context_module_is_pure_and_bootstrap_imports_it() -> None:
    index_html, app_js, _styles_css = read_static_texts()
    context_js = read_static_javascript("execution-context.js")

    assert '<script type="module" src="/static/app.js"></script>' in index_html
    assert 'from "./execution-context.js"' in app_js
    assert "PowersToolWebUI" not in context_js
    assert "document" not in context_js
    assert "fetch(" not in context_js
    assert "EventSource" not in context_js


def test_context_module_preserves_execution_and_workspace_isolation() -> None:
    run_webui_module_assertions(
        r"""
const context = globalThis.webuiContext;
strictAssert.deepEqual(Object.keys(context).sort(), [
  "buildCurrentWorkspaceResultContext", "buildWorkspaceResultContextForJob",
  "buildWorkspaceResultEntry", "buildWorkspaceResultKey", "findWorkspaceResult",
  "isNoHardwareExecutionMode"
]);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
strictAssert.equal(context.isNoHardwareExecutionMode("real"), false);
strictAssert.equal(context.isNoHardwareExecutionMode("simulate"), true);
strictAssert.equal(context.isNoHardwareExecutionMode("dry-run"), true);
const maps = { commandModelByResource: { "R": "keysight-e36312a" }, channelModelByResource: { "R": "keysight-edu36311a" } };
const job = { command: "identify", runtime: { resource: "R", expected_model_id: "keysight-e36312a" }, result: { resource: { name: "R", model_id: "keysight-e3646a" } }, status: "finished" };
const real = context.buildWorkspaceResultContextForJob(job, maps);
strictAssert.deepEqual(real, { command: "identify", executionMode: "real", resource: "R", expectedModelGuard: "keysight-e36312a", canonicalModelId: "keysight-e3646a" });
strictAssert.equal(context.buildWorkspaceResultKey(real), context.buildWorkspaceResultKey(context.buildCurrentWorkspaceResultContext(real)));
strictAssert.notEqual(context.buildWorkspaceResultKey(real), context.buildWorkspaceResultKey({ ...real, resource: "OTHER" }));
const fallback = context.buildWorkspaceResultContextForJob({ command: "identify", runtime: { resource: "R" }, result: {} }, maps);
strictAssert.equal(fallback.canonicalModelId, "keysight-e36312a");
strictAssert.deepEqual(context.buildWorkspaceResultContextForJob({ command: "set", runtime: { simulate: true, planning_model_id: "keysight-e36312a" } }), { command: "set", executionMode: "simulate", planningModelId: "keysight-e36312a" });
strictAssert.deepEqual(context.buildCurrentWorkspaceResultContext({ command: "set", executionMode: "dry-run", planningIdentity: "profile:generic-scpi" }), { command: "set", executionMode: "dry-run", planningProfileId: "generic-scpi" });
const entry = context.buildWorkspaceResultEntry(job, maps);
strictAssert.equal(context.findWorkspaceResult({ [entry.key]: job }, entry.context), job);
strictAssert.equal(context.buildWorkspaceResultEntry({ status: "running" }), null);
const runtime = { resource: "R", expected_model_id: "keysight-e36312a" };
const result = { resource: { name: "R", model_id: "keysight-e3646a" } };
const immutableJob = { command: "identify", runtime, result, status: "finished" };
const before = JSON.parse(JSON.stringify({ runtime, result, maps, immutableJob }));
context.buildWorkspaceResultContextForJob(immutableJob, maps);
context.buildWorkspaceResultEntry(immutableJob, maps);
strictAssert.deepEqual({ runtime, result, maps, immutableJob }, before);
""",
        ("execution-context.js",),
    )
