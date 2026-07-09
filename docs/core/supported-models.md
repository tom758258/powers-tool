# Supported Models

This document records manually maintained support decisions that are broader
than one CLI command. Command-level behavior is documented in
`../contracts/power-cli-jsonl-contract.md`.

## Live Suite Validation Matrix

This table is the manually maintained source of truth for suite-based live
validation records. For each active model, `-Suite full` is the complete
validation gate for all currently project-supported LIVE features of that
model. After the expanded full suite passes for the approved model and
connection, the model's currently project-supported LIVE features may be
opened. Disabled, unimplemented, out-of-scope, or factory-only features are
not implied by the pass. A passed `scripts/live-cli-check.ps1` run validates
only the selected target model, connection, suite, and cases in that run's
`.tmp_tests` artifacts. It does not validate unsupported suites, skipped
features, other connection types, every factory instrument function, or the
whole model.

| Target | Connection | Supported suites in `full` | Notes |
| --- | --- | --- | --- |
| E36312A | USB-local or LAN-network | `readonly`, `output`, `protection`, `snapshot`, `trigger-list`, `software-sequence` | Trigger/native LIST and snapshot/restore are considered suite validated only when the corresponding suite/cases pass for the selected connection. `software-sequence` covers project-supported software `ramp-list` and sequence workflows only. |
| EDU36311A | USB-local or LAN-network | `readonly`, `output`, `protection`, `software-sequence` | `software-sequence` covers project-supported software `ramp-list` and sequence read-only/output workflows only. Trigger/native LIST, snapshot, and restore-from-snapshot remain disabled in live, simulate, and dry-run. |
| E3646A | RS-232 / ASRL | `readonly`, `output`, `software-sequence` | CH1/CH2 only. `OUTP ON/OFF` is global. `ramp-list` and `sequence` are software workflows, not native LIST. |

Previous live artifacts for E36312A and EDU36311A passed before
`software-sequence` was added to their `full` suites. After this change, those
previous artifacts do not prove the expanded full suite. The expanded full
suites must be rerun before claiming those models' currently
project-supported LIVE features are fully validated and may be opened.

EDU36311A USB read-only, output/write, and protection commands are enabled for
real execution after staged validation. Use `scripts/live-cli-check.ps1
-Target EDU36311A -Connection USB -Resource ... -Suite full` for current
suite validation. The full suite now includes `software-sequence` for
project-supported software `ramp-list` and sequence read-only/output
workflows. The legacy smoke wrapper remains available for bounded smoke
checks only. EDU36311A `protection-set` and
`clear-protection` require `--confirm` for real execution and report
`hardware_validation=validated`.

Trigger workflows are E36312A-only. EDU36311A, E3646A, and GENERIC do not
expose trigger dry-run or simulator behavior; their trigger commands report
`real=false`, `simulate=false`, and `dry_run=false`.

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
| GENERIC | None; use explicit `--model GENERIC` / `model_profile="GENERIC"` | CH1 | Unknown | Conservative no-hardware planning only. Trigger workflows, native LIST, and protection writes are not exposed. |

Live hardware uses the IDN-detected model. In live mode, `--model` and
`RuntimeOptions.model_profile` are expected-model guards: Core queries
`*IDN?`, requires the detected model to match, and fails before setup/write
SCPI on mismatch. The selected model never overrides the IDN-selected driver.
`GENERIC` is a conservative no-hardware profile and is not a live expected
model.

E36103B and E36232A are not active supported models. They are rejected as
no-hardware model profiles, live expected-model guards, WebUI model selections,
`scripts/live-cli-check.ps1` targets, and live `*IDN?`-detected model-aware
operations. They must not fall back to `GenericScpiPowerSupply`. Additional
Keysight E36xxx / E36000-series models may be evaluated later after
programming-guide review, fake/simulator coverage, and real hardware
validation.

## Command Support Notes

`capabilities --json` includes a `command_support` map, and
`capabilities --command COMMAND --json` also returns `data.selected_command`
for one map entry. The matrix above must stay consistent with these
command-level facts:

- Unsupported model, command, and mode combinations fail intentionally. These
  feature-lock failures mean the workflow is not enabled for that model yet,
  not that `--model` or the WebUI selector can unlock it.
- CLI `--model` and WebUI `runtime.model_profile` are no-hardware planning
  profiles in dry-run/simulate mode. In live mode they are expected-model
  guards only: live driver selection always follows the connected `*IDN?`
  response. `GENERIC` is no-hardware only and is not accepted as a live
  expected model.
- E36312A USB-local full-suite validation covers project-supported read-only,
  output, protection, snapshot, trigger/native LIST, software `ramp-list`, and
  software `sequence` paths after the expanded full suite is rerun and passes.
- E36312A native trigger/LIST support is exposed through `trigger-status`,
  `trigger-step`, `trigger-list`, `trigger-fire`, and `trigger-abort`. The
  trigger dry-run and simulator paths are also E36312A-only.
  Native LIST execution is limited to 100 steps, dwell values from 0.01 to
  3600 seconds, and count values from 1 to 256. Real native trigger sources
  are currently limited to BUS and immediate; rear pin and external input
  sources remain dry-run/simulator only until hardware validation.
- Ramp always uses software setpoint steps. Native LIST execution is confined
  to `trigger-list`.
- EDU36311A USB-local read-only/output/protection commands plus software
  `ramp-list` and sequence read-only/output workflows are enabled after the
  expanded full suite is rerun and passes. LAN uses the same explicit-resource
  suite wrapper and must be validated with the target instrument before
  acceptance.
- E36312A and EDU36311A OVP/OCP trip status is queried per channel. Aggregate
  `protection-status` flags are the OR of the selected channel results.
- EDU36311A trigger commands remain disabled. `capabilities --json` reports
  all trigger commands with `hardware_validation=not_supported_by_model` and
  does not expose trigger dry-run or simulator behavior.
- EDU36311A snapshot and restore-from-snapshot are not enabled. They remain
  E36312A-only until separately implemented and hardware validated.
- EDU36311A `sequence` must not bypass disabled trigger/native LIST,
  snapshot, or restore workflows; unsupported sequence step types stay
  rejected in live, simulate, and dry-run paths.
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
  E3646A `ramp-list` is software setpoint stepping, and E3646A `sequence` is a
  software workflow limited to validated output/read-only steps. Neither is
  native instrument LIST support. E3646A sequence rejects unsupported step
  types such as protection, trigger, snapshot, restore, native LIST, and
  completion-pulse steps.
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
- Live trigger behavior remains IDN-driven. `--model` is a live
  expected-model guard and does not override connected hardware.
- `snapshot-diff`, `snapshot-diff --summary`, and `hardware-report` are
  offline/no-hardware tools and never open VISA. `sequence --lint` also
  validates without opening VISA and remains syntax/document validation unless
  combined with `--dry-run` or `--simulate`.
