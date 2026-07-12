from __future__ import annotations

import ast
import inspect
from pathlib import Path

import powers_tool_cli.cli as cli


CLI_SOURCE = Path(cli.__file__).read_text(encoding="utf-8")


def test_cli_does_not_access_driver_private_session() -> None:
    tree = ast.parse(CLI_SOURCE)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "_session":
            continue
        owner = next(
            (
                candidate
                for candidate in ast.walk(tree)
                if isinstance(candidate, ast.ClassDef)
                and candidate.name == "_ScpiLoggingSession"
                and node in ast.walk(candidate)
            ),
            None,
        )
        if owner is None:
            violations.append(node.lineno)
    assert violations == []


def test_active_restore_trigger_and_sequence_adapters_delegate_scpi_to_core() -> None:
    restore_source = inspect.getsource(cli._run_restore_from_snapshot)
    trigger_source = inspect.getsource(cli._run_core_trigger)
    sequence_source = inspect.getsource(cli._run_sequence)

    assert "restore_core.run_restore" in restore_source
    assert "trigger_core.run_trigger" in trigger_source
    assert "sequence.run_sequence" in sequence_source
    assert "_open_resource(" not in restore_source
    assert "create_power_supply(" not in restore_source
    assert not any(token in restore_source for token in ("OUTP ", "VOLT:", "CURR:", "SYST:ERR?"))
    assert not any(token in trigger_source for token in ("ABOR ", "INIT ", "LIST:", "TRIG:SOUR"))
    assert not any(token in sequence_source for token in ("OUTP ", "VOLT ", "CURR ", "SYST:ERR?"))
