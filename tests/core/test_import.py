def test_package_imports() -> None:
    from importlib import metadata

    import keysight_power_core

    assert keysight_power_core.__version__ == metadata.version("keysight-powers")
