"""Cooperative cancellation helpers for long-running core commands."""

from __future__ import annotations

from typing import Callable

from powers_tool_core.core import CommandCancelled

StopRequested = Callable[[], bool] | None


def raise_if_cancelled(stop_requested: StopRequested) -> None:
    if stop_requested is not None and stop_requested():
        raise CommandCancelled("command cancelled")


def interruptible_sleep(
    seconds: float,
    *,
    sleep: Callable[[float], None],
    stop_requested: StopRequested,
    interval: float = 0.05,
) -> None:
    if seconds <= 0:
        raise_if_cancelled(stop_requested)
        return
    if stop_requested is None:
        sleep(seconds)
        return

    remaining = seconds
    while remaining > 0:
        raise_if_cancelled(stop_requested)
        chunk = min(remaining, interval)
        sleep(chunk)
        remaining -= chunk
    raise_if_cancelled(stop_requested)
