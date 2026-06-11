# Agent Instructions

These instructions guide coding agents working in this repository. They are long-term working rules, not a project status log.

## 1. Primary Project Documents

- Read `docs/workspace.md`, `docs/release-checklist.md`, and the relevant package README before implementing features.
- Read the root contracts in `docs/contracts/` before changing adapter or worker behavior.
- Keep temporary AI planning notes out of committed public documentation.

## 2. Communication And Writing Rules

- Discuss with the user in Traditional Chinese.
- Write repository files in English unless the user explicitly requests otherwise.
- Keep code comments short and useful.
- Prefer clear public documentation and focused issue notes over long chat-only explanations.

## 3. Project Direction

- Build a Python package for Keysight DC power supplies.
- CLI and WebUI are parallel product interfaces over the shared Core runtime.
- Keep adapter behavior aligned; neither CLI nor WebUI may own SCPI behavior.
- Main environment is Windows.
- Use the root `uv` workspace workflow. Install packages with `uv sync --all-packages --dev`.
- Primary communication interfaces are USB and LAN through PyVISA.

## 4. Architecture Rules

- Do not scatter SCPI strings through CLI commands, examples, or test flows.
- Put SCPI behavior in driver classes or small command helpers.
- Use a common power-supply interface with series-specific driver adapters.
- Do not assume every E36xxx model uses identical SCPI.
- Verify model-specific SCPI, channel syntax, timing, protection behavior, and LIST/trigger behavior against the relevant programming guide before implementing it.
- Keep resource strings configurable. Do not hard-code real VISA addresses in committed code.
- Prefer fake-instrument tests for command generation and error paths before using hardware.

## 5. Safety Rules

- This project controls Keysight power supplies through VISA/SCPI. Treat output-affecting changes as high risk.
- Never enable real hardware output from a default test.
- Hardware tests must be explicit, opt-in, and require a user-provided VISA resource.
- Default output state should be off.
- Examples that enable output must use low safe values, set current limit before voltage, and use `try`/`finally` or a context manager.
- Get user confirmation before changing SCPI behavior, VISA timeout, trigger wait strategy, `TRIG:DEL`, LIST/sequence timing, OVP/OCP behavior, output-on behavior, output-off behavior, remote/local behavior, or cleanup behavior.
- Do not add automatic high-voltage or high-current behavior without an explicit safety design and user confirmation.

## 6. Stop And Cleanup Behavior

Preserve the current stop design for long-running flows:

- `engine.stop()` or any equivalent stop request only sets stop state and stop events.
- Main VISA measurement, logging, sequence, and cleanup I/O belongs on the worker/cleanup path.
- Preserve the cleanup order unless explicitly changing it with user confirmation:
  1. Wait for worker.
  2. `release_to_local`.
  3. Close session.
  4. `cleanup_release_to_local`.
  5. Stop HTTP server.

Power Worker stop and cleanup output must remain structured JSONL. Do not emit
plain-text lifecycle output on stdout.

Do not change stop/release/local behavior without explicit confirmation.

## 7. Testing Rules

- Run the narrowest relevant tests first, then broader tests when practical.
- On Windows, run the uv/pytest no-hardware gates from an Administrator PowerShell.
- Run pytest from the repository root. Use the default `.tmp_pytest` basetemp,
  or place intentional per-run output under `.tmp_tests/<purpose>`.
- Never use `Local/` as a pytest basetemp or test-artifact output directory.
- Default tests must run without hardware.
- Hardware tests should live under an integration path or require a marker such as `hardware`.
- Do not hide failed or skipped verification. State exactly what ran and what did not.
- After a project skeleton exists, the expected default test command is:

```powershell
uv run python -m pytest packages -q -p no:cacheprovider
```

- Hardware validation should require an explicit resource, for example:

```powershell
uv run python -m pytest packages\cli\tests\integration -q -m hardware --resource "USB0::..."
```

## 8. Documentation Rules

- Keep long-term agent rules in this file.
- Keep implementation progress, temporary notes, and large status sections out
  of this file.
- Record reusable workflow and release information in `docs/workspace.md`,
  `docs/release-checklist.md`, package READMEs, or contract documents.
- Do not commit private hardware notes, exact lab resource strings, or local
  machine details to public documentation.


## 9. Monorepo Migration and Structure

This repository is now organized as a Monorepo under the `packages/` directory:
- `packages/core`: Core instrument driver, transport, and runtime layer (`keysight_power_core`).
- `packages/cli`: Command line interface adapter (`keysight_power_cli`).
- `packages/webui`: Web interface skeleton (`keysight_power_webui`).

Always read the package-local code, configuration, and documentation (e.g., package-local `pyproject.toml`) before implementing or modifying features.
- Never let `packages/core` import from `packages/cli` or `packages/webui`.
- CLI commands are invoked via `keysight-power` or `python -m keysight_power_cli.cli`. The old `python -m keysight_power.cli` entry is no longer supported.
