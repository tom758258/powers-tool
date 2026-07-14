"""Signed capabilities for the internal validation distribution.

This module is intentionally an internal implementation detail.  The wrapper
issues signed run/case documents and the CLI verifies and consumes them before
Core is allowed to admit a validation-only command candidate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from powers_tool_core.core import ValidationCandidateContext
from powers_tool_core.capabilities import command_support
from powers_tool_validation.build_identity import verified_candidate_context

SCHEMA_VERSION = 1
SECRET_ENVIRONMENT_VARIABLE = "POWERS_TOOL_VALIDATION_RUN_SECRET"
_CAPABILITY_ID_PATTERN = re.compile(r"^[0-9a-f]{32,128}$")
_MIN_RUN_SECONDS = 30 * 60
_MAX_RUN_SECONDS = 4 * 60 * 60
_MAX_CASE_SECONDS = 15 * 60
_MIN_CASE_SECONDS = 60
_MAX_CLOCK_SKEW_SECONDS = 60
_HIDDEN_ARGUMENTS = frozenset(
    {
        "--validation-candidate-manifest",
        "--validation-candidate-capability",
        "--validation-candidate-context-root",
        "--validation-candidate-case-id",
        "--validation-candidate-suite",
    }
)


class CandidateCapabilityError(ValueError):
    """Raised when a signed candidate manifest/capability is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize one signed value using the shared canonical JSON contract."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateCapabilityError("candidate capability contains invalid JSON values") from exc
    return text.encode("utf-8")


def request_fingerprint(argv: Iterable[str]) -> str:
    """Return the SHA-256 fingerprint of the effective invocation arguments."""

    normalized: list[str] = []
    arguments = list(argv)
    index = 0
    while index < len(arguments):
        argument = str(arguments[index])
        if argument in _HIDDEN_ARGUMENTS:
            index += 2
            continue
        normalized.append(argument)
        index += 1
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def _signature(payload: dict[str, Any], secret: bytes) -> str:
    if not secret:
        raise CandidateCapabilityError("candidate capability secret is missing")
    return hmac.new(secret, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


def _signed_payload(document: dict[str, Any], field: str) -> tuple[dict[str, Any], str]:
    if not isinstance(document, dict):
        raise CandidateCapabilityError("candidate capability document is malformed")
    signature = document.get(field)
    if not isinstance(signature, str) or not signature:
        raise CandidateCapabilityError("candidate capability signature is missing")
    payload = dict(document)
    payload.pop(field, None)
    return payload, signature


def _verify_signature(document: dict[str, Any], field: str, secret: bytes) -> dict[str, Any]:
    payload, supplied = _signed_payload(document, field)
    expected = _signature(payload, secret)
    if not hmac.compare_digest(supplied, expected):
        raise CandidateCapabilityError("candidate capability signature is invalid")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateCapabilityError("candidate capability document is missing or malformed") from exc
    if not isinstance(value, dict):
        raise CandidateCapabilityError("candidate capability document is malformed")
    return value


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CandidateCapabilityError(f"candidate capability {field} timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateCapabilityError(f"candidate capability {field} timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise CandidateCapabilityError(f"candidate capability {field} timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _validate_time_window(
    document: dict[str, Any],
    *,
    maximum_seconds: int,
    now: datetime | None = None,
) -> None:
    issued = _parse_timestamp(document.get("issued_at"), "issued_at")
    expires = _parse_timestamp(document.get("expires_at"), "expires_at")
    if expires <= issued:
        raise CandidateCapabilityError("candidate capability time range is invalid")
    if expires - issued > timedelta(seconds=maximum_seconds):
        raise CandidateCapabilityError("candidate capability expiry is too long")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if issued > current + timedelta(seconds=_MAX_CLOCK_SKEW_SECONDS):
        raise CandidateCapabilityError("candidate capability is issued in the future")
    if expires < current:
        raise CandidateCapabilityError("candidate capability has expired")


def _validate_manifest_payload(payload: dict[str, Any], private_root: Path | None = None) -> None:
    required = {
        "schema_version",
        "run_id",
        "target_model_id",
        "selected_suite",
        "selected_suites",
        "transport_scope",
        "backend_scope",
        "private_run_directory_identity",
        "issued_at",
        "expires_at",
        "candidate_cases",
    }
    if set(payload) != required or payload.get("schema_version") != SCHEMA_VERSION:
        raise CandidateCapabilityError("candidate run manifest is malformed")
    if not all(isinstance(payload.get(key), str) and payload.get(key) for key in required - {"schema_version", "selected_suites", "candidate_cases"}):
        raise CandidateCapabilityError("candidate run manifest is malformed")
    if not isinstance(payload["selected_suites"], list) or not all(isinstance(item, str) and item for item in payload["selected_suites"]):
        raise CandidateCapabilityError("candidate run manifest suites are malformed")
    cases = payload["candidate_cases"]
    if not isinstance(cases, list) or not cases:
        raise CandidateCapabilityError("candidate run manifest candidate inventory is malformed")
    if private_root is not None:
        expected = private_root.resolve()
        actual = Path(str(payload["private_run_directory_identity"])).resolve()
        if actual != expected:
            raise CandidateCapabilityError("candidate run manifest private directory does not match")
    _validate_time_window(payload, maximum_seconds=_MAX_RUN_SECONDS)
    seen: set[str] = set()
    seen_capabilities: set[str] = set()
    for entry in cases:
        if not isinstance(entry, dict):
            raise CandidateCapabilityError("candidate run manifest case entry is malformed")
        entry_required = {
            "case_id",
            "suite",
            "command",
            "model_id",
            "transport_scope",
            "backend_scope",
            "state_changing",
            "arguments",
            "request_fingerprint",
            "capability_id",
        }
        if set(entry) != entry_required:
            raise CandidateCapabilityError("candidate run manifest case entry is malformed")
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise CandidateCapabilityError("candidate run manifest case ID is invalid")
        seen.add(case_id)
        if not all(isinstance(entry.get(key), str) and entry.get(key) for key in entry_required - {"state_changing", "arguments"}):
            raise CandidateCapabilityError("candidate run manifest case entry is malformed")
        if not isinstance(entry["state_changing"], bool) or not isinstance(entry["arguments"], list) or not all(isinstance(item, str) for item in entry["arguments"]):
            raise CandidateCapabilityError("candidate run manifest case arguments are malformed")
        capability = command_support(entry["model_id"]).get(entry["command"])
        if capability is None or entry["state_changing"] is not bool(
            capability.get("requires_confirm")
        ):
            raise CandidateCapabilityError(
                "candidate run manifest state-changing classification is invalid"
            )
        if entry["request_fingerprint"] != request_fingerprint(entry["arguments"]):
            raise CandidateCapabilityError("candidate run manifest request fingerprint is invalid")
        if not _CAPABILITY_ID_PATTERN.fullmatch(entry["capability_id"]):
            raise CandidateCapabilityError("candidate run manifest capability ID is invalid")
        if entry["capability_id"] in seen_capabilities:
            raise CandidateCapabilityError("candidate run manifest capability ID is duplicated")
        seen_capabilities.add(entry["capability_id"])


def verify_manifest(document: dict[str, Any], secret: bytes, *, private_root: Path | None = None) -> dict[str, Any]:
    payload = _verify_signature(document, "manifest_signature", secret)
    _validate_manifest_payload(payload, private_root=private_root)
    return payload


def issue_manifest(input_path: Path, output_path: Path, secret: bytes) -> None:
    payload = _read_json(input_path)
    for entry in payload.get("candidate_cases", []):
        if isinstance(entry, dict) and not entry.get("request_fingerprint"):
            entry["request_fingerprint"] = request_fingerprint(entry.get("arguments", []))
    _validate_manifest_payload(payload)
    issued = _parse_timestamp(payload["issued_at"], "issued_at")
    expires = _parse_timestamp(payload["expires_at"], "expires_at")
    if expires - issued < timedelta(seconds=_MIN_RUN_SECONDS):
        raise CandidateCapabilityError("candidate run manifest expiry is too short")
    document = dict(payload)
    document["manifest_signature"] = _signature(payload, secret)
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def issue_capability(manifest_path: Path, output_path: Path, case_id: str, secret: bytes) -> None:
    document = _read_json(manifest_path)
    payload = verify_manifest(document, secret, private_root=manifest_path.parent)
    entries = [entry for entry in payload["candidate_cases"] if entry["case_id"] == case_id]
    if len(entries) != 1:
        raise CandidateCapabilityError("candidate case is not present in the signed run manifest")
    entry = dict(entries[0])
    issued_at = datetime.now(timezone.utc)
    manifest_expires = _parse_timestamp(payload["expires_at"], "expires_at")
    expires_at = min(issued_at + timedelta(seconds=_MAX_CASE_SECONDS), manifest_expires)
    if expires_at - issued_at < timedelta(seconds=_MIN_CASE_SECONDS):
        raise CandidateCapabilityError("candidate run manifest is too near expiry")
    capability_payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": payload["run_id"],
        "case_id": entry["case_id"],
        "suite": entry["suite"],
        "model_id": entry["model_id"],
        "command": entry["command"],
        "transport_scope": entry["transport_scope"],
        "backend_scope": entry["backend_scope"],
        "state_changing": entry["state_changing"],
        "arguments": entry["arguments"],
        "request_fingerprint": entry["request_fingerprint"],
        "capability_id": entry["capability_id"],
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "private_run_directory_identity": payload["private_run_directory_identity"],
        "manifest_path": str(manifest_path.resolve()),
        "manifest_signature": document["manifest_signature"],
    }
    capability = dict(capability_payload)
    capability["capability_signature"] = _signature(capability_payload, secret)
    output_path.write_text(json.dumps(capability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _consume_marker(private_root: Path, capability_id: str) -> None:
    consumed_dir = private_root / ".candidate-consumed"
    consumed_dir.mkdir(parents=True, exist_ok=True)
    marker = consumed_dir / f"{capability_id}.marker"
    try:
        descriptor = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise CandidateCapabilityError("candidate capability has already been consumed") from exc
    try:
        os.write(descriptor, b"consumed\n")
    finally:
        os.close(descriptor)


def consume_and_verify(
    manifest_path: Path,
    capability_path: Path,
    private_root: Path,
    secret: bytes,
    *,
    argv: Iterable[str],
    command: str,
    expected_case_id: str | None = None,
    expected_suite: str | None = None,
) -> ValidationCandidateContext:
    root = private_root.resolve()
    manifest = manifest_path.resolve()
    capability_file = capability_path.resolve()
    if manifest.parent != root or capability_file.parent != root:
        raise CandidateCapabilityError("candidate capability path is outside the private run directory")
    manifest_document = _read_json(manifest)
    manifest_payload = verify_manifest(manifest_document, secret, private_root=root)
    capability_document = _read_json(capability_file)
    capability_payload = _verify_signature(capability_document, "capability_signature", secret)
    required = {
        "schema_version", "run_id", "case_id", "suite", "model_id", "command",
        "transport_scope", "backend_scope", "state_changing", "arguments",
        "request_fingerprint", "capability_id", "issued_at", "expires_at",
        "private_run_directory_identity", "manifest_path", "manifest_signature",
    }
    if set(capability_payload) != required or capability_payload.get("schema_version") != SCHEMA_VERSION:
        raise CandidateCapabilityError("candidate capability is malformed")
    _validate_time_window(capability_payload, maximum_seconds=_MAX_CASE_SECONDS)
    if capability_payload["manifest_path"] != str(manifest):
        raise CandidateCapabilityError("candidate capability manifest does not match")
    manifest_signature = manifest_document.get("manifest_signature")
    if not isinstance(manifest_signature, str) or not hmac.compare_digest(
        capability_payload["manifest_signature"], manifest_signature
    ):
        raise CandidateCapabilityError("candidate capability manifest signature does not match")
    if expected_case_id is not None and capability_payload["case_id"] != expected_case_id:
        raise CandidateCapabilityError("candidate capability case does not match")
    if expected_suite is not None and capability_payload["suite"] != expected_suite:
        raise CandidateCapabilityError("candidate capability suite does not match")
    matches = [entry for entry in manifest_payload["candidate_cases"] if entry["case_id"] == capability_payload["case_id"]]
    if len(matches) != 1 or capability_payload.get("run_id") != manifest_payload.get("run_id") or any(
        capability_payload.get(key) != matches[0].get(key)
        for key in (
            "suite", "model_id", "command", "transport_scope", "backend_scope",
            "state_changing", "arguments", "request_fingerprint", "capability_id",
        )
    ):
        raise CandidateCapabilityError("candidate capability is not an exact signed manifest case")
    if capability_payload["command"] != command:
        raise CandidateCapabilityError("candidate capability command does not match")
    actual_fingerprint = request_fingerprint(argv)
    if not hmac.compare_digest(actual_fingerprint, capability_payload["request_fingerprint"]):
        raise CandidateCapabilityError("candidate capability invocation does not match")
    _consume_marker(root, str(capability_payload["capability_id"]))
    try:
        capability_file.unlink(missing_ok=True)
    except OSError:
        pass
    return verified_candidate_context(
        run_id=capability_payload["run_id"],
        case_id=capability_payload["case_id"],
        suite=capability_payload["suite"],
        model_id=capability_payload["model_id"],
        command=capability_payload["command"],
        transport_scope=capability_payload["transport_scope"],
        backend_scope=capability_payload["backend_scope"],
        request_fingerprint=capability_payload["request_fingerprint"],
        capability_id=capability_payload["capability_id"],
        issued_at=capability_payload["issued_at"],
        expires_at=capability_payload["expires_at"],
    )


def secret_from_environment() -> bytes:
    value = os.environ.pop(SECRET_ENVIRONMENT_VARIABLE, None)
    if not isinstance(value, str) or not value:
        raise CandidateCapabilityError("candidate capability secret is missing")
    return value.encode("utf-8")


def _helper_main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    manifest = subparsers.add_parser("issue-manifest")
    manifest.add_argument("--input", required=True)
    manifest.add_argument("--output", required=True)
    capability = subparsers.add_parser("issue-capability")
    capability.add_argument("--manifest", required=True)
    capability.add_argument("--output", required=True)
    capability.add_argument("--case-id", required=True)
    args = parser.parse_args(argv)
    secret = secret_from_environment()
    if args.operation == "issue-manifest":
        issue_manifest(Path(args.input), Path(args.output), secret)
    else:
        issue_capability(Path(args.manifest), Path(args.output), args.case_id, secret)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_helper_main(os.sys.argv[1:]))
    except CandidateCapabilityError as exc:
        print(str(exc), file=os.sys.stderr)
        raise SystemExit(2)
