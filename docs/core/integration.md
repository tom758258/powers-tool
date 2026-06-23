# Core Integration

`keysight_power_core` owns the hardware-facing runtime for Keysight DC power
supplies. Adapter packages should build parser-neutral request objects and call
the shared command runners instead of constructing SCPI directly.

`keysight_power_core` ships as part of the single `keysight-powers`
distribution. Its installed version follows `[project].version` from the root
`pyproject.toml`, while the import boundary remains `keysight_power_core`.

The package exposes `__version__` through `keysight_power_core.__all__`.

## Boundary

Core may depend on PyVISA, simulator helpers, model drivers, safety validation,
sequence loading, and command runner modules. It must not import from
`keysight_power_cli` or `keysight_power_webui`.

Core documentation is package-local:

- `supported-models.md`

The cross-adapter JSONL and worker contracts remain under `../contracts/`.
