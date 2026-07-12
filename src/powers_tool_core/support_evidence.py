"""Immutable identities for accepted historical live-support evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType
from typing import Mapping

from powers_tool_core.identity import IdentityResolutionError, canonical_physical_model_id

SOURCE_AVAILABILITY_VERIFIED_LOCAL = "verified_local"
SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY = "historical_reference_only"

EVIDENCE_KIND_FULL_SUITE = "accepted_historical_full_suite"

_SOURCE_AVAILABILITY_STATES = frozenset(
    {
        SOURCE_AVAILABILITY_VERIFIED_LOCAL,
        SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY,
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PRIVATE_IPV4_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3})\b"
)

LEGACY_SYSTEM_VISA_INTERPRETATION = (
    "The historical wrapper omitted an explicit backend argument and used the "
    "default pyvisa.ResourceManager() system-VISA path. This does not validate "
    "pyvisa-py or a custom VISA backend."
)
EVIDENCE_MIGRATION_NOTE = (
    "Migrated from the accepted pre-V2 live-support baseline. The historical "
    "artifact remains immutable, and this identity migration is not new hardware validation."
)


@dataclass(frozen=True)
class SupportEvidenceRecord:
    """Stable, non-sensitive metadata for one historical evidence bundle."""

    evidence_id: str
    model_id: str
    transport_scope: str
    backend_scope: str
    evidence_date: str
    evidence_kind: str
    artifact_directory: str
    report_path: str
    summary_path: str
    legacy_model_name: str
    legacy_backend_interpretation: str
    artifact_schema_version: int | None
    report_sha256: str | None
    source_availability: str
    migration_note: str


def _historical_record(
    evidence_id: str,
    model_id: str,
    transport_scope: str,
    legacy_model_name: str,
    artifact_directory: str,
) -> SupportEvidenceRecord:
    return SupportEvidenceRecord(
        evidence_id=evidence_id,
        model_id=model_id,
        transport_scope=transport_scope,
        backend_scope="system_visa",
        evidence_date="2026-07-09",
        evidence_kind=EVIDENCE_KIND_FULL_SUITE,
        artifact_directory=artifact_directory,
        report_path=f"{artifact_directory}/shareable/report.json",
        summary_path=f"{artifact_directory}/shareable/summary.md",
        legacy_model_name=legacy_model_name,
        legacy_backend_interpretation=LEGACY_SYSTEM_VISA_INTERPRETATION,
        artifact_schema_version=None,
        report_sha256=None,
        source_availability=SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY,
        migration_note=EVIDENCE_MIGRATION_NOTE,
    )


SUPPORT_EVIDENCE_RECORDS = (
    _historical_record(
        "keysight-e36312a-usb-system-visa-20260709-full",
        "keysight-e36312a",
        "usb",
        "E36312A",
        ".tmp_tests/live_cli_check/20260709_153201_E36312A_USB_full",
    ),
    _historical_record(
        "keysight-e36312a-tcpip-system-visa-20260709-full",
        "keysight-e36312a",
        "tcpip",
        "E36312A",
        ".tmp_tests/live_cli_check/20260709_201420_E36312A_LAN_full",
    ),
    _historical_record(
        "keysight-edu36311a-usb-system-visa-20260709-full",
        "keysight-edu36311a",
        "usb",
        "EDU36311A",
        ".tmp_tests/live_cli_check/20260709_151534_EDU36311A_USB_full",
    ),
    _historical_record(
        "keysight-edu36311a-tcpip-system-visa-20260709-full",
        "keysight-edu36311a",
        "tcpip",
        "EDU36311A",
        ".tmp_tests/live_cli_check/20260709_200530_EDU36311A_LAN_full",
    ),
    _historical_record(
        "keysight-e3646a-asrl-system-visa-20260709-full",
        "keysight-e3646a",
        "asrl",
        "E3646A",
        ".tmp_tests/live_cli_check/20260709_151205_E3646A_ASRL_full",
    ),
)

SUPPORT_EVIDENCE_BY_ID: Mapping[str, SupportEvidenceRecord] = MappingProxyType(
    {record.evidence_id: record for record in SUPPORT_EVIDENCE_RECORDS}
)


def validate_support_evidence_metadata(
    records: tuple[SupportEvidenceRecord, ...] | None = None,
) -> None:
    """Fail closed when evidence identities or availability claims are inconsistent."""

    selected = SUPPORT_EVIDENCE_RECORDS if records is None else records
    seen_ids: set[str] = set()
    for record in selected:
        if not _EVIDENCE_ID_PATTERN.fullmatch(record.evidence_id):
            raise ValueError(f"invalid evidence_id: {record.evidence_id!r}")
        if record.evidence_id in seen_ids:
            raise ValueError(f"duplicate evidence_id: {record.evidence_id}")
        seen_ids.add(record.evidence_id)
        try:
            if canonical_physical_model_id(record.model_id) != record.model_id:
                raise ValueError(f"noncanonical evidence model_id: {record.model_id!r}")
        except IdentityResolutionError as exc:
            raise ValueError(f"noncanonical evidence model_id: {record.model_id!r}") from exc
        if record.transport_scope not in {"usb", "tcpip", "asrl", "gpib"}:
            raise ValueError(f"invalid evidence transport: {record.transport_scope!r}")
        if record.backend_scope not in {"system_visa", "pyvisa_py", "custom_visa"}:
            raise ValueError(f"invalid evidence backend: {record.backend_scope!r}")
        if record.source_availability not in _SOURCE_AVAILABILITY_STATES:
            raise ValueError(f"invalid evidence source availability: {record.source_availability!r}")
        if record.source_availability == SOURCE_AVAILABILITY_VERIFIED_LOCAL:
            if record.report_sha256 is None or not _SHA256_PATTERN.fullmatch(record.report_sha256):
                raise ValueError(f"verified-local evidence requires SHA-256: {record.evidence_id}")
        elif record.report_sha256 is not None:
            raise ValueError(
                f"historical-reference-only evidence cannot claim a checksum: {record.evidence_id}"
            )
        if record.artifact_schema_version is not None and record.artifact_schema_version < 1:
            raise ValueError(f"invalid artifact schema version: {record.evidence_id}")
        if not record.migration_note.strip():
            raise ValueError(f"evidence migration note is required: {record.evidence_id}")
        _validate_repository_relative_path(record.artifact_directory, record.evidence_id)
        _validate_repository_relative_path(record.report_path, record.evidence_id)
        _validate_repository_relative_path(record.summary_path, record.evidence_id)
        if record.report_path != f"{record.artifact_directory}/shareable/report.json":
            raise ValueError(f"unexpected evidence report path: {record.evidence_id}")
        if record.summary_path != f"{record.artifact_directory}/shareable/summary.md":
            raise ValueError(f"unexpected evidence summary path: {record.evidence_id}")
        _validate_non_sensitive_record(record)


def _validate_repository_relative_path(value: str, evidence_id: str) -> None:
    path = PurePosixPath(value)
    if (
        not value.startswith(".tmp_tests/live_cli_check/")
        or path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in path.parts
        or "\\" in value
    ):
        raise ValueError(f"evidence path must be repository-relative: {evidence_id}")


def _validate_non_sensitive_record(record: SupportEvidenceRecord) -> None:
    values = (
        record.evidence_id,
        record.artifact_directory,
        record.report_path,
        record.summary_path,
        record.legacy_backend_interpretation,
        record.migration_note,
    )
    for value in values:
        if "::" in value or _PRIVATE_IPV4_PATTERN.search(value):
            raise ValueError(f"evidence metadata contains private resource data: {record.evidence_id}")


validate_support_evidence_metadata()
