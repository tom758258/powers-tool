from importlib import metadata

import pytest


def test_webui_import() -> None:
    import keysight_power_webui

    assert keysight_power_webui.__version__ == metadata.version("keysight-powers")


def test_webui_server_version_prints_without_starting_server(monkeypatch, capsys) -> None:
    from keysight_power_webui import server

    def fail_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "uvicorn":
            raise AssertionError("uvicorn should not be imported for --version")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    with pytest.raises(SystemExit) as excinfo:
        server.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"keysight-power-webui {server.WEBUI_VERSION}"
    assert captured.err == ""
