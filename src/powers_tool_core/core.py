"""Parser-neutral request and exception types for command core modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from powers_tool_core.connection import DEFAULT_TIMEOUT_MS, SerialOptions


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

    def __init__(
        self,
        message: str,
        *,
        trigger: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.trigger = trigger
        self.data = data


class CommandCancelled(CoreExecutionError):
    """A command stopped cooperatively after a cancellation request."""

    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data or {
            "status": "cancelled",
            "cancelled_by_user": True,
            "original_reason": "user_cancelled",
            "cleanup": [],
        }


class StopCleanupError(CoreExecutionError):
    """Stop cleanup failed after all remaining cleanup steps were attempted."""

    def __init__(
        self,
        message: str,
        *,
        results: tuple[dict[str, Any], ...],
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.results = results
        self.data = data or {
            "status": "failed",
            "original_reason": "user_cancelled",
            "cleanup": list(results),
        }


class CoreVerificationError(CoreExecutionError):
    """A write verification failed after hardware I/O."""

    def __init__(
        self,
        message: str,
        *,
        verification: dict[str, Any],
        trigger: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, trigger=trigger, data=data)
        self.verification = verification


class TriggerWaitTimeout(CoreExecutionError):
    """A trigger wait did not complete before the configured timeout."""


class TriggerInterrupted(CoreExecutionError):
    """A trigger wait was interrupted and cleanup was attempted."""


class SequenceStopped(CoreExecutionError):
    """A sequence stopped after interrupt or failed step cleanup."""
