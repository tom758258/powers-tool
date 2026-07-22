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

def test_cli_parser_build_parser_signature_has_no_whole_module_dependency() -> None:
    import inspect
    sig = inspect.signature(cli_parser.build_parser)
    params = list(sig.parameters.values())

    # 1. First parameter must be version_provider (positional or keyword)
    assert len(params) > 0
    assert params[0].name == "version_provider"

    # 2. Assert there are exactly 22 keyword-only runner callables
    kw_only_params = [p for p in params if p.kind == inspect.Parameter.KEYWORD_ONLY]
    assert len(kw_only_params) == 22

    # 3. Assert no generic runtime, module, namespace, mapping, or collection parameters are allowed
    banned_names = {"runtime", "module", "namespace", "runners", "registry", "mapping", "container", "context"}
    for param in params:
        assert param.name not in banned_names, f"Banned parameter '{param.name}' found in signature."

    # 4. Verify all keyword-only parameters are runner names starting with 'run_'
    for param in kw_only_params:
        assert param.name.startswith("run_"), f"Keyword-only parameter '{param.name}' must start with 'run_'."


def test_cli_build_parser_does_not_pass_whole_module() -> None:
    import inspect
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

    # Ensure sys.modules[__name__], cli, or similar module references are NOT passed
    for arg in call.args:
        if isinstance(arg, ast.Call):
            # check for sys.modules[...]
            if isinstance(arg.func, ast.Attribute) and arg.func.attr == "modules":
                raise AssertionError("sys.modules must not be passed to '_build_parser'.")
        if isinstance(arg, ast.Name):
            assert arg.id not in ("cli", "sys"), "Module or package namespace passed to '_build_parser'."

    # Ensure the 22 root runners are passed explicitly as keyword arguments
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    assert len(kwargs) == 22
    for k, v in kwargs.items():
        assert k.startswith("run_")
        assert isinstance(v, ast.Name)
        assert v.id.startswith("_run_")


def test_cli_parser_commands_point_to_original_callables() -> None:
    # Verify that the parsed command actions still link to the correct root and lifecycle runners in cli.py
    parser = cli.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    for cmd_name in cli.COMMAND_NAMES:
        expected_func_name = f"_run_{cmd_name.replace('-', '_')}"
        if not hasattr(cli, expected_func_name):
            continue

        sub_parser = subparsers.choices[cmd_name]
        func = sub_parser.get_default("func")
        if func is None:
            continue

        # Only check commands whose default function is defined inside cli.py itself
        # This elegantly skips other modules (like lifecycle or family command modules)
        if getattr(func, "__module__", None) != "powers_tool_cli.cli":
            continue

        expected_callable = getattr(cli, expected_func_name)
        assert func is expected_callable, f"Command '{cmd_name}' has incorrect runner '{func.__name__}'."

    # Verify lifecycle nested client runner (worker command)
    worker_parser = subparsers.choices["worker"]
    func = worker_parser.get_default("func")
    assert func is cli._run_worker, f"Worker command has incorrect runner '{func.__name__ if func else None}'."


def test_args_runtime_still_exists_temporarily() -> None:
    # In this first small step, args._runtime must still exist temporarily as required
    parser = cli.build_parser()
    args = parser.parse_args(["doctor", "--simulate", "--json"])
    # Since main() is not called here, parser.parse_args() doesn't set _runtime directly,
    # but cli.main() does. Let's make sure cli.main() sets args._runtime to sys.modules[__name__]
    # as required for the temporary boundary.
    import sys
    cli_module = sys.modules[cli.__name__]

    # Let's mock the internal run_doctor to make it a no-op so we can run main safely
    orig_doctor = cli._run_doctor
    captured_args = None
    def mock_doctor(args_obj: argparse.Namespace) -> int:
        nonlocal captured_args
        captured_args = args_obj
        return 0

    cli._run_doctor = mock_doctor
    try:
        cli.main(["doctor", "--simulate", "--json"])
        assert captured_args is not None
        assert getattr(captured_args, "_runtime", None) is cli_module, "args._runtime should temporarily exist."
    finally:
        cli._run_doctor = orig_doctor
