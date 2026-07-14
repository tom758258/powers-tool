from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _run(*arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_actual_product_wheel_and_sdist_exclude_validation_runtime(
    tmp_path: Path,
) -> None:
    out = tmp_path / "product"
    result = _run(
        sys.executable,
        "-m",
        "build",
        "--no-isolation",
        "--outdir",
        str(out),
        str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inspection = _run(
        sys.executable,
        str(ROOT / "tests" / "packaging" / "inspect_distribution.py"),
        "--expected-version",
        "2.0.0",
        str(out),
    )
    assert inspection.returncode == 0, inspection.stdout + inspection.stderr


def test_actual_validation_wheel_is_separate_and_contains_internal_runtime(
    tmp_path: Path,
) -> None:
    out = tmp_path / "validation"
    result = _run(
        sys.executable,
        "-m",
        "build",
        "--no-isolation",
        "--wheel",
        "--outdir",
        str(out),
        str(ROOT / "validation"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inspection = _run(
        sys.executable,
        str(
            ROOT
            / "validation"
            / "tests"
            / "inspect_validation_distribution.py"
        ),
        "--expected-version",
        "2.0.0",
        str(out),
    )
    assert inspection.returncode == 0, inspection.stdout + inspection.stderr
