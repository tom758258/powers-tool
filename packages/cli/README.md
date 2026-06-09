# Keysight Power CLI

CLI adapter for controlling Keysight DC power supplies.

- Package: `keysight-power-cli` `1.0.0`
- Import package: `keysight_power_cli`
- Console command: `keysight-power`
- Python: `>=3.10,<3.13`
- Runtime dependency: `keysight-power-core`

## Purpose

This package provides the `keysight-power` console script, command argument
parsing, JSON envelope handling, SCPI logging, command adapters over
`keysight-power-core`, and the local Power Worker daemon used by
orchestrators/agents.

Hardware-affecting commands remain explicit and opt-in; the default package
test suite runs without hardware.

## Package Contents

- `keysight_power_cli.cli`: top-level argument parser, command dispatch, JSON
  envelope conversion, SCPI logging, and runtime adapters into core.
- `keysight_power_cli.cli_io`: stable JSON success/error envelope helpers and
  optional `--save-json` output.
- `keysight_power_cli.worker`: local async worker service, config validation,
  event emission, job queueing, artifact writing, and `/command`/`/stop` HTTP
  endpoints.
- `keysight_power_cli.commands.output`: output command registration helpers.
- `keysight_power_cli.commands.sequence`: sequence command registration and CLI
  request conversion.
- `keysight_power_cli.commands.trigger`: trigger command registration and CLI
  request conversion.

## Install

From the repository root:

```powershell
uv sync --all-packages --dev
```

For an editable package-only install:

```powershell
uv pip install -e packages/core -e packages/cli --link-mode=copy
```

The primary entry point is the installed console script:

```powershell
uv run keysight-power doctor --simulate --json
```

The fallback module entry point is:

```powershell
uv run python -m keysight_power_cli.cli doctor --simulate --json
```

## Test

The default CLI tests are no-hardware tests:

```powershell
.\.venv\Scripts\python.exe -m pytest packages\cli\tests -q -p no:cacheprovider
```

Focused suites:

```powershell
.\.venv\Scripts\python.exe -m pytest packages\cli\tests\test_cli.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest packages\cli\tests\test_worker.py -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Pass `--basetemp PATH` to override it for a specific run.

Run the bundled no-hardware regression checklist:

```powershell
.\scripts\no-hardware-regression.ps1
```

### Scripted Validation

Run all scripts from the repository root in PowerShell. Each script writes a
machine-readable `report.json` and a human-readable `summary.md` under
`.tmp_tests`.

If the current Windows execution policy blocks `.ps1` files, use a
process-local bypass for the selected script:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\no-hardware-regression.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-smoke-validation.ps1 -Target E36312A
```

No-hardware regression runs focused follow-up checks, JSON/docs contract
checks, and the full default pytest suite:

```powershell
.\scripts\no-hardware-regression.ps1
```

Its default report directory is `.tmp_tests\no_hardware_regression`. To select
another Python executable or report directory:

```powershell
.\scripts\no-hardware-regression.ps1 -Python .\.venv\Scripts\python.exe -OutputDir .tmp_tests\my_regression
```

Smoke preflight uses only `--dry-run` and `--simulate`; it does not open VISA
or touch hardware:

```powershell
.\scripts\preflight-smoke-validation.ps1 -Target E36312A
.\scripts\preflight-smoke-validation.ps1 -Target EDU36311A
```

Reports are written to `.tmp_tests\smoke_validation_preflight\<Target>`.

Live smoke always runs the matching no-hardware preflight first and requires
an explicit `-Resource`. It pauses for confirmation before opening VISA:

```powershell
$env:E36312A_USB_RESOURCE = "USB0::...::INSTR"
$env:EDU36311A_USB_RESOURCE = "USB0::...::INSTR"

.\scripts\live-smoke-validation-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE
.\scripts\live-smoke-validation-check.ps1 -Target EDU36311A -Connection USB -Resource $env:EDU36311A_USB_RESOURCE
```

E36312A live smoke sets all channels to 1 V / 0.05 A, leaves all outputs off,
and briefly enables channel 1 for about 500 ms. EDU36311A defaults to a
read-only profile. `-Connection LAN` is also supported when an explicit LAN
VISA resource is supplied. Use `-Backend "@ivi"` or another backend only when
the local VISA setup requires it.

Batch validation runs only the checks selected by switches. Simulated
resources are useful for checking the batch/report workflow without hardware:

```powershell
.\scripts\batch-validation.ps1 `
  -RunE36312AOutput `
  -E36312AUsbResource "USB0::SIM::E36312A::INSTR" `
  -RunEDUReadOnly `
  -EDU36311AUsbResource "USB0::SIM::EDU36311A::INSTR"
```

For real hardware, replace the simulated resources with explicit VISA
resources. `-RunE36312AOutput` is state-changing; `-RunEDUReadOnly` is
read-only. The current `-RunIntegrationPytest` batch switch records a skipped
task only, so run hardware pytest directly when required.

### Hardware Pytest

Hardware integration tests are excluded from normal use unless an explicit
resource is passed. Run the read-only hardware suite first:

```powershell
uv run python -m pytest packages\cli\tests\integration -q -m hardware --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A
```

Output-affecting hardware pytest additionally requires `--run-output`:

```powershell
uv run python -m pytest packages\cli\tests\integration -q -m hardware_output --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A --run-output
```

Add `--backend "@ivi"` when needed. Before any output-affecting run, confirm
the expected instrument, disconnect unknown DUTs, and verify the requested
voltage/current are safe.

## Command Status

E36312A and EDU36311A have model-specific driver foundations selected from
valid `*IDN?` responses. Their channel-list SCPI is covered by no-hardware
tests. Simulated CLI measurement supports channels 1, 2, and 3 for these
models.

Real CLI measurement keeps generic instruments on channel 1. E36312A and
EDU36311A channels 2 and 3 use IDN-selected channel-list measurement queries.
Real CLI `set` is supported for E36312A and EDU36311A channels 1, 2, and 3. It
writes the current limit before voltage and does not enable output.

Real CLI `output-on` is supported for E36312A and EDU36311A channels 1, 2, 3,
and `all`. After `*IDN?`, it reads back `VOLT? (@N)` and `CURR? (@N)` before
sending `OUTP ON,(@N)`. With `--safety-config`, unsafe readback setpoints are
rejected before any output is enabled. Real CLI `output-off`, `output-state`,
`safe-off`, `cycle-output`, `apply`, `smoke-output`, and setpoint-only `ramp`
are also supported for both models. `output-off`, `output-state`, and
`cycle-output` also accept `--channel all`; `set`, `ramp`, and `smoke-output`
remain single-channel commands.

Real CLI `measure-all` and `trigger-pulse` remain E36312A-first commands for
all-channel measurement and rear digital trigger output pulses.
`validate-readonly` is a one-shot read-only diagnostic for E36312A and
EDU36311A.

`list-resources`, `verify`, `clear`, `error`, `measure`, `identify`,
`protection-status`, `protection-set`, `clear-protection`, and `snapshot` now
execute through shared core runners. The CLI still owns argparse handling,
human text output, JSON success/error envelopes, `--save-json`, and exit-code
mapping.

`snapshot --compare PATH` compares the current E36312A snapshot with either a
saved JSON envelope or raw snapshot `data`. It ignores `resource` and
`read_count`, uses default tolerances of 0.001 V/A for programmed setpoints,
0.05 V measured voltage, and 0.01 A measured current, and exits `3` when
differences are found.

`ramp` is a setpoint-only command for E36312A and EDU36311A: it sets current
limit first, then steps voltage from `--start-voltage` to the exact
`--stop-voltage`. It does not turn output on or off. E36312A `ramp` uses native
LIST when the pulse mode is `auto` or `native` and the ramp has at most 100
steps. EDU36311A real `ramp` does not support native LIST or completion-pulse
options. `set`, `apply`, `output-on`, `output-off`, and `ramp` accept
`--settle-ms` and `--verify-after-write`; verification failures return JSON
error code `verification_failed` and exit `3`.

## Power Worker Daemon

The Keysight Power Supply Worker is a local background service that listens on
localhost and accepts HTTP commands to control Keysight instruments
asynchronously.

For full details on the REST API, JSONL lifecycle events, and job result
artifacts, see the [Power Worker Contract](../../docs/contracts/power-worker-contract.md).
For the orchestrator/agent handoff flow, including ready-event discovery and
result artifact polling, see the
[Power Worker Orchestrator Guide](../../docs/contracts/power-orchestrator-workflows.md).

Start the worker in simulation mode on a dynamic port:

```powershell
uv run keysight-power worker --id power_1 --mode simulate --control-port 0
```

`POST /stop` is cooperative: the handler only sets stop state and wakes the
runner. The Worker emits structured `power_cleanup` JSONL events and does not
emit its final `summary` or stop the HTTP server until runner cleanup finishes.

When started, it outputs a `ready` event on stdout containing the dynamically
assigned control endpoints.

Run the simulator-only orchestrator smoke example:

```powershell
.\examples\worker_orchestrator_smoke.ps1
```

## Examples

List VISA resource strings reported by the selected backend:

```powershell
uv run keysight-power list-resources
```

This is passive discovery only: a resource string can appear here even when the
instrument is not currently reachable.

List only resources that can be opened and queried with `*IDN?`:

```powershell
uv run keysight-power list-resources --live-only
```

This opens each listed resource and sends `*IDN?`. Resources that cannot be
opened or do not respond to `*IDN?` are omitted. Text output includes each
resource's raw IDN response so the instrument model is visible. Add `--log-scpi`
to show the verification query and response for each live check.

Verify that one resource can be opened and queried with `*IDN?`:

```powershell
uv run keysight-power verify --resource "USB0::...::INSTR"
uv run keysight-power verify --resource "USB0::...::INSTR" --log-scpi
```

Clear instrument status and the error queue with `*CLS`:

```powershell
uv run keysight-power clear --resource "USB0::...::INSTR" --log-scpi
uv run keysight-power clear --dry-run --json --resource "USB0::SIM::E36103B::INSTR"
```

Read the instrument error queue without changing output state:

```powershell
uv run keysight-power error --resource "USB0::...::INSTR" --max-reads 20 --log-scpi
```

Measure voltage and current:

```powershell
uv run keysight-power measure --resource "USB0::...::INSTR" --channel 1 --log-scpi
uv run keysight-power measure --resource "USB0::...::INSTR" --channel 2 --log-scpi
uv run keysight-power measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
```

Measure all E36312A channels and read output state:

```powershell
uv run keysight-power measure-all --json --resource "USB0::...::INSTR" --log-scpi
uv run keysight-power read-status --json --resource "USB0::...::INSTR" --log-scpi
```

Run a full read-only validation pass on E36312A or EDU36311A:

```powershell
uv run keysight-power validate-readonly --json --resource "USB0::...::INSTR" --log-scpi --save-json logs\validate-readonly.json
```

Read programmed E36312A setpoints and protection state:

```powershell
uv run keysight-power readback --json --resource "USB0::...::INSTR" --log-scpi
uv run keysight-power protection-status --json --resource "USB0::...::INSTR" --log-scpi
```

Capture and compare E36312A snapshots:

```powershell
uv run keysight-power identify --json --resource "USB0::...::INSTR" --log-scpi
uv run keysight-power snapshot --json --resource "USB0::...::INSTR" --log-scpi
uv run keysight-power snapshot --json --resource "USB0::...::INSTR" --compare logs\e36312a-baseline.json
uv run keysight-power snapshot --simulate --json --redact-resource --resource "USB0::SIM::E36312A::INSTR"
uv run keysight-power snapshot-diff --summary --json --before logs\before.json --after logs\after.json
```

Preview a restore plan and save the plan data without opening VISA:

```powershell
uv run keysight-power restore-from-snapshot --dry-run --json --snapshot logs\before.json --resource "USB0::...::INSTR" --channel all --plan-json logs\restore-plan.json
```

Preview or confirm E36312A protection actions:

```powershell
uv run keysight-power clear-protection --dry-run --json --resource "USB0::...::INSTR" --all
uv run keysight-power clear-protection --json --resource "USB0::...::INSTR" --all --confirm --log-scpi
uv run keysight-power protection-set --dry-run --json --resource "USB0::...::INSTR" --channel all --ovp-voltage 5 --ocp on
uv run keysight-power protection-set --dry-run --json --resource "USB0::...::INSTR" --channel 1 --ocp-delay 0.5 --ocp-delay-trigger setting-change
uv run keysight-power protection-set --json --resource "USB0::...::INSTR" --channel all --ovp-voltage 5 --ocp on --confirm --log-scpi
```

Configure an E36312A rear digital pin as trigger output, arm one output channel
with a no-change STEP trigger sequence, and emit `*TRG`:

```powershell
uv run keysight-power trigger-pulse --json --resource "USB0::...::INSTR" --pin 1 --channel 1 --polarity positive --log-scpi
```

Use `--dry-run` to preview trigger-pulse SCPI without opening VISA. The final
`*TRG` may also trigger any already armed BUS-triggered instrument behavior.
Real execution checks `SYST:ERR?` after output-affecting writes and fails the
command if the instrument reports errors.

Native E36312A trigger/LIST commands:

```powershell
uv run keysight-power trigger-status --json --resource "USB0::...::INSTR" --channel all
uv run keysight-power trigger-step --json --resource "USB0::...::INSTR" --channel 1 --source bus --fire --wait-complete
uv run keysight-power trigger-list --json --resource "USB0::...::INSTR" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --completion-pulse-pins 1 --fire --wait-complete
uv run keysight-power trigger-fire --json --resource "USB0::...::INSTR" --channel 1 --wait-complete
uv run keysight-power trigger-abort --json --resource "USB0::...::INSTR" --channel all
```

For native BUS triggers, `trigger-step` and `trigger-list` only arm by default;
add `--fire` to send `*TRG` in the same command. Arm-only `trigger-list`
commands must also use `--leave-trigger-configured`, then a later
`trigger-fire --channel N` can fire the already armed channel. `trigger-pulse`
is the legacy post-action pulse helper and is separate from the native
trigger/list subsystem.

Run offline diagnostics:

```powershell
uv run keysight-power doctor --simulate --json
uv run keysight-power capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run keysight-power safety inspect --json --explain --safety-config examples\safety-config.toml --resource-alias sim-e36103b --channel 1
```

Validate a sequence file or preview deterministic write SCPI without opening
VISA:

```powershell
uv run keysight-power sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run keysight-power sequence --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
```

Sequence YAML files are formally supported through the core package's PyYAML
runtime dependency. A small built-in parser remains as a fallback for minimal
environments.

Preview output-affecting commands with no hardware writes:

```powershell
uv run keysight-power set --dry-run --json --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

Set low E36312A or EDU36311A setpoints without enabling output:

```powershell
uv run keysight-power set --json --resource "USB0::...::INSTR" --channel 1 --voltage 1 --current 0.05 --log-scpi
```

Real `set` first confirms the selected resource is an E36312A or EDU36311A
with `*IDN?`, then sends `CURR <current>,(@N)` followed by
`VOLT <voltage>,(@N)`. Channels other than 1, 2, and 3 are rejected.

Enable an E36312A or EDU36311A output only after setpoints are already safe:

```powershell
uv run keysight-power output-on --json --resource "USB0::...::INSTR" --channel 1 --log-scpi
uv run keysight-power output-on --json --resource "USB0::...::INSTR" --channel all --log-scpi
```

Real `output-on` first confirms the selected resource is an E36312A or
EDU36311A with `*IDN?`, reads programmed voltage/current setpoints, then sends
`OUTP ON,(@N)`. It does not change voltage or current setpoints.

Read back and cycle output state:

```powershell
uv run keysight-power output-state --json --resource "USB0::...::INSTR" --channel 1 --log-scpi
uv run keysight-power cycle-output --json --resource "USB0::...::INSTR" --channel 1 --duration-ms 500 --log-scpi
uv run keysight-power cycle-output --json --resource "USB0::...::INSTR" --channel all --duration-ms 500 --log-scpi
```

For `cycle-output --channel all`, the CLI enables channels 1, 2, and 3 in
order, waits once for `--duration-ms`, then disables channels 1, 2, and 3 in
order.

Apply low setpoints and enable output:

```powershell
uv run keysight-power apply --json --resource "USB0::...::INSTR" --channel 1 --voltage 1 --current 0.05 --log-scpi
uv run keysight-power apply --json --resource "USB0::...::INSTR" --channel all --voltage 1 --current 0.05 --log-scpi
uv run keysight-power apply --json --resource "USB0::...::INSTR" --channel all --voltage 1 --current 0.05 --no-output --log-scpi
```

Ramp voltage setpoints without changing output state:

```powershell
uv run keysight-power ramp --json --resource "USB0::...::INSTR" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --settle-ms 200 --log-scpi
uv run keysight-power ramp --json --resource "USB0::...::INSTR" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.5 --current 0.05 --completion-pulse-pins 1 --completion-pulse-mode native --log-scpi
```

Add an explicit safety config to apply local global limits to output plans:

```powershell
uv run keysight-power set --dry-run --json --safety-config examples\safety-config.toml --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

The config is never auto-discovered from the current directory. It is used only
when `--safety-config PATH` is passed to `set`, `apply`, `output-on`,
`output-off`, or `safe-off`. `--resource-alias ALIAS` is mutually exclusive
with `--resource` and requires the explicit safety config path.

```toml
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]

[[resources]]
alias = "sim-e36103b"
resource = "USB0::SIM::E36103B::INSTR"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
```

Resource-specific fields override global `[safety]` fields one by one. A raw
`--resource` that matches a `[[resources]].resource` entry also receives that
entry's resource-specific limits; otherwise the global `[safety]` limits apply.

```powershell
uv run keysight-power set --dry-run --json --safety-config examples\safety-config.toml --resource-alias sim-e36103b --channel 1 --voltage 1 --current 0.05
```

The early standalone examples provide the same passive discovery and identity
query behavior:

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
.\.venv\Scripts\python.exe examples\02_identify.py --resource "USB0::..."
```

Add `--json` to supported CLI commands for the stable machine-readable v1
contract. Diagnostic logs such as `--log-scpi` remain on stderr so JSON stdout
stays parseable. Every JSON success and error envelope includes
`metadata.duration_ms`.

## Safety Defaults

- Output-affecting behavior must be explicit.
- Real output execution is enabled for E36312A and EDU36311A `set`, `apply`,
  `output-on`, `output-off`, `output-state`, `cycle-output`, `safe-off`,
  `smoke-output`, and `ramp` on explicit channels 1, 2, or 3. `apply`,
  `output-on`, `output-off`, `output-state`, `cycle-output`, and `safe-off`
  accept `--channel all` and expand to channels 1, 2, and 3 in order. `set`,
  `ramp`, and `smoke-output` remain single-channel commands. `output-on` does
  not set voltage or current.
- Real `measure-all`, `trigger-pulse`, `trigger-status`, `trigger-list`, and
  native LIST-backed ramp are enabled only for E36312A. `status`, `readback`,
  `log`, `validate-readonly`, and protection commands are enabled for E36312A
  and EDU36311A. EDU36311A STEP trigger commands are simulator/dry-run planning
  only; real trigger/LIST execution remains disabled for that model.
- Real `clear`, `error`, and `measure` are safe I/O commands: `clear` sends
  `*CLS` and clears status/error state, while `error` and `measure` only query.
- `--safety-config` is explicit only and applies local plan validation limits;
  it does not enable real hardware output.
- Real VISA resources must not be hard-coded in committed files.
- Hardware tests must require a user-provided resource.
- Examples that enable output must set current limit before voltage and turn
  output off in cleanup.

## Docs

- Root workspace README: `../../README.md`
- JSON envelope contract: `../../docs/contracts/power-cli-jsonl-contract.md`
- Worker REST/event/artifact contract: `../../docs/contracts/power-worker-contract.md`
- Orchestrator/agent worker handoff: `../../docs/contracts/power-orchestrator-workflows.md`
- Supported models: `../core/docs/supported-models.md`
- Workspace overview: `../../docs/workspace.md`
- Release checklist: `../../docs/release-checklist.md`

## Status

Active package. Live E36312A validation covers read-only CLI flows,
output-safe setpoint flows, worker dry-run/read-only behavior, and native
LIST-backed trigger/ramp flows documented in the hardware test guide.
