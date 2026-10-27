[繁體中文](README.zh-TW.md)

# Powers Tool

Powers Tool is a safety-first, vendor-neutral Python toolkit for supported DC power
supplies. The single `powers-tool` distribution contains independent
`powers_tool_core`, `powers_tool_cli`, and `powers_tool_webui` import packages. It
uses VISA for registered USB, LAN, and explicitly configured RS-232/ASRL connections,
with dry-run, simulation, and machine-readable JSON/JSONL workflows.

Core owns instrument identification, drivers, SCPI, safety validation, and exact live
support. CLI and WebUI are parallel adapters; the Power Worker exposes the same Core
command boundary for local automation. Live devices are identified through `*IDN?`;
unknown, unregistered, or out-of-scope models, commands, transports, backends, and
features fail closed. Vendor-specific drivers, aliases, manuals, SCPI, and support
records retain their proper vendor names. See [Supported Models](docs/core/supported-models.md)
and [CLI planning/expected-model guidance](docs/cli/README.md#planning-identities-and-live-expected-model-guards).

**VISA backends:** Python installs and Windows bundles include PyVISA and PyVISA-py,
plus `psutil` for TCPIP interface discovery and `zeroconf` for HiSLIP discovery.
System VISA defaults to IVI (`@ivi`) and requires a separately installed runtime
(e.g., Keysight IO Libraries Suite or NI-VISA). Load failures never fall back to
PyVISA-py, even with `PYVISA_LIBRARY=@py`. Select PyVISA-py explicitly through CLI
`--backend @py` or WebUI Device options → VISA Backend. Custom CLI VISA library paths
and backend selectors remain subject to support policy; optional USB/serial backend
libraries are not bundled.

E36312A and EDU36311A have independently validated, exact Product-open TCPIP +
PyVISA-py (`@py`) scopes. USB + `@py` and other model/backend combinations remain
closed; Sequence and Trigger subfeatures have separate scope limits. Backend loading,
device identification, or runtime installation does not expand Product support.
Dry-run, simulation, and ordinary no-hardware checks require no physical instrument
or vendor VISA runtime. See [Supported Models](docs/core/supported-models.md).

## Features

- Control supported DC supplies over USB, LAN, or explicitly configured RS-232/ASRL via VISA
- Operate through the `powers-tool` CLI or local `powers-tool-webui` dashboard
- Switch WebUI between English and Traditional Chinese without reload or changes to
  machine-facing values, API payloads, or raw diagnostics
- Preview hardware-affecting commands with dry-run before opening VISA
- Test workflows without hardware with the built-in simulator
- Set voltage/current limits, control output state, and read live instrument data
- Run ramp, ramp-list, sequence, trigger, snapshot, restore, and protection workflows through Core
- Produce JSON/JSONL for automation, agents, and orchestrators
- Keep real output opt-in; default tests and simulator runs never enable instrument output

## Project Structure

The single `powers-tool` distribution takes `<version>` from `[project].version`
in the root `pyproject.toml`:

- Distribution: `powers-tool` `<version>`
- Core import: `powers_tool_core`
- CLI import: `powers_tool_cli`
- WebUI import: `powers_tool_webui`

The import paths remain independent. Do not use a `powers_tool.*` namespace package
or the retired `keysight_power.*` namespace.

```text
src/
  powers_tool_core/
  powers_tool_cli/
  powers_tool_webui/
desktop/
  package.json
  package-lock.json
  main.cjs
tests/
  core/
  cli/
  webui/
  integration/
  packaging/
  tooling/
docs/
  core/                runtime and Product support documentation
  cli/                 CLI maintainer and operator documentation
  webui/               WebUI and Desktop documentation
  contracts/           public protocol and workflow contracts
  help/                bundled Help presentation and maintenance
  architecture/
  CONTRIBUTING.md
  testing-guidelines.md
scripts/
```

## Install

From the repository root in PowerShell:

```powershell
cd path\to\powers-tool
```

Install uv if necessary, then verify it:

```powershell
py -m pip install --user uv
```

```powershell
uv --version
```

Create the virtual environment and sync development/test dependencies from `uv.lock`:

```powershell
uv venv .venv
```

```powershell
uv sync --all-extras --link-mode=copy
```

For CI or strict local checks, keep the committed lockfile unchanged:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Python `>=3.10` is supported; uv selects an available compatible version, or specify one:

```powershell
uv venv .venv --python 3.12
```

`uv.lock` identifies the `powers-tool` distribution. Windows installs
`powers-tool.exe`, `powers-tool-webui.exe`, and `powers-tool-webui-launcher.exe`
under `.venv\Scripts\`; former names are not compatibility aliases. If an existing
synced environment has missing or stale wrappers, reinstall only the project:

```powershell
uv sync --all-extras --link-mode=copy --reinstall-package powers-tool
```

Normal setup needs only `uv sync`. For more safe entry points, see the
[CLI Quick Start](docs/cli/README.md#quick-start) and
[WebUI User Guide](docs/webui/USER_GUIDE.md).

## Quick Start

These no-hardware and local-only examples never discover VISA resources or enable
real output.

Run the CLI simulator diagnostic:

```powershell
uv run powers-tool doctor --simulate --json
```

Start the local WebUI Launcher:

```powershell
uv run powers-tool-webui-launcher
```

Start the Electron development shell from `desktop/`:

```powershell
Set-Location .\desktop
npm ci
npm start
```

For details, see the [CLI README](docs/cli/README.md) and
[WebUI User Guide](docs/webui/USER_GUIDE.md).

## Build

Build one Python wheel and source distribution with the `dev` extra's `build` package:

```powershell
.\.venv\Scripts\python.exe -m build
```

Output:

```text
dist\powers_tool-<version>-py3-none-any.whl
dist\powers_tool-<version>.tar.gz
```

The distribution inspector validates the wheel/sdist and rejects validation scripts,
private fixtures, candidate evidence, and internal-only tests. The Windows Bundle is
assembled separately using PyInstaller onedir.

Prepare the locked development environment, including PyInstaller:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Build the shared CLI, WebUI Launcher, and private Desktop Host bundle:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

**Windows prerequisite:** The Launcher uses Tkinter; the build script checks that
Python has a working Tcl/Tk runtime before PyInstaller starts.

Shared output:

```text
dist\powers-tool\
  powers-tool.exe
  powers-tool-webui-launcher.exe
  powers-tool-webui-host.exe
  _internal\
```

The bundle's Launcher and installed `powers-tool-webui-launcher` both call
`powers_tool_webui.launcher:main`. The private `powers-tool-webui-host.exe` is not a
public CLI entry point; all three executables share one `_internal` directory.

For Desktop development, start the Electron shell that reuses the existing WebUI:

```powershell
Set-Location .\desktop
npm ci
npm start
```

The Desktop launches the private WebUI Host, fits the window to the display work area,
and supports System/Light/Dark themes; see the [WebUI README](docs/webui/README.md)
for UI details. Multiple instances may control **different** instruments, but separate
clients must not concurrently use the same physical instrument resource.

Build the Windows Desktop directory with the shared Python bundle:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

It contains `Powers Tool.exe`, the three Python executables, Electron runtime, and
one shared `_internal` directory; the same layout ships in the Windows ZIP.

Smoke the packaged CLI without hardware:

```powershell
.\dist\powers-tool\powers-tool.exe --version
.\dist\powers-tool\powers-tool.exe doctor --simulate --json
```

Assemble versioned wheel, sdist, Windows ZIP, and SHA-256 checksums:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

Output:

```text
release\<version>\powers-tool-<version>-windows-x64.zip
release\<version>\powers_tool-<version>-py3-none-any.whl
release\<version>\powers_tool-<version>.tar.gz
release\<version>\checksums.txt
```

The ZIP has one `powers-tool-<version>\` root with shared `_internal`;
`checksums.txt` covers only the ZIP, wheel, and sdist.

Run formal no-hardware Release Acceptance on a **clean, committed, unchanged HEAD**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

Acceptance uses the existing `.venv`, checks `uv.lock`, runs the entire no-hardware
suite once, and builds the release once. It validates the wheel/sdist/Desktop ZIP and
three SHA-256 hashes, installs the final wheel and sdist in separate clean environments,
checks bundled Help in both and every sdist console entry point, then runs CLI smoke for
all Product-active models, deeper capability-representative workflows, and simulator
`PlanOnly`. Add another deep representative only for a new capability family or hardware
structure. Reports (`report.json`, `summary.md`) are stored under the ignored output
root; a custom `-OutputRoot` must stay inside `.tmp_tests/`.

The manual **Build Windows** workflow offers `bundle`, `desktop`, `release`, and
`release-acceptance`; the first three only provide downloads. Only the last mode on
`main`, with explicit `create_draft=true`, may create a Draft Release from verified
report, commit, version, hashes, original accepted artifacts, and matching CHANGELOG.
Publication remains a manual review step. Acceptance never discovers VISA, opens a
resource, sends SCPI, or publishes a release; changed HEAD or worktree fails the gate.

## Test

Pytest defaults to the ignored local `.tmp_pytest/` directory; run it from the
repository root. Use `--basetemp .tmp_tests/<purpose>` for isolated runs and never
place generated artifacts in private `Local/`.

Run focused component tests during development:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

Run CI's Ruff check:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

Run the fast no-hardware suite (excluding Windows wrapper and release-acceptance
contract tests):

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests\cli\test_cli_wrappers.py --ignore=tests\packaging\test_release_acceptance.py
```

CI also checks tracked-text hygiene, whitespace, WebUI JavaScript/Node runtime,
cross-version Python contracts, packaging, and console entry points. Windows PowerShell
contracts and packaging smoke are conditional on changed paths; formal Release
Acceptance is not regular PR CI. See [Testing Guidelines](docs/testing-guidelines.md).

For scripted and live validation, see the
[CLI README](docs/cli/README.md#scripted-validation). Live hardware runs are explicit
opt-in and require a user-provided VISA resource.

## Documentation

- [Changelog](CHANGELOG.md)
- [Core README](docs/core/README.md)
- [Supported Models](docs/core/supported-models.md)
- [CLI User Guide](docs/cli/USER_GUIDE.md)
- [CLI README](docs/cli/README.md)
- [WebUI README](docs/webui/README.md)
- [WebUI User Guide](docs/webui/USER_GUIDE.md)
- [WebUI Change Rules](docs/webui/web-ui-change-rules.md)
- [Help Maintenance](docs/help/README.md)
- [Repository Layout](docs/architecture/monorepo-layout.md)
- [Testing Guidelines](docs/testing-guidelines.md)
- [Contributing Guide](docs/CONTRIBUTING.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)

## Contributing

See [Contributing](docs/CONTRIBUTING.md) for development ownership, no-hardware
test expectations, and the contributor validation-artifact workflow. Changes
to live model, command, transport, or backend support require reviewable
real-instrument evidence when applicable.

## License and Disclaimer

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Application icon: The Powers Tool application icon was generated with OpenAI
image generation in ChatGPT, then reviewed and selected by the project maintainer.

This project is independent and unofficial. It is not affiliated with,
endorsed by, or sponsored by supported instrument manufacturers or vendors.

All manufacturer names, product names, model names, and trademarks referenced
by Powers Tool remain the property of their respective owners.

Users are responsible for complying with applicable software, driver,
instrument, and documentation license terms from those vendors.
