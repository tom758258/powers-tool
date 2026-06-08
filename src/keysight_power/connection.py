"""VISA connection helpers and a small instrument session wrapper."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from keysight_power.errors import VisaConnectionError

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_READ_TERMINATION = "\n"
DEFAULT_WRITE_TERMINATION = "\n"


@runtime_checkable
class ResourceManagerLike(Protocol):
    def list_resources(self) -> tuple[str, ...]:
        """Return available VISA resources."""

    def open_resource(self, resource_name: str) -> Any:
        """Open a VISA resource."""


class InstrumentSession:
    """Thin wrapper around a VISA resource."""

    def __init__(self, resource: Any, resource_name: str | None = None) -> None:
        self._resource = resource
        self.resource_name = resource_name
        self._closed = False

    def __enter__(self) -> InstrumentSession:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, command: str) -> Any:
        self._ensure_open()
        try:
            return self._resource.write(command)
        except Exception as exc:  # pragma: no cover - exception type depends on backend
            raise VisaConnectionError(f"VISA write failed for {command!r}") from exc

    def query(self, command: str) -> str:
        self._ensure_open()
        try:
            return str(self._resource.query(command)).strip()
        except Exception as exc:  # pragma: no cover - exception type depends on backend
            raise VisaConnectionError(f"VISA query failed for {command!r}") from exc

    def identify(self) -> str:
        return self.query("*IDN?")

    def clear_status(self) -> Any:
        return self.write("*CLS")

    def query_error(self) -> str:
        return self.query("SYST:ERR?")

    def check_errors(self, max_reads: int = 20) -> list[str]:
        if max_reads < 1:
            raise ValueError("max_reads must be at least 1")

        errors: list[str] = []
        for _ in range(max_reads):
            response = self.query_error()
            if _is_no_error(response):
                break
            errors.append(response)
        return errors

    def close(self) -> None:
        if self._closed:
            return

        try:
            self._resource.close()
        except Exception as exc:  # pragma: no cover - exception type depends on backend
            raise VisaConnectionError("VISA close failed") from exc
        finally:
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise VisaConnectionError("VISA session is closed")


def create_resource_manager(backend: str | None = None) -> ResourceManagerLike:
    try:
        import pyvisa
    except ImportError as exc:  # pragma: no cover - dependency is installed in normal env
        raise VisaConnectionError("PyVISA is not installed") from exc

    try:
        if backend:
            return pyvisa.ResourceManager(backend)
        return pyvisa.ResourceManager()
    except Exception as exc:  # pragma: no cover - depends on local VISA backend
        raise VisaConnectionError("Could not create PyVISA resource manager") from exc


def list_resources(
    resource_manager: ResourceManagerLike | None = None,
    *,
    backend: str | None = None,
) -> tuple[str, ...]:
    manager = resource_manager or create_resource_manager(backend)
    try:
        return tuple(str(resource) for resource in manager.list_resources())
    except Exception as exc:
        raise VisaConnectionError("Could not list VISA resources") from exc


def open_resource(
    resource_name: str,
    resource_manager: ResourceManagerLike | None = None,
    *,
    backend: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    read_termination: str = DEFAULT_READ_TERMINATION,
    write_termination: str = DEFAULT_WRITE_TERMINATION,
) -> InstrumentSession:
    if not resource_name:
        raise ValueError("resource_name is required")
    if timeout_ms < 1:
        raise ValueError("timeout_ms must be at least 1")

    manager = resource_manager or create_resource_manager(backend)
    try:
        resource = manager.open_resource(resource_name)
        resource.timeout = timeout_ms
        resource.read_termination = read_termination
        resource.write_termination = write_termination
    except Exception as exc:
        raise VisaConnectionError(f"Could not open VISA resource {resource_name!r}") from exc

    return InstrumentSession(resource, resource_name=resource_name)


def _is_no_error(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")
