"""Server entry point for Keysight Power WebUI."""

from __future__ import annotations

import argparse
import uvicorn

from .app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Keysight Power WebUI Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    
    print(f"Starting Keysight Power WebUI on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
