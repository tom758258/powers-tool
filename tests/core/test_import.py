import importlib.util
from pathlib import Path


def test_package_imports() -> None:
    from importlib import metadata

    import powers_tool_core

    assert powers_tool_core.__version__ == metadata.version("keysight-powers")


def test_old_core_namespace_is_absent_without_compatibility_shim() -> None:
    old_namespace = "keysight" + "_power_core"

    assert not Path("src", old_namespace).exists()
    assert importlib.util.find_spec(old_namespace) is None


def test_package_discovery_uses_only_the_new_core_namespace() -> None:
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"powers_tool_core*"' in metadata
    assert f'"{"keysight" + "_power_core"}*"' not in metadata
