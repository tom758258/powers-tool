# Keysight Power WebUI

FastAPI and static-asset WebUI adapter for Keysight Power.

This README is the WebUI behavior, API, validation, and maintainer guide. For
normal operator workflows, use the [WebUI User Guide](USER_GUIDE.md). For
developer and agent UI-change boundaries, use the
[Web UI Change Rules](web-ui-change-rules.md).

The WebUI and CLI are parallel product interfaces over the shared Core
runtime.

The WebUI ships inside the single `keysight-powers` distribution while
preserving the `keysight_power_webui` import boundary. It depends on the
shared `powers_tool_core` runtime and the distribution's `webui` extra.
Its frontend is static `index.html`, `styles.css`, and `app.js`; no Node
toolchain is required.

## Package And Entry Point

The WebUI exposes the `keysight-power-webui` console command for the local
FastAPI server and the `keysight-power-webui-launcher` wrapper for the Windows
launcher.

## Purpose

The WebUI adapter provides a local FastAPI and browser interface around the
shared Core runtime in `powers_tool_core`.

The WebUI owns:

- Browser interface and static assets under `src/keysight_power_webui/static/`.
- FastAPI route shape in `src/keysight_power_webui/app.py`.
- Local Tkinter launcher behavior in `src/keysight_power_webui/launcher.py`.
- Browser-facing request and response serialization.
- Job submission, job state display, and SSE event presentation.
- Live Data display state derived from read-only Core operations.
- Resource scanning display and command metadata rendering.

Core owns:

- SCPI command generation and instrument I/O.
- Runtime request validation and dry-run planning.
- Output, protection, trigger, sequence, ramp, snapshot, and restore behavior.
- Safety limits and model capability decisions.
- Stop, cancellation, release/local, close, and cleanup behavior.

The WebUI must use Core public APIs instead of importing CLI adapter code or
reimplementing instrument behavior.

## Run

From the repository root:

```powershell
uv run python -m keysight_power_webui.server --host 127.0.0.1 --port 7999
```

Open `http://127.0.0.1:7999/`.

Keep the host as `127.0.0.1` unless there is a deliberate reason to expose the
server beyond the local machine.

The installed Windows GUI launcher wrapper is:

```powershell
.\.venv\Scripts\keysight-power-webui.exe --version
.\.venv\Scripts\keysight-power-webui-launcher.exe
```

The launcher defaults to `127.0.0.1:7999`, opens the browser after Start, and
keeps the window available so Quit can stop the local Uvicorn server. If the
selected port already hosts Keysight Power WebUI, the launcher opens that page
instead of starting a second server. If the port is used by another service,
startup is rejected. Quit is blocked while a hardware command is active; stop
or cancel the command in the browser first and wait for cleanup.

## API

- `GET /api/health`: server and hardware-lock state.
- `GET /api/commands`: command metadata, confirmation flags, WebUI-only
  limitations, and Core-derived model-level exact live-support summaries.
- `POST /api/jobs`: submit a command job with `command`, `runtime`,
  `parameters`, and optional `artifacts`.
- `GET /api/jobs/{job_id}`: read current job state.
- `POST /api/jobs/{job_id}/cancel`: request cancellation.
- `GET /api/events?job_id=...`: job SSE stream with `id`, `event`, and `data`.
- `POST /api/live`: start live read-only polling.
- `GET /api/live/{job_id}/events`: live-data SSE stream.
- `POST /api/live/{job_id}/stop`: stop live-data polling.

`/api/health` keeps the adapter identifier `keysight-power-webui` for the
`package` field, while `version` is sourced from the single installed
`keysight-powers` distribution.

## Runtime Boundary

The WebUI does not import `keysight_power_cli` and does not perform direct
VISA or SCPI operations. It maps HTTP payloads to core `RuntimeOptions` and
request objects, then calls `powers_tool_core.command_runner`.

Real hardware jobs are serialized by a single hardware lock. Simulate,
dry-run, offline metadata commands, and live-data jobs do not occupy that lock.
Synchronous core execution runs in a worker thread so FastAPI's event loop
continues serving health, job status, cancellation, and SSE endpoints.

Raw `/api/jobs` no-hardware payloads that need model-specific planning should
send `runtime.model_profile`. In dry-run/simulate mode, this is the
no-hardware model profile used for planning and channel validation. In live
mode, the same field is an expected-model guard: Core queries `*IDN?`, fails
before setup/write SCPI if the detected model differs, and never uses the
selected model to override the IDN-selected driver.

Dry-run example:

```json
{
  "command": "trigger-step",
  "runtime": {
    "resource": "USB0::FAKE::E36312A::INSTR",
    "dry_run": true,
    "simulate": false,
    "model_profile": "E36312A"
  },
  "parameters": {
    "channel": 1,
    "source": "bus",
    "fire": true
  }
}
```

`runtime.model_profile` is the canonical WebUI/API runtime field.
`runtime.model` is accepted as a simple compatibility alias. The WebUI does
not infer a dry-run/simulate model from fake or live-looking resource strings;
use `model_profile` or a deterministic SIM resource such as
`USB0::SIM::E36312A::INSTR`. WebUI live resource support is learned from
scan/job IDN metadata. The browser UI remains live-oriented and does not
provide general dry-run or simulate controls.

The browser and raw WebUI jobs always use the product support-policy mode.
Validation-policy runtime fields are rejected, not ignored. Frontend enabled
state is UX only: Core remains the final IDN-selected exact-scope authority,
and pending transport/backend scopes are not product-open.

Cancelling an executing job first moves it to non-terminal
`cancel_requested`. The WebUI keeps `active_job_id` and the hardware lock until
the current thread I/O and Core stop cleanup finish. Only then does the job
become `cancelled`; cleanup failure makes it `failed`. Accepted jobs that have
not started can become `cancelled` immediately.

## UI

The static UI is a three-panel dashboard:

- package-versioned title area and top connection bar for resource selection
  and health;
- Basic command panel for direct per-channel setpoint and output shortcuts;
- collapsible command rail populated from `/api/commands`;
- generated command form with typed controls and a graphical Sequence
  step-card editor, shown by the advanced command toggle;
- right panel for live trend canvas, live table, job history, and result JSON.

Machine-facing command IDs remain kebab-case. Human-facing WebUI command names
use spaces and sentence case.

The connection area includes advanced device options. `Expected model`
defaults to `Auto-detect`, which omits `runtime.model_profile`. Auto-detect
uses the connected instrument IDN for live operation. Selecting `Require
<model>` sends `runtime.model_profile` as a live expected-model guard and may
drive frontend command, channel, and rating planning when metadata exists. The
Device / Resource summary shows the detected live model separately from the
expected model selection, such as `live E3646A / Auto-detect` or `live E3646A /
Require E36312A`. A selected model never overrides the IDN-selected live
driver; Core remains the authority for live mismatch rejection before setup or
write SCPI.
The serial fields are optional; blank fields are omitted from the runtime
payload and do not override VISA backend or Connection Expert settings.
Read/write termination fields accept `CR`, `LF`, `CRLF`, and `NONE` aliases.
`NONE`, blank, or omitted termination means no termination override is applied.

The frontend command rail may hide or disable unsupported commands for
operator clarity, but this is UX only. Direct `/api/jobs` submissions still
pass through WebUI backend validation and Core support gates, so unsupported
model/command/mode combinations are rejected even when a caller bypasses the
browser controls.

The browser distinguishes profile support from exact Product-mode live
availability. Before a real resource has returned capabilities, commands keep
their model-planning behavior and show that the connection scope has not been
evaluated. A successful resource-backed `capabilities` result on an already
Product-open scope, or a successful real `identify` diagnostic, adds the
IDN-detected model, normalized transport/backend scope, and per-command exact
status. The diagnostic path reads identity under the expected-model guard but
does not open pending feature commands. Validated commands remain available;
pending or missing exact scopes are shown disabled with distinct reasons,
while identity/status diagnostics remain explicitly policy-exempt. Changing
the resource clears this exact context until capabilities or identity are read
for the new resource.

If a successful `identify` or `verify` diagnostic detects an unknown or
de-scoped model, the diagnostic result remains available but its support
projection is unevaluated and contains no command availability. That neutral
result clears stale exact context and does not enable Generic fallback; normal
model-aware live commands still fail closed. An expected-model mismatch still
fails the diagnostic before optional support metadata is attached.

The Device / Resource summary shows the detected model, expected-model guard,
transport/backend scope, and compact validated/pending/unavailable counts when
that exact context is known. Pending metadata appears only when the actual
runtime transport/backend matches a registered pending scope. WebUI remains
Product-only and the standard browser uses the default system-VISA backend; it
has no validation mode or VISA-backend selector. These displays and disabled
controls are UX; the Core post-IDN exact-scope gate remains authoritative.

The safe Core projection can also include additive `sequence_action` and
`trigger_source` inventories for an exact scope. These entries expose status
and Product availability only; they do not expose evidence or internal notes.
The projection contract is schema version 2: evaluated physical results use
canonical `model_id`, while unevaluated diagnostics keep reported manufacturer
and model separate from a nullable resolved `model_id`. The projection never
exposes evidence IDs, historical paths, checksums, or private evidence notes.
Because documents and trigger requests select features at run time, the
command rail remains command-level and does not globally disable a command
merely because another future feature is pending. Core validates the actual
normalized request features after IDN and before feature-specific SCPI.

The Product model selector contains Product-active models only. Candidate,
catalog-only, and de-scoped models are not browser runtime choices; there are
currently no candidates and this framework enables no new model. WebUI remains
Product-only and provides neither a candidate bootstrap control nor a backend
or validation selector.

Pure offline utilities are classified separately from identity/status
diagnostics. They do not represent Product-open live commands and are not
described as policy-exempt hardware diagnostics.

The `set` command accepts Voltage, Current, or both in Basic command and
Commands. Blank setpoint fields are omitted from the job payload and left
unchanged by Core; Live Data/readback remains the source for complete
instrument setpoint state.
Voltage is the output voltage setpoint, and Current is the output current
limit/current setting for E36312A, EDU36311A, and E3646A. `/api/commands`
includes official setpoint programming-range metadata for these active models.
E3646A metadata is range-dependent for LOW/P8V and HIGH/P20V; the current
WebUI does not add a range selector from that metadata. Browser constraints
and hints are UX only, and backend Core validation remains authoritative. The
metadata does not introduce hard decimal-place rejection or silent
rounding/truncation.
Basic output controls are lit-state ON buttons: an unlit ON control represents
OFF/unknown, and a lit ON control represents ON according to fresh Live Data.

The Live Data status row uses LED indicators for WebUI State, Command State,
and Live State. Command State reports whether the WebUI command path is free
to accept real hardware jobs; it reflects the WebUI hardware I/O lock, not an
instrument-internal state register. Live State remains tied to real Live Data
readback and one-shot post-command refreshes.

The frontend keeps one job SSE controller and one live-data SSE controller.
Ramp List uses a dedicated segment-card editor with versioned JSON Load/Save,
up to 10 ordered segments, and full-list trip guarding before submission.
Sequence uses collapsed step cards with JSON Load/Save and supports up to 250
steps in the WebUI. Loaded Sequence JSON is normalized to the canonical
`{"version": 1, "steps": [...]}` shape before saving or running. CLI and Core
Sequence YAML/JSON support is unchanged and has no WebUI step limit.
Job Result history is expanded by default and can be collapsed or cleared
without changing Result Detail.

### Pulse Workflows

Cycle Output exposes an optional finished pulse. Ramp exposes mutually
exclusive Segment complete and Every-step pulse controls. Ramp List Load/Save
preserves its global pulse configuration, and Sequence includes a Trigger pulse
action.

Pulse rear pins are independent of output channels and are E36312A-only.
Controls are disabled when the selected resource is known to be another model.
Pulse detail fields in Cycle Output and Ramp appear only after a pulse option
is enabled. Rear-pin fields use a selector for every valid pin combination,
including All. Ramp and Ramp List Every-step pulse accept a zero millisecond
additional delay.

Workflow completion pulses are software-scheduled post-action `*TRG` pulses,
not native LIST execution. They temporarily modify and restore trigger/rear-pin
settings, and global `*TRG` may affect other armed BUS behavior. Sequence
Trigger pulse `Leave configured` controls only whether those settings are
restored after the pulse; it does not keep the pulse trigger armed and may
affect later Sequence steps or other BUS triggers.

### Trigger Execution

Trigger Fire sends global `*TRG` to every armed BUS trigger. Its Abort target
channel is required only when Wait complete is enabled and is used only if the
instrument-wide completion wait times out or is interrupted.

For Trigger Step and Trigger List, Immediate starts when `INIT` is sent, so
Fire now is cleared and disabled. BUS Wait complete requires Fire now in the
same command. A LIST that starts without Wait complete requires Leave
configured; select Wait complete to restore after completion or Leave
configured for asynchronous execution.

### Trigger List Workspace

Trigger List uses a dedicated three-channel workspace editor. Each channel
keeps its own count and 1 to 100 step rows with Voltage, Current, Dwell, BOST,
and EOST. Run submits only the selected channel. Load/Save uses strict
`keysight-power-trigger-list-workspace` version 1 JSON and preserves all three
channel drafts plus shared controls. Enabled BOST/EOST rows require LIST
output pins.

When Wait complete is selected and Leave configured is off, completion writes
back the pre-run Trigger settings and LIST table. The running table may be
briefly visible before restore. Select Leave configured to retain the new
table and Trigger settings.
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

Commands outside the WebUI surface are marked disabled by `/api/commands` and
return `not_implemented_in_webui` if submitted directly. No hardware tests are
run from this package by default. Model feature-lock policy is also enforced
for direct `/api/jobs` submissions: EDU36311A trigger/native LIST and
snapshot/restore jobs, E3646A protection/trigger/native LIST/snapshot/restore
and completion-pulse jobs, and unsupported E3646A sequence step types are
rejected by the backend/Core boundary.

Live validation evidence is recorded by CLI suite artifacts, not created by
the browser selector. The WebUI only displays a safe Core projection of the
current policy; it does not expose evidence paths or promote status. Suite
names are evidence groupings and do not open every command in a feature
family. Core requires an exact canonical `model_id`, command, transport,
backend, and required-feature scope; missing and pending scopes fail closed.
The authoritative current
command list is the
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix).
WebUI hiding or disabling remains UX only; backend/Core rejection is still the
safety boundary for unsupported direct submissions.

The WebUI expected-model field is a safety guard and planning hint only. It
does not change the IDN-selected live driver or cause the browser to open a
different connection type. Current recorded opening status is connection-
scoped; only commands in the Core exact matrix are opened:

- E36312A USB + system VISA
- E36312A LAN + system VISA
- EDU36311A USB + system VISA
- EDU36311A LAN + system VISA
- E3646A ASRL / RS-232 + system VISA

Only exact commands in the Core product matrix are opened on those
connections. E3646A live validation remains restricted to ASRL / RS-232;
E3646A USB and LAN remain outside the current scope.

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | accepted exact commands | accepted exact commands | N/A |
| EDU36311A | accepted exact commands | accepted exact commands | N/A |
| E3646A | not current scope | not current scope | accepted exact commands |

E36312A `full` now includes `software-sequence` in addition to read-only,
output, protection, snapshot, and trigger-list suites. EDU36311A `full` now
includes `software-sequence` in addition to read-only, output, and protection
suites; EDU36311A trigger/native LIST and snapshot/restore remain disabled.
E3646A `full` remains `readonly`, `output`, and `software-sequence`; E3646A
`ramp-list` and `sequence` are software workflows, not native LIST, and
protection, trigger/native LIST, snapshot/restore, and completion-pulse remain
disabled.


## Test

```powershell
uv run python -m pytest tests/webui -q -p no:cacheprovider
```

Focused launcher and package validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\webui\test_launcher.py tests\webui\test_webui_import.py tests\core\test_distribution_metadata.py -q -p no:cacheprovider
```

After editing `src/keysight_power_webui/static/app.js`, also run:

```powershell
node --check src\keysight_power_webui\static\app.js
```

Broader no-hardware validation when practical:

```powershell
uv run python -m pytest tests -q -p no:cacheprovider
```

Build the optional local WebUI launcher exe with PyInstaller from an
environment that already has `keysight-powers` installed. PyInstaller is a
local release-build tool, not a WebUI runtime dependency, so install it into
the venv before rebuilding on a fresh machine:

```powershell
uv pip install pyinstaller --python .\.venv\Scripts\python.exe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_webui_exe.ps1
```

After building, confirm the launcher reports the package version:

```powershell
.\dist\keysight-power-webui-launcher.exe --version
```

Numeric field limits come from the shared
[Commands parameter contract](../contracts/commands-parameter-contract.md).
After a resource model is identified, the UI applies verified official
independent-channel DC output ratings and disables Run for known over-rating
requests. Unknown models do not receive invented limits; Core remains
authoritative.

## Documentation Map

- [WebUI User Guide](USER_GUIDE.md): operator-facing WebUI usage guide.
- [WebUI README](README.md): this WebUI behavior, API, validation, and
  maintainer guide.
- [Web UI Change Rules](web-ui-change-rules.md): maintainer and agent-facing
  rules for UI changes.
