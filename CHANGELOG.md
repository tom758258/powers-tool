# Changelog

- Correct the internal Product/Validation runtime boundary so real validation
  requires exact clean installed wheels, rejects source shadowing, uses one
  Product runtime for the full suite, records both wheel SHA-256 identities,
  and exposes no direct permit or verified-context minting API. No candidate
  was hardware-validated or Product-opened by this correction.

## 2.0.0

- Renames the product from Keysight Powers to Powers Tool and the distribution
  from `keysight-powers` to `powers-tool`.
- Renames the Python packages to `powers_tool_core`, `powers_tool_cli`, and
  `powers_tool_webui`, and renames the CLI/WebUI entry points to `powers-tool`,
  `powers-tool-webui`, and `powers-tool-webui-launcher`.
- Removes old command, import-package, field, environment-variable, and schema
  compatibility aliases.
- Introduces vendor-qualified physical `model_id` values and requires reported
  manufacturer plus model to jointly resolve live identity. An expected model
  is a safety guard and never overrides the IDN-selected driver.
- Replaces the physical-model-like `GENERIC` identity with the no-hardware-only
  `generic-scpi` planning profile.
- Splits the ambiguous model-profile contract into `planning_model_id`,
  `expected_model_id`, and `planning_profile_id`.
- Moves affected public schemas to version 2 and changes the Ramp List
  discriminator to `powers-tool-ramp-list`.
- Migrates support policy to canonical `model_id` while preserving the exact
  Product-open and pending command, transport, backend, and feature boundaries.
- Preserves existing hardware evidence without treating the identity migration
  as new hardware validation. Currently validated hardware remains the
  documented Keysight models; no support scope was expanded by the rename.
- Expands the model-specific `full` contributor-validation plans with bounded
  standalone `output-on`, logging, resource-backed doctor, E36312A
  `measure-all`, and E36312A real restore candidates. Product mode remains
  closed for these commands until separate live evidence review and promotion;
  historical accepted evidence is unchanged and predates these cases. The
  expanded suite has not yet been run or accepted as new hardware evidence.
- Product release artifacts now exclude candidate parser inputs and capability
  machinery. Candidate validation uses a separate internal
  `powers-tool-validation` distribution with an embedded Validation identity;
  normal release workflows continue to build only Product artifacts.
- HMAC-signed, exact, run/case-scoped one-time capabilities provide expiry,
  invocation integrity, and replay prevention inside that validation build.
  Distribution separation, not a caller-supplied HMAC key, is the admission
  boundary; registered transport-pending admission remains a separate path.

## 1.0.0

- First stable release of `keysight-powers` for Keysight DC power supply
  workflows.
- Provides the shared Core runtime, `keysight-power` CLI, local WebUI server,
  and Windows WebUI launcher in one installable distribution.
- Supports USB and LAN VISA communication, simulator and dry-run workflows,
  JSON/JSONL automation output, ramp, sequence, trigger, snapshot, restore,
  and protection operations.
- Keeps real hardware output opt-in; default tests and simulator flows do not
  enable instrument output.
