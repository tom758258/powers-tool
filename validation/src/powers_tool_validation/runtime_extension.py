"""Validation-only parser and verified runtime option extension."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from powers_tool_core.core import CoreValidationError
from powers_tool_validation import candidate_capability
from powers_tool_validation._runtime_trust import (
    _context_from_verified_result,
    _RUNTIME_PERMIT,
)


_ARGUMENT_NAMES = (
    "validation_candidate_manifest",
    "validation_candidate_capability",
    "validation_candidate_context_root",
    "validation_candidate_case_id",
    "validation_candidate_suite",
)


class ValidationRuntimeExtension:
    """Adapter installed only by the internal validation entry point."""

    def add_live_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--validation-candidate-manifest", help=argparse.SUPPRESS)
        parser.add_argument("--validation-candidate-capability", help=argparse.SUPPRESS)
        parser.add_argument("--validation-candidate-context-root", help=argparse.SUPPRESS)
        parser.add_argument("--validation-candidate-case-id", help=argparse.SUPPRESS)
        parser.add_argument("--validation-candidate-suite", help=argparse.SUPPRESS)

    def _candidate_inputs(self, args: argparse.Namespace) -> tuple[Any, ...]:
        return tuple(getattr(args, name, None) for name in _ARGUMENT_NAMES)

    def _candidate_inputs_supplied(self, args: argparse.Namespace) -> bool:
        return any(value is not None for value in self._candidate_inputs(args))

    def decorate_execution(
        self, args: argparse.Namespace, execution: dict[str, Any]
    ) -> None:
        if self._candidate_inputs_supplied(args):
            execution.setdefault("candidate_context_required", True)
            execution.setdefault("candidate_context_integrity_validated", False)
            execution.setdefault("candidate_scope_admitted", False)

    def runtime_options(self, args: argparse.Namespace) -> Mapping[str, Any]:
        cached = getattr(args, "_validation_distribution_runtime_options", None)
        if isinstance(cached, dict):
            return cached
        values = self._candidate_inputs(args)
        options: dict[str, Any] = {
            "validation_build_permit": _RUNTIME_PERMIT,
        }
        if not any(value is not None for value in values):
            setattr(args, "_validation_distribution_runtime_options", options)
            return options
        if not all(isinstance(value, str) and value for value in values):
            raise CoreValidationError("validation candidate capability is malformed")
        manifest_value, capability_value, root_value, case_id_value, suite_value = values
        try:
            manifest_path = Path(manifest_value).resolve()
            capability_path = Path(capability_value).resolve()
            context_root = Path(root_value).resolve()
        except (OSError, ValueError) as exc:
            raise CoreValidationError("validation candidate capability path is malformed") from exc
        if (
            context_root.name != "private"
            or manifest_path.parent != context_root
            or capability_path.parent != context_root
        ):
            raise CoreValidationError(
                "validation candidate capability is outside the private run directory"
            )
        state = getattr(args, "_execution_state", None)
        if not isinstance(state, dict):
            state = getattr(args, "_candidate_admission_state", None)
        if not isinstance(state, dict):
            state = {}
            setattr(args, "_candidate_admission_state", state)
        self.decorate_execution(args, state)
        try:
            secret = candidate_capability.secret_from_environment()
            verified_result = candidate_capability.consume_and_verify(
                manifest_path,
                capability_path,
                context_root,
                secret,
                argv=getattr(args, "_raw_argv", ()),
                command=args.command,
                expected_case_id=case_id_value,
                expected_suite=suite_value,
            )
        except candidate_capability.CandidateCapabilityError as exc:
            raise CoreValidationError(str(exc)) from exc
        context = _context_from_verified_result(verified_result)
        state["candidate_context_integrity_validated"] = True
        options.update(
            {
                "validation_candidate_context": context,
                "validation_request_fingerprint": context.request_fingerprint,
                "validation_admission_state": state,
            }
        )
        setattr(args, "_validation_distribution_runtime_options", options)
        return options
