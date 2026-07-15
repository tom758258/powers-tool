"""Private E36312A trigger-fire arm and restore helper for live validation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Sequence

from powers_tool_core.connection import open_resource
from powers_tool_core.core import RuntimeOptions, TriggerRequest
from powers_tool_core.drivers.e36312a import E36312APowerSupply, TriggerSnapshot
from powers_tool_core.factory import create_power_supply
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.models import parse_idn
from powers_tool_core.support_policy import SUPPORT_POLICY_MODE_VALIDATION
from powers_tool_core.trigger import (
    _abort_trigger_channels,
    _raise_on_instrument_errors,
    _restore_trigger_snapshots,
)

IDN_QUERY = "*IDN?"
EXPECTED_MODEL_ID = "keysight-e36312a"


def snapshot_and_arm(
    power_supply: E36312APowerSupply,
    *,
    persist: Callable[[Sequence[TriggerSnapshot]], None],
) -> tuple[TriggerSnapshot, ...]:
    """Persist three snapshots before arming CH1 without firing it."""

    snapshots = tuple(
        power_supply.trigger_snapshot(channel)
        for channel in power_supply.capabilities.channels
    )
    persist(snapshots)
    try:
        abort_errors = _abort_trigger_channels(
            power_supply,
            power_supply.capabilities.channels,
        )
        if abort_errors:
            raise RuntimeError("abort failed: " + "; ".join(abort_errors))
        voltage = power_supply.programmed_voltage(channel=1)
        current = power_supply.programmed_current(channel=1)
        power_supply.set_triggered_current(channel=1, current=current)
        power_supply.set_triggered_voltage(channel=1, voltage=voltage)
        power_supply.set_trigger_modes(channel=1, current_mode="STEP", voltage_mode="STEP")
        power_supply.configure_output_trigger_source_bus(1)
        power_supply.initiate_output_trigger(1)
        _raise_on_instrument_errors(power_supply, "trigger-fire arm")
    except BaseException:
        _restore_trigger_snapshots(power_supply, snapshots)
        raise
    return snapshots


def restore_snapshots(
    power_supply: E36312APowerSupply,
    snapshots: Sequence[TriggerSnapshot],
) -> None:
    """Restore all captured Trigger state and reject incomplete cleanup."""

    errors = _restore_trigger_snapshots(power_supply, snapshots)
    try:
        _raise_on_instrument_errors(power_supply, "trigger-fire restore")
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        raise RuntimeError("; ".join(errors))


def _request(resource: str, backend: str | None, timeout_ms: int) -> TriggerRequest:
    return TriggerRequest(
        command="trigger-fire",
        runtime=RuntimeOptions(
            resource=resource,
            backend=backend,
            timeout_ms=timeout_ms,
            expected_model_id=EXPECTED_MODEL_ID,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        parameters={"channel": 1},
    )


def _open_power_supply(
    resource: str,
    backend: str | None,
    timeout_ms: int,
):
    return open_resource(resource, backend=backend, timeout_ms=timeout_ms)


def _validated_power_supply(
    instrument: Any,
    request: TriggerRequest,
) -> tuple[E36312APowerSupply, str]:
    idn = instrument.query(IDN_QUERY)
    enforce_live_support_for_idn(request, idn)
    power_supply = create_power_supply(instrument, idn)
    if not isinstance(power_supply, E36312APowerSupply):
        raise RuntimeError("connected instrument is not an E36312A")
    return power_supply, idn


def _snapshot_document(
    *,
    resource: str,
    idn: str,
    snapshots: Sequence[TriggerSnapshot],
) -> dict[str, Any]:
    identity = parse_idn(idn)
    return {
        "schema_version": 1,
        "kind": "powers-tool-private-e36312a-trigger-validation",
        "resource": resource,
        "identity": {
            "manufacturer": identity.manufacturer,
            "model": identity.model,
            "serial": identity.serial,
        },
        "snapshots": [snapshot.to_dict() for snapshot in snapshots],
    }


def _trigger_snapshot(value: dict[str, Any]) -> TriggerSnapshot:
    return TriggerSnapshot(
        channel=int(value["channel"]),
        digital_pins={
            int(pin): {
                "function": str(state["function"]),
                "polarity": str(state["polarity"]),
            }
            for pin, state in value["digital_pins"].items()
        },
        trigger_output_bus_enabled=value["trigger_output_bus_enabled"] is True,
        trigger=dict(value["trigger"]),
        list_state=dict(value["list"]),
    )


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_snapshot(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("kind") != "powers-tool-private-e36312a-trigger-validation":
        raise ValueError("private trigger snapshot has an unsupported schema")
    snapshots = value.get("snapshots")
    if not isinstance(snapshots, list) or [item.get("channel") for item in snapshots] != [1, 2, 3]:
        raise ValueError("private trigger snapshot must contain channels 1, 2, and 3")
    return value


def _identity_matches(document: dict[str, Any], resource: str, idn: str) -> bool:
    identity = parse_idn(idn)
    expected = document["identity"]
    return (
        document.get("resource") == resource
        and expected.get("manufacturer") == identity.manufacturer
        and expected.get("model") == identity.model
        and expected.get("serial") == identity.serial
    )


def _arm(args: argparse.Namespace) -> dict[str, Any]:
    request = _request(args.resource, args.backend, args.timeout_ms)
    with _open_power_supply(args.resource, args.backend, args.timeout_ms) as instrument:
        power_supply, idn = _validated_power_supply(instrument, request)
        snapshot_and_arm(
            power_supply,
            persist=lambda snapshots: _write_json_atomic(
                args.snapshot_json,
                _snapshot_document(resource=args.resource, idn=idn, snapshots=snapshots),
            ),
        )
    return {
        "ok": True,
        "armed": True,
        "channels_snapshotted": [1, 2, 3],
        "target_channel": 1,
        "fired": False,
        "error_queue_empty": True,
    }


def _restore(args: argparse.Namespace) -> dict[str, Any]:
    document = _read_snapshot(args.snapshot_json)
    request = _request(args.resource, args.backend, args.timeout_ms)
    with _open_power_supply(args.resource, args.backend, args.timeout_ms) as instrument:
        power_supply, idn = _validated_power_supply(instrument, request)
        if not _identity_matches(document, args.resource, idn):
            raise RuntimeError("private trigger snapshot identity does not match the connected instrument")
        restore_snapshots(
            power_supply,
            tuple(_trigger_snapshot(value) for value in document["snapshots"]),
        )
    return {
        "ok": True,
        "restored": True,
        "channels_restored": [1, 2, 3],
        "digital_trigger_state_restored": True,
        "error_queue_empty": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("arm", "restore"))
    parser.add_argument("--resource", required=True)
    parser.add_argument("--snapshot-json", required=True, type=Path)
    parser.add_argument("--backend")
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = _arm(args) if args.action == "arm" else _restore(args)
    except BaseException as exc:
        print(json.dumps({"ok": False, "action": args.action, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
