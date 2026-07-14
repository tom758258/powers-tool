[Traditional Chinese](README.zh-TW.md)

# Powers Tool

Powers Tool is a vendor-neutral Python toolkit for controlling supported DC
power supplies. Version 2.0.0 provides one installable distribution,
`powers-tool`, with three import packages: `powers_tool_core`,
`powers_tool_cli`, and `powers_tool_webui`.

The framework is vendor-neutral, but current Product-active and
hardware-validated models are the Keysight models listed below. Vendor-neutral
architecture does not mean arbitrary or unknown power supplies are supported:
unregistered or unresolved live hardware fails closed. Vendor-specific
drivers, aliases, manuals, SCPI behavior, evidence, and support tables retain
their correct vendor names.

The shared Core runtime owns identity resolution, drivers, SCPI behavior,
safety, and exact live-support decisions. The CLI and WebUI are parallel
adapters over Core, while the Power Worker exposes the same Core command
boundary to local automation. The project supports USB, LAN, and explicit
RS-232/ASRL communication through VISA, with safety-first dry-run, simulator,
and machine-readable workflows.

Powers Tool was previously developed as Keysight Powers. Version 2.0.0
introduces the vendor-neutral product and package identity; old names are not
supported aliases. See the [version 2 migration guide](docs/migration-v2.md).

## Features

- Control supported Keysight DC power supplies over USB, LAN, or explicit
  RS-232/ASRL settings using VISA
- Use either the `powers-tool` CLI or the local `powers-tool-webui`
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

## Planning And Live Expected-Model Guards

Dry-run and simulator flows do not open real VISA hardware. For commands that
need model-specific planning, `--model` maps to the canonical physical
`planning_model_id`. `--profile generic-scpi` selects the separate nonphysical
`planning_profile_id` for supported dry-run commands. The two are mutually
exclusive, and simulator mode accepts only a physical planning model unless a
known deterministic SIM resource supplies it.

In live mode, `--model` maps to `expected_model_id` and is only a safety guard. The
connected instrument is still identified with `*IDN?`, and Core requires the
reported manufacturer and model to resolve to one canonical physical
`model_id` before checking the selected model and before any setup or write
SCPI. The selected model never overrides the IDN-detected driver.
`generic-scpi` is no-hardware planning only and is never a physical or live
expected model. Bare model names and legacy runtime aliases are rejected.

For model-aware live commands, Core makes the final product decision after
`*IDN?` using canonical `model_id + command + transport + backend + required
feature`. Missing exact metadata and pending TCPIP/pyvisa-py scopes
fail closed; system-VISA evidence does not validate another backend. Identity
diagnostics do not imply command support, and no validation bypass exists.
Unsupported model, command, and mode failures are intentional feature-lock
behavior; selecting a model is not a feature unlock.

Sequence and native trigger commands also enforce request-specific feature
metadata for sequence actions and trigger sources. A Product-open command does
not automatically open a future action or source; missing and pending feature
metadata fails closed. Physical models have explicit Product-active,
candidate, catalog-only, or de-scoped lifecycle boundaries. This release adds
the lifecycle framework without enabling a new model.

Valid no-hardware examples:

```powershell
uv run powers-tool set --dry-run --model keysight-e3646a --channel 1 --voltage 1 --current 0.05
uv run powers-tool readback --simulate --resource USB0::SIM::E36312A::INSTR --channel all
uv run powers-tool trigger-step --dry-run --model keysight-e36312a --channel 1 --source bus --fire
uv run powers-tool set --dry-run --profile generic-scpi --channel 1 --voltage 1 --current 0.05
```

Live guard example:

```powershell
uv run powers-tool set --model keysight-e36312a --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
```

This command requires the connected `*IDN?` model to be `E36312A`; it does not
force the E36312A driver if another model answers.

Current model boundaries are enforced across Core, CLI, and WebUI backend
direct jobs. Feature-family and simulator support do not mean every command in
that family has accepted product LIVE evidence. The exact command inventory is
listed in [Supported Models](docs/core/supported-models.md); notably,
`output-on`, `measure-all`, `trigger-pulse`, `trigger-fire`,
`restore-from-snapshot`, `log`, and resource-backed `doctor` are not
product-open. E3646A product LIVE remains ASRL / RS-232 + system VISA only,
and its `ramp-list` and step-limited `sequence` are software workflows, not
native LIST.

The maintained `full` live-validation suite now includes those implemented
commands as exact validation candidates where the model supports them:
E36312A adds `output-on`, `log`, resource-backed `doctor`, `measure-all`, and
real `restore-from-snapshot`; EDU36311A adds `output-on`, `log`, and
resource-backed `doctor`; E3646A adds `output-on` and resource-backed
`doctor`. Each live candidate invocation additionally requires a signed,
run-scoped, case-scoped, one-time capability issued by this maintained
wrapper. The capability binds the exact model, command, connection, case, and
request; the ordinary pending-support switch alone cannot admit a candidate.
This is an internal misuse-resistance contract, not a security boundary
against a user who controls or modifies the machine. It is not a public
bypass.
Normal Product mode remains closed until new live artifacts are run, reviewed,
registered, and promoted in a separate change. Existing historical evidence
does not cover these new standalone cases, and a future passing suite does not
promote them automatically. Direct `trigger-pulse` and `trigger-fire` remain
closed and are not candidates; the existing Product-open E36312A
`trigger-status`, `trigger-step`, `trigger-list`, and `trigger-abort` scopes are
unchanged.

For output commands, `voltage` means the output voltage setpoint and `current`
means the output current limit/current setting for E36312A, EDU36311A, and
E3646A. Core exposes official programming-range metadata from the model
programming manuals separately from the existing DC output rating safety
limits. E3646A programming ranges are range-dependent: LOW/P8V is 0 to 8.24 V
and 0 to 3.09 A, while HIGH/P20V is 0 to 20.60 V and 0 to 1.545 A. Powers Tool does
not currently claim an official manual-required decimal-place rejection rule
and does not round or truncate user setpoints before SCPI.

This is intentionally rejected:

```powershell
uv run powers-tool trigger-step --dry-run --resource USB0::FAKE::E36312A::INSTR --channel 1 --source bus --fire
```

Fake or live-looking resource strings are placeholders and must not imply a
real instrument model. Deterministic SIM resources, such as
`USB0::SIM::E36312A::INSTR`, are allowed because they map to known simulator
IDN/model data.

## Current Hardware Scope

| Lifecycle | Canonical model IDs | Current boundary |
| --- | --- | --- |
| Product-active | `keysight-e36312a` (Keysight E36312A), `keysight-edu36311a` (Keysight EDU36311A), `keysight-e3646a` (Keysight E3646A) | Exact Product-open scopes only |
| Candidate | None | No candidate models |
| Catalog-only | `keysight-e36313a`, `keysight-e36233a`, `keysight-e36441a`, `keysight-e36155a` | Identity/catalog metadata only |
| De-scoped | `keysight-e36103b`, `keysight-e36232a` | Blocked from Product and Validation use |

E36312A and EDU36311A TCPIP + `pyvisa_py` scopes remain pending and
Product-closed. E3646A remains Product-open only for its existing ASRL/RS-232
+ `system_visa` exact scopes; USB and TCPIP are not current E3646A scopes. A
successful identity diagnostic does not imply control support, and suite or
feature-family labels do not register additional commands. The complete
command and connection matrix is in
[Supported Models](docs/core/supported-models.md).

## Project Structure

The repository has one distribution and one version number. In examples,
`<version>` means `[project].version` from the root `pyproject.toml`:

- Distribution: `powers-tool` `<version>`
- Core import: `powers_tool_core`
- CLI import: `powers_tool_cli`
- WebUI import: `powers_tool_webui`

The import paths remain independent. Do not use a `keysight_power.*`
namespace package.

```text
src/
  powers_tool_core/
  powers_tool_cli/
  powers_tool_webui/
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
cd path\to\powers-tool
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

The lock file records the local project as `powers-tool`. Installed command
wrappers are `powers-tool`, `powers-tool-webui`, and
`powers-tool-webui-launcher`; former distribution, package, and command names
are not compatibility aliases.

If you need pip directly, use the virtual environment's Python:

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install ".[webui]"
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

Windows creates virtualenv console wrappers such as
`.\.venv\Scripts\powers-tool.exe` and
`.\.venv\Scripts\powers-tool-webui.exe`. The WebUI launcher wrapper is
`.\.venv\Scripts\powers-tool-webui-launcher.exe`.

## Build

Build the wheel and source distribution. This uses the `build` package from
the `dev` extra installed above:

```powershell
.\.venv\Scripts\python.exe -m build
```

This produces only one Python distribution:

```text
dist\powers_tool-2.0.0-py3-none-any.whl
dist\powers_tool-2.0.0.tar.gz
```

Standalone executables are separate PyInstaller workflows. Prepare the locked
development environment, which includes PyInstaller, before building exe
artifacts:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Build the standalone CLI and WebUI launcher executables:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_cli_exe.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_webui_exe.ps1
```

By default, these commands produce:

```text
dist\powers-tool.exe
dist\powers-tool-webui.exe
```

The standalone `powers-tool-webui.exe` artifact is distinct from the installed
`powers-tool-webui-launcher` console entry point; both invoke the existing
`powers_tool_webui.launcher:main` launcher implementation where applicable.

Check the built CLI executable without touching hardware:

```powershell
.\dist\powers-tool.exe --version
.\dist\powers-tool.exe doctor --simulate --json
```

Build a release folder with wheel, sdist, standalone executables, and checksums:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

For version 2.0.0, this produces release artifacts named with the selected
project version:

```text
release\<version>\powers-tool-<version>.exe
release\<version>\powers-tool-webui-<version>.exe
release\<version>\powers_tool-<version>-py3-none-any.whl
release\<version>\powers_tool-<version>.tar.gz
release\<version>\checksums.txt
```

Run the final no-hardware release acceptance from an isolated clean worktree.
The final acceptance uses separate locked Python 3.10 and Python 3.13
environments, builds and installs the wheel and sdist, checks all console entry
points, builds both standalone executables, and writes `report.json` and
`summary.md` under the ignored output root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\release-acceptance.ps1 `
  -Python310 (uv python find 3.10) `
  -CurrentPython (uv python find 3.13)
```

This acceptance script never performs VISA discovery, opens a resource, or
sends SCPI. It does not publish a release or rename the repository.

Before committing a release-tooling correction, maintainers may validate the
working-tree candidate by adding `-IncludeWorkingTreeChanges`. That mode
validates the recorded `source_commit` plus a candidate patch and labels its
report as pre-commit candidate validation. It does not replace final release
acceptance. After the corrective commit is created, rerun the command above
from a clean working tree without `-IncludeWorkingTreeChanges`; the final
report must identify the committed HEAD and show no overlay, candidate paths,
or candidate patch hash.

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

The maintained public validation entry points are layered as follows:

- `scripts\preflight-cli.ps1` runs model-aware CLI dry-run and simulator
  validation without hardware for one active model or all active models.
- `scripts\live-cli-check.ps1` always runs that external preflight, then the
  selected suite's exact plans, before any optional interactive live work.
- `scripts\release-acceptance.ps1` is the complete version-neutral isolated
  release gate and includes both the all-model preflight and a representative
  live `-PlanOnly` contract check.

Live feature validation is suite-based. For each active model, `-Suite full`
is the complete validation gate for all currently project-supported LIVE
features of that model. With a passing expanded full-suite record for the
approved model and connection, the model's currently project-supported LIVE
features may be opened. Disabled, unimplemented, out-of-scope, or factory-only
features are not implied by the pass.

Plan-only reports include the model-specific planned live-case inventory. The
new candidate cases remain limited to E36312A USB/TCPIP + system VISA,
EDU36311A USB/TCPIP + system VISA, and E3646A ASRL + system VISA; other models,
transports, pyvisa-py, and custom backends fail closed.
Each live candidate invocation also requires an exact, private, run-scoped
context created by this maintained wrapper. The existing hidden pending-scope
switch alone does not admit these command candidates.

A passed `scripts\live-cli-check.ps1` run validates only the selected target
model, connection type, suite, and cases recorded in that run's artifacts. It
does not mean every factory feature on that instrument, or the same feature on
another connection, is live validated.

Current accepted evidence connections are scoped by model, connection, suite,
and exact recorded cases:

- E36312A USB + system VISA
- E36312A LAN + system VISA
- EDU36311A USB + system VISA
- EDU36311A LAN + system VISA
- E3646A ASRL / RS-232 + system VISA

These are historical accepted full-suite records. They predate and do not
include the newly added validation-candidate cases. The expanded suite has
no newly run or accepted hardware evidence yet.

Core references these immutable historical bundles by stable evidence ID.
Their original artifact directories remain unchanged; migrating their identity
metadata is not new hardware validation. System-VISA evidence does not validate
pyvisa-py, a custom backend, another transport, model, vendor, command, or
feature. Passing a later validation artifact is candidate evidence only and
does not promote Product support automatically; evidence-backed promotion
remains separate P9 work.

Only the exact commands in the Core policy matrix are product-open on these
connections. E3646A live validation is restricted to ASRL / RS-232; E3646A
USB and LAN remain outside the current scope.

Examples:

```powershell
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection LAN -Resource $env:E36312A_LAN_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-edu36311a -Connection USB -Resource $env:EDU36311A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-edu36311a -Connection LAN -Resource $env:EDU36311A_LAN_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-e3646a -Connection ASRL -Resource $env:E3646A_ASRL_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite output -PlanOnly
```

## Contributing

See [Contributing](docs/CONTRIBUTING.md) for development ownership, no-hardware
test expectations, and the contributor validation-artifact workflow. Changes
to live model, command, transport, or backend support require reviewable
real-instrument evidence when applicable.

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
