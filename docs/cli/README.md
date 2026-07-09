# Keysight Power CLI

CLI adapter for controlling Keysight DC power supplies.

The CLI ships inside the single `keysight-powers` distribution while
preserving the `keysight_power_cli` import boundary. It exposes the
`keysight-power` console command and adapts operator commands to the shared
`keysight_power_core` runtime.

## Documentation Set

- [CLI User Guide](USER_GUIDE.md) - operator workflow, live resource
  selection, and safe first checks.
- [CLI README](README.md) - engineering setup, validation scripts, detailed
  command reference, automation, and maintainer boundaries.
- [Power CLI JSON / JSONL Contract](../contracts/power-cli-jsonl-contract.md)
  - command-line JSON envelope and JSONL rules.
- [Power Worker Contract](../contracts/power-worker-contract.md) - local
  worker REST, JSONL, and artifact contract.
- [Power Orchestrator Workflows](../contracts/power-orchestrator-workflows.md)
  - subprocess handoff and result polling guidance.
- [Commands Parameter Contract](../contracts/commands-parameter-contract.md)
  - stable command parameter boundaries.

## Purpose

This package provides the `keysight-power` console script, command argument
parsing, JSON envelope handling, SCPI logging, command adapters over
`keysight_power_core`, and the local Power Worker daemon used by
orchestrators/agents.

Hardware-affecting commands remain explicit and opt-in; the default package
test suite runs without hardware.

For normal operator workflows, start with the [CLI User Guide](USER_GUIDE.md).
This README keeps the detailed command reference, validation paths,
JSON/JSONL contracts, examples, and maintainer-facing CLI behavior in one
place.

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
pip install -e ".[all,dev]"
```

For a basic Core/CLI install:

```powershell
pip install .
```

The primary entry point is the installed console script:

```powershell
uv run keysight-power --version
uv run keysight-power doctor --simulate --json
```

The fallback module entry point is:

```powershell
uv run python -m keysight_power_cli.cli doctor --simulate --json
```

`--version` prints `keysight-power <package-version>` and exits without
requiring a subcommand or opening VISA.

## Test

The default CLI tests are no-hardware tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
```

Focused suites:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli\test_cli.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli\test_worker.py -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Run pytest from the repository root. For an intentional per-run override, use
`--basetemp .tmp_tests/<purpose>`. Do not use `Local/` for pytest temporary
data or generated test artifacts.

Run the bundled no-hardware regression checklist:

```powershell
.\scripts\no-hardware-regression.ps1
```

### Scripted Validation

Run all scripts from the repository root in PowerShell. Each script writes a
machine-readable `report.json` and a human-readable `summary.md` under
`.tmp_tests`.

| Script | Hardware use | Purpose |
| --- | --- | --- |
| `scripts\no-hardware-regression.ps1` | No hardware | Runs focused follow-up checks, JSON/docs contract checks, and the full default pytest suite. Use this as the normal no-hardware regression gate. |
| `scripts\live-cli-check.ps1` | Plan-only or explicit live hardware | Runs Meters-style target/connection/suite validation cases. Use this for feature validation records. |
| `scripts\preflight-smoke-validation.ps1` | No hardware | Runs target-specific dry-run and simulator smoke checks for E36312A or EDU36311A before live work. |
| `scripts\live-smoke-validation-check.ps1` | Live hardware | Legacy smoke wrapper for E36312A/EDU36311A bounded smoke checks. It is not the feature-suite validation record; use `live-cli-check.ps1` for suite validation. |
| `scripts\batch-validation.ps1` | Selected by switches | Runs only the selected simulated or live validation tasks and writes one batch report. |

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

Suite live validation uses an explicit target, connection, resource, and
suite. `-PlanOnly` runs only simulator, dry-run, lint, and expected-failure
checks; it does not open VISA. Without `-PlanOnly`, the script runs the same
preflight first, then requires interactive Enter confirmation before opening
VISA. If stdin is redirected, live execution is refused with a
confirmation-required report.

`live-cli-check.ps1` is a validation tool, not the same thing as declaring a
connection opened for normal use. A passed validation run is scoped to the
selected model, connection, suite, and cases; it does not prove every feature,
every connection type, or every model, and it does not mean USB validation
covers LAN validation.

Current opened records from passing validation artifacts:

- E36312A USB: validated/open
- EDU36311A USB: validated/open
- E3646A ASRL / RS-232: validated/open

E36312A LAN and EDU36311A LAN are not opened by current recorded artifacts.
They may be validated later by running `live-cli-check.ps1 -Suite full` with an
exact known LAN VISA resource and recording the passing artifact. E3646A live
validation is currently restricted to ASRL / RS-232.

```powershell
.\scripts\live-cli-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target EDU36311A -Connection USB -Resource $env:EDU36311A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target E3646A -Connection ASRL -Resource $env:E3646A_ASRL_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite output -PlanOnly
```

Supported suites are model-aware:

| Target | `full` suite composition |
| --- | --- |
| E36312A | `readonly`, `output`, `protection`, `snapshot`, `trigger-list`, `software-sequence` |
| EDU36311A | `readonly`, `output`, `protection`, `software-sequence` |
| E3646A | `readonly`, `output`, `software-sequence` |

For each active model, `-Suite full` is the complete validation gate for all
currently project-supported LIVE features of that model. With a passing
expanded full-suite record for the approved model and connection, the model's
currently project-supported LIVE features may be opened. Disabled,
unimplemented, out-of-scope, or factory-only features are not implied by the
pass.

A passed suite means the target model matched, the selected connection type
was used, the selected suite/cases passed, and artifacts were recorded under
`.tmp_tests`. It does not imply untested features, skipped suites, other
models, other connection types, disabled features, out-of-scope factory
features, or every instrument function are validated. It does not validate
the entire model. Explicit unsupported suite requests fail before live
execution instead of silently skipping everything.

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | validated/open | not opened by current artifacts; may be validated later with exact LAN VISA resource | N/A |
| EDU36311A | validated/open | not opened by current artifacts; may be validated later with exact LAN VISA resource | N/A |
| E3646A | not current scope | not current scope | validated/open |

E3646A suite validation is ASRL/RS-232 focused. It uses CH1/CH2, records that
`OUTP ON/OFF` is global, and treats `ramp-list` and `sequence` as software
workflows only, not native LIST. E3646A protection, trigger/native LIST,
snapshot/restore, completion-pulse, and unsupported sequence steps remain
disabled in live, simulate, and dry-run paths.

EDU36311A `software-sequence` validation covers only project-supported
software `ramp-list` and sequence read-only/output workflows. It does not
enable trigger/native LIST, snapshot, or restore-from-snapshot.

Smoke preflight uses only `--dry-run` and `--simulate`; it does not open VISA
or touch hardware. It uses deterministic SIM resources for the selected target
so the no-hardware model profile is explicit:

```powershell
.\scripts\preflight-smoke-validation.ps1 -Target E36312A
.\scripts\preflight-smoke-validation.ps1 -Target EDU36311A
```

Pass `-Profile readonly` with `-Target EDU36311A` only when you need the
legacy read-only preflight instead of the default output-smoke preflight.

Reports are written to `.tmp_tests\smoke_validation_preflight\<Target>`.

Live smoke always runs the matching no-hardware preflight first and requires
an explicit `-Resource`. The script does not scan for resources, guess a
resource, or read an environment default. Discover a live resource first, copy
the exact value, then pass it explicitly:

```powershell
.\.venv\Scripts\keysight-power.exe list-resources --live-only --json
```

Use `list-resources --verify --json` instead when you need to diagnose stale
VISA cache entries. After choosing the intended live resource, run the live
smoke script. It pauses for confirmation before opening VISA:

```powershell
$env:E36312A_USB_RESOURCE = "USB0::...::INSTR"
$env:EDU36311A_USB_RESOURCE = "USB0::...::INSTR"

.\scripts\live-smoke-validation-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE
.\scripts\live-smoke-validation-check.ps1 -Target EDU36311A -Connection USB -Resource $env:EDU36311A_USB_RESOURCE
```

E36312A and EDU36311A live smoke are the normal hardware acceptance gates.
They run read-only checks first, read protection status without changing
protection settings, set all channels to 1 V / 0.05 A with outputs off, and
briefly enable CH1, CH2, and CH3 one at a time for about 500 ms each.
EDU36311A can still run the legacy read-only profile with `-Profile readonly`.
`-Connection LAN` is also supported when an explicit LAN VISA resource is
supplied. Use `-Backend "@ivi"` or another backend only when the local VISA
setup requires it.

Legacy smoke success is a bounded smoke result, not a complete
feature-validation suite result. For enabling or recording a model-specific
feature, use the corresponding `live-cli-check.ps1` suite/case result.

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

### Optional Hardware Pytest

The live smoke script is the normal hardware OK gate for operator acceptance.
Run hardware pytest only when you need deeper repeatable hardware regression,
when a changed feature has matching hardware tests, or when validating SCPI,
trigger, protection-setting, or intentional protection-trip behavior beyond
the smoke script.

Hardware integration tests are excluded from normal use unless an explicit
resource is passed. If deeper hardware pytest is needed, run the read-only
hardware suite first:

```powershell
uv run python -m pytest tests\integration -q -m hardware --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A
```

Output-affecting hardware pytest additionally requires `--run-output`:

```powershell
uv run python -m pytest tests\integration -q -m hardware_output --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A --run-output
```

Add `--backend "@ivi"` when needed. Before any output-affecting run, confirm
the expected instrument, disconnect unknown DUTs, and verify the requested
voltage/current are safe.

## Command Status

E36312A and EDU36311A have model-specific driver foundations selected from
valid `*IDN?` responses. Their channel-list SCPI is covered by no-hardware
tests. Simulated CLI measurement supports channels 1, 2, and 3 for these
models.

### Model Profiles And Live Expected-Model Guards

Output-family commands, `ramp-list`, `sequence`, `protection-set`,
`clear-protection`, and trigger workflows use strict model resolution in
`--dry-run` and `--simulate` mode. In these no-hardware planning paths,
`--model` is the model profile used for planning, channel validation,
capability selection, and SCPI preview. They require either `--model` or a
known deterministic simulator resource such as `USB0::SIM::E36312A::INSTR`.
Trigger no-hardware paths are E36312A-only and require `--model E36312A` or a
known deterministic E36312A SIM resource. The CLI does not infer a model from
arbitrary fake, live-looking, or alias-only resource strings.

Examples:

```powershell
uv run keysight-power set --dry-run --model E3646A --channel 1 --voltage 1 --current 0.05
uv run keysight-power readback --simulate --resource USB0::SIM::E36312A::INSTR --channel all
uv run keysight-power trigger-step --dry-run --model E36312A --channel 1 --source bus --fire
```

This is rejected because a fake resource is only a placeholder and must not
imply a model:

```powershell
uv run keysight-power trigger-step --dry-run --resource USB0::FAKE::E36312A::INSTR --channel 1 --source bus --fire
```

Deterministic SIM resources are accepted because they map to known simulator
IDN/model data.

In live mode, `--model` is an expected-model guard. The CLI opens the explicit
resource, queries `*IDN?`, and requires the reported model to match before any
setup or write SCPI. The selected model never overrides the IDN-detected
driver.

Unsupported model, command, and mode failures are intentional feature-lock
behavior. `--model` is not a feature unlock: in dry-run/simulate mode it only
selects the no-hardware planning profile, and in live mode it only checks that
the connected `*IDN?` model is the expected one. `GENERIC` is no-hardware only
and cannot be used as a live expected model.

Live guard example:

```powershell
uv run keysight-power set --model E36312A --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
```

This requires the connected `*IDN?` model to be `E36312A`.

Accepted no-hardware model profiles are `E36312A`, `EDU36311A`, `E3646A`,
and `GENERIC`. In `--simulate` mode, `--model` can derive the matching
deterministic simulator resource for active supported models except
`GENERIC`. `GENERIC` is a conservative no-hardware profile and is not a live
expected model. If both `--model` and a SIM resource are provided, their models
must match. Unsupported models, including EDU36311A, do not expose trigger
dry-run or simulator behavior.

No-hardware plans include `data.plan.target.model_profile`. Channel validation
and `--channel all` expansion use that profile: E3646A expands `all` to CH1
and CH2 and rejects CH3; E36312A and EDU36311A expand to CH1, CH2, and CH3;
GENERIC conservatively allows CH1 only.

Trigger/native LIST workflows are E36312A-only. EDU36311A supports validated
read-only, output, and protection workflows, but trigger/native LIST,
`snapshot`, and `restore-from-snapshot` are disabled in live, simulate, and
dry-run until separately implemented and hardware validated. E3646A supports
validated RS-232 read-only/output workflows plus software `ramp-list` and
step-limited software `sequence`; those workflows are not native LIST support
and reject unsupported protection, trigger, snapshot, restore, native LIST,
and completion-pulse sequence steps. E36103B and E36232A are not active
supported models and are rejected as model profiles and live expected-model
guards. If live `*IDN?` reports either model, model-aware commands reject the
instrument instead of falling back to `GenericScpiPowerSupply`; `verify` and
`list-resources --live-only` may still report the raw IDN as diagnostics.

Real CLI measurement keeps generic instruments on channel 1. E36312A and
EDU36311A channels 2 and 3 use IDN-selected channel-list measurement queries.
Real CLI `set` is supported for E36312A and EDU36311A channels 1, 2, and 3,
and for live-validated E3646A RS-232 / ASRL channels 1 and 2. It accepts
`--voltage`, `--current`, or both. Omitted setpoints are left unchanged; when
both are supplied, it writes the current limit before voltage. It does not
enable output.

Real CLI `output-on` is supported for E36312A and EDU36311A channels 1, 2, 3,
and `all`, and for live-validated E3646A RS-232 / ASRL channels 1, 2, and
`all`. After `*IDN?`, it reads back programmed voltage/current setpoints
before enabling output. With `--safety-config`, unsafe readback setpoints are
rejected before any output is enabled. Real CLI `output-off`, `output-state`,
`safe-off`, `cycle-output`, `apply`, `smoke-output`, and setpoint-only `ramp`
are also supported for these models.
`output-off`, `output-state`, and `cycle-output` also accept `--channel all`;
`set`, `ramp`, and `smoke-output` remain single-channel commands.

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

`ramp` is a setpoint-only command for E36312A, E3646A, and EDU36311A: it sets
current limit first, then steps voltage from `--start-voltage` to the exact
`--stop-voltage`. It does not turn output on or off and always uses software
setpoint steps. E3646A and EDU36311A real `ramp` do not support
completion-pulse options. `set`, `apply`, `output-on`, `output-off`, and
`ramp` accept `--settle-ms` and `--verify-after-write`; verification failures
return JSON error code `verification_failed` and exit `3`.

`ramp-list` runs 1 to 10 ordered software-setpoint ramp segments through one
VISA session. It validates the complete versioned JSON document and all
generated setpoints before the first hardware write. It does not enable or
disable output, use native LIST, or perform automatic safe-off on failure.

Ramp `--completion-pulse-timing segment` preserves one completion pulse.
`--completion-pulse-timing step` emits a software post-action pulse after
every voltage write and accepts `--delay-ms 0`.
Rear pulse pins are not output channels. Pulse workflows are E36312A-only, and
`*TRG` may affect other already armed BUS-triggered behavior.

Ramp List version 1 may contain a global `completion_pulse` object. Inline
`--segment` usage accepts `--completion-pulse-timing`,
`--completion-pulse-pins`, and `--completion-pulse-polarity`; with `--file`,
the document is authoritative and CLI pulse overrides are rejected.

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
uv run keysight-power ramp-list --lint --json --file example.ramp-list.json
uv run keysight-power ramp-list --dry-run --json --model E36312A --file example.ramp-list.json
uv run keysight-power ramp-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

## Power Worker Daemon

The Keysight Power Supply Worker is a local background service that listens on
localhost and accepts HTTP commands to control Keysight instruments
asynchronously.

For full details on the REST API, JSONL lifecycle events, and job result
artifacts, see the [Power Worker Contract](../contracts/power-worker-contract.md).
For the orchestrator/agent handoff flow, including ready-event discovery and
result artifact polling, see the
[Power Worker Orchestrator Guide](../contracts/power-orchestrator-workflows.md).

Start the worker in simulation mode on a dynamic port:

```powershell
uv run keysight-power worker --id power_1 --mode simulate --control-port 0
```

Worker dry-run/simulate requests that need model-specific planning must pass
`arguments.model_profile` in the `/command` request, unless the configured
resource is a known deterministic SIM resource. Worker does not provide a
config-level model default.

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

### Resource Discovery And Live Resource Setup

List only VISA resources that can be opened and queried with `*IDN?`:

```powershell
uv run keysight-power list-resources --live-only
```

Use this for normal live operation. Text output includes each resource's raw
IDN response so the instrument model is visible. Add `--log-scpi` to show the
verification query and response for each live check.

List VISA resource strings reported by the selected backend without opening
them:

```powershell
uv run keysight-power list-resources
```

This is passive discovery only: a resource string can appear here even when the
instrument is not currently reachable.

For live USB examples below, set the VISA resource once per PowerShell session:

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
```

### Generic USB Live Examples

Verify that one resource can be opened and queried with `*IDN?`:

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_RESOURCE"
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

Clear instrument status and the error queue with `*CLS`:

```powershell
uv run keysight-power clear --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

Read the instrument error queue without changing output state:

```powershell
uv run keysight-power error --resource "$env:KEYSIGHT_POWER_RESOURCE" --max-reads 20 --log-scpi
```

### E3646A RS-232 / ASRL Examples

E3646A support over RS-232/ASRL includes live-validated read/status and output
workflows. Before any live E3646A output command, confirm the physical setup
has been checked and the requested voltage/current limits are safe for the
connected load.

Model-supported commands include `identify`, `measure`, `readback`,
`read-status`, `output-state`, `capabilities`, `set`, `apply`, `output-on`,
`output-off`, `safe-off`, `cycle-output`, `smoke-output`, `ramp`,
`ramp-list`, and output-affecting `sequence` steps. `verify` is also
available as a model-independent connection diagnostic that opens the selected
resource and queries `*IDN?`. Protection writes, trigger workflows, snapshot
restore, completion pulses, and native LIST remain disabled.
`ramp-list` is software setpoint stepping, and `sequence` is a step-limited
software workflow for validated output/read-only steps; neither is native LIST.

E3646A uses `INST:NSEL` channel preselection for setpoint writes and readbacks.
`OUTP ON/OFF` is a global output enable/disable on this model, so `output-on`,
`output-off`, `safe-off`, `cycle-output`, and `smoke-output` can affect the
instrument output state globally even when a command accepts a channel.
E3646A `sequence` accepts only validated read-only/output steps; protection,
trigger, snapshot, restore, native LIST, and completion-pulse step types are
rejected by the current feature-lock policy.

Set the ASRL resource once per PowerShell session:

```powershell
$env:KEYSIGHT_POWER_ASRL_RESOURCE = "ASRL1::INSTR"
```

For repeated examples, keep common ASRL settings in variables:

```powershell
$Base = @("--resource", "$env:KEYSIGHT_POWER_ASRL_RESOURCE", "--serial-read-termination", "CRLF", "--serial-write-termination", "LF")
$Remote = @("--serial-remote", "--serial-local-on-close")
```

Plain resource discovery does not need serial options:

```powershell
uv run keysight-power list-resources
```

If Connection Expert already has the ASRL resource configured and verified,
you can let VISA use those settings:

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE"
```

Serial settings are explicit only. If omitted, the CLI does not overwrite
VISA backend, Keysight IO Libraries Suite, or Connection Expert serial
settings. If supplied, only those supplied fields are applied to ASRL
resources. The E3646A factory example is 9600 baud, 8 data bits, none parity,
2 stop bits, and DTR/DSR handshake, but the actual instrument front-panel
settings may differ:

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` sends `SYST:REM` after opening the ASRL resource.
`--serial-local-on-close` best-effort sends `SYST:LOC` during cleanup. These
commands affect the instrument remote/local state and are never sent unless
explicitly requested.

Read/status examples:

```powershell
uv run keysight-power identify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-remote --serial-local-on-close
uv run keysight-power readback --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
uv run keysight-power output-state --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

Validated output examples:

```powershell
uv run keysight-power set @Base @Remote --channel 1 --voltage 1 --current 0.05 --json --log-scpi
uv run keysight-power apply @Base @Remote --channel 1 --voltage 1 --current 0.05 --no-output --json --log-scpi
uv run keysight-power output-on @Base @Remote --channel 1 --confirm --json --log-scpi
uv run keysight-power output-off @Base @Remote --channel 1 --json --log-scpi
uv run keysight-power safe-off @Base @Remote --channel 1 --json --log-scpi
uv run keysight-power ramp @Base @Remote --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --json --log-scpi
```

`output-on`, `cycle-output`, `smoke-output`, and `apply` without `--no-output`
require `--confirm` when the selected setpoints exceed the configured
confirmation threshold. `set`, `output-off`, `safe-off`, `ramp`, and
`ramp-list` do not require `--confirm`.

For serial terminations, prefer aliases in PowerShell:

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-read-termination CRLF --serial-write-termination LF
```

Supported aliases are `CR`, `LF`, `CRLF`, and `NONE`/`none`. `NONE` means do
not set that termination option. Omitted or empty termination fields also mean
do not override the VISA setting. Custom raw strings are still accepted, but
PowerShell may pass values such as `\r` as a literal backslash plus `r`; use
the aliases when you need actual control characters.

### Read-Only Command Examples

Measure voltage and current:

```powershell
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 2 --log-scpi
```

Measure all E36312A channels and read output state:

```powershell
uv run keysight-power measure-all --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power read-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

Run a full read-only validation pass on E36312A or EDU36311A:

```powershell
uv run keysight-power validate-readonly --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi --save-json logs\validate-readonly.json
```

Read programmed E36312A setpoints and protection state:

```powershell
uv run keysight-power readback --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power protection-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

For E36312A and EDU36311A, `protection-status` reads OVP/OCP trip flags per
channel. The existing aggregate flags remain available and are calculated as
the OR of the selected channel results.

### Snapshot And Restore Examples

Capture and compare E36312A snapshots:

```powershell
uv run keysight-power identify --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power snapshot --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power snapshot --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --compare logs\e36312a-baseline.json
uv run keysight-power snapshot-diff --summary --json --before logs\before.json --after logs\after.json
```

Preview a restore plan and save the plan data without opening VISA:

```powershell
uv run keysight-power restore-from-snapshot --dry-run --json --snapshot logs\before.json --resource USB0::SIM::E36312A::INSTR --channel all --plan-json logs\restore-plan.json
```

### Protection And Trigger Examples

Preview or confirm E36312A protection actions:

```powershell
uv run keysight-power clear-protection --dry-run --json --model E36312A --all
uv run keysight-power clear-protection --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --all --confirm --log-scpi
uv run keysight-power protection-set --dry-run --json --model E36312A --channel all --ovp-voltage 5 --ocp on
uv run keysight-power protection-set --dry-run --json --model E36312A --channel 1 --ocp-delay 0.5 --ocp-delay-trigger setting-change
uv run keysight-power protection-set --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --ovp-voltage 5 --ocp on --confirm --log-scpi
```

Configure an E36312A rear digital pin as trigger output, arm one output channel
with a no-change STEP trigger sequence, and emit `*TRG`:

```powershell
uv run keysight-power trigger-pulse --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --pin 1 --channel 1 --polarity positive --log-scpi
```

Use `--dry-run --model E36312A` or a deterministic E36312A SIM resource to
preview trigger SCPI without opening VISA. Trigger dry-run and simulator
behavior is E36312A-only; unsupported models do not expose trigger
no-hardware behavior. The final `*TRG` may also trigger any already armed
BUS-triggered instrument behavior. Real execution checks `SYST:ERR?` after
output-affecting writes and fails the command if the instrument reports
errors. Live trigger behavior remains IDN-driven; a live `--model` only
requires the connected IDN model to match and never overrides connected
hardware.

Native E36312A trigger/LIST commands:

```powershell
uv run keysight-power trigger-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all
uv run keysight-power trigger-step --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --source bus --fire --wait-complete
uv run keysight-power trigger-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --completion-pulse-pins 1 --fire --wait-complete
uv run keysight-power trigger-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --bost-list on,off --eost-list off,on --trigger-output-pins 1 --source immediate --wait-complete
uv run keysight-power trigger-fire --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --wait-complete
uv run keysight-power trigger-abort --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all
```

For native BUS triggers, `trigger-step` and `trigger-list` only arm by default;
add `--fire` to send `*TRG` in the same command. BUS `--wait-complete` requires
`--fire`. Immediate source starts when `INIT` is sent and rejects `--fire`.
Arm-only LIST requires `--leave-trigger-configured`; a LIST that starts without
`--wait-complete` also requires `--leave-trigger-configured`, otherwise restore
would abort it. Trigger Step keeps its existing non-wait behavior. For
`trigger-fire`, `--channel N` is required only with `--wait-complete`; it
selects the output channel to abort if the instrument-wide completion wait
times out or is interrupted. It does not limit the scope of `*TRG` or the
completion wait. `trigger-pulse` is the legacy post-action pulse helper and is
separate from the native trigger/list subsystem.
Canonical Trigger LIST files and flags accept per-step `bost_list` and
`eost_list` plus `trigger_output_pins` and `trigger_output_polarity`. Enabled
pulses require explicit output pins. Legacy `--completion-pulse-pins` remains
a final-step EOST pulse and cannot be mixed with canonical fields. A completed
wait restores the pre-run Trigger settings and LIST table unless
`--leave-trigger-configured` is selected.

### Output-Affecting Examples

Set low E36312A, E3646A, or EDU36311A setpoints without enabling output:

```powershell
uv run keysight-power set --model E36312A --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
uv run keysight-power set --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --current 0.05 --log-scpi
uv run keysight-power set --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --log-scpi
```

The first example uses `--model E36312A` as a live expected-model guard: it
requires the connected `*IDN?` model to be E36312A before any setup/write SCPI.

Real `set` first confirms the selected resource is an E36312A, E3646A, or
EDU36311A with `*IDN?`, then writes only the requested setpoint fields. E3646A
uses channels 1 and 2 with `INST:NSEL` preselection; E36312A and EDU36311A use
channels 1, 2, and 3.

Enable an E36312A, E3646A, or EDU36311A output only after setpoints are
already safe:

```powershell
uv run keysight-power output-on --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --confirm --log-scpi
uv run keysight-power output-on --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --confirm --log-scpi
```

Real `output-on` first confirms the selected resource is an E36312A, E3646A,
or EDU36311A with `*IDN?`, reads programmed voltage/current setpoints, then
enables the selected output. It does not change voltage or current setpoints.
For E3646A, `OUTP ON/OFF` is a global output enable/disable. Confirm the
physical setup and connected load before enabling output.

Read back and cycle output state:

```powershell
uv run keysight-power output-state --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
uv run keysight-power cycle-output --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --duration-ms 500 --confirm --log-scpi
uv run keysight-power cycle-output --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --duration-ms 500 --confirm --log-scpi
```

For `cycle-output --channel all`, the CLI enables channels 1, 2, and 3 in
order, waits once for `--duration-ms`, then disables channels 1, 2, and 3 in
order.

Apply low setpoints and enable output:

```powershell
uv run keysight-power apply --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --current 0.05 --confirm --log-scpi
uv run keysight-power apply --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --voltage 1 --current 0.05 --confirm --log-scpi
uv run keysight-power apply --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --voltage 1 --current 0.05 --no-output --log-scpi
```

Add an explicit safety config to apply local global limits to output plans:

```toml
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
```

Resource-specific fields override global `[safety]` fields one by one. A raw
`--resource` that matches a `[[resources]].resource` entry also receives that
entry's resource-specific limits; otherwise the global `[safety]` limits apply.

### Ramp And Sequence Examples

Ramp voltage setpoints without changing output state:

```powershell
uv run keysight-power ramp --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --settle-ms 200 --log-scpi
uv run keysight-power ramp --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.5 --current 0.05 --completion-pulse-pins 1 --log-scpi
```

Validate a sequence file or preview deterministic write SCPI without opening
VISA:

```powershell
uv run keysight-power sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run keysight-power sequence --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run keysight-power sequence --dry-run --json --model E3646A --file examples\sequence-readonly.yaml
```

Sequence YAML files are formally supported through the core package's PyYAML
runtime dependency. A small built-in parser remains as a fallback for minimal
environments.

Sequence documents also accept `{"action":"trigger-pulse","channel":1,
"pins":[1],"polarity":"positive","leave_trigger_configured":false}`. The
default restores trigger and rear-pin configuration after the pulse.
`leave_trigger_configured` controls only that restore; it does not keep the
pulse trigger armed, and enabling it may affect later steps or other BUS triggers.

Ramp List examples:

```powershell
uv run keysight-power ramp-list --lint --json --file example.ramp-list.json
uv run keysight-power ramp-list --dry-run --json --model E36312A --file example.ramp-list.json
uv run keysight-power ramp-list --dry-run --json --model E3646A --file example.ramp-list.json
uv run keysight-power ramp-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

### Simulator Examples

Clear instrument status and the error queue on a simulated resource:

```powershell
uv run keysight-power clear --dry-run --json --resource "USB0::SIM::E36312A::INSTR"
```

Measure voltage and current on a simulated resource:

```powershell
uv run keysight-power measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
```

Capture a snapshot on a simulated resource with redacted resource details:

```powershell
uv run keysight-power snapshot --simulate --json --redact-resource --resource "USB0::SIM::E36312A::INSTR"
```

Preview output-affecting commands with no hardware writes:

```powershell
uv run keysight-power set --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --channel 1 --voltage 1 --current 0.05
uv run keysight-power output-on --dry-run --json --model E3646A --channel all
```

Run offline diagnostics, capabilities, and safety inspect checks:

```powershell
uv run keysight-power doctor --simulate --json
uv run keysight-power capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run keysight-power safety inspect --json --explain --safety-config examples\safety-config.toml --resource-alias sim-e36312a --channel 1
```

The early standalone examples provide the same passive discovery and identity
query behavior:

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
.\.venv\Scripts\python.exe examples\02_identify.py --resource "$env:KEYSIGHT_POWER_RESOURCE"
```

Add `--json` to supported CLI commands for the stable machine-readable v1
contract. Diagnostic logs such as `--log-scpi` remain on stderr so JSON stdout
stays parseable. Every JSON success and error envelope includes
`metadata.duration_ms`.

## Safety Defaults

- Output-affecting behavior must be explicit.
- Real output execution is validated for E36312A, E3646A, and EDU36311A `set`,
  `apply`, `output-on`, `output-off`, `output-state`, `cycle-output`,
  `safe-off`, `smoke-output`, and `ramp` on explicit supported channels.
  `apply`, `output-on`, `output-off`, `output-state`, `cycle-output`, and
  `safe-off` accept `--channel all` and expand to the model's supported
  channels in order. On E3646A, `OUTP ON/OFF` is global even when channel
  selection is used for setpoint writes and readbacks.
  `set`, `ramp`, and `smoke-output` remain single-channel commands.
  `output-on` does not set voltage or current.
- Real `measure-all`, `trigger-pulse`, `trigger-status`, `trigger-step`,
  `trigger-list`, `trigger-fire`, and `trigger-abort` are enabled only for
  E36312A. Trigger dry-run and simulator behavior is also E36312A-only.
  `status`, `readback`, `log`, `validate-readonly`, and protection commands
  are enabled for E36312A and EDU36311A.
- Real `clear`, `error`, and `measure` are safe I/O commands: `clear` sends
  `*CLS` and clears status/error state, while `error` and `measure` only query.
- `--safety-config` is explicit only and applies local plan validation limits;
  it does not enable real hardware output.
- E36312A and EDU36311A setpoints are also bounded by verified official
  independent-channel DC output ratings. Safety config may only lower them.
- Real VISA resources must not be hard-coded in committed files.
- Hardware tests must require a user-provided resource.
- Examples that enable output must set current limit before voltage and turn
  output off in cleanup.

## Status

Active package. Live E36312A validation covers read-only CLI flows,
output-safe setpoint flows, worker dry-run/read-only behavior, and native
trigger-list flows documented in the hardware test guide.
