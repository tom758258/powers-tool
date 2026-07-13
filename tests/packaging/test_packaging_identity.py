from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

try:  # pragma: no cover - branch depends on Python version
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]

LEGACY_IDENTITY_TOKENS = (
    "keysight-powers",  # stale-name-audit-data
    "keysight-power",  # stale-name-audit-data
    "keysight_power_core",  # stale-name-audit-data
    "keysight_power_cli",  # stale-name-audit-data
    "keysight_power_webui",  # stale-name-audit-data
    "Keysight Powers",  # stale-name-audit-data
    "Keysight Power",  # stale-name-audit-data
    "Keysight Power contributors",  # stale-name-audit-data
    "keysight-power-ramp-list",  # stale-name-audit-data
    "model_profile",  # stale-name-audit-data
)

# Every retained occurrence is tied to one exact tracked file, token, count, and
# reason. Count drift fails so a future occurrence cannot inherit an exemption.
_ALLOWED_LEGACY_MATCHES = {
    ("CHANGELOG.md", LEGACY_IDENTITY_TOKENS[0]): (2, "V2 migration and immutable V1 history"),
    ("CHANGELOG.md", LEGACY_IDENTITY_TOKENS[1]): (3, "V2 migration and immutable V1 history"),
    ("CHANGELOG.md", LEGACY_IDENTITY_TOKENS[5]): (1, "V2 product rename history"),
    ("CHANGELOG.md", LEGACY_IDENTITY_TOKENS[6]): (1, "V2 product rename history"),
    ("README.md", LEGACY_IDENTITY_TOKENS[5]): (1, "concise V2 product history"),
    ("README.md", LEGACY_IDENTITY_TOKENS[6]): (1, "concise V2 product history"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[0]): (1, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[1]): (5, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[2]): (2, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[3]): (2, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[4]): (2, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[5]): (1, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[6]): (2, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[7]): (1, "V2 migration mapping"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[8]): (1, "V2 schema migration"),
    ("docs/migration-v2.md", LEGACY_IDENTITY_TOKENS[9]): (1, "V2 field migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[0]): (2, "P6 localized-doc migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[1]): (13, "P6 localized-doc migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[2]): (3, "P6 localized-doc migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[3]): (3, "P6 localized-doc migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[4]): (3, "P6 localized-doc migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[5]): (2, "P6 localized-doc migration"),
    ("README.zh-TW.md", LEGACY_IDENTITY_TOKENS[6]): (2, "P6 localized-doc migration"),
    ("docs/cli/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[1]): (39, "P6 localized-doc migration"),
    ("docs/cli/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[6]): (1, "P6 localized-doc migration"),
    ("docs/cli/USER_GUIDE.zh-TW.md", LEGACY_IDENTITY_TOKENS[1]): (29, "P6 localized-doc migration"),
    ("docs/cli/USER_GUIDE.zh-TW.md", LEGACY_IDENTITY_TOKENS[6]): (1, "P6 localized-doc migration"),
    ("docs/cli/USER_GUIDE.zh-TW.html", LEGACY_IDENTITY_TOKENS[1]): (29, "P6 generated localized-doc migration"),
    ("docs/cli/USER_GUIDE.zh-TW.html", LEGACY_IDENTITY_TOKENS[6]): (2, "P6 generated localized-doc migration"),
    ("docs/core/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[0]): (2, "P6 localized-doc migration"),
    ("docs/core/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[1]): (3, "P6 localized-doc migration"),
    ("docs/core/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[2]): (16, "P6 localized-doc migration"),
    ("docs/core/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[6]): (1, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[0]): (3, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[1]): (10, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[2]): (3, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[3]): (1, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[4]): (7, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.md", LEGACY_IDENTITY_TOKENS[6]): (3, "P6 localized-doc migration"),
    ("docs/webui/README.zh-TW.html", LEGACY_IDENTITY_TOKENS[0]): (3, "P6 generated localized-doc migration"),
    ("docs/webui/README.zh-TW.html", LEGACY_IDENTITY_TOKENS[1]): (10, "P6 generated localized-doc migration"),
    ("docs/webui/README.zh-TW.html", LEGACY_IDENTITY_TOKENS[2]): (3, "P6 generated localized-doc migration"),
    ("docs/webui/README.zh-TW.html", LEGACY_IDENTITY_TOKENS[3]): (1, "P6 generated localized-doc migration"),
    ("docs/webui/README.zh-TW.html", LEGACY_IDENTITY_TOKENS[4]): (7, "P6 generated localized-doc migration"),
    ("docs/webui/README.zh-TW.html", LEGACY_IDENTITY_TOKENS[6]): (4, "P6 generated localized-doc migration"),
    ("docs/webui/USER_GUIDE.zh-TW.md", LEGACY_IDENTITY_TOKENS[1]): (3, "P6 localized-doc migration"),
    ("docs/webui/USER_GUIDE.zh-TW.md", LEGACY_IDENTITY_TOKENS[6]): (2, "P6 localized-doc migration"),
    ("docs/webui/USER_GUIDE.zh-TW.html", LEGACY_IDENTITY_TOKENS[1]): (3, "P6 generated localized-doc migration"),
    ("docs/webui/USER_GUIDE.zh-TW.html", LEGACY_IDENTITY_TOKENS[6]): (3, "P6 generated localized-doc migration"),
    ("docs/contracts/power-worker-contract.md", LEGACY_IDENTITY_TOKENS[9]): (1, "explicit removed-field contract"),
    ("docs/webui/README.md", LEGACY_IDENTITY_TOKENS[9]): (1, "explicit removed-field contract"),
    ("src/powers_tool_cli/worker.py", LEGACY_IDENTITY_TOKENS[9]): (1, "explicit legacy-field rejection"),
    ("src/powers_tool_webui/app.py", LEGACY_IDENTITY_TOKENS[9]): (1, "explicit legacy-field rejection"),
    ("tests/cli/test_cli_model_profile.py", LEGACY_IDENTITY_TOKENS[1]): (1, "negative legacy-entry-point regression"),  # stale-name-audit-data
    ("tests/cli/test_live_cli_check_script.py", LEGACY_IDENTITY_TOKENS[3]): (1, "negative legacy-import regression"),
    ("tests/cli/test_supported_models_docs.py", LEGACY_IDENTITY_TOKENS[9]): (1, "legacy-removal regression name"),
    ("tests/cli/test_worker.py", LEGACY_IDENTITY_TOKENS[9]): (2, "negative legacy-field regressions"),
    ("tests/core/test_runtime_identity.py", LEGACY_IDENTITY_TOKENS[9]): (1, "negative legacy-field regression"),
    ("tests/core/test_ramp_list_core.py", LEGACY_IDENTITY_TOKENS[1]): (1, "negative legacy Ramp List kind regression"),
    ("tests/core/test_ramp_list_core.py", LEGACY_IDENTITY_TOKENS[8]): (1, "negative legacy Ramp List kind regression"),
    ("tests/packaging/inspect_distribution.py", LEGACY_IDENTITY_TOKENS[1]): (1, "negative legacy-entry-point inspection"),
    ("tests/packaging/inspect_distribution.py", LEGACY_IDENTITY_TOKENS[2]): (1, "negative legacy-package inspection"),
    ("tests/packaging/inspect_distribution.py", LEGACY_IDENTITY_TOKENS[3]): (1, "negative legacy-package inspection"),
    ("tests/packaging/inspect_distribution.py", LEGACY_IDENTITY_TOKENS[4]): (1, "negative legacy-package inspection"),
    ("scripts/v2-release-acceptance.ps1", LEGACY_IDENTITY_TOKENS[1]): (3, "negative installed-command checks"),
    ("scripts/v2-release-acceptance.ps1", LEGACY_IDENTITY_TOKENS[2]): (1, "negative legacy-import check"),
    ("scripts/v2-release-acceptance.ps1", LEGACY_IDENTITY_TOKENS[3]): (1, "negative legacy-import check"),
    ("scripts/v2-release-acceptance.ps1", LEGACY_IDENTITY_TOKENS[4]): (1, "negative legacy-import check"),
    ("tests/packaging/inspect_pyinstaller.py", LEGACY_IDENTITY_TOKENS[0]): (1, "negative legacy-metadata inspection"),
    ("tests/packaging/inspect_pyinstaller.py", LEGACY_IDENTITY_TOKENS[1]): (1, "negative legacy-metadata inspection"),
    ("tests/webui/test_webui.py", LEGACY_IDENTITY_TOKENS[1]): (1, "negative legacy Ramp List kind regression"),
    ("tests/webui/test_webui.py", LEGACY_IDENTITY_TOKENS[8]): (1, "negative legacy Ramp List kind regression"),
    ("tests/webui/test_webui.py", LEGACY_IDENTITY_TOKENS[9]): (5, "negative legacy-field regressions"),
}

_SELF_ALLOWLIST_MARKER = "stale-name-audit-data"


def test_pyproject_uses_only_v2_distribution_packages_and_scripts() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "powers-tool"
    assert data["project"]["scripts"] == {
        "powers-tool": "powers_tool_cli.cli:main",
        "powers-tool-webui": "powers_tool_webui.server:main",
        "powers-tool-webui-launcher": "powers_tool_webui.launcher:main",
    }
    assert data["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "powers_tool_core*",
        "powers_tool_cli*",
        "powers_tool_webui*",
    ]
    assert set(data["tool"]["setuptools"]["package-data"]) == {"powers_tool_webui"}


def test_old_python_packages_are_absent() -> None:
    for package in LEGACY_IDENTITY_TOKENS[2:5]:
        assert not (ROOT / "src" / package).exists()
        assert importlib.util.find_spec(package) is None


def test_build_scripts_use_v2_names_and_preserve_path_guards() -> None:
    cli = (ROOT / "scripts" / "build_cli_exe.ps1").read_text(encoding="utf-8")
    webui = (ROOT / "scripts" / "build_webui_exe.ps1").read_text(encoding="utf-8")

    assert '[string]$Name = "powers-tool"' in cli
    assert "src\\powers_tool_cli\\cli.py" in cli
    assert '[string]$Name = "powers-tool-webui"' in webui
    assert "src\\powers_tool_webui\\launcher.py" in webui
    assert "src\\powers_tool_webui\\static');powers_tool_webui\\static" in webui
    for script in (cli, webui):
        assert "--copy-metadata powers-tool" in script
        assert "DistPath must stay under the repository" in script
        assert "StartsWith($repoPrefix" in script
        assert "src\\keysight_power_" not in script

    release = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
    assert '-Name "powers-tool-webui-$Version"' in release
    assert '-Name "powers-tool-webui-launcher-$Version"' not in release


def test_ci_uses_v2_distribution_and_console_commands() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert "--reinstall-package powers-tool" in workflow
    assert "uv run powers-tool --help" in workflow
    assert "uv run powers-tool-webui --help" in workflow
    assert "uv run powers-tool-webui-launcher --version" in workflow
    assert "inspect_distribution.py dist" in workflow
    assert f"--reinstall-package {LEGACY_IDENTITY_TOKENS[0]}" not in workflow


def test_active_runtime_identity_is_vendor_neutral_and_has_no_stale_fallback() -> None:
    paths = (
        ROOT / "src" / "powers_tool_core" / "__init__.py",
        ROOT / "src" / "powers_tool_cli" / "__init__.py",
        ROOT / "src" / "powers_tool_webui" / "__init__.py",
        ROOT / "src" / "powers_tool_cli" / "cli.py",
    )
    stale_phrases = (
        "Tools for controlling " + "Keysight DC power supplies safely.",
        "CLI adapter for controlling " + "Keysight DC power supplies.",
        "WebUI adapter for " + "Keysight DC power supplies.",
        "Safe Powers Tool CLI for " + "Keysight DC power supplies.",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "1.0.0" not in text
        for phrase in stale_phrases:
            assert phrase not in text


def _tracked_utf8_text() -> dict[str, str]:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    texts: dict[str, str] = {}
    intended_untracked_paths = (
        "docs/migration-v2.md",
        "scripts/v2-release-acceptance.ps1",
        "tests/packaging/inspect_pyinstaller.py",
        "tests/packaging/test_v2_release_acceptance.py",
    )
    for relative in intended_untracked_paths:
        if relative not in tracked and (ROOT / relative).exists():
            tracked.append(relative)
    for relative in tracked:
        if not relative:
            continue
        raw = (ROOT / relative).read_bytes()
        if b"\0" in raw:
            continue
        try:
            texts[relative] = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return texts


def _unexpected_legacy_matches(texts: dict[str, str]) -> list[str]:
    matches: dict[tuple[str, str], list[tuple[int, int]]] = {}
    self_path = "tests/packaging/test_packaging_identity.py"
    for relative, text in texts.items():
        for line_number, line in enumerate(text.splitlines(), start=1):
            for token in LEGACY_IDENTITY_TOKENS:
                start = 0
                while (column := line.find(token, start)) >= 0:
                    if not (relative == self_path and _SELF_ALLOWLIST_MARKER in line):
                        matches.setdefault((relative, token), []).append(
                            (line_number, column + 1)
                        )
                    start = column + 1

    findings: list[str] = []
    for key, locations in sorted(matches.items()):
        allowed = _ALLOWED_LEGACY_MATCHES.get(key)
        if allowed is None:
            for line_number, column in locations:
                findings.append(f"{key[0]}:{line_number}:{column}: {key[1]!r}")
            continue
        expected_count, reason = allowed
        if len(locations) != expected_count:
            findings.append(
                f"{key[0]}: {key[1]!r}: expected {expected_count} allowed "
                f"match(es) for {reason}, found {len(locations)} at {locations}"
            )

    for key, (expected_count, reason) in sorted(_ALLOWED_LEGACY_MATCHES.items()):
        if key not in matches:
            findings.append(
                f"{key[0]}: {key[1]!r}: stale allowlist expected {expected_count} "
                f"match(es) for {reason}, found 0"
            )
    return findings


def test_all_tracked_text_has_only_explicit_legacy_identity_allowlist() -> None:
    assert _unexpected_legacy_matches(_tracked_utf8_text()) == []


def test_stale_identity_audit_rejects_every_unexpected_frozen_token() -> None:
    for token in LEGACY_IDENTITY_TOKENS:
        findings = _unexpected_legacy_matches({"docs/unexpected.md": f"new {token}"})
        assert any("docs/unexpected.md:1:" in finding for finding in findings)
        assert any(repr(token) in finding for finding in findings)
