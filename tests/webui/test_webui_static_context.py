"""Static contracts and direct behavior tests for pure WebUI context helpers."""

from __future__ import annotations

import pytest

import _webui_shared as webui_shared
from _webui_shared import (
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
)


CONTEXT_API_NAMES = (
    "isNoHardwareExecutionMode",
    "buildWorkspaceResultKey",
    "buildWorkspaceResultContextForJob",
    "buildCurrentWorkspaceResultContext",
    "buildWorkspaceResultEntry",
    "findWorkspaceResult",
)


def context_api_bootstrap(*, missing: str | None = None, invalid: str | None = None) -> str:
    properties = []
    for api_name in CONTEXT_API_NAMES:
        if api_name == missing:
            continue
        value = "null" if api_name == invalid else "() => ({})"
        properties.append(f"{api_name}: {value}")
    return (
        "globalThis.PowersToolWebUI = { "
        f"context: {{ {', '.join(properties)} }}, "
        "electrical: { resolveInputElectricalConstraint: () => ({}) } "
        "};"
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
        "buildWorkspaceResultEntry",
        "findWorkspaceResult",
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
  "buildWorkspaceResultEntry",
  "buildWorkspaceResultKey",
  "findWorkspaceResult",
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

    const immutableRuntime = {
      resource: "RESOURCE-A",
      simulate: false,
      dry_run: false,
      expected_model_id: "keysight-e36312a"
    };
    const immutableResult = {
      resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" },
      live_support: { model_id: "keysight-e36312a" }
    };
    const immutableJob = { command: "identify", runtime: immutableRuntime, result: immutableResult };
    const immutableSnapshot = {
      command: "identify",
      executionMode: "real",
      resource: "RESOURCE-A",
      expectedModelGuard: "keysight-e36312a",
      canonicalModelId: "keysight-e3646a"
    };
    const immutableModelMaps = {
      commandModelByResource: { "RESOURCE-A": "keysight-e36312a" },
      channelModelByResource: { "RESOURCE-A": "keysight-edu36311a" }
    };
    const immutableBefore = {
      job: JSON.parse(JSON.stringify(immutableJob)),
      runtime: JSON.parse(JSON.stringify(immutableRuntime)),
      result: JSON.parse(JSON.stringify(immutableResult)),
      snapshot: JSON.parse(JSON.stringify(immutableSnapshot)),
      modelMaps: JSON.parse(JSON.stringify(immutableModelMaps))
    };
    context.buildWorkspaceResultContextForJob(immutableJob, immutableModelMaps);
    context.buildCurrentWorkspaceResultContext(immutableSnapshot);
    strictAssert.deepEqual(immutableJob, immutableBefore.job);
    strictAssert.deepEqual(immutableRuntime, immutableBefore.runtime);
    strictAssert.deepEqual(immutableResult, immutableBefore.result);
    strictAssert.deepEqual(immutableSnapshot, immutableBefore.snapshot);
    strictAssert.deepEqual(immutableModelMaps, immutableBefore.modelMaps);
"""

    run_frontend_javascript_assertions(
        assertions,
        source_names=("app-context.js",),
    )


def test_frontend_workspace_result_entry_and_lookup_preserve_cache_contract() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const context = globalThis.PowersToolWebUI.context;
const namespace = globalThis.PowersToolWebUI;
const globalKeysBefore = Reflect.ownKeys(globalThis);
const contextDescriptorBefore = Object.getOwnPropertyDescriptor(namespace, "context");
const modelMaps = {
  commandModelByResource: { "RESOURCE-A": "keysight-e36312a" },
  channelModelByResource: { "RESOURCE-A": "keysight-edu36311a" }
};
const runtime = {
  resource: "RESOURCE-A",
  simulate: false,
  dry_run: false,
  expected_model_id: "keysight-e36312a"
};
const result = { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } };
const job = { status: "finished", command: "identify", runtime, result };
const immutableBefore = JSON.parse(JSON.stringify({ job, runtime, result, modelMaps }));
const expectedContext = context.buildWorkspaceResultContextForJob(job, modelMaps);
const entry = context.buildWorkspaceResultEntry(job, modelMaps);

strictAssert.equal(Object.getPrototypeOf(entry), Object.prototype);
strictAssert.deepEqual(entry.context, expectedContext);
strictAssert.equal(entry.key, context.buildWorkspaceResultKey(expectedContext));
strictAssert.strictEqual(entry.job, job);
const secondEntry = context.buildWorkspaceResultEntry(job, modelMaps);
strictAssert.notStrictEqual(secondEntry, entry);
strictAssert.notStrictEqual(secondEntry.context, entry.context);
strictAssert.strictEqual(secondEntry.job, job);
strictAssert.deepEqual({ job, runtime, result, modelMaps }, immutableBefore);

strictAssert.equal(context.buildWorkspaceResultEntry(undefined, modelMaps), null);
strictAssert.equal(context.buildWorkspaceResultEntry(null, modelMaps), null);
for (const status of ["accepted", "started", "failed", "cancelled"]) {
  strictAssert.equal(context.buildWorkspaceResultEntry({ ...job, status }, modelMaps), null);
}
strictAssert.equal(context.buildWorkspaceResultEntry({ ...job, command: "" }, modelMaps), null);
for (const falsyResult of [null, false, 0, ""]) {
  strictAssert.equal(context.buildWorkspaceResultEntry({ ...job, result: falsyResult }, modelMaps), null);
}
const emptyResultJob = { ...job, result: {} };
strictAssert.strictEqual(context.buildWorkspaceResultEntry(emptyResultJob, modelMaps).job, emptyResultJob);

const cache = Object.create(null);
const lookupContext = entry.context;
const lookupContextBefore = JSON.parse(JSON.stringify(lookupContext));
const cacheKeysBeforeMiss = Reflect.ownKeys(cache);
strictAssert.equal(context.findWorkspaceResult(cache, lookupContext), null);
strictAssert.deepEqual(Reflect.ownKeys(cache), cacheKeysBeforeMiss);
strictAssert.deepEqual(lookupContext, lookupContextBefore);
cache[entry.key] = job;
const cacheKeysBeforeHit = Reflect.ownKeys(cache);
strictAssert.strictEqual(context.findWorkspaceResult(cache, lookupContext), job);
strictAssert.deepEqual(Reflect.ownKeys(cache), cacheKeysBeforeHit);
const laterJob = { ...job, result: { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" }, marker: "later" } };
const laterEntry = context.buildWorkspaceResultEntry(laterJob, modelMaps);
strictAssert.equal(laterEntry.key, entry.key);
cache[laterEntry.key] = laterEntry.job;
strictAssert.strictEqual(context.findWorkspaceResult(cache, lookupContext), laterJob);

const jobFor = (command, runtimeValue, resultValue) => ({
  status: "finished", command, runtime: runtimeValue, result: resultValue
});
const realBase = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { resource: "RESOURCE-A", simulate: false, dry_run: false, expected_model_id: "keysight-e36312a" },
  { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } }
), modelMaps);
const realOtherResource = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { resource: "RESOURCE-B", simulate: false, dry_run: false, expected_model_id: "keysight-e36312a" },
  { resource: { name: "RESOURCE-B", model_id: "keysight-e3646a" } }
), modelMaps);
const realOtherExpected = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { resource: "RESOURCE-A", simulate: false, dry_run: false, expected_model_id: "keysight-edu36311a" },
  { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } }
), modelMaps);
const realOtherCanonical = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { resource: "RESOURCE-A", simulate: false, dry_run: false, expected_model_id: "keysight-e36312a" },
  { resource: { name: "RESOURCE-A", model_id: "keysight-edu36311a" } }
), modelMaps);
const realOtherCommand = context.buildWorkspaceResultEntry(jobFor(
  "capabilities",
  { resource: "RESOURCE-A", simulate: false, dry_run: false, expected_model_id: "keysight-e36312a" },
  { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } }
), modelMaps);
const simulateA = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { resource: "PRESERVED-REAL", simulate: true, dry_run: false, planning_model_id: "keysight-e36312a" },
  {}
));
const simulateB = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { resource: "PRESERVED-OTHER", simulate: true, dry_run: false, planning_model_id: "keysight-edu36311a" },
  {}
));
const dryModel = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { simulate: false, dry_run: true, planning_model_id: "keysight-e36312a" },
  {}
));
const dryProfile = context.buildWorkspaceResultEntry(jobFor(
  "identify",
  { simulate: false, dry_run: true, planning_profile_id: "generic-scpi" },
  {}
));
for (const isolatedEntry of [realOtherResource, realOtherExpected, realOtherCanonical, realOtherCommand, simulateA, dryModel, dryProfile]) {
  strictAssert.notEqual(realBase.key, isolatedEntry.key);
}
strictAssert.notEqual(simulateA.key, simulateB.key);
strictAssert.notEqual(dryModel.key, dryProfile.key);
strictAssert.notEqual(simulateA.key, dryModel.key);
strictAssert.notEqual(simulateA.key, dryProfile.key);

strictAssert.deepEqual(Reflect.ownKeys(globalThis), globalKeysBefore);
strictAssert.strictEqual(namespace.context, context);
strictAssert.deepEqual(Object.getOwnPropertyDescriptor(namespace, "context"), contextDescriptorBefore);
"""

    run_frontend_javascript_assertions(
        assertions,
        source_names=("app-context.js",),
    )


def test_frontend_context_helper_adds_only_namespace_global_property() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const addedGlobalProperties = Reflect.ownKeys(globalThis)
  .filter((name) => !globalPropertiesBeforeContextHelper.has(name));
strictAssert.deepEqual(addedGlobalProperties, ["PowersToolWebUI"]);
const descriptor = Object.getOwnPropertyDescriptor(globalThis.PowersToolWebUI, "context");
strictAssert.equal(Object.isFrozen(globalThis.PowersToolWebUI.context), true);
strictAssert.equal(descriptor.writable, false);
strictAssert.equal(descriptor.configurable, false);
"""

    run_frontend_javascript_assertions(
        assertions,
        source_names=("app-context.js",),
        bootstrap="const globalPropertiesBeforeContextHelper = new Set(Reflect.ownKeys(globalThis));",
    )


def test_frontend_context_helper_rejects_duplicate_load() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js", "app-context.js"),
        expected_failure_substrings=("app-context.js", "already initialized"),
    )


@pytest.mark.parametrize("existing_context", ("null", "false", "0", '\"\"'))
def test_frontend_context_helper_rejects_falsy_existing_context(existing_context: str) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js",),
        bootstrap=f"globalThis.PowersToolWebUI = {{ context: {existing_context} }};",
        expected_failure_substrings=("app-context.js", "already initialized"),
    )


@pytest.mark.parametrize("existing_root", ("undefined", "null", "false", "0", '\"\"', '\"incompatible\"', "() => {}"))
def test_frontend_context_helper_rejects_incompatible_namespace_root(existing_root: str) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js",),
        bootstrap=f"globalThis.PowersToolWebUI = {existing_root};",
        expected_failure_substrings=("app-context.js", "namespace must be a usable object"),
    )


def test_frontend_context_helper_rejects_nonextensible_namespace() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js",),
        bootstrap="globalThis.PowersToolWebUI = Object.freeze({});",
        expected_failure_substrings=("app-context.js", "cannot define its context API"),
    )


def test_frontend_app_fails_fast_without_context_helper() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app.js",),
        expected_failure_substrings=("app.js", "PowersToolWebUI.context failed to load before app.js"),
    )


@pytest.mark.parametrize("missing_api", CONTEXT_API_NAMES)
def test_frontend_app_fails_fast_when_required_context_api_is_missing(missing_api: str) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app.js",),
        bootstrap=context_api_bootstrap(missing=missing_api),
        expected_failure_substrings=("app.js", missing_api),
    )


@pytest.mark.parametrize("invalid_api", CONTEXT_API_NAMES)
def test_frontend_app_fails_fast_when_required_context_api_is_not_a_function(invalid_api: str) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app.js",),
        bootstrap=context_api_bootstrap(invalid=invalid_api),
        expected_failure_substrings=("app.js", invalid_api),
    )


def test_frontend_classic_scripts_load_context_before_app() -> None:
    run_frontend_javascript_assertions(
        r"""
const strictAssert = require("node:assert/strict");
strictAssert.equal(typeof globalThis.PowersToolWebUI.context.buildWorkspaceResultKey, "function");
strictAssert.equal(typeof globalThis.PowersToolWebUI.context.buildWorkspaceResultEntry, "function");
strictAssert.equal(typeof globalThis.PowersToolWebUI.context.findWorkspaceResult, "function");
strictAssert.equal(typeof state, "object");
""",
        source_names=("app-context.js", "app-electrical.js", "app.js"),
    )


def test_frontend_classic_scripts_fail_fast_when_app_loads_first() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app.js", "app-context.js"),
        expected_failure_substrings=("app.js", "PowersToolWebUI.context failed to load before app.js"),
    )


def test_frontend_runner_detects_cross_script_top_level_lexical_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = {
        "first-classic-script.js": "const sharedClassicBinding = 1;",
        "second-classic-script.js": "const sharedClassicBinding = 2;",
    }
    monkeypatch.setattr(webui_shared, "read_static_javascript", sources.__getitem__)

    webui_shared.run_frontend_javascript_assertions(
        "",
        source_names=("first-classic-script.js", "second-classic-script.js"),
        expected_failure_substrings=("second-classic-script.js", "already been declared"),
    )
