"""Native-module contracts for Device/Resource presentation helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_device_resource_module_owns_controller_and_app_imports_it() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    device_js = read_static_javascript("device-resource.js")

    assert 'from "./device-resource.js"' in app_js
    assert "export function createDeviceResourceController" in device_js
    assert 'document.getElementById("device-options-panel")' in device_js
    assert "fetch(" not in device_js
    assert "new EventSource" not in device_js


def test_device_module_preserves_resource_and_identity_presentation() -> None:
    run_webui_module_assertions(
        r"""
const device = globalThis.webuiDevice;
const models = [{ model_id: "keysight-e36312a", display_name: "Keysight E36312A" }];
strictAssert.equal(device.physicalModelDisplayName(models, "keysight-e36312a"), "Keysight E36312A");
strictAssert.equal(device.physicalModelDisplayName(models, ""), "Unknown model");
strictAssert.equal(device.planningIdentitySummary({ executionMode: "simulate", planningProfiles: {}, physicalModels: models }, ""), "Planning model: not selected");
strictAssert.equal(device.planningIdentitySummary({ executionMode: "dry-run", planningProfiles: { generic: { display_name: "Generic SCPI" } }, physicalModels: models }, "profile:generic"), "Planning profile: Generic SCPI");
strictAssert.equal(device.liveResourceSummary({}, "USB0::A", { value: "USB0::A", options: [] }), "live selected");
strictAssert.equal(device.liveResourceSummary({}, "USB0::A", { value: "", options: [{ textContent: "No live resources found" }] }), "no live resources");
strictAssert.equal(device.resourceLabel({ idn: { manufacturer: "Keysight", model: "E36312A" } }, "USB0::A"), "USB0::A - Keysight - E36312A");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("device-resource.js",),
    )


def test_device_controller_native_module_owns_state_and_e3646a_constants() -> None:
    run_webui_module_assertions(
        r"""
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set(["state-warning"]);
    elements.set(id, {
      id,
      title: "",
      textContent: "",
      children: [],
      classList: {
        add(name) { classes.add(name); },
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
        contains(name) { return classes.has(name); }
      },
      querySelector(selector) { return this.children.find((child) => child.selector === selector) || null; },
      append(...children) { this.children.push(...children); }
    });
  }
  return elements.get(id);
}
globalThis.document = {
  getElementById: element,
  createElement() {
    return {
      selector: "",
      className: "",
      textContent: "",
      setAttribute() {},
      set className(value) { this._className = value; this.selector = value === "state-dot" ? ".state-dot" : value === "state-text" ? ".state-text" : ""; },
      get className() { return this._className; }
    };
  }
};
const state = {
  executionMode: "simulate",
  planningIdentityCache: { simulate: "keysight-e3646a", "dry-run": "" },
  realIdentityCache: { expectedModelId: "" },
  resourceModels: {},
  resourceChannelModels: {},
  physicalModels: [],
  channelCapabilitiesByModel: {},
  jobs: [],
  basicActionStates: {},
  workflowControl: { phase: "idle" }
};
const capability = { output_control_scope: "global", channels: [1, 2] };
const controller = webuiDevice.createDeviceResourceController({
  state,
  devicePresentation: webuiDevice,
  executionContext: { isNoHardwareExecutionMode: (mode) => mode !== "real" },
  valueOrNull: (id) => id === "expected-model-id" ? state.planningIdentityCache.simulate : null,
  channelCapabilityForModel: (model) => model === "keysight-e3646a" ? capability : null
});
controller.setStateIndicator("status", "Ready", "state-ok", "Ready title");
const indicator = element("status");
strictAssert.equal(indicator.classList.contains("state-ok"), true);
strictAssert.equal(indicator.classList.contains("state-warning"), false);
strictAssert.equal(indicator.querySelector(".state-text").textContent, "Ready");
strictAssert.equal(indicator.title, "Ready title");
strictAssert.deepEqual(controller.e3646aGlobalOutputCapability(), capability);
strictAssert.equal(controller.basicOutputPresentation().mode, "e3646a-global");
state.planningIdentityCache.simulate = "keysight-e36312a";
strictAssert.deepEqual(controller.basicOutputPresentation(), { mode: "ordinary", capability: null });
""",
        ("device-resource.js",),
    )


def test_controller_wiring_omits_self_forwarders_and_ignored_properties() -> None:
    app_js = read_static_javascript("app.js")
    device_js = read_static_javascript("device-resource.js")
    command_form_js = read_static_javascript("command-form.js")
    device_wiring = app_js[
        app_js.index("createDeviceResourceController({"):app_js.index("});", app_js.index("createDeviceResourceController({"))
    ]
    command_wiring = app_js[
        app_js.index("createCommandController({"):app_js.index("});", app_js.index("createCommandController({"))
    ]

    for removed in (
        "stateClassNames:",
        "e3646aModelId:",
        "refreshDeviceResourceSummary:",
        "stopLiveJobsBeforeModeChange:",
    ):
        assert removed not in device_wiring

    for removed in (
        "refreshBasicInputConstraintsForForm:",
        "refreshBasicInputConstraints: (...args) => refreshBasicInputConstraints(...args)",
        "commandDisplayName: (...args) => commandDisplayName(...args)",
        "applyParameterConstraintForForm:",
        "applyElectricalRatingConstraintForForm:",
        "enforcePulseFormRulesForForm:",
        "refreshElectricalRatingConstraintsForForm:",
        "renderCurrentForm:",
    ):
        assert removed not in command_wiring

    assert "refreshDeviceResourceSummary," not in device_js
    assert "stopLiveJobsBeforeModeChange," not in device_js
    assert "updateDeviceResourceSummary();" in device_js
    assert "await stopRealLiveJobsAndWait();" in device_js
    assert "refreshBasicInputConstraintsForForm," not in command_form_js
    assert "renderCurrentForm," not in command_form_js
    assert "renderForm(\"ramp-list\");" in command_form_js
    assert "triggerCommands: TRIGGER_COMMANDS" in app_js
    assert "TRIGGER_COMMANDS.has(command)" in command_form_js
    assert all(
        f"{name}:" not in device_wiring + command_wiring
        for name in ("services", "dependencies", "context", "container", "registry", "controllerBag", "callbacks")
    )
