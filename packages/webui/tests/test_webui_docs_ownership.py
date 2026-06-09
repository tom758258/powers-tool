from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def read_package_doc(*parts: str) -> str:
    return PACKAGE_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_webui_docs_are_package_local():
    assert (PACKAGE_ROOT / "README.md").exists()
    assert (PACKAGE_ROOT / "CHANGELOG.md").exists()

    for path in (
        "docs/USER_GUIDE.md",
        "docs/Webui-README.md",
        "docs/web-ui-ai-change-rules.md",
    ):
        assert (PACKAGE_ROOT / path).exists()

    for cli_doc in (
        "docs/cli-integration.md",
        "docs/README_CLI_EN.md",
        "docs/power-cli-jsonl-contract.md",
        "docs/power-worker-contract.md",
        "docs/power-orchestrator-workflows.md",
    ):
        assert not (PACKAGE_ROOT / cli_doc).exists()


def test_webui_docs_point_to_current_import_and_static_paths():
    text = "\n".join(
        read_package_doc(*path)
        for path in (
            ("README.md",),
            ("docs", "Webui-README.md"),
            ("docs", "USER_GUIDE.md"),
        )
    )

    assert "keysight_power_webui" in text
    assert "keysight_power_core" in text
    assert "packages/webui/src/keysight_power_webui/static" in text
