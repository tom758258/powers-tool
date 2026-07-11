"""VISA connection helpers and a small instrument session wrapper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.models import resource_interface
from powers_tool_core.transport import ResourceManagerLike

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_READ_TERMINATION = "\n"
DEFAULT_WRITE_TERMINATION = "\n"
SERIAL_TERMINATION_ALIASES = {
    "CR": "\r",
    "LF": "\n",
    "CRLF": "\r\n",
}


@dataclass(frozen=True)
class SerialOptions:
    """Optional ASRL settings to apply only when explicitly requested."""

    baud_rate: int | None = None
    data_bits: int | None = None
    parity: str | None = None
    stop_bits: float | int | str | None = None
    flow_control: str | None = None
    read_termination: str | None = None
    write_termination: str | None = None

    def has_explicit_values(self) -> bool:
        return any(
            value is not None
            for value in (
                self.baud_rate,
                self.data_bits,
                self.parity,
                self.stop_bits,
                self.flow_control,
                self.read_termination,
                self.write_termination,
            )
        )


def normalize_serial_termination(value: Any) -> str | None:
    """Normalize user-facing termination aliases before building SerialOptions."""

    if value is None:
        return None
    text = str(value)
    if text == "":
        return None
    normalized = text.strip().upper()
    if normalized == "NONE":
        return None
    return SERIAL_TERMINATION_ALIASES.get(normalized, text)


class InstrumentSession:
    """Thin wrapper around a VISA resource."""

    def __init__(
        self,
        resource: Any,
        resource_name: str | None = None,
        *,
        serial_local_on_close: bool = False,
        scpi_logger: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._resource = resource
        self.resource_name = resource_name
        self._serial_local_on_close = serial_local_on_close
        self._scpi_logger = scpi_logger
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

    def release_to_local(self) -> None:
        """Release only this GPIB device to local control when PyVISA supports it."""

        self._ensure_open()
        control_ren = getattr(self._resource, "control_ren", None)
        if not callable(control_ren):
            raise NotImplementedError("PyVISA resource does not support device-local control")
        try:
            from pyvisa.constants import RENLineOperation
        except (ImportError, AttributeError) as exc:
            raise NotImplementedError("PyVISA does not expose RENLineOperation.address_gtl") from exc
        control_ren(RENLineOperation.address_gtl)

    def close(self) -> None:
        if self._closed:
            return

        try:
            if self._serial_local_on_close:
                try:
                    _log_scpi(self._scpi_logger, self.resource_name, ">>", "SYST:LOC")
                    self._resource.write("SYST:LOC")
                except Exception:
                    pass
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
    serial_options: SerialOptions | None = None,
    serial_remote: bool = False,
    serial_local_on_close: bool = False,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> InstrumentSession:
    if not resource_name:
        raise ValueError("resource_name is required")
    if timeout_ms < 1:
        raise ValueError("timeout_ms must be at least 1")
    if (serial_remote or serial_local_on_close) and resource_interface(resource_name) != "ASRL":
        raise ValueError("serial remote/local flags can only be used with ASRL resources")

    manager = resource_manager or create_resource_manager(backend)
    resource = None
    try:
        resource = manager.open_resource(resource_name)
        resource.timeout = timeout_ms
        if resource_interface(resource_name) != "ASRL":
            resource.read_termination = read_termination
            resource.write_termination = write_termination
        _apply_serial_options(resource, resource_name, serial_options)
        if serial_remote:
            _log_scpi(scpi_logger, resource_name, ">>", "SYST:REM")
            resource.write("SYST:REM")
    except Exception as exc:
        if resource is not None:
            if serial_remote:
                try:
                    _log_scpi(scpi_logger, resource_name, ">>", "SYST:LOC")
                    resource.write("SYST:LOC")
                except Exception:
                    pass
            try:
                resource.close()
            except Exception:
                pass
        raise VisaConnectionError(f"Could not open VISA resource {resource_name!r}") from exc

    return InstrumentSession(
        resource,
        resource_name=resource_name,
        serial_local_on_close=serial_local_on_close,
        scpi_logger=scpi_logger,
    )


def _is_no_error(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")


def _log_scpi(
    scpi_logger: Callable[[str, str, str], None] | None,
    resource_name: str | None,
    direction: str,
    payload: str,
) -> None:
    if scpi_logger is not None and resource_name is not None:
        scpi_logger(resource_name, direction, payload)


def serial_open_kwargs(
    *,
    serial_options: SerialOptions | None,
    serial_remote: bool,
    serial_local_on_close: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if serial_options is not None:
        kwargs["serial_options"] = serial_options
    if serial_remote:
        kwargs["serial_remote"] = True
    if serial_local_on_close:
        kwargs["serial_local_on_close"] = True
    return kwargs


def _apply_serial_options(resource: Any, resource_name: str, options: SerialOptions | None) -> None:
    if options is None or not options.has_explicit_values():
        return
    if resource_interface(resource_name) != "ASRL":
        raise ValueError("serial options can only be applied to ASRL resources")

    assignments = {
        "baud_rate": options.baud_rate,
        "data_bits": options.data_bits,
        "parity": _pyvisa_parity(options.parity),
        "stop_bits": _pyvisa_stop_bits(options.stop_bits),
        "flow_control": _pyvisa_flow_control(options.flow_control),
        "read_termination": options.read_termination,
        "write_termination": options.write_termination,
    }
    for name, value in assignments.items():
        if value is not None:
            setattr(resource, name, value)


def _pyvisa_parity(value: str | None) -> Any:
    if value is None:
        return None
    normalized = value.strip().lower()
    aliases = {
        "none": "none",
        "n": "none",
        "odd": "odd",
        "o": "odd",
        "even": "even",
        "e": "even",
        "mark": "mark",
        "m": "mark",
        "space": "space",
        "s": "space",
    }
    if normalized not in aliases:
        raise ValueError("serial parity must be none, odd, even, mark, or space")
    return _pyvisa_constant("Parity", aliases[normalized], fallback=aliases[normalized])


def _pyvisa_stop_bits(value: float | int | str | None) -> Any:
    if value is None:
        return None
    normalized = str(value).strip()
    aliases = {"1": "one", "1.0": "one", "1.5": "one_and_a_half", "2": "two", "2.0": "two"}
    if normalized not in aliases:
        raise ValueError("serial stop bits must be 1, 1.5, or 2")
    return _pyvisa_constant("StopBits", aliases[normalized], fallback=value)


def _pyvisa_flow_control(value: str | None) -> Any:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "none": "none",
        "xon_xoff": "xon_xoff",
        "xonxoff": "xon_xoff",
        "rts_cts": "rts_cts",
        "rtscts": "rts_cts",
        "dtr_dsr": "dtr_dsr",
        "dtrdsr": "dtr_dsr",
    }
    if normalized not in aliases:
        raise ValueError("serial flow control must be none, xon_xoff, rts_cts, or dtr_dsr")
    return _pyvisa_constant("ControlFlow", aliases[normalized], fallback=aliases[normalized])


def _pyvisa_constant(type_name: str, member: str, *, fallback: Any) -> Any:
    try:
        import pyvisa.constants as constants
    except ImportError:
        return fallback
    enum_type = getattr(constants, type_name, None)
    if enum_type is None:
        return fallback
    return getattr(enum_type, member, fallback)
