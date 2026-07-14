"""Embedded identity and opaque permits for the internal validation build."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import metadata
from pathlib import Path
import subprocess
from typing import Any

from powers_tool_core.build_profile import BuildProfile
from powers_tool_core.core import ValidationCandidateContext

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
    package_hash: str


class _ValidationRuntimePermit:
    __slots__ = ()


_VALIDATION_RUNTIME_PERMIT = _ValidationRuntimePermit()
_VERIFIED_CONTEXT_PROOF = object()


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


def _package_hash() -> str:
    digest = hashlib.sha256()
    package_root = Path(__file__).resolve().parent
    for path in sorted(package_root.rglob("*.py")):
        if path.name == "_build_metadata.py":
            continue
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


_SOURCE_COMMIT, _SOURCE_DIRTY, _ARTIFACT_KIND = _source_metadata()
VALIDATION_BUILD_IDENTITY = ValidationBuildIdentity(
    profile=BuildProfile.VALIDATION,
    distribution_name="powers-tool-validation",
    version=__version__,
    product_version=_product_version(),
    source_commit=_SOURCE_COMMIT,
    source_dirty=_SOURCE_DIRTY,
    artifact_kind=_ARTIFACT_KIND,
    package_hash=_package_hash(),
)


def validation_runtime_permit() -> object:
    return _VALIDATION_RUNTIME_PERMIT


def validation_runtime_permit_is_valid(value: Any) -> bool:
    return (
        value is _VALIDATION_RUNTIME_PERMIT
        and VALIDATION_BUILD_IDENTITY.profile is BuildProfile.VALIDATION
    )


def verified_candidate_context(**values: Any) -> ValidationCandidateContext:
    return ValidationCandidateContext(
        **values,
        integrity_validated=True,
        _verifier_proof=_VERIFIED_CONTEXT_PROOF,
    )


def validation_context_was_verified(context: Any) -> bool:
    return (
        isinstance(context, ValidationCandidateContext)
        and context._verifier_proof is _VERIFIED_CONTEXT_PROOF
    )
