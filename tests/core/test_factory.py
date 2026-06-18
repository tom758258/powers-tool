from keysight_power_core.drivers.base import DriverCapabilities
from keysight_power_core.drivers.e36312a import E36312APowerSupply
from keysight_power_core.drivers.edu36311a import EDU36311APowerSupply
from keysight_power_core.drivers.generic_scpi import GenericScpiPowerSupply
from keysight_power_core.electrical_ratings import E36312A_ELECTRICAL_RATINGS, EDU36311A_ELECTRICAL_RATINGS
from keysight_power_core.factory import create_power_supply, select_driver
from keysight_power_core.models import parse_idn


class FakeSession:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        return "0"

    def close(self) -> None:
        self.closed = True


def test_first_target_models_are_recognized() -> None:
    e36312a = select_driver("KEYSIGHT,E36312A,SERIAL0000,1.0")
    edu36311a = select_driver("KEYSIGHT,EDU36311A,SERIAL0000,1.0")

    assert e36312a.model_info is not None
    assert e36312a.model_info.first_hardware_target is True
    assert e36312a.driver_class is E36312APowerSupply
    assert e36312a.reason == "model_specific_driver"
    assert edu36311a.model_info is not None
    assert edu36311a.model_info.first_hardware_target is True
    assert edu36311a.driver_class is EDU36311APowerSupply
    assert edu36311a.reason == "model_specific_driver"


def test_first_target_drivers_expose_conservative_capabilities() -> None:
    e36312a_expected = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
        electrical_ratings=E36312A_ELECTRICAL_RATINGS,
    )
    edu36311a_expected = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
        electrical_ratings=EDU36311A_ELECTRICAL_RATINGS,
    )

    e36312a = select_driver("KEYSIGHT,E36312A,SERIAL0000,1.0")
    edu36311a = select_driver("KEYSIGHT,EDU36311A,SERIAL0000,1.0")

    assert e36312a.capabilities == e36312a_expected
    assert edu36311a.capabilities == edu36311a_expected


def test_generic_fallback_exposes_channel_one_measure_capability() -> None:
    selection = select_driver("KEYSIGHT,E36103B,SERIAL0000,1.0")

    assert selection.driver_class is GenericScpiPowerSupply
    assert selection.capabilities == DriverCapabilities(
        channels=(1,),
        simulated_measure_channels=(1,),
        real_measure_channels=(1,),
    )


def test_near_term_and_later_models_are_recognized() -> None:
    for model in (
        "E36313A",
        "E36103B",
        "E36232A",
        "E36233A",
        "E36441A",
        "E36155A",
    ):
        selection = select_driver(f"KEYSIGHT,{model},SERIAL0000,1.0")

        assert selection.model_info is not None
        assert selection.model_info.model == model
        assert selection.driver_class is GenericScpiPowerSupply
        assert selection.reason == "known_model_generic_fallback"


def test_unknown_model_falls_back_to_generic_driver() -> None:
    selection = select_driver("KEYSIGHT,UNKNOWN,SERIAL0000,1.0")

    assert selection.idn.parse_ok is True
    assert selection.model_info is None
    assert selection.driver_class is GenericScpiPowerSupply
    assert selection.reason == "unknown_model_generic_fallback"


def test_malformed_idn_falls_back_to_generic_driver_without_model_metadata() -> None:
    selection = select_driver("KEYSIGHT,E36312A")

    assert selection.idn.parse_ok is False
    assert selection.model_info is None
    assert selection.driver_class is GenericScpiPowerSupply
    assert selection.reason == "malformed_idn_generic_fallback"


def test_select_driver_accepts_preparsed_idn() -> None:
    parsed = parse_idn("KEYSIGHT,E36232A,SERIAL0000,1.0")

    selection = select_driver(parsed)

    assert selection.idn is parsed
    assert selection.model_info is not None
    assert selection.model_info.model == "E36232A"


def test_create_power_supply_wraps_session_without_commands() -> None:
    session = FakeSession()

    power_supply = create_power_supply(
        session,
        "KEYSIGHT,E36312A,SERIAL0000,1.0",
    )

    assert isinstance(power_supply, E36312APowerSupply)
    assert session.commands == []
