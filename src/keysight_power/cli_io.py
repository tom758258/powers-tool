"""Small output helpers for human-readable and JSON CLI modes."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

SCHEMA_VERSION = "1.0"


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
            data=None,
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
        "metadata": metadata or {},
    }


def _emit(payload: dict[str, Any], stream: TextIO) -> None:
    print(json.dumps(payload, sort_keys=True), file=stream)
