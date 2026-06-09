from __future__ import annotations

from pathlib import Path

import keysight_power_core as core


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]


def read_package_doc(*parts: str) -> str:
    return PACKAGE_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_core_docs_are_package_local():
    assert (PACKAGE_ROOT / "README.md").exists()
    assert (PACKAGE_ROOT / "CHANGELOG.md").exists()

    for path in (
        "docs/integration.md",
        "docs/supported-models.md",
    ):
        assert (PACKAGE_ROOT / path).exists()

    for adapter_doc in (
        "docs/cli-integration.md",
        "docs/README_CLI_EN.md",
        "docs/Webui-README.md",
        "docs/power-cli-jsonl-contract.md",
        "docs/power-worker-contract.md",
    ):
        assert not (PACKAGE_ROOT / adapter_doc).exists()


def test_core_integration_names_public_core_api():
    text = read_package_doc("docs", "integration.md")

    for name in core.__all__:
        assert name in text

    assert "keysight_power_core" in text


def test_root_contracts_remain_canonical():
    for contract in (
        "common-worker-protocol.md",
        "common-cli-jsonl-contract.md",
        "common-orchestrator-workflows.md",
        "power-worker-contract.md",
        "power-cli-jsonl-contract.md",
        "power-orchestrator-workflows.md",
    ):
        assert (REPO_ROOT / "docs" / "contracts" / contract).exists()


def test_root_testing_guidelines_are_linked_and_structural():
    guidelines_path = REPO_ROOT / "docs" / "testing-guidelines.md"
    assert guidelines_path.exists()

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/testing-guidelines.md" in readme

    guidelines = guidelines_path.read_text(encoding="utf-8")
    for heading in (
        "# Testing Guidelines",
        "## What To Test",
        "## What Not To Freeze",
        "## Documentation Tests",
        "## Frontend Static Tests",
        "## Instrument Safety Tests",
        "## Review Standard",
    ):
        assert heading in guidelines

    for token in ("SCPI", "safety", "JSON", "Frontend Static Tests"):
        assert token in guidelines
