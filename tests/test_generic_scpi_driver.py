import math

import pytest

from keysight_power.drivers.generic_scpi import (
    ChannelListStrategy,
    GenericScpiPowerSupply,
    PreselectChannelStrategy,
)
from keysight_power.safety import SafetyLimits, SafetyValidationError


class FakeSession:
    def __init__(self, responses: dict[str, list[str]] | None = None) -> None:
        self.commands: list[str] = []
        self.responses = responses or {}
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        responses = self.responses.get(command)
        if not responses:
            raise RuntimeError(f"No fake response for {command}")
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]

    def close(self) -> None:
        self.closed = True


def test_generic_scpi_no_channel_operations_use_expected_command_order() -> None:
    session = FakeSession(
        {
            "MEAS:VOLT?": ["1.234"],
            "MEAS:CURR?": ["0.056"],
            "OUTP?": ["ON"],
        }
    )
    power_supply = GenericScpiPowerSupply(session)

    power_supply.set_current_limit(channel=1, current=0.05)
    power_supply.set_voltage(channel=1, voltage=1.0)
    power_supply.output_on(channel=1)
    voltage = power_supply.measure_voltage(channel=1)
    current = power_supply.measure_current(channel=1)
    output_enabled = power_supply.output_state(channel=1)
    power_supply.output_off(channel=1)

    assert voltage == 1.234
    assert current == 0.056
    assert output_enabled is True
    assert session.commands == [
        "CURR 0.05",
        "VOLT 1",
        "OUTP ON",
        "MEAS:VOLT?",
        "MEAS:CURR?",
        "OUTP?",
        "OUTP OFF",
    ]


def test_generic_scpi_clear_status_and_check_errors() -> None:
    session = FakeSession(
        {
            "SYST:ERR?": [
                '-100,"Command error"',
                '-200,"Execution error"',
                '0,"No error"',
            ]
        }
    )
    power_supply = GenericScpiPowerSupply(session)

    power_supply.clear_status()
    errors = power_supply.check_errors()

    assert errors == ['-100,"Command error"', '-200,"Execution error"']
    assert session.commands == ["*CLS", "SYST:ERR?", "SYST:ERR?", "SYST:ERR?"]


def test_channel_list_strategy_appends_channel_lists() -> None:
    session = FakeSession({"MEAS:CURR? (@2)": ["0.125"]})
    power_supply = GenericScpiPowerSupply(
        session,
        channel_strategy=ChannelListStrategy(),
    )

    power_supply.set_voltage(channel=2, voltage=3.3)
    current = power_supply.measure_current(channel=2)

    assert current == 0.125
    assert session.commands == ["VOLT 3.3,(@2)", "MEAS:CURR? (@2)"]


def test_preselect_channel_strategy_selects_before_operations() -> None:
    session = FakeSession({"MEAS:VOLT?": ["5.0"]})
    power_supply = GenericScpiPowerSupply(
        session,
        channel_strategy=PreselectChannelStrategy(
            select_command_template="INST:NSEL {channel}"
        ),
    )

    power_supply.output_on(channel=3)
    voltage = power_supply.measure_voltage(channel=3)

    assert voltage == 5.0
    assert session.commands == [
        "INST:NSEL 3",
        "OUTP ON",
        "INST:NSEL 3",
        "MEAS:VOLT?",
    ]


def test_no_channel_strategy_rejects_unexpected_channels() -> None:
    session = FakeSession()
    power_supply = GenericScpiPowerSupply(session)

    with pytest.raises(ValueError, match="no-channel"):
        power_supply.output_on(channel=2)

    assert session.commands == []


def test_channel_strategies_require_valid_channels() -> None:
    session = FakeSession()
    power_supply = GenericScpiPowerSupply(
        session,
        channel_strategy=ChannelListStrategy(),
    )

    with pytest.raises(ValueError, match="channel is required"):
        power_supply.output_on()
    with pytest.raises(ValueError, match="at least 1"):
        power_supply.output_on(channel=0)

    assert session.commands == []


def test_programmed_values_must_be_non_negative_and_finite() -> None:
    session = FakeSession()
    power_supply = GenericScpiPowerSupply(session)

    with pytest.raises(ValueError, match="voltage must be non-negative"):
        power_supply.set_voltage(voltage=-1.0)
    with pytest.raises(ValueError, match="current must be finite"):
        power_supply.set_current_limit(current=math.inf)

    assert session.commands == []


def test_safety_limits_block_programming_before_scpi_command() -> None:
    session = FakeSession()
    power_supply = GenericScpiPowerSupply(
        session,
        channel_strategy=ChannelListStrategy(),
        safety_limits=SafetyLimits(
            max_voltage=5.0,
            max_current=0.5,
            allowed_channels=(1,),
        ),
    )

    with pytest.raises(SafetyValidationError, match="channel 2 is not allowed"):
        power_supply.set_voltage(channel=2, voltage=1.0)
    with pytest.raises(SafetyValidationError, match="voltage 6 exceeds maximum 5"):
        power_supply.set_voltage(channel=1, voltage=6.0)
    with pytest.raises(SafetyValidationError, match="current 0.6 exceeds maximum 0.5"):
        power_supply.set_current_limit(channel=1, current=0.6)

    assert session.commands == []


def test_measurement_parse_failures_are_explicit() -> None:
    power_supply = GenericScpiPowerSupply(
        FakeSession({"MEAS:VOLT?": ["not-a-number"]})
    )

    with pytest.raises(ValueError, match="Could not parse voltage"):
        power_supply.measure_voltage()


def test_check_errors_requires_positive_max_reads() -> None:
    power_supply = GenericScpiPowerSupply(FakeSession())

    with pytest.raises(ValueError, match="max_reads"):
        power_supply.check_errors(max_reads=0)


def test_generic_scpi_driver_closes_underlying_session() -> None:
    session = FakeSession()

    with GenericScpiPowerSupply(session) as power_supply:
        assert power_supply is not None

    assert session.closed
