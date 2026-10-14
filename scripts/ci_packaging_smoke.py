"""Verify real, headless Windows build outputs; never certify a release."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLES = (
    "Powers Tool.exe",
    "powers-tool.exe",
    "powers-tool-webui-launcher.exe",
    "powers-tool-webui-host.exe",
)

def run(*args: str) -> None:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=90, check=False)
    if result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {args!r}\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )

def desktop_smoke(version: str) -> None:
    desktop = ROOT / "dist" / "desktop" / "win-unpacked"
    bundle = ROOT / "dist" / "powers-tool"
    assert desktop.is_dir(), desktop
    assert bundle.is_dir(), bundle
    for executable in EXECUTABLES:
        assert (desktop / executable).is_file(), executable
    assert (desktop / "resources").is_dir()
    assert (desktop / "_internal").is_dir()
    assert not (desktop / "resources" / "backend").exists()
    assert len([p for p in desktop.rglob("_internal") if p.is_dir()]) == 1

    run(sys.executable, "tests/packaging/inspect_windows_bundle.py", "--expected-version",
        version, str(bundle))
    run(sys.executable, "tests/packaging/inspect_pyinstaller.py",
        str(desktop / "powers-tool.exe"),
        str(desktop / "powers-tool-webui-launcher.exe"))
    run(str(desktop / "powers-tool.exe"), "identify", "--simulate", "--json")
    run(str(desktop / "powers-tool-webui-launcher.exe"), "--version")

def release_smoke(version: str) -> None:
    release = ROOT / "release" / version
    expected = {
        f"powers-tool-{version}-windows-x64.zip",
        f"powers_tool-{version}-py3-none-any.whl",
        f"powers_tool-{version}.tar.gz",
        "checksums.txt",
    }
    assert release.is_dir(), release
    assert {file.name for file in release.iterdir()} == expected
    lines = (release / "checksums.txt").read_text(encoding="utf-8-sig").splitlines()
    seen: set[str] = set()
    for line in lines:
        match = re.fullmatch(r"([a-fA-F0-9]{64})  (.+)", line)
        assert match is not None, f"Bad checksum line: {line!r}"
        digest, filename = match.groups()
        assert filename in expected - {"checksums.txt"}
        assert filename not in seen
        seen.add(filename)
        assert hashlib.sha256((release / filename).read_bytes()).hexdigest() == digest.lower()
    assert seen == expected - {"checksums.txt"}

    with zipfile.ZipFile(release / f"powers-tool-{version}-windows-x64.zip") as archive:
        names = {name.replace("\\", "/") for name in archive.namelist()}
        prefix = f"powers-tool-{version}/"
        for exe in EXECUTABLES:
            assert prefix + exe in names, exe
        assert any(x.startswith(prefix + "_internal/") for x in names)
        assert any(x.startswith(prefix + "resources/") for x in names)
        assert not any("/resources/backend/" in x for x in names)
    run(sys.executable, "tests/packaging/inspect_distribution.py",
        "--expected-version", version, str(release))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-layout", action="store_true")
    args = parser.parse_args()
    assert sys.platform == "win32", "Windows packaging smoke requires Windows"
    version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    desktop_smoke(version)
    if args.release_layout:
        release_smoke(version)
    print("Windows headless packaging smoke passed; not formal release acceptance")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
