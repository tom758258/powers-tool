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


def validation_runtime_permit_is_valid(permit: Any) -> bool:
    """Return whether the separately installed validation build issued *permit*."""

    if permit is None:
        return False
    try:
        from powers_tool_validation.build_identity import (  # type: ignore[import-not-found]
            validation_runtime_permit_is_valid as validate,
        )
    except (ImportError, ModuleNotFoundError):
        return False
    return bool(validate(permit))


def validation_context_was_verified(context: Any) -> bool:
    """Return whether the validation distribution's verifier created *context*."""

    try:
        from powers_tool_validation.build_identity import (  # type: ignore[import-not-found]
            validation_context_was_verified as validate,
        )
    except (ImportError, ModuleNotFoundError):
        return False
    return bool(validate(context))
