# WebUI AI Change Rules

- Keep WebUI behavior adapter-local and route hardware operations through
  `keysight_power_core`.
- Do not add a Node toolchain unless the user explicitly changes the project
  direction.
- Default tests must remain no-hardware tests.
- Keep static files under `src/keysight_power_webui/static`.
