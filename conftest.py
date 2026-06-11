from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent
LOCAL_ROOT = REPO_ROOT / "Local"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    basetemp = config.getoption("basetemp")
    if not basetemp:
        return

    basetemp_path = Path(basetemp)
    if not basetemp_path.is_absolute():
        basetemp_path = Path(config.invocation_params.dir) / basetemp_path

    if _is_within(basetemp_path.resolve(), LOCAL_ROOT.resolve()):
        raise pytest.UsageError(
            "pytest basetemp must not be inside Local/. "
            "Use .tmp_pytest or .tmp_tests/<purpose> instead."
        )
