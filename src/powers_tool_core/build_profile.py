"""Immutable Product build identity and validation-runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import metadata
from typing import Any


class BuildProfile(str, Enum):
    """Build profiles embedded by the Product and internal validation artifacts."""

    PRODUCT = "product"
    VALIDATION = "validation"


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


def consume_validation_admission(handle: Any) -> Any:
    """Consume one verifier-created admission handle from the companion runtime."""

    if handle is None:
        return None
    try:
        from powers_tool_validation.candidate_capability import (  # type: ignore[import-not-found]
            consume_verified_admission,
        )
    except (ImportError, ModuleNotFoundError):
        return None
    return consume_verified_admission(handle)
