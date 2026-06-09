# Power Worker Contract

This contract extends `common-worker-protocol.md` for Keysight Power.

## Endpoints

- `GET /status`: lifecycle status only. It is non-mutating and never opens VISA.
- `POST /command`: asynchronous Power command submission.
- `POST /stop`: priority cooperative stop request.

`/trigger`, `trigger_url`, `--default-action`, and default-action config are not supported.

## Power Stop Cleanup

`POST /stop` only sets stop state, wakes the background runner, and returns.
It performs no VISA I/O, cleanup, or HTTP-server shutdown in the handler.
The runner must finish command safety cleanup before the Worker stops the HTTP
server or emits the final `summary`.

Stop-only cleanup results use Power status values `succeeded`, `unsupported`,
`not_applicable`, and `failed`. Cleanup runs `release_to_local`, closes the
VISA session, then records `cleanup_release_to_local`; HTTP server shutdown
follows runner completion. `release_to_local` uses device-specific PyVISA GPIB
local control only when available. USB/LAN are `unsupported`; simulated or
unopened sessions are `not_applicable`. `cleanup_release_to_local` is
post-close bookkeeping and must not access the closed VISA session.

Each result is emitted as a structured `power_cleanup` JSONL event.
Unsupported cleanup is a warning. Any failed release, close, or post-cleanup
makes final `summary.ok` false and Worker exit code `3`.

## `POST /command`

The request body is a strict JSON object:

```json
{
  "command": "read-status",
  "arguments": { "channel": "all", "dry_run": true },
  "job_id": "optional-orchestrator-id"
}
```

Allowed top-level fields are `command`, `arguments`, and `job_id`. Unknown fields, malformed JSON, a non-object body, a missing/non-string command, non-object `arguments`, non-string `job_id`, unknown command names, and invalid Power arguments return `400` before any VISA I/O or queue mutation.

Every `/command` response is a JSON object with `status`, `command`, and
`job_id`. In the HTTP response, `command` is the submitted command string, for
example `"read-status"`.

- Accepted commands return `202` with `status: "accepted"`, `worker_job_id`, and `artifact_path`.
- Validation failures return `400` with `status: "error"`.
- Admission/safety rejections return `409` with `status: "rejected"` and one of the Power rejection reasons.

Power rejection reasons are `busy`, `run_not_ready`, `output_confirmation_required`, and `output_changes_not_allowed`.

`POST /command` HTTP `202` means only that the request was accepted and
enqueued. It does not mean the Power command has succeeded. Before returning
HTTP `202`, the Worker must create the job artifact directory and write
`request.json` successfully. If artifact initialization fails, the request
must not be reported as accepted.

`job_id` is the optional orchestrator ID from the request. It is echoed in
responses and runtime status but is not written into request/result artifacts
or measurement metadata. `worker_job_id` identifies the Worker artifact
directory and is the Worker job identity.

Power Worker job states are:

- `accepted`: the HTTP handler accepted the request.
- `queued`: the job artifact directory and `request.json` exist, and the job
  is waiting for the background runner.
- `running`: the background runner is executing the command.
- `succeeded`: terminal success.
- `failed`: terminal failure.
- `cancelled`: terminal cooperative stop/cancellation.

## `GET /status`

`GET /status` is non-mutating. It must not open VISA, execute a domain
command, mutate the queue, request stop, or create artifacts.

The response includes `schema_version`, `service`, `run_id`, Worker
`status`, `command_url`, `status_url`, `stop_url`, `queue_size`,
`active_job`, `last_job`, `fatal_error`, and `timestamp_utc`.

`active_job` and `last_job`, when present, include at least `worker_job_id`,
`job_id`, `command`, `status`, and `artifact_path`. Top-level `job_id` is not
used for domain job identity.

## Commands

Read-only/status:

- `identify`
- `read-status`
- `readback`
- `measure`
- `measure-all`
- `output-state`
- `protection-status`
- `error`
- `snapshot`

Output/setpoint:

- `set`
- `apply`
- `output-on`
- `output-off`
- `safe-off`
- `cycle-output`
- `ramp`
- `smoke-output`

Protection/restore/sequencing:

- `protection-set`
- `clear-protection`
- `restore-from-snapshot`
- `sequence`

Trigger:

- `trigger-pulse`
- `trigger-status`
- `trigger-step`
- `trigger-list`
- `trigger-fire`
- `trigger-abort`

## Arguments

Common `arguments` keys:

- `dry_run`: optional boolean, default `false`. When true, no VISA I/O is performed.
- `confirm_output`: optional boolean, default `false`. Required with Worker config `settings.allow_output_writes: true` for live non-dry-run output-affecting commands.

Command-specific fields match the CLI/core names, including `channel`,
`voltage`, `current`, `max_errors`, `max_reads`, `file`, `document`,
`snapshot`, `wait_timeout_ms`, `poll_ms`, protection options, snapshot
options, and sequence options. `channel` accepts a positive integer or `"all"`;
for output commands, `"all"` is supported by `apply`, `safe-off`,
`output-on`, `output-off`, `output-state`, and `cycle-output`. `set`, `ramp`,
and `smoke-output` remain single-channel commands.

## Safety

For live non-dry-run output-affecting Worker commands, both conditions are required before enqueueing:

- Worker config `settings.allow_output_writes: true`.
- Request `arguments.confirm_output: true`.

Rejected commands do not open VISA, enqueue work, write artifacts, or issue partial SCPI.

## Artifacts

Accepted jobs create:

- `request.json`: `command` and `arguments` only.
- `result.json`: final-only CLI-style result envelope with
  `schema_version: 1`, `run_id`, `worker_job_id`, `ok`, terminal `status`,
  `command`, `execution`, `request`, `data`, `warnings`, `error`, and
  `metadata`.

`artifact_path` is the job artifact directory, not the `result.json` path.
The final `result.json.command` field uses the existing CLI result command
object shape, for example `{"name": "read-status"}`. This differs from the
HTTP `/command` response, where `command` is the submitted command string.
`result.json` is written atomically only for terminal states. Pending/running
absence of `result.json` is not success. Failed and cancelled jobs also write a
terminal result artifact when the artifact directory is writable.

Terminal artifact `status` is one of `succeeded`, `failed`, or `cancelled`.
`ok` is `true` only for `succeeded`.
