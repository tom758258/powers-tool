"""Strict no-hardware model resolution helpers."""

from __future__ import annotations

from dataclasses import replace

from powers_tool_core.core import CoreValidationError, RuntimeOptions
from powers_tool_core.identity import IDENTITY_INDEXES, planning_model_id_from_sim_resource
from powers_tool_core.models import CANDIDATE_MODEL_IDS, PRODUCT_ACTIVE_MODEL_IDS

PRODUCT_MODEL_PROFILES = frozenset(
    IDENTITY_INDEXES.models_by_id[model_id].canonical_model
    for model_id in PRODUCT_ACTIVE_MODEL_IDS
)
CANDIDATE_MODEL_PROFILES = frozenset(
    IDENTITY_INDEXES.models_by_id[model_id].canonical_model
    for model_id in CANDIDATE_MODEL_IDS
)
CANONICAL_MODEL_PROFILES = PRODUCT_MODEL_PROFILES | CANDIDATE_MODEL_PROFILES | {"GENERIC"}

LIVE_EXPECTED_MODEL_PROFILES = PRODUCT_MODEL_PROFILES | CANDIDATE_MODEL_PROFILES

MODEL_CHANNELS_BY_ID = {
    "keysight-e36312a": (1, 2, 3),
    "keysight-edu36311a": (1, 2, 3),
    "keysight-e3646a": (1, 2),
}
PLANNING_PROFILE_CHANNELS = {
    "GENERIC": (1,),
}

SIMULATED_RESOURCE_FOR_MODEL_ID = {
    "keysight-e36312a": "USB0::SIM::E36312A::INSTR",
    "keysight-edu36311a": "USB0::SIM::EDU36311A::INSTR",
    "keysight-e3646a": "ASRL1::SIM::E3646A::INSTR",
}

_MODEL_ID_BY_MODEL_PROFILE = {
    IDENTITY_INDEXES.models_by_id[model_id].canonical_model: model_id
    for model_id in PRODUCT_ACTIVE_MODEL_IDS | CANDIDATE_MODEL_IDS
}


def canonical_model_profile(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip().upper()
    if normalized not in CANONICAL_MODEL_PROFILES:
        supported = ", ".join(sorted(CANONICAL_MODEL_PROFILES))
        raise CoreValidationError(f"unsupported model profile {model!r}; supported: {supported}")
    return normalized


def canonical_live_expected_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = canonical_model_profile(model)
    if normalized not in LIVE_EXPECTED_MODEL_PROFILES:
        if normalized == "GENERIC":
            raise CoreValidationError(
                "GENERIC is no-hardware only and cannot be used as a live expected model. "
                "--model is an expected-model guard in live mode and does not override the IDN-detected driver."
            )
        supported = ", ".join(sorted(LIVE_EXPECTED_MODEL_PROFILES))
        raise CoreValidationError(
            f"unsupported live expected model {model!r}; supported: {supported}. "
            "--model is an expected-model guard in live mode and does not override the IDN-detected driver."
        )
    return normalized


def validate_live_expected_model(
    expected_model: str | None,
    detected_model: str | None,
    *,
    command: str | None = None,
) -> str | None:
    expected = canonical_live_expected_model(expected_model)
    if expected is None:
        return None
    detected = _canonical_detected_model(detected_model)
    if detected != expected:
        prefix = f"{command}: " if command else ""
        reported = detected or "UNKNOWN"
        raise CoreValidationError(
            f"{prefix}Expected model {expected} but connected instrument reported {reported}. "
            "--model is an expected-model guard in live mode and does not override the IDN-detected driver."
        )
    return expected


def model_profile_from_sim_resource(resource: str | None) -> str | None:
    model_id = planning_model_id_from_sim_resource(resource)
    if model_id is None:
        return None
    return IDENTITY_INDEXES.models_by_id[model_id].canonical_model


def model_id_from_model_profile(model_profile: str | None) -> str | None:
    """Project the staged legacy planning profile to a canonical physical model ID."""

    profile = canonical_model_profile(model_profile)
    if profile is None or profile == "GENERIC":
        return None
    return _MODEL_ID_BY_MODEL_PROFILE[profile]


def resolve_no_hardware_runtime(runtime: RuntimeOptions) -> RuntimeOptions:
    """Resolve no-hardware planning models and live expected-model guards."""

    if not runtime.dry_run and not runtime.simulate:
        expected = canonical_live_expected_model(runtime.model_profile)
        return replace(runtime, model_profile=expected)

    requested = canonical_model_profile(runtime.model_profile)
    inferred = model_profile_from_sim_resource(runtime.resource)

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
    if model_profile in PLANNING_PROFILE_CHANNELS:
        return PLANNING_PROFILE_CHANNELS[model_profile]
    model_id = model_id_from_model_profile(model_profile)
    try:
        assert model_id is not None
        return MODEL_CHANNELS_BY_ID[model_id]
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
        model_id = model_id_from_model_profile(model)
        if model_id is None:
            raise KeyError(model)
        return SIMULATED_RESOURCE_FOR_MODEL_ID[model_id]
    except KeyError as exc:
        raise CoreValidationError(f"--simulate --model {model} has no deterministic simulator resource") from exc


def _canonical_detected_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip().upper()
    return normalized or None
