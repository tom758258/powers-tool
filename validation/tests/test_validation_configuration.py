from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _version_module():
    path = ROOT / "scripts" / "resolve_validation_version.py"
    spec = importlib.util.spec_from_file_location("resolve_validation_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_project(path: Path, version: str | None) -> None:
    value = "[project]\nname = \"fixture\"\n"
    if version is not None:
        value += f'version = "{version}"\n'
    path.write_text(value, encoding="utf-8")


def test_validation_pytest_configuration_has_no_fixed_basetemp() -> None:
    document = tomllib.loads((ROOT / "validation" / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = document["tool"]["pytest"]["ini_options"]
    assert "addopts" not in pytest_options
    assert pytest_options["testpaths"] == ["tests"]
    assert pytest_options["pythonpath"] == ["src", "../src"]


@pytest.mark.parametrize("version", ["2.0.0", "2.0.0rc1", "2.0.0+validation.1"])
def test_resolver_returns_matching_valid_version(tmp_path: Path, version: str) -> None:
    module = _version_module()
    product = tmp_path / "product.toml"
    validation = tmp_path / "validation.toml"
    _write_project(product, version)
    _write_project(validation, version)
    assert module.resolve_validation_version(product, validation) == version


@pytest.mark.parametrize(
    ("product_version", "validation_version"),
    [("2.0.0", "2.0.1"), (None, "2.0.0"), ("2.0.0", None), ("not a version", "not a version")],
)
def test_resolver_rejects_mismatch_missing_and_malformed_versions(
    tmp_path: Path, product_version: str | None, validation_version: str | None
) -> None:
    module = _version_module()
    product = tmp_path / "product.toml"
    validation = tmp_path / "validation.toml"
    _write_project(product, product_version)
    _write_project(validation, validation_version)
    with pytest.raises(module.VersionResolutionError):
        module.resolve_validation_version(product, validation)


def test_preparation_script_uses_shared_resolver_without_direct_tomllib() -> None:
    text = (ROOT / "scripts" / "prepare-validation-environment.ps1").read_text(encoding="utf-8")
    assert "resolve_validation_version.py" in text
    assert "tomllib" not in text
    assert "tomllib.loads" not in text
