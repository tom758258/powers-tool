# Core Integration

`powers_tool_core` owns the vendor-neutral hardware-facing runtime for
supported DC power supplies. Current validated drivers target the documented
Keysight models. Adapter packages should build parser-neutral request objects
and call the shared command runners instead of constructing SCPI directly.

`powers_tool_core` ships as part of the single `powers-tool`
distribution. Its installed version follows `[project].version` from the root
`pyproject.toml`, while the import boundary remains `powers_tool_core`.

The package exposes `__version__` through `powers_tool_core.__all__`.

## Boundary

Core may depend on PyVISA, simulator helpers, model drivers, safety validation,
sequence loading, and command runner modules. It must not import from
`powers_tool_cli` or `powers_tool_webui`.

## Adapter Integration Boundary

Core owns adapter-neutral domain logic, command admission, model identity,
Product policy, driver and SCPI execution, and workflow runtime. The bundled
CLI (including the Worker) and WebUI are parallel adapters: they map their
transport inputs to parser-neutral Core request objects, then own their own
serialization and presentation.

For generic command routing, `validate_request_admission()` and
`run_core_command()` are the adapter-facing Core integration entry points used
by those bundled adapters. Admission performs canonicalization without
hardware, VISA, or SCPI I/O and without device-state mutation. File-backed
requests may perform local filesystem I/O during one-time materialization.
`run_core_command()` admits before dispatching the request.

These statements describe the bundled-adapter integration boundary; they do not
expand package exports or make other non-underscore functions broad stable
third-party APIs. Underscore-prefixed helpers, including `_run_*_admitted`, are
Core-internal handoffs for already admitted requests and are not stable adapter
APIs.

Core documentation is package-local:

- `supported-models.md`

The cross-adapter JSONL and worker contracts remain under `../contracts/`.
