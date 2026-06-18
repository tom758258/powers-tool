# Keysight Powers Workspace

This repository builds one Python distribution, `keysight-powers`, from the
root `pyproject.toml`. The distribution contains three independent import
packages under `src/`: `keysight_power_core`, `keysight_power_cli`, and
`keysight_power_webui`.

## Workspace Workflow

Use the root directory for dependency sync, tests, and builds:

```powershell
uv sync --all-extras
uv run python -m pytest tests -q -p no:cacheprovider
python -m build
uv run keysight-power doctor --simulate --json
```

Use the [release checklist](release-checklist.md) before creating release
commits or package tags.

Before adding or changing tests, use the
[testing guidelines](testing-guidelines.md) to decide whether the assertion
protects a durable contract or freezes an implementation detail.

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so the no-hardware test gates do not require access to the system temporary
directory. Run pytest from the repository root. If a specific run needs a
separate basetemp, use `--basetemp .tmp_tests/<purpose>`. Do not write pytest
temporary data or generated test artifacts under `Local/`.

The tested Python range is 3.10 through 3.12. Package metadata constrains
`requires-python` to `>=3.10,<3.13` until CI validates newer versions.

Use `keysight-power ...` as the primary CLI entry point after syncing the
project. `uv run python -m keysight_power_cli.cli ...` is retained only as a
fallback for diagnosing console-script installation issues.

Sequence YAML files are supported by the `keysight-powers` runtime dependency
on PyYAML. The simple fallback parser remains in core for low dependency
environments, but package installs should resolve PyYAML.

## Import Packages

The CLI and WebUI are parallel product interfaces. Both adapters build
parser-neutral Core requests and must keep SCPI, cancellation, and cleanup
behavior in `src/keysight_power_core`.

1. **Core (`keysight_power_core`)**
   - Responsibility: driver, safety validation, models, transport, VISA helpers, simulator, and shared runtime.
   - Rules: must not import from `keysight_power_cli` or `keysight_power_webui`.

2. **CLI (`keysight_power_cli`)**
   - Responsibility: command-line interface, JSON envelope handling, and local Power Worker.
   - Dependencies: may import `keysight_power_core`; must not import `keysight_power_webui`.

3. **WebUI (`keysight_power_webui`)**
   - Responsibility: FastAPI job/SSE adapter and static dashboard frontend for shared core command execution.
   - Dependencies: may import `keysight_power_core`; must not import `keysight_power_cli`; must not contain direct VISA/SCPI command logic.

All three import paths are public and must remain stable.
