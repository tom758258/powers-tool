"""Parser-neutral request and exception types for command core modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from keysight_power_core.connection import DEFAULT_TIMEOUT_MS


@dataclass(frozen=True)
class RuntimeOptions:
    """Runtime context shared by CLI, future UI, and automation adapters."""

    resource: str | None = None
    resource_alias: str | None = None
    safety_config: str | None = None
    simulate: bool = False
    dry_run: bool = False
    backend: str | None = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    log_scpi: bool = False
    confirm: bool = False


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
