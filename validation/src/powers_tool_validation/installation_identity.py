"""Verification of the prepared installed-wheel validation runtime."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
from importlib import metadata
import json
from pathlib import Path
import sys
from typing import Any


MANIFEST_NAME = ".powers-tool-validation-installation.json"
KEY_NAME = ".powers-tool-validation-installation.key"


class InstallationIdentityError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_record(distribution_name: str) -> bool:
    distribution = metadata.distribution(distribution_name)
    record = distribution.read_text("RECORD")
    if not record:
        return False
    root = Path(distribution.locate_file(""))
    for relative, digest_value, _size in csv.reader(record.splitlines()):
        if not digest_value:
            continue
        algorithm, encoded = digest_value.split("=", 1)
        if algorithm != "sha256":
            return False
        path = root / relative
        if not path.is_file():
            return False
        actual = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(actual, encoded):
            return False
    return True


def _origin_kind(module: Any, repository_root: Path | None) -> tuple[str, bool]:
    origin = Path(module.__file__).resolve()
    if repository_root is not None:
        source_roots = (repository_root / "src", repository_root / "validation" / "src")
        if any(origin == root.resolve() or root.resolve() in origin.parents for root in source_roots):
            return "source-tree", True
    prefix = Path(sys.prefix).resolve()
    return ("installed-wheel", False) if prefix in origin.parents else ("external", False)


def development_runtime_info(repository_root: Path) -> dict[str, Any]:
    import powers_tool_cli
    import powers_tool_core
    import powers_tool_validation

    product_kind, product_shadow = _origin_kind(powers_tool_core, repository_root)
    cli_kind, cli_shadow = _origin_kind(powers_tool_cli, repository_root)
    validation_kind, validation_shadow = _origin_kind(powers_tool_validation, repository_root)
    return {
        "product_runtime_origin_kind": product_kind,
        "product_cli_runtime_origin_kind": cli_kind,
        "validation_runtime_origin_kind": validation_kind,
        "repository_source_shadowed": product_shadow or cli_shadow or validation_shadow,
        "installed_runtime_verified": False,
    }


def verified_installation_identity() -> dict[str, Any]:
    import powers_tool_cli
    import powers_tool_core
    import powers_tool_validation

    prefix = Path(sys.prefix).resolve()
    manifest_path = prefix / MANIFEST_NAME
    key_path = prefix / KEY_NAME
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        key = key_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallationIdentityError("prepared installation identity is missing or malformed") from exc
    signature = document.pop("identity_hmac_sha256", None)
    if not isinstance(signature, str) or not key or not hmac.compare_digest(
        signature, hmac.new(key, _canonical(document), hashlib.sha256).hexdigest()
    ):
        raise InstallationIdentityError("prepared installation identity integrity check failed")
    required = {
        "schema_version", "product_distribution_name", "product_version",
        "product_wheel_filename", "product_wheel_sha256",
        "validation_distribution_name", "validation_version",
        "validation_wheel_filename", "validation_wheel_sha256", "source_commit",
        "source_dirty", "build_time", "python_version",
    }
    if set(document) != required or document.get("schema_version") != 1:
        raise InstallationIdentityError("prepared installation identity schema is invalid")
    if document["product_distribution_name"] != "powers-tool" or document["validation_distribution_name"] != "powers-tool-validation":
        raise InstallationIdentityError("prepared distribution identity is invalid")
    if metadata.version("powers-tool") != document["product_version"] or metadata.version("powers-tool-validation") != document["validation_version"]:
        raise InstallationIdentityError("installed distribution version differs from prepared identity")
    for field in ("product_wheel_sha256", "validation_wheel_sha256"):
        value = document.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise InstallationIdentityError("prepared wheel identity is invalid")
    if not _verify_record("powers-tool") or not _verify_record("powers-tool-validation"):
        raise InstallationIdentityError("installed distribution RECORD verification failed")
    kinds = [_origin_kind(module, None)[0] for module in (powers_tool_core, powers_tool_cli, powers_tool_validation)]
    if kinds != ["installed-wheel", "installed-wheel", "installed-wheel"]:
        raise InstallationIdentityError("runtime modules are not loaded from the prepared environment")
    if any(Path(entry).resolve() in {Path.cwd().resolve() / "src", Path.cwd().resolve() / "validation" / "src"} for entry in sys.path if entry):
        raise InstallationIdentityError("repository source path shadows the installed runtime")
    return {
        **document,
        "product_runtime_origin_kind": kinds[0],
        "product_cli_runtime_origin_kind": kinds[1],
        "validation_runtime_origin_kind": kinds[2],
        "repository_source_shadowed": False,
        "installed_runtime_verified": True,
        "installed_files_record_verified": True,
    }
