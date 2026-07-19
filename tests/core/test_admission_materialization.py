"""Regression coverage for one-time workflow document admission."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from powers_tool_core.command_runner import run_core_command, validate_request_admission
from powers_tool_core.core import OperationRequest, RuntimeOptions, SequenceRequest, TriggerRequest


def _runtime() -> RuntimeOptions:
    return RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a")


def _sequence_document() -> dict[str, object]:
    return {"version": 1, "steps": [{"action": "wait", "seconds": 0}]}


def _ramp_list_document() -> dict[str, object]:
    return {
        "kind": "powers-tool-ramp-list",
        "version": 2,
        "segments": [{
            "channel": 1,
            "current": 0.1,
            "start_voltage": 0,
            "stop_voltage": 1,
            "step_voltage": 1,
            "delay_ms": 0,
            "hold_ms": 0,
        }],
    }


def _snapshot_document() -> dict[str, object]:
    return run_core_command(
        OperationRequest(
            "snapshot",
            RuntimeOptions(simulate=True, resource="USB0::SIM::E36312A::INSTR"),
        )
    )


def test_sequence_file_admission_is_idempotent_and_does_not_reload(tmp_path: Path) -> None:
    path = tmp_path / "sequence.json"
    path.write_text(json.dumps(_sequence_document()), encoding="utf-8")
    first = validate_request_admission(SequenceRequest("sequence", _runtime(), {"file": str(path)}))

    path.unlink()
    second = validate_request_admission(first)

    assert second == first
    assert "file" not in first.parameters
    assert run_core_command(first)["plan"]["operation"]["name"] == "sequence"


def test_sequence_inline_admission_deep_copies_document() -> None:
    document = _sequence_document()
    request = SequenceRequest("sequence", _runtime(), {"document": document})
    first = validate_request_admission(request)

    document["steps"][0]["seconds"] = 9

    assert first.parameters["document"]["steps"][0]["seconds"] == 0
    assert validate_request_admission(first) == first


def test_ramp_list_file_admission_is_idempotent_and_does_not_reload(tmp_path: Path) -> None:
    path = tmp_path / "ramp-list.json"
    path.write_text(json.dumps(_ramp_list_document()), encoding="utf-8")
    first = validate_request_admission(OperationRequest("ramp-list", _runtime(), {"file": str(path)}))

    path.unlink()
    second = validate_request_admission(first)

    assert second == first
    assert "file" not in first.parameters
    assert run_core_command(first)["plan"]["operation"]["name"] == "ramp-list"


def test_ramp_list_inline_admission_deep_copies_document() -> None:
    document = _ramp_list_document()
    first = validate_request_admission(OperationRequest("ramp-list", _runtime(), {"document": document}))

    document["segments"][0]["current"] = 2.0

    assert first.parameters["document"]["segments"][0]["current"] == 0.1
    assert validate_request_admission(first) == first


def test_restore_file_admission_is_idempotent_and_does_not_reload(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_snapshot_document()), encoding="utf-8")
    first = validate_request_admission(
        OperationRequest("restore-from-snapshot", RuntimeOptions(dry_run=True), {"file": str(path), "channel": "all"})
    )

    path.unlink()
    second = validate_request_admission(first)

    assert second == first
    assert "file" not in first.parameters
    assert run_core_command(first)["restored_channels"] == [1, 2, 3]


def test_restore_inline_admission_deep_copies_document() -> None:
    document = _snapshot_document()
    original = deepcopy(document)
    first = validate_request_admission(
        OperationRequest("restore-from-snapshot", RuntimeOptions(dry_run=True), {"document": document, "channel": 1})
    )

    document["readback"][0]["setpoints"]["voltage"] = 99.0

    assert first.parameters["document"] == original
    assert validate_request_admission(first) == first


def test_trigger_list_alias_admission_is_idempotent() -> None:
    first = validate_request_admission(
        TriggerRequest(
            "trigger-list",
            _runtime(),
            {
                "channel": 1,
                "voltage_list": [1.0],
                "current_list": [0.1],
                "dwell_list": [0.01],
                "leave_trigger_configured": True,
            },
        )
    )

    assert first.parameters["voltages"] == (1.0,)
    assert "voltage_list" not in first.parameters
    assert validate_request_admission(first) == first
