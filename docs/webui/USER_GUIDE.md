# Keysight Power WebUI User Guide

The WebUI is a local browser dashboard for safe Keysight DC power supply
inspection and command submission.

Start it from the repository root:

```powershell
uv run python -m keysight_power_webui.server --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

The page provides a connection bar, command rail, generated command form, live
read-only trend area, job history, and JSON result view. Hardware-affecting jobs
remain explicit and confirmed.
