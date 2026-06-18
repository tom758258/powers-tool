from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = REPO_ROOT / "docs" / "webui"


def read_webui_doc(*parts: str) -> str:
    return DOC_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_webui_docs_are_root_local():
    assert (DOC_ROOT / "README.md").exists()
    assert (REPO_ROOT / "CHANGELOG.md").exists()

    for path in (
        "USER_GUIDE.md",
        "Webui-README.md",
        "web-ui-ai-change-rules.md",
    ):
        assert (DOC_ROOT / path).exists()

    for cli_doc in (
        "cli-integration.md",
        "README_CLI_EN.md",
        "power-cli-jsonl-contract.md",
        "power-worker-contract.md",
        "power-orchestrator-workflows.md",
    ):
        assert not (DOC_ROOT / cli_doc).exists()


def test_webui_docs_point_to_current_import_and_static_paths():
    text = "\n".join(
        read_webui_doc(*path)
        for path in (
            ("README.md",),
            ("Webui-README.md",),
            ("USER_GUIDE.md",),
        )
    )

    assert "keysight_power_webui" in text
    assert "keysight_power_core" in text
    assert "src/keysight_power_webui/static" in text
