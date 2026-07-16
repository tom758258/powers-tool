# Power CLI JSONL Contract

This contract extends `common-cli-jsonl-contract.md` with Power command names and payload shapes.

Numeric command fields follow the shared
[Commands parameter contract](commands-parameter-contract.md).

## CLI Commands

The installed Python distribution is `powers-tool`. CLI JSON payloads use
the V2 adapter identifier `powers-tool-cli`, while the reported version is
sourced from the single distribution.

Lifecycle clients:

- `send-command`
- `status`
- `stop`
- `wait-ready`

Instrument/domain commands include:

- `identify`
- `read-status`
- `readback`
- `measure`
- `measure-all`
- `output-state`
- `protection-status`
- `error`
- `snapshot`
- `set`
- `apply`
- `output-on`
- `output-off`
- `safe-off`
- `cycle-output`
- `ramp`
- `ramp-list`
- `smoke-output`
- `protection-set`
- `clear-protection`
- `restore-from-snapshot`
- `sequence`
- `trigger-pulse`
- `trigger-status`
- `trigger-step`
- `trigger-list`
- `trigger-fire`
- `trigger-abort`

This list defines accepted command names and payload envelopes. It does not
mean every command is product-open for real hardware. Model-aware LIVE
execution resolves detected manufacturer plus model to canonical `model_id`.
The exact Core policy key is `model_id + command + transport + backend +
required feature`; missing or pending scopes fail closed.
Dry-run/simulator availability also does not imply product LIVE support. The
five explicit diagnostics are `list-resources`, `verify`, `identify`,
`error`, and `clear`; their success does not promote another command.

The former instrument `status` command is `read-status`. `powers-tool status` is reserved for Worker `GET /status`.

## Runtime JSONL

`powers-tool worker` writes runtime JSONL to stdout by default. No
`--json`, `--jsonl`, or format flag is required for orchestrators to parse the
Worker stream. Every non-empty stdout line from the Worker is a JSON object
line. Human-readable diagnostics, warnings, and logging must be written to
stderr so stdout remains directly parseable as JSONL.

Power CLI JSON success/error envelopes and Worker runtime JSONL events use
integer `schema_version: 2` and include
`timestamp_utc`. The runtime event names are:

- `ready`
- `status`
- `message`
- `error`
- `summary`
- `dry_run`
- `power_cleanup`

Each non-dry-run Worker session creates one `run_id`. Runtime events,
`GET /status`, accepted job status, and job result artifacts use that same
`run_id`. Dry-run output that does not create a runtime session omits
`run_id`.

The Worker emits `ready` only after `POST /command`, `GET /status`, and
`POST /stop` can accept requests. `ready` contains `schema_version: 2`,
`timestamp_utc`, `run_id`, `service`, `host`, `port`, `command_url`,
`status_url`, and `stop_url`. It never contains `trigger_url`.

Normal Worker shutdown emits a final `summary`. Fatal failure emits
`summary.ok: false`, includes `fatal_error`, and exits `3`. A missing final
summary is incomplete.

`power_cleanup` is Power-specific and contains a `cleanup` object with
`operation`, `status`, and `message`. Cleanup status is one of `succeeded`,
`unsupported`, `not_applicable`, or `failed`. The final `summary` is emitted
only after runner completion, stop cleanup, and HTTP server shutdown.

## Lifecycle Clients

`send-command --command` is required. `--arguments-json` defaults to `{}`. `--job-id` is omitted by default. `--timeout-ms` defaults to `3000` and accepts `100..600000`. `--json` aliases `--format json`; conflicting format options exit `2`.

Exit mapping:

- Accepted HTTP command submission or successful lifecycle client operation: `0`.
- Local validation or Worker HTTP `400`: `2`.
- Worker `409`/`429`, connection errors, invalid response bodies, and wait timeouts: `3`.

`send-command --dry-run` validates and prints the request without sending
HTTP. `status --dry-run` also does not send HTTP. `wait-ready` polls
`GET /status`; readiness means only that the Worker endpoint is reachable and
ready, not that a submitted job has completed. `stop` uses `POST /stop` for
cooperative cleanup and does not enter the domain job queue.

`send-command --json` merges the Worker response with client diagnostics:
`client_command`, `method`, `url`, `endpoint`, `timeout_ms`, `elapsed_ms`,
`request_sent`, `reachable`, `http_status`, `error_phase`, and `ok`. On
failures it also includes `exit_code`. For accepted command responses, `ok`
means the request was accepted; it does not mean job execution succeeded.

## Result Payloads

Power command success envelopes follow the common CLI contract. Command names use the public names above, including `read-status`.

Runtime identity fields:

- CLI `--model` maps to `planning_model_id` in dry-run/simulator mode and to
  `expected_model_id` in live mode. Values are canonical vendor-qualified
  physical IDs such as `keysight-e36312a`.
- CLI `--profile generic-scpi` maps to `planning_profile_id` and is dry-run
  only. It is exposed only where Generic planning is already supported.
- WebUI and Worker raw payloads use `planning_model_id`, `expected_model_id`,
  and `planning_profile_id`. No legacy runtime identity aliases are accepted.
- Physical planning identity is used for dry-run/simulator planning, channel
  validation, and `channel: "all"` expansion. Fake or live-looking resources such as
  `USB0::FAKE::E36312A::INSTR` do not imply a model. Deterministic SIM
  resources such as `USB0::SIM::E36312A::INSTR` may infer the matching model
  because they map to known simulator IDN/model data.
- Live hardware uses the manufacturer-plus-model resolved identity. `--model`
  becomes an expected-model guard in live mode: after `*IDN?`, Core requires
  canonical model IDs to match before setup/write SCPI. The guard never overrides
  the IDN-detected driver.

Selected data mappings:

- Dry-run and simulator plan payloads for output-family commands, `ramp-list`,
  `sequence`, `protection-set`, `clear-protection`, and trigger workflows
  identify `planning_model_id` and `planning_profile_id` separately. Physical
  planning identity is used for channel validation and `channel: "all"`
  expansion. Trigger no-hardware plans accept only `keysight-e36312a`; unsupported
  models do not expose trigger dry-run or simulator behavior.
- `read-status`: `resource`, `errors`, `read_count`, and `outputs`.
- `readback`: `resource`, `idn_raw`, and `channels[].setpoints`.
- `measure`: selected channel measurements.
- `measure-all`: all supported channel measurements. Non-dry-run results,
  including simulator execution, also contain `data.idn` derived from the
  observed Core `idn_raw`. This sanitized object contains only `manufacturer`,
  `model`, `serial`, `firmware`, and `parse_ok`; it never contains the raw IDN
  string. Dry-run plans do not contain observed identity.
- `set`: request arguments contain `channel` plus `voltage`, `current`, or
  both. Omitted setpoints are left unchanged, not defaulted. Successful results
  include `updated_setpoints` with only the setpoints actually written; full
  set requests also keep the existing top-level `voltage` and `current` fields.
- `output-state`: single-channel responses contain `channel` and the exact
  boolean `output_enabled`; they do not contain `output` or `outputs`.
  All-channel responses contain `channel: "all"` and a non-empty `outputs[]`
  whose entries contain `channel` and exact boolean `enabled`; they do not
  contain `output` or top-level `output_enabled`.
- Other output-family commands retain their existing payloads. In particular,
  `output-on`, `output-off`, and `cycle-output` single-channel responses keep
  the existing `channel` plus `output` shape. Their `channel: "all"` responses
  keep `channel: "all"` and add `outputs[]` entries keyed by `channel`.
  `cycle-output` enables all channels, waits once for `duration_ms`, then
  disables all channels.
- `protection-status`: aggregate protection flags calculated as the OR of the
  selected channels, true per-channel protection flags, and output state.
- `snapshot`: a `schema_version: 2`, `kind: "powers-tool-snapshot"` document
  with separate `reported_identity` and canonical `resolved_identity`, plus
  errors, outputs, readback, measurements, and protection settings.
  `--snapshot-json PATH` writes this raw document atomically and can be used
  without JSON stdout. `--json --save-json PATH` separately writes the full
  CLI schema-2 envelope; restore does not unwrap that envelope. If both options
  are used, their paths must differ. Resource redaction applies to the raw
  snapshot too, and restore never depends on the saved resource field.
- `sequence`: lint/plan/execution status, step results, and stop/failure details.
- `ramp-list`: version, segment count, completed segment count, ordered segment
  plans/results, and failed segment details when execution stops or fails.
- Ramp and Ramp List every-step pulse results use ordered `triggers` entries
  containing step index, voltage, and trigger result. Single completion pulses
  remain under `trigger`; Ramp List pulse results are stored per segment.
- Ramp always uses software setpoint writes and accepts
  `completion_pulse_pins`, `completion_pulse_polarity`,
  `completion_pulse_channel`, `leave_trigger_configured`, and
  `completion_pulse_timing`. Removed Native LIST/trigger-wait options are
  argparse errors. Completion pulse results report `native: false`.
- `restore-from-snapshot`: accepts only the schema-2 snapshot document,
  validates canonical model identity and serial before writes, and returns
  restored channels and the restore plan. Legacy and unversioned snapshots
  are rejected rather than converted. Restore-relevant booleans must be exact
  JSON booleans, channels must be unique positive integers, and setpoints must
  be finite numbers; no persisted value is interpreted by truthiness.
- `trigger-list`: selected channel, step count, completion state, and
  `restored`; `restored: true` means the pre-run Trigger configuration and LIST
  table were written back after completion.
- `trigger-pulse`: selected channel, pins, polarity, triggered setpoints, and
  `restored`; `restored: true` means all three channels' pre-run Trigger/LIST
  state plus the rear digital pin and BUS trigger-output state were restored.
  It does not mean output channels were turned off.
- Failed post-admission `trigger-fire` execution envelopes that reach the
  fire/abort path include `data.trigger` with the observed `fired` and
  `completed` state plus `abort_attempted`, `abort_succeeded`, and
  `abort_errors`. Abort is best effort; an abort failure is diagnostic and does
  not replace the original trigger failure. Validation, argument, connection,
  and admission failures do not guarantee `data.trigger`.
- Live trigger behavior remains IDN-driven. Live `--model` is an
  expected-model guard and does not override connected hardware.
