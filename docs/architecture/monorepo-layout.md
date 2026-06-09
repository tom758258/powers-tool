# Monorepo Layout

```text
packages/
  core/
    src/keysight_power_core/
    tests/
    docs/
  cli/
    src/keysight_power_cli/
    tests/
    docs/
  webui/
    src/keysight_power_webui/
    tests/
    docs/
```

## Package Names

| Package | Distribution | Import | Version | Console command |
| --- | --- | --- | --- | --- |
| Core | `keysight-power-core` | `keysight_power_core` | `1.0.0` | None |
| CLI | `keysight-power-cli` | `keysight_power_cli` | `1.0.0` | `keysight-power` |
| WebUI | `keysight-power-webui` | `keysight_power_webui` | `0.1.0` | `keysight-power-webui` |

## Ownership

Each package owns its README, changelog, tests, package-local docs, and package
metadata. Root docs own workspace planning, architecture notes, release
checklists, and canonical cross-package contracts under `../contracts/`.
