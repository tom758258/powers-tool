# Keysight Power Monorepo Workspace

This root directory is a workspace-only container. It is not an importable
Python package itself. The root `pyproject.toml` declares a non-package `uv`
workspace (`tool.uv.package = false`) and the shared development dependency
group. The root `uv.lock` is the single workspace lockfile and should be
committed whenever dependency resolution changes.

## Workspace Workflow

Use the root directory for dependency sync and tests:

```powershell
uv sync --locked --all-packages --dev
uv run python -m pytest packages -q -p no:cacheprovider
uv build --all-packages
uv run keysight-power doctor --simulate --json
```

Use the [release checklist](release-checklist.md) before creating release
commits or package tags.

Before adding or changing tests, use the
[testing guidelines](testing-guidelines.md) to decide whether the assertion
protects a durable contract or freezes an implementation detail.

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so the no-hardware test gates do not require access to the system temporary
directory. Pass `--basetemp PATH` to override it for a specific run.

The tested Python range is 3.10 through 3.12. Package metadata constrains
`requires-python` to `>=3.10,<3.13` until CI validates newer versions.

Use `keysight-power ...` as the primary CLI entry point after syncing the
workspace. `uv run python -m keysight_power_cli.cli ...` is retained only as a
fallback for diagnosing console-script installation issues.

Sequence YAML files are supported by the `keysight-power-core` runtime
dependency on PyYAML. The simple fallback parser remains in core for low
dependency environments, but package installs should resolve PyYAML.

## Packages

The CLI and WebUI are parallel product interfaces. Both adapters build
parser-neutral Core requests and must keep SCPI, cancellation, and cleanup
behavior in `packages/core`.

The project is structured into independent packages located inside the `packages/` directory:

1. **`packages/core` (keysight-power-core)**
   - **Responsibility**: Houses the core driver, safety validation, models, transport, VISA connection helpers, and the simulator/testing helpers.
   - **Imports**: `keysight_power_core.*`
   - **Rules**: Must NOT import from `keysight-power-cli` or `keysight-power-webui`.

2. **`packages/cli` (keysight-power-cli)**
   - **Responsibility**: Implements the command-line interface commands (`keysight-power`), CLI argument parsing, and JSON contract validation.
   - **Imports**: `keysight_power_cli.*`
   - **Dependencies**: Depends on `keysight-power-core`.

3. **`packages/webui` (keysight-power-webui)**
   - **Responsibility**: FastAPI job/SSE adapter and static dashboard frontend for shared core command execution.
   - **Imports**: `keysight_power_webui.*`
   - **Dependencies**: Depends on `keysight-power-core`.
   - **Rules**: Must NOT import `keysight_power_cli`; must not contain direct VISA/SCPI command logic.
   - **Status**: Active static WebUI package using shared core runners.
