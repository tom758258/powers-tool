import importlib.util
from pathlib import Path
import runpy


def test_package_imports() -> None:
    from importlib import metadata

    import powers_tool_core

    assert powers_tool_core.__version__ == metadata.version("powers-tool")


def test_old_core_namespace_is_absent_without_compatibility_shim() -> None:
    old_namespace = "keysight" + "_power_core"

    assert not Path("src", old_namespace).exists()
    assert importlib.util.find_spec(old_namespace) is None


def test_package_discovery_uses_only_the_new_core_namespace() -> None:
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"powers_tool_core*"' in metadata
    assert f'"{"keysight" + "_power_core"}*"' not in metadata


def test_core_missing_distribution_metadata_uses_nonrelease_fallback(monkeypatch) -> None:
    from importlib import metadata

    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("powers-tool")

    monkeypatch.setattr(metadata, "version", missing_distribution)
    namespace = runpy.run_path("src/powers_tool_core/__init__.py")
    source = Path("src/powers_tool_core/__init__.py").read_text(encoding="utf-8")

    assert namespace["__version__"] == "0+unknown"
    assert namespace["__version__"] not in {"1.0.0", "2.0.0"}
    assert "powers_tool_cli" not in source
    assert "powers_tool_webui" not in source
