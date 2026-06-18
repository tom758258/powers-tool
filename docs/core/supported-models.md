# Supported Models

This document records manually maintained support decisions that are broader
than one CLI command. Command-level behavior is documented in
`../contracts/power-cli-jsonl-contract.md`.

## Smoke Validation Matrix

This table is the single manually maintained source of truth for the smoke
validation wrapper workflow.

| Target | Connection | dry-run | simulate | live | Notes |
| --- | --- | --- | --- | --- | --- |
| E36312A | USB-local | yes | yes | yes | Full output smoke is supported by `scripts/live-smoke-validation-check.ps1`; Phase 1-8 USB validation passed on 2026-05-22. |
| E36312A | LAN-network | yes | yes | yes | Full output smoke is allowed only with an explicit `-Resource`; no LAN scan is performed. |
| EDU36311A | USB-local or LAN-network | yes | yes | yes | Default live smoke is read-only. USB output profile is opt-in with `-Profile output` and uses 1 V / 0.05 A. LAN remains read-only pending a separate live pass. |

EDU36311A USB read-only, output/write, and protection commands are enabled for
real execution after staged validation. The live wrapper still defaults to the
read-only profile; run `scripts/live-smoke-validation-check.ps1 -Target
EDU36311A -Connection USB -Resource ... -Profile output` only for intentional
no-DUT low-power output validation. EDU36311A `protection-set` and
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
  remains read-only pending a separate live pass.
- E36312A and EDU36311A OVP/OCP trip status is queried per channel. Aggregate
  `protection-status` flags are the OR of the selected channel results.
- EDU36311A real trigger commands remain disabled. `capabilities --json`
  reports STEP trigger planning as `hardware_validation=planning_only` and
  native LIST as `not_supported_by_model`.
- `snapshot-diff`, `snapshot-diff --summary`, `hardware-report`, and
  `sequence --lint` are offline/no-hardware tools and never open VISA.

