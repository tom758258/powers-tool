"""Tools for controlling supported DC power supplies safely."""

from importlib import metadata

__all__ = ["__version__"]

try:
    __version__ = metadata.version("powers-tool")
except metadata.PackageNotFoundError:
    __version__ = "0+unknown"
