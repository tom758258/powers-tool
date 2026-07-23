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
strictAssert.equal(catalog.commandSourceDisplayName("output-on", "Output on"), "Output on");
strictAssert.equal(catalog.commandDescription("trigger-fire", "raw"), "Send *TRG to an already armed BUS trigger");
i18n.setLocale("zh-TW");
strictAssert.equal(catalog.commandCategoryLabel("output"), "輸出");
strictAssert.equal(catalog.commandDisplayName("output-on", "Output on"), "開啟輸出");
strictAssert.equal(catalog.commandDescription("trigger-fire", "raw"), "將 *TRG 傳送至已準備的 BUS 觸發");
strictAssert.equal(catalog.commandDisplayName("backend-new-command", "Backend New Command"), "Backend New Command");
strictAssert.equal(catalog.commandSourceDisplayName("output-on", "Output on"), "Output on");
strictAssert.equal(i18n.getLocale(), "zh-TW");
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, ids);
i18n.setLocale("en");
""",
        ("command-catalog.js",),
    )


def test_command_controller_uses_english_source_order_across_locales() -> None:
    run_webui_module_assertions(
        r"""
const i18n = await import(new URL("./i18n.js", moduleUrls["command-catalog.js"]));
class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.className = "";
    this.disabled = false;
    this.dataset = {};
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  querySelectorAll() { return []; }
  set innerHTML(value) {
    strictAssert.equal(value, "");
    this.children = [];
  }
}
const elements = new Map([
  ["command-filter", new FakeElement("input")],
  ["command-categories", new FakeElement()],
  ["command-list", new FakeElement()],
  ["selected-command", new FakeElement()],
  ["command-form", new FakeElement("form")],
]);
globalThis.document = {
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: (id) => elements.get(id),
};
const workflowIds = ["smoke-output", "sequence", "ramp-list", "cycle-output", "ramp"];
const state = {
  selected: "ramp-list",
  activeCategory: "workflow",
  commands: Object.fromEntries(workflowIds.map((id) => [id, { category: "workflow" }])),
  workflowControl: { phase: "idle" },
};
const catalog = globalThis.webuiCommandCatalog;
const dependencies = {
  state,
  commandCatalog: catalog,
  commandMeta: (name) => state.commands[name] || {},
};
const controller = globalThis.webuiCommandForm.createCommandController(dependencies);
const commandIds = () => elements.get("command-list").children.map(
  (button) => workflowIds.find((id) => button.children[0].textContent === catalog.commandDisplayName(id))
);
const commandLabels = () => elements.get("command-list").children.map((button) => button.children[0].textContent);
const expectedIds = ["cycle-output", "ramp", "ramp-list", "sequence", "smoke-output"];

i18n.setLocale("en");
controller.renderCommands();
strictAssert.deepEqual(commandIds(), expectedIds);
strictAssert.deepEqual(commandLabels(), ["Cycle output", "Ramp", "Ramp list", "Sequence", "Smoke output"]);
const categoryIds = [...catalog.COMMAND_CATEGORIES];

const form = elements.get("command-form");
const formDraft = new FakeElement("input");
formDraft.value = "preserved draft";
form.appendChild(formDraft);
const formIdentity = form.children[0];
i18n.setLocale("zh-TW");
controller.refreshCommandPresentation();
strictAssert.deepEqual(commandIds(), expectedIds);
strictAssert.ok(commandLabels().every((label) => /[^\x00-\x7f]/.test(label)));
strictAssert.equal(state.selected, "ramp-list");
strictAssert.equal(state.activeCategory, "workflow");
strictAssert.equal(form.children[0], formIdentity);
strictAssert.equal(form.children[0].value, "preserved draft");
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, categoryIds);
strictAssert.deepEqual(
  elements.get("command-categories").children.map((button) => button.textContent),
  categoryIds.map((category) => catalog.commandCategoryLabel(category)),
);

elements.get("command-filter").value = "smoke-output";
controller.renderCommands();
strictAssert.deepEqual(commandIds(), ["smoke-output"]);
elements.get("command-filter").value = catalog.commandDisplayName("ramp-list").toLowerCase();
controller.renderCommands();
strictAssert.deepEqual(commandIds(), ["ramp-list"]);

state.commands = {
  "tie-b": { category: "workflow" },
  "tie-a": { category: "workflow" },
};
elements.get("command-filter").value = "";
const tieController = globalThis.webuiCommandForm.createCommandController({
  ...dependencies,
  commandCatalog: { ...catalog, commandSourceDisplayName: () => "Same English name" },
});
tieController.renderCommands();
strictAssert.deepEqual(
  elements.get("command-list").children.map((button) => button.children[0].textContent),
  [catalog.commandDisplayName("tie-a", "Tie a"), catalog.commandDisplayName("tie-b", "Tie b")],
);
i18n.setLocale("en");
""",
        ("command-catalog.js", "command-form.js"),
    )
