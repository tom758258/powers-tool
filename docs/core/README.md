# Keysight Power Core

Core library and driver layer for controlling Keysight DC power supplies safely.

Core ships inside the single `keysight-powers` distribution while preserving
the `keysight_power_core` import boundary. It owns hardware-facing behavior
and is shared by the CLI and WebUI adapters.

## Purpose

This package owns the hardware-facing model logic, safety validation,
transport helpers, simulator support, snapshot handling, and parser-neutral
sequence runtime. It must stay independent from the CLI and WebUI packages.

Use the core package when another Python package needs to call the power-supply
runtime directly. End users should normally use the `keysight-power` console
script included in the same `keysight-powers` distribution.

## Package Contents

- `keysight_power_core.connection`: VISA backend selection, resource listing,
  identity query, and connection helpers.
- `keysight_power_core.factory`: IDN-based driver selection for generic SCPI,
  E36312A, EDU36311A, and E3646A instruments.
- `keysight_power_core.drivers`: model-specific driver implementations and
  shared SCPI channel strategies.
- `keysight_power_core.operations`: output and setpoint operations such as
  `set`, `apply`, `output-on`, `output-off`, `safe-off`, `ramp`, `ramp-list`, and
  readback/snapshot helpers.
- `keysight_power_core.readonly`: read-only `status`, `readback`,
  `measure-all`, log, and validation flows, including dry-run plans that do
  not open VISA.
- `keysight_power_core.trigger`: E36312A trigger, STEP, native LIST, fire, and
  abort support.
- `keysight_power_core.sequence`: parser-neutral sequence document loading,
  linting, dry-run planning, and execution.
- `keysight_power_core.ramp_list`: versioned JSON Ramp List loading, full
  prevalidation, planning, and ordered software-setpoint execution.
- `keysight_power_core.discovery`, `instrument_io`, `protection`, and
  `snapshot`: adapter-neutral runners for discovery, safe instrument I/O,
  protection, and snapshot commands shared by CLI and WebUI.
- `keysight_power_core.command_runner`: shared router used by adapters that
  submit parser-neutral core requests.
- `keysight_power_core.cancellation` and `stop_cleanup`: cooperative
  cancellation, interruptible waits, GPIB-only local release, and structured
  stop cleanup results shared by Worker and WebUI.
- `keysight_power_core.safety`: explicit local safety-config loading and plan
  validation.
- `keysight_power_core.electrical_ratings` and `setpoint_limits`: verified
  independent-channel DC output ratings and effective safety limits.
- `keysight_power_core.capabilities`: command and model capability reporting.
- `keysight_power_core.model_resolution`: strict no-hardware model profile
  resolution for dry-run/simulator planning and live expected-model guards.
- `keysight_power_core.testing`: no-hardware simulator used by tests and CLI
  simulation mode.

## Install

From the repository root:

```powershell
pip install -e ".[all,dev]"
```

For a basic Core/CLI install:

```powershell
pip install .
```

Runtime installs resolve `pyvisa`, PyYAML for sequence YAML support, and the
Python-version TOML fallback where needed. The package does not include a
console script. This project supports Python `>=3.10`; test dependencies come
from the root `dev` extra.

## Test

The default core tests are no-hardware tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
```

Focused suites are useful when changing specific layers:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core\test_model_drivers.py tests\core\test_trigger.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\core\test_operations.py -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Run pytest from the repository root. For an intentional per-run override, use
`--basetemp .tmp_tests/<purpose>`. Do not use `Local/` for pytest temporary
data or generated test artifacts.

The repository-level validation scripts also exercise core behavior through
the CLI adapter. Run the no-hardware gate before live validation:

```powershell
.\scripts\no-hardware-regression.ps1
.\scripts\preflight-smoke-validation.ps1 -Target E36312A
```

Live smoke and hardware pytest are explicit, opt-in hardware checks. Their
commands, state-changing behavior, and report locations are documented in the
[CLI README scripted validation section](../cli/README.md#scripted-validation).

## Docs

- Core integration guide: `integration.md`
- Supported models: `supported-models.md`
- CLI JSON contract that consumes core envelopes: `../contracts/power-cli-jsonl-contract.md`
- Root workspace README: `../../README.md`
- CLI validation scripts: `../cli/README.md#scripted-validation`
- Commands parameter contract: `../contracts/commands-parameter-contract.md`

## Status

Active package. E36312A, EDU36311A, and E3646A are the current model-specific
targets. Model-specific driver foundations are selected from valid `*IDN?`
responses.
Channel-list SCPI, snapshot/readback parsing, protection state handling,
sequence loading/planning, safety validation, simulator behavior, and
output-operation planning are covered by no-hardware tests.

E36312A and EDU36311A protection trip reads use channel-list queries. Shared
Core protection status preserves aggregate flags while calculating them from
the selected channels, and the WebUI live-panel read returns parsed model
identity plus channel-local OVP/OCP trip state.

E36312A native trigger/LIST behavior has no-hardware coverage and live USB
validation for channel 1 trigger-list, arm/fire, and trigger-fire. Native LIST
execution belongs only to `trigger-list`; Ramp always uses software setpoint
steps. Trigger workflows are E36312A-only. Unsupported models, including
EDU36311A, do not expose trigger dry-run or simulator behavior.
Hardware-affecting behavior remains explicit and opt-in.

E3646A RS-232 support covers validated read-only/output workflows plus
software `ramp-list` and step-limited software `sequence`. These workflows are
not native LIST support. E3646A protection, trigger/native LIST,
snapshot/restore, completion-pulse, and unsupported sequence step types remain
disabled by the feature-lock policy.

The adapter boundary is intentionally one-way: core contains driver methods,
SCPI helpers, simulator selection, no-hardware model resolution, and dry-run
planning; CLI and WebUI build `RuntimeOptions`/`OperationRequest` objects and
wrap returned `data` in their own transport envelopes.

Dry-run and simulator planning does not guess a model from arbitrary resource
strings. Output-family, Ramp List, Sequence, protection write, and trigger
planners require `RuntimeOptions.model_profile` or a known deterministic
simulator resource, and returned plans include `target.model_profile`.
Fake or live-looking resources such as `USB0::FAKE::E36312A::INSTR` are test
placeholders and must not imply a model. Deterministic SIM resources such as
`USB0::SIM::E36312A::INSTR` are accepted because they map to known simulator
IDN/model data. Trigger no-hardware planning accepts only E36312A. Live
hardware uses the IDN-detected model. In live mode, `model_profile` is an
expected-model guard: after `*IDN?`, Core requires the detected model to match
before setup/write SCPI. The selected model never overrides the IDN-selected
driver.

## Output Workflow Pulses

Completion pulses use E36312A rear digital pins; rear pins are separate from
the selected output channel. Ramp supports `segment` timing for one completion
pulse and `step` timing for a software post-action pulse after every voltage
write, including the final write. Every-step timing accepts `delay_ms = 0`.

Ramp List version 1 optionally accepts a document-level `completion_pulse`
object with `timing`, `pins`, and `polarity`. Sequence documents accept the canonical
`trigger-pulse` action. Software pulses snapshot and restore trigger/digital
pin settings unless `leave_trigger_configured` is explicitly requested.
They send global `*TRG`, which may also trigger other armed BUS behavior.
