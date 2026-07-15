from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def inspect_validation_distribution(dist_dir: Path, *, expected_version: str) -> None:
    wheels = sorted(dist_dir.glob("powers_tool_validation-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise AssertionError(f"expected one validation wheel, found {wheels!r}")
    expected_name = f"powers_tool_validation-{expected_version}-py3-none-any.whl"
    assert wheels[0].name == expected_name
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        dist_info = f"powers_tool_validation-{expected_version}.dist-info"
        metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8")
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")
        assert "Name: powers-tool-validation" in metadata
        assert f"Version: {expected_version}" in metadata
        assert f"Requires-Dist: powers-tool=={expected_version}" in metadata
        assert "powers-tool-validation = powers_tool_validation.cli:main" in entry_points
        assert "powers-tool =" not in entry_points
        for required in (
            "powers_tool_validation/build_identity.py",
            "powers_tool_validation/installation_identity.py",
            "powers_tool_validation/_runtime_trust.py",
            "powers_tool_validation/candidate_capability.py",
            "powers_tool_validation/cli.py",
            "powers_tool_validation/runtime_extension.py",
            "powers_tool_validation/_build_metadata.py",
        ):
            assert required in names
        assert not any(name.startswith("powers_tool_core/") for name in names)
        assert not any(name.startswith("powers_tool_cli/") for name in names)
        build_identity = archive.read(
            "powers_tool_validation/build_identity.py"
        ).decode("utf-8")
        assert "BuildProfile.VALIDATION" in build_identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args(argv)
    expected_version = args.expected_version
    if expected_version is None:
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        expected_version = project["project"]["version"]
    inspect_validation_distribution(args.dist_dir, expected_version=expected_version)
    print("Powers Tool validation distribution inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
