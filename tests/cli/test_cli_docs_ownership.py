from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = REPO_ROOT / "docs" / "cli"


def read_cli_doc(*parts: str) -> str:
    return DOC_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def read_contract(name: str) -> str:
    return (REPO_ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8")


def test_cli_docs_are_root_local_and_contracts_are_root_level():
    assert (DOC_ROOT / "README.md").exists()
    assert (REPO_ROOT / "CHANGELOG.md").exists()
    assert not (DOC_ROOT / "CHANGELOG.md").exists()

    for path in (
        "cli-integration.md",
        "USER_GUIDE.md",
    ):
        assert (DOC_ROOT / path).exists()

    for package_contract in (
        "power-cli-jsonl-contract.md",
        "power-worker-contract.md",
        "power-orchestrator-workflows.md",
        "common-worker-protocol.md",
    ):
        assert not (DOC_ROOT / package_contract).exists()

    for contract in (
        "common-worker-protocol.md",
        "common-cli-jsonl-contract.md",
        "common-orchestrator-workflows.md",
        "power-worker-contract.md",
        "power-cli-jsonl-contract.md",
        "power-orchestrator-workflows.md",
    ):
        assert (REPO_ROOT / "docs" / "contracts" / contract).exists()


def test_cli_integration_keeps_cli_fields_out_of_core_schema():
    text = read_cli_doc("cli-integration.md")

    assert "measurement_cli_name" in text
    assert "argparse.Namespace" in text
    assert "--enable-hw-trigger" in text


def test_power_contracts_link_common_contracts():
    cli_contract = read_contract("power-cli-jsonl-contract.md")
    workflow_contract = read_contract("power-orchestrator-workflows.md")
    worker_contract = read_contract("power-worker-contract.md")

    assert "common-cli-jsonl-contract.md" in cli_contract
    assert "common-orchestrator-workflows.md" in workflow_contract
    assert "common-worker-protocol.md" in worker_contract


def test_common_contracts_stay_instrument_neutral():
    common_text = "\n".join(
        read_contract(name)
        for name in (
            "common-cli-jsonl-contract.md",
            "common-worker-protocol.md",
            "common-orchestrator-workflows.md",
        )
    )

    assert "acquisition" not in common_text.lower()
