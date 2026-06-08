import pytest

from keysight_power.errors import VisaConnectionError
from keysight_power.models import parse_idn
from keysight_power.testing.simulator import (
    SIMULATED_IDN,
    SIMULATED_RESOURCES,
    SimulatedResourceManager,
)


def test_simulator_lists_first_target_resources() -> None:
    assert SIMULATED_RESOURCES == (
        "USB0::SIM::E36103B::INSTR",
        "TCPIP0::SIM::E36232A::INSTR",
        "USB0::SIM::E36312A::INSTR",
        "USB0::SIM::EDU36311A::INSTR",
    )
    assert SimulatedResourceManager().list_resources() == SIMULATED_RESOURCES


@pytest.mark.parametrize("resource", SIMULATED_RESOURCES)
def test_simulator_idn_responses_are_parseable_keysight_idns(resource) -> None:
    session = SimulatedResourceManager().open_resource(resource)

    idn = parse_idn(session.query("*IDN?"))

    assert idn.parse_ok is True
    assert idn.manufacturer == "KEYSIGHT"
    assert idn.raw == SIMULATED_IDN[resource]


@pytest.mark.parametrize(
    ("resource", "channel", "expected_voltage", "expected_current"),
    [
        ("USB0::SIM::E36312A::INSTR", 1, "1.100", "0.110"),
        ("USB0::SIM::E36312A::INSTR", 2, "2.200", "0.220"),
        ("USB0::SIM::E36312A::INSTR", 3, "3.300", "0.330"),
        ("USB0::SIM::EDU36311A::INSTR", 1, "1.010", "0.101"),
        ("USB0::SIM::EDU36311A::INSTR", 2, "2.020", "0.202"),
        ("USB0::SIM::EDU36311A::INSTR", 3, "3.030", "0.303"),
    ],
)
def test_first_target_simulator_supports_channel_list_measurements(
    resource,
    channel,
    expected_voltage,
    expected_current,
) -> None:
    session = SimulatedResourceManager().open_resource(resource)

    assert session.query(f"MEAS:VOLT? (@{channel})") == expected_voltage
    assert session.query(f"MEAS:CURR? (@{channel})") == expected_current


def test_generic_simulator_supports_default_measurement_queries() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36103B::INSTR")

    assert session.query("MEAS:VOLT?") == "1.000"
    assert session.query("MEAS:CURR?") == "0.050"


def test_generic_simulator_rejects_unmodeled_channel_list() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36103B::INSTR")

    with pytest.raises(VisaConnectionError, match="No simulated response"):
        session.query("MEAS:VOLT? (@2)")
