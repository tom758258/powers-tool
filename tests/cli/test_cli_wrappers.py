from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")
PSM2010_SMOKE_CASES = (
    "identify-simulate",
    "capabilities-simulate",
    "measure-ch1-simulate",
    "output-state-ch1-simulate",
    "set-dry-run",
)
PSM2010_DEEP_CASES = (
    "list-resources-simulate",
    "verify-simulate",
    "readback-simulate",
    "read-status-simulate",
    "error-simulate",
    "output-off-simulate",
    "safe-off-simulate",
    "output-state-dry-run",
    "output-off-dry-run",
    "safe-off-dry-run",
    "ramp-list-dry-run",
    "sequence-dry-run",
    "protection-status-simulate",
    "protection-set-dry-run",
    "snapshot-simulate",
)


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_validation_script_inventory_and_obsolete_removals() -> None:
    assert (ROOT / "scripts" / "preflight-cli.ps1").is_file()
    assert (ROOT / "scripts" / "live-cli-check.ps1").is_file()
    assert (ROOT / "scripts" / "_validation_helpers.ps1").is_file()
    for obsolete in (
        "no-hardware-regression.ps1",
        "preflight-smoke-validation.ps1",
        "live-smoke-validation-check.ps1",
    ):
        assert not (ROOT / "scripts" / obsolete).exists()


@pytest.mark.windows_powershell
def test_shared_helper_owns_all_model_and_suite_boundaries() -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    helper = ROOT / "scripts" / "_validation_helpers.ps1"
    command = (
        f". '{helper}'; "
        "$profiles = @(Get-ValidationTargetProfiles | ForEach-Object { "
        "[pscustomobject]@{ "
        "model_id=$_.model_id; vendor_id=$_.vendor_id; model=$_.model; "
        "model_name=$_.model_name; reported_manufacturer_aliases=@($_.reported_manufacturer_aliases); "
        "canonical_display_name=$_.canonical_display_name; channels=@($_.channels); "
        "simulator_resource=$_.simulator_resource; suites=@($_.suites) "
        "} }); "
        "$smokeCases = @(Get-ValidationPreflightCases -Target 'keysight-e36312a' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'smoke'); "
        "$deepCases = @(Get-ValidationPreflightCases -Target 'keysight-e36312a' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'deep'); "
        "$fullCases = @(Get-ValidationPreflightCases -Target 'keysight-e36312a' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'full'); "
        "$psmSmokeCases = @(Get-ValidationPreflightCases -Target 'gw-instek-psm-2010' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'smoke'); "
        "$psmDeepCases = @(Get-ValidationPreflightCases -Target 'gw-instek-psm-2010' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'deep'); "
        "$psmFullCases = @(Get-ValidationPreflightCases -Target 'gw-instek-psm-2010' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'full'); "
        "$result = [pscustomobject]@{ "
        "profiles=$profiles; "
        "suites=@((Resolve-ValidationSuite -Suite 'smoke'), "
        "(Resolve-ValidationSuite -Suite 'deep'), "
        "(Resolve-ValidationSuite -Suite 'full')); "
        "smoke_targets=@(Resolve-ValidationPreflightTargets -Target 'all' -Suite 'smoke'); "
        "full_targets=@(Resolve-ValidationPreflightTargets -Target 'all' -Suite 'full'); "
        "deep_targets=@(Resolve-ValidationPreflightTargets -Target 'all' -Suite 'deep'); "
        "smoke_cases=@($smokeCases | ForEach-Object { $_.name }); "
        "deep_cases=@($deepCases | ForEach-Object { $_.name }); "
        "full_cases=@($fullCases | ForEach-Object { $_.name }); "
        "psm_smoke_cases=@($psmSmokeCases | ForEach-Object { $_.name }); "
        "psm_deep_cases=@($psmDeepCases | ForEach-Object { $_.name }); "
        "psm_full_cases=@($psmFullCases | ForEach-Object { $_.name }) "
        "}; "
        "ConvertTo-Json -InputObject $result -Compress -Depth 6"
    )
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inventory = json.loads(result.stdout)
    profiles = {item["model_id"]: item for item in inventory["profiles"]}
    assert set(profiles) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
        "gw-instek-psm-2010",
    }
    assert profiles["keysight-e36312a"]["suites"] == [
        "readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence"
    ]
    assert profiles["keysight-edu36311a"]["suites"] == [
        "readonly", "output", "protection", "software-sequence"
    ]
    assert profiles["keysight-e3646a"]["suites"] == [
        "readonly", "output", "software-sequence"
    ]
    assert profiles["gw-instek-psm-2010"] == {
        "model_id": "gw-instek-psm-2010",
        "vendor_id": "gw-instek",
        "model": "PSM-2010",
        "model_name": "PSM-2010",
        "reported_manufacturer_aliases": ["GW.Inc"],
        "canonical_display_name": "GW Instek PSM-2010",
        "channels": [1],
        "simulator_resource": "ASRL1::SIM::PSM2010::INSTR",
        "suites": [
            "readonly", "safe-state", "output", "protection", "snapshot",
            "software-sequence",
        ],
    }
    assert inventory["suites"] == ["smoke", "deep", "full"]
    assert inventory["smoke_targets"] == [
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
        "gw-instek-psm-2010",
    ]
    assert inventory["full_targets"] == inventory["smoke_targets"]
    assert inventory["deep_targets"] == ["keysight-e36312a", "keysight-e3646a"]
    assert inventory["smoke_cases"] == [
        "identify-simulate",
        "capabilities-simulate",
        "measure-ch1-simulate",
        "set-dry-run",
    ]
    assert len(inventory["deep_cases"]) == 12
    assert set(inventory["full_cases"]) == {
        *inventory["smoke_cases"],
        *inventory["deep_cases"],
    }
    assert set(inventory["psm_smoke_cases"]) == set(PSM2010_SMOKE_CASES)
    assert set(inventory["psm_deep_cases"]) == set(PSM2010_DEEP_CASES)
    assert set(inventory["psm_full_cases"]) == {
        *PSM2010_SMOKE_CASES,
        *PSM2010_DEEP_CASES,
    }
    assert {
        "set-dry-run",
        "ramp-list-dry-run",
        "sequence-dry-run",
    }.issubset(inventory["psm_full_cases"])


@pytest.mark.parametrize(
    ("suite", "expected_cases"),
    [
        ("smoke", set(PSM2010_SMOKE_CASES)),
        ("full", {*PSM2010_SMOKE_CASES, *PSM2010_DEEP_CASES}),
    ],
)
@pytest.mark.windows_powershell
def test_psm2010_preflight_executes_maintained_no_hardware_cases(
    suite: str, expected_cases: set[str]
) -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "gw-instek-psm-2010",
        "-Suite", suite,
        "-DebugArtifacts",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    report_path = next(output.glob("run_*/gw-instek-psm-2010/shareable/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["suite"] == suite
    assert report["targets"] == ["gw-instek-psm-2010"]
    assert report["hardware_touched"] is False
    assert report["visa_io_performed"] is False
    assert report["resource_scan_performed"] is False
    assert report["resource_guess_performed"] is False

    target_report = report
    assert target_report["model_id"] == "gw-instek-psm-2010"
    assert target_report["expected_model"] == "PSM-2010"
    assert target_report["simulator_resource"] == "ASRL1::SIM::PSM2010::INSTR"
    assert target_report["suites"] == [
        "readonly", "safe-state", "output", "protection", "snapshot",
        "software-sequence",
    ]
    assert target_report["visa_io_performed"] is False
    assert target_report["resource_scan_performed"] is False
    assert target_report["resource_guess_performed"] is False

    commands = {command["name"]: command for command in target_report["commands"]}
    assert set(commands) == expected_cases
    assert "set-dry-run" in commands
    if suite == "full":
        assert {"ramp-list-dry-run", "sequence-dry-run"}.issubset(commands)
    assert all(
        command["passed"] is True and command["hardware_touched"] is False
        for command in commands.values()
    )
    assert all(
        command["dry_run"] is True
        if name.endswith("-dry-run")
        else command["mode"] == "simulate"
        for name, command in commands.items()
    )


@pytest.mark.windows_powershell
def test_representative_smoke_executes_required_no_hardware_cli() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-edu36311a",
        "-Suite", "smoke",
        "-DebugArtifacts",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    reports = sorted(output.glob("run_*/keysight-edu36311a/shareable/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["kind"] == "powers-tool-cli-preflight"
    assert report["status"] == "passed"
    assert report["suite"] == "smoke"
    assert report["targets"] == ["keysight-edu36311a"]
    assert report["hardware_touched"] is False
    assert report["summary_counts"]["failed"] == 0
    assert "Suite: `smoke`" in reports[0].with_name("summary.md").read_text(
        encoding="utf-8"
    )

    target_report = report
    commands = {command["name"]: command for command in target_report["commands"]}
    assert set(commands) == {
        "identify-simulate",
        "capabilities-simulate",
        "measure-ch1-simulate",
        "set-dry-run",
    }
    identify = json.loads(
        (ROOT / commands["identify-simulate"]["json_path"]).read_text(encoding="utf-8")
    )
    assert identify["data"]["idn"]["model"] == "EDU36311A"
    capabilities = json.loads(
        (ROOT / commands["capabilities-simulate"]["json_path"]).read_text(encoding="utf-8")
    )
    assert capabilities["data"]["resource"]["model_id"] == "keysight-edu36311a"
    planned_set = json.loads(
        (ROOT / commands["set-dry-run"]["json_path"]).read_text(encoding="utf-8")
    )
    assert (
        planned_set["data"]["plan"]["target"]["planning_model_id"]
        == "keysight-edu36311a"
    )
    assert all(
        command["suite"] == "smoke"
        and command["passed"] is True
        and command["hardware_touched"] is False
        for command in commands.values()
    )


@pytest.mark.windows_powershell
def test_representative_deep_executes_required_no_hardware_cli() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-e3646a",
        "-Suite", "deep",
        "-DebugArtifacts",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = next(output.glob("run_*/keysight-e3646a/shareable/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suite"] == "deep"
    assert report["targets"] == ["keysight-e3646a"]
    assert report["hardware_touched"] is False
    assert "Suite: `deep`" in report_path.with_name("summary.md").read_text(
        encoding="utf-8"
    )

    e3646a = report
    assert {command["category"] for command in e3646a["commands"]} >= {
        "software-sequence",
        "safe-off",
    }
    e3646a_commands = {
        command["name"]: command for command in e3646a["commands"]
    }
    e3646a_safe_off = json.loads(
        (ROOT / e3646a_commands["safe-off-dry-run"]["json_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert e3646a_safe_off["data"]["plan"]["target"] == {
        "channel": "all",
        "planning_model_id": "keysight-e3646a",
        "planning_profile_id": None,
        "resource": None,
    }
    assert all(
        command["hardware_touched"] is False
        for command in e3646a["commands"]
    )
    assert not (report_path.parents[2] / "keysight-e36312a").exists()
    assert not (report_path.parent / "keysight-edu36311a").exists()


@pytest.mark.windows_powershell
def test_preflight_rejects_unsupported_suite_and_target() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    invalid_suite = _run(
        "scripts/preflight-cli.ps1",
        "-Suite", "unknown",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert invalid_suite.returncode != 0
    assert "Suite" in invalid_suite.stderr

    invalid_target = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "unknown-model",
        "-Suite", "smoke",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert invalid_target.returncode == 2
    assert "Unsupported target" in invalid_target.stderr

    unsupported_deep_target = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-edu36311a",
        "-Suite", "deep",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert unsupported_deep_target.returncode == 2
    assert "not a deep preflight representative" in unsupported_deep_target.stderr


@pytest.mark.parametrize("failed", [False, True], ids=["passed", "failed"])
@pytest.mark.windows_powershell
def test_preflight_minimal_retains_two_reports_per_model(failed) -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    if failed:
        command = rf'''
function global:ConvertFrom-Json {{
    [CmdletBinding()] param([Parameter(ValueFromPipeline=$true)][string]$InputObject)
    process {{
        $value = Microsoft.PowerShell.Utility\ConvertFrom-Json -InputObject $InputObject
        if ($null -ne $value.PSObject.Properties["ok"]) {{ $value.ok = $false }}
        return $value
    }}
}}
& .\scripts\preflight-cli.ps1 -Target all -Suite smoke -OutputRoot "{output}"
'''
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
    else:
        result = _run(
            "scripts/preflight-cli.ps1",
            "-Target", "all", "-Suite", "smoke",
            "-OutputRoot", str(output.relative_to(ROOT)),
        )
    assert result.returncode == int(failed), result.stdout + result.stderr
    run = next(output.glob("run_*"))
    assert not (run / "report.json").exists()
    reports = sorted(run.glob("*/shareable/report.json"))
    assert len(reports) == 4
    for report_path in reports:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["artifact_mode"] == "minimal"
        assert report["status"] == ("failed" if failed else "passed")
        assert report["hardware_touched"] is False
        assert report["commands"]
        assert all(command["json_path"] is None for command in report["commands"])
        assert all(command["assertions"] for command in report["commands"])
    assert len([p for p in run.rglob("*") if p.is_file()]) == len(reports) * 2


@pytest.mark.parametrize(
    ("surface", "boundary"),
    [("live", "normal"), ("live", "outside"), ("live", "ancestor"),
     ("live", "run"), ("live", "child"), ("preflight", "outside"),
     ("preflight", "ancestor"), ("preflight", "output-root")],
)
@pytest.mark.windows_powershell
def test_validation_output_paths_are_checked_before_writing(surface, boundary) -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    parent = ROOT / ".tmp_tests" / "pytest_output_paths" / uuid4().hex
    parent.mkdir(parents=True)
    target = parent / "target"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("outside evidence", encoding="utf-8")
    sibling = parent / "sibling-run"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("another run", encoding="utf-8")
    output = parent / "run"
    link = None
    if boundary == "outside":
        output = ROOT / ("unsafe-validation-" + uuid4().hex)
    elif boundary in {"ancestor", "run", "output-root", "child"}:
        link = parent / "link"
        if boundary == "child":
            output.mkdir()
            (output / "original.txt").write_text("current evidence", encoding="utf-8")
            link = output / "link"
        create = subprocess.run(
            [POWERSHELL, "-NoProfile", "-Command",
             f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' -ErrorAction Stop | Out-Null"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        assert create.returncode == 0, create.stdout + create.stderr
        if boundary != "child":
            output = link / "new-output" if boundary == "ancestor" else link
    else:
        output.mkdir()
        (output / "old.txt").write_text("old current run", encoding="utf-8")
    if surface == "live":
        command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
try {{ Reset-OutputDirectory -Path "{output}" -Root $TmpRoot | Out-Null }} catch {{ exit 1 }}
exit 0
'''
    else:
        command = rf'& .\scripts\preflight-cli.ps1 -Target keysight-e36312a -Suite smoke -OutputRoot "{output}"'
    try:
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode == (0 if boundary == "normal" else 1), result.stdout + result.stderr
        assert sentinel.read_text(encoding="utf-8") == "outside evidence"
        assert {p.relative_to(target).as_posix() for p in target.rglob("*")} == {"keep.txt"}
        assert (sibling / "keep.txt").read_text(encoding="utf-8") == "another run"
        if boundary == "normal":
            assert list(output.iterdir()) == []
        elif boundary == "child":
            assert (output / "original.txt").read_text(encoding="utf-8") == "current evidence"
        elif boundary in {"ancestor", "outside"}:
            assert not output.exists()
    finally:
        if link is not None:
            link.rmdir()


@pytest.mark.windows_powershell
def test_shared_capture_helper_defaults_to_memory_without_raw_files() -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    output = ROOT / ".tmp_tests" / "pytest_capture_helper" / uuid4().hex
    output.mkdir(parents=True)
    helper = ROOT / "scripts" / "_validation_helpers.ps1"
    out_path = output / "stdout.txt"
    err_path = output / "stderr.txt"
    command = (
        f". '{helper}'; "
        "$argsForChild = @('-NoProfile','-Command','[Console]::Out.WriteLine(\"captured\"); [Console]::Error.WriteLine(\"warning\")'); "
        f"$memory = Invoke-CapturedValidationCommand -FilePath 'powershell.exe' -Arguments $argsForChild -CaptureInMemory -StdOutPath '{out_path}' -StdErrPath '{err_path}'; "
        "if ($memory.stdout_text.Trim() -ne 'captured' -or $memory.stderr_text.Trim() -ne 'warning' -or $memory.exit_code -ne 0) { exit 7 }; "
        f"if (Test-Path '{out_path}') {{ exit 8 }}; "
        f"$saved = Invoke-CapturedValidationCommand -FilePath 'powershell.exe' -Arguments $argsForChild -StdOutPath '{out_path}' -StdErrPath '{err_path}'; "
        "if ($saved.exit_code -ne 0 -or -not (Test-Path $saved.stdout_path) -or -not (Test-Path $saved.stderr_path)) { exit 9 }; "
        "exit 0"
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "boundary",
    ["normal", "tmp-root", "ancestor", "run", "child", "missing-run", "root-itself", "outside", "remove-error"],
)
@pytest.mark.windows_powershell
def test_shareable_generation_failure_keeps_only_safe_summary_in_current_run(boundary) -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    tmp_root = ROOT / ".tmp_tests"
    parent = tmp_root / "pytest_artifact_failure" / uuid4().hex
    run = parent / "failed-run"
    sibling = parent / "sibling-run"
    (run / "shareable").mkdir(parents=True)
    sibling.mkdir(parents=True)
    sentinel = sibling / "keep.txt"
    sentinel.write_text("another run", encoding="utf-8")
    report = run / "shareable" / "report.json"
    report.write_text("{invalid", encoding="utf-8")
    summary = run / "shareable" / "summary.md"
    summary.write_text("partial summary", encoding="utf-8")
    helper = ROOT / "scripts" / "_validation_helpers.ps1"
    link = None
    if boundary != "normal":
        sandbox = parent / "sandbox"
        sandbox.mkdir()
        tmp_root = sandbox / ".tmp_tests"
        tmp_root.mkdir()
        cleanup_run = tmp_root / "run"
        cleanup_run.mkdir()
        (cleanup_run / "keep.txt").write_text("current run", encoding="utf-8")
        linked_run = parent / "linked-run"
        if boundary in {"tmp-root", "ancestor", "run", "child", "missing-run"}:
            if boundary == "ancestor":
                link, target = parent / "linked-sandbox", sandbox
                tmp_root = link / ".tmp_tests"
                cleanup_run = tmp_root / "run"
            elif boundary in {"tmp-root", "missing-run"}:
                link, target = parent / "linked-tmp", tmp_root
                tmp_root = link
                cleanup_run = link / ("missing" if boundary == "missing-run" else "run")
            elif boundary == "run":
                link, target = linked_run, cleanup_run
                cleanup_run = link
                tmp_root = parent
            else:
                link, target = cleanup_run / "linked-child", sibling
            create = subprocess.run(
                [POWERSHELL, "-NoProfile", "-Command",
                 f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' -ErrorAction Stop | Out-Null"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            assert create.returncode == 0, create.stdout + create.stderr
        elif boundary == "root-itself":
            cleanup_run = tmp_root
        elif boundary == "outside":
            cleanup_run = run
        prelude = (
            'function Remove-Item { [CmdletBinding()] param([string]$LiteralPath, [switch]$Force); '
            'Write-Error "fixture deletion denied" }; '
            if boundary == "remove-error" else ""
        )
        script = (
            f". '{helper}'; $ErrorActionPreference = 'Continue'; {prelude}"
            f"try {{ Write-ValidationArtifactFailure -RunRoot '{cleanup_run}' -TmpRoot '{tmp_root}'; exit 7 }} "
            "catch { exit 0 }"
        )
        try:
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert sentinel.read_text(encoding="utf-8") == "another run"
            assert not list(parent.rglob("error-summary.md"))
            assert (sandbox / ".tmp_tests" / "run" / "keep.txt").read_text(encoding="utf-8") == "current run"
        finally:
            if link is not None:
                link.rmdir()
        return
    script = (
        f". '{helper}'; "
        f"try {{ Test-ValidationShareablePair -Report '{report}' -Summary '{summary}'; exit 3 }} "
        f"catch {{ Write-ValidationArtifactFailure -RunRoot '{run}' -TmpRoot '{tmp_root}' }}; "
        "exit 0"
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text(encoding="utf-8") == "another run"
    assert [file.relative_to(run).as_posix() for file in run.rglob("*") if file.is_file()] == [
        "private/error-summary.md"
    ]
    failure_text = (run / "private" / "error-summary.md").read_text(encoding="utf-8")
    assert "failed" in failure_text
    assert "{invalid" not in failure_text


@pytest.mark.parametrize("fault", ["json", "status-only", "missing-commands", "missing-assertions"])
@pytest.mark.windows_powershell
def test_preflight_report_generation_failure_is_fail_closed(fault) -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    output = ROOT / ".tmp_tests" / "pytest_preflight_report_failure" / uuid4().hex
    sibling = output / "sibling-run"
    sibling.mkdir(parents=True)
    sentinel = sibling / "keep.txt"
    sentinel.write_text("another run", encoding="utf-8")
    command = rf'''
function global:ConvertTo-Json {{
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline=$true)]$InputObject, [int]$Depth = 2, [switch]$Compress)
    process {{
        $json = Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $InputObject -Depth $Depth -Compress:$Compress
        if ($json -match '"kind"\s*:\s*"powers-tool-cli-preflight"') {{
            [Console]::Out.WriteLine("fixture-report-status:" + $InputObject.status)
            switch ("{fault}") {{
                "json" {{ return "{{invalid fixture-private-data" }}
                "status-only" {{ return '{{"status":"passed"}}' }}
                "missing-commands" {{ $InputObject.Remove("commands") }}
                "missing-assertions" {{ $InputObject.commands[0].PSObject.Properties.Remove("assertions") }}
            }}
            return Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $InputObject -Depth $Depth
        }}
        return $json
    }}
}}
& .\scripts\preflight-cli.ps1 -Target keysight-e36312a -Suite smoke -OutputRoot "{output}"
'''
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "fixture-report-status:passed" in result.stdout
    assert sentinel.read_text(encoding="utf-8") == "another run"
    run, = output.glob("run_*")
    assert {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()} == {
        "private/error-summary.md"
    }
    text = (run / "private/error-summary.md").read_text(encoding="utf-8")
    assert "failed" in text
    assert "fixture-private-data" not in text
    assert str(output) not in text
