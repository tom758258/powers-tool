# Release Checklist

Use this checklist before creating a release commit and package tag.

## keysight-powers v1.0.0

The repository now publishes one distribution, `keysight-powers`, containing
the Core, CLI, and WebUI import packages.

Recommended commit message:

```text
release: prepare keysight-powers v1.0.0
```

Recommended tag on the release commit:

```powershell
git tag v1.0.0
```

## Pre-Tag Validation

Run the no-hardware and package gates from the repository root:

```powershell
uv sync --all-extras
.\.venv\Scripts\python.exe -m pytest tests\core\test_import.py -q -p no:cacheprovider
uv run keysight-power doctor --simulate --json
.\scripts\no-hardware-regression.ps1
python -m build
git status --short
```

The `doctor --simulate --json` payload should report adapter package
`keysight-power-cli` with version `1.0.0`; that version is sourced from the
single installed `keysight-powers` distribution. The final
`git status --short` should show only intentional release, documentation, and
lockfile changes before committing.

## Future EXE Packaging Prep

This release does not add PyInstaller, Nuitka, or other packager dependencies.
When EXE packaging work starts, keep the package entry points aligned with the
current console scripts:

```text
keysight_power_cli.cli:main
keysight_power_webui.server:main
```

Minimum EXE smoke checks should include:

```powershell
keysight-power.exe doctor --simulate --json
keysight-power.exe list-resources --simulate --json
keysight-power.exe capabilities --simulate --json --resource "USB0::SIM::E36312A::INSTR"
```

The packaged EXE must preserve JSON stdout, diagnostic stderr, simulator mode,
and explicit opt-in behavior for hardware-affecting commands.
