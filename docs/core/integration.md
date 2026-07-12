# Core Integration

`powers_tool_core` owns the hardware-facing runtime for Keysight DC power
supplies. Adapter packages should build parser-neutral request objects and call
the shared command runners instead of constructing SCPI directly.

`powers_tool_core` ships as part of the single `keysight-powers`
distribution. Its installed version follows `[project].version` from the root
`pyproject.toml`, while the import boundary remains `powers_tool_core`.

The package exposes `__version__` through `powers_tool_core.__all__`.

## Boundary

Core may depend on PyVISA, simulator helpers, model drivers, safety validation,
sequence loading, and command runner modules. It must not import from
`powers_tool_cli` or `powers_tool_webui`.

Core documentation is package-local:

- `supported-models.md`

The cross-adapter JSONL and worker contracts remain under `../contracts/`.
