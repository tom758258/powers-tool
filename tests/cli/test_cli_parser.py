from __future__ import annotations

import argparse
import ast
import inspect
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

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


ROOT_RUNNER_BINDINGS = {
    "run_list_resources": "_run_list_resources",
    "run_verify": "_run_verify",
    "run_clear": "_run_clear",
    "run_error": "_run_error",
    "run_measure": "_run_measure",
    "run_measure_all": "_run_measure_all",
    "run_status": "_run_status",
    "run_validate_readonly": "_run_validate_readonly",
    "run_readback": "_run_readback",
    "run_protection_status": "_run_protection_status",
    "run_protection_set": "_run_protection_set",
    "run_clear_protection": "_run_clear_protection",
    "run_identify": "_run_identify",
    "run_snapshot": "_run_snapshot",
    "run_snapshot_diff": "_run_snapshot_diff",
    "run_hardware_report": "_run_hardware_report",
    "run_restore_from_snapshot": "_run_restore_from_snapshot",
    "run_log": "_run_log",
    "run_doctor": "_run_doctor",
    "run_capabilities": "_run_capabilities",
    "run_safety_inspect": "_run_safety_inspect",
    "run_worker": "_run_worker",
}


ROOT_COMMAND_HANDLERS = {
    ("list-resources",): cli._run_list_resources,
    ("verify",): cli._run_verify,
    ("clear",): cli._run_clear,
    ("error",): cli._run_error,
    ("measure",): cli._run_measure,
    ("measure-all",): cli._run_measure_all,
    ("read-status",): cli._run_status,
    ("validate-readonly",): cli._run_validate_readonly,
    ("readback",): cli._run_readback,
    ("protection-status",): cli._run_protection_status,
    ("protection-set",): cli._run_protection_set,
    ("clear-protection",): cli._run_clear_protection,
    ("identify",): cli._run_identify,
    ("snapshot",): cli._run_snapshot,
    ("snapshot-diff",): cli._run_snapshot_diff,
    ("hardware-report",): cli._run_hardware_report,
    ("restore-from-snapshot",): cli._run_restore_from_snapshot,
    ("log",): cli._run_log,
    ("doctor",): cli._run_doctor,
    ("capabilities",): cli._run_capabilities,
    ("safety", "inspect"): cli._run_safety_inspect,
    ("worker",): cli._run_worker,
}


def _parser_for_path(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> argparse.ArgumentParser:
    current_parser = parser
    for command_name in path:
        subparsers = next(
            (
                action
                for action in current_parser._actions
                if isinstance(action, argparse._SubParsersAction)
            ),
            None,
        )
        assert subparsers is not None, f"No subparsers found while resolving {path!r}."
        assert command_name in subparsers.choices, f"Missing parser path {path!r}."
        current_parser = subparsers.choices[command_name]
    return current_parser


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

def test_cli_parser_build_parser_signature_has_no_whole_module_dependency() -> None:
    sig = inspect.signature(cli_parser.build_parser)
    params = list(sig.parameters.values())

    assert params[0].name == "version_provider"
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert [param.name for param in params if param.kind != inspect.Parameter.KEYWORD_ONLY] == [
        "version_provider"
    ]
    assert not any(
        param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for param in params
    )

    kw_only_params = [p for p in params if p.kind == inspect.Parameter.KEYWORD_ONLY]
    assert {param.name for param in kw_only_params} == set(ROOT_RUNNER_BINDINGS)

    banned_names = {"runtime", "module", "namespace", "runners", "registry", "mapping", "container", "context"}
    for param in params:
        assert param.name not in banned_names, f"Banned parameter '{param.name}' found in signature."


def test_cli_build_parser_does_not_pass_whole_module() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the def build_parser() function definition
    build_parser_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_parser"
    )

    # Find the _build_parser(...) call inside it
    class CallVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.calls: list[ast.Call] = []
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id == "_build_parser":
                self.calls.append(node)
            self.generic_visit(node)

    visitor = CallVisitor()
    visitor.visit(build_parser_node)
    assert len(visitor.calls) == 1, "Expected exactly one call to '_build_parser' inside 'build_parser'."
    call = visitor.calls[0]

    assert len(call.args) == 1
    assert not any(isinstance(arg, ast.Starred) for arg in call.args)
    assert isinstance(call.args[0], ast.Name)
    assert call.args[0].id == "_package_version"
    assert all(keyword.arg is not None for keyword in call.keywords)
    assert len(call.keywords) == len(ROOT_RUNNER_BINDINGS)
    assert {keyword.arg for keyword in call.keywords} == set(ROOT_RUNNER_BINDINGS)
    for keyword in call.keywords:
        assert keyword.arg is not None
        assert isinstance(keyword.value, ast.Name)
        assert keyword.value.id == ROOT_RUNNER_BINDINGS[keyword.arg]


def test_cli_parser_commands_point_to_original_callables() -> None:
    parser = cli.build_parser()
    for path, expected_handler in ROOT_COMMAND_HANDLERS.items():
        parser_for_path = _parser_for_path(parser, path)
        assert parser_for_path.get_default("func") is expected_handler


def test_args_runtime_still_exists_temporarily(monkeypatch: pytest.MonkeyPatch) -> None:
    cli_module = sys.modules[cli.__name__]
    captured_args: argparse.Namespace | None = None

    def mock_doctor(args_obj: argparse.Namespace) -> int:
        nonlocal captured_args
        captured_args = args_obj
        return 0

    monkeypatch.setattr(cli, "_run_doctor", mock_doctor)

    assert cli.main(["doctor", "--simulate", "--json"]) == 0
    assert captured_args is not None
    assert captured_args._runtime is cli_module
