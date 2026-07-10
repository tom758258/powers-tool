from keysight_power_core.setpoint_ranges import (
    setpoint_ranges_by_model_metadata,
    setpoint_ranges_for_model,
)


def only_range(model: str, channel: int) -> dict[str, object]:
    ranges = setpoint_ranges_for_model(model)
    assert ranges is not None
    channel_ranges = ranges.channel(channel)
    assert channel_ranges is not None
    assert len(channel_ranges.ranges) == 1
    return channel_ranges.ranges[0].to_dict()


def output_identifier(model: str, channel: int) -> str:
    ranges = setpoint_ranges_for_model(model)
    assert ranges is not None
    channel_ranges = ranges.channel(channel)
    assert channel_ranges is not None
    return channel_ranges.output_identifier


def test_e36312a_programming_ranges() -> None:
    assert only_range("E36312A", 1) == {
        "name": "fixed",
        "aliases": [],
        "rated_range_label": None,
        "voltage_min": 0.0,
        "voltage_max": 6.18,
        "voltage_default": 0.0,
        "voltage_reset": 0.0,
        "current_min": 0.0,
        "current_max": 5.15,
        "current_default": 5.0,
        "current_reset": 5.0,
        "current_min_keyword_value": 0.001,
    }
    assert output_identifier("E36312A", 2) == "P25V"
    assert only_range("E36312A", 2)["voltage_max"] == 25.75
    assert only_range("E36312A", 2)["current_max"] == 1.03
    assert output_identifier("E36312A", 3) == "N25V"
    assert only_range("E36312A", 3)["voltage_max"] == 25.75
    assert only_range("E36312A", 3)["current_min_keyword_value"] == 0.001


def test_edu36311a_programming_ranges_include_current_min_keyword_values() -> None:
    assert only_range("EDU36311A", 1)["voltage_max"] == 6.18
    assert only_range("EDU36311A", 1)["current_max"] == 5.15
    assert only_range("EDU36311A", 1)["current_min"] == 0.0
    assert only_range("EDU36311A", 1)["current_min_keyword_value"] == 0.002
    assert only_range("EDU36311A", 2)["voltage_max"] == 30.9
    assert only_range("EDU36311A", 2)["current_min_keyword_value"] == 0.001
    assert only_range("EDU36311A", 3)["voltage_max"] == 30.9
    assert only_range("EDU36311A", 3)["current_min_keyword_value"] == 0.001


def test_e3646a_programming_ranges_are_range_aware() -> None:
    ranges = setpoint_ranges_for_model("E3646A")
    assert ranges is not None
    assert ranges.channel(1) is not None
    channel_ranges = ranges.channel(1).ranges

    low = channel_ranges[0].to_dict()
    high = channel_ranges[1].to_dict()
    assert low["name"] == "LOW"
    assert low["aliases"] == ["P8V"]
    assert low["rated_range_label"] == "0 to 8 V / 3 A"
    assert low["voltage_max"] == 8.24
    assert low["current_max"] == 3.09
    assert high["name"] == "HIGH"
    assert high["aliases"] == ["P20V"]
    assert high["rated_range_label"] == "0 to 20 V / 1.5 A"
    assert high["voltage_max"] == 20.60
    assert high["current_max"] == 1.545

    assert ranges.channel(2).to_dict() == ranges.channel(1).to_dict() | {"channel": 2, "output_identifier": "OUT2"}


def test_setpoint_ranges_metadata_lists_active_models_only() -> None:
    metadata = setpoint_ranges_by_model_metadata()
    assert set(metadata) == {"E36312A", "EDU36311A", "E3646A"}
    assert metadata["E3646A"]["source"]["pages"] == [
        "printed page 82",
        "printed page 83",
        "printed page 84",
        "printed page 91",
    ]
    assert setpoint_ranges_for_model("E36103B") is None
    assert setpoint_ranges_for_model("E36232A") is None
