from __future__ import annotations

from importlib import metadata, resources

import keysight_power_cli
import keysight_power_core
import keysight_power_webui


def test_import_package_versions_match_distribution():
    distribution_version = metadata.version("keysight-powers")

    assert keysight_power_core.__version__ == distribution_version
    assert keysight_power_cli.__version__ == distribution_version
    assert keysight_power_webui.__version__ == distribution_version


def test_webui_static_assets_are_package_resources():
    static_root = resources.files("keysight_power_webui").joinpath("static")

    for filename in ("index.html", "styles.css", "app.js"):
        assert static_root.joinpath(filename).is_file()
