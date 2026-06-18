# Keysight Power CLI Reference

This root-local reference summarizes the `keysight-power` command adapter.
For examples and the full command catalog, see `../README.md`.

The CLI package owns:

- command parsing and help text;
- JSON success/error envelope creation;
- local worker startup and artifact handling;
- adapter-specific smoke and regression documentation.

Core runtime behavior remains in `../core/`. Worker and JSONL wire contracts
remain in `../contracts/`.
