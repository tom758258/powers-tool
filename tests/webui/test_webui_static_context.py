"""Static contracts and direct behavior tests for pure WebUI context helpers."""

from __future__ import annotations

from _webui_shared import (
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
)


def test_static_context_helper_is_pure_and_loaded_before_app() -> None:
    index_html, _app_js, _styles_css = read_static_texts()
    context_js = read_static_javascript("app-context.js")

    assert "/static/app-context.js?v=__WEBUI_VERSION__" in index_html
    assert index_html.index("/static/app-context.js") < index_html.index("/static/app.js")
    assert "document" not in context_js
    assert "fetch(" not in context_js
    assert "EventSource" not in context_js
    assert "PowersToolWebUI.context" in context_js
    for function_name in (
        "isNoHardwareExecutionMode",
        "buildWorkspaceResultKey",
        "buildWorkspaceResultContextForJob",
        "buildCurrentWorkspaceResultContext",
    ):
        assert f"function {function_name}" in context_js


def test_frontend_context_helper_preserves_execution_and_workspace_isolation() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const context = globalThis.PowersToolWebUI.context;

strictAssert.equal(Object.isFrozen(context), true);
strictAssert.deepEqual(Object.keys(context).sort(), [
  "buildCurrentWorkspaceResultContext",
  "buildWorkspaceResultContextForJob",
  "buildWorkspaceResultKey",
  "isNoHardwareExecutionMode"
]);
strictAssert.equal(context.isNoHardwareExecutionMode("real"), false);
strictAssert.equal(context.isNoHardwareExecutionMode("simulate"), true);
strictAssert.equal(context.isNoHardwareExecutionMode("dry-run"), true);

const modelMaps = {
  commandModelByResource: { "RESOURCE-A": "keysight-e36312a" },
  channelModelByResource: { "RESOURCE-A": "keysight-edu36311a" }
};
const realJob = {
  command: "identify",
  runtime: {
    resource: "RESOURCE-A",
    simulate: false,
    dry_run: false,
    expected_model_id: "keysight-e36312a"
  },
  result: { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } }
};
const realContext = context.buildWorkspaceResultContextForJob(realJob, modelMaps);
strictAssert.deepEqual(realContext, {
  command: "identify",
  executionMode: "real",
  resource: "RESOURCE-A",
  expectedModelGuard: "keysight-e36312a",
  canonicalModelId: "keysight-e3646a"
});
strictAssert.equal(
  context.buildWorkspaceResultKey(realContext),
  context.buildWorkspaceResultKey(context.buildCurrentWorkspaceResultContext({
    command: "identify",
    executionMode: "real",
    resource: "RESOURCE-A",
    expectedModelGuard: "keysight-e36312a",
    canonicalModelId: "keysight-e3646a"
  }))
);
strictAssert.notEqual(
  context.buildWorkspaceResultKey(realContext),
  context.buildWorkspaceResultKey({ ...realContext, resource: "RESOURCE-B" })
);

const fallbackContext = context.buildWorkspaceResultContextForJob({
  command: "identify",
  runtime: { resource: "RESOURCE-A", simulate: false, dry_run: false },
  result: {}
}, modelMaps);
strictAssert.equal(fallbackContext.canonicalModelId, "keysight-e36312a");

const simulateContext = context.buildWorkspaceResultContextForJob({
  command: "identify",
  runtime: {
    resource: "PRESERVED-REAL-RESOURCE",
    simulate: true,
    dry_run: false,
    planning_model_id: "keysight-e36312a"
  },
  result: {}
});
strictAssert.deepEqual(simulateContext, {
  command: "identify",
  executionMode: "simulate",
  planningModelId: "keysight-e36312a"
});
strictAssert.equal(
  context.buildWorkspaceResultKey(simulateContext),
  context.buildWorkspaceResultKey(context.buildCurrentWorkspaceResultContext({
    command: "identify",
    executionMode: "simulate",
    planningIdentity: "keysight-e36312a"
  }))
);

const dryRunContext = context.buildWorkspaceResultContextForJob({
  command: "identify",
  runtime: { simulate: false, dry_run: true, planning_profile_id: "generic-scpi" },
  result: {}
});
strictAssert.deepEqual(dryRunContext, {
  command: "identify",
  executionMode: "dry-run",
  planningModelId: "",
  planningProfileId: "generic-scpi"
});
strictAssert.equal(
  context.buildWorkspaceResultKey(dryRunContext),
  context.buildWorkspaceResultKey(context.buildCurrentWorkspaceResultContext({
    command: "identify",
    executionMode: "dry-run",
    planningIdentity: "profile:generic-scpi"
  }))
);
strictAssert.notEqual(
  context.buildWorkspaceResultKey(simulateContext),
  context.buildWorkspaceResultKey(dryRunContext)
);
"""

    run_frontend_javascript_assertions(
        assertions,
        source_names=("app-context.js",),
    )
