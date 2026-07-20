"""Direct behavior and loading tests for pure WebUI electrical helpers."""

from __future__ import annotations

import pytest

from _webui_shared import read_static_javascript, read_static_texts, run_frontend_javascript_assertions


CONTEXT_API_NAMES = (
    "isNoHardwareExecutionMode",
    "buildWorkspaceResultKey",
    "buildWorkspaceResultContextForJob",
    "buildCurrentWorkspaceResultContext",
    "buildWorkspaceResultEntry",
    "findWorkspaceResult",
)


def app_electrical_bootstrap(*, missing: bool = False, invalid: bool = False) -> str:
    context_api_properties = ", ".join(f"{name}: () => ({{}})" for name in CONTEXT_API_NAMES)
    electrical_properties = "" if missing else (
        "resolveInputElectricalConstraint: null" if invalid else "resolveInputElectricalConstraint: () => ({})"
    )
    return (
        "globalThis.PowersToolWebUI = { "
        f"context: {{ {context_api_properties} }}, electrical: {{ {electrical_properties} }} "
        "};"
    )


def test_static_electrical_helper_is_pure_and_loaded_between_context_and_app() -> None:
    index_html, _app_js, _styles_css = read_static_texts()
    electrical_js = read_static_javascript("app-electrical.js")

    assert "/static/app-electrical.js?v=__WEBUI_VERSION__" in index_html
    assert index_html.index("/static/app-context.js") < index_html.index("/static/app-electrical.js")
    assert index_html.index("/static/app-electrical.js") < index_html.index("/static/app.js")
    assert "document" not in electrical_js
    assert "fetch(" not in electrical_js
    assert "EventSource" not in electrical_js
    assert "setpointRanges" not in electrical_js
    assert "function resolveInputElectricalConstraint" in electrical_js


def test_frontend_electrical_helper_resolves_existing_parameter_and_rating_semantics() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const electrical = globalThis.PowersToolWebUI.electrical;
const constraints = {
  voltage: { min: 0, max: 100, step: 0.1, description: "Generic voltage guidance" },
  current: { min: null, max: null, step: null, exclusive_min: null, description: "" },
  start_voltage: { min: 0, step: "any", description: "Start" },
  stop_voltage: { min: 0, step: "any", description: "Stop" },
  delay_ms: { min: 0, step: 1, description: false }
};
const ratings = {
  "model-a": { channels: [
    { channel: 1, max_voltage: 6, max_current: 5 },
    { channel: 2, max_voltage: 25, max_current: 1 }
  ] }
};
const before = JSON.parse(JSON.stringify({ constraints, ratings }));

const voltage = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: 1, parameterName: "voltage"
});
strictAssert.deepEqual(voltage, {
  parameter: { attributes: { min: "0", max: "100", step: "0.1", title: "Generic voltage guidance" } },
  rating: { max_voltage: 6, max_current: 5 },
  override: { attributes: { max: "6", title: "Official independent-channel DC output rating: maximum 6 V." } }
});
strictAssert.deepEqual(Object.keys(voltage), ["parameter", "rating", "override"]);

const current = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: "2", parameterName: "current"
});
strictAssert.deepEqual(current.parameter, {
  attributes: { min: "null", max: "null", step: "any" }, exclusiveMin: "null"
});
strictAssert.deepEqual(current.rating, { max_voltage: 25, max_current: 1 });
strictAssert.deepEqual(current.override, {
  attributes: { max: "1", title: "Official independent-channel DC output rating: maximum 1 A." }
});

for (const parameterName of ["start_voltage", "stop_voltage"]) {
  const result = electrical.resolveInputElectricalConstraint({
    parameterConstraints: constraints, electricalRatingsByModel: ratings,
    modelId: "model-a", channel: 1, parameterName
  });
  strictAssert.equal(result.override.attributes.max, "6");
  strictAssert.match(result.override.attributes.title, /maximum 6 V/);
}
const nonElectrical = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: 1, parameterName: "delay_ms"
});
strictAssert.deepEqual(nonElectrical.parameter, { attributes: { min: "0", step: "1" } });
strictAssert.deepEqual(nonElectrical.rating, { max_voltage: 6, max_current: 5 });
strictAssert.equal(nonElectrical.override, null);
const undefinedFields = electrical.resolveInputElectricalConstraint({
  parameterConstraints: { partial: { min: undefined, max: undefined, step: undefined, exclusive_min: undefined, description: undefined } },
  electricalRatingsByModel: {}, modelId: "missing-model", channel: 1, parameterName: "partial"
});
strictAssert.deepEqual(undefinedFields, {
  parameter: { attributes: { step: "any" } }, rating: null, override: null
});

const allChannels = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: "all", parameterName: "voltage"
});
strictAssert.deepEqual(allChannels.rating, { max_voltage: 6, max_current: 1 });
strictAssert.equal(allChannels.override.attributes.max, "6");

const missingParameter = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: 1, parameterName: "missing"
});
strictAssert.deepEqual(missingParameter, {
  parameter: null, rating: { max_voltage: 6, max_current: 5 }, override: null
});
for (const modelId of [null, "", "profile:generic-scpi", "missing-model"]) {
  const result = electrical.resolveInputElectricalConstraint({
    parameterConstraints: constraints, electricalRatingsByModel: ratings,
    modelId, channel: 1, parameterName: "voltage"
  });
  strictAssert.equal(result.rating, null);
  strictAssert.equal(result.override, null);
  strictAssert.equal(result.parameter.attributes.min, "0");
}
for (const electricalRatingsByModel of [undefined, {}, { "model-a": { channels: null } }]) {
  const result = electrical.resolveInputElectricalConstraint({
    parameterConstraints: constraints, electricalRatingsByModel,
    modelId: "model-a", channel: 1, parameterName: "voltage"
  });
  strictAssert.equal(result.rating, null);
  strictAssert.equal(result.override, null);
}
const missingChannel = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: 3, parameterName: "voltage"
});
strictAssert.equal(missingChannel.rating, null);
strictAssert.equal(missingChannel.override, null);

const partial = electrical.resolveInputElectricalConstraint({
  parameterConstraints: constraints,
  electricalRatingsByModel: { "model-a": { channels: [{ channel: 1, max_voltage: 6 }] } },
  modelId: "model-a", channel: 1, parameterName: "current"
});
strictAssert.equal(partial.rating.max_voltage, 6);
strictAssert.equal(Number.isNaN(partial.rating.max_current), true);
strictAssert.equal(partial.override.attributes.max, "NaN");
const request = {
  parameterConstraints: constraints, electricalRatingsByModel: ratings,
  modelId: "model-a", channel: 1, parameterName: "voltage"
};
const requestBefore = JSON.parse(JSON.stringify(request));
const first = electrical.resolveInputElectricalConstraint(request);
const second = electrical.resolveInputElectricalConstraint(request);
strictAssert.notEqual(first, second);
strictAssert.deepEqual({ constraints, ratings }, before);
strictAssert.deepEqual(request, requestBefore);
"""
    run_frontend_javascript_assertions(assertions, source_names=("app-context.js", "app-electrical.js"))


def test_frontend_electrical_helper_preserves_context_and_global_ownership() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const namespace = globalThis.PowersToolWebUI;
const addedGlobalProperties = Reflect.ownKeys(globalThis)
  .filter((name) => !electricalGlobalKeysBefore.has(name));
const addedNamespaceProperties = Reflect.ownKeys(namespace)
  .filter((name) => !electricalNamespaceKeysBefore.has(name));
strictAssert.deepEqual(addedGlobalProperties, []);
strictAssert.deepEqual(addedNamespaceProperties, ["electrical"]);
strictAssert.equal(namespace.context, electricalContextBefore);
strictAssert.deepEqual(Object.getOwnPropertyDescriptor(namespace, "context"), electricalContextDescriptorBefore);
const descriptor = Object.getOwnPropertyDescriptor(namespace, "electrical");
strictAssert.equal(Object.isFrozen(namespace.electrical), true);
strictAssert.equal(descriptor.writable, false);
strictAssert.equal(descriptor.configurable, false);
strictAssert.equal(typeof namespace.electrical.resolveInputElectricalConstraint, "function");
"""
    run_frontend_javascript_assertions(
        assertions,
        source_names=("app-context.js", "app-electrical.js"),
        after_source_assertions={
            "app-context.js": r"""
const electricalGlobalKeysBefore = new Set(Reflect.ownKeys(globalThis));
const electricalNamespaceKeysBefore = new Set(Reflect.ownKeys(globalThis.PowersToolWebUI));
const electricalContextBefore = globalThis.PowersToolWebUI.context;
const electricalContextDescriptorBefore = Object.getOwnPropertyDescriptor(globalThis.PowersToolWebUI, "context");
"""
        },
    )


def test_frontend_electrical_helper_rejects_duplicate_load() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js", "app-electrical.js", "app-electrical.js"),
        expected_failure_substrings=("app-electrical.js", "already initialized"),
    )


@pytest.mark.parametrize("existing_electrical", ("null", "false", "0", '\"\"'))
def test_frontend_electrical_helper_rejects_falsy_existing_property(existing_electrical: str) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-electrical.js",),
        bootstrap=f"globalThis.PowersToolWebUI = {{ context: {{}}, electrical: {existing_electrical} }};",
        expected_failure_substrings=("app-electrical.js", "already initialized"),
    )


@pytest.mark.parametrize("existing_root", ("undefined", "null", "false", "0", '\"\"', '\"incompatible\"', "() => {}"))
def test_frontend_electrical_helper_rejects_incompatible_namespace_root(existing_root: str) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-electrical.js",),
        bootstrap=f"globalThis.PowersToolWebUI = {existing_root};",
        expected_failure_substrings=("app-electrical.js", "namespace must be a usable object"),
    )


def test_frontend_electrical_helper_requires_context_and_extensible_namespace() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-electrical.js",),
        bootstrap="globalThis.PowersToolWebUI = {};",
        expected_failure_substrings=("app-electrical.js", "context must load"),
    )
    run_frontend_javascript_assertions(
        "",
        source_names=("app-electrical.js",),
        bootstrap="globalThis.PowersToolWebUI = Object.freeze({ context: {} });",
        expected_failure_substrings=("app-electrical.js", "cannot define its electrical API"),
    )


def test_frontend_electrical_helper_fails_before_context() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-electrical.js", "app-context.js"),
        expected_failure_substrings=("app-electrical.js", "context must load"),
    )


def test_frontend_app_fails_fast_without_electrical_helper() -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js", "app.js"),
        expected_failure_substrings=("app.js", "PowersToolWebUI.electrical failed to load before app.js"),
    )


@pytest.mark.parametrize("missing, invalid", ((True, False), (False, True)))
def test_frontend_app_fails_fast_for_missing_or_invalid_electrical_api(missing: bool, invalid: bool) -> None:
    run_frontend_javascript_assertions(
        "",
        source_names=("app.js",),
        bootstrap=app_electrical_bootstrap(missing=missing, invalid=invalid),
        expected_failure_substrings=("app.js", "resolveInputElectricalConstraint"),
    )


def test_frontend_classic_scripts_load_context_electrical_then_app() -> None:
    run_frontend_javascript_assertions(
        r"""
const strictAssert = require("node:assert/strict");
strictAssert.equal(typeof globalThis.PowersToolWebUI.context.buildWorkspaceResultKey, "function");
strictAssert.equal(typeof globalThis.PowersToolWebUI.electrical.resolveInputElectricalConstraint, "function");
strictAssert.equal(typeof state, "object");
""",
        source_names=("app-context.js", "app-electrical.js", "app.js"),
    )
    run_frontend_javascript_assertions(
        "",
        source_names=("app-context.js", "app.js", "app-electrical.js"),
        expected_failure_substrings=("app.js", "PowersToolWebUI.electrical failed to load before app.js"),
    )


def test_frontend_rating_guard_remains_unchanged_for_workflow_and_restore_paths() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const identity = { value: "model-a" };
document.getElementById = (id) => id === "expected-model-id" ? identity : null;
state.executionMode = "simulate";
state.physicalModels = [{ model_id: "model-a", display_name: "Model A" }];
state.electricalRatingsByModel = {
  "model-a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }] }
};
const expected = "Voltage 7 exceeds official DC output rating 6 V for Model A channel 1.";
strictAssert.equal(electricalRatingGuardReason("ramp", { channel: 1, start_voltage: 0, stop_voltage: 7, current: 1 }), expected);
state.rampListSegments = [{ channel: 1, start_voltage: 0, stop_voltage: 7, current: 1 }];
strictAssert.equal(electricalRatingGuardReason("ramp-list", {}), expected);
strictAssert.equal(electricalRatingGuardReason("trigger-step", { channel: 1, voltage: 7, current: 1 }), expected);
strictAssert.equal(electricalRatingGuardReason("trigger-list", { channel: 1, voltage_list: [7], current_list: [1] }), expected);
state.sequenceSteps = [{ action: "set", channel: 1, voltage: 7, current: 1 }];
strictAssert.equal(electricalRatingGuardReason("sequence", {}), expected);
state.loadedSnapshotDocument = { readback: [{ channel: 1, setpoints: { voltage: 7, current: 1 } }] };
state.restoreChannel = "all";
strictAssert.equal(electricalRatingGuardReason("restore-from-snapshot", {}), expected);
strictAssert.equal(electricalRatingGuardReason("set", { channel: 1, voltage: 6, current: 5 }), "");
"""
    run_frontend_javascript_assertions(assertions)
