"""Small output helpers for human-readable and JSON CLI modes."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

SCHEMA_VERSION = "1.0"
JSON_SAVE_PATH: str | None = None
JSON_START_TIME: float | None = None


class JsonSaveError(OSError):
    """Raised when a JSON envelope cannot be saved to disk."""


def set_json_save_path(path: str | None) -> None:
    global JSON_SAVE_PATH
    JSON_SAVE_PATH = path


def set_json_start_time(start_time: float | None) -> None:
    global JSON_START_TIME
    JSON_START_TIME = start_time


def emit_json_success(
    *,
    command: str,
    execution: dict[str, Any],
    request: dict[str, Any],
    data: dict[str, Any],
    warnings: list[dict[str, str]] | None = None,
    metadata: dict[str, Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    _emit(
        _envelope(
            ok=True,
            command=command,
            execution=execution,
            request=request,
            data=data,
            warnings=warnings,
            error=None,
            metadata=metadata,
        ),
        stream or sys.stdout,
    )


def emit_json_error(
    *,
    command: str,
    execution: dict[str, Any],
    request: dict[str, Any],
    error_type: str,
    code: str,
    message: str,
    retryable: bool,
    data: dict[str, Any] | None = None,
    warnings: list[dict[str, str]] | None = None,
    metadata: dict[str, Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    _emit(
        _envelope(
            ok=False,
            command=command,
            execution=execution,
            request=request,
            data=data,
            warnings=warnings,
            error={
                "type": error_type,
                "code": code,
                "message": message,
                "retryable": retryable,
            },
            metadata=metadata,
        ),
        stream or sys.stdout,
    )


def _envelope(
    *,
    ok: bool,
    command: str,
    execution: dict[str, Any],
    request: dict[str, Any],
    data: dict[str, Any] | None,
    warnings: list[dict[str, str]] | None,
    error: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    envelope_metadata = dict(metadata or {})
    if "duration_ms" not in envelope_metadata:
        envelope_metadata["duration_ms"] = _duration_ms()
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "status": "ok" if ok else "error",
        "command": {"name": command},
        "execution": execution,
        "request": request,
        "data": data,
        "warnings": warnings or [],
        "error": error,
        "metadata": envelope_metadata,
    }


def _emit(payload: dict[str, Any], stream: TextIO) -> None:
    encoded = json.dumps(payload, sort_keys=True)
    if JSON_SAVE_PATH is not None:
        try:
            path = Path(JSON_SAVE_PATH)
            if path.parent != Path("."):
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{encoded}\n", encoding="utf-8")
        except OSError as exc:
            raise JsonSaveError(str(exc)) from exc
    print(encoded, file=stream)


def _duration_ms() -> float:
    if JSON_START_TIME is None:
        return 0.0
    return max(0.0, round((time.perf_counter() - JSON_START_TIME) * 1000, 3))
