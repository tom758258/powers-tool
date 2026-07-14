"""Entry point for the internal Powers Tool validation distribution."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Sequence

from powers_tool_core.support_policy import internal_validation_candidate_inventory
from powers_tool_validation import __version__, candidate_capability
from powers_tool_validation.build_identity import VALIDATION_BUILD_IDENTITY
from powers_tool_validation.runtime_extension import ValidationRuntimeExtension


def _inventory_payload() -> dict[str, Any]:
    return {
        model_id: {
            "commands": list(entry["commands"]),
            "connections": [list(connection) for connection in entry["connections"]],
        }
        for model_id, entry in internal_validation_candidate_inventory().items()
    }


def _build_info_payload() -> dict[str, Any]:
    identity = VALIDATION_BUILD_IDENTITY
    return {
        "schema_version": 1,
        "distribution_name": identity.distribution_name,
        "validation_distribution_version": identity.version,
        "product_package_version": identity.product_version,
        "build_profile": identity.profile.value,
        "source_commit": identity.source_commit,
        "source_dirty": identity.source_dirty,
        "artifact_kind": identity.artifact_kind,
        "package_hash": identity.package_hash,
        "validation_runtime_available": True,
        "candidate_inventory_available": bool(_inventory_payload()),
        "entry_point": "powers-tool-validation",
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"powers-tool-validation {__version__}")
        return 0
    if arguments == ["_internal-build-info", "--json"]:
        print(json.dumps(_build_info_payload(), sort_keys=True))
        return 0
    if arguments == ["_internal-candidate-inventory", "--json"]:
        print(json.dumps(_inventory_payload(), sort_keys=True))
        return 0
    if arguments and arguments[0] in {"issue-manifest", "issue-capability"}:
        try:
            return candidate_capability._helper_main(arguments)
        except candidate_capability.CandidateCapabilityError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    from powers_tool_cli import cli as product_cli

    product_cli._install_distribution_runtime_extension(ValidationRuntimeExtension())
    try:
        return product_cli.main(arguments)
    finally:
        product_cli._install_distribution_runtime_extension(None)


if __name__ == "__main__":
    raise SystemExit(main())
