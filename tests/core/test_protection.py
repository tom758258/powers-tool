from __future__ import annotations

import pytest

from keysight_power_core.core import OperationRequest, RuntimeOptions
from keysight_power_core.protection import run_protection


class FakeSession:
    def __init__(self, idn: str, responses: dict[str, str]) -> None:
        self.idn = idn
        self.responses = responses
        self.queries: list[str] = []

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        pass

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        return self.responses[command]

    def write(self, command: str) -> None:
        raise AssertionError(f"protection-status must not write {command!r}")

    def close(self) -> None:
        pass


@pytest.mark.parametrize("model", ["E36312A", "EDU36311A"])
def test_protection_status_reads_and_aggregates_trip_flags_by_channel(model: str) -> None:
    session = FakeSession(
        f"KEYSIGHT,{model},SERIAL0000,1.0",
        {
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "0",
            "VOLT:PROT:TRIP? (@2)": "1",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "0",
            "CURR:PROT:TRIP? (@3)": "1",
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "OFF",
        },
    )
    request = OperationRequest(
        command="protection-status",
        runtime=RuntimeOptions(resource=f"USB0::FAKE::{model}::INSTR"),
        parameters={"all": True},
    )

    result = run_protection(request, opener=lambda *args, **kwargs: session)

    assert result["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": True,
    }
    assert result["protection_by_channel"] == [
        {
            "channel": 1,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": False,
            },
        },
        {
            "channel": 2,
            "protection": {
                "over_voltage_tripped": True,
                "over_current_tripped": False,
            },
        },
        {
            "channel": 3,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": True,
            },
        },
    ]
    assert result["outputs"] == [
        {"channel": 1, "enabled": False, "disabled_with_protection": False},
        {"channel": 2, "enabled": True, "disabled_with_protection": False},
        {"channel": 3, "enabled": False, "disabled_with_protection": True},
    ]
    assert session.queries == [
        "*IDN?",
        "VOLT:PROT:TRIP? (@1)",
        "CURR:PROT:TRIP? (@1)",
        "VOLT:PROT:TRIP? (@2)",
        "CURR:PROT:TRIP? (@2)",
        "VOLT:PROT:TRIP? (@3)",
        "CURR:PROT:TRIP? (@3)",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
