from __future__ import annotations

from importlib import import_module, metadata, resources
from pathlib import Path

from packaging.requirements import Requirement

try:  # pragma: no cover - branch depends on Python version
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

import powers_tool_cli
import powers_tool_core
import powers_tool_webui


ROOT = Path(__file__).resolve().parents[2]


def test_distribution_release_metadata():
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["name"] == "powers-tool"
    assert project["authors"] == [{"name": "Powers Tool contributors"}]
    assert project["description"] == (
        "Safe vendor-neutral Python tooling for supported DC power supplies."
    )


def test_import_package_versions_match_distribution():
    distribution_version = metadata.version("powers-tool")

    assert powers_tool_core.__version__ == distribution_version
    assert powers_tool_cli.__version__ == distribution_version
    assert powers_tool_webui.__version__ == distribution_version


def test_webui_static_assets_are_package_resources():
    static_root = resources.files("powers_tool_webui").joinpath("static")

    for filename in ("index.html", "styles.css", "app.js"):
        assert static_root.joinpath(filename).is_file()


def test_python_backend_and_discovery_dependencies_are_required_and_loadable():
    from pyvisa.highlevel import get_wrapper_class
    from pyvisa_py.highlevel import PyVisaLibrary

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for requirements in (project["dependencies"], metadata.requires("powers-tool")):
        required = {
            requirement.name
            for value in requirements
            if (requirement := Requirement(value)).marker is None
        }
        assert {"pyvisa-py", "psutil", "zeroconf"} <= required
    for module in ("psutil", "zeroconf"):
        import_module(module)
    assert get_wrapper_class("py") is PyVisaLibrary
