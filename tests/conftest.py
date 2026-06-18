from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = REPO_ROOT / "Local"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--resource", action="store", default=None, help="VISA resource for hardware tests.")
    parser.addoption("--backend", action="store", default=None, help="Optional PyVISA backend.")
    parser.addoption("--expected-model", action="store", default=None, help="Expected instrument model.")
    parser.addoption(
        "--run-output",
        action="store_true",
        default=False,
        help="Enable output-affecting hardware tests.",
    )
    parser.addoption(
        "--run-protection",
        action="store_true",
        default=False,
        help="Enable protection-write hardware tests.",
    )
    parser.addoption(
        "--run-trigger",
        action="store_true",
        default=False,
        help="Enable trigger hardware tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    basetemp = config.getoption("basetemp")
    if basetemp:
        basetemp_path = Path(basetemp)
        if not basetemp_path.is_absolute():
            basetemp_path = Path(config.invocation_params.dir) / basetemp_path

        if _is_within(basetemp_path.resolve(), LOCAL_ROOT.resolve()):
            raise pytest.UsageError(
                "pytest basetemp must not be inside Local/. "
                "Use .tmp_pytest or .tmp_tests/<purpose> instead."
            )

    config.addinivalue_line("markers", "hardware: opt-in read-only hardware test")
    config.addinivalue_line("markers", "hardware_readonly: opt-in read-only hardware test")
    config.addinivalue_line("markers", "hardware_output: opt-in output-affecting hardware test")
    config.addinivalue_line("markers", "hardware_protection: opt-in protection hardware test")
    config.addinivalue_line("markers", "hardware_trigger: opt-in trigger hardware test")


@pytest.fixture
def hardware_resource(request: pytest.FixtureRequest) -> str:
    resource = request.config.getoption("--resource")
    if not resource:
        pytest.skip("hardware tests require --resource")
    return str(resource)


@pytest.fixture
def hardware_backend(request: pytest.FixtureRequest) -> str | None:
    backend = request.config.getoption("--backend")
    return str(backend) if backend else None


@pytest.fixture
def expected_model(request: pytest.FixtureRequest) -> str | None:
    model = request.config.getoption("--expected-model")
    return str(model) if model else None


@pytest.fixture
def run_output(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--run-output"))


@pytest.fixture
def run_protection(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--run-protection"))


@pytest.fixture
def run_trigger(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--run-trigger"))
