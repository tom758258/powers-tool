# Keysight Power Monorepo

Safe Python tooling for Keysight DC power supplies.

This workspace contains three separately installable packages:

- `packages/core`: `keysight-power-core` `1.0.0`, imported as
  `keysight_power_core`
- `packages/cli`: `keysight-power-cli` `1.0.0`, imported as
  `keysight_power_cli`, console command `keysight-power`
- `packages/webui`: `keysight-power-webui` `0.1.0`, imported as
  `keysight_power_webui`

The root `pyproject.toml` is workspace tooling only. Package metadata lives in
each package directory.

## Install

```powershell
uv sync --all-packages --dev
```

For editable package installs without syncing the whole workspace:

```powershell
uv pip install -e packages/core -e packages/cli -e packages/webui --link-mode=copy
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest packages\core\tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest packages\cli\tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest packages\webui\tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest packages -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Pass `--basetemp PATH` to override it for a specific run.

### Scripted Validation

Run validation scripts from the repository root in PowerShell.

| Script | Hardware use | Purpose | Report location |
| --- | --- | --- | --- |
| `scripts\no-hardware-regression.ps1` | none | Focused CLI checks, JSON/docs contract checks, and the full default pytest suite | `.tmp_tests\no_hardware_regression\` |
| `scripts\preflight-smoke-validation.ps1` | none | Dry-run/simulator smoke validation for E36312A or EDU36311A | `.tmp_tests\smoke_validation_preflight\<Target>\` |
| `scripts\live-smoke-validation-check.ps1` | yes | Explicit live smoke validation after automatically running preflight | `.tmp_tests\smoke_validation_live\<timestamp>_<Target>_<Connection>\` |
| `scripts\batch-validation.ps1` | optional | Run selected E36312A output and EDU36311A read-only checks in one report | `.tmp_tests\batch_validation\<timestamp>\` |

Recommended no-hardware validation:

```powershell
.\scripts\no-hardware-regression.ps1
.\scripts\preflight-smoke-validation.ps1 -Target E36312A
.\scripts\preflight-smoke-validation.ps1 -Target EDU36311A
```

If the current Windows execution policy blocks `.ps1` files, run a script with
a process-local bypass instead of changing the machine policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\no-hardware-regression.ps1
```

Live hardware validation is opt-in and requires an explicit VISA resource.
E36312A live smoke briefly enables channel 1 at 1 V / 0.05 A. EDU36311A
defaults to a read-only live profile:

```powershell
.\scripts\live-smoke-validation-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE
.\scripts\live-smoke-validation-check.ps1 -Target EDU36311A -Connection USB -Resource $env:EDU36311A_USB_RESOURCE
```

See the [CLI README scripted validation section](packages/cli/README.md#scripted-validation)
for batch examples, hardware pytest commands, parameters, and safety details.

Build all packages:

```powershell
uv build --all-packages
```

## Docs

- Core: [README](packages/core/README.md)
- CLI: [README](packages/cli/README.md), [CLI JSON contract](docs/contracts/power-cli-jsonl-contract.md),
  [worker contract](docs/contracts/power-worker-contract.md), [orchestrator guide](docs/contracts/power-orchestrator-workflows.md)
- WebUI: [README](packages/webui/README.md)
- Workspace: [workspace overview](docs/workspace.md), [release checklist](docs/release-checklist.md),
  [supported models](packages/core/docs/supported-models.md)
- Testing guidelines: [testing-guidelines.md](docs/testing-guidelines.md)

## Safety

Default tests must run without hardware. Any command or test that can affect a
real instrument output must remain explicit and opt-in. Real VISA resources must
not be hard-coded in committed files.

See `Agent.md`, `docs/workspace.md`, and the relevant package README before
making implementation changes.
