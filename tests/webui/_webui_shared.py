"""Shared helpers for WebUI frontend and static-contract tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

WEBUI_COMMAND_NAMES = {
    "clear", "error", "capabilities", "identify",
    "set", "apply", "output-on", "output-off", "safe-off", "cycle-output",
    "ramp", "ramp-list", "smoke-output", "protection-set", "clear-protection", "trigger-pulse",
    "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort",
    "sequence", "snapshot", "restore-from-snapshot",
}

WEBUI_HIDDEN_UNSUPPORTED_COMMANDS = {
    "doctor", "validate-readonly", "log", "snapshot-diff", "hardware-report",
}

WEBUI_HIDDEN_LIVE_DATA_COMMANDS = {
    "measure", "measure-all", "read-status", "protection-status", "output-state",
}

WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS = {"verify", "readback", "safety inspect"}

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"


def read_static_texts() -> tuple[str, str, str]:
    return (
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        (STATIC_DIR / "app.js").read_text(encoding="utf-8"),
        (STATIC_DIR / "styles.css").read_text(encoding="utf-8"),
    )


def simulated_e36312a_runtime() -> dict[str, Any]:
    return {
        "resource": "USB0::SIM::E36312A::INSTR",
        "simulate": True,
        "timeout_ms": 5000,
        "confirm": False,
    }


def static_tag_with_id(html: str, element_id: str) -> str:
    match = re.search(rf"<[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>", html)
    if not match:
        raise AssertionError(f'Missing element id="{element_id}"')
    return match.group(0)


def assert_static_id(html: str, element_id: str) -> None:
    static_tag_with_id(html, element_id)


def assert_static_attr(html: str, element_id: str, attr: str, value: str | None = None) -> None:
    tag = static_tag_with_id(html, element_id)
    if value is None:
        assert re.search(rf"\b{re.escape(attr)}(?:\s|=|>|$)", tag), tag
    else:
        assert re.search(rf"\b{re.escape(attr)}=\"{re.escape(value)}\"", tag), tag


def extract_param_block(app_js: str, command_name: str) -> str:
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function baseOutputParams()")]
    match = re.search(rf'(?m)^\s*(?:"{re.escape(command_name)}"|{re.escape(command_name)}):', params_block)
    if not match:
        raise AssertionError(f"Missing PARAMS entry for {command_name}")
    start = match.start()
    next_match = re.search(r'(?m)^\s*(?:"[^"]+"|[A-Za-z_$][\w$-]*):', params_block[match.end():])
    end = match.end() + next_match.start() if next_match else len(params_block)
    return params_block[start:end]


def assert_param_contract(
    block: str,
    name: str,
    type_: str | None = None,
    options: list[str] | None = None,
) -> None:
    assert f'name: "{name}"' in block
    if type_ is not None:
        assert f'type: "{type_}"' in block
    if options is not None:
        quoted = ", ".join(f'"{option}"' for option in options)
        assert f"options: [{quoted}]" in block


def extract_js_function(app_js: str, function_name: str) -> str:
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(function_name)}\s*\(",
        app_js,
    )
    if not match:
        raise AssertionError(f"Missing function {function_name}")
    parameter_depth = 1
    index = match.end()
    while index < len(app_js):
        if app_js[index] == "(":
            parameter_depth += 1
        elif app_js[index] == ")":
            parameter_depth -= 1
            if parameter_depth == 0:
                break
        index += 1
    if parameter_depth != 0:
        raise AssertionError(f"Could not parse signature for {function_name}")
    brace = app_js.index("{", index)
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = brace
    while index < len(app_js):
        char = app_js[index]
        next_char = app_js[index + 1] if index + 1 < len(app_js) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue

        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return app_js[match.start():index + 1]
        index += 1
    raise AssertionError(f"Could not extract function {function_name}")


def run_frontend_javascript_assertions(assertions: str) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for WebUI JavaScript behavior tests."
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    bootstrap = """
globalThis.window = {};
globalThis.document = {
  addEventListener() {},
  getElementById() { return { value: "" }; }
};
"""
    completed = subprocess.run(
        [node, "--input-type=commonjs"],
        input=f"{bootstrap}\n{app_js}\n{assertions}",
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
