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
| E3646A | RS-232 / ASRL | yes | yes | read-only | Model support is limited to identity, measurement, readback, read-status, output-state, and capabilities. `verify` remains available as a model-independent connection diagnostic. Serial settings are applied only when explicitly provided. |

EDU36311A USB read-only, output/write, and protection commands are enabled for
real execution after staged validation. The live wrapper defaults to no-DUT
low-power output validation; run `scripts/live-smoke-validation-check.ps1
-Target EDU36311A -Connection USB -Resource ... -Profile readonly` only for
legacy read-only validation. EDU36311A `protection-set` and
`clear-protection` require `--confirm` for real execution and report
`hardware_validation=validated`.

EDU36311A trigger/LIST remains intentionally bounded. `trigger-step`,
`trigger-fire`, and `trigger-abort` are simulator/dry-run planning paths with
`hardware_validation=planning_only`; real EDU36311A trigger execution is
disabled. `trigger-list`, `trigger-pulse`, and completion-pulse pins are
reported as `not_supported_by_model`.

## Command Support Notes

`capabilities --json` includes a `command_support` map, and
`capabilities --command COMMAND --json` also returns `data.selected_command`
for one map entry. The matrix above must stay consistent with these
command-level facts:

- E36312A USB-local has validated real read-only, output, protection, trigger,
  snapshot, and restore paths.
- E36312A native trigger/LIST support is exposed through `trigger-status`,
  `trigger-step`, `trigger-list`, `trigger-fire`, and `trigger-abort`.
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
- EDU36311A real trigger commands remain disabled. `capabilities --json`
  reports STEP trigger planning as `hardware_validation=planning_only` and
  native LIST as `not_supported_by_model`.
- E3646A RS-232 support is read-only/status only. The model-supported command
  set is `identify`, `measure`, `readback`, `read-status`, `output-state`,
  and `capabilities`. `verify` is a model-independent connection diagnostic
  that opens the selected resource and queries `*IDN?`; it is not part of the
  model capability matrix. E3646A uses `INST:NSEL` channel preselection for
  channels 1 and 2 and does not enable setpoint writes, protection changes,
  trigger workflows, snapshot, restore, ramp, sequence output steps, or
  output-on/off commands.
- E3646A serial settings are explicit only. If no serial options are provided,
  the program does not overwrite VISA backend, Keysight IO Libraries Suite, or
  Connection Expert serial settings. The factory example is 9600 baud, 8 data
  bits, none parity, 2 stop bits, and DTR/DSR handshake, but the actual
  front-panel settings may differ and are not auto-applied.
- E3646A `SYST:REM` and `SYST:LOC` are state-changing remote/local commands.
  They are sent only when `--serial-remote` or `--serial-local-on-close` is
  explicitly requested for an ASRL resource.
- `snapshot-diff`, `snapshot-diff --summary`, `hardware-report`, and
  `sequence --lint` are offline/no-hardware tools and never open VISA.

