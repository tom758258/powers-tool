"""WebUI adapter for Keysight DC power supplies."""

from importlib import metadata

__all__ = ["__version__"]

try:
    __version__ = metadata.version("keysight-powers")
except metadata.PackageNotFoundError:
    __version__ = "1.0.0"
