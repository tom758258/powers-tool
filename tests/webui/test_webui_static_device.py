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
