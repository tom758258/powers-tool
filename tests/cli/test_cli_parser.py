from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys
import textwrap

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_parser as cli_parser


PARSER_PRIMITIVES = (
    "JsonCliArgumentParser",
    "_add_backend_argument",
    "_add_channel_or_all_argument",
    "_add_completion_pulse_arguments",
    "_add_dry_run_argument",
    "_add_duration_argument",
    "_add_json_argument",
    "_add_lifecycle_format_arguments",
    "_add_lifecycle_timeout_argument",
    "_add_lifecycle_url_argument",
    "_add_model_argument",
    "_add_output_resource_arguments",
    "_add_ramp_completion_pulse_arguments",
    "_add_resource_argument",
    "_add_safety_config_argument",
    "_add_serial_arguments",
    "_add_simulate_argument",
    "_add_timeout_argument",
    "_add_trigger_restore_argument",
    "_add_trigger_wait_arguments",
    "_add_validation_support_policy_argument",
    "_add_write_verification_arguments",
    "_apply_channel",
    "_bool_list",
    "_channels_list",
    "_e36312a_channel",
    "_e36312a_channel_or_all",
    "_float_list",
    "_lifecycle_timeout_ms",
    "_log_channel",
    "_loop_count",
    "_nonnegative_int",
    "_output_channel",
    "_positive_channel",
    "_positive_duration_ms",
    "_positive_float",
    "_positive_int",
    "_positive_max_errors",
    "_positive_max_reads",
    "_safe_off_channel",
    "_status_channel",
    "_trigger_pin",
    "_trigger_pins_list",
    "_trigger_poll_ms",
)


def test_cli_parser_primitives_have_one_owner_and_keep_facade_imports() -> None:
    for name in PARSER_PRIMITIVES:
        assert getattr(cli, name) is getattr(cli_parser, name)

    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions.isdisjoint(PARSER_PRIMITIVES)


def test_root_parser_construction_has_internal_owner_and_public_facade() -> None:
    assert cli._build_parser is cli_parser.build_parser
    assert cli_parser.build_parser.__module__ == "powers_tool_cli.cli_parser"

    parser = cli.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(subparsers.choices) == cli.COMMAND_NAMES


def test_command_parser_registration_uses_explicit_parser_dependencies() -> None:
    root = Path(__file__).resolve().parents[2]
    for module_name in ("output", "trigger", "sequence", "ramp_list", "lifecycle"):
        source = (root / "src" / "powers_tool_cli" / "commands" / f"{module_name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        registration = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "register_commands"
        )
        assert "runtime" not in {argument.arg for argument in registration.args.args}
        assert "sys.modules[__name__]" not in source


def test_cli_parser_import_does_not_load_cli_or_worker() -> None:
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """\
        import sys
        sys.path.insert(0, r"{source}")
        import powers_tool_cli.cli_parser
        assert "powers_tool_cli.cli" not in sys.modules
        assert "powers_tool_cli.worker" not in sys.modules
        """
    ).format(source=root / "src")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
