"""Direct behavior checks for Restore document helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_restore_document_module_is_pure_and_preserves_restore_contract() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    restore_document_js = read_static_javascript("snapshot-restore.js")

    assert 'from "./snapshot-restore.js"' in app_js
    assert "getElementById" not in restore_document_js
    assert "createElement" not in restore_document_js
    assert "querySelector" not in restore_document_js
    assert "fetch(" not in restore_document_js
    assert "EventSource" not in restore_document_js

    run_webui_module_assertions(
        r"""
const restore = globalThis.webuiRestoreDocument;
const valid = { schema_version: 2, kind: "powers-tool-snapshot", reported_identity: { model: "E36312A" }, resolved_identity: { model_id: "keysight-e36312a" }, readback: [{ channel: 1, setpoints: { voltage: 1, current: 0.1 } }], outputs: [{ channel: 1, enabled: false }] };
strictAssert.equal(restore.validateRestoreSnapshot(valid), undefined);
strictAssert.deepEqual(restore.restoreSnapshotParameters(valid, "2", true, Number), { document: valid, channel: 2, restore_output_state: true });
strictAssert.equal(restore.normalizeRestoreChannel("all", Number), "all");
strictAssert.throws(() => restore.validateRestoreSnapshot({ ...valid, readback: [...valid.readback, valid.readback[0]] }), /duplicate channel/);
strictAssert.throws(() => restore.validateRestoreSnapshot({ ...valid, resolved_identity: { model_id: "keysight-e3646a" } }), /not supported/);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("snapshot-restore.js", "snapshot-restore.js"),
    )
