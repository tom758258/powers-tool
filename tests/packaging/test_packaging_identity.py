from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import tomllib


ROOT = Path(__file__).resolve().parents[2]


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
    for package in ("keysight_power_core", "keysight_power_cli", "keysight_power_webui"):
        assert not (ROOT / "src" / package).exists()
        assert importlib.util.find_spec(package) is None


def test_build_scripts_use_v2_names_and_preserve_path_guards() -> None:
    cli = (ROOT / "scripts" / "build_cli_exe.ps1").read_text(encoding="utf-8")
    webui = (ROOT / "scripts" / "build_webui_exe.ps1").read_text(encoding="utf-8")

    assert '[string]$Name = "powers-tool"' in cli
    assert "src\\powers_tool_cli\\cli.py" in cli
    assert '[string]$Name = "powers-tool-webui-launcher"' in webui
    assert "src\\powers_tool_webui\\launcher.py" in webui
    assert "src\\powers_tool_webui\\static');powers_tool_webui\\static" in webui
    for script in (cli, webui):
        assert "DistPath must stay under the repository" in script
        assert "StartsWith($repoPrefix" in script
        assert "src\\keysight_power_" not in script


def test_ci_uses_v2_distribution_and_console_commands() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert "--reinstall-package powers-tool" in workflow
    assert "uv run powers-tool --help" in workflow
    assert "uv run powers-tool-webui --help" in workflow
    assert "inspect_distribution.py dist" in workflow
    assert "--reinstall-package keysight-powers" not in workflow


def test_tracked_operational_files_have_no_legacy_framework_identity() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    operational = [
        path
        for path in tracked
        if path == "pyproject.toml"
        or path == "uv.lock"
        or path.startswith((".github/", "scripts/", "examples/", "src/"))
    ]
    forbidden = ("keysight-powers", "keysight-power", "keysight_power_")
    findings: list[str] = []
    for relative in operational:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                findings.append(f"{relative}: {token}")

    assert findings == []
