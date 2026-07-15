from __future__ import annotations

import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from typing import Callable
from uuid import uuid4
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-acceptance.ps1"
PACKAGING_DIR = ROOT / "tests" / "packaging"

if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

inspect_pyinstaller = importlib.import_module("inspect_pyinstaller")
inspector_utils = importlib.import_module("_inspector_utils")


def _write_distribution_fixture(
    dist_dir: Path,
    *,
    artifact_version: str,
    metadata_version: str | None = None,
    sdist_root_version: str | None = None,
    include_sdist: bool = True,
) -> None:
    dist_dir.mkdir(parents=True, exist_ok=True)
    metadata_version = metadata_version or artifact_version
    dist_info = f"powers_tool-{artifact_version}.dist-info"
    wheel = dist_dir / f"powers_tool-{artifact_version}-py3-none-any.whl"
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: powers-tool\n"
        f"Version: {metadata_version}\n"
        "Requires-Python: >=3.10\n"
    )
    entry_points = (
        "[console_scripts]\n"
        "powers-tool = powers_tool_cli.cli:main\n"
        "powers-tool-webui = powers_tool_webui.server:main\n"
        "powers-tool-webui-launcher = powers_tool_webui.launcher:main\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/entry_points.txt", entry_points)
        for package in ("powers_tool_core", "powers_tool_cli", "powers_tool_webui"):
            archive.writestr(f"{package}/__init__.py", "")
        archive.writestr(
            "powers_tool_core/build_profile.py",
            "PRODUCT_BUILD_IDENTITY = ProductBuildIdentity(profile=BuildProfile.PRODUCT)\n",
        )
        for filename in ("index.html", "styles.css", "app.js"):
            archive.writestr(f"powers_tool_webui/static/{filename}", filename)

    if not include_sdist:
        return
    root = f"powers_tool-{sdist_root_version or artifact_version}"
    with tarfile.open(dist_dir / f"powers_tool-{artifact_version}.tar.gz", "w:gz") as archive:
        for package in ("powers_tool_core", "powers_tool_cli", "powers_tool_webui"):
            _add_tar_text(archive, f"{root}/src/{package}/__init__.py", "")
        _add_tar_text(
            archive,
            f"{root}/src/powers_tool_core/build_profile.py",
            "PRODUCT_BUILD_IDENTITY = ProductBuildIdentity(profile=BuildProfile.PRODUCT)\n",
        )
        for filename in ("index.html", "styles.css", "app.js"):
            _add_tar_text(
                archive,
                f"{root}/src/powers_tool_webui/static/{filename}",
                filename,
            )


def _add_tar_text(archive: tarfile.TarFile, name: str, text: str) -> None:
    payload = text.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _run_distribution_inspector(
    dist_dir: Path, *arguments: str, inspector: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            str(inspector or PACKAGING_DIR / "inspect_distribution.py"),
            *arguments,
            str(dist_dir),
        ],
        cwd=ROOT,
        check=False,
    )


class _FakePyz:
    def __init__(self, names: set[str]) -> None:
        self.toc = names


class _FakeCArchive:
    def __init__(
        self,
        *,
        version: str,
        extra_metadata_versions: tuple[str, ...] = (),
        pyz_names: set[str] | None = None,
        webui_assets: bool = True,
    ) -> None:
        self.metadata = {
            f"powers_tool-{item}.dist-info/METADATA": (
                f"Name: powers-tool\nVersion: {item}\n".encode("utf-8")
            )
            for item in (version, *extra_metadata_versions)
        }
        names = [*self.metadata, "PYZ.pyz"]
        if webui_assets:
            names.extend(
                f"powers_tool_webui/static/{filename}"
                for filename in ("index.html", "styles.css", "app.js")
            )
        self.toc = {name: None for name in names}
        self.pyz_names = pyz_names or {
            "powers_tool_core",
            "powers_tool_core.driver",
            "powers_tool_cli",
            "powers_tool_cli.cli",
            "powers_tool_webui",
            "powers_tool_webui.server",
        }

    def extract(self, name: str) -> bytes:
        return self.metadata[name]

    def open_embedded_archive(self, name: str) -> _FakePyz:
        assert name == "PYZ.pyz"
        return _FakePyz(self.pyz_names)


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip(
            "Windows PowerShell is required for acceptance-script behavior tests"
        )
    return executable


def _find_uv_python(version: str, cache: Path) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for acceptance-script behavior tests")
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(cache)
    result = subprocess.run(
        [uv, "python", "find", version],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        pytest.skip(f"Python {version} is not installed for the behavior test")
    path = Path(result.stdout.strip().splitlines()[-1]).resolve()
    if not path.is_file():
        pytest.skip(f"uv returned no usable Python {version} interpreter")
    return path


@pytest.fixture
def find_python(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    _powershell()
    cache = tmp_path_factory.mktemp("release_uv_cache")
    return lambda version: _find_uv_python(version, cache)


def _make_distinct_interpreter(
    base_python: Path, request: pytest.FixtureRequest
) -> Path:
    environment = ROOT / ".tmp_tests" / "release_preflight_python" / uuid4().hex
    request.addfinalizer(lambda: shutil.rmtree(environment, ignore_errors=True))
    clean_env = os.environ.copy()
    for name in ("PYTHONHOME", "UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV", "PYTHONPATH"):
        clean_env.pop(name, None)
    _run(
        [str(base_python), "-m", "venv", "--without-pip", str(environment)],
        cwd=ROOT,
        env=clean_env,
    )
    return environment / "Scripts" / "python.exe"


def _make_preflight_repository(request: pytest.FixtureRequest) -> Path:
    fixture_id = uuid4().hex
    repository = ROOT / ".tmp_tests" / "release_preflight_repo" / fixture_id
    git_directory = ROOT / ".tmp_tests" / "release_preflight_git" / fixture_id
    repository.mkdir(parents=True)
    git_directory.parent.mkdir(parents=True, exist_ok=True)
    request.addfinalizer(lambda: shutil.rmtree(repository, ignore_errors=True))
    request.addfinalizer(lambda: shutil.rmtree(git_directory, ignore_errors=True))
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "powers-tool"\nversion = "3.4.5"\n',
        encoding="utf-8",
    )
    (repository / "README.md").write_text("preflight fixture\n", encoding="utf-8")
    _run(
        [
            "git",
            "-c",
            "core.longpaths=true",
            "init",
            f"--separate-git-dir={git_directory}",
            "-b",
            "main",
        ],
        cwd=repository,
    )
    _run(["git", "config", "core.longpaths", "true"], cwd=repository)
    _run(["git", "config", "user.email", "release-tests@example.invalid"], cwd=repository)
    _run(["git", "config", "user.name", "Release Tests"], cwd=repository)
    _run(["git", "add", "."], cwd=repository)
    _run(["git", "commit", "-m", "preflight fixture"], cwd=repository)
    return repository


def _run_preflight(
    repository: Path,
    *,
    python310: Path,
    current_python: Path,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    command = [
        _powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repository / "scripts" / SCRIPT.name),
        "-InterpreterPreflightOnly",
        "-Python310",
        str(python310),
        "-CurrentPython",
        str(current_python),
        "-OutputRoot",
        ".tmp_tests\\preflight",
    ]
    result = _run(command, cwd=repository, check=False)
    reports = list((repository / ".tmp_tests" / "preflight").glob("r_*/report.json"))
    assert len(reports) == 1, result.stdout + result.stderr
    return result, json.loads(reports[0].read_text(encoding="utf-8"))


def test_preflight_rejects_non_310_python310(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    current_python = find_python("3.13")
    wrong_python310 = _make_distinct_interpreter(current_python, request)
    result, report = _run_preflight(
        repository,
        python310=wrong_python310,
        current_python=current_python,
    )

    assert result.returncode == 1
    assert report["ok"] is False
    assert report["failed_step"] == "interpreter preflight"
    assert str(wrong_python310) in report["failure_message"]
    assert "expected Python 3.10" in report["failure_message"]
    assert "actual Python 3.13" in report["failure_message"]


def test_preflight_rejects_non_313_current_python(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    python310 = find_python("3.10")
    wrong_current = _make_distinct_interpreter(python310, request)
    result, report = _run_preflight(
        repository,
        python310=python310,
        current_python=wrong_current,
    )

    assert result.returncode == 1
    assert report["ok"] is False
    assert str(wrong_current) in report["failure_message"]
    assert "expected Python 3.13" in report["failure_message"]
    assert "actual Python 3.10" in report["failure_message"]


def test_preflight_rejects_the_same_interpreter_for_both_roles(
    request: pytest.FixtureRequest,
) -> None:
    repository = _make_preflight_repository(request)
    interpreter = Path(sys.executable).resolve()
    result, report = _run_preflight(
        repository,
        python310=interpreter,
        current_python=interpreter,
    )

    assert result.returncode == 1
    assert report["ok"] is False
    assert report["interpreters_distinct"] is False
    assert "must be distinct files" in report["failure_message"]


def test_preflight_report_records_exact_interpreter_and_committed_provenance(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    python310 = find_python("3.10")
    current_python = find_python("3.13")
    expected_commit = _run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
    result, report = _run_preflight(
        repository,
        python310=python310,
        current_python=current_python,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["schema_version"] == 1
    assert report["kind"] == "powers-tool-release-acceptance"
    assert report["ok"] is True
    assert report["acceptance_mode"] == "interpreter-preflight"
    assert report["full_acceptance_completed"] is False
    assert report["source_commit"] == expected_commit
    assert report["distribution_name"] == "powers-tool"
    assert report["project_version"] == "3.4.5"
    assert Path(report["python_310"]["requested_interpreter"]) == python310
    assert report["python_310"]["expected_version"] == "3.10"
    assert report["python_310"]["actual_version"].startswith("3.10.")
    assert report["python_310"]["actual_major"] == 3
    assert report["python_310"]["actual_minor"] == 10
    assert (
        Path(report["python_310"]["resolved_interpreter"])
        == python310
    )
    assert Path(report["current_python"]["requested_interpreter"]) == current_python
    assert report["current_python"]["expected_version"] == "3.13"
    assert report["current_python"]["actual_version"].startswith("3.13.")
    assert report["current_python"]["actual_major"] == 3
    assert report["current_python"]["actual_minor"] == 13
    assert (
        Path(report["current_python"]["resolved_interpreter"])
        == current_python
    )
    assert report["interpreters_distinct"] is True
    assert report["acceptance_worktree_state"] == "not-created"
    assert report["hardware_touched"] is False
    assert report["support_metadata_changed"] is False
    assert report["evidence_changed"] is False
    assert report["repository_renamed"] is False
    assert "working_tree_overlay_applied" not in report
    assert "candidate_paths" not in report


def test_dirty_repository_fails_before_creating_acceptance_output(
    request: pytest.FixtureRequest,
    find_python: Callable[[str], Path],
) -> None:
    repository = _make_preflight_repository(request)
    python310 = find_python("3.10")
    current_python = find_python("3.13")
    (repository / "README.md").write_text("dirty change\n", encoding="utf-8")
    output_root = repository / ".tmp_tests" / "preflight"
    result = _run(
        [
            _powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(repository / "scripts" / SCRIPT.name), "-InterpreterPreflightOnly",
            "-Python310", str(python310), "-CurrentPython", str(current_python),
            "-OutputRoot", ".tmp_tests\\preflight",
        ],
        cwd=repository,
        check=False,
    )

    assert result.returncode == 1
    assert "requires a clean source worktree" in " ".join(
        (result.stdout + result.stderr).split()
    )
    assert not output_root.exists()


def test_release_acceptance_has_no_working_tree_overlay_mode() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for removed in (
        "IncludeWorkingTreeChanges",
        "allowedCandidatePaths",
        "candidate_patch_sha256",
        "working_tree_overlay_applied",
        "apply-working-tree-diff",
    ):
        assert removed not in text


def test_release_acceptance_passes_project_version_to_every_inspector() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    invocations = re.findall(
        r'-Arguments @\("tests\\packaging\\(inspect_(?:distribution|pyinstaller)\.py)"([^\n]*)\)',
        text,
    )
    assert {name for name, _ in invocations} == {
        "inspect_distribution.py",
        "inspect_pyinstaller.py",
    }
    for name, arguments in invocations:
        assert '"--expected-version", $projectVersion' in arguments, name


def test_distribution_inspector_accepts_matching_explicit_future_version(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="3.4.5")

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_distribution_inspector_rejects_mismatching_metadata(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(
        dist_dir, artifact_version="3.4.5", metadata_version="2.0.0"
    )

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected wheel metadata version '3.4.5'" in result.stderr
    assert "Version: 2.0.0" in result.stderr


def test_distribution_inspector_rejects_mismatching_artifact_filenames(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="2.0.0")

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected wheel filename 'powers_tool-3.4.5-py3-none-any.whl'" in result.stderr
    assert "powers_tool-2.0.0-py3-none-any.whl" in result.stderr


def test_distribution_inspector_rejects_mismatching_sdist_filename(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="3.4.5")
    (dist_dir / "powers_tool-3.4.5.tar.gz").rename(
        dist_dir / "powers_tool-2.0.0.tar.gz"
    )

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected sdist filename 'powers_tool-3.4.5.tar.gz'" in result.stderr
    assert "powers_tool-2.0.0.tar.gz" in result.stderr


def test_distribution_inspector_rejects_mismatching_sdist_root(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(
        dist_dir, artifact_version="3.4.5", sdist_root_version="2.0.0"
    )

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected sdist root 'powers_tool-3.4.5'" in result.stderr
    assert "powers_tool-2.0.0" in result.stderr


def test_distribution_inspector_wheel_only_accepts_explicit_version(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(
        dist_dir, artifact_version="3.4.5", include_sdist=False
    )

    result = _run_distribution_inspector(
        dist_dir, "--wheel-only", "--expected-version", "3.4.5"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_inspectors_resolve_future_version_from_fixture_pyproject(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    packaging = repository / "tests" / "packaging"
    packaging.mkdir(parents=True)
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "powers-tool"\nversion = "3.4.5"\n', encoding="utf-8"
    )
    for name in ("_inspector_utils.py", "inspect_distribution.py"):
        shutil.copy2(PACKAGING_DIR / name, packaging / name)
    dist_dir = repository / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="3.4.5")

    result = _run_distribution_inspector(
        dist_dir, inspector=packaging / "inspect_distribution.py"
    )
    resolved = inspector_utils.resolve_expected_version(
        None, inspector_file=packaging / "inspect_pyinstaller.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert resolved == "3.4.5"
    archive = _FakeCArchive(version=resolved)
    inspect_pyinstaller._validate_metadata(
        archive,
        {name: name for name in archive.toc},
        expected_version=resolved,
    )


def test_pyinstaller_inspector_accepts_matching_future_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _FakeCArchive(version="3.4.5")
    monkeypatch.setattr(inspect_pyinstaller, "CArchiveReader", lambda path: archive)

    inspect_pyinstaller.inspect_executable(
        Path("future.exe"),
        ("powers_tool_core", "powers_tool_webui"),
        webui=True,
        expected_version="3.4.5",
    )


def test_pyinstaller_cli_accepts_explicit_and_canonical_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_archive = _FakeCArchive(version="3.4.5")
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: future_archive
    )
    assert (
        inspect_pyinstaller.main(
            ["--expected-version", "3.4.5", "cli.exe", "webui.exe"]
        )
        == 0
    )

    canonical_version = inspector_utils.resolve_expected_version(
        None, inspector_file=PACKAGING_DIR / "inspect_pyinstaller.py"
    )
    canonical_archive = _FakeCArchive(version=canonical_version)
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: canonical_archive
    )
    assert inspect_pyinstaller.main(["cli.exe", "webui.exe"]) == 0


def test_pyinstaller_inspector_rejects_stale_metadata_version() -> None:
    archive = _FakeCArchive(version="2.0.0")

    with pytest.raises(AssertionError) as error:
        inspect_pyinstaller._validate_metadata(
            archive,
            {name: name for name in archive.toc},
            expected_version="3.4.5",
        )

    assert "powers_tool-3.4.5.dist-info/METADATA" in str(error.value)
    assert "powers_tool-2.0.0.dist-info/METADATA" in str(error.value)


def test_pyinstaller_inspector_rejects_competing_metadata_version() -> None:
    archive = _FakeCArchive(
        version="3.4.5", extra_metadata_versions=("2.0.0",)
    )

    with pytest.raises(AssertionError) as error:
        inspect_pyinstaller._validate_metadata(
            archive,
            {name: name for name in archive.toc},
            expected_version="3.4.5",
        )

    assert "powers_tool-3.4.5.dist-info/METADATA" in str(error.value)
    assert "powers_tool-2.0.0.dist-info/METADATA" in str(error.value)


def test_pyinstaller_inspector_retains_package_webui_and_legacy_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_package = _FakeCArchive(
        version="3.4.5", pyz_names={"powers_tool_core", "powers_tool_core.driver"}
    )
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: missing_package
    )
    with pytest.raises(AssertionError, match="powers_tool_cli"):
        inspect_pyinstaller.inspect_executable(
            Path("missing-package.exe"),
            ("powers_tool_core", "powers_tool_cli"),
            webui=False,
            expected_version="3.4.5",
        )

    missing_assets = _FakeCArchive(version="3.4.5", webui_assets=False)
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: missing_assets
    )
    with pytest.raises(AssertionError, match="index.html"):
        inspect_pyinstaller.inspect_executable(
            Path("missing-assets.exe"),
            ("powers_tool_core", "powers_tool_webui"),
            webui=True,
            expected_version="3.4.5",
        )

    legacy = _FakeCArchive(
        version="3.4.5",
        pyz_names={
            "powers_tool_core",
            "powers_tool_core.driver",
            "keysight_power_core",
        },
    )
    monkeypatch.setattr(inspect_pyinstaller, "CArchiveReader", lambda path: legacy)
    with pytest.raises(AssertionError):
        inspect_pyinstaller.inspect_executable(
            Path("legacy.exe"),
            ("powers_tool_core",),
            webui=False,
            expected_version="3.4.5",
        )
