from __future__ import annotations

from importlib import metadata, resources

import powers_tool_cli
import powers_tool_core
import powers_tool_webui


def test_import_package_versions_match_distribution():
    distribution_version = metadata.version("keysight-powers")

    assert powers_tool_core.__version__ == distribution_version
    assert powers_tool_cli.__version__ == distribution_version
    assert powers_tool_webui.__version__ == distribution_version


def test_webui_static_assets_are_package_resources():
    static_root = resources.files("powers_tool_webui").joinpath("static")

    for filename in ("index.html", "styles.css", "app.js"):
        assert static_root.joinpath(filename).is_file()
