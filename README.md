# Keysight Power

Safe Python tooling for Keysight DC power supplies, starting with a CLI and a
driver layer for E36xxx-family instruments.

The project is in early implementation phase. Default tests must run without
hardware, and any command or test that can affect a real instrument output must
remain explicit and opt-in.

E36312A and EDU36311A now have model-specific driver foundations selected from
valid `*IDN?` responses. Their channel-list SCPI is covered by no-hardware
tests. Simulated CLI measurement supports channels 1, 2, and 3 for these
models. Real CLI measurement keeps generic instruments on channel 1, and
E36312A channels 2 and 3 use IDN-selected channel-list measurement queries.
Real CLI `set` is supported only for E36312A channels 1, 2, and 3. It writes
the current limit before voltage and does not enable output. Real CLI
`output-on` is also supported only for E36312A channels 1, 2, and 3; after
`*IDN?` it reads back `VOLT? (@N)` and `CURR? (@N)` before sending
`OUTP ON,(@N)`. With `--safety-config`, unsafe readback setpoints are rejected
before output is enabled.
Real CLI `output-off` is supported only for E36312A channels 1, 2, and 3.
Real CLI `output-state` reads back `OUTP? (@N)`. Real CLI `safe-off` now
supports E36312A channel `1`, `2`, `3`, or `all` and expands `all` to
channels `1`, `2`, and `3` in order. Real CLI `cycle-output` and `apply` are
also supported for E36312A channels 1, 2, and 3. Real CLI `measure-all`,
`status`, and `trigger-pulse` are E36312A-first commands for all-channel
measurement, error/output status, and rear digital trigger output pulses.
`validate-readonly` is a one-shot read-only diagnostic for E36312A and
EDU36311A.

`snapshot --compare PATH` compares the current E36312A snapshot with either a
saved JSON envelope or raw snapshot `data`. It ignores `resource` and
`read_count`, uses default tolerances of 0.001 V/A for programmed setpoints,
0.05 V measured voltage, and 0.01 A measured current, and exits `3` when
differences are found.

`ramp` is an E36312A setpoint-only command: it sets current limit first, then
steps voltage from `--start-voltage` to the exact `--stop-voltage`. It does not
turn output on or off. `set`, `apply`, `output-on`, `output-off`, and `ramp`
accept `--settle-ms` and `--verify-after-write`; verification failures return
JSON error code `verification_failed` and exit `3`.

## Development

From PowerShell, change into the project directory, create or reuse the local
virtual environment, install the package with development dependencies, then
run the default tests:

```powershell
cd path\to\Keysight_Power
```

```powershell
uv venv .venv
```

```powershell
uv pip install -e ".[dev]"
```

Use the Python executable inside `.venv` for project commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

On Windows, run the test command from an Administrator PowerShell if the normal
shell reports a permission or login-session error while launching Python.

GitHub Actions runs the same pytest suite on Windows with Python 3.10 and 3.12.

## Examples

List VISA resource strings reported by the selected backend:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli list-resources
```

This is passive discovery only: a resource string can appear here even when the
instrument is not currently reachable.

List only resources that can be opened and queried with `*IDN?`:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli list-resources --live-only
```

This opens each listed resource and sends `*IDN?`. Resources that cannot be
opened or do not respond to `*IDN?` are omitted. Add `--log-scpi` to show the
verification query and response for each live check.

Verify that one resource can be opened and queried with `*IDN?`:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli verify --resource "USB0::...::INSTR"
```

Add `--log-scpi` to print the SCPI command log for manual hardware checks:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli verify --resource "USB0::...::INSTR" --log-scpi
```

Clear instrument status and the error queue with `*CLS`:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli clear --resource "USB0::...::INSTR" --log-scpi
```

Use `--dry-run` to preview the `*CLS` command without opening VISA:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli clear --dry-run --json --resource "USB0::SIM::E36103B::INSTR"
```

Read the instrument error queue without changing output state:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli error --resource "USB0::...::INSTR" --max-reads 20 --log-scpi
```

Measure voltage and current for the generic real-mode path:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli measure --resource "USB0::...::INSTR" --channel 1 --log-scpi
```

Measure E36312A channels 2 and 3 with IDN-selected channel-list queries:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli measure --resource "USB0::...::INSTR" --channel 2 --log-scpi
```

Simulate first-target model measurement without hardware:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
```

Measure all E36312A channels:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli measure-all --json --resource "USB0::...::INSTR" --log-scpi
```

Read E36312A error queue and output states:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli status --json --resource "USB0::...::INSTR" --log-scpi
```

Run a full read-only validation pass on E36312A or EDU36311A:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli validate-readonly --json --resource "USB0::...::INSTR" --log-scpi --save-json logs\validate-readonly.json
```

Read programmed E36312A setpoints and protection state:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli readback --json --resource "USB0::...::INSTR" --log-scpi
.\.venv\Scripts\python.exe -m keysight_power.cli protection-status --json --resource "USB0::...::INSTR" --log-scpi
```

Capture an E36312A snapshot for hardware handoff:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli identify --json --resource "USB0::...::INSTR" --log-scpi
.\.venv\Scripts\python.exe -m keysight_power.cli snapshot --json --resource "USB0::...::INSTR" --log-scpi
```

Compare against a saved E36312A snapshot:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli snapshot --json --resource "USB0::...::INSTR" --compare logs\e36312a-baseline.json
```

Preview or confirm clearing E36312A output protection:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli clear-protection --dry-run --json --resource "USB0::...::INSTR" --all
.\.venv\Scripts\python.exe -m keysight_power.cli clear-protection --json --resource "USB0::...::INSTR" --all --confirm --log-scpi
```

Preview or confirm E36312A protection setup:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli protection-set --dry-run --json --resource "USB0::...::INSTR" --channel all --ovp-voltage 5 --ocp on
.\.venv\Scripts\python.exe -m keysight_power.cli protection-set --json --resource "USB0::...::INSTR" --channel all --ovp-voltage 5 --ocp on --confirm --log-scpi
```

Configure an E36312A rear digital pin as trigger output, arm one output
channel with a no-change STEP trigger sequence, and emit `*TRG`:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli trigger-pulse --json --resource "USB0::...::INSTR" --pin 1 --channel 1 --polarity positive --log-scpi
```

Use `--dry-run` to preview trigger-pulse SCPI without opening VISA. The final
`*TRG` may also trigger any already armed BUS-triggered instrument behavior.
Real execution checks `SYST:ERR?` after output-affecting writes and fails the
command if the instrument reports errors.

Add `--json` to supported CLI commands for the stable machine-readable v1
contract. The contract is documented in `docs/cli-json-contract.md`; diagnostic
logs such as `--log-scpi` remain on stderr so JSON stdout stays parseable.

Preview output-affecting commands with no hardware writes:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli set --dry-run --json --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

Set low E36312A setpoints without enabling output:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli set --json --resource "USB0::...::INSTR" --channel 1 --voltage 1 --current 0.05 --log-scpi
```

Real `set` first confirms the selected resource is an E36312A with `*IDN?`,
then sends `CURR <current>,(@N)` followed by `VOLT <voltage>,(@N)`. Channels
other than 1, 2, and 3 are rejected.

Enable an E36312A output only after setpoints are already safe:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli output-on --json --resource "USB0::...::INSTR" --channel 1 --log-scpi
```

Real `output-on` first confirms the selected resource is an E36312A with
`*IDN?`, reads programmed voltage/current setpoints, then sends
`OUTP ON,(@N)`. It does not change voltage or current setpoints.

Read back the enabled state for one E36312A channel:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli output-state --json --resource "USB0::...::INSTR" --channel 1 --log-scpi
```

Cycle output briefly on then off:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli cycle-output --json --resource "USB0::...::INSTR" --channel 1 --duration-ms 500 --log-scpi
```

Apply low setpoints and enable output:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli apply --json --resource "USB0::...::INSTR" --channel 1 --voltage 1 --current 0.05 --log-scpi
```

Apply the same setpoints to all E36312A channels, or skip output enable:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli apply --json --resource "USB0::...::INSTR" --channel all --voltage 1 --current 0.05 --log-scpi
.\.venv\Scripts\python.exe -m keysight_power.cli apply --json --resource "USB0::...::INSTR" --channel all --voltage 1 --current 0.05 --no-output --log-scpi
```

Ramp E36312A voltage setpoints without changing output state:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli ramp --json --resource "USB0::...::INSTR" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --settle-ms 200 --log-scpi
```

Add an explicit safety config to apply local global limits to output plans:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli set --dry-run --json --safety-config examples\safety-config.toml --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

The config is never auto-discovered from the current directory. It is used only
when `--safety-config PATH` is passed to `set`, `apply`, `output-on`,
`output-off`, or `safe-off`. `--resource-alias ALIAS` is mutually exclusive
with `--resource` and requires the explicit safety config path.

```toml
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]

[[resources]]
alias = "sim-e36103b"
resource = "USB0::SIM::E36103B::INSTR"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
```

Resource-specific fields override global `[safety]` fields one by one. A raw
`--resource` that matches a `[[resources]].resource` entry also receives that
entry's resource-specific limits; otherwise the global `[safety]` limits apply.

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli set --dry-run --json --safety-config examples\safety-config.toml --resource-alias sim-e36103b --channel 1 --voltage 1 --current 0.05
```

The early standalone examples provide the same passive discovery and identity
query behavior:

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
```

```powershell
.\.venv\Scripts\python.exe examples\02_identify.py --resource "USB0::..."
```

## Safety Defaults

- Output-affecting behavior must be explicit.
- Real output execution is enabled for E36312A `set`, `apply`, `output-on`,
  `output-off`, `output-state`, `cycle-output`, and `safe-off` on explicit
  channels 1, 2, or 3. `apply --channel all` and `safe-off --channel all`
  expand to channels 1, 2, and 3 in order. `set` does not enable output.
  `output-on` does not set voltage or current.
- Real `measure-all` and `trigger-pulse` are enabled only for E36312A in this
  first implementation. `status`, `readback`, `log`, and `validate-readonly`
  are read-only paths for E36312A and EDU36311A. `trigger-pulse` affects
  rear-panel digital trigger output state and supports `--dry-run`.
- Real `clear`, `error`, and `measure` are safe I/O commands: `clear` sends
  `*CLS` and clears status/error state, while `error` and `measure` only query.
- `--safety-config` is explicit only and applies local plan validation limits;
  it does not enable real hardware output.
- Real VISA resources must not be hard-coded in committed files.
- Hardware tests must require a user-provided resource.
- Examples that enable output must set current limit before voltage and turn
  output off in cleanup.

See `Agent.md`, `docs/project-plan.md`, and `docs/session-handoff.md` before
making implementation changes.
