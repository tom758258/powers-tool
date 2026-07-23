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


def test_command_catalog_localizes_presentation_without_changing_ids() -> None:
    run_webui_module_assertions(
        r"""
const i18n = await import(new URL("./i18n.js", moduleUrls["command-catalog.js"]));
const catalog = globalThis.webuiCommandCatalog;
const ids = [...catalog.COMMAND_CATEGORIES];
strictAssert.equal(catalog.commandCategoryLabel("output"), "Output");
strictAssert.equal(catalog.commandDisplayName("output-on", "Output on"), "Output on");
strictAssert.equal(catalog.commandDescription("trigger-fire", "raw"), "Send *TRG to an already armed BUS trigger");
i18n.setLocale("zh-TW");
strictAssert.equal(catalog.commandCategoryLabel("output"), "輸出");
strictAssert.equal(catalog.commandDisplayName("output-on", "Output on"), "開啟輸出");
strictAssert.equal(catalog.commandDescription("trigger-fire", "raw"), "將 *TRG 傳送至已準備的 BUS 觸發");
strictAssert.equal(catalog.commandDisplayName("backend-new-command", "Backend New Command"), "Backend New Command");
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, ids);
i18n.setLocale("en");
""",
        ("command-catalog.js",),
    )
