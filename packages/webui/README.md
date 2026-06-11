# Keysight Power WebUI

FastAPI and static-asset WebUI adapter for Keysight Power.

The WebUI and CLI are parallel product interfaces over the shared Core
runtime.

- Package: `keysight-power-webui` `0.1.0`
- Import package: `keysight_power_webui`
- Runtime dependency: `keysight-power-core`
- Frontend: static `index.html`, `styles.css`, and `app.js`; no Node toolchain

## Run

From the repository root:

```powershell
uv run python -m keysight_power_webui.server --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

## API

- `GET /api/health`: server and hardware-lock state.
- `GET /api/commands`: command metadata, confirmation flags, and disabled
  WebUI-only limitations.
- `POST /api/jobs`: submit a command job with `command`, `runtime`,
  `parameters`, and optional `artifacts`.
- `GET /api/jobs/{job_id}`: read current job state.
- `POST /api/jobs/{job_id}/cancel`: request cancellation.
- `GET /api/events?job_id=...`: job SSE stream with `id`, `event`, and `data`.
- `POST /api/live`: start live read-only polling.
- `GET /api/live/{job_id}/events`: live-data SSE stream.
- `POST /api/live/{job_id}/stop`: stop live-data polling.

## Runtime Boundary

The WebUI does not import `keysight_power_cli` and does not perform direct
VISA or SCPI operations. It maps HTTP payloads to core `RuntimeOptions` and
request objects, then calls `keysight_power_core.command_runner`.

Real hardware jobs are serialized by a single hardware lock. Simulate,
dry-run, offline metadata commands, and live-data jobs do not occupy that lock.
Synchronous core execution runs in a worker thread so FastAPI's event loop
continues serving health, job status, cancellation, and SSE endpoints.

Cancelling an executing job first moves it to non-terminal
`cancel_requested`. The WebUI keeps `active_job_id` and the hardware lock until
the current thread I/O and Core stop cleanup finish. Only then does the job
become `cancelled`; cleanup failure makes it `failed`. Accepted jobs that have
not started can become `cancelled` immediately.

## UI

The static UI is a three-panel dashboard:

- top connection bar for mode, resource, backend, timeout, safety config, and
  health;
- left command rail populated from `/api/commands`;
- main generated command form with typed controls and a graphical Sequence
  step-card editor;
- right panel for live trend canvas, live table, job history, and result JSON.

Machine-facing command IDs remain kebab-case. Human-facing WebUI command names
use spaces and sentence case.

The frontend keeps one job SSE controller and one live-data SSE controller.
Ramp List uses a dedicated segment-card editor with versioned JSON Load/Save,
up to 10 ordered segments, and full-list trip guarding before submission.
Sequence uses collapsed step cards with JSON Load/Save and supports up to 250
steps in the WebUI. Loaded Sequence JSON is normalized to the canonical
`{"version": 1, "steps": [...]}` shape before saving or running. CLI and Core
Sequence YAML/JSON support is unchanged and has no WebUI step limit.
Job Result history is expanded by default and can be collapsed or cleared
without changing Result Detail.

Cycle Output exposes an optional finished pulse. Ramp exposes mutually
exclusive Segment complete and Every-step pulse controls; Every-step requires
Delay(ms) greater than 5000. Ramp List Load/Save preserves its global pulse
configuration, and Sequence includes a Trigger pulse action. Pulse rear pins
are independent of output channels and are E36312A-only. Controls are disabled
when the selected resource is known to be another model.
Pulse detail fields in Cycle Output and Ramp appear only after a pulse option
is enabled. Rear-pin fields use a selector for every valid pin combination,
including All. Ramp List disables Every-step pulse when any segment delay is
5000 ms or less and points users to the built-in Segment complete pulse, which
supports those shorter delays.
Live Data samples include parsed model identity and channel-local OVP/OCP trip
state. A valid Live Data model can repair the selected resource's command
support cache; results without a model do not replace an already known model.

Fresh, explicit channel trip state adds a WebUI soft guard for direct output
commands targeting that channel. Stale or unknown trip state does not add a
guard. Safe/off and recovery commands remain available.

Commands are grouped into Output, Output Workflows, Protection, Trigger,
Snapshot, and Advanced Diagnostics. Clear Protection is under Protection and
still requires explicit confirmation. A tripped channel card can open and
prefill the form without executing it. Clear Status / Errors is separate and
does not clear OVP/OCP protection latches.

Advanced Diagnostics exposes Clear Status / Errors, Get capabilities, Read
device information, and Read errors. The Workspace keeps the latest successful
result for each command and resource, while Result Detail keeps the complete
raw job payload. Read errors removes each returned entry from the instrument
error queue.

## Limits

CLI-only or not-yet-shared commands are marked disabled by `/api/commands` and
return `not_implemented_in_webui` if submitted directly. No hardware tests are
run from this package by default.

## Test

```powershell
uv run python -m pytest packages/webui/tests -q -p no:cacheprovider
```
