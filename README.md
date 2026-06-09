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
`*IDN?` it sends only `OUTP ON,(@N)` and does not set voltage or current.

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
`*IDN?`, then sends only `OUTP ON,(@N)`. It does not query or change voltage or
current setpoints.

Add an explicit safety config to apply local global limits to output plans:

```powershell
.\.venv\Scripts\python.exe -m keysight_power.cli set --dry-run --json --safety-config examples\safety-config.toml --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

The config is never auto-discovered from the current directory. It is used only
when `--safety-config PATH` is passed to `set`, `output-on`, `output-off`, or
`safe-off`. `--resource-alias ALIAS` is mutually exclusive with `--resource`
and requires the explicit safety config path.

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
- Real output execution is disabled except for E36312A `set`, `output-on`, and
  `output-off` on explicit channels 1, 2, or 3. Real `set` does not enable
  output. Real `output-on` does not set voltage or current.
- `safe-off` remains disabled in real mode; use `--dry-run` or `--simulate`
  for planning.
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
