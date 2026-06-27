from keysight_power_core.models import (
    REGISTERED_MODELS,
    lookup_model,
    parse_idn,
    resource_interface,
)


def test_parse_standard_keysight_idn() -> None:
    idn = parse_idn("KEYSIGHT,E36312A,SERIAL0000,1.2.3")

    assert idn.raw == "KEYSIGHT,E36312A,SERIAL0000,1.2.3"
    assert idn.manufacturer == "KEYSIGHT"
    assert idn.model == "E36312A"
    assert idn.serial == "SERIAL0000"
    assert idn.firmware == "1.2.3"
    assert idn.parse_ok is True
    assert idn.to_dict() == {
        "raw": "KEYSIGHT,E36312A,SERIAL0000,1.2.3",
        "manufacturer": "KEYSIGHT",
        "model": "E36312A",
        "serial": "SERIAL0000",
        "firmware": "1.2.3",
        "parse_ok": True,
    }


def test_parse_idn_trims_fields() -> None:
    idn = parse_idn(" KEYSIGHT , E36103B , SERIAL0000 , 1.0 ")

    assert idn.manufacturer == "KEYSIGHT"
    assert idn.model == "E36103B"
    assert idn.serial == "SERIAL0000"
    assert idn.firmware == "1.0"
    assert idn.parse_ok is True


def test_parse_idn_missing_fields_are_none_and_not_ok() -> None:
    idn = parse_idn("KEYSIGHT,E36312A")

    assert idn.manufacturer == "KEYSIGHT"
    assert idn.model == "E36312A"
    assert idn.serial is None
    assert idn.firmware is None
    assert idn.parse_ok is False


def test_parse_idn_empty_fields_are_none_and_not_ok() -> None:
    idn = parse_idn("KEYSIGHT,E36312A,,1.0")

    assert idn.serial is None
    assert idn.firmware == "1.0"
    assert idn.parse_ok is False


def test_parse_idn_preserves_extra_commas_in_firmware() -> None:
    idn = parse_idn("KEYSIGHT,E36312A,SERIAL0000,1.2.3,build 4")

    assert idn.firmware == "1.2.3,build 4"
    assert idn.parse_ok is True


def test_resource_interface_detection() -> None:
    assert resource_interface("USB0::A::INSTR") == "USB"
    assert resource_interface("TCPIP0::192.0.2.1::INSTR") == "TCPIP"
    assert resource_interface("GPIB0::5::INSTR") == "GPIB"
    assert resource_interface("ASRL3::INSTR") == "ASRL"
    assert resource_interface("PXI0::1::INSTR") == "UNKNOWN"


def test_known_model_registry_lookup() -> None:
    assert set(REGISTERED_MODELS) == {
        "E36312A",
        "EDU36311A",
        "E36313A",
        "E3646A",
        "E36103B",
        "E36232A",
        "E36233A",
        "E36441A",
        "E36155A",
    }

    model = lookup_model(" e36312a ")

    assert model is not None
    assert model.manufacturer == "KEYSIGHT"
    assert model.model == "E36312A"
    assert model.target_group == "initial"
    assert model.first_hardware_target is True
    assert lookup_model("UNKNOWN") is None
