[繁體中文](README.zh-TW.md)

# Keysight Powers

Keysight Powers is a Python control toolkit for Keysight DC power supplies.
It provides one installable distribution, `keysight-powers` `<version>`, while
preserving three import packages: `keysight_power_core`,
`keysight_power_cli`, and `keysight_power_webui`.

The project supports USB, LAN, and explicit RS-232/ASRL communication through VISA, command-line
operation, and a local browser WebUI. It is designed for power-supply workflows
where explicit safety checks, simulator support, and machine-readable output
matter.

## Features

- Control supported Keysight DC power supplies over USB, LAN, or explicit
  RS-232/ASRL settings using VISA
- Use either the `keysight-power` CLI or the local `keysight-power-webui`
  dashboard
- Preview hardware-affecting commands with dry-run mode before opening VISA
- Test workflows without hardware using the built-in simulator
- Set voltage/current limits, control output state, and read back live
  instrument data
- Run ramp, ramp-list, sequence, trigger, snapshot, restore, and protection
  workflows through the shared Core runtime
- Produce JSON and JSONL output for automation, agents, and orchestrators
- Keep real hardware output opt-in; default tests and simulator flows do not
  enable instrument output

## Model Profiles And Live Expected-Model Guards

Dry-run and simulator flows do not open real VISA hardware. For commands that
need model-specific planning, `--model` / `model_profile` is the no-hardware
model profile used for planning, channel validation, capability selection, and
SCPI preview unless the resource is a known deterministic SIM resource.

In live mode, `--model` / `model_profile` is an expected-model guard. The
connected instrument is still identified with `*IDN?`, and Core requires the
reported model to match the selected model before any setup or write SCPI. The
selected model never overrides the IDN-detected driver.
`GENERIC` is no-hardware only and is not accepted as a live expected model.
Unsupported model, command, and mode failures are intentional feature-lock
behavior; selecting a model is not a feature unlock.

Valid no-hardware examples:

```powershell
uv run keysight-power set --dry-run --model E3646A --channel 1 --voltage 1 --current 0.05
uv run keysight-power readback --simulate --resource USB0::SIM::E36312A::INSTR --channel all
uv run keysight-power trigger-step --dry-run --model E36312A --channel 1 --source bus --fire
```

Live guard example:

```powershell
uv run keysight-power set --model E36312A --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
```

This command requires the connected `*IDN?` model to be `E36312A`; it does not
force the E36312A driver if another model answers.

Current model boundaries are enforced across Core, CLI, and WebUI backend
direct jobs. Trigger/native LIST is E36312A-only. EDU36311A supports
read-only/output/protection workflows but not trigger/native LIST or
snapshot/restore. E3646A supports validated RS-232 read-only/output workflows
plus software `ramp-list` and step-limited software `sequence`; these are not
native LIST workflows, and E3646A protection, trigger/native LIST,
snapshot/restore, completion-pulse, and unsupported sequence steps remain
disabled.

This is intentionally rejected:

```powershell
uv run keysight-power trigger-step --dry-run --resource USB0::FAKE::E36312A::INSTR --channel 1 --source bus --fire
```

Fake or live-looking resource strings are placeholders and must not imply a
real instrument model. Deterministic SIM resources, such as
`USB0::SIM::E36312A::INSTR`, are allowed because they map to known simulator
IDN/model data.

## Project Structure

The repository has one distribution and one version number. In examples,
`<version>` means `[project].version` from the root `pyproject.toml`:

- Distribution: `keysight-powers` `<version>`
- Core import: `keysight_power_core`
- CLI import: `keysight_power_cli`
- WebUI import: `keysight_power_webui`

The import paths remain independent. Do not use a `keysight_power.*`
namespace package.

```text
src/
  keysight_power_core/
  keysight_power_cli/
  keysight_power_webui/
tests/
  core/
  cli/
  webui/
  integration/
docs/
  core/
  cli/
  webui/
scripts/
```

## Install

Open PowerShell and enter the project root first:

```powershell
cd path\to\Keysight_Powers_Controller
```

Install uv if it is not already available:

```powershell
py -m pip install --user uv
```

Verify uv:

```powershell
uv --version
```

Create the project virtual environment in the project folder:

```powershell
uv venv .venv
```

Sync the reproducible development and test environment from `uv.lock`:

```powershell
uv sync --all-extras --link-mode=copy
```

For CI or strict local checks, require the committed lock file to stay
unchanged:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

This project supports Python `>=3.10`. `uv venv .venv` uses an available
compatible Python. If you need a specific Python version, request it explicitly:

```powershell
uv venv .venv --python 3.12
```

The `uv.lock` file is used by uv for development and CI reproducibility.
`pip install .` reads `pyproject.toml`, not `uv.lock`. Users without uv must
install uv before using the locked environment.

If you need pip directly, use the virtual environment's Python:

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install ".[webui]"
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

Windows creates virtualenv console wrappers such as
`.\.venv\Scripts\keysight-power.exe` and
`.\.venv\Scripts\keysight-power-webui.exe`. The WebUI launcher wrapper is
`.\.venv\Scripts\keysight-power-webui-launcher.exe`.

## Build

Build the wheel and source distribution. This uses the `build` package from
the `dev` extra installed above:

```powershell
.\.venv\Scripts\python.exe -m build
```

This produces only one Python distribution:

```text
dist\keysight_powers-<version>-py3-none-any.whl
dist\keysight_powers-<version>.tar.gz
```

Standalone executables are separate PyInstaller workflows. Install PyInstaller
before building exe artifacts:

```powershell
uv pip install pyinstaller --python .\.venv\Scripts\python.exe
```

If your virtual environment uses pip directly:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

Build the standalone CLI and WebUI launcher executables:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_cli_exe.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_webui_exe.ps1
```

By default, these commands produce:

```text
dist\keysight-power.exe
dist\keysight-power-webui-launcher.exe
```

Check the built CLI executable without touching hardware:

```powershell
.\dist\keysight-power.exe --version
.\dist\keysight-power.exe doctor --simulate --json
```

Build a release folder with wheel, sdist, standalone executables, and checksums:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

This produces release artifacts named with the selected project version:

```text
release\<version>\keysight-power-<version>.exe
release\<version>\keysight-power-webui-launcher-<version>.exe
release\<version>\keysight_powers-<version>-py3-none-any.whl
release\<version>\keysight_powers-<version>.tar.gz
release\<version>\checksums.txt
```

## Test

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so no-hardware tests do not depend on access to the Windows system temporary
directory. Run pytest from the repository root. If a specific run needs a
separate basetemp, use `--basetemp .tmp_tests/<purpose>`. Do not write pytest
temporary data or generated test artifacts under `Local/`.

Run focused tests while iterating:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

Run the full no-hardware suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Scripted no-hardware and live validation workflows are documented in the
[CLI README](docs/cli/README.md).

## Documentation

- [Core README](docs/core/README.md)
- [Supported Models](docs/core/supported-models.md)
- [CLI User Guide](docs/cli/USER_GUIDE.md)
- [CLI README](docs/cli/README.md)
- [WebUI README](docs/webui/README.md)
- [WebUI User Guide](docs/webui/USER_GUIDE.md)
- [Web UI Change Rules](docs/webui/web-ui-change-rules.md)
- [Repository Layout](docs/architecture/monorepo-layout.md)
- [Testing Guidelines](docs/testing-guidelines.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)

## License and Disclaimer

This project is licensed under the MIT License. See [LICENSE](LICENSE).

This project is independent and unofficial. It is not affiliated with,
endorsed by, or sponsored by Keysight Technologies.

Users are responsible for complying with all applicable Keysight software,
driver, instrument, and documentation license terms.
