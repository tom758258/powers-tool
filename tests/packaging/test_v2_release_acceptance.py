from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v2-release-acceptance.ps1"


def test_v2_acceptance_script_uses_isolated_locked_workflows() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for required in (
        '"worktree", "add"',
        '"worktree", "remove"',
        "--locked",
        "--all-extras",
        "--no-emit-project",
        "Python310",
        "CurrentPython",
        "IncludeWorkingTreeChanges",
        "powers-tool-webui-launcher",
        "inspect_distribution.py",
        "inspect_pyinstaller.py",
        "hardware_touched = $false",
        "support_metadata_changed = $false",
        "evidence_changed = $false",
        "repository_renamed = $false",
        'acceptance_worktree_state = "detached"',
        "candidate_patch_sha256",
        "candidate_file_hashes",
        "failure_message",
    ):
        assert required in text

    build_text = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in ("build_cli_exe.ps1", "build_webui_exe.ps1", "build_release.ps1")
    )
    assert "DistPath must stay under the repository" in build_text
    assert "ReleaseRoot must stay under the repository" in build_text
    assert "--reinstall-package" in text
    assert "--basetemp" in text
    assert "PYTHONNOUSERSITE" in text
    assert "apply-working-tree-diff" in text
    assert "ls-files --others --exclude-standard" in text
    assert "outside the P7 allowlist" in text
    assert text.index('"focused release acceptance tests"') < text.index(
        '"complete no-hardware suites"'
    )


def test_v2_acceptance_candidate_overlay_has_an_exact_write_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    allowed_block = text.split("$allowedCandidatePaths = @(", 1)[1].split(")", 1)[0]
    expected = {
        ".github/workflows/tests.yml",
        "README.md",
        "pyproject.toml",
        "scripts/v2-release-acceptance.ps1",
        "tests/packaging/inspect_distribution.py",
        "tests/packaging/inspect_pyinstaller.py",
        "tests/packaging/test_packaging_identity.py",
        "tests/packaging/test_v2_release_acceptance.py",
        "uv.lock",
    }
    actual = {
        line.strip().strip('",')
        for line in allowed_block.splitlines()
        if line.strip().startswith('"')
    }
    assert actual == expected
    assert not any(path.startswith(("Local/", "docs/")) for path in actual)


def test_v2_acceptance_script_is_no_hardware_and_keeps_localized_docs_out_of_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "list-resources --live-only",
        "live-cli-check.ps1",
        "*IDN?",
        "pyvisa_py",
        "VISA discovery",
    ):
        assert forbidden not in text
    for protected in (
        "Local/",
        "README.zh-TW.md",
        "generated localized",
        "hardware_touched = $false",
    ):
        assert protected in text


def test_pyinstaller_inspector_requires_release_metadata_and_webui_assets() -> None:
    text = (ROOT / "tests" / "packaging" / "inspect_pyinstaller.py").read_text(
        encoding="utf-8"
    )
    assert "Name: powers-tool" in text
    assert "Version: 2.0.0" in text
    assert '"index.html", "styles.css", "app.js"' in text
    assert "keysight_power_" in text
    assert "open_embedded_archive" in text
    assert "names[powers_metadata]" in text
