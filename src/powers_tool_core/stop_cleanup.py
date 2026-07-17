"""Cooperative stop cleanup and structured cleanup results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from powers_tool_core.core import CommandCancelled, StopCleanupError

CleanupStatus = Literal["succeeded", "unsupported", "not_applicable", "failed"]
CleanupReporter = Callable[["StopCleanupResult"], None]


@dataclass(frozen=True)
class StopCleanupResult:
    operation: str
    status: CleanupStatus
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["details"] is None:
            payload.pop("details")
        return payload


WORKFLOW_CANCELLATION_COMMANDS = frozenset({"ramp", "ramp-list", "sequence"})
MAX_WORKFLOW_CLEANUP_ERROR_READS = 20


def stop_aware_opener(
    opener: Callable[..., Any],
    *,
    stop_requested: Callable[[], bool],
    simulated: bool,
    reporter: CleanupReporter | None = None,
) -> Callable[..., Any]:
    """Wrap an opener so stop-only cleanup runs around its session context."""

    def open_with_stop_cleanup(resource_name: str, *args: Any, **kwargs: Any) -> Any:
        context = opener(resource_name, *args, **kwargs)
        return StopAwareSessionContext(
            context,
            resource_name=resource_name,
            stop_requested=stop_requested,
            simulated=simulated,
            reporter=reporter,
        )

    return open_with_stop_cleanup


class StopAwareSessionContext:
    def __init__(
        self,
        context: Any,
        *,
        resource_name: str,
        stop_requested: Callable[[], bool],
        simulated: bool,
        reporter: CleanupReporter | None,
    ) -> None:
        self._context = context
        self._resource_name = resource_name
        self._stop_requested = stop_requested
        self._simulated = simulated
        self._reporter = reporter
        self._session: Any | None = None

    def __enter__(self) -> Any:
        self._session = self._context.__enter__()
        return self._session

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        cancellation_cleanup = isinstance(exc, (CommandCancelled, StopCleanupError))
        if not self._stop_requested() and not cancellation_cleanup:
            return bool(self._context.__exit__(exc_type, exc, tb))

        results: list[StopCleanupResult] = []
        results.append(
            release_to_local(
                self._session,
                resource_name=self._resource_name,
                simulated=self._simulated,
            )
        )
        try:
            suppressed = bool(self._context.__exit__(exc_type, exc, tb))
        except Exception as close_exc:
            suppressed = False
            results.append(StopCleanupResult("close_session", "failed", str(close_exc)))
        else:
            results.append(StopCleanupResult("close_session", "succeeded", "VISA session closed"))
        results.append(cleanup_release_to_local(results[0]))

        for result in results:
            if self._reporter is not None:
                self._reporter(result)

        prior_results = list(getattr(exc, "results", ()))
        if isinstance(exc, CommandCancelled):
            prior_results = list(exc.data.get("cleanup", ()))
        combined_results = prior_results + [result.to_dict() for result in results]
        failures = tuple(result for result in combined_results if result.get("status") == "failed")
        if failures:
            data = {
                "status": "failed",
                "original_reason": "user_cancelled",
                "cleanup": combined_results,
            }
            partial_result = getattr(exc, "data", {}).get("partial_result") if exc is not None else None
            if partial_result is not None:
                data["partial_result"] = partial_result
            raise StopCleanupError(
                "workflow cancellation cleanup failed",
                results=tuple(combined_results),
                data=data,
            )
        if isinstance(exc, CommandCancelled):
            exc.data["cleanup"] = combined_results
        return suppressed


def cancel_workflow_with_safe_off(
    power_supply: Any,
    *,
    partial_result: dict[str, Any] | None = None,
    reporter: CleanupReporter | None = None,
) -> None:
    """Safe-off all channels on the current session, then raise cancellation."""

    results: list[StopCleanupResult] = []
    channels = tuple(power_supply.capabilities.channels)

    for channel in channels:
        try:
            power_supply.output_off(channel=channel)
        except Exception as exc:
            results.append(
                StopCleanupResult(
                    "output_off",
                    "failed",
                    str(exc),
                    {"channel": channel},
                )
            )
        else:
            results.append(
                StopCleanupResult(
                    "output_off",
                    "succeeded",
                    "output OFF requested",
                    {"channel": channel},
                )
            )

    for channel in channels:
        try:
            enabled = power_supply.output_state(channel=channel)
        except Exception as exc:
            results.append(
                StopCleanupResult(
                    "output_state",
                    "failed",
                    str(exc),
                    {"channel": channel, "expected_enabled": False},
                )
            )
        else:
            status: CleanupStatus = "succeeded" if enabled is False else "failed"
            message = "output OFF confirmed" if enabled is False else "output remained ON"
            results.append(
                StopCleanupResult(
                    "output_state",
                    status,
                    message,
                    {"channel": channel, "enabled": enabled, "expected_enabled": False},
                )
            )

    try:
        errors, read_count = power_supply.read_error_queue(MAX_WORKFLOW_CLEANUP_ERROR_READS)
    except Exception as exc:
        results.append(
            StopCleanupResult(
                "error_queue",
                "failed",
                str(exc),
                {"max_reads": MAX_WORKFLOW_CLEANUP_ERROR_READS},
            )
        )
    else:
        limit_reached = read_count >= MAX_WORKFLOW_CLEANUP_ERROR_READS and len(errors) >= read_count
        status = "failed" if errors or limit_reached else "succeeded"
        if limit_reached:
            message = "error queue did not reach a no-error sentinel before the read limit"
        elif errors:
            message = "instrument error queue contained errors during cancellation cleanup"
        else:
            message = "instrument error queue drained to no-error sentinel"
        results.append(
            StopCleanupResult(
                "error_queue",
                status,
                message,
                {
                    "max_reads": MAX_WORKFLOW_CLEANUP_ERROR_READS,
                    "read_count": read_count,
                    "errors": list(errors),
                    "no_error_sentinel_seen": not limit_reached,
                },
            )
        )

    for result in results:
        if reporter is not None:
            reporter(result)
    result_dicts = [result.to_dict() for result in results]
    data: dict[str, Any] = {
        "status": "cancelled",
        "cancelled_by_user": True,
        "original_reason": "user_cancelled",
        "cleanup": result_dicts,
    }
    if partial_result is not None:
        data["partial_result"] = partial_result
    if any(result.status == "failed" for result in results):
        data["status"] = "failed"
        raise StopCleanupError(
            "workflow cancellation cleanup failed",
            results=tuple(result_dicts),
            data=data,
        )
    raise CommandCancelled("workflow cancelled by user", data=data)


def release_to_local(
    session: Any | None,
    *,
    resource_name: str | None,
    simulated: bool,
) -> StopCleanupResult:
    if simulated:
        return StopCleanupResult("release_to_local", "not_applicable", "simulated session")
    if session is None:
        return StopCleanupResult("release_to_local", "not_applicable", "no open VISA session")
    if not str(resource_name or "").upper().startswith("GPIB"):
        return StopCleanupResult("release_to_local", "unsupported", "release to local is supported only for GPIB")

    release = getattr(session, "release_to_local", None)
    if not callable(release):
        return StopCleanupResult("release_to_local", "unsupported", "PyVISA session does not expose device-local control")
    try:
        release()
    except NotImplementedError as exc:
        return StopCleanupResult("release_to_local", "unsupported", str(exc))
    except Exception as exc:
        return StopCleanupResult("release_to_local", "failed", str(exc))
    return StopCleanupResult("release_to_local", "succeeded", "GPIB device released to local control")


def cleanup_release_to_local(release_result: StopCleanupResult) -> StopCleanupResult:
    """Report post-close bookkeeping without accessing the closed session."""

    return StopCleanupResult(
        "cleanup_release_to_local",
        "succeeded",
        f"post-close cleanup recorded release_to_local={release_result.status}",
    )
