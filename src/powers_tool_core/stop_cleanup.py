"""Stop-only VISA session cleanup and structured cleanup results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from powers_tool_core.core import StopCleanupError

CleanupStatus = Literal["succeeded", "unsupported", "not_applicable", "failed"]
CleanupReporter = Callable[["StopCleanupResult"], None]


@dataclass(frozen=True)
class StopCleanupResult:
    operation: str
    status: CleanupStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


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
        if not self._stop_requested():
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

        failures = tuple(result.to_dict() for result in results if result.status == "failed")
        if failures:
            raise StopCleanupError("stop cleanup failed", results=tuple(result.to_dict() for result in results))
        return suppressed


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
