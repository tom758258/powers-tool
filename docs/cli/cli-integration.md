# CLI Integration

`powers_tool_cli` owns argparse handling, command-line text output, JSON
envelope wrapping, `--save-json`, `--log-scpi`, and the local worker daemon.

The CLI does not own the core runtime schema. CLI-only fields such as
`measurement_cli_name`, parsed `argparse.Namespace` values, command aliases,
and adapter error text are adapter concerns, not Core schema.

The old `--enable-hw-trigger` flag was removed; native trigger behavior is
documented through current command options and root contracts.

Canonical contracts stay at the repository root:

- `../contracts/power-cli-jsonl-contract.md`
- `../contracts/power-worker-contract.md`
- `../contracts/power-orchestrator-workflows.md`
