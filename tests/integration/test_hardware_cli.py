from __future__ import annotations

import json

import pytest

import keysight_power.cli as cli


pytestmark = [pytest.mark.hardware, pytest.mark.hardware_readonly]


def _json_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err or captured.out
    return json.loads(captured.out)


def _base_args(command: str, resource: str, backend: str | None) -> list[str]:
    args = [command, "--json", "--resource", resource]
    if backend:
        args.extend(["--backend", backend])
    return args


def test_identify_expected_model(
    hardware_resource: str,
    hardware_backend: str | None,
    expected_model: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _json_cli(_base_args("identify", hardware_resource, hardware_backend), capsys)
    if expected_model:
        assert payload["data"]["idn"]["model"] == expected_model


def test_read_only_channel_measurement(
    hardware_resource: str,
    hardware_backend: str | None,
    expected_model: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    channel = "2" if expected_model in {"E36312A", "EDU36311A"} else "1"
    payload = _json_cli(
        [*_base_args("measure", hardware_resource, hardware_backend), "--channel", channel],
        capsys,
    )
    assert payload["data"]["measurements"]["voltage"] is not None
    assert payload["data"]["measurements"]["current"] is not None


@pytest.mark.parametrize("command", ["readback", "status"])
def test_read_only_model_commands(
    command: str,
    hardware_resource: str,
    hardware_backend: str | None,
    expected_model: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if expected_model not in {"E36312A", "EDU36311A"}:
        pytest.skip(f"{command} requires E36312A or EDU36311A")
    payload = _json_cli(_base_args(command, hardware_resource, hardware_backend), capsys)
    assert payload["ok"] is True


def test_read_only_log(
    tmp_path,
    hardware_resource: str,
    hardware_backend: str | None,
    expected_model: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if expected_model not in {"E36312A", "EDU36311A"}:
        pytest.skip("log requires E36312A or EDU36311A")
    payload = _json_cli(
        [
            *_base_args("log", hardware_resource, hardware_backend),
            "--channel",
            "1",
            "--interval-sec",
            "0.1",
            "--samples",
            "1",
            "--csv",
            str(tmp_path / "hardware-log.csv"),
        ],
        capsys,
    )
    assert payload["data"]["samples_written"] == 1


@pytest.mark.hardware_output
def test_output_state_requires_explicit_run_output(
    hardware_resource: str,
    hardware_backend: str | None,
    expected_model: str | None,
    run_output: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not run_output:
        pytest.skip("output-affecting hardware tests require --run-output")
    if expected_model != "E36312A":
        pytest.skip("output smoke is currently E36312A-only")
    payload = _json_cli(
        [*_base_args("output-state", hardware_resource, hardware_backend), "--channel", "1"],
        capsys,
    )
    assert isinstance(payload["data"]["output"]["enabled"], bool)
