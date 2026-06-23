# Changelog

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
