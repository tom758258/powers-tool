# Repository Layout

```text
src/
  keysight_power_core/
  keysight_power_cli/
  keysight_power_webui/
tests/
  core/
  cli/
  webui/
  integration/
docs/
  core/
  cli/
  webui/
  contracts/
```

## Package Names

Core, CLI, and WebUI are separate import packages and maintenance boundaries,
released together as one `keysight-powers` distribution. The distribution
version is owned by `[project].version` in the root `pyproject.toml`; use
`<version>` in examples where the installed release version is substituted.

| Area | Distribution | Import | Version | Console command |
| --- | --- | --- | --- | --- |
| Core | `keysight-powers` | `keysight_power_core` | distribution version | None |
| CLI | `keysight-powers` | `keysight_power_cli` | distribution version | `keysight-power` |
| WebUI | `keysight-powers` | `keysight_power_webui` | distribution version | `keysight-power-webui`, `keysight-power-webui-launcher` |

## Ownership

Root `pyproject.toml` owns distribution metadata, dependencies, console
scripts, package discovery, and WebUI package data for the single
`keysight-powers` distribution. Root docs own repository planning,
architecture notes, release checklists, and canonical cross-package contracts
under `../contracts/`.
