# WebUI Package Notes

`keysight_power_webui` is the FastAPI/static-asset adapter for Keysight Power.
It imports `keysight_power_core` and must not import `keysight_power_cli`.

Static assets live under:

```text
src/keysight_power_webui/static
```

The WebUI maps HTTP payloads to core request objects, runs synchronous core work
in worker threads, and streams job/live-data events through the browser API.
