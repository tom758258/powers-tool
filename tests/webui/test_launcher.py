from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from powers_tool_webui import launcher


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_build_local_url_uses_loopback_default_port() -> None:
    assert launcher.DEFAULT_HOST == "127.0.0.1"
    assert launcher.DEFAULT_PORT == 7999
    assert launcher.build_local_url(launcher.DEFAULT_PORT) == "http://127.0.0.1:7999"


def test_launcher_version_prints_without_opening_gui(monkeypatch, capsys) -> None:
    def fail_tk() -> object:
        raise AssertionError("launcher GUI should not open for --version")

    monkeypatch.setattr(launcher.tk, "Tk", fail_tk)

    with pytest.raises(SystemExit) as excinfo:
        launcher.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"powers-tool-webui-launcher {launcher.WEBUI_VERSION}"
    assert captured.err == ""


@pytest.mark.parametrize("value", ["1", "7999", "65535", " 1234 "])
def test_parse_port_accepts_valid_port(value: str) -> None:
    assert 1 <= launcher.parse_port(value) <= 65535


@pytest.mark.parametrize("value", ["0", "65536", "abc", ""])
def test_parse_port_rejects_invalid_port(value: str) -> None:
    with pytest.raises(ValueError):
        launcher.parse_port(value)


def test_server_is_ready_accepts_powers_tool_webui_health(monkeypatch) -> None:
    health_url = f"{launcher.build_local_url(launcher.DEFAULT_PORT)}/api/health"

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        assert url == health_url
        assert timeout == 0.5
        return FakeResponse({"status": "ok", "package": "powers-tool-webui"})

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._server_is_ready(health_url) is True


def test_server_is_ready_rejects_other_http_service(monkeypatch) -> None:
    health_url = f"{launcher.build_local_url(launcher.DEFAULT_PORT)}/api/health"

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        return FakeResponse({"status": "ok", "package": "other-service"})

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._server_is_ready(health_url) is False


def test_http_server_is_ready_detects_any_http_response(monkeypatch) -> None:
    url = launcher.build_local_url(launcher.DEFAULT_PORT)

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        return FakeResponse({}, status=404)

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._http_server_is_ready(url) is True


def test_http_server_is_ready_accepts_http_error(monkeypatch) -> None:
    url = launcher.build_local_url(launcher.DEFAULT_PORT)

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        raise HTTPError(url, 503, "busy", {}, None)

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._http_server_is_ready(url) is True


def test_http_server_is_ready_rejects_connection_error(monkeypatch) -> None:
    url = launcher.build_local_url(launcher.DEFAULT_PORT)

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._http_server_is_ready(url) is False


def test_launcher_does_not_import_cli_adapter() -> None:
    source = (REPO_ROOT / "src" / "powers_tool_webui" / "launcher.py").read_text(
        encoding="utf-8"
    )

    assert "powers_tool_cli" not in source


def test_hardware_job_is_active_reads_webui_job_manager() -> None:
    from powers_tool_webui.jobs import job_manager

    previous = job_manager.active_job_id
    try:
        job_manager.active_job_id = "active-job"
        assert launcher.hardware_job_is_active() is True
    finally:
        job_manager.active_job_id = previous


def test_create_uvicorn_server_uses_loopback_and_selected_port() -> None:
    server = launcher.create_uvicorn_server(8123)

    assert server.config.host == "127.0.0.1"
    assert server.config.port == 8123
    assert server.config.log_config is None
    assert server.config.access_log is False


def test_pyproject_declares_launcher_script() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'powers-tool-webui-launcher = "powers_tool_webui.launcher:main"' in pyproject
