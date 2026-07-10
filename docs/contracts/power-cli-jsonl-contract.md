# Power CLI JSONL Contract

This contract extends `common-cli-jsonl-contract.md` with Power command names and payload shapes.

Numeric command fields follow the shared
[Commands parameter contract](commands-parameter-contract.md).

## CLI Commands

The installed Python distribution is `keysight-powers`. CLI JSON payloads keep
the adapter identifier `keysight-power-cli` for compatibility, but the reported
version is sourced from the single `keysight-powers` distribution.

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
execution requires an exact detected-model, command, transport, and backend
scope in the Core support policy; missing or pending scopes fail closed.
Dry-run/simulator availability also does not imply product LIVE support. The
five explicit diagnostics are `list-resources`, `verify`, `identify`,
`error`, and `clear`; their success does not promote another command.

The former instrument `status` command is `read-status`. `keysight-power status` is reserved for Worker `GET /status`.

## Runtime JSONL

`keysight-power worker` writes runtime JSONL to stdout by default. No
`--json`, `--jsonl`, or format flag is required for orchestrators to parse the
Worker stream. Every non-empty stdout line from the Worker is a JSON object
line. Human-readable diagnostics, warnings, and logging must be written to
stderr so stdout remains directly parseable as JSONL.

Power runtime JSONL events use `schema_version: 1` and include
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
`POST /stop` can accept requests. `ready` contains `schema_version: 1`,
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

Runtime model fields:

- CLI `--model` maps to the Core no-hardware model profile for commands that
  support dry-run or simulator model planning. In live mode, it maps to the
  Core expected-model guard.
- WebUI and worker-style raw payloads use `runtime.model_profile` as the
  canonical model field. `runtime.model` is accepted only as a compatibility
  alias where the adapter explicitly supports it.
- `model_profile` is used for dry-run/simulate planning, channel validation,
  and `channel: "all"` expansion. Fake or live-looking resources such as
  `USB0::FAKE::E36312A::INSTR` do not imply a model. Deterministic SIM
  resources such as `USB0::SIM::E36312A::INSTR` may infer the matching model
  because they map to known simulator IDN/model data.
- Live hardware uses the IDN-detected model. `--model`/`model_profile` is an
  expected-model guard in live mode: after `*IDN?`, Core requires the detected
  model to match before setup/write SCPI. The selected model never overrides
  the IDN-detected driver.

Selected data mappings:

- Dry-run and simulator plan payloads for output-family commands, `ramp-list`,
  `sequence`, `protection-set`, `clear-protection`, and trigger workflows
  include `plan.target.model_profile`. The field is the canonical
  no-hardware model profile used for channel validation and `channel: "all"`
  expansion. Trigger no-hardware plans accept only `E36312A`; unsupported
  models do not expose trigger dry-run or simulator behavior.
- `read-status`: `resource`, `errors`, `read_count`, and `outputs`.
- `readback`: `resource`, `idn_raw`, and `channels[].setpoints`.
- `measure`: selected channel measurements.
- `measure-all`: all E36312A channel measurements.
- `set`: request arguments contain `channel` plus `voltage`, `current`, or
  both. Omitted setpoints are left unchanged, not defaulted. Successful results
  include `updated_setpoints` with only the setpoints actually written; full
  set requests also keep the existing top-level `voltage` and `current` fields.
- `output-on`, `output-off`, `output-state`, and `cycle-output`: single-channel
  responses keep the existing `channel` plus `output` shape. With
  `channel: "all"`, responses keep `channel: "all"` and add `outputs[]` entries
  keyed by `channel`. `cycle-output` enables all channels, waits once for
  `duration_ms`, then disables all channels.
- `protection-status`: aggregate protection flags calculated as the OR of the
  selected channels, true per-channel protection flags, and output state.
- `snapshot`: errors, outputs, readback, measurements, and protection settings.
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
- `restore-from-snapshot`: restored channels and restore plan.
- `trigger-list`: selected channel, step count, completion state, and
  `restored`; `restored: true` means the pre-run Trigger configuration and LIST
  table were written back after completion.
- Live trigger behavior remains IDN-driven. Live `--model` is an
  expected-model guard and does not override connected hardware.
