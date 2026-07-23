"""Direct behavior checks for Live Data sample helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_frontend_live_data_module_preserves_channel_merge_and_normalization() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")

    assert 'from "./live-data.js"' in app_js
    assert "export function createLiveDataController" in live_data_js
    assert 'fetchJson("/api/live"' in live_data_js
    assert "new EventSource" in live_data_js

    run_webui_module_assertions(
        r"""
const live = globalThis.webuiLiveData;
globalThis.document = {
  createElement: (tagName) => ({
    tagName,
    className: "",
    textContent: "",
    children: [],
    attributes: {},
    append(...children) { this.children.push(...children); },
    setAttribute(name, value) { this.attributes[name] = String(value); }
  })
};
const previous = [{ channel: 1, measured_voltage: 1, output_enabled: true }];
const merged = live.mergeLiveChannels([{ channel: 1, measured_voltage: null }], previous, true, [1, 2]);
strictAssert.equal(merged[0].measured_voltage, 1);
strictAssert.equal(merged[0].output_enabled, true);
strictAssert.deepEqual(merged[1], { channel: 2, output_enabled: null, measured_voltage: null, measured_current: null, set_voltage: null, set_current: null, over_voltage_tripped: null, over_current_tripped: null, protection_tripped: null, over_voltage_protection_level: null, over_current_protection_enabled: null });
strictAssert.deepEqual(live.normalizeMeasurements({ data: { channels: [{ channel: 1, measured_voltage: 2, measured_current: 0.1 }] } }), [{ channel: 1, voltage: 2, current: 0.1 }]);
strictAssert.equal(live.liveStateClass("busy"), "state-warning");
const badge = live.protectionBadge("OVP", true);
strictAssert.equal(badge.children[1].textContent, "OVP TRIP");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("live-data.js",),
    )
