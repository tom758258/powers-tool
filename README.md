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

List visible VISA resources:

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
```

Query instrument identity. This does not enable output:

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
