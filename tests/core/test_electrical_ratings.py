import pytest

from powers_tool_core.electrical_ratings import (
    electrical_ratings_by_model_metadata,
    ratings_for_model_id,
)
from powers_tool_core.safety import SafetyLimits, SafetyValidationError
from powers_tool_core.setpoint_limits import effective_setpoint_limits, validate_effective_setpoint


@pytest.mark.parametrize(
    ("model", "channel", "max_voltage", "max_current"),
    [
        ("keysight-e36312a", 1, 6.0, 5.0),
        ("keysight-e36312a", 2, 25.0, 1.0),
        ("keysight-e36312a", 3, 25.0, 1.0),
        ("keysight-edu36311a", 1, 6.0, 5.0),
        ("keysight-edu36311a", 2, 30.0, 1.0),
        ("keysight-edu36311a", 3, 30.0, 1.0),
    ],
)
def test_verified_channel_ratings(model, channel, max_voltage, max_current) -> None:
    ratings = ratings_for_model_id(model)

    assert ratings is not None
    assert ratings.channel(channel).max_voltage == max_voltage
    assert ratings.channel(channel).max_current == max_current
    validate_effective_setpoint(
        model=model,
        channel=channel,
        electrical_ratings=ratings,
        voltage=max_voltage,
        current=max_current,
    )


def test_official_rating_rejects_above_boundary_with_source() -> None:
    ratings = ratings_for_model_id("keysight-e36312a")

    with pytest.raises(
        SafetyValidationError,
        match=r"voltage 6\.01 exceeds effective maximum 6 V for E36312A channel 1, limited by official DC output rating",
    ):
        validate_effective_setpoint(
            model="E36312A",
            channel=1,
            electrical_ratings=ratings,
            voltage=6.01,
        )


def test_safety_config_can_only_make_rating_more_restrictive() -> None:
    ratings = ratings_for_model_id("keysight-e36312a")

    restrictive = effective_setpoint_limits(
        model="E36312A",
        channel=2,
        electrical_ratings=ratings,
        safety_limits=SafetyLimits(max_voltage=5, max_current=0.5),
    )
    permissive = effective_setpoint_limits(
        model="E36312A",
        channel=2,
        electrical_ratings=ratings,
        safety_limits=SafetyLimits(max_voltage=50, max_current=5),
    )

    assert (restrictive.max_voltage, restrictive.voltage_source) == (5, "safety config")
    assert (restrictive.max_current, restrictive.current_source) == (0.5, "safety config")
    assert (permissive.max_voltage, permissive.voltage_source) == (25, "official DC output rating")
    assert (permissive.max_current, permissive.current_source) == (1, "official DC output rating")


def test_unknown_model_has_no_invented_rating() -> None:
    assert ratings_for_model_id("UNKNOWN") is None
    assert set(electrical_ratings_by_model_metadata()) == {
        "keysight-e36312a",
        "keysight-edu36311a",
    }
