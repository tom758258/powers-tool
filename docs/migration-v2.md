# Migrating To Powers Tool 2.0

Powers Tool 2.0 intentionally changes public identity and contracts. This is a
migration reference, not a compatibility promise; update callers and artifacts
before upgrading.

## Product And Package Names

| Version 1 | Version 2 |
| --- | --- |
| Keysight Powers | Powers Tool |
| `keysight-powers` | `powers-tool` |
| `keysight_power_core` | `powers_tool_core` |
| `keysight_power_cli` | `powers_tool_cli` |
| `keysight_power_webui` | `powers_tool_webui` |
| Keysight Power contributors | Powers Tool contributors |

The repository remains one distribution with three import packages.

## CLI Commands

| Removed command | Version 2 command |
| --- | --- |
| `keysight-power` | `powers-tool` |
| `keysight-power-webui` | `powers-tool-webui` |
| `keysight-power-webui-launcher` | `powers-tool-webui-launcher` |

The old commands are removed. Installed Python console scripts include all
three version 2 commands. Standalone Windows artifacts are
`powers-tool.exe` and `powers-tool-webui.exe`; versioned release artifacts are
`powers-tool-<version>.exe` and `powers-tool-webui-<version>.exe`.

## Python Imports

| Removed import | Version 2 import |
| --- | --- |
| `keysight_power_core` | `powers_tool_core` |
| `keysight_power_cli` | `powers_tool_cli` |
| `keysight_power_webui` | `powers_tool_webui` |

The old import packages are removed.

## Model Identity

Physical models now use canonical vendor-qualified IDs. Reported manufacturer
and model are resolved together; a model-only match cannot select a
model-specific live driver.

| Legacy model value | Canonical `model_id` | Lifecycle |
| --- | --- | --- |
| `E36312A` | `keysight-e36312a` | Product-active |
| `EDU36311A` | `keysight-edu36311a` | Product-active |
| `E3646A` | `keysight-e3646a` | Product-active |
| `E36313A` | `keysight-e36313a` | Catalog-only |
| `E36233A` | `keysight-e36233a` | Catalog-only |
| `E36441A` | `keysight-e36441a` | Catalog-only |
| `E36155A` | `keysight-e36155a` | Catalog-only |
| `E36103B` | `keysight-e36103b` | De-scoped |
| `E36232A` | `keysight-e36232a` | De-scoped |
| `GENERIC` | `generic-scpi` | Nonphysical, no-hardware planning profile only |

`generic-scpi` is not a live expected model, does not unlock unknown hardware,
and has no Product-open support scope.

## Runtime Fields

The ambiguous `model_profile` field is removed:

| Version 2 field | Use |
| --- | --- |
| `planning_model_id` | Canonical physical model for dry-run or simulation planning |
| `expected_model_id` | Optional live safety guard checked after IDN resolution |
| `planning_profile_id` | Nonphysical dry-run profile, currently `generic-scpi` |

The CLI still offers `--model`, translating it to the correct internal field
for the selected mode. `--profile generic-scpi` selects no-hardware dry-run
planning. Incompatible combinations fail closed.

## Environment Variables

Documentation examples now use `POWERS_TOOL_RESOURCE` and
`POWERS_TOOL_ASRL_RESOURCE`. The former `KEYSIGHT_POWER_RESOURCE` and
`KEYSIGHT_POWER_ASRL_RESOURCE` names are not aliases.

## Public Schemas

Affected JSON, JSONL, snapshot, support, and Worker contracts use schema
version 2. Ramp List documents now require:

```json
{
  "kind": "powers-tool-ramp-list",
  "version": 2
}
```

The version 1 `keysight-power-ramp-list` discriminator is rejected rather than
converted.

## Compatibility Statement

Version 2 intentionally provides no legacy CLI, Python import, runtime-field,
environment-variable, or Ramp List version 1 compatibility layer. Historical
names in this document and the changelog describe migration only; they are not
supported operational identities.
