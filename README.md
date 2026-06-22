[繁體中文](README.zh-TW.md)

# Keysight Powers

Keysight Powers is a Python control toolkit for Keysight DC power supplies.
It provides one installable distribution, `keysight-powers` `1.0.0`, while
preserving three import packages: `keysight_power_core`,
`keysight_power_cli`, and `keysight_power_webui`.

The project supports USB and LAN communication through VISA, command-line
operation, and a local browser WebUI. It is designed for power-supply workflows
where explicit safety checks, simulator support, and machine-readable output
matter.

## Features

- Control supported Keysight DC power supplies over USB or LAN using VISA
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

## Project Structure

The repository has one distribution and one version number:

- Distribution: `keysight-powers` `1.0.0`
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
`.\.venv\Scripts\keysight-power-webui.exe`.

## Run

List only VISA resources that currently answer `*IDN?`:

```powershell
.\.venv\Scripts\keysight-power.exe list-resources --live-only
```

Plain `list-resources` is passive VISA discovery and can show stale cached
resources. Use `--live-only` for normal live operation and `--verify` when
diagnosing stale entries.

Run a simulator-only health check:

```powershell
.\.venv\Scripts\keysight-power.exe doctor --simulate --json
```

Start the WebUI:

```powershell
.\.venv\Scripts\keysight-power-webui.exe --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

## Build

Build the wheel and source distribution. This uses the `build` package from
the `dev` extra installed above:

```powershell
.\.venv\Scripts\python.exe -m build
```

This produces only one Python distribution:

```text
dist\keysight_powers-1.0.0-py3-none-any.whl
dist\keysight_powers-1.0.0.tar.gz
```

Python package builds do not create Windows executables. Any future executable
packaging should stay in dedicated scripts separate from `python -m build`.

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

Hardware validation is explicit and opt-in. See the CLI README for live smoke
checks, hardware pytest commands, and safety details.

## Release Validation

Before creating release commits or package tags, run the no-hardware and
package gates from the repository root:

```powershell
uv sync --all-extras --locked --link-mode=copy
.\.venv\Scripts\python.exe -m pytest tests\core\test_import.py -q -p no:cacheprovider
uv run keysight-power doctor --simulate --json
.\scripts\no-hardware-regression.ps1
.\.venv\Scripts\python.exe -m build
git status --short
```

The final `git status --short` should show only intentional release,
documentation, and lockfile changes before committing.

This release does not add PyInstaller, Nuitka, or other packager dependencies.
Future EXE packaging should keep the package entry points aligned with the
current console scripts:

```text
keysight_power_cli.cli:main
keysight_power_webui.server:main
```

## Documentation

- [Core README](docs/core/README.md)
- [CLI User Guide](docs/cli/USER_GUIDE.md)
- [CLI README](docs/cli/README.md)
- [WebUI README](docs/webui/README.md)
- [WebUI User Guide](docs/webui/USER_GUIDE.md)
- [Web UI Change Rules](docs/webui/web-ui-change-rules.md)
- [Monorepo Architecture](docs/architecture/monorepo-layout.md)
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
