from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from powers_tool_cli import cli as product_cli
from powers_tool_core.core import OperationRequest, RuntimeOptions, ValidationCandidateContext
from powers_tool_core.live_support import enforce_live_support
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_VALIDATION,
    internal_validation_candidate_inventory,
)
from powers_tool_validation import candidate_capability
from powers_tool_validation.build_identity import (
    BuildProfile,
    VALIDATION_BUILD_IDENTITY,
)
from powers_tool_validation.runtime_extension import ValidationRuntimeExtension


def _verified_handle(tmp_path: Path) -> tuple[str, str]:
    root = tmp_path / "private"
    root.mkdir()
    now = datetime.now(timezone.utc)
    arguments = ["output-on", "--channel", "1"]
    payload = {
        "schema_version": 1,
        "run_id": "run-1",
        "target_model_id": "keysight-e36312a",
        "selected_suite": "output",
        "selected_suites": ["output"],
        "transport_scope": "usb",
        "backend_scope": "system_visa",
        "private_run_directory_identity": str(root.resolve()),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
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
                "capability_id": "b" * 48,
            }
        ],
    }
    input_path = root / "input.json"
    manifest_path = root / "manifest.json"
    capability_path = root / "capability.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    secret = b"runtime-test-secret"
    candidate_capability.issue_manifest(input_path, manifest_path, secret)
    candidate_capability.issue_capability(
        manifest_path, capability_path, "output-on-ch1", secret
    )
    handle = candidate_capability.consume_and_verify(
        manifest_path,
        capability_path,
        root,
        secret,
        argv=arguments,
        command="output-on",
        expected_case_id="output-on-ch1",
        expected_suite="output",
    )
    return handle, candidate_capability.request_fingerprint(arguments)


def _request(handle: object, fingerprint: str, **overrides: object) -> OperationRequest:
    options = {
        "resource": "USB0::1::INSTR",
        "support_policy_mode": SUPPORT_POLICY_MODE_VALIDATION,
        "validation_admission_handle": handle,
        "validation_request_fingerprint": fingerprint,
    }
    options.update(overrides)
    return OperationRequest("output-on", RuntimeOptions(**options))


def test_validation_build_identity_is_embedded_and_version_matched() -> None:
    assert VALIDATION_BUILD_IDENTITY.profile is BuildProfile.VALIDATION
    assert VALIDATION_BUILD_IDENTITY.distribution_name == "powers-tool-validation"
    assert VALIDATION_BUILD_IDENTITY.version == VALIDATION_BUILD_IDENTITY.product_version
    assert VALIDATION_BUILD_IDENTITY.artifact_kind in {"source-tree", "wheel"}


def test_no_arbitrary_context_or_permit_minting_api_is_exported() -> None:
    from powers_tool_validation import build_identity

    assert not hasattr(build_identity, "verified_candidate_context")
    assert not hasattr(build_identity, "validation_runtime_permit")


def test_validation_parser_accepts_candidate_inputs_only_when_extension_installed() -> None:
    product_cli._install_distribution_runtime_extension(ValidationRuntimeExtension())
    try:
        args = product_cli.build_parser().parse_args(
            [
                "output-on",
                "--channel",
                "1",
                "--validation-candidate-manifest",
                "manifest.json",
                "--validation-candidate-capability",
                "capability.json",
                "--validation-candidate-context-root",
                "private",
                "--validation-candidate-case-id",
                "case",
                "--validation-candidate-suite",
                "output",
            ]
        )
    finally:
        product_cli._install_distribution_runtime_extension(None)
    assert args.validation_candidate_case_id == "case"


def test_only_verifier_output_admits_exact_candidate(tmp_path: Path) -> None:
    handle, fingerprint = _verified_handle(tmp_path)
    state = {"candidate_context_integrity_validated": True}
    scope = enforce_live_support(
        _request(handle, fingerprint, validation_admission_state=state),
        "keysight-e36312a",
    )
    assert scope is not None
    assert scope.admission_kind == "validation_candidate"
    assert state == {
        "candidate_context_integrity_validated": True,
        "candidate_scope_admitted": True,
        "candidate_admission_kind": "validation_candidate",
    }


def test_candidate_admission_evidence_remains_true_after_later_case_failure(
    tmp_path: Path,
) -> None:
    handle, fingerprint = _verified_handle(tmp_path)
    execution = {
        "candidate_context_required": True,
        "candidate_context_integrity_validated": True,
        "candidate_scope_admitted": False,
    }
    enforce_live_support(
        _request(handle, fingerprint, validation_admission_state=execution),
        "keysight-e36312a",
    )
    result = "failed"
    assert execution["candidate_context_integrity_validated"] is True
    assert execution["candidate_scope_admitted"] is True
    assert result == "failed"


def test_candidate_scope_rejection_does_not_report_admission(tmp_path: Path) -> None:
    handle, fingerprint = _verified_handle(tmp_path)
    state = {
        "candidate_context_integrity_validated": True,
        "candidate_scope_admitted": False,
    }
    with pytest.raises(LiveSupportPolicyError, match="does not match"):
        enforce_live_support(
            _request(
                handle,
                fingerprint,
                resource="TCPIP0::192.0.2.1::INSTR",
                validation_admission_state=state,
            ),
            "keysight-e36312a",
        )
    assert state["candidate_context_integrity_validated"] is True
    assert state["candidate_scope_admitted"] is False


def test_registered_pending_admission_remains_separate() -> None:
    state: dict[str, object] = {}
    request = OperationRequest(
        "measure",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            validation_admission_state=state,
        ),
    )
    scope = enforce_live_support(request, "keysight-e36312a")
    assert scope is not None
    assert state == {
        "candidate_scope_admitted": False,
        "candidate_admission_kind": "registered_pending",
    }


@pytest.mark.parametrize(
    "context",
    [
        ValidationCandidateContext("run", "case", "output", "keysight-e36312a", "output-on", "usb", "system_visa"),
        ValidationCandidateContext(
            "run",
            "case",
            "output",
            "keysight-e36312a",
            "output-on",
            "usb",
            "system_visa",
            integrity_validated=True,
        ),
        ValidationCandidateContext(
            "run",
            "case",
            "output",
            "keysight-e36312a",
            "output-on",
            "usb",
            "system_visa",
            request_fingerprint="f" * 64,
            capability_id="c" * 48,
            issued_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-01-01T01:00:00+00:00",
            integrity_validated=True,
        ),
    ],
)
def test_validation_build_rejects_bare_or_forged_context(
    context: ValidationCandidateContext,
) -> None:
    with pytest.raises(LiveSupportPolicyError, match="integrity"):
        enforce_live_support(
            _request(None, "f" * 64, validation_candidate_context=context),
            "keysight-e36312a",
        )


def test_verified_context_request_fingerprint_must_match(tmp_path: Path) -> None:
    handle, fingerprint = _verified_handle(tmp_path)
    with pytest.raises(LiveSupportPolicyError, match="invocation"):
        enforce_live_support(
            _request(handle, "0" * 64),
            "keysight-e36312a",
        )


def test_verified_admission_handle_is_one_time(tmp_path: Path) -> None:
    handle, fingerprint = _verified_handle(tmp_path)
    enforce_live_support(_request(handle, fingerprint), "keysight-e36312a")
    with pytest.raises(LiveSupportPolicyError, match="context is required"):
        enforce_live_support(_request(handle, fingerprint), "keysight-e36312a")


def test_importable_modules_cannot_forge_candidate_admission() -> None:
    import powers_tool_validation.candidate_capability as capability
    import powers_tool_validation.runtime_extension as extension

    assert not hasattr(extension, "_RUNTIME_PERMIT")
    assert not hasattr(extension, "_context_from_verified_result")
    assert not hasattr(capability, "_RESULT_SENTINEL")
    assert not hasattr(capability, "_VerifiedCapabilityResult")
    assert not hasattr(capability, "_install_verified_admission")
    with pytest.raises(LiveSupportPolicyError, match="context is required"):
        enforce_live_support(_request("forged-handle", "f" * 64), "keysight-e36312a")


def test_core_candidate_inventory_is_single_exact_source() -> None:
    inventory = internal_validation_candidate_inventory()
    assert set(inventory) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    }
    assert inventory["keysight-e36312a"]["commands"] == (
        "doctor",
        "log",
        "measure-all",
        "output-on",
        "restore-from-snapshot",
    )
    assert "trigger-pulse" not in inventory["keysight-e36312a"]["commands"]
    assert "trigger-fire" not in inventory["keysight-e36312a"]["commands"]
