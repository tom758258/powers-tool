"""Pure native ES-module contracts for the WebUI i18n foundation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"
NODE = shutil.which("node")


def test_i18n_modules_use_the_existing_static_root_package_layout() -> None:
    expected = {
        STATIC_DIR / "i18n.js",
        STATIC_DIR / "locale_en.js",
        STATIC_DIR / "locale_zh_tw.js",
    }

    assert all(path.is_file() for path in expected)
    assert not (STATIC_DIR / "locales").exists()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"static/*.js"' in pyproject


@pytest.mark.skipif(NODE is None, reason="Node.js is required for ES-module runtime tests")
def test_i18n_es_module_runtime_contract() -> None:
    script = r"""
import assert from "node:assert/strict";

const [i18nUrl, enUrl, zhTwUrl] = process.argv.slice(1);
const guardedGlobals = [
  "document",
  "window",
  "navigator",
  "localStorage",
  "fetch",
  "XMLHttpRequest",
  "EventSource",
];
const globalAccesses = [];
for (const name of guardedGlobals) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    get() {
      globalAccesses.push(name);
      throw new Error(`unexpected global access: ${name}`);
    },
  });
}

const i18n = await import(i18nUrl);
const enModule = await import(enUrl);
const zhTwModule = await import(zhTwUrl);
const { EN_MESSAGES } = enModule;
const { ZH_TW_MESSAGES } = zhTwModule;

assert.equal(i18n.SOURCE_LOCALE, "en");
assert.equal(i18n.FALLBACK_LOCALE, "en");
assert.deepEqual(i18n.SUPPORTED_LOCALES, ["en", "zh-TW"]);
assert.equal(i18n.LOCALE_STORAGE_KEY, "powers-tool.webui.locale");
assert.equal(Object.isFrozen(i18n.SUPPORTED_LOCALES), true);
assert.equal(Object.isFrozen(EN_MESSAGES), true);
assert.equal(Object.isFrozen(ZH_TW_MESSAGES), true);
assert.equal(enModule.default, EN_MESSAGES);
assert.equal(zhTwModule.default, ZH_TW_MESSAGES);
assert.deepEqual(Object.keys(EN_MESSAGES), []);
assert.deepEqual(Object.keys(EN_MESSAGES), Object.keys(ZH_TW_MESSAGES));

assert.equal(i18n.getLocale(), "en");
assert.equal(i18n.setLocale("zh-TW"), "zh-TW");
assert.equal(i18n.getLocale(), "zh-TW");
assert.throws(() => i18n.setLocale("ZH-tw"), RangeError);
assert.equal(i18n.getLocale(), "zh-TW");
assert.equal(i18n.setLocale("en"), "en");

for (const value of ["en", "zh-TW"]) {
  assert.equal(i18n.isSupportedLocale(value), true);
}
for (const value of ["", "EN", "zh-tw", "zh-Hant", null, undefined, 1, {}]) {
  assert.equal(i18n.isSupportedLocale(value), false);
}

const enCatalog = {
  "test.greeting": "Hello {name}",
  "test.count": "Captured {count} samples; {count} total",
  "test.fallback": "English fallback",
  "test.undefined": "Value {value}",
  "test.literal": "Content {value}",
};
const zhTwCatalog = {
  "test.greeting": "Traditional Chinese {name}",
  "test.count": "Count {count}; repeated {count}",
  "test.undefined": "Value {value}",
  "test.literal": "Literal {value}",
};
const catalogs = { en: enCatalog, "zh-TW": zhTwCatalog };
const before = JSON.stringify(catalogs);
const missing = [];
const translator = i18n.createI18n({
  catalogs,
  initialLocale: "zh-TW",
  onMissingKey(info) {
    missing.push(info);
  },
});

assert.equal(translator.getLocale(), "zh-TW");
assert.equal(translator.t("test.greeting", { name: "Ada" }), "Traditional Chinese Ada");
assert.equal(translator.t("test.fallback"), "English fallback");
assert.equal(translator.t("test.missing"), "test.missing");
assert.equal(translator.t("test.raw", undefined, "backend detail"), "backend detail");
assert.deepEqual(missing, [
  { key: "test.missing", locale: "zh-TW", fallbackLocale: "en" },
  { key: "test.raw", locale: "zh-TW", fallbackLocale: "en" },
]);

assert.equal(
  translator.t("test.count", { count: 3, extra: "ignored" }),
  "Count 3; repeated 3"
);
assert.equal(translator.t("test.greeting", {}), "Traditional Chinese {name}");
assert.equal(translator.t("test.undefined", { value: undefined }), "Value {value}");
const inheritedParams = Object.create({ name: "prototype value" });
assert.equal(translator.t("test.greeting", inheritedParams), "Traditional Chinese {name}");
const html = "<img src=x onerror=alert(1)>";
assert.equal(translator.t("test.literal", { value: html }), `Literal ${html}`);

assert.equal(translator.setLocale("en"), "en");
assert.equal(translator.t("test.greeting", { name: 7 }), "Hello 7");
assert.throws(() => translator.setLocale("fr"), RangeError);
assert.equal(translator.getLocale(), "en");
assert.equal(JSON.stringify(catalogs), before);
assert.equal(Object.isFrozen(enCatalog), false);
assert.equal(Object.isFrozen(zhTwCatalog), false);

const callerOwned = {
  en: { "test.copy": "Original English" },
  "zh-TW": { "test.copy": "Original zh-TW" },
};
const copied = i18n.createI18n({ catalogs: callerOwned, initialLocale: "zh-TW" });
callerOwned.en["test.copy"] = "Changed English";
callerOwned["zh-TW"]["test.copy"] = "Changed zh-TW";
assert.equal(copied.t("test.copy"), "Original zh-TW");
copied.setLocale("en");
assert.equal(copied.t("test.copy"), "Original English");

const second = i18n.createI18n({ catalogs });
assert.equal(second.getLocale(), "en");
assert.equal(second.setLocale("zh-TW"), "zh-TW");
assert.equal(translator.getLocale(), "en");

const callbackFailure = i18n.createI18n({
  catalogs: { en: {}, "zh-TW": {} },
  onMissingKey() { throw new Error("callback failed"); },
});
assert.equal(callbackFailure.t("test.unknown", undefined, "raw detail"), "raw detail");
assert.equal(callbackFailure.t("test.unknown"), "test.unknown");

Object.prototype["test.prototype"] = "inherited message";
try {
  assert.equal(translator.t("test.prototype"), "test.prototype");
} finally {
  delete Object.prototype["test.prototype"];
}

assert.throws(() => i18n.createI18n(), TypeError);
assert.throws(() => i18n.createI18n({ catalogs: [] }), TypeError);
assert.throws(() => i18n.createI18n({ catalogs: { en: {} } }), TypeError);
assert.throws(() => i18n.createI18n({ catalogs: { "zh-TW": {} } }), TypeError);
assert.throws(
  () => i18n.createI18n({ catalogs: { en: [], "zh-TW": {} } }),
  TypeError
);
assert.throws(
  () => i18n.createI18n({ catalogs: { en: { "test.bad": 1 }, "zh-TW": {} } }),
  TypeError
);
for (const key of ["bad", "Test.bad", "test.bad-key", "test..bad", "test.Bad"]) {
  assert.throws(
    () => i18n.createI18n({ catalogs: { en: { [key]: "value" }, "zh-TW": {} } }),
    TypeError
  );
  assert.throws(() => translator.t(key), TypeError);
}
assert.throws(
  () => i18n.createI18n({
    catalogs: { en: {}, "zh-TW": { "test.zh_only": "zh-TW only" } },
  }),
  /test\.zh_only.*zh-TW.*English source catalog/i
);
const englishOnly = i18n.createI18n({
  catalogs: { en: { "test.english_only": "English fallback" }, "zh-TW": {} },
  initialLocale: "zh-TW",
});
assert.equal(englishOnly.t("test.english_only"), "English fallback");
assert.throws(() => i18n.createI18n({ catalogs, initialLocale: "fr" }), RangeError);
assert.throws(() => i18n.createI18n({ catalogs, onMissingKey: true }), TypeError);

assert.deepEqual(globalAccesses, []);
process.stdout.write(JSON.stringify({ ok: true }));
"""
    completed = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "--eval",
            script,
            (STATIC_DIR / "i18n.js").resolve().as_uri(),
            (STATIC_DIR / "locale_en.js").resolve().as_uri(),
            (STATIC_DIR / "locale_zh_tw.js").resolve().as_uri(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, (
        f"Node i18n contract failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout == '{"ok":true}'
