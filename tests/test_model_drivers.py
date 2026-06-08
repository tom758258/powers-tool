import pytest

from keysight_power.drivers.e36312a import E36312APowerSupply
from keysight_power.drivers.edu36311a import EDU36311APowerSupply
from keysight_power.drivers.generic_scpi import NoChannelStrategy
from keysight_power.safety import SafetyLimits, SafetyValidationError


class FakeSession:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.commands: list[str] = []
        self.responses = responses or {}

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        response = self.responses.get(command)
        if response is None:
            raise RuntimeError(f"No fake response for {command}")
        return response

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    "driver_class",
    [E36312APowerSupply, EDU36311APowerSupply],
)
@pytest.mark.parametrize("channel", [1, 2, 3])
def test_first_target_drivers_use_channel_list_scpi(driver_class, channel) -> None:
    session = FakeSession(
        {
            f"MEAS:VOLT? (@{channel})": "1.234",
            f"MEAS:CURR? (@{channel})": "0.056",
        }
    )
    power_supply = driver_class(session)

    power_supply.set_current_limit(channel=channel, current=0.05)
    power_supply.set_voltage(channel=channel, voltage=1.0)
    power_supply.output_off(channel=channel)
    voltage = power_supply.measure_voltage(channel=channel)
    current = power_supply.measure_current(channel=channel)

    assert voltage == 1.234
    assert current == 0.056
    assert session.commands == [
        f"CURR 0.05,(@{channel})",
        f"VOLT 1,(@{channel})",
        f"OUTP OFF,(@{channel})",
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    ]


@pytest.mark.parametrize(
    "driver_class",
    [E36312APowerSupply, EDU36311APowerSupply],
)
def test_first_target_drivers_allow_channel_strategy_override(driver_class) -> None:
    session = FakeSession()
    power_supply = driver_class(session, channel_strategy=NoChannelStrategy())

    power_supply.output_off(channel=1)

    assert session.commands == ["OUTP OFF"]


def test_first_target_driver_safety_validation_runs_before_scpi_write() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(
        session,
        safety_limits=SafetyLimits(
            max_voltage=5.0,
            max_current=0.5,
            allowed_channels=(1,),
        ),
    )

    with pytest.raises(SafetyValidationError, match="channel 2 is not allowed"):
        power_supply.set_voltage(channel=2, voltage=1.0)

    assert session.commands == []
