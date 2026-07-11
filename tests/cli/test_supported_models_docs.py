import json
import re
from pathlib import Path

import keysight_power_cli.cli as cli


def _capabilities(resource: str, capsys) -> dict[str, object]:
    assert cli.main(["capabilities", "--simulate", "--json", "--resource", resource]) == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_supported_models_matrix_matches_cli_support(capsys):
    matrix = Path("docs/core/supported-models.md").read_text(encoding="utf-8")
    assert "E36312A" in matrix
    assert "EDU36311A" in matrix
    assert "Live Suite Validation Matrix" in matrix
    assert "scripts/live-cli-check.ps1" in matrix
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


def test_public_docs_describe_strict_no_hardware_model_profiles():
    docs = {
        path: Path(path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/cli/README.md",
            "docs/cli/USER_GUIDE.md",
            "docs/core/README.md",
            "docs/core/supported-models.md",
            "docs/contracts/power-cli-jsonl-contract.md",
            "docs/webui/README.md",
            "docs/webui/USER_GUIDE.md",
        )
    }
    combined = "\n".join(docs.values())

    assert "No-Hardware Model-Profile Matrix" in docs["docs/core/supported-models.md"]
    assert "suite validates only" in "\n".join(docs.values())
    assert "runtime.model_profile" in docs["docs/contracts/power-cli-jsonl-contract.md"]
    assert "runtime.model" in docs["docs/contracts/power-cli-jsonl-contract.md"]
    assert "runtime.model_profile" in docs["docs/webui/README.md"]
    assert "deterministic SIM resource" in combined
    assert "USB0::FAKE::E36312A::INSTR" in combined
    assert "must not imply a model" in combined
    assert "Live hardware uses the IDN-detected model" in combined


def test_public_docs_describe_p4_policy_boundary_without_publishing_hidden_switch():
    paths = (
        "README.md",
        "docs/core/README.md",
        "docs/core/supported-models.md",
        "docs/cli/README.md",
        "docs/cli/USER_GUIDE.md",
        "docs/contracts/power-worker-contract.md",
        "docs/webui/README.md",
        "docs/webui/USER_GUIDE.md",
    )
    docs = {path: Path(path).read_text(encoding="utf-8") for path in paths}
    hidden_switch = "--validation-allow-pending-live-support"

    assert hidden_switch not in "\n".join(docs.values())
    assert "RuntimeOptions.support_policy_mode" in docs["docs/core/README.md"]
    assert "contributor-validation policy mode" in docs["docs/core/README.md"]
    assert "registered pending candidates, not\nproduct-open support" in docs["docs/core/supported-models.md"]
    assert "Normal CLI operation always uses the product live-support policy" in docs["docs/cli/README.md"]
    assert "Worker always operates in the product support-policy mode" in docs["docs/contracts/power-worker-contract.md"]
    assert "Validation-policy runtime fields are rejected" in docs["docs/webui/README.md"]
    assert "The WebUI is product-only" in docs["docs/webui/USER_GUIDE.md"]


def test_contributor_guide_documents_p5_validation_boundary_without_publishing_switch_elsewhere():
    public_paths = (
        "README.md",
        "docs/core/README.md",
        "docs/core/supported-models.md",
        "docs/cli/README.md",
        "docs/cli/USER_GUIDE.md",
        "docs/contracts/power-worker-contract.md",
        "docs/webui/README.md",
        "docs/webui/USER_GUIDE.md",
    )
    hidden_switch = "--validation-allow-pending-live-support"
    guide = Path("docs/CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "[Contributing](docs/CONTRIBUTING.md)" in Path("README.md").read_text(encoding="utf-8")
    assert hidden_switch in guide
    assert "not a general `--force`" in guide
    assert "Missing metadata is not pending support." in guide
    assert "do not automatically promote product support" in guide
    assert "Attach only the files from `shareable/`" in guide
    assert "local raw execution files in `private/`" in guide
    assert "Never upload or manually copy files from `private/`." in guide
    assert "Failed or\nmalformed raw command output remains private" in guide
    assert "raw resource, private IP address, complete serial number, raw\nIDN string, personal filesystem path, or any file from `private/`" in guide
    assert "Skipped or incomplete cleanup is not cleanup-verified evidence." in guide
    assert "outputs are\nconfirmed OFF, and the final error queue is clean" in guide
    assert "explicit resource" in guide
    for required_phrase in (
        "output OFF before and after",
        "low voltage and current limit",
        "OVP/OCP",
        "cleanup",
        "private IP address",
    ):
        assert required_phrase in guide
    assert hidden_switch not in "\n".join(Path(path).read_text(encoding="utf-8") for path in public_paths)
    combined = "\n".join(Path(path).read_text(encoding="utf-8") for path in (*public_paths, "docs/CONTRIBUTING.md"))
    assert "Local/docs" not in combined


def test_public_dry_run_examples_do_not_use_live_resource_without_model():
    checked_paths = (
        "README.md",
        "docs/cli/README.md",
        "docs/cli/USER_GUIDE.md",
        "docs/core/README.md",
        "docs/core/supported-models.md",
        "docs/contracts/power-cli-jsonl-contract.md",
        "docs/webui/README.md",
        "docs/webui/USER_GUIDE.md",
    )
    offenders: list[str] = []
    for path in checked_paths:
        for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
            if "--dry-run" not in line:
                continue
            if "$env:KEYSIGHT_POWER_RESOURCE" in line and "--model" not in line and "::SIM::" not in line:
                offenders.append(f"{path}:{line_number}: {line}")
            if re.search(r"USB0::FAKE::\w+::INSTR", line) and "--dry-run" in line and "--model" not in line:
                context = "\n".join(Path(path).read_text(encoding="utf-8").splitlines()[max(0, line_number - 5):line_number + 2])
                if "rejected" not in context and "Not OK" not in context:
                    offenders.append(f"{path}:{line_number}: {line}")

    assert offenders == []


def test_no_hardware_scripts_use_model_or_deterministic_sim_resources():
    preflight = Path("scripts/preflight-smoke-validation.ps1").read_text(encoding="utf-8")
    live_cli_check = Path("scripts/live-cli-check.ps1").read_text(encoding="utf-8")
    batch = Path("scripts/batch-validation.ps1").read_text(encoding="utf-8")

    assert "USB0::SIM::E36312A::INSTR" in preflight
    assert "USB0::SIM::EDU36311A::INSTR" in preflight
    assert "ASRL1::SIM::E3646A::INSTR" in live_cli_check
    assert "E36103B" not in live_cli_check
    assert "E36232A" not in live_cli_check
    assert "deterministic SIM resources" in preflight
    assert "Test-DeterministicSimResource" in batch
    assert '"USB0::SIM::E36312A::INSTR"' in batch
    assert '"USB0::SIM::EDU36311A::INSTR"' in batch
    assert '@("--model", "E36312A")' in batch


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
