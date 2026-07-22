"""Native ES-module smoke tests for the WebUI application graph."""

from __future__ import annotations

import shutil
import subprocess

from _webui_shared import STATIC_DIR


def test_app_js_native_module_graph_imports() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the WebUI native module graph smoke test."
    app_url = (STATIC_DIR / "app.js").resolve().as_uri()
    runner = f"""
import {{ strict as strictAssert }} from "node:assert";
const listeners = [];
let networkRequests = 0;
globalThis.window = {{}};
globalThis.document = {{
  addEventListener(type, listener) {{ listeners.push({{ type, listener }}); }}
}};
globalThis.fetch = () => {{
  networkRequests += 1;
  throw new Error("app.js native import must not perform network I/O");
}};
await import({app_url!r});
strictAssert.equal(listeners.filter((entry) => entry.type === "DOMContentLoaded").length, 1);
strictAssert.equal(networkRequests, 0);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
"""
    completed = subprocess.run(
        [node, "--input-type=module"],
        input=runner,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    diagnostics = completed.stderr or completed.stdout
    assert completed.returncode == 0, diagnostics
