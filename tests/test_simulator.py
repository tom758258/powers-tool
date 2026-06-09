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
    assert session.query("OUTP?") == "OFF"


def test_generic_simulator_rejects_unmodeled_channel_list() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36103B::INSTR")

    with pytest.raises(VisaConnectionError, match="No simulated response"):
        session.query("MEAS:VOLT? (@2)")


@pytest.mark.parametrize(
    ("resource", "channel"),
    [
        ("USB0::SIM::E36312A::INSTR", 1),
        ("USB0::SIM::E36312A::INSTR", 2),
        ("USB0::SIM::E36312A::INSTR", 3),
    ],
)
def test_first_target_simulator_supports_output_state_queries(resource, channel) -> None:
    session = SimulatedResourceManager().open_resource(resource)

    assert session.query(f"OUTP? (@{channel})") == "OFF"


@pytest.mark.parametrize(
    ("channel", "expected_voltage", "expected_current"),
    [
        (1, "1.000", "0.050"),
        (2, "2.000", "0.100"),
        (3, "3.000", "0.150"),
    ],
)
def test_e36312a_simulator_supports_programmed_setpoint_queries(
    channel,
    expected_voltage,
    expected_current,
) -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    assert session.query(f"VOLT? (@{channel})") == expected_voltage
    assert session.query(f"CURR? (@{channel})") == expected_current


def test_e36312a_simulator_supports_protection_and_identity_queries() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    assert session.query("VOLT:PROT:TRIP?") == "0"
    assert session.query("CURR:PROT:TRIP?") == "0"
    assert session.query("*OPT?") == "0"
    assert session.query("SYST:VERS?") == "1999.0"
    assert session.query("SYST:COMM:RLST?") == "RWLock"


def test_e36312a_simulator_accepts_clear_protection_writes() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("OUTP:PROT:CLE (@2)")

    assert session.commands == ["OUTP:PROT:CLE (@2)"]


def test_e36312a_simulator_accepts_protection_set_writes() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("VOLT:PROT 5,(@2)")
    session.write("CURR:PROT:STAT ON,(@2)")

    assert session.commands == ["VOLT:PROT 5,(@2)", "CURR:PROT:STAT ON,(@2)"]
