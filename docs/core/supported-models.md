# Supported Models

This document records manually maintained support decisions that are broader
than one CLI command. Command-level behavior is documented in
`../contracts/power-cli-jsonl-contract.md`.

## Smoke Validation Matrix

This table is the single manually maintained source of truth for the smoke
validation wrapper workflow.

| Target | Connection | dry-run | simulate | live | Notes |
| --- | --- | --- | --- | --- | --- |
| E36312A | USB-local | yes | yes | yes | Full output smoke runs read-only checks, protection-status reads, and low-power CH1-CH3 output smoke through `scripts/live-smoke-validation-check.ps1`; Phase 1-8 USB validation passed on 2026-05-22. |
| E36312A | LAN-network | yes | yes | yes | Full output smoke is allowed only with an explicit `-Resource`; no LAN scan is performed. |
| EDU36311A | USB-local or LAN-network | yes | yes | yes | Default live smoke is low-power CH1-CH3 output smoke at 1 V / 0.05 A. The legacy read-only profile remains available with `-Profile readonly`. |
| E3646A | RS-232 / ASRL | yes | yes | yes | Identity, measurement, readback, read-status, output-state, capabilities, and RS-232 / ASRL output workflows are live validated. `verify` remains available as a model-independent connection diagnostic. Serial settings are applied only when explicitly provided. |

EDU36311A USB read-only, output/write, and protection commands are enabled for
real execution after staged validation. The live wrapper defaults to no-DUT
low-power output validation; run `scripts/live-smoke-validation-check.ps1
-Target EDU36311A -Connection USB -Resource ... -Profile readonly` only for
legacy read-only validation. EDU36311A `protection-set` and
`clear-protection` require `--confirm` for real execution and report
`hardware_validation=validated`.

Trigger workflows are E36312A-only. EDU36311A, E3646A, E36103B, E36232A, and
GENERIC do not expose trigger dry-run or simulator behavior; their trigger
commands report `real=false`, `simulate=false`, and `dry_run=false`.

## No-Hardware Model-Profile Matrix

Dry-run and simulate planning do not open real VISA hardware. Model-specific
no-hardware commands require an explicit model profile or a known
deterministic SIM resource. Fake or live-looking resource strings are
placeholders and must not imply a model.

| Model profile | Deterministic SIM resource | No-hardware channels | Output control scope | Trigger / LIST / protection notes |
| --- | --- | --- | --- | --- |
| E36312A | `USB0::SIM::E36312A::INSTR` | CH1, CH2, CH3 | Per-channel output control; `all` expands to CH1-CH3 | Trigger workflows and native LIST are E36312A-only and validated for live E36312A paths. Protection read/write paths are supported. |
| EDU36311A | `USB0::SIM::EDU36311A::INSTR` | CH1, CH2, CH3 | Per-channel output control; `all` expands to CH1-CH3 | Protection read/write paths are supported. Trigger workflows and native LIST are not exposed in dry-run, simulate, or real mode. |
| E3646A | `ASRL1::SIM::E3646A::INSTR` | CH1, CH2 | Global output enable/disable; channel selection is used for setpoints and readback | RS-232 / ASRL output workflows are live validated. Protection writes, trigger workflows, snapshot restore, completion pulses, and native LIST are disabled. |
| E36103B | `USB0::SIM::E36103B::INSTR` | CH1 | Single-channel conservative no-hardware profile | Trigger workflows, native LIST, and protection writes are not exposed. |
| E36232A | `TCPIP0::SIM::E36232A::INSTR` | CH1 | Single-channel conservative no-hardware profile | Trigger workflows, native LIST, and protection writes are not exposed. |
| GENERIC | None; use explicit `--model GENERIC` / `model_profile="GENERIC"` | CH1 | Unknown | Conservative no-hardware planning only. Trigger workflows, native LIST, and protection writes are not exposed. |

Live hardware uses the IDN-detected model. `--model` and
`RuntimeOptions.model_profile` are for no-hardware dry-run/simulate planning
unless a future explicit expected-model guard is added.

## Command Support Notes

`capabilities --json` includes a `command_support` map, and
`capabilities --command COMMAND --json` also returns `data.selected_command`
for one map entry. The matrix above must stay consistent with these
command-level facts:

- E36312A USB-local has validated real read-only, output, protection, trigger,
  snapshot, and restore paths.
- E36312A native trigger/LIST support is exposed through `trigger-status`,
  `trigger-step`, `trigger-list`, `trigger-fire`, and `trigger-abort`. The
  trigger dry-run and simulator paths are also E36312A-only.
  Native LIST execution is limited to 100 steps, dwell values from 0.01 to
  3600 seconds, and count values from 1 to 256. Real native trigger sources
  are currently limited to BUS and immediate; rear pin and external input
  sources remain dry-run/simulator only until hardware validation.
- Ramp always uses software setpoint steps. Native LIST execution is confined
  to `trigger-list`.
- EDU36311A USB-local read-only/output/protection commands are enabled; LAN
  uses the same explicit-resource smoke wrapper and must be validated with the
  target instrument before acceptance.
- E36312A and EDU36311A OVP/OCP trip status is queried per channel. Aggregate
  `protection-status` flags are the OR of the selected channel results.
- EDU36311A trigger commands remain disabled. `capabilities --json` reports
  all trigger commands with `hardware_validation=not_supported_by_model` and
  does not expose trigger dry-run or simulator behavior.
- E3646A RS-232 support implements live-validated identity, measurement,
  readback, read-status, output-state, capabilities, and output workflows.
  The validated output commands are `set`, `apply`, `output-on`,
  `output-off`, `safe-off`, `cycle-output`, `smoke-output`, `ramp`,
  `ramp-list`, and output-affecting `sequence` steps. `apply`,
  `output-on`, `cycle-output`, and `smoke-output` report
  `hardware_validation=validated_confirm_threshold_conditional`; `set`,
  `output-off`, `safe-off`, `ramp`, `ramp-list`, and output-affecting
  `sequence` steps report `hardware_validation=validated`. Before any live
  E3646A output command, confirm the physical setup has been checked and the
  requested voltage/current limits are safe for the connected load.
  `verify` is a model-independent connection diagnostic that opens the
  selected resource and queries `*IDN?`; it is not part of the model
  capability matrix. E3646A uses `INST:NSEL` channel preselection for channels
  1 and 2 and does not use channel-list SCPI for output writes. E3646A
  `OUTP ON/OFF` is a global output enable/disable; channel selection is still
  used for setpoint writes and readbacks, but output enable/disable affects the
  instrument output state globally. Protection changes, trigger workflows,
  snapshot, restore, completion pulses, and native LIST remain disabled.
- E3646A serial settings are explicit only. If no serial options are provided,
  the program does not overwrite VISA backend, Keysight IO Libraries Suite, or
  Connection Expert serial settings. The factory example is 9600 baud, 8 data
  bits, none parity, 2 stop bits, and DTR/DSR handshake, but the actual
  front-panel settings may differ and are not auto-applied.
- E3646A `SYST:REM` and `SYST:LOC` are state-changing remote/local commands.
  They are sent only when `--serial-remote` or `--serial-local-on-close` is
  explicitly requested for an ASRL resource.
- No-hardware output-family, Ramp List, Sequence, `protection-set`,
  `clear-protection`, and trigger plans use a strict model profile.
  `--dry-run` and `--simulate` require either an explicit `--model` or a known
  deterministic SIM resource. Trigger no-hardware plans accept only
  `--model E36312A` or a known deterministic E36312A SIM resource such as
  `USB0::SIM::E36312A::INSTR`; an EDU36311A SIM resource is resolved and then
  rejected for trigger workflows. E3646A no-hardware `--channel all` plans
  expand to CH1 and CH2; CH3 is rejected.
- Live trigger behavior remains IDN-driven. `--model` is rejected for live
  commands before opening VISA and does not override connected hardware.
- `snapshot-diff`, `snapshot-diff --summary`, and `hardware-report` are
  offline/no-hardware tools and never open VISA. `sequence --lint` also
  validates without opening VISA and remains syntax/document validation unless
  combined with `--dry-run` or `--simulate`.
