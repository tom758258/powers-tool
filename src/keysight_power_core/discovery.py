"""Adapter-neutral discovery commands."""

from __future__ import annotations

from typing import Any, Callable

from keysight_power_core.connection import list_resources, open_resource, serial_open_kwargs
from keysight_power_core.core import CoreIoError, CoreValidationError, OperationRequest
from keysight_power_core.errors import VisaConnectionError
from keysight_power_core.models import parse_idn, resource_interface
from keysight_power_core.operations import ScpiLoggingSession
from keysight_power_core.testing.simulator import SimulatedResourceManager

IDN_QUERY = "*IDN?"


def run_discovery(
    request: OperationRequest,
    *,
    resource_lister: Callable[..., tuple[str, ...]] = list_resources,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    if request.command == "list-resources":
        return _run_list_resources(request, resource_lister=resource_lister, opener=opener, scpi_logger=scpi_logger)
    if request.command == "verify":
        return _run_verify(request, opener=opener, scpi_logger=scpi_logger)
    raise CoreValidationError(f"unsupported discovery command {request.command!r}")


def _run_list_resources(
    request: OperationRequest,
    *,
    resource_lister: Callable[..., tuple[str, ...]],
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    try:
        resources = resource_lister(manager, backend=request.runtime.backend)
    except VisaConnectionError as exc:
        raise CoreIoError(f"Could not list VISA resources: {exc}", opened=False) from exc

    live_only = bool(request.parameters.get("live_only", False))
    if not live_only:
        payloads = [
            resource_payload(resource, simulated=request.runtime.simulate, reachable=None, idn_raw=None)
            for resource in resources
        ]
        return {"resources": payloads, "count": len(payloads)}

    live: list[dict[str, Any]] = []
    for resource in resources:
        idn = _query_idn(request, resource, opener=opener, manager=manager, scpi_logger=scpi_logger)
        if idn is not None:
            live.append(resource_payload(resource, simulated=request.runtime.simulate, reachable=True, idn_raw=idn))
    return {"resources": live, "count": len(live)}


def _run_verify(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    resource = request.runtime.resource
    if not resource:
        raise CoreValidationError("resource is required")
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    idn = _query_idn(request, resource, opener=opener, manager=manager, scpi_logger=scpi_logger)
    if idn is None:
        raise CoreIoError(f"Could not verify VISA resource: {resource}", opened=False)
    return {
        "resource": resource_payload(
            resource,
            simulated=request.runtime.simulate,
            reachable=True,
            idn_raw=idn,
        )
    }


def _query_idn(
    request: OperationRequest,
    resource: str,
    *,
    opener: Callable[..., Any],
    manager: SimulatedResourceManager | None,
    scpi_logger: Callable[[str, str, str], None] | None,
) -> str | None:
    try:
        with opener(
            resource,
            manager,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            **serial_open_kwargs(
                serial_options=request.runtime.serial_options,
                serial_remote=request.runtime.serial_remote,
                serial_local_on_close=request.runtime.serial_local_on_close,
            ),
        ) as instrument:
            session = (
                ScpiLoggingSession(resource, instrument, scpi_logger)
                if request.runtime.log_scpi and scpi_logger is not None
                else instrument
            )
            return session.query(IDN_QUERY).strip()
    except (VisaConnectionError, ValueError):
        return None


def resource_payload(
    name: str,
    *,
    simulated: bool,
    reachable: bool | None,
    idn_raw: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "interface": resource_interface(name),
        "simulated": simulated,
        "reachable": reachable,
        "idn": parse_idn(idn_raw).to_dict() if idn_raw is not None else None,
    }
