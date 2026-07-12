# Keysight Power Core

Core library and driver layer for controlling Keysight DC power supplies safely.

Core ships inside the single `keysight-powers` distribution while preserving
the `powers_tool_core` import boundary. It owns hardware-facing behavior
and is shared by the CLI and WebUI adapters.

## Purpose

This package owns the hardware-facing model logic, safety validation,
transport helpers, simulator support, snapshot handling, and parser-neutral
sequence runtime. It must stay independent from the CLI and WebUI packages.

Use the core package when another Python package needs to call the power-supply
runtime directly. End users should normally use the `keysight-power` console
script included in the same `keysight-powers` distribution.

## Physical Identity And Registry Boundary

Core resolves a physical instrument from its reported manufacturer and model
before selecting a model-specific driver. Its physical catalog, lifecycle,
driver, channel, simulator, capability, electrical-range, and safety-coverage
registries use canonical vendor-qualified IDs such as
`keysight-e36312a`. Vendor-specific driver class names remain unchanged.

The existing CLI and adapter `model_profile` contract remains unchanged in
this phase. Generic no-hardware planning metadata is kept separately;
`generic-scpi` is a planning profile, not a physical model or live expected
model, and it is not present in physical registries.

## Live Support Policy Modes

`RuntimeOptions.support_policy_mode` defaults to `product`. After Core reads
`*IDN?`, it resolves the reported manufacturer plus model to a canonical
physical `model_id` and validates any expected-model guard. Product execution
then requires an exact `model_id + command + transport + backend + required
feature` scope before command-specific SCPI. Missing, unsupported, and pending
scopes fail closed.

Core also has an internal contributor-validation policy mode for running only
already-registered pending exact scopes. It does not select or override the
IDN-detected model, promote support, or bypass command/profile validation,
safety limits, confirmation, electrical ratings, sequence restrictions, or
cleanup behavior. Adapters decide whether that internal mode is available;
normal product integrations remain product mode.

Exact policy evaluation is feature-aware for `sequence_action` and
`trigger_source`. Sequence validates every distinct instrument-relevant
normalized action before its first step; host-only `wait` and `log` actions do
not require live feature entries. `trigger-step` and `trigger-list` validate
their effective BUS or Immediate source before trigger setup. A validated
command scope does not open an unregistered future action/source. Missing,
unknown, unsupported, and Product-mode pending feature entries fail closed;
Validation mode accepts only explicitly registered `feature_pending` entries.
A validated transport/backend parent may mix validated and pending command
features: validated siblings remain Product-open, while each pending feature
remains Validation-only. A transport-pending parent cannot contain a validated
feature.

`powers_tool_core.support_policy.live_support_policy_metadata()` and
`exact_live_support_metadata()` provide JSON-ready display projections without
exposing validation artifacts or mutable registry records. The model-level
projection distinguishes profile support, explicit diagnostic exemptions, and
registered scopes. The exact projection evaluates one detected model,
resource transport, and backend in Product mode for adapter UX; it does not
replace the enforcing runtime gate. These projections use schema version 2 and
canonical `model_id`; they do not expose evidence IDs, artifact paths,
checksums, or private evidence notes. Unevaluated diagnostics distinguish
reported manufacturer/model fields from resolved physical identity and expose
no Product-open command map.

Identity/status diagnostics and pure offline utilities are separate in this
projection. Exempt diagnostics may report exact Product-policy metadata after
a real IDN read without acquiring a model feature scope. If the detected model
has no active exact policy, the diagnostic may still succeed with an
unevaluated, empty support projection; this does not open live commands or
enable Generic fallback. Expected-model mismatches remain validation errors.
Offline-only utilities are marked `offline_only`; they are not diagnostics and
are never reported as Product-open exact live commands.

## Package Contents

- `powers_tool_core.connection`: VISA backend selection, resource listing,
  identity query, and connection helpers.
- `powers_tool_core.factory`: IDN-based driver selection for generic SCPI,
  E36312A, EDU36311A, and E3646A instruments.
- `powers_tool_core.drivers`: model-specific driver implementations and
  shared SCPI channel strategies.
- `powers_tool_core.operations`: output and setpoint operations such as
  `set`, `apply`, `output-on`, `output-off`, `safe-off`, `ramp`, `ramp-list`, and
  readback/snapshot helpers.
- `powers_tool_core.readonly`: read-only `status`, `readback`,
  `measure-all`, log, and validation flows, including dry-run plans that do
  not open VISA.
- `powers_tool_core.trigger`: E36312A trigger, STEP, native LIST, fire, and
  abort support.
- `powers_tool_core.sequence`: parser-neutral sequence document loading,
  linting, dry-run planning, and execution.
- `powers_tool_core.ramp_list`: versioned JSON Ramp List loading, full
  prevalidation, planning, and ordered software-setpoint execution.
- `powers_tool_core.discovery`, `instrument_io`, `protection`, and
  `snapshot`: adapter-neutral runners for discovery, safe instrument I/O,
  protection, and snapshot commands shared by CLI and WebUI.
- `powers_tool_core.command_runner`: shared router used by adapters that
  submit parser-neutral core requests.
- `powers_tool_core.cancellation` and `stop_cleanup`: cooperative
  cancellation, interruptible waits, GPIB-only local release, and structured
  stop cleanup results shared by Worker and WebUI.
- `powers_tool_core.safety`: explicit local safety-config loading and plan
  validation.
- `powers_tool_core.electrical_ratings` and `setpoint_limits`: verified
  independent-channel DC output ratings and effective safety limits.
- `powers_tool_core.setpoint_ranges`: official output voltage setpoint and
  output current limit programming-range metadata from model programming
  manuals.
- `powers_tool_core.capabilities`: command and model capability reporting.
- `powers_tool_core.support_policy`: exact live-support enforcement metadata
  and safe public display projections.
- `powers_tool_core.support_evidence`: immutable accepted historical evidence
  identities and non-sensitive migration metadata.
- `powers_tool_core.model_resolution`: strict no-hardware model profile
  resolution for dry-run/simulator planning and live expected-model guards.
- `powers_tool_core.model_enablement`: injectable consistency validation for
  Product-active, candidate, catalog-only, and de-scoped model inventories.
- `powers_tool_core.testing`: no-hardware simulator used by tests and CLI
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
.\scripts\live-cli-check.ps1 -Target E36312A -Connection USB -Resource USB0::SIM::E36312A::INSTR -Suite readonly -PlanOnly
```

Live suite checks and hardware pytest are explicit, opt-in hardware checks.
`scripts\live-cli-check.ps1` is the maintained contributor validation harness
and records target/connection/suite/case candidate-evidence artifacts under
`.tmp_tests`; passing artifacts do not automatically promote product support.
See [Contributing](../CONTRIBUTING.md) for the contributor workflow. For each
active model, `-Suite full` is the complete validation gate for all currently
project-supported LIVE features of that model. With a passing expanded
full-suite record for the approved model and connection, the model's currently
project-supported LIVE features may be opened. Disabled, unimplemented,
out-of-scope, or factory-only features are not implied by the pass. A passing
suite validates only the selected model, connection, suite, and recorded cases;
it does not validate other connection types or every factory instrument
function. Commands, state-changing behavior, and report locations are
documented in the [CLI README scripted validation section](../cli/README.md#scripted-validation).

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
They are the Product-active models. There are currently no candidate models;
E36313A, E36233A, E36441A, and E36155A remain catalog-only, while E36103B and
E36232A remain de-scoped. `GENERIC` is a no-hardware fallback profile, not a
physical-model lifecycle stage.
Channel-list SCPI, snapshot/readback parsing, protection state handling,
sequence loading/planning, safety validation, simulator behavior, and
output-operation planning are covered by no-hardware tests.

E36312A and EDU36311A protection trip reads use channel-list queries. Shared
Core protection status preserves aggregate flags while calculating them from
the selected channels, and the WebUI live-panel read returns parsed model
identity plus channel-local OVP/OCP trip state.

E36312A native trigger/LIST behavior has no-hardware coverage, while product
LIVE execution is limited to exact commands with accepted scopes. In
particular, `trigger-fire` and `trigger-pulse` are not product-open. Native
LIST execution belongs only to `trigger-list`; Ramp always uses software
setpoint steps. Unsupported models, including EDU36311A, do not expose trigger
dry-run or simulator behavior.

The current expanded full-suite records have passed for E36312A USB,
E36312A LAN, EDU36311A USB, EDU36311A LAN, and E3646A ASRL / RS-232. These
records remain scoped to the recorded model, connection, suite, and cases.
E3646A USB and LAN remain outside the current scope.

E3646A product LIVE support is ASRL / RS-232 + system VISA and only the exact
commands listed in [Supported Models](supported-models.md). A read-only or
output feature family does not open every command; for example,
`output-on` is not product-open. Software `ramp-list` and step-limited
`sequence` are not native LIST support.

For output workflows, `voltage` is the output voltage setpoint and `current`
is the output current limit/current setting on E36312A, EDU36311A, and
E3646A. Core exposes official programming-range metadata separately from
independent-channel DC output rating safety limits. The manuals document common
SCPI numeric parameter handling, so this metadata does not introduce
decimal-place rejection or silent rounding/truncation in Core.

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

After that guard, Core enforces exact product support using the resolved
canonical `model_id`, effective command, VISA resource transport, runtime
backend, and required feature. Missing or pending scopes fail closed before
command-specific I/O. This applies equally to direct Core callers and adapter
requests; no validation-mode bypass exists.

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
