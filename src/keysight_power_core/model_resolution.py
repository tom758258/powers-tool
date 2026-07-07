"""Strict no-hardware model resolution helpers."""

from __future__ import annotations

from dataclasses import replace

from keysight_power_core.core import CoreValidationError, RuntimeOptions
from keysight_power_core.models import parse_idn

CANONICAL_MODEL_PROFILES = frozenset(
    {"E36103B", "E36232A", "E36312A", "EDU36311A", "E3646A", "GENERIC"}
)

MODEL_PROFILE_CHANNELS = {
    "E36103B": (1,),
    "E36232A": (1,),
    "E36312A": (1, 2, 3),
    "EDU36311A": (1, 2, 3),
    "E3646A": (1, 2),
    "GENERIC": (1,),
}

SIMULATED_RESOURCE_FOR_MODEL = {
    "E36103B": "USB0::SIM::E36103B::INSTR",
    "E36232A": "TCPIP0::SIM::E36232A::INSTR",
    "E36312A": "USB0::SIM::E36312A::INSTR",
    "EDU36311A": "USB0::SIM::EDU36311A::INSTR",
    "E3646A": "ASRL1::SIM::E3646A::INSTR",
}


def canonical_model_profile(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip().upper()
    if normalized not in CANONICAL_MODEL_PROFILES:
        supported = ", ".join(sorted(CANONICAL_MODEL_PROFILES))
        raise CoreValidationError(f"unsupported model profile {model!r}; supported: {supported}")
    return normalized


def model_profile_from_sim_resource(resource: str | None) -> str | None:
    if resource is None:
        return None
    from keysight_power_core.testing.simulator import SIMULATED_IDN

    idn = SIMULATED_IDN.get(resource)
    if idn is None:
        return None
    return parse_idn(idn).model


def resolve_no_hardware_runtime(runtime: RuntimeOptions) -> RuntimeOptions:
    """Resolve no-hardware planning model/resource without opening VISA."""

    requested = canonical_model_profile(runtime.model_profile)
    inferred = model_profile_from_sim_resource(runtime.resource)

    if not runtime.dry_run and not runtime.simulate:
        if requested is not None:
            raise CoreValidationError("--model is only supported with --dry-run or --simulate")
        return runtime

    if requested is None and inferred is None:
        raise CoreValidationError(
            "--dry-run and --simulate require --model or a known deterministic SIM resource"
        )
    if requested is not None and inferred is not None and requested != inferred:
        raise CoreValidationError(
            f"--model {requested} does not match SIM resource model {inferred}"
        )

    model = requested or inferred
    assert model is not None
    resource = runtime.resource
    if runtime.simulate:
        resource = _simulate_resource_for_model(model, resource)

    return replace(runtime, resource=resource, model_profile=model)


def no_hardware_channels(model_profile: str) -> tuple[int, ...]:
    try:
        return MODEL_PROFILE_CHANNELS[model_profile]
    except KeyError as exc:
        raise CoreValidationError(f"unsupported model profile {model_profile!r}") from exc


def _simulate_resource_for_model(model: str, resource: str | None) -> str:
    if resource is not None:
        if model_profile_from_sim_resource(resource) is None:
            raise CoreValidationError(
                "--simulate requires a deterministic SIM resource; "
                "omit --resource to derive one from --model or pass a known SIM resource"
            )
        return resource
    try:
        return SIMULATED_RESOURCE_FOR_MODEL[model]
    except KeyError as exc:
        raise CoreValidationError(f"--simulate --model {model} has no deterministic simulator resource") from exc
