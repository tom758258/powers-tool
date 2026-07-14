"""Parser-neutral request and exception types for command core modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from powers_tool_core.connection import DEFAULT_TIMEOUT_MS, SerialOptions


@dataclass(frozen=True)
class ValidationCandidateContext:
    """Validated, run-scoped admission context for one internal candidate case."""

    run_id: str
    case_id: str
    suite: str
    model_id: str
    command: str
    transport_scope: str
    backend_scope: str
    request_fingerprint: str = ""
    capability_id: str = ""
    issued_at: str = ""
    expires_at: str = ""
    # Direct Core callers already supply the typed internal contract.  The CLI
    # sets this explicitly after verifying the signed capability.
    integrity_validated: bool = True


@dataclass(frozen=True)
class RuntimeOptions:
    """Runtime context shared by CLI, future UI, and automation adapters."""

    resource: str | None = None
    resource_alias: str | None = None
    safety_config: str | None = None
    simulate: bool = False
    dry_run: bool = False
    planning_model_id: str | None = None
    expected_model_id: str | None = None
    planning_profile_id: str | None = None
    backend: str | None = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    log_scpi: bool = False
    confirm: bool = False
    serial_options: SerialOptions | None = None
    serial_remote: bool = False
    serial_local_on_close: bool = False
    # Kept as a literal to avoid importing support_policy back into Core.
    support_policy_mode: str = "product"
    validation_candidate_context: ValidationCandidateContext | None = None
    validation_request_fingerprint: str | None = None
    validation_admission_state: dict[str, object] | None = None

    def __post_init__(self) -> None:
        from powers_tool_core.model_resolution import validate_runtime_identity

        validate_runtime_identity(self)


@dataclass(frozen=True)
class OperationRequest:
    command: str
    runtime: RuntimeOptions = field(default_factory=RuntimeOptions)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TriggerRequest:
    command: str
    runtime: RuntimeOptions = field(default_factory=RuntimeOptions)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SequenceRequest:
    command: str = "sequence"
    runtime: RuntimeOptions = field(default_factory=RuntimeOptions)
    parameters: dict[str, Any] = field(default_factory=dict)


class CoreValidationError(ValueError):
    """The request is invalid before any hardware I/O is required."""


class UnsupportedModelError(CoreValidationError):
    """The connected or requested model cannot perform the command."""


class UnsupportedChannelError(CoreValidationError):
    """The requested channel is not supported for the command."""


class ConfirmationRequiredError(CoreValidationError):
    """Real output-affecting execution requires an explicit confirmation."""


class CoreIoError(RuntimeError):
    """Opening or using an instrument failed."""

    def __init__(self, message: str, *, opened: bool = False) -> None:
        super().__init__(message)
        self.opened = opened


class CoreExecutionError(RuntimeError):
    """A command failed after request validation."""


class CommandCancelled(CoreExecutionError):
    """A command stopped cooperatively after a cancellation request."""


class StopCleanupError(CoreExecutionError):
    """Stop cleanup failed after all remaining cleanup steps were attempted."""

    def __init__(self, message: str, *, results: tuple[dict[str, Any], ...]) -> None:
        super().__init__(message)
        self.results = results


class CoreVerificationError(CoreExecutionError):
    """A write verification failed after hardware I/O."""

    def __init__(self, message: str, *, verification: dict[str, Any]) -> None:
        super().__init__(message)
        self.verification = verification


class TriggerWaitTimeout(CoreExecutionError):
    """A trigger wait did not complete before the configured timeout."""


class TriggerInterrupted(CoreExecutionError):
    """A trigger wait was interrupted and cleanup was attempted."""


class SequenceStopped(CoreExecutionError):
    """A sequence stopped after interrupt or failed step cleanup."""
