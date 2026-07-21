"""Native-module contracts for WebUI command categories."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_command_catalog_module_is_explicit_and_pure() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    catalog_js = read_static_javascript("command-catalog.js")

    assert 'from "./command-catalog.js"' in app_js
    assert "document" not in catalog_js
    assert "fetch(" not in catalog_js
    assert "EventSource" not in catalog_js


def test_command_catalog_preserves_category_order_and_labels() -> None:
    run_webui_module_assertions(
        r"""
const catalog = globalThis.webuiCommandCatalog;
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, ["output", "workflow", "protection", "trigger", "artifact", "discovery"]);
strictAssert.deepEqual(catalog.COMMAND_CATEGORY_LABELS, {
  output: "Output", workflow: "Output Workflows", protection: "Protection",
  trigger: "Trigger", artifact: "Snapshot", discovery: "Advanced Diagnostics"
});
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-catalog.js",),
    )
