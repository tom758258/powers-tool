from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_preparation_workflow_installs_exact_local_wheels() -> None:
    text = (ROOT / "scripts" / "prepare-validation-environment.ps1").read_text(encoding="utf-8")
    assert "--no-index --no-deps $productWheel.FullName" in text
    assert "--no-index --no-deps $validationWheel.FullName" in text
    assert "uv export --locked --no-dev --no-emit-workspace" in text
    assert "pip download --require-hashes --only-binary=:all:" in text
    assert "pip install --no-index --find-links" in text
    assert "import yaml,pyvisa,powers_tool_core,powers_tool_cli,powers_tool_validation" in text
    assert ".powers-tool-validation-artifacts" in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert ".powers-tool-validation-installation.json" in text
    assert "status --porcelain" in text


def test_preparation_workflow_is_version_neutral() -> None:
    text = (ROOT / "scripts" / "prepare-validation-environment.ps1").read_text(encoding="utf-8")
    assert "pyproject.toml" in text and "validation\\pyproject.toml" in text
    assert "resolve_validation_version.py" in text
    assert "--expected-version $productVersion" in text
    assert "--expected-version $validationVersion" in text
    assert 'product_version = $productVersion' in text
    assert 'validation_version = $validationVersion' in text
    assert "2.0.0" not in text


def test_runtime_identity_closes_retained_wheels_to_installed_files() -> None:
    text = (ROOT / "validation" / "src" / "powers_tool_validation" / "installation_identity.py").read_text(encoding="utf-8")
    for contract in (
        "ARTIFACT_DIRECTORY", "retained wheel identity verification failed",
        "installed file differs from retained wheel RECORD",
        "installed METADATA differs from retained wheel",
        "installed entry points differ from retained wheel",
        "installed RECORD integrity check failed",
        "loaded runtime module was not verified against retained wheels",
        "runtime_dependencies_verified",
    ):
        assert contract in text


def test_real_wrapper_has_one_runtime_and_no_source_fallback() -> None:
    text = (ROOT / "scripts" / "live-cli-check.ps1").read_text(encoding="utf-8")
    live_function = text.split("function Invoke-ValidationCommand", 1)[1].split("function Test-AllOutputsOff", 1)[0]
    assert "& $ValidationExecutable @ValidationPrefix @allArgs" in live_function
    assert "installed_runtime_verified" in text
    assert "repository_source_shadowed" in text
    assert "POWERS_TOOL_VALIDATION_TEST_STOP_BEFORE_VISA" in text


def test_pre_visa_acceptance_bypass_is_exact_and_after_installed_runtime_gates() -> None:
    text = (ROOT / "scripts" / "live-cli-check.ps1").read_text(encoding="utf-8")
    opt_in = text.index('POWERS_TOOL_RUN_CLEAN_PRE_VISA_ACCEPTANCE -eq "1"')
    stop_marker = text.index('POWERS_TOOL_VALIDATION_TEST_STOP_BEFORE_VISA -eq "1"')
    pytest_call = text.index(
        'validation/tests/test_clean_pre_visa_acceptance.py::test_clean_pre_visa_acceptance (call)'
    )
    redirected = text.index("[Console]::IsInputRedirected")
    installed_gate = text.index("Real validation requires a clean, installed internal validation wheel.")
    stop = text.index('Write-ValidationArtifacts -ValidationMode "pre_visa_test"')
    secret = text.index("$script:CandidateRunSecret = New-SecureHexValue -ByteCount 32")
    assert opt_in < redirected and stop_marker < redirected and pytest_call < redirected
    assert installed_gate < stop < secret


def test_product_entry_point_is_not_replaced() -> None:
    pyproject = (ROOT / "validation" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'powers-tool-validation = "powers_tool_validation.cli:main"' in pyproject
    scripts = pyproject.split("[project.scripts]", 1)[1].split("[", 1)[0]
    assert "powers-tool =" not in scripts
