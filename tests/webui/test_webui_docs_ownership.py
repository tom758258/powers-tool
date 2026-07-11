from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = REPO_ROOT / "docs" / "webui"


def read_webui_doc(*parts: str) -> str:
    return DOC_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_webui_docs_are_root_local():
    assert (DOC_ROOT / "README.md").exists()
    assert (REPO_ROOT / "CHANGELOG.md").exists()
    assert not (DOC_ROOT / "CHANGELOG.md").exists()

    for path in (
        "USER_GUIDE.md",
        "web-ui-change-rules.md",
    ):
        assert (DOC_ROOT / path).exists()

    for cli_doc in (
        "cli-integration.md",
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
            ("USER_GUIDE.md",),
            ("web-ui-change-rules.md",),
        )
    )

    assert "keysight_power_webui" in text
    assert "keysight_power_core" in text
    assert "src/keysight_power_webui/static" in text


def test_webui_docs_describe_exact_support_as_product_only_ux():
    readme = read_webui_doc("README.md")
    guide = read_webui_doc("USER_GUIDE.md")
    text = f"{readme}\n{guide}"
    normalized_readme = " ".join(readme.split())
    normalized_guide = " ".join(guide.split())

    assert "Core-derived model-level exact live-support summaries" in readme
    assert "Connection scope not evaluated" in guide
    assert "Pending live validation" in guide
    assert "Product-only" in readme
    assert "no validation mode or VISA-backend selector" in normalized_readme
    assert "Core post-IDN exact-scope gate remains authoritative" in readme
    assert "Pending commands remain visible but disabled" in normalized_guide
    assert "successful real `identify` diagnostic" in readme
    assert "does not open pending feature commands" in normalized_readme
    assert "unknown or de-scoped model" in normalized_readme
    assert "support projection is unevaluated" in normalized_readme
    assert "does not enable Generic fallback" in normalized_readme
    assert "expected-model mismatch still fails" in normalized_readme.lower()
    assert "default system-VISA backend" in normalized_guide
    assert "actual runtime transport/backend matches a registered pending scope" in normalized_guide
    assert "Offline-only utilities are not identity/status diagnostics" in guide
    assert "not shown as Product-open live commands" in normalized_guide
    assert "--validation-allow-pending-live-support" not in text
    assert "Local/" not in text
