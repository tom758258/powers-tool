from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - branch depends on Python version
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


def resolve_expected_version(
    explicit_version: str | None, *, inspector_file: Path
) -> str:
    if explicit_version:
        return explicit_version

    repository_root = inspector_file.resolve().parents[2]
    pyproject_path = repository_root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
        version = project["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(
            f"could not resolve [project] version from {pyproject_path}: {exc}"
        ) from exc
    if not isinstance(version, str) or not version.strip():
        raise ValueError(
            f"could not resolve [project] version from {pyproject_path}: "
            "version must be a non-empty string"
        )
    return version
