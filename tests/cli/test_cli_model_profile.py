import json

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


class FakeLiveSession:
    def __init__(self, idn: str, *, query_responses: dict[str, str] | None = None) -> None:
        self.idn = idn
        self.query_responses = query_responses or {}
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeLiveSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        if command == "INST:NSEL?":
            return self.query_responses.get(command, "1")
        if command == "SYST:ERR?":
            return self.query_responses.get(command, '0,"No error"')
        if command in self.query_responses:
            return self.query_responses[command]
        raise AssertionError(f"unexpected query {command!r}")


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
    assert "model" in out.lower()
    assert "expected" in out.lower() or "dry-run" in out.lower()


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


def test_live_output_expected_model_match_keeps_idn_selected_e3646a_driver(monkeypatch, capsys) -> None:
    session = FakeLiveSession("Agilent Technologies,E3646A,0,1.0")
    monkeypatch.setattr(cli, "_open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--model",
                "E3646A",
                "--resource",
                "USB0::FAKE::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["resource"]["idn"]["model"] == "E3646A"
    assert session.queries[0] == "*IDN?"
    assert "INST:NSEL 1" in session.writes
    assert "CURR 0.05" in session.writes
    assert "VOLT 1" in session.writes
    assert "CURR 0.05,(@1)" not in session.writes
    assert "VOLT 1,(@1)" not in session.writes


def test_live_output_expected_model_mismatch_fails_before_setup_writes(monkeypatch, capsys) -> None:
    session = FakeLiveSession("Agilent Technologies,E3646A,0,1.0")
    monkeypatch.setattr(cli, "_open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--model",
                "E36312A",
                "--resource",
                "USB0::FAKE::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    message = payload["error"]["message"]
    assert "Expected model E36312A" in message
    assert "connected instrument reported E3646A" in message
    assert "does not override" in message
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_live_trigger_expected_model_mismatch_fails_before_trigger_setup(monkeypatch, capsys) -> None:
    session = FakeLiveSession("Keysight Technologies,E36312A,0,1.0")
    monkeypatch.setattr(cli, "_open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-step",
                "--json",
                "--model",
                "E3646A",
                "--resource",
                "USB0::FAKE::INSTR",
                "--channel",
                "1",
                "--source",
                "bus",
                "--fire",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    message = payload["error"]["message"]
    assert "Expected model E3646A" in message
    assert "connected instrument reported E36312A" in message
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    blocked = ("INIT", "TRIG", "DIG", "LIST", "OUTP", "CURR", "VOLT", "ABOR")
    assert not any(command.startswith(blocked) or command == "*TRG" for command in session.writes)


def test_live_unsupported_expected_model_fails_before_opening(monkeypatch, capsys) -> None:
    opened: list[str] = []

    def fake_open_resource(resource: str, *args, **kwargs):
        opened.append(resource)
        return FakeLiveSession("Agilent Technologies,E3646A,0,1.0")

    monkeypatch.setattr(cli, "_open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--model",
                "FUTURE123",
                "--resource",
                "USB0::FAKE::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert "unsupported model profile" in payload["error"]["message"]
    assert opened == []


def test_live_without_model_remains_idn_driven(monkeypatch, capsys) -> None:
    session = FakeLiveSession("Agilent Technologies,E3646A,0,1.0")
    monkeypatch.setattr(cli, "_open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "E3646A"
    assert "INST:NSEL 1" in session.writes
