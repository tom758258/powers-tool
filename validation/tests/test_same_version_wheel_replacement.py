from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _run(
    *args: str | Path, cwd: Path = ROOT, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, check=check, capture_output=True, text=True, env=env
    )


def _wheel_record_is_valid(wheel: Path) -> bool:
    with zipfile.ZipFile(wheel) as archive:
        record_name = next(name for name in archive.namelist() if name.endswith(".dist-info/RECORD"))
        for name, digest, size in csv.reader(archive.read(record_name).decode("utf-8").splitlines()):
            if not digest:
                continue
            algorithm, encoded = digest.split("=", 1)
            data = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            if algorithm != "sha256" or actual != encoded or len(data) != int(size):
                return False
    return True


def _replacement_wheel(original: Path, destination: Path, package_prefix: str) -> Path:
    with zipfile.ZipFile(original) as source:
        files = {name: source.read(name) for name in source.namelist()}
    record_name = next(name for name in files if name.endswith(".dist-info/RECORD"))
    target = next(
        name for name in files if name.startswith(package_prefix + "/") and name.endswith(".py")
    )
    files[target] += b"\n# same-version replacement sentinel\n"
    rows = []
    for name in sorted(files):
        if name == record_name:
            continue
        data = files[name]
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        rows.append((name, f"sha256={digest}", str(len(data))))
    rows.append((record_name, "", ""))
    record = "".join(",".join(row) + "\n" for row in rows).encode("utf-8")
    destination.mkdir(parents=True, exist_ok=True)
    replacement = destination / original.name
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, record if name == record_name else data)
    assert _wheel_record_is_valid(replacement)
    return replacement


@pytest.fixture(scope="module")
def built_wheels(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path, Path]:
    root = tmp_path_factory.mktemp("same-version-wheels")
    product = root / "product"
    validation = root / "validation"
    _run(sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", product, ROOT)
    _run(
        sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", validation,
        ROOT / "validation",
    )
    requirements = root / "runtime-requirements.txt"
    wheelhouse = root / "wheelhouse"
    downloader = root / "downloader"
    _run(sys.executable, "-m", "venv", downloader)
    downloader_python = downloader / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    _run(
        "uv", "export", "--locked", "--no-dev", "--no-emit-workspace", "--format",
        "requirements.txt", "--output-file", requirements,
    )
    _run(
        downloader_python, "-m", "pip", "download", "--require-hashes", "--only-binary=:all:",
        "--dest", wheelhouse, "--requirement", requirements,
    )
    return next(product.glob("*.whl")), next(validation.glob("*.whl")), requirements, wheelhouse


def _record_hash(python: Path, distribution: str) -> str:
    code = (
        "from importlib import metadata; import hashlib; "
        f"d=metadata.distribution({distribution!r}); p=d.locate_file(d._path.name+'/RECORD'); "
        "print(hashlib.sha256(p.read_bytes()).hexdigest())"
    )
    return _run(python, "-c", code).stdout.strip()


def _prepare_identity(venv: Path, python: Path, product: Path, validation: Path) -> None:
    retained = venv / ".powers-tool-validation-artifacts"
    retained.mkdir()
    shutil.copy2(product, retained / product.name)
    shutil.copy2(validation, retained / validation.name)
    version = "2.0.0"
    payload = {
        "schema_version": 2,
        "product_distribution_name": "powers-tool",
        "product_version": version,
        "product_wheel_filename": product.name,
        "product_wheel_sha256": hashlib.sha256(product.read_bytes()).hexdigest(),
        "product_installed_record_sha256": _record_hash(python, "powers-tool"),
        "validation_distribution_name": "powers-tool-validation",
        "validation_version": version,
        "validation_wheel_filename": validation.name,
        "validation_wheel_sha256": hashlib.sha256(validation.read_bytes()).hexdigest(),
        "validation_installed_record_sha256": _record_hash(python, "powers-tool-validation"),
        "source_commit": _run("git", "rev-parse", "HEAD").stdout.strip(),
        "source_dirty": True,
        "build_time": "2026-01-01T00:00:00+00:00",
        "python_version": _run(python, "-c", "import platform; print(platform.python_version())").stdout.strip(),
    }
    key = b"same-version-replacement-test-key"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload["identity_hmac_sha256"] = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    (venv / ".powers-tool-validation-installation.key").write_bytes(key)
    (venv / ".powers-tool-validation-installation.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("replaced_distribution", "package_prefix"),
    [("product", "powers_tool_core"), ("validation", "powers_tool_validation")],
)
def test_same_version_replacement_is_rejected_by_installed_runtime_and_retained_wheel_closure(
    tmp_path: Path,
    built_wheels: tuple[Path, Path, Path, Path],
    replaced_distribution: str,
    package_prefix: str,
) -> None:
    product, validation, requirements, wheelhouse = built_wheels
    venv = tmp_path / "venv"
    _run(sys.executable, "-m", "venv", venv)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    _run(
        python, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse,
        "--requirement", requirements,
    )
    _run(python, "-m", "pip", "install", "--no-index", "--no-deps", product, validation)
    _prepare_identity(venv, python, product, validation)
    baseline = _run(python, "-m", "powers_tool_validation.cli", "_internal-build-info", "--json")
    assert json.loads(baseline.stdout)["retained_wheels_verified"] is True

    original = product if replaced_distribution == "product" else validation
    replacement = _replacement_wheel(original, tmp_path / "replacement", package_prefix)
    _run(python, "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", replacement)
    result = _run(
        python, "-m", "powers_tool_validation.cli", "_internal-build-info", "--json", check=False
    )
    assert result.returncode != 0
    assert "retained wheel" in result.stderr or "retained wheel RECORD" in result.stderr
