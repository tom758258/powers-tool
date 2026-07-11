# Keysight Power WebUI User Guide

This guide is for operators who receive the built WebUI launcher and use it to
inspect and control supported Keysight DC power supplies. It avoids developer
details and focuses on normal local WebUI workflows. Developer setup, API
behavior, validation, and UI change boundaries are documented in the
[WebUI README](README.md) and [Web UI Change Rules](web-ui-change-rules.md).

## Start The WebUI

For normal use, double-click the WebUI launcher provided with the release or
local build:

```text
keysight-power-webui-launcher.exe
```

To confirm the launcher version from PowerShell:

```powershell
.\keysight-power-webui-launcher.exe --version
```

Release folders may include a versioned launcher name, such as:

```text
keysight-power-webui-launcher-<version>.exe
```

In the launcher window:

1. Keep `Use default port 7999` selected unless that port is already in use.
2. Click `Start`.
3. Wait for the browser to open. The launcher starts a local WebUI server on
   this computer and opens the browser page for you.
4. Click `Quit` in the launcher when you are done with the WebUI.

If port 7999 is already in use, clear `Use default port 7999`, enter an
available local port such as `8001`, then click `Start`.

If the browser does not open automatically, open this address manually:

```text
http://127.0.0.1:7999/
```

Developers or source-checkout users should use the [WebUI README](README.md)
for terminal commands, validation, API, and build details.

The WebUI runs on the same Windows computer that has access to the instrument.
It is a local tool, not a cloud service. Closing the browser tab does not
always stop the server; use `Quit` in the launcher or stop the terminal process
when you are done.

## Screen Overview

The page is an instrument control console. The main areas are:

- `VISA resource`: the explicit instrument address used by command jobs.
- `Live resource`: resources discovered by the Scan Device workflow.
- `Scan Device`: searches for live VISA resources and fills the selector.
- `Live Data`: read-only channel cards and state indicators.
- `Basic command`: per-channel Voltage, Current, Set, and output ON controls.
- `Show more commands`: opens the advanced command rail and generated form.
- `Job Result`: recent submitted jobs and their state.
- `Result Detail`: raw JSON details for the selected job.

Hardware-affecting jobs remain explicit and confirmed.

## First Use

Use this flow when checking a new computer, VISA runtime, connection, or power
supply setup.

1. Confirm the supply and connected DUT are safe to query.
2. Start the WebUI and open the local browser page.
3. Click `Scan Device`.
4. Select the intended live resource or copy it into `VISA resource`.
5. Start `Live Data` to confirm read-only communication and channel state.
6. Review model identity, output state, programmed setpoints, and protection
   state before running any output-affecting command.
7. Use Basic command or the advanced command rail only after the target channel
   and setpoints are known safe.

Do not guess a resource when more than one instrument may be connected.

## Resource Scanning

`Scan Device` runs the WebUI resource discovery job with live-resource filtering
enabled. It is intended to show resources that currently answer, not stale VISA
cache entries.

Selecting a resource copies it into the `VISA resource` input. You may also
type a known operator-provided VISA resource manually.

Device options include `Expected model`. Leave it on `Auto-detect` for normal
live use. Auto-detect uses the connected instrument IDN. When `Require
<model>` is selected, the WebUI uses it for frontend capability planning and
sends it as an expected-model guard: the connected `*IDN?` model must match
before setup or write SCPI, and the selection does not force that model's
driver. The Device / Resource summary shows the detected live model and
expected model selection separately, for example `live E3646A / Auto-detect`
or `live E3646A / Require E36312A`.

The normal model dropdown intentionally shows only active supported models:
E36312A, EDU36311A, and E3646A. Unsupported direct model submissions are still
rejected by the WebUI backend and Core. Auto-detect may still use detected
live model metadata when available, but frontend state never overrides the
Core IDN-selected live driver.

After a successful `Get capabilities` run for the selected real resource, the
Device / Resource summary also shows the detected transport/backend scope and
compact Product live-support counts. Changing the resource clears that exact
context until capabilities are read again. Changing `Expected model` updates
planning guidance only; it does not rewrite the detected model or connection
scope. The WebUI uses the normal Product policy and does not provide a backend
selector or validation mode.

If no live resource appears, check instrument power, cabling, VISA driver
visibility, and whether another program is holding the instrument.

## Live Data

`Live Data` is a read-only monitor. It reads the selected resource on an
interval, updates channel cards, and shows WebUI, command, and live monitor
state.

Use Live Data before output commands to confirm:

- the expected model answered;
- measured voltage/current look plausible;
- programmed setpoints are understood;
- output state is known;
- OVP/OCP trip state is visible when supported.

Live Data may refresh once after successful real hardware commands. It remains
read-only and should be treated as the source of displayed instrument state.

## Basic Commands

The Basic command panel is for common per-channel setpoint and output actions.

Voltage and Current fields are blankable. Blank fields are omitted and left
unchanged by Core. To set both, fill both fields and click `Set` for the
channel.

The ON controls reflect fresh Live Data when available. An unlit ON control
means OFF or unknown; it is not a confirmed OFF state unless Live Data is
fresh. Real output-affecting actions require confirmation.

Before enabling output:

1. Confirm the selected channel.
2. Set a safe current limit and voltage.
3. Confirm the values through Live Data or readback.
4. Enable output only when the connected DUT can tolerate the request.

## Advanced Commands

Use `Show more commands` for the command rail and generated command form.
Commands are grouped by purpose, such as Output, Output Workflows, Protection,
Trigger, Snapshot, and Advanced Diagnostics.

The form is generated from WebUI command metadata. Required fields must be
filled before Run. Disabled commands or controls indicate unsupported model,
mode, or WebUI scope.

Disabled-command explanations are intentional feature-lock guidance, not random
UI failures. Product LIVE support is exact by detected model, command,
transport, and backend. A read-only, output, protection, or trigger feature
family does not mean every command in that family is product-open; missing and
pending scopes fail closed. E3646A product LIVE remains ASRL / RS-232 + system
VISA only, and its software `ramp-list` and step-limited `sequence` are not
native LIST.

The command rail distinguishes `Live validated`, `Pending live validation`,
model-unsupported, missing exact scope, policy-exempt diagnostic, and
`Connection scope not evaluated` states. Pending commands remain visible but
disabled; pending means the instrument profile recognizes the command but the
exact connection/backend evidence is not Product-open. These browser states
are guidance only. Core repeats the exact policy check for every submitted
live job, including direct or stale API requests.

The WebUI is product-only. It does not offer a validation override, and raw
job submissions cannot use one to turn pending evidence into normal product
support.

Some editors support JSON Load/Save, including Sequence, Ramp List, and Trigger
List workspaces. Use these for repeatable workflows, and keep saved files free
of private lab resource strings unless they are intentionally local-only.

## Job Results

Submitted commands appear in `Job Result`. Select a job to inspect its state
and raw JSON in `Result Detail`.

Typical job states include accepted, started, progress, finished, failed,
cancel requested, and cancelled. A failed job should include a message in the
result payload.

The browser UI is live-oriented and does not provide general dry-run or
simulate controls. When submitting raw WebUI API jobs instead of using the
browser form, include `runtime.model_profile` for no-hardware
dry-run/simulate jobs that need a model-specific plan, or use a deterministic
SIM resource such as `USB0::SIM::E36312A::INSTR`. For live raw API jobs,
`runtime.model_profile` is an expected-model guard checked against `*IDN?`;
mismatch fails before setup or write SCPI. The browser learns live model
support from scan/job IDN metadata; fake resource strings do not imply a
model. Browser disabled or hidden state is not the safety boundary; direct
`/api/jobs` submissions are still rejected by the WebUI backend and Core when
the model, command, or mode is unsupported.

## Stop And Cancel

If a job has not started, cancel can finish quickly. If a real hardware job is
already executing, cancellation is cooperative: the WebUI requests cancellation
and waits for Core cleanup to finish.

Do not close the browser or kill the process to interrupt normal cleanup unless
there is an external safety reason. Cleanup and release/local behavior belong
to Core and may take time.

The launcher blocks `Quit` while a hardware command is active. Stop or cancel
the command in the browser first, then wait for cleanup before quitting the
launcher.

## Common Problems

### The page does not load

Confirm the server is still running and open:

```text
http://127.0.0.1:7999/
```

If the port is already in use, start the server on a different port and open
that URL.

### The launcher says the port is already in use

If another Keysight Power WebUI server is already running on that port, the
launcher opens it. If a different service owns the port, choose another port or
stop that service before starting the launcher.

### Scan Device finds nothing

Check that:

- the instrument is powered on;
- USB or LAN is connected;
- the VISA driver can see the instrument;
- no other program is holding the resource;
- the correct backend is available on this PC.

You can still type a known VISA resource manually.

### Run is blocked

Read the visible validation message and Result Detail. Common causes are a
missing resource, missing required command field, unsupported model, unsafe
setpoint, or missing confirmation for real output-affecting commands.
Selecting an expected model does not unlock disabled commands; it only plans
no-hardware requests or guards a live command against the connected `*IDN?`
model.

### Output buttons do not look current

Start or refresh Live Data. The WebUI avoids displaying stale output state as
fresh truth.

### A command appears busy

Real hardware commands are serialized by the WebUI hardware lock. Wait for the
current command and cleanup to finish, or cancel only when that is the intended
operator action.

### Live Data reports stale or error state

Check the resource, connection, and whether another command owns hardware I/O.
Live Data does not override real command execution.

## Operator Safety Notes

- Use read-only Live Data before output-affecting commands.
- Keep first live checks low voltage/current and explicit channel.
- Confirm current limit before enabling output.
- Treat `channel all` as a deliberate multi-channel action.
- Do not clear protection until the cause of the trip is understood.
- Treat trigger and LIST workflows as advanced operations.
- Stop or turn output off before disconnecting the DUT when practical.

## More WebUI Documentation

- [WebUI README](README.md): API behavior, validation, development setup, and
  maintainer boundaries.
- [Web UI Change Rules](web-ui-change-rules.md): developer and agent rules for
  UI changes.
