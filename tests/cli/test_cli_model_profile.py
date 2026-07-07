import pytest

import keysight_power_cli.cli as cli


MODEL_PROFILE_COMMANDS = [
    "set",
    "output-on",
    "output-off",
    "safe-off",
    "output-state",
    "cycle-output",
    "apply",
    "ramp",
    "ramp-list",
    "smoke-output",
    "sequence",
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
    "protection-set",
    "clear-protection",
]

NON_MODEL_PROFILE_COMMANDS = [
    "list-resources",
    "verify",
    "measure",
    "readback",
    "protection-status",
    "identify",
    "snapshot",
    "log",
    "doctor",
    "capabilities",
]


def _parse_args(argv: list[str]):
    return cli.build_parser().parse_args(argv)


@pytest.mark.parametrize("command", MODEL_PROFILE_COMMANDS)
def test_model_profile_commands_expose_model_help(command: str, capsys) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args([command, "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--model" in out
    assert "No-hardware model profile" in out


@pytest.mark.parametrize("command", NON_MODEL_PROFILE_COMMANDS)
def test_selected_commands_do_not_expose_model_help(command: str, capsys) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args([command, "--help"])

    assert exc.value.code == 0
    assert "--model" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        [
            "set",
            "--dry-run",
            "--model",
            "FUTURE123",
            "--channel",
            "1",
            "--voltage",
            "1",
            "--current",
            "0.05",
        ],
        [
            "trigger-step",
            "--dry-run",
            "--model",
            "FUTURE123",
            "--channel",
            "1",
            "--source",
            "bus",
            "--fire",
        ],
        [
            "sequence",
            "--dry-run",
            "--model",
            "FUTURE123",
            "--file",
            "examples/sequence-readonly.yaml",
        ],
        [
            "ramp-list",
            "--dry-run",
            "--model",
            "FUTURE123",
            "--file",
            "examples/ramp-list",
        ],
    ],
)
def test_model_profile_is_not_argparse_choices(argv: list[str]) -> None:
    args = _parse_args(argv)

    assert args.model == "FUTURE123"


@pytest.mark.parametrize(
    ("argv", "request_builder", "expected_model"),
    [
        (
            [
                "ramp-list",
                "--dry-run",
                "--model",
                "E3646A",
                "--file",
                "examples/ramp-list",
            ],
            cli._ramp_list_request_for_args,
            "E3646A",
        ),
        (
            [
                "sequence",
                "--dry-run",
                "--model",
                "E36312A",
                "--file",
                "examples/sequence-readonly.yaml",
            ],
            cli._sequence_request_for_args,
            "E36312A",
        ),
        (
            [
                "set",
                "--dry-run",
                "--model",
                "E3646A",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ],
            cli._operation_request_for_args,
            "E3646A",
        ),
        (
            [
                "trigger-step",
                "--dry-run",
                "--model",
                "E36312A",
                "--channel",
                "1",
                "--source",
                "bus",
                "--fire",
            ],
            cli._trigger_request_for_args,
            "E36312A",
        ),
    ],
)
def test_model_profile_maps_to_runtime_options(argv, request_builder, expected_model: str) -> None:
    args = _parse_args(argv)
    request = request_builder(args)

    assert request.runtime.model_profile == expected_model
