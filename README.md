# Keysight Power

Safe Python tooling for Keysight DC power supplies, starting with a CLI and a
driver layer for E36xxx-family instruments.

The project is in early implementation phase. Default tests must run without
hardware, and any command or test that can affect a real instrument output must
remain explicit and opt-in.

## Development

Create or reuse the local virtual environment, then run the default tests:

```powershell
uv pip install -e ".[dev]"
```

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

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
- Real VISA resources must not be hard-coded in committed files.
- Hardware tests must require a user-provided resource.
- Examples that enable output must set current limit before voltage and turn
  output off in cleanup.

See `Agent.md`, `docs/project-plan.md`, and `docs/session-handoff.md` before
making implementation changes.
