from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path


CANONICAL_PACKAGES = ("powers_tool_core", "powers_tool_cli", "powers_tool_webui")
LEGACY_PACKAGES = ("keysight_power_core", "keysight_power_cli", "keysight_power_webui")
ENTRY_POINTS = {
    "powers-tool = powers_tool_cli.cli:main",
    "powers-tool-webui = powers_tool_webui.server:main",
    "powers-tool-webui-launcher = powers_tool_webui.launcher:main",
}


def inspect_distribution(dist_dir: Path, *, require_sdist: bool = True) -> None:
    wheels = sorted(dist_dir.glob("powers_tool-*-py3-none-any.whl"))
    sdists = sorted(dist_dir.glob("powers_tool-*.tar.gz"))
    if len(wheels) != 1 or (require_sdist and len(sdists) != 1):
        raise AssertionError(f"expected one Powers Tool wheel and sdist: {wheels!r}, {sdists!r}")

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
        entry_points = archive.read(entry_points_name).decode("utf-8")
        metadata_lines = set(metadata.splitlines())
        assert "Name: powers-tool" in metadata_lines
        assert "Version: 2.0.0" in metadata_lines
        assert "Requires-Python: >=3.10" in metadata_lines
        entry_point_lines = set(entry_points.splitlines())
        assert ENTRY_POINTS <= entry_point_lines
        assert not any(line.startswith("keysight-power") for line in entry_point_lines)
        for package in CANONICAL_PACKAGES:
            assert any(name.startswith(f"{package}/") for name in names), package
        for package in LEGACY_PACKAGES:
            assert not any(name.startswith(f"{package}/") for name in names), package
        for filename in ("index.html", "styles.css", "app.js"):
            assert f"powers_tool_webui/static/{filename}" in names

    if sdists:
        with tarfile.open(sdists[0], "r:gz") as archive:
            names = set(archive.getnames())
            top_levels = {name.split("/", 1)[0] for name in names}
            assert len(top_levels) == 1
            root = top_levels.pop()
            assert root.startswith("powers_tool-")
            for package in CANONICAL_PACKAGES:
                assert any(name.startswith(f"{root}/src/{package}/") for name in names), package
            for package in LEGACY_PACKAGES:
                assert not any(name.startswith(f"{root}/src/{package}/") for name in names), package
            for filename in ("index.html", "styles.css", "app.js"):
                assert f"{root}/src/powers_tool_webui/static/{filename}" in names


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 1:
        inspect_distribution(Path(args[0]))
    elif len(args) == 2 and args[0] == "--wheel-only":
        inspect_distribution(Path(args[1]), require_sdist=False)
    else:
        raise SystemExit("usage: inspect_distribution.py [--wheel-only] DIST_DIR")
    print("Powers Tool distribution inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
