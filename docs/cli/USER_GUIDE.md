# Keysight Power CLI User Guide

This guide is for operators who receive the built CLI executable or an
already-installed `keysight-power` command to control supported Keysight DC
power supplies. It focuses on normal live workflows, resource selection, and
safe first checks. For developer setup, detailed command reference, and
automation details, see the [CLI README](README.md).

## Start The CLI

Open PowerShell in the folder that contains the CLI executable and check it:

```powershell
.\keysight-power.exe --version
```

Release folders may include a versioned executable name, such as:

```text
keysight-power-<version>.exe
```

Use that file name in the commands below if your release folder uses a
versioned executable. Developers or source-checkout users should use the
[CLI README](README.md) for virtual environment, module, validation, and build
commands.

For an already-installed command, replace `.\keysight-power.exe` with
`keysight-power`:

```powershell
keysight-power --version
```

## First Live Check

Use this flow when checking a new computer, VISA runtime, connection, or power
supply setup.

1. Confirm the instrument is safe to query and any connected DUT can tolerate
   the existing output state.
2. List only VISA resources that currently answer `*IDN?`:

```powershell
.\keysight-power.exe list-resources --live-only
```

3. Copy the exact resource string and set a session variable:

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
```

4. Run a read-only identity check:

```powershell
.\keysight-power.exe verify --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

5. Run a read-only measurement or status check before any output action:

```powershell
.\keysight-power.exe measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
.\keysight-power.exe read-status --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
```

Use an explicit resource string for live commands. Do not rely on a script or
unattended workflow to guess which instrument should be used.

## Resource Listing

For normal live use, prefer:

```powershell
.\keysight-power.exe list-resources --live-only
```

Plain `list-resources` is passive VISA discovery. It can show stale cached
resources after a device is disconnected or unavailable. `--live-only` opens
each discovered resource, queries `*IDN?`, and prints only resources that
answered.

Use `--verify` when diagnosing stale entries because it reports both live and
failed resources:

```powershell
.\keysight-power.exe list-resources --verify
```

Add `--json` when copying results into automation:

```powershell
.\keysight-power.exe list-resources --live-only --json
```

## Resource Variables

Use environment variables to simplify copying and running multiple commands in a session:

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
$env:KEYSIGHT_POWER_ASRL_RESOURCE = "ASRL1::INSTR"
```

Please note:
* `$env:KEYSIGHT_POWER_RESOURCE` is for generic live USB/LAN examples.
* `$env:KEYSIGHT_POWER_ASRL_RESOURCE` is for E3646A RS-232 / ASRL examples.
* These are documentation convenience variables, not hidden CLI defaults.
* Live commands still require an explicit `--resource` argument.

## E3646A RS-232 / ASRL

E3646A support over RS-232/ASRL includes read/status commands and experimental
output workflows. Output-affecting commands are implemented but pending live
hardware validation. Before any live E3646A output command, confirm the
physical setup has been checked and no DUT is connected.

Model-supported live commands are `identify`, `measure`, `readback`,
`read-status`, `output-state`, `capabilities`, `set`, `apply`, `output-on`,
`output-off`, `safe-off`, `cycle-output`, `smoke-output`, `ramp`,
`ramp-list`, and output-affecting `sequence` steps. `verify` is also
available as a model-independent connection diagnostic that opens the selected
resource and queries `*IDN?`. Protection writes, trigger workflows, snapshot
restore, completion pulses, and native LIST remain disabled for E3646A.

Set the ASRL resource once per PowerShell session:

```powershell
$env:KEYSIGHT_POWER_ASRL_RESOURCE = "ASRL1::INSTR"
```

Plain `list-resources` normally does not need serial settings:

```powershell
keysight-power list-resources
```

If Keysight IO Libraries Suite / Connection Expert already has the ASRL
resource configured, try a read-only check without overriding those settings:

```powershell
keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE"
```

To explicitly apply serial settings for one command, pass only the fields you
want to override. The E3646A factory example is 9600 baud, 8 data bits, none
parity, 2 stop bits, and DTR/DSR handshake, but the instrument front-panel
settings may have been changed:

```powershell
keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` sends `SYST:REM`. `--serial-local-on-close` best-effort
sends `SYST:LOC` during cleanup. These affect remote/local state and are sent
only when explicitly requested.

Useful read/status examples:

```powershell
keysight-power identify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-remote --serial-local-on-close
keysight-power readback --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
keysight-power measure --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
keysight-power output-state --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

For serial read/write termination in PowerShell, use aliases when possible:
`CR`, `LF`, `CRLF`, or `NONE`. `NONE`, omitted, or blank termination means do
not override the VISA setting.

## Read-Only Workflow

Use read-only commands first when validating an instrument:

```powershell
.\keysight-power.exe identify --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
.\keysight-power.exe readback --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
.\keysight-power.exe protection-status --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
.\keysight-power.exe validate-readonly --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
```

These commands query identity, programmed setpoints, measured values, status,
or protection state. They do not intentionally enable outputs.

## Output-Affecting Workflow

Output-affecting commands are explicit. Before using them, confirm the
instrument model, channel, DUT wiring, voltage, current limit, and protection
settings.

Set low setpoints without enabling output:

```powershell
.\keysight-power.exe set --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --current 0.05 --json --log-scpi
```

Read back the programmed state:

```powershell
.\keysight-power.exe readback --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
```

Enable output only after the setpoints are known safe. For E3646A, treat live
output as experimental until hardware validation is complete; confirm the
physical setup has been checked and no DUT is connected:

```powershell
.\keysight-power.exe output-on --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --json --log-scpi
```

Turn output off when the check is complete:

```powershell
.\keysight-power.exe output-off --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --json --log-scpi
```

For a short smoke action, keep voltage and current low and use the documented
bounded commands in the CLI README. Do not run output workflows unattended
against an unknown resource.

## Common Commands

| Command | Typical use |
| --- | --- |
| `list-resources --live-only` | Find resources that currently answer `*IDN?`. |
| `verify` | Confirm one explicit resource opens and responds. |
| `identify` | Read the model identity. |
| `measure` | Read voltage/current for one channel. |
| `read-status` | Read output status. |
| `readback` | Read programmed setpoints and measured values. |
| `protection-status` | Read protection state. |
| `validate-readonly` | Run a read-only diagnostic pass. |
| `set` | Set voltage/current without enabling output. |
| `output-on` / `output-off` | Explicitly enable or disable output. |
| `safe-off` | Turn output off using the supported safety path. |

## Common Problems

If `keysight-power.exe` is missing, confirm you are in the folder that contains
the CLI executable and use the actual filename from that folder.

If no live resources are found, check instrument power, USB/LAN cabling, VISA
driver visibility, and whether another program is holding the instrument.

If plain `list-resources` shows old entries, rerun with `--live-only` for the
normal operator path or `--verify` to diagnose stale VISA cache entries.

If a command refuses to run, read the validation message before retrying. The
CLI intentionally rejects unsupported models, channels, unsafe setpoints, and
missing confirmations before performing risky actions.

If JSON output is needed for logs or automation, add `--json`. Diagnostic SCPI
logs from `--log-scpi` are written separately so JSON stdout remains parseable.

## More CLI Documentation

- [CLI README](README.md): engineering setup, validation scripts, full command
  reference, JSON behavior, worker details, and maintainer notes.
- [Power CLI JSON / JSONL Contract](../contracts/power-cli-jsonl-contract.md):
  structured command-line output rules.
- [Power Worker Contract](../contracts/power-worker-contract.md): local worker
  REST, JSONL, and artifact contract.
- [Supported Models](../core/supported-models.md): model-specific support
  status and validation notes.
