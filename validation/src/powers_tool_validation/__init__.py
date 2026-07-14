"""Internal validation-only Powers Tool companion distribution."""

from importlib import metadata
from pathlib import Path
import re

try:
    __version__ = metadata.version("powers-tool-validation")
except metadata.PackageNotFoundError:
    try:
        project_text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        __version__ = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"\s*$', project_text
        ).group(1)
    except (AttributeError, OSError):
        __version__ = "0+unknown"

__all__ = ["__version__"]
