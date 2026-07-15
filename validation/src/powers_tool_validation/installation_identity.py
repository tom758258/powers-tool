"""Verification of the prepared installed-wheel validation runtime."""

from __future__ import annotations

import base64
import csv
from email.parser import Parser
import hashlib
import hmac
from importlib import metadata
import json
from pathlib import Path
import sys
from typing import Any
import zipfile


MANIFEST_NAME = ".powers-tool-validation-installation.json"
KEY_NAME = ".powers-tool-validation-installation.key"
ARTIFACT_DIRECTORY = ".powers-tool-validation-artifacts"


class InstallationIdentityError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_path(distribution_name: str) -> Path:
    distribution = metadata.distribution(distribution_name)
    path = distribution.locate_file(f"{distribution._path.name}/RECORD")
    return Path(path).resolve()


def _verify_wheel(
    wheel: Path, distribution_name: str, version: str, expected_record_sha256: str
) -> set[Path]:
    distribution = metadata.distribution(distribution_name)
    install_root = Path(distribution.locate_file("")).resolve()
    verified: set[Path] = set()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        entry_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(metadata_names) != 1 or len(entry_names) != 1 or len(record_names) != 1:
            raise InstallationIdentityError("retained wheel metadata contract is invalid")
        message = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
        if message["Name"].lower() != distribution_name.lower() or message["Version"] != version:
            raise InstallationIdentityError("retained wheel distribution identity is invalid")
        if distribution_name == "powers-tool-validation":
            requirements = message.get_all("Requires-Dist", [])
            if not any(item.replace(" ", "").lower() == f"powers-tool=={version}" for item in requirements):
                raise InstallationIdentityError("Validation wheel does not require the exact Product version")
            if any(name.startswith(("powers_tool_core/", "powers_tool_cli/")) for name in names):
                raise InstallationIdentityError("Validation wheel contains Product packages")
        elif any(name.startswith("powers_tool_validation/") for name in names):
            raise InstallationIdentityError("Product wheel contains Validation packages")
        installed_metadata = Path(distribution.locate_file(metadata_names[0])).resolve()
        installed_entries = Path(distribution.locate_file(entry_names[0])).resolve()
        if installed_metadata.read_bytes() != archive.read(metadata_names[0]):
            raise InstallationIdentityError("installed METADATA differs from retained wheel")
        if installed_entries.read_bytes() != archive.read(entry_names[0]):
            raise InstallationIdentityError("installed entry points differ from retained wheel")
        for relative, digest_value, _size in csv.reader(
            archive.read(record_names[0]).decode("utf-8").splitlines()
        ):
            if not digest_value:
                continue
            algorithm, encoded = digest_value.split("=", 1)
            path = (install_root / relative).resolve()
            if algorithm != "sha256" or not path.is_file():
                raise InstallationIdentityError("installed wheel file is missing or unsupported")
            actual = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode("ascii")
            if not hmac.compare_digest(actual, encoded):
                raise InstallationIdentityError("installed file differs from retained wheel RECORD")
            verified.add(path)
    if not hmac.compare_digest(_sha256(_record_path(distribution_name)), expected_record_sha256):
        raise InstallationIdentityError("installed RECORD integrity check failed")
    return verified


def _origin_kind(module: Any, repository_root: Path | None) -> tuple[str, bool]:
    origin = Path(module.__file__).resolve()
    if repository_root is not None:
        roots = (repository_root / "src", repository_root / "validation" / "src")
        if any(origin == root.resolve() or root.resolve() in origin.parents for root in roots):
            return "source-tree", True
    prefix = Path(sys.prefix).resolve()
    return ("installed-wheel", False) if prefix in origin.parents else ("external", False)


def development_runtime_info(repository_root: Path) -> dict[str, Any]:
    import powers_tool_cli, powers_tool_core, powers_tool_validation
    kinds = [_origin_kind(module, repository_root) for module in (powers_tool_core, powers_tool_cli, powers_tool_validation)]
    return {"product_runtime_origin_kind": kinds[0][0], "product_cli_runtime_origin_kind": kinds[1][0], "validation_runtime_origin_kind": kinds[2][0], "repository_source_shadowed": any(item[1] for item in kinds), "installed_runtime_verified": False, "runtime_dependencies_verified": False, "retained_wheels_verified": False, "installed_files_record_verified": False, "module_origins_verified": False}


def verified_installation_identity() -> dict[str, Any]:
    import powers_tool_cli, powers_tool_core, powers_tool_validation
    prefix = Path(sys.prefix).resolve()
    try:
        document = json.loads((prefix / MANIFEST_NAME).read_text(encoding="utf-8"))
        key = (prefix / KEY_NAME).read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallationIdentityError("prepared installation identity is missing or malformed") from exc
    signature = document.pop("identity_hmac_sha256", None)
    if not isinstance(signature, str) or not key or not hmac.compare_digest(signature, hmac.new(key, _canonical(document), hashlib.sha256).hexdigest()):
        raise InstallationIdentityError("prepared installation identity integrity check failed")
    required = {"schema_version", "product_distribution_name", "product_version", "product_wheel_filename", "product_wheel_sha256", "product_installed_record_sha256", "validation_distribution_name", "validation_version", "validation_wheel_filename", "validation_wheel_sha256", "validation_installed_record_sha256", "source_commit", "source_dirty", "build_time", "python_version"}
    if set(document) != required or document.get("schema_version") != 2:
        raise InstallationIdentityError("prepared installation identity schema is invalid")
    if document["product_distribution_name"] != "powers-tool" or document["validation_distribution_name"] != "powers-tool-validation" or document["product_version"] != document["validation_version"]:
        raise InstallationIdentityError("prepared distribution identity is invalid")
    if metadata.version("powers-tool") != document["product_version"] or metadata.version("powers-tool-validation") != document["validation_version"]:
        raise InstallationIdentityError("installed distribution version differs from prepared identity")
    artifacts = prefix / ARTIFACT_DIRECTORY
    wheels = [artifacts / document["product_wheel_filename"], artifacts / document["validation_wheel_filename"]]
    for wheel, field in zip(wheels, ("product_wheel_sha256", "validation_wheel_sha256")):
        expected = document[field]
        if not isinstance(expected, str) or len(expected) != 64 or not wheel.is_file() or not hmac.compare_digest(_sha256(wheel), expected):
            raise InstallationIdentityError("retained wheel identity verification failed")
    product_files = _verify_wheel(wheels[0], "powers-tool", document["product_version"], document["product_installed_record_sha256"])
    validation_files = _verify_wheel(wheels[1], "powers-tool-validation", document["validation_version"], document["validation_installed_record_sha256"])
    modules = (powers_tool_core, powers_tool_cli, powers_tool_validation)
    origins = [Path(module.__file__).resolve() for module in modules]
    if origins[0] not in product_files or origins[1] not in product_files or origins[2] not in validation_files:
        raise InstallationIdentityError("loaded runtime module was not verified against retained wheels")
    kinds = [_origin_kind(module, None)[0] for module in modules]
    if kinds != ["installed-wheel"] * 3:
        raise InstallationIdentityError("runtime modules are not loaded from the prepared environment")
    import yaml, pyvisa
    if not callable(getattr(pyvisa.ResourceManager, "open_resource", None)):
        raise InstallationIdentityError("PyVISA ResourceManager path is unavailable")
    return {**document, "product_runtime_origin_kind": kinds[0], "product_cli_runtime_origin_kind": kinds[1], "validation_runtime_origin_kind": kinds[2], "repository_source_shadowed": False, "installed_runtime_verified": True, "runtime_dependencies_verified": bool(yaml and pyvisa), "retained_wheels_verified": True, "installed_files_record_verified": True, "module_origins_verified": True}
