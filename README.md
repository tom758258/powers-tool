# Keysight Powers

Safe Python tooling for Keysight DC power supplies.

This repository builds one Python distribution, `keysight-powers` `1.0.0`,
while preserving three independent import packages:

- `keysight_power_core`: driver, safety, transport, simulator, and shared runtime.
- `keysight_power_cli`: `keysight-power` CLI and local Power Worker adapter.
- `keysight_power_webui`: `keysight-power-webui` FastAPI/static dashboard adapter.

The CLI and WebUI are parallel product interfaces over the shared Core runtime.
Neither adapter owns SCPI behavior.

## Install

Install the basic Core/CLI distribution:

```powershell
pip install .
```

Install WebUI runtime dependencies:

```powershell
pip install ".[webui]"
```

Install everything needed for local development and tests:

```powershell
pip install -e ".[all,dev]"
```

With `uv`, the equivalent development sync is:

```powershell
uv sync --all-extras
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Run pytest from the repository root. For an intentional per-run override, use
`--basetemp .tmp_tests/<purpose>`. Do not use `Local/` for pytest temporary
data or generated test artifacts.

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

See the [CLI README scripted validation section](docs/cli/README.md#scripted-validation)
for batch examples, hardware pytest commands, parameters, and safety details.

## Build

Build the single wheel and source distribution:

```powershell
python -m build
```

The expected artifacts are:

```text
dist/
  keysight_powers-1.0.0-py3-none-any.whl
  keysight_powers-1.0.0.tar.gz
```

Building Python packages does not create Windows executables. Any future EXE
packaging should stay in dedicated scripts separate from `python -m build`.

## Docs

- Core: [README](docs/core/README.md), [supported models](docs/core/supported-models.md)
- CLI: [README](docs/cli/README.md), [CLI JSON contract](docs/contracts/power-cli-jsonl-contract.md),
  [worker contract](docs/contracts/power-worker-contract.md), [orchestrator guide](docs/contracts/power-orchestrator-workflows.md)
- WebUI: [README](docs/webui/README.md)
- Workspace: [workspace overview](docs/workspace.md), [release checklist](docs/release-checklist.md)
- Testing guidelines: [testing-guidelines.md](docs/testing-guidelines.md)

## Safety

Default tests must run without hardware. Any command or test that can affect a
real instrument output must remain explicit and opt-in. Real VISA resources must
not be hard-coded in committed files.

See `AGENTS.md`, `docs/workspace.md`, and the relevant interface README before
making implementation changes.

## License and Disclaimer

This project is licensed under the MIT License. See [LICENSE](LICENSE).

This project is an independent, unofficial project and is not affiliated with,
endorsed by, or sponsored by Keysight Technologies.

Users are responsible for complying with all applicable Keysight software,
driver, instrument, and documentation license terms.
