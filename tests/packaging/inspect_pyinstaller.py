from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def _normalise(name: str) -> str:
    return name.replace("\\", "/")


def inspect_executable(path: Path, required_packages: tuple[str, ...], *, webui: bool) -> None:
    archive = CArchiveReader(str(path))
    names = {_normalise(name): name for name in archive.toc}

    metadata_names = sorted(
        name for name in names if name.endswith(".dist-info/METADATA")
    )
    powers_metadata = "powers_tool-2.0.0.dist-info/METADATA"
    assert powers_metadata in metadata_names, metadata_names
    assert not any("keysight" in name.lower() for name in metadata_names)
    metadata = archive.extract(names[powers_metadata]).decode("utf-8")
    assert "Name: powers-tool" in metadata.splitlines()
    assert "Version: 2.0.0" in metadata.splitlines()

    pyz_name = names.get("PYZ.pyz")
    if pyz_name is None:
        raise AssertionError(f"{path} does not contain PYZ.pyz")
    pyz_names = set(archive.open_embedded_archive(pyz_name).toc)
    for package in required_packages:
        assert package in pyz_names, package
        assert any(name.startswith(f"{package}.") for name in pyz_names), package
    assert not any("keysight_power_" in name for name in (*names, *pyz_names))
    assert not any("keysight-powers" in name.lower() for name in names)

    if webui:
        for filename in ("index.html", "styles.css", "app.js"):
            assert f"powers_tool_webui/static/{filename}" in names


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: inspect_pyinstaller.py CLI_EXE WEBUI_EXE")
    cli, webui = (Path(value) for value in args)
    inspect_executable(cli, ("powers_tool_core", "powers_tool_cli"), webui=False)
    inspect_executable(webui, ("powers_tool_core", "powers_tool_webui"), webui=True)
    print("Powers Tool PyInstaller archive inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
