from __future__ import annotations

import os

import pytest

from powers_tool_cli import cli
from powers_tool_core.build_profile import BuildProfile, PRODUCT_BUILD_IDENTITY


@pytest.mark.parametrize(
    "argument",
    [
        "--validation-candidate-manifest",
        "--validation-candidate-capability",
        "--validation-candidate-context-root",
        "--validation-candidate-case-id",
        "--validation-candidate-suite",
    ],
)
def test_product_parser_rejects_candidate_capability_arguments(argument: str) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["output-on", argument, "forged"])


def test_product_build_identity_is_immutable_product_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POWERS_TOOL_BUILD_PROFILE", "validation")
    monkeypatch.setenv("POWERS_TOOL_VALIDATION_RUN_SECRET", "forged")
    assert PRODUCT_BUILD_IDENTITY.profile is BuildProfile.PRODUCT
    assert PRODUCT_BUILD_IDENTITY.distribution_name == "powers-tool"
