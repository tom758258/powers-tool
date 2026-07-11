"""Pure consistency checks for the physical-model enablement lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from keysight_power_core.models import (
    DE_SCOPED_MODELS,
    MODEL_ENABLEMENT_CANDIDATE,
    MODEL_ENABLEMENT_CATALOG_ONLY,
    MODEL_ENABLEMENT_DE_SCOPED,
    MODEL_ENABLEMENT_PRODUCT_ACTIVE,
    REGISTERED_MODELS,
    parse_idn,
)
from keysight_power_core.support_features import FEATURE_AWARE_LIVE_COMMANDS
from keysight_power_core.support_policy import (
    EXEMPT_LIVE_DIAGNOSTIC_COMMANDS,
    PURE_OFFLINE_COMMANDS,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    ModelSupportPolicy,
    expected_live_feature_inventory,
    validate_live_feature_scope_metadata,
)

MODEL_ENABLEMENT_STAGES = frozenset(
    {
        MODEL_ENABLEMENT_PRODUCT_ACTIVE,
        MODEL_ENABLEMENT_CANDIDATE,
        MODEL_ENABLEMENT_CATALOG_ONLY,
        MODEL_ENABLEMENT_DE_SCOPED,
    }
)

# E3646A predates flattened rating metadata and uses enforced range-dependent
# limits. This compatibility is only for the existing Product-active model.
PRODUCT_RATING_COMPATIBILITY_MODELS = frozenset({"E3646A"})


@dataclass(frozen=True)
class ModelEnablementInventory:
    """Injected registries required to validate model-enablement consistency."""

    model_stages: Mapping[str, str]
    product_profiles: frozenset[str]
    candidate_profiles: frozenset[str]
    canonical_profiles: frozenset[str]
    live_expected_profiles: frozenset[str]
    channels: Mapping[str, tuple[int, ...]]
    simulator_resources: Mapping[str, str]
    simulator_idns: Mapping[str, str]
    drivers: Mapping[str, object]
    command_capabilities: Mapping[str, Mapping[str, Mapping[str, object]]]
    live_policies: Mapping[str, ModelSupportPolicy]
    feature_inventories: Mapping[
        str, Mapping[str, frozenset[tuple[str, str]]]
    ]
    electrical_rating_models: frozenset[str]
    setpoint_range_models: frozenset[str]
    product_rating_compatibility_models: frozenset[str]
    safety_validated_models: frozenset[str]
    no_hardware_covered_models: frozenset[str]


def current_model_enablement_inventory() -> ModelEnablementInventory:
    """Build the current inventory without coupling Core to adapters or scripts."""

    from keysight_power_core.capabilities import command_support
    from keysight_power_core.electrical_ratings import ELECTRICAL_RATINGS_BY_MODEL
    from keysight_power_core.factory import MODEL_DRIVERS
    from keysight_power_core.model_resolution import (
        CANDIDATE_MODEL_PROFILES,
        CANONICAL_MODEL_PROFILES,
        LIVE_EXPECTED_MODEL_PROFILES,
        MODEL_PROFILE_CHANNELS,
        PRODUCT_MODEL_PROFILES,
        SIMULATED_RESOURCE_FOR_MODEL,
    )
    from keysight_power_core.setpoint_ranges import SETPOINT_RANGES_BY_MODEL
    from keysight_power_core.support_policy import LIVE_SUPPORT_POLICY_REGISTRY
    from keysight_power_core.testing.simulator import SIMULATED_IDN

    active_or_candidate = PRODUCT_MODEL_PROFILES | CANDIDATE_MODEL_PROFILES
    stages = {
        model: info.enablement_stage for model, info in REGISTERED_MODELS.items()
    }
    stages.update({model: MODEL_ENABLEMENT_DE_SCOPED for model in DE_SCOPED_MODELS})
    simulator_idns = {
        model: SIMULATED_IDN[resource]
        for model, resource in SIMULATED_RESOURCE_FOR_MODEL.items()
        if resource in SIMULATED_IDN
    }
    command_capabilities = {
        model: command_support(model) for model in active_or_candidate
    }
    feature_inventories = {
        model: {
            command: expected_live_feature_inventory(model, command)
            for command, capability in capabilities.items()
            if capability.get("real") is True
            and command in FEATURE_AWARE_LIVE_COMMANDS
        }
        for model, capabilities in command_capabilities.items()
    }
    return ModelEnablementInventory(
        model_stages=stages,
        product_profiles=PRODUCT_MODEL_PROFILES,
        candidate_profiles=CANDIDATE_MODEL_PROFILES,
        canonical_profiles=CANONICAL_MODEL_PROFILES,
        live_expected_profiles=LIVE_EXPECTED_MODEL_PROFILES,
        channels=MODEL_PROFILE_CHANNELS,
        simulator_resources=SIMULATED_RESOURCE_FOR_MODEL,
        simulator_idns=simulator_idns,
        drivers=MODEL_DRIVERS,
        command_capabilities=command_capabilities,
        live_policies={policy.model: policy for policy in LIVE_SUPPORT_POLICY_REGISTRY},
        feature_inventories=feature_inventories,
        electrical_rating_models=frozenset(ELECTRICAL_RATINGS_BY_MODEL),
        setpoint_range_models=frozenset(SETPOINT_RANGES_BY_MODEL),
        product_rating_compatibility_models=PRODUCT_RATING_COMPATIBILITY_MODELS,
        safety_validated_models=frozenset(PRODUCT_MODEL_PROFILES),
        no_hardware_covered_models=frozenset(PRODUCT_MODEL_PROFILES),
    )


def validate_model_enablement(
    inventory: ModelEnablementInventory | None = None,
) -> None:
    """Fail when lifecycle stages and runtime prerequisites drift apart."""

    selected = inventory or current_model_enablement_inventory()
    stage_sets = {
        stage: frozenset(
            model for model, current_stage in selected.model_stages.items() if current_stage == stage
        )
        for stage in MODEL_ENABLEMENT_STAGES
    }
    unknown_stages = set(selected.model_stages.values()) - MODEL_ENABLEMENT_STAGES
    if unknown_stages:
        raise ValueError(f"unknown model enablement stage: {sorted(unknown_stages)}")
    noncanonical_models = [
        model for model in selected.model_stages if model != model.strip().upper()
    ]
    if noncanonical_models:
        raise ValueError(f"noncanonical model enablement metadata: {sorted(noncanonical_models)}")
    if "GENERIC" in selected.model_stages:
        raise ValueError("GENERIC is not a physical model-enablement stage")
    if stage_sets[MODEL_ENABLEMENT_PRODUCT_ACTIVE] != selected.product_profiles:
        raise ValueError("product model profiles do not match product_active lifecycle models")
    if stage_sets[MODEL_ENABLEMENT_CANDIDATE] != selected.candidate_profiles:
        raise ValueError("candidate model profiles do not match candidate lifecycle models")
    expected_canonical = selected.product_profiles | selected.candidate_profiles | {"GENERIC"}
    if selected.canonical_profiles != expected_canonical:
        raise ValueError("canonical model profiles must equal product + candidate + GENERIC")
    if selected.live_expected_profiles != selected.product_profiles | selected.candidate_profiles:
        raise ValueError("live expected-model profiles must equal product + candidate models")

    active_or_candidate = selected.product_profiles | selected.candidate_profiles
    forbidden = (
        stage_sets[MODEL_ENABLEMENT_CATALOG_ONLY]
        | stage_sets[MODEL_ENABLEMENT_DE_SCOPED]
    )
    leaked = forbidden & (
        selected.canonical_profiles
        | selected.live_expected_profiles
        | frozenset(selected.drivers)
        | frozenset(selected.simulator_resources)
        | frozenset(selected.live_policies)
    )
    if leaked:
        raise ValueError(f"catalog-only or de-scoped models leaked into active registries: {sorted(leaked)}")

    for model in sorted(active_or_candidate):
        _validate_enabled_model(selected, model, candidate=model in selected.candidate_profiles)


def _validate_enabled_model(
    inventory: ModelEnablementInventory,
    model: str,
    *,
    candidate: bool,
) -> None:
    if model not in inventory.channels or not inventory.channels[model]:
        raise ValueError(f"{model}: missing channel inventory")
    resource = inventory.simulator_resources.get(model)
    if not resource:
        raise ValueError(f"{model}: missing deterministic simulator resource")
    idn = inventory.simulator_idns.get(model)
    if not idn or parse_idn(idn).model != model:
        raise ValueError(f"{model}: missing deterministic matching simulator IDN")
    driver = inventory.drivers.get(model)
    if driver is None:
        raise ValueError(f"{model}: missing model-specific driver mapping")
    if getattr(driver, "__name__", "") == "GenericScpiPowerSupply":
        raise ValueError(f"{model}: candidate/active model cannot use Generic driver fallback")
    capabilities = inventory.command_capabilities.get(model)
    if not capabilities:
        raise ValueError(f"{model}: missing command capability metadata")
    policy = inventory.live_policies.get(model)
    if policy is None:
        raise ValueError(f"{model}: missing live support-policy metadata")
    if model not in inventory.no_hardware_covered_models:
        raise ValueError(f"{model}: missing simulator/fake/no-hardware coverage")
    if model not in inventory.safety_validated_models:
        raise ValueError(f"{model}: missing safety validation coverage")

    output_capable = any(
        entry.get("real") is True
        for command, entry in capabilities.items()
        if command in {
            "set", "apply", "output-on", "output-off", "safe-off", "cycle-output",
            "ramp", "ramp-list", "smoke-output", "sequence",
        }
    )
    if output_capable:
        has_ratings = model in inventory.electrical_rating_models
        product_compatibility = (
            not candidate
            and model in inventory.product_rating_compatibility_models
        )
        if not has_ratings and not product_compatibility:
            raise ValueError(f"{model}: missing electrical ratings")
        if model not in inventory.setpoint_range_models:
            raise ValueError(f"{model}: missing setpoint range/limit metadata")

    policies = {entry.command: entry for entry in policy.commands}
    for command, capability in capabilities.items():
        if capability.get("real") is not True:
            continue
        if command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS | PURE_OFFLINE_COMMANDS:
            continue
        command_policy = policies.get(command)
        if command_policy is None:
            raise ValueError(f"{model}/{command}: missing command policy classification")
        if command_policy.validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL:
            continue
        if candidate:
            if not command_policy.scopes:
                raise ValueError(f"{model}/{command}: candidate live command lacks exact pending scope")
            if any(
                scope.validation_status != VALIDATION_STATUS_TRANSPORT_PENDING
                for scope in command_policy.scopes
            ):
                raise ValueError(f"{model}/{command}: candidate scope is not exclusively pending")
            if command in FEATURE_AWARE_LIVE_COMMANDS:
                expected_features = inventory.feature_inventories.get(model, {}).get(command)
                if not expected_features:
                    raise ValueError(
                        f"{model}/{command}: candidate live command lacks canonical feature inventory"
                    )
                for scope in command_policy.scopes:
                    validate_live_feature_scope_metadata(
                        model=model,
                        command=command,
                        scope=scope,
                        expected_features=expected_features,
                    )
                    if any(
                        feature.validation_status != VALIDATION_STATUS_FEATURE_PENDING
                        for feature in scope.feature_scopes
                    ):
                        raise ValueError(
                            f"{model}/{command}: candidate implemented features must remain feature_pending"
                        )

    product_open = [
        scope
        for command_policy in policy.commands
        for scope in command_policy.scopes
        if scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
    ]
    if candidate and product_open:
        raise ValueError(f"{model}: candidate model has an accidental Product-open exact scope")
    if not candidate and not product_open:
        raise ValueError(f"{model}: Product-active model has no Product-open exact scope")
    if not candidate and any(
        not scope.evidence or not scope.artifact for scope in product_open
    ):
        raise ValueError(f"{model}: Product-open scope lacks accepted evidence metadata")
