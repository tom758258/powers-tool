from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_preparation_workflow_installs_exact_local_wheels() -> None:
    text = (ROOT / "scripts" / "prepare-validation-environment.ps1").read_text(encoding="utf-8")
    assert "--no-index --no-deps $productWheel.FullName" in text
    assert "--no-index --no-deps $validationWheel.FullName" in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert ".powers-tool-validation-installation.json" in text
    assert "status --porcelain" in text


def test_real_wrapper_has_one_runtime_and_no_source_fallback() -> None:
    text = (ROOT / "scripts" / "live-cli-check.ps1").read_text(encoding="utf-8")
    live_function = text.split("function Invoke-ValidationCommand", 1)[1].split("function Test-AllOutputsOff", 1)[0]
    assert "& $ValidationExecutable @ValidationPrefix @allArgs" in live_function
    assert "installed_runtime_verified" in text
    assert "repository_source_shadowed" in text
    assert "POWERS_TOOL_VALIDATION_TEST_STOP_BEFORE_VISA" in text


def test_product_entry_point_is_not_replaced() -> None:
    pyproject = (ROOT / "validation" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'powers-tool-validation = "powers_tool_validation.cli:main"' in pyproject
    scripts = pyproject.split("[project.scripts]", 1)[1].split("[", 1)[0]
    assert "powers-tool =" not in scripts
