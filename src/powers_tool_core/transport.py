"""Transport protocols shared by real, fake, and simulator sessions."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionLike(Protocol):
    """Minimal instrument session behavior required by drivers."""

    def write(self, command: str) -> Any:
        """Write one command to the instrument."""

    def query(self, command: str) -> str:
        """Query the instrument and return the response."""

    def close(self) -> None:
        """Close the instrument session."""


@runtime_checkable
class ResourceManagerLike(Protocol):
    """Minimal resource-manager behavior required by connection helpers."""

    def list_resources(self) -> tuple[str, ...]:
        """Return available resource strings."""

    def open_resource(self, resource_name: str) -> Any:
        """Open a resource by name."""


def dry_run_plan(
    *,
    command: str,
    resource: str | None = None,
    planning_model_id: str | None = None,
    planning_profile_id: str | None = None,
    scpi: tuple[str, ...] = (),
    description: str | None = None,
) -> dict[str, object]:
    """Return a stable dry-run plan without touching an instrument."""

    return {
        "operation": {"name": command},
        "target": {
            "resource": resource,
            "planning_model_id": planning_model_id,
            "planning_profile_id": planning_profile_id,
        },
        "steps": [
            {
                "index": index,
                "type": "scpi",
                "command": command_text,
            }
            for index, command_text in enumerate(scpi, start=1)
        ],
        "description": description,
        "hardware_touched": False,
    }
