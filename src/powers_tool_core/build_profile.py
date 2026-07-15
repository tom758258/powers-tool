"""Immutable Product build identity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import metadata


class BuildProfile(str, Enum):
    """Build profile embedded by the Product artifact."""

    PRODUCT = "product"


@dataclass(frozen=True)
class ProductBuildIdentity:
    """Identity embedded in the normal release distribution."""

    profile: BuildProfile
    distribution_name: str
    version: str


def _product_version() -> str:
    try:
        return metadata.version("powers-tool")
    except metadata.PackageNotFoundError:
        return "0+unknown"


PRODUCT_BUILD_IDENTITY = ProductBuildIdentity(
    profile=BuildProfile.PRODUCT,
    distribution_name="powers-tool",
    version=_product_version(),
)
