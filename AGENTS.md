# Agent Instructions

These instructions guide coding agents working in this repository. They are long-term working rules, not a project status log.

## 1. Primary Project Documents

- Read the root `README.md` and the relevant package README before implementing features.
- Read the root contracts in `docs/contracts/` before changing adapter or worker behavior.
- Keep temporary AI planning notes out of committed public documentation.

## 2. Communication And Writing Rules

- Discuss with the user in Traditional Chinese.
- Write repository files in English unless the user explicitly requests otherwise.
- Keep code comments short and useful.
- Prefer clear public documentation and focused issue notes over long chat-only explanations.

## 2.1 Encoding And Line Endings

- Save edited Markdown, plain-text, JSON, YAML, TOML, Python, and similar text
  files as UTF-8 without BOM.
- Preserve the file's existing line-ending style unless the task explicitly
  requires normalization. Avoid unrelated CRLF/LF churn in documentation-only
  or code-only edits.
- Prefer LF for new Markdown files unless a repository-level rule says
  otherwise.
- Do not use Windows PowerShell 5.1 `Set-Content -Encoding UTF8` or
  `Out-File -Encoding utf8` for final writes, because they can write a UTF-8
  BOM.
- In Windows PowerShell 5.1, use
  `[System.IO.File]::WriteAllText(..., (New-Object System.Text.UTF8Encoding($false)))`
  when a script must write text. In PowerShell 7+, `Set-Content -Encoding utf8`
  is acceptable.
- After rewriting files or editing non-ASCII text, verify the first three bytes
  are not `EF BB BF`, check for mojibake, and inspect `git diff` to confirm
  line endings were not unintentionally normalized.

## 3. Project Direction

- Build a Python package for Keysight DC power supplies.
- CLI and WebUI are parallel product interfaces over the shared Core runtime.
- Keep adapter behavior aligned; neither CLI nor WebUI may own SCPI behavior.
- Main environment is Windows.
- Use the root single-distribution workflow. Install development dependencies
  with `pip install -e ".[all,dev]"` or sync with `uv sync --all-extras`.
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
uv run python -m pytest tests -q -p no:cacheprovider
```

- Hardware validation should require an explicit resource, for example:

```powershell
uv run python -m pytest tests\integration -q -m hardware --resource "USB0::..."
```

## 8. Documentation Boundary

- Keep long-term agent rules in this file.
- Keep tracked public docs limited to README, changelog, architecture,
  contracts, integration guides, user guides, supported models, testing
  guidelines, and change rules.
- Keep `USER_GUIDE.md` files operator/user-facing. Avoid source-checkout,
  virtualenv, build, validation, or maintainer workflow details there unless
  explicitly needed for the user-facing task.
- Keep `README.md` files available for engineering setup, build, validation,
  detailed reference, automation, and maintainer boundaries.
- Keep implementation progress, temporary notes, validation records, and
  hardware-specific operator context outside tracked public docs.
- Default documentation edits should update English `.md` source files only.
- Do not update Traditional Chinese or localized docs, including
  `README.zh-TW.md`, unless explicitly requested.
- If localized docs exist and English docs change, mention the possible
  follow-up instead of auto-syncing them.
- Generated or presentation-oriented documentation HTML may be updated only
  when the task explicitly concerns published docs or documentation
  presentation.
- Do not update product WebUI HTML, CSS, JavaScript, static assets, or in-app
  UI copy under `src/keysight_power_webui/static` as part of ordinary
  documentation work unless explicitly requested or required by a user-facing
  UI change.
- Record reusable workflow and release information in the root README, package
  READMEs, testing guidelines, changelog, or contract documents.
- Do not commit private hardware notes, exact lab resource strings,
  instrument serial numbers, local machine details, or link-local/private lab
  IP addresses to public documentation.
- Do not duplicate large status sections here.


## 9. Monorepo Migration and Structure

This repository is organized as a single-distribution Monorepo under the root
`src/` directory:
- `src/keysight_power_core`: Core instrument driver, transport, and runtime layer.
- `src/keysight_power_cli`: Command line interface adapter.
- `src/keysight_power_webui`: Web interface adapter and static dashboard.

Always read root `pyproject.toml` plus the relevant package-local code and
docs under `docs/core`, `docs/cli`, or `docs/webui` before implementing or
modifying features.
- Never let `keysight_power_core` import from `keysight_power_cli` or
  `keysight_power_webui`.
- CLI commands are invoked via `keysight-power` or `python -m keysight_power_cli.cli`. The old `python -m keysight_power.cli` entry is no longer supported.
