import re
from dataclasses import replace
from pathlib import Path

import pytest

from keysight_power_core.drivers.generic_scpi import GenericScpiPowerSupply
from keysight_power_core.model_enablement import (
    ModelEnablementInventory,
    current_model_enablement_inventory,
    validate_model_enablement,
)
from keysight_power_core.model_resolution import (
    CANDIDATE_MODEL_PROFILES,
    CANONICAL_MODEL_PROFILES,
    LIVE_EXPECTED_MODEL_PROFILES,
    PRODUCT_MODEL_PROFILES,
)
from keysight_power_core.models import (
    CANDIDATE_MODELS,
    CATALOG_ONLY_MODELS,
    DE_SCOPED_MODELS,
    PRODUCT_ACTIVE_MODELS,
)
from keysight_power_core.support_policy import (
    BACKEND_SYSTEM_VISA,
    TRANSPORT_USB,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_PROFILE_VALIDATED,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    CommandLiveSupportScope,
    CommandSupportPolicy,
    ModelSupportPolicy,
)


def _synthetic_candidate() -> ModelEnablementInventory:
    current = current_model_enablement_inventory()
    model = "SYNTH1"
    policy = ModelSupportPolicy(
        model=model,
        commands=(
            CommandSupportPolicy(
                command="measure",
                validation_status=VALIDATION_STATUS_PROFILE_VALIDATED,
                scopes=(
                    CommandLiveSupportScope(
                        validation_status=VALIDATION_STATUS_TRANSPORT_PENDING,
                        transport_scope=TRANSPORT_USB,
                        backend_scope=BACKEND_SYSTEM_VISA,
                        note="Synthetic candidate pending validation.",
                    ),
                ),
            ),
        ),
    )
    return replace(
        current,
        model_stages={**current.model_stages, model: "candidate"},
        candidate_profiles=current.candidate_profiles | {model},
        canonical_profiles=current.canonical_profiles | {model},
        live_expected_profiles=current.live_expected_profiles | {model},
        channels={**current.channels, model: (1,)},
        simulator_resources={**current.simulator_resources, model: "USB0::SIM::SYNTH1::INSTR"},
        simulator_idns={**current.simulator_idns, model: "KEYSIGHT,SYNTH1,SIM000001,1.0"},
        drivers={**current.drivers, model: type("SynthPowerSupply", (), {})},
        command_capabilities={
            **current.command_capabilities,
            model: {"measure": {"real": True, "simulate": True, "dry_run": True}},
        },
        live_policies={**current.live_policies, model: policy},
        safety_validated_models=current.safety_validated_models | {model},
        no_hardware_covered_models=current.no_hardware_covered_models | {model},
    )


def test_current_model_enablement_stage_sets_are_exact_and_disjoint() -> None:
    assert PRODUCT_ACTIVE_MODELS == {"E36312A", "EDU36311A", "E3646A"}
    assert CANDIDATE_MODELS == frozenset()
    assert CATALOG_ONLY_MODELS == {"E36313A", "E36233A", "E36441A", "E36155A"}
    assert DE_SCOPED_MODELS == {"E36103B", "E36232A"}
    stage_sets = [PRODUCT_ACTIVE_MODELS, CANDIDATE_MODELS, CATALOG_ONLY_MODELS, DE_SCOPED_MODELS]
    assert all(not left & right for index, left in enumerate(stage_sets) for right in stage_sets[index + 1 :])
    assert PRODUCT_MODEL_PROFILES == PRODUCT_ACTIVE_MODELS
    assert CANDIDATE_MODEL_PROFILES == frozenset()
    assert CANONICAL_MODEL_PROFILES == PRODUCT_ACTIVE_MODELS | {"GENERIC"}
    assert LIVE_EXPECTED_MODEL_PROFILES == PRODUCT_ACTIVE_MODELS


def test_current_model_enablement_inventory_is_consistent() -> None:
    validate_model_enablement()


def test_complete_synthetic_candidate_inventory_passes() -> None:
    validate_model_enablement(_synthetic_candidate())


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("channels", {}, "missing channel inventory"),
        ("simulator_resources", {}, "missing deterministic simulator resource"),
        ("simulator_idns", {}, "missing deterministic matching simulator IDN"),
        ("drivers", {}, "missing model-specific driver mapping"),
        ("command_capabilities", {}, "missing command capability metadata"),
        ("live_policies", {}, "missing live support-policy metadata"),
        ("safety_validated_models", frozenset(), "missing safety validation coverage"),
        ("no_hardware_covered_models", frozenset(), "missing simulator/fake/no-hardware coverage"),
    ],
)
def test_candidate_missing_one_prerequisite_fails_precisely(
    field: str, value: object, match: str
) -> None:
    candidate = _synthetic_candidate()
    current_value = getattr(candidate, field)
    if isinstance(current_value, dict):
        replacement = {key: item for key, item in current_value.items() if key != "SYNTH1"}
    else:
        replacement = current_value - {"SYNTH1"}
    with pytest.raises(ValueError, match=match):
        validate_model_enablement(replace(candidate, **{field: replacement}))


def test_candidate_cannot_use_generic_driver_fallback() -> None:
    candidate = _synthetic_candidate()
    with pytest.raises(ValueError, match="Generic driver fallback"):
        validate_model_enablement(
            replace(candidate, drivers={**candidate.drivers, "SYNTH1": GenericScpiPowerSupply})
        )


def test_candidate_cannot_have_product_open_scope() -> None:
    candidate = _synthetic_candidate()
    policy = candidate.live_policies["SYNTH1"]
    command = policy.commands[0]
    validated_scope = replace(
        command.scopes[0],
        validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        evidence="Synthetic accepted evidence.",
        artifact="synthetic/report.json",
    )
    changed = replace(policy, commands=(replace(command, scopes=(validated_scope,)),))
    with pytest.raises(ValueError, match="not exclusively pending|accidental Product-open"):
        validate_model_enablement(
            replace(candidate, live_policies={**candidate.live_policies, "SYNTH1": changed})
        )


def test_output_candidate_requires_limits_ranges_and_safety_metadata() -> None:
    candidate = _synthetic_candidate()
    capabilities = {
        **candidate.command_capabilities["SYNTH1"],
        "set": {"real": True, "simulate": True, "dry_run": True},
    }
    measure_policy = candidate.live_policies["SYNTH1"].commands[0]
    set_policy = replace(measure_policy, command="set")
    policy = replace(
        candidate.live_policies["SYNTH1"],
        commands=(measure_policy, set_policy),
    )
    candidate = replace(
        candidate,
        command_capabilities={**candidate.command_capabilities, "SYNTH1": capabilities},
        live_policies={**candidate.live_policies, "SYNTH1": policy},
    )
    with pytest.raises(ValueError, match="electrical rating or range-dependent output limits"):
        validate_model_enablement(candidate)


def test_catalog_and_descoped_models_do_not_leak_into_active_registries() -> None:
    inventory = current_model_enablement_inventory()
    forbidden = CATALOG_ONLY_MODELS | DE_SCOPED_MODELS
    assert forbidden.isdisjoint(inventory.canonical_profiles)
    assert forbidden.isdisjoint(inventory.live_expected_profiles)
    assert forbidden.isdisjoint(inventory.drivers)
    assert forbidden.isdisjoint(inventory.simulator_resources)
    assert forbidden.isdisjoint(inventory.live_policies)


def test_product_ui_and_wrapper_targets_match_product_active_models() -> None:
    index_html = Path("src/keysight_power_webui/static/index.html").read_text(encoding="utf-8")
    webui_models = frozenset(
        re.findall(r'<option value="([A-Z0-9]+)">Require ', index_html)
    )
    assert webui_models == PRODUCT_ACTIVE_MODELS
    wrapper = Path("scripts/live-cli-check.ps1").read_text(encoding="utf-8")
    target_line = next(
        line for line in wrapper.splitlines() if line.startswith("$SupportedTargets = @(")
    )
    assert frozenset(re.findall(r'"([A-Z0-9]+)"', target_line)) == PRODUCT_ACTIVE_MODELS
