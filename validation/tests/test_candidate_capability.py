from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from powers_tool_validation import candidate_capability


def _manifest(root: Path, arguments: list[str], *, expires_in: int = 1800) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "run_id": "run-1",
        "target_model_id": "keysight-e36312a",
        "selected_suite": "full",
        "selected_suites": ["readonly", "output"],
        "transport_scope": "usb",
        "backend_scope": "system_visa",
        "private_run_directory_identity": str(root.resolve()),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
        "candidate_cases": [
            {
                "case_id": "output-on-ch1",
                "suite": "output",
                "command": "output-on",
                "model_id": "keysight-e36312a",
                "transport_scope": "usb",
                "backend_scope": "system_visa",
                "state_changing": True,
                "arguments": arguments,
                "request_fingerprint": "",
                "capability_id": "a" * 48,
            }
        ],
    }


def _issue(tmp_path: Path, arguments: list[str]) -> tuple[Path, Path, bytes]:
    root = tmp_path / "private"
    root.mkdir()
    secret = b"candidate-test-secret"
    input_path = root / "manifest-input.json"
    manifest_path = root / "manifest.json"
    capability_path = root / "capability.json"
    input_path.write_text(json.dumps(_manifest(root, arguments)), encoding="utf-8")
    candidate_capability.issue_manifest(input_path, manifest_path, secret)
    candidate_capability.issue_capability(manifest_path, capability_path, "output-on-ch1", secret)
    return manifest_path, capability_path, secret


def test_signed_capability_binds_exact_invocation_and_is_one_time(tmp_path: Path) -> None:
    arguments = [
        "output-on",
        "--json",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--confirm",
        "--save-json",
        str(tmp_path / "private" / "output.json"),
    ]
    manifest, capability, secret = _issue(tmp_path, arguments)
    context = candidate_capability.consume_and_verify(
        manifest,
        capability,
        manifest.parent,
        secret,
        argv=arguments,
        command="output-on",
    )
    assert context.values["request_fingerprint"] == candidate_capability.request_fingerprint(arguments)
    with pytest.raises(candidate_capability.CandidateCapabilityError):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            secret,
            argv=arguments,
            command="output-on",
        )


def test_signed_capability_rejects_tampering_and_wrong_arguments(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)
    document = json.loads(capability.read_text(encoding="utf-8"))
    document["arguments"] = ["output-on", "--channel", "all"]
    capability.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="signature"):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            secret,
            argv=arguments,
            command="output-on",
        )
    assert not list(manifest.parent.glob(".candidate-consumed/*.marker"))


def test_self_consistent_unsigned_document_cannot_be_used(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)
    document = json.loads(capability.read_text(encoding="utf-8"))
    document.pop("capability_signature")
    capability.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="signature"):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            secret,
            argv=arguments,
            command="output-on",
        )
    assert not list(manifest.parent.glob(".candidate-consumed/*.marker"))


def test_expired_capability_is_rejected(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    root = tmp_path / "private"
    root.mkdir()
    secret = b"candidate-test-secret"
    input_path = root / "manifest-input.json"
    manifest_path = root / "manifest.json"
    input_path.write_text(json.dumps(_manifest(root, arguments, expires_in=-1)), encoding="utf-8")
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="time range"):
        candidate_capability.issue_manifest(input_path, manifest_path, secret)


@pytest.mark.parametrize(
    ("command", "case_id", "suite"),
    [
        ("output-off", "output-on-ch1", "output"),
        ("output-on", "other-case", "output"),
        ("output-on", "output-on-ch1", "snapshot"),
    ],
)
def test_capability_rejects_command_case_and_suite_mismatch(
    tmp_path: Path, command: str, case_id: str, suite: str
) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)
    with pytest.raises(candidate_capability.CandidateCapabilityError):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            secret,
            argv=arguments,
            command=command,
            expected_case_id=case_id,
            expected_suite=suite,
        )
    assert capability.exists()
    assert not list(manifest.parent.glob(".candidate-consumed/*.marker"))
    candidate_capability.consume_and_verify(
        manifest,
        capability,
        manifest.parent,
        secret,
        argv=arguments,
        command="output-on",
        expected_case_id="output-on-ch1",
        expected_suite="output",
    )


def test_capability_rejects_wrong_secret_and_private_root(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="signature"):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            b"wrong-secret",
            argv=arguments,
            command="output-on",
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="outside"):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            outside,
            secret,
            argv=arguments,
            command="output-on",
        )


def test_capability_consumption_rejects_changed_effective_arguments(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="invocation"):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            secret,
            argv=["output-on", "--channel", "all"],
            command="output-on",
        )
    assert capability.exists()
    context = candidate_capability.consume_and_verify(
        manifest,
        capability,
        manifest.parent,
        secret,
        argv=arguments,
        command="output-on",
    )
    assert context.values["command"] == "output-on"


def test_expired_case_capability_does_not_consume(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)
    document = json.loads(capability.read_text(encoding="utf-8"))
    document["issued_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    document["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    payload = dict(document)
    payload.pop("capability_signature")
    document["capability_signature"] = candidate_capability._signature(payload, secret)
    capability.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="expired"):
        candidate_capability.consume_and_verify(
            manifest,
            capability,
            manifest.parent,
            secret,
            argv=arguments,
            command="output-on",
        )
    assert capability.exists()
    assert not list(manifest.parent.glob(".candidate-consumed/*.marker"))


def test_long_run_manifest_remains_valid_after_previous_ten_minute_boundary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private"
    root.mkdir()
    now = datetime.now(timezone.utc)
    payload = _manifest(root, ["output-on", "--channel", "1"], expires_in=2 * 60 * 60)
    candidate_capability._validate_time_window(
        payload,
        maximum_seconds=candidate_capability._MAX_RUN_SECONDS,
        now=now + timedelta(minutes=11),
    )


def test_run_manifest_lifetime_is_bounded_to_four_hours(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir()
    input_path = root / "input.json"
    output_path = root / "manifest.json"
    input_path.write_text(
        json.dumps(_manifest(root, ["output-on"], expires_in=4 * 60 * 60 + 1)),
        encoding="utf-8",
    )
    with pytest.raises(candidate_capability.CandidateCapabilityError, match="too long"):
        candidate_capability.issue_manifest(input_path, output_path, b"secret")


def test_concurrent_exact_replay_allows_at_most_one_success(tmp_path: Path) -> None:
    arguments = ["output-on", "--channel", "1"]
    manifest, capability, secret = _issue(tmp_path, arguments)

    def consume() -> bool:
        try:
            candidate_capability.consume_and_verify(
                manifest,
                capability,
                manifest.parent,
                secret,
                argv=arguments,
                command="output-on",
            )
            return True
        except candidate_capability.CandidateCapabilityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume(), range(2)))
    assert results.count(True) == 1
    assert results.count(False) == 1
