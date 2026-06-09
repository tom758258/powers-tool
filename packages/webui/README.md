# Keysight Power WebUI

FastAPI and static-asset WebUI adapter for Keysight Power.

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

## UI

The static UI is a three-panel dashboard:

- top connection bar for mode, resource, backend, timeout, safety config, and
  health;
- left command rail populated from `/api/commands`;
- main generated command form with typed controls and sequence-document JSON input;
- right panel for live trend canvas, live table, job history, and result JSON.

The frontend keeps one job SSE controller and one live-data SSE controller.

## Limits

CLI-only or not-yet-shared commands are marked disabled by `/api/commands` and
return `not_implemented_in_webui` if submitted directly. No hardware tests are
run from this package by default.

## Test

```powershell
uv run python -m pytest packages/webui/tests -q -p no:cacheprovider
```
