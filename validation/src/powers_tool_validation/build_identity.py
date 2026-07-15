"""Embedded build identity for the internal validation distribution."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import subprocess
from powers_tool_core.build_profile import BuildProfile

from powers_tool_validation import __version__


@dataclass(frozen=True)
class ValidationBuildIdentity:
    profile: BuildProfile
    distribution_name: str
    version: str
    product_version: str
    source_commit: str
    source_dirty: bool
    artifact_kind: str


def _product_version() -> str:
    try:
        return metadata.version("powers-tool")
    except metadata.PackageNotFoundError:
        return "0+unknown"


def _source_metadata() -> tuple[str, bool, str]:
    try:
        from powers_tool_validation._build_metadata import (  # type: ignore[import-not-found]
            ARTIFACT_KIND,
            SOURCE_COMMIT,
            SOURCE_DIRTY,
        )

        return str(SOURCE_COMMIT), bool(SOURCE_DIRTY), str(ARTIFACT_KIND)
    except ImportError:
        root = Path(__file__).resolve().parents[3]
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip()
            dirty = bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                ).stdout.strip()
            )
            return commit, dirty, "source-tree"
        except (OSError, subprocess.CalledProcessError):
            return "unknown", True, "source-tree"


_SOURCE_COMMIT, _SOURCE_DIRTY, _ARTIFACT_KIND = _source_metadata()
VALIDATION_BUILD_IDENTITY = ValidationBuildIdentity(
    profile=BuildProfile.VALIDATION,
    distribution_name="powers-tool-validation",
    version=__version__,
    product_version=_product_version(),
    source_commit=_SOURCE_COMMIT,
    source_dirty=_SOURCE_DIRTY,
    artifact_kind=_ARTIFACT_KIND,
)
