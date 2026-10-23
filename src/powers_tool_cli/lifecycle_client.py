"""Worker lifecycle HTTP client commands."""

from __future__ import annotations

import argparse
import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def run_send_command(args: argparse.Namespace) -> int:
    try:
        arguments = json.loads(args.arguments_json)
    except json.JSONDecodeError as exc:
        return _lifecycle_error(args, 2, "argument_error", f"--arguments-json must be a JSON object: {exc}")
    if not isinstance(arguments, dict):
        return _lifecycle_error(args, 2, "argument_error", "--arguments-json must be a JSON object")
    from powers_tool_cli.worker_protocol import (
        WORKER_SCHEMA_VERSION,
        validate_worker_argument_context_fields,
        validate_worker_context,
    )

    try:
        validate_worker_argument_context_fields(arguments)
    except ValueError as exc:
        return _lifecycle_error(args, 2, "argument_error", str(exc))
    try:
        context = json.loads(args.context_json)
    except json.JSONDecodeError as exc:
        return _lifecycle_error(args, 2, "argument_error", f"--context-json must be a JSON object: {exc}")
    try:
        context = validate_worker_context(context)
    except ValueError as exc:
        return _lifecycle_error(args, 2, "argument_error", f"--context-json {exc}")

    payload: dict[str, Any] = {
        "schema_version": WORKER_SCHEMA_VERSION,
        "command": args.worker_command,
        "arguments": arguments,
        "context": context,
    }
    if args.job_id is not None:
        payload["job_id"] = args.job_id
    if args.dry_run:
        url = _lifecycle_url(args, "/command")
        diagnostics = _lifecycle_diagnostics(args, "POST", url, "/command")
        diagnostics.update({"request_sent": False, "reachable": None, "http_status": None, "error_phase": None})
        return _lifecycle_output(args, {"ok": True, "request": payload, **diagnostics})
    url = _lifecycle_url(args, "/command")
    if url is None:
        return _lifecycle_error(args, 2, "argument_error", "--port is required when --url is omitted")
    response = _worker_http_json(args, "POST", url, payload)
    return _lifecycle_response_exit(args, response)


def run_worker_status_client(args: argparse.Namespace) -> int:
    url = _lifecycle_url(args, "/status")
    if args.dry_run:
        diagnostics = _lifecycle_diagnostics(args, "GET", url, "/status")
        diagnostics.update({"request_sent": False, "reachable": None, "http_status": None, "error_phase": None})
        return _lifecycle_output(args, {"ok": True, **diagnostics})
    if url is None:
        return _lifecycle_error(args, 2, "argument_error", "--port is required when --url is omitted")
    response = _worker_http_json(args, "GET", url, None)
    return _lifecycle_response_exit(args, response)


def run_worker_stop_client(args: argparse.Namespace) -> int:
    url = _lifecycle_url(args, "/stop")
    if url is None:
        return _lifecycle_error(args, 2, "argument_error", "--port is required when --url is omitted")
    response = _worker_http_json(args, "POST", url, {"schema_version": 3, "reason": args.reason})
    return _lifecycle_response_exit(args, response)


def run_wait_ready_client(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + (args.wait_timeout_ms / 1000.0)
    last: dict[str, Any] | None = None
    url = _lifecycle_url(args, "/status")
    if url is None:
        return _lifecycle_error(args, 2, "argument_error", "--port is required when --url is omitted")
    while time.monotonic() <= deadline:
        response = _worker_http_json(args, "GET", url, None, quiet_errors=True)
        if response.get("_http_ok"):
            last = response["data"]
            if isinstance(last, dict) and last.get("worker_state") == "running" and last.get("fatal_error") is None:
                return _lifecycle_output(args, last)
        elif response.get("_diagnostics", {}).get("error_phase") == "invalid_response":
            return _lifecycle_response_exit(args, response)
        time.sleep(args.poll_ms / 1000.0)
    return _lifecycle_error(args, 3, "wait_timeout", "worker did not become ready before timeout", data=last)


def _lifecycle_url(args: argparse.Namespace, default_path: str) -> str | None:
    if getattr(args, "url", None):
        return args.url
    if not getattr(args, "port", 0):
        return None
    return f"http://{args.host}:{args.port}{default_path}"


def _worker_http_json(
    args: argparse.Namespace,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    *,
    quiet_errors: bool = False,
) -> dict[str, Any]:
    endpoint = urllib.parse.urlparse(url).path or None
    diagnostics = _lifecycle_diagnostics(args, method, url, endpoint)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout_ms / 1000.0) as res:
            body = res.read().decode("utf-8")
            elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
            if not body:
                return _invalid_lifecycle_response(
                    diagnostics,
                    res.status,
                    elapsed_ms,
                    "worker response body was empty",
                )
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                return _invalid_lifecycle_response(
                    diagnostics,
                    res.status,
                    elapsed_ms,
                    f"worker response was not valid JSON: {exc}",
                )
            if not isinstance(parsed, dict):
                return _invalid_lifecycle_response(
                    diagnostics,
                    res.status,
                    elapsed_ms,
                    "worker response JSON must be an object",
                )
            validation_error = _validate_lifecycle_success_response(args.command, res.status, parsed, payload)
            if validation_error is not None:
                return _invalid_lifecycle_response(diagnostics, res.status, elapsed_ms, validation_error)
            return {
                "_http_ok": True,
                "status_code": res.status,
                "data": parsed,
                "_diagnostics": {
                    **diagnostics,
                    "elapsed_ms": elapsed_ms,
                    "request_sent": True,
                    "reachable": True,
                    "http_status": res.status,
                    "error_phase": None,
                },
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except Exception:
            return _invalid_lifecycle_response(
                diagnostics, exc.code, elapsed_ms, "worker error body was not valid JSON"
            )
        if not isinstance(parsed, dict):
            return _invalid_lifecycle_response(
                diagnostics, exc.code, elapsed_ms, "worker error body JSON was not an object"
            )
        expected_status = "rejected" if exc.code in {409, 429} else "error"
        if (
            not _valid_version_and_run(parsed)
            or parsed.get("status") != expected_status
            or not _valid_common_error(parsed.get("error"))
        ):
            return _invalid_lifecycle_response(
                diagnostics,
                exc.code,
                elapsed_ms,
                "worker error response must contain a valid v3 error envelope",
            )
        if args.command == "send-command" and (
            any(field not in parsed for field in ("command", "job_id", "kind", "worker_job_id"))
            or parsed["worker_job_id"] is not None
            or parsed["command"] not in (None, payload.get("command"))
            or parsed["job_id"] not in (None, payload.get("job_id"))
            or parsed["kind"] not in (None, "async_job")
        ):
            return _invalid_lifecycle_response(
                diagnostics,
                exc.code,
                elapsed_ms,
                "worker command error response has invalid identity",
            )
        return {
            "_http_ok": False,
            "status_code": exc.code,
            "data": parsed,
            "_diagnostics": {
                **diagnostics,
                "elapsed_ms": elapsed_ms,
                "request_sent": True,
                "reachable": True,
                "http_status": exc.code,
                "error_phase": "http_status",
            },
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        error_data = {"error": {"code": "connection_failed", "message": str(exc)}}
        response = {
            "_http_ok": False,
            "status_code": None,
            "data": error_data,
            "_diagnostics": {
                **diagnostics,
                "elapsed_ms": elapsed_ms,
                "request_sent": True,
                "reachable": False,
                "http_status": None,
                "error_phase": "connection",
            },
        }
        if quiet_errors:
            return response
        return response


def _invalid_lifecycle_response(
    diagnostics: dict[str, Any],
    status_code: int,
    elapsed_ms: float,
    message: str,
) -> dict[str, Any]:
    return {
        "_http_ok": False,
        "status_code": status_code,
        "data": {"error": {"code": "invalid_response", "message": message}},
        "_diagnostics": {
            **diagnostics,
            "elapsed_ms": elapsed_ms,
            "request_sent": True,
            "reachable": True,
            "http_status": status_code,
            "error_phase": "invalid_response",
        },
    }


def _validate_lifecycle_success_response(
    command: str,
    status_code: int,
    data: dict[str, Any],
    payload: dict[str, Any] | None,
) -> str | None:
    expected_status = {
        "send-command": (202,),
        "stop": (200, 202),
        "status": (200,),
        "wait-ready": (200,),
    }.get(command)
    if expected_status is None:
        return "worker response command was not recognized"
    if status_code not in expected_status:
        return f"worker response status {status_code} was not the expected {expected_status} for {command}"
    if command == "send-command":
        return _validate_accepted_command_response(data, payload or {})
    if command == "stop":
        if (
            not _valid_version_and_run(data)
            or data.get("status") != "accepted"
            or "error" not in data
            or data["error"] is not None
        ):
            return "worker stop response must contain a valid v3 acknowledgement"
        return None
    return _validate_worker_status_response(data)


def _validate_accepted_command_response(
    data: dict[str, Any], payload: dict[str, Any]
) -> str | None:
    if not _valid_version_and_run(data):
        return "worker command response must contain integer schema_version: 3 and run_id"
    if data.get("status") != "accepted":
        return "worker command response must contain status: accepted"
    if data.get("command") != payload.get("command"):
        return "worker command response command did not match the submitted command"
    if "job_id" not in data or data["job_id"] != payload.get("job_id"):
        return "worker command response job_id did not match the submitted job_id"
    if data.get("kind") != "async_job" or "error" not in data or data["error"] is not None:
        return "worker command response must identify an accepted async job without error"
    if not _is_nonempty_string(data.get("worker_job_id")):
        return "worker command response must contain a non-empty worker_job_id"
    if "artifact_path" in data and not _is_nonempty_string(data["artifact_path"]):
        return "worker command response artifact_path must be non-empty when present"
    return None


def _validate_worker_status_response(data: dict[str, Any]) -> str | None:
    if not _valid_version_and_run(data):
        return "worker status response must contain integer schema_version: 3 and run_id"
    if data.get("service") != "powers-tool":
        return "worker status response must contain service: powers-tool"
    if data.get("worker_state") not in ("starting", "running", "stopping", "failed"):
        return "worker status response contained an unknown worker_state"
    if not _valid_utc_timestamp(data.get("timestamp_utc")) or "fatal_error" not in data:
        return "worker status response must contain timestamp_utc and fatal_error"
    if data.get("fatal_error") is not None and not _valid_common_error(data["fatal_error"]):
        return "worker status response fatal_error is invalid"
    if data["worker_state"] == "failed" and data["fatal_error"] is None:
        return "failed worker status requires fatal_error"
    origin = None
    for field, path in (
        ("status_url", "/status"),
        ("command_url", "/command"),
        ("stop_url", "/stop"),
        ("cancel_url", "/cancel"),
    ):
        if not _is_nonempty_string(data.get(field)):
            return f"worker status response must contain a valid {field}"
        try:
            url = urllib.parse.urlparse(data[field])
            current_origin = (url.scheme, url.hostname, url.port or 80)
            if (
                url.scheme != "http"
                or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.port == 0
                or url.path != path
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
            ):
                return f"worker status response must contain a valid {field}"
        except ValueError:
            return f"worker status response must contain a valid {field}"
        if origin is not None and current_origin != origin:
            return "worker status response URLs must share one origin"
        origin = current_origin
    features = data.get("features")
    if not isinstance(features, dict):
        return "worker status response has invalid runtime features"
    for name in ("common.async_jobs", "common.job_cancel"):
        feature = features.get(name)
        if (
            not isinstance(feature, dict)
            or type(feature.get("contract_version")) is not int
            or feature["contract_version"] != 1
        ):
            return "worker status response has invalid runtime features"
    commands = features["common.job_cancel"].get("commands")
    if (
        not isinstance(commands, list)
        or any(not isinstance(command, str) for command in commands)
        or len(commands) != 4
        or set(commands) != {"ramp", "ramp-list", "sequence", "log"}
    ):
        return "worker status response has invalid cancellation commands"
    if "common.streaming" in features:
        return "worker status response declares unsupported streaming"
    if "active_job" not in data or "last_job" not in data:
        return "worker status response must contain job snapshots"
    for field in ("active_job", "last_job"):
        if data[field] is not None and not _valid_job_snapshot(
            data[field], terminal=field == "last_job"
        ):
            return f"worker status response contained an invalid {field} snapshot"
    if data.get("status") not in ("ready", "busy", "stopping", "error"):
        return "worker status response contained an unknown status"
    return None


def _valid_version_and_run(data: dict[str, Any]) -> bool:
    return (
        type(data.get("schema_version")) is int
        and data["schema_version"] == 3
        and _is_nonempty_string(data.get("run_id"))
    )


def _valid_common_error(error: Any) -> bool:
    return (
        isinstance(error, dict)
        and error.get("category") in ("validation", "admission", "execution", "worker")
        and _is_nonempty_string(error.get("code"))
        and _is_nonempty_string(error.get("message"))
        and isinstance(error.get("details"), dict)
    )


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).utcoffset() == datetime.timedelta(0)
    except ValueError:
        return False


def _valid_job_snapshot(job: Any, *, terminal: bool) -> bool:
    if (
        not isinstance(job, dict)
        or not _is_nonempty_string(job.get("worker_job_id"))
        or not _is_nonempty_string(job.get("command"))
        or "job_id" not in job
        or (job["job_id"] is not None and not isinstance(job["job_id"], str))
        or not _valid_utc_timestamp(job.get("timestamp_utc"))
    ):
        return False
    if not terminal:
        return job.get("state") in ("queued", "running")
    if (
        job.get("state") not in ("succeeded", "failed", "cancelled")
        or type(job.get("ok")) is not bool
        or "result" not in job
        or "error" not in job
    ):
        return False
    if job["state"] == "succeeded":
        return job["ok"] and job["error"] is None
    return not job["ok"] and (
        job["error"] is None and job["state"] == "cancelled" or _valid_common_error(job["error"])
    )


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _lifecycle_diagnostics(args: argparse.Namespace, method: str, url: str | None, endpoint: str | None) -> dict[str, Any]:
    return {
        "client_command": args.command,
        "method": method,
        "url": url,
        "endpoint": endpoint,
        "timeout_ms": getattr(args, "timeout_ms", None),
    }


def _lifecycle_response_exit(args: argparse.Namespace, response: dict[str, Any]) -> int:
    status_code = response.get("status_code")
    data = dict(response.get("data")) if isinstance(response.get("data"), dict) else {}
    diagnostics = response.get("_diagnostics") if isinstance(response.get("_diagnostics"), dict) else {}
    data.update(diagnostics)
    if response.get("_http_ok"):
        data.setdefault("ok", True)
        return _lifecycle_output(args, data)
    exit_code = 2 if status_code == 400 else 3
    data.setdefault("ok", False)
    data["exit_code"] = exit_code
    return _lifecycle_output(args, data, exit_code=exit_code)


def _lifecycle_output(args: argparse.Namespace, data: dict[str, Any], *, exit_code: int = 0) -> int:
    if getattr(args, "format", "text") == "json":
        print(json.dumps(data, sort_keys=True))
    else:
        if "status" in data:
            print(f"Status: {data['status']}")
        elif data.get("ok") is True:
            print("OK")
        else:
            print(json.dumps(data, sort_keys=True))
    return exit_code


def _lifecycle_error(args: argparse.Namespace, exit_code: int, code: str, message: str, *, data: Any = None) -> int:
    payload = {"status": "error", "error": {"code": code, "message": message}}
    if data is not None:
        payload["data"] = data
    return _lifecycle_output(args, payload, exit_code=exit_code)
