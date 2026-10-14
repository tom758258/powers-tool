"""Classify changed paths for conditional Windows CI without guessing safe skips."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys

VALIDATION = (
    "src/powers_tool_core/**", "src/powers_tool_cli/**", "src/powers_tool_webui/**",
    "desktop/**", "scripts/preflight-cli.ps1", "scripts/live-cli-check.ps1",
    "scripts/_validation_helpers.ps1", "scripts/batch-validation.ps1",
    "scripts/e36312a_trigger_validation.py", "scripts/release-acceptance.ps1",
    "scripts/build_windows_bundle.ps1", "scripts/build_desktop.ps1",
    "scripts/build_release.ps1", "scripts/powers-tool-windows.spec",
    "scripts/ci_change_detection.py", "scripts/ci_packaging_smoke.py",
    "tests/cli/test_cli_wrappers.py", "tests/cli/test_live_cli_check_script.py",
    "tests/packaging/test_release_acceptance.py",
    "tests/tooling/test_ci_change_detection.py", "tests/tooling/test_changed_whitespace.py",
    "pyproject.toml", "uv.lock", ".github/workflows/tests.yml",
    ".github/workflows/build-windows.yml",
)
PACKAGING = (
    "src/powers_tool_core/**", "src/powers_tool_cli/**", "src/powers_tool_webui/**",
    "desktop/**", "scripts/build_windows_bundle.ps1", "scripts/build_desktop.ps1",
    "scripts/build_release.ps1", "scripts/powers-tool-windows.spec",
    "scripts/ci_change_detection.py", "scripts/ci_packaging_smoke.py",
    "tests/tooling/test_ci_change_detection.py", "tests/packaging/inspect_*.py",
    "tests/packaging/_inspector_utils.py", "pyproject.toml", "uv.lock",
    ".github/workflows/tests.yml", ".github/workflows/build-windows.yml",
    "docs/help/**", "scripts/generate_help.py",
)
RELEASE_LAYOUT = (
    "desktop/package.json", "desktop/package-lock.json", "scripts/build_release.ps1",
    "scripts/ci_change_detection.py", "scripts/ci_packaging_smoke.py",
    "tests/tooling/test_ci_change_detection.py", "pyproject.toml", "uv.lock",
    ".github/workflows/tests.yml", ".github/workflows/build-windows.yml",
)

def classify_paths(paths: set[str]) -> dict[str, bool]:
    result = {
        "validation": any(fnmatch.fnmatchcase(path, pat) for path in paths for pat in VALIDATION),
        "packaging": any(fnmatch.fnmatchcase(path, pat) for path in paths for pat in PACKAGING),
        "release-layout": any(fnmatch.fnmatchcase(path, pat) for path in paths for pat in RELEASE_LAYOUT),
    }
    if result["release-layout"]:
        result["packaging"] = True
    return result

def git(*args: str) -> str:
    process = subprocess.run(["git", *args], capture_output=True, check=False)
    if process.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {process.stderr.decode(errors='replace')}")
    return process.stdout.decode("utf-8", errors="strict").strip()

def revision(sha: str) -> str:
    if not sha or re.fullmatch("0+", sha):
        raise RuntimeError("Missing or zero commit SHA")
    return git("rev-parse", "--verify", f"{sha}^{{commit}}")

def changed_files() -> set[str] | None:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "pull_request":
        head = revision(os.environ.get("PR_HEAD_SHA", ""))
        base = revision(os.environ.get("PR_BASE_SHA", ""))
        old = revision(git("merge-base", base, head))
    elif event == "push":
        head = revision(os.environ.get("GITHUB_SHA", ""))
        before = os.environ.get("PUSH_BEFORE", "")
        if not before or re.fullmatch("0+", before):
            return None
        old = revision(before)
    elif event == "workflow_dispatch":
        revision(os.environ.get("GITHUB_SHA", ""))
        return None
    else:
        raise RuntimeError(f"Unsupported event: {event!r}")

    proc = subprocess.run(
        ["git", "diff", "--name-status", "--find-renames", "-z", old, head],
        capture_output=True, check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"Could not diff commits: {proc.stderr.decode(errors='replace')}")
    fields = proc.stdout.decode("utf-8", errors="strict").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    paths: set[str] = set()
    cursor = 0
    while cursor < len(fields):
        status = fields[cursor]
        cursor += 1
        count = 2 if status.startswith(("R", "C")) else 1
        if not status or status[0] not in "ACDMRTUXB" or cursor + count > len(fields):
            raise RuntimeError(f"Unknown git diff status: {status!r}")
        paths.update(fields[cursor:cursor + count])
        cursor += count
    return paths

def main() -> int:
    try:
        paths = changed_files()
        filters = (
            classify_paths(paths) if paths is not None
            else {"validation": True, "packaging": True, "release-layout": True}
        )
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(f"::error::Unable to establish trusted changed range: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"paths": sorted(paths) if paths is not None else "all", "filters": filters}))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            for key, enabled in filters.items():
                stream.write(f"{key}={'true' if enabled else 'false'}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
