"""IDN parsing and model metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IdnInfo:
    """Parsed information from a SCPI `*IDN?` response."""

    raw: str
    manufacturer: str | None
    model: str | None
    serial: str | None
    firmware: str | None
    parse_ok: bool

    def to_dict(self) -> dict[str, object]:
        """Return the stable CLI JSON representation for parsed IDN data."""

        return {
            "raw": self.raw,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "firmware": self.firmware,
            "parse_ok": self.parse_ok,
        }


@dataclass(frozen=True)
class ModelInfo:
    """Known model metadata without unverified electrical ratings."""

    manufacturer: str
    model: str
    target_group: str
    first_hardware_target: bool = False


REGISTERED_MODELS: dict[str, ModelInfo] = {
    "E36312A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="E36312A",
        target_group="initial",
        first_hardware_target=True,
    ),
    "EDU36311A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="EDU36311A",
        target_group="initial",
        first_hardware_target=True,
    ),
    "E36313A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="E36313A",
        target_group="near-term",
    ),
    "E3646A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="E3646A",
        target_group="read-only-serial",
    ),
    "E36233A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="E36233A",
        target_group="near-term",
    ),
    "E36441A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="E36441A",
        target_group="near-term",
    ),
    "E36155A": ModelInfo(
        manufacturer="KEYSIGHT",
        model="E36155A",
        target_group="later",
    ),
}

DE_SCOPED_MODELS = frozenset({"E36103B", "E36232A"})


def de_scoped_model_message(model: str) -> str:
    """Return the current support-boundary message for a de-scoped model."""

    return (
        f"{model} is de-scoped and not active supported. It was previously "
        "considered as an unvalidated planning model, but is now blocked from "
        "generic fallback. Future reintroduction requires a new "
        "model-enablement plan, programming-guide review, simulator/fake "
        "coverage, explicit feature matrix, and real hardware validation."
    )


def parse_idn(raw: str) -> IdnInfo:
    """Parse a SCPI `*IDN?` response into the stable project model."""

    parts = [part.strip() for part in raw.split(",", maxsplit=3)]
    values = [part or None for part in parts]

    def get(index: int) -> str | None:
        if index >= len(values):
            return None
        return values[index]

    return IdnInfo(
        raw=raw,
        manufacturer=get(0),
        model=get(1),
        serial=get(2),
        firmware=get(3),
        parse_ok=all(get(index) is not None for index in range(4)),
    )


def resource_interface(name: str) -> str:
    """Return the high-level VISA interface family for a resource name."""

    normalized = name.strip().upper()
    for interface in ("USB", "TCPIP", "GPIB", "ASRL"):
        if normalized.startswith(interface):
            return interface
    return "UNKNOWN"


def lookup_model(model: str | None) -> ModelInfo | None:
    """Return metadata for a registered model name, if known."""

    if model is None:
        return None
    return REGISTERED_MODELS.get(model.strip().upper())
