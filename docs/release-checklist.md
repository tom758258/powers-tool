# Release Checklist

Use this checklist before creating a release commit and package tags.

## core-v1.0.0 and cli-v1.0.0

The `keysight-power-core` and `keysight-power-cli` packages are released
together for this milestone. `keysight-power-webui` remains version `0.1.0`
but is an active parallel product interface over the shared Core runtime.

Recommended commit message:

```text
release: prepare core and cli v1.0.0
```

Recommended tags on the release commit:

```powershell
git tag core-v1.0.0
git tag cli-v1.0.0
```

## Pre-Tag Validation

Run the no-hardware and package gates from the repository root:

```powershell
uv sync --locked --all-packages --dev
.\.venv\Scripts\python.exe -m pytest packages\core\tests\test_import.py -q -p no:cacheprovider
uv run keysight-power doctor --simulate --json
.\scripts\no-hardware-regression.ps1
uv build --all-packages
git status --short
```

The `doctor --simulate --json` payload should report package
`keysight-power-cli` version `1.0.0`. The final `git status --short` should
show only intentional release, documentation, and lockfile changes before
committing.

## Future EXE Packaging Prep

This release does not add PyInstaller, Nuitka, or other packager dependencies.
When EXE packaging work starts, keep the package entry point aligned with the
current console script:

```text
keysight_power_cli.cli:main
```

Minimum EXE smoke checks should include:

```powershell
keysight-power.exe doctor --simulate --json
keysight-power.exe list-resources --simulate --json
keysight-power.exe capabilities --simulate --json --resource "USB0::SIM::E36312A::INSTR"
```

The packaged EXE must preserve JSON stdout, diagnostic stderr, simulator mode,
and explicit opt-in behavior for hardware-affecting commands.
