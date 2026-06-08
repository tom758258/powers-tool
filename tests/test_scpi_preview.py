import pytest

from keysight_power._scpi_preview import preview_measure_scpi


@pytest.mark.parametrize(
    "idn",
    [
        "KEYSIGHT,E36312A,MY00000001,1.0",
        "KEYSIGHT,EDU36311A,MY00000002,1.0",
    ],
)
@pytest.mark.parametrize("channel", [1, 2, 3])
def test_preview_measure_scpi_uses_first_target_channel_list_queries(idn, channel) -> None:
    assert preview_measure_scpi(idn, channel=channel) == (
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    )


def test_preview_measure_scpi_uses_generic_queries_for_fallback_driver() -> None:
    assert preview_measure_scpi("KEYSIGHT,E36103B,MY00000000,1.0", channel=1) == (
        "MEAS:VOLT?",
        "MEAS:CURR?",
    )
