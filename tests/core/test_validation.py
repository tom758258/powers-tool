from __future__ import annotations

import pytest

import powers_tool_core.validation as validation
from powers_tool_core.safety import SafetyLimits, SafetyValidationError


def test_positive_and_nonnegative_helpers() -> None:
    assert validation.parse_positive_int("3") == 3
    assert validation.parse_positive_int("4", name="channel") == 4
    assert validation.parse_nonnegative_int("0") == 0
    assert validation.parse_positive_float("1.25") == 1.25

    with pytest.raises(validation.ValidationError, match="value must be a positive integer"):
        validation.parse_positive_int("0")
    with pytest.raises(validation.ValidationError, match="value must be a non-negative integer"):
        validation.parse_nonnegative_int("-1")
    with pytest.raises(validation.ValidationError, match="value must be a positive number"):
        validation.parse_positive_float("nan")


def test_comma_separated_parsers() -> None:
    assert validation.parse_channel_list("1, 2,3") == (1, 2, 3)
    assert validation.parse_float_list("1, 2.5,-3") == (1.0, 2.5, -3.0)
    assert validation.parse_trigger_pins("1,3") == (1, 3)

    with pytest.raises(validation.ValidationError, match="channels must be comma-separated positive integers"):
        validation.parse_channel_list("1,,2")
    with pytest.raises(validation.ValidationError, match="values must be comma-separated numbers"):
        validation.parse_float_list("1,,2")
    with pytest.raises(validation.ValidationError, match="pin must be 1, 2, or 3"):
        validation.parse_trigger_pins("4")


def test_duplicate_trigger_pins_are_rejected() -> None:
    with pytest.raises(validation.ValidationError, match="pins must not contain duplicates"):
        validation.parse_trigger_pins("1,2,1")


def test_expand_channel_selection_all_and_unsupported_message() -> None:
    assert validation.expand_channel_selection("all", (1, 2, 3)) == (1, 2, 3)
    assert validation.expand_channel_selection(2, (1, 2, 3)) == (2,)

    with pytest.raises(
        validation.ChannelSelectionError,
        match=r"channel 4 is not supported; supported: \(1, 2, 3\)",
    ):
        validation.expand_channel_selection(4, (1, 2, 3))


def test_safety_config_alias_without_config_is_rejected() -> None:
    with pytest.raises(validation.SafetyResolutionError, match="resource alias requires --safety-config"):
        validation.resolve_request_safety_limits(
            safety_config=None,
            resource=None,
            resource_alias="bench",
            model=None,
            channel=None,
        )


@pytest.mark.parametrize(
    ("command", "channel"),
    [
        ("set", 1),
        ("apply", "all"),
        ("smoke-output", 2),
        ("ramp", 1),
        ("output-on", 1),
        ("output-on", "all"),
        ("output-off", 1),
        ("output-off", "all"),
        ("output-state", 1),
        ("output-state", "all"),
        ("cycle-output", 1),
        ("cycle-output", "all"),
        ("safe-off", 1),
        ("safe-off", "all"),
    ],
)
def test_validate_output_request_accepts_supported_commands(command: str, channel: int | str) -> None:
    validation.validate_output_request(
        command=command,
        channel=channel,
        safety_limits=SafetyLimits(max_voltage=5, max_current=1, allowed_channels=(1, 2, 3)),
        voltage=1.0,
        current=0.1,
        start_voltage=0.0,
        stop_voltage=1.0,
        step_voltage=0.5,
    )


@pytest.mark.parametrize("command", ["set", "ramp", "smoke-output"])
def test_validate_output_request_rejects_all_for_single_channel_commands(command: str) -> None:
    with pytest.raises(validation.ValidationError, match=f"{command} does not support channel all"):
        validation.validate_output_request(
            command=command,
            channel="all",
            safety_limits=SafetyLimits(max_voltage=5, max_current=1, allowed_channels=(1, 2, 3)),
            voltage=1.0,
            current=0.1,
            start_voltage=0.0,
            stop_voltage=1.0,
            step_voltage=0.5,
        )


def test_validate_output_request_blocks_unsafe_setpoint() -> None:
    with pytest.raises(SafetyValidationError, match="voltage 6 exceeds maximum 5"):
        validation.validate_output_request(
            command="set",
            channel=1,
            safety_limits=SafetyLimits(max_voltage=5),
            voltage=6.0,
            current=0.1,
        )


def test_validate_output_on_readback_blocks_unsafe_setpoint() -> None:
    with pytest.raises(SafetyValidationError, match="voltage 6 exceeds maximum 5"):
        validation.validate_output_on_readback(
            1,
            {"voltage": 6.0, "current": 0.1},
            SafetyLimits(max_voltage=5),
        )


def test_confirmation_required_for_request() -> None:
    limits = SafetyLimits(confirm_above_voltage=2.0, confirm_above_current=0.5)

    assert validation.confirmation_required_for_request(
        voltage=3.0,
        current=0.1,
        limits=limits,
        confirmed=False,
    )
    assert not validation.confirmation_required_for_request(
        voltage=3.0,
        current=0.1,
        limits=limits,
        confirmed=True,
    )
