# Power CLI JSONL Contract

This contract extends `common-cli-jsonl-contract.md` with Power command names and payload shapes.

## CLI Commands

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

Selected data mappings:

- `read-status`: `resource`, `errors`, `read_count`, and `outputs`.
- `readback`: `resource`, `idn_raw`, and `channels[].setpoints`.
- `measure`: selected channel measurements.
- `measure-all`: all E36312A channel measurements.
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
