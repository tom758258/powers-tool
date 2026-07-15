"""Resolve the shared Product and Validation distribution version."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


_VERSION_PATTERN = re.compile(
    r"^[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?$",
    re.IGNORECASE,
)


class VersionResolutionError(ValueError):
    """Raised when Product and Validation do not have one valid version."""


def _project_version(path: Path, label: str) -> str:
    try:
        document: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise VersionResolutionError(f"{label} project metadata is missing or malformed: {path}") from exc
    version = document.get("project", {}).get("version")
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise VersionResolutionError(f"{label} project version is missing or invalid: {path}")
    return version


def resolve_validation_version(product_pyproject: Path, validation_pyproject: Path) -> str:
    product_version = _project_version(product_pyproject, "Product")
    validation_version = _project_version(validation_pyproject, "Validation")
    if product_version != validation_version:
        raise VersionResolutionError(
            f"Product and Validation versions must match exactly: {product_version!r} != {validation_version!r}"
        )
    return product_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("product_pyproject", type=Path)
    parser.add_argument("validation_pyproject", type=Path)
    args = parser.parse_args()
    try:
        version = resolve_validation_version(args.product_pyproject, args.validation_pyproject)
    except VersionResolutionError as exc:
        parser.exit(1, f"{exc}\n")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
