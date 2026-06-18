# Monorepo Layout

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

| Area | Distribution | Import | Version | Console command |
| --- | --- | --- | --- | --- |
| Core | `keysight-powers` | `keysight_power_core` | `1.0.0` | None |
| CLI | `keysight-powers` | `keysight_power_cli` | `1.0.0` | `keysight-power` |
| WebUI | `keysight-powers` | `keysight_power_webui` | `1.0.0` | `keysight-power-webui` |

## Ownership

Root `pyproject.toml` owns distribution metadata, dependencies, console
scripts, package discovery, and WebUI package data. Root docs own workspace
planning, architecture notes, release checklists, and canonical cross-package
contracts under `../contracts/`.
