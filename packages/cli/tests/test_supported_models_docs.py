import json
from pathlib import Path

import keysight_power_cli.cli as cli


def _capabilities(resource: str, capsys) -> dict[str, object]:
    assert cli.main(["capabilities", "--simulate", "--json", "--resource", resource]) == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_supported_models_matrix_matches_cli_support(capsys):
    matrix = Path("packages/core/docs/supported-models.md").read_text(encoding="utf-8")
    assert "E36312A" in matrix
    assert "EDU36311A" in matrix
    assert "Smoke Validation Matrix" in matrix
    assert "hardware_validation=planning_only" in matrix
    assert "not_supported_by_model" in matrix

    e36312a = _capabilities("USB0::SIM::E36312A::INSTR", capsys)["command_support"]
    edu = _capabilities("USB0::SIM::EDU36311A::INSTR", capsys)["command_support"]

    assert e36312a["smoke-output"]["real"] is True
    assert e36312a["protection-set"]["real"] is True
    assert e36312a["trigger-list"]["real"] is True
    assert e36312a["trigger-list"]["dry_run"] is True
    assert edu["validate-readonly"]["real"] is True
    assert edu["smoke-output"]["real"] is True
    assert edu["apply"]["real"] is True
    assert edu["trigger-list"]["real"] is False
    assert edu["protection-set"] == {
        "real": True,
        "simulate": True,
        "dry_run": True,
        "requires_confirm": True,
        "hardware_validation": "validated",
    }
    assert edu["trigger-step"]["hardware_validation"] == "planning_only"
    assert edu["trigger-list"]["hardware_validation"] == "not_supported_by_model"
