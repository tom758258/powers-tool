from pathlib import Path

import pytest

from powers_tool_core.drivers.e36312a import TriggerSnapshot
from scripts import e36312a_trigger_validation as helper


def _snapshot(channel: int) -> TriggerSnapshot:
    return TriggerSnapshot(
        channel=channel,
        digital_pins={
            pin: {"function": "DIO", "polarity": "POS"}
            for pin in (1, 2, 3)
        },
        trigger_output_bus_enabled=False,
        trigger={
            "source": "BUS",
            "delay": 0.0,
            "voltage_mode": "FIX",
            "current_mode": "FIX",
            "triggered_voltage": 0.0,
            "triggered_current": 0.05,
        },
        list_state={
            "voltage": (0.0,),
            "current": (0.05,),
            "dwell": (0.01,),
            "tout_bost": (False,),
            "tout_eost": (False,),
            "count": 1,
            "step_mode": "AUTO",
            "terminate_last": False,
        },
    )


class HelperPowerSupply:
    capabilities = type("Capabilities", (), {"channels": (1, 2, 3)})()

    def __init__(self, *, fail_arm: bool = False) -> None:
        self.events: list[str] = []
        self.fail_arm = fail_arm

    def trigger_snapshot(self, channel: int) -> TriggerSnapshot:
        self.events.append(f"snapshot-{channel}")
        return _snapshot(channel)

    def abort_output_trigger(self, channel: int) -> None:
        self.events.append(f"abort-{channel}")

    def programmed_voltage(self, *, channel: int) -> float:
        return 1.0

    def programmed_current(self, *, channel: int) -> float:
        return 0.05

    def set_triggered_current(self, **kwargs) -> None:
        self.events.append("configure-current")

    def set_triggered_voltage(self, **kwargs) -> None:
        self.events.append("configure-voltage")
        if self.fail_arm:
            raise RuntimeError("arm failed")

    def set_trigger_modes(self, **kwargs) -> None:
        self.events.append("configure-modes")

    def configure_output_trigger_source_bus(self, channel: int) -> None:
        self.events.append("configure-source")

    def initiate_output_trigger(self, channel: int) -> None:
        self.events.append("init")

    def _restore_trigger_channel_snapshot(self, snapshot: TriggerSnapshot) -> None:
        self.events.append(f"restore-{snapshot.channel}")

    def _restore_trigger_global_snapshot(self, snapshot: TriggerSnapshot) -> None:
        self.events.append("restore-global")

    def read_error_queue(self, max_errors: int):
        self.events.append("error-queue")
        return [], 1


def test_arm_helper_persists_before_mutation_and_never_fires() -> None:
    power_supply = HelperPowerSupply()

    helper.snapshot_and_arm(
        power_supply,
        persist=lambda snapshots: power_supply.events.append("persist"),
    )

    assert power_supply.events[:7] == [
        "snapshot-1",
        "snapshot-2",
        "snapshot-3",
        "persist",
        "abort-1",
        "abort-2",
        "abort-3",
    ]
    assert "init" in power_supply.events
    assert "*TRG" not in Path(helper.__file__).read_text(encoding="utf-8")


def test_arm_helper_best_effort_restores_after_partial_failure() -> None:
    power_supply = HelperPowerSupply(fail_arm=True)

    with pytest.raises(RuntimeError, match="arm failed"):
        helper.snapshot_and_arm(power_supply, persist=lambda snapshots: None)

    assert power_supply.events[-4:] == [
        "restore-1",
        "restore-2",
        "restore-3",
        "restore-global",
    ]


def test_helper_identity_mismatch_is_rejected() -> None:
    document = helper._snapshot_document(
        resource="USB0::PRIVATE::INSTR",
        idn="KEYSIGHT,E36312A,SERIAL-A,1.0",
        snapshots=tuple(_snapshot(channel) for channel in (1, 2, 3)),
    )

    assert helper._identity_matches(
        document,
        "USB0::PRIVATE::INSTR",
        "KEYSIGHT,E36312A,SERIAL-B,1.0",
    ) is False
