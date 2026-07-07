import json
from pathlib import Path

import keysight_power_cli.cli as cli


def _capabilities(resource: str, capsys) -> dict[str, object]:
    assert cli.main(["capabilities", "--simulate", "--json", "--resource", resource]) == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_supported_models_matrix_matches_cli_support(capsys):
    matrix = Path("docs/core/supported-models.md").read_text(encoding="utf-8")
    assert "E36312A" in matrix
    assert "EDU36311A" in matrix
    assert "Smoke Validation Matrix" in matrix
    assert "E36312A-only" in matrix
    assert "not_supported_by_model" in matrix

    e36312a = _capabilities("USB0::SIM::E36312A::INSTR", capsys)["command_support"]
    e3646a = _capabilities("ASRL1::SIM::E3646A::INSTR", capsys)["command_support"]
    edu = _capabilities("USB0::SIM::EDU36311A::INSTR", capsys)["command_support"]

    assert e36312a["smoke-output"]["real"] is True
    assert e36312a["protection-set"]["real"] is True
    assert e36312a["trigger-list"]["real"] is True
    assert e36312a["trigger-list"]["dry_run"] is True
    assert e3646a["set"]["real"] is True
    assert e3646a["set"]["hardware_validation"] == "validated"
    assert e3646a["output-on"]["hardware_validation"] == "validated_confirm_threshold_conditional"
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
    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert edu[command]["real"] is False
        assert edu[command]["simulate"] is False
        assert edu[command]["dry_run"] is False
        assert edu[command]["hardware_validation"] == "not_supported_by_model"


def test_e3646a_public_status_docs_do_not_use_pending_output_wording():
    docs = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "docs/core/supported-models.md",
            "docs/cli/README.md",
            "docs/cli/USER_GUIDE.md",
            "docs/cli/README.zh-TW.md",
            "docs/cli/USER_GUIDE.zh-TW.md",
            "docs/cli/USER_GUIDE.zh-TW.html",
        )
    )

    stale_tokens = (
        "implemented_pending_hardware_validation",
        "pending hardware validation",
        "experimental output",
        "hardware validation is completed",
        "仍等待實機硬體驗證",
        "實驗性輸出",
        "實驗性的輸出",
        "硬體驗證完成前仍屬實驗性",
        "完成實機硬體驗收",
        "影響輸出的指令仍維持停用",
    )
    for token in stale_tokens:
        assert token not in docs

    assert "INST:NSEL" in docs
    assert "OUTP ON/OFF" in docs
    assert "global output enable/disable" in docs
