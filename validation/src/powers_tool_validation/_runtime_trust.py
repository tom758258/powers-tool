"""Private verifier-to-Core trust bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from powers_tool_core.build_profile import BuildProfile
from powers_tool_core.core import ValidationCandidateContext


class _ValidationRuntimePermit:
    __slots__ = ()


_RUNTIME_PERMIT = _ValidationRuntimePermit()
_RESULT_SENTINEL = object()
_CONTEXT_PROOF = object()


@dataclass(frozen=True)
class _VerifiedCapabilityResult:
    values: dict[str, str]
    _sentinel: object


def _context_from_verified_result(result: _VerifiedCapabilityResult) -> ValidationCandidateContext:
    if not isinstance(result, _VerifiedCapabilityResult) or result._sentinel is not _RESULT_SENTINEL:
        raise TypeError("candidate context requires a verified capability result")
    return ValidationCandidateContext(
        **result.values, integrity_validated=True, _verifier_proof=_CONTEXT_PROOF
    )


def _permit_is_valid(value: Any) -> bool:
    return value is _RUNTIME_PERMIT and BuildProfile.VALIDATION.value == "validation"


def _context_is_verified(context: Any) -> bool:
    return isinstance(context, ValidationCandidateContext) and context._verifier_proof is _CONTEXT_PROOF
