#!/usr/bin/env python3
"""Credential-free architecture contract for the flags-2-env adopted workspace."""

from __future__ import annotations

import configparser
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "architecture-contract" / "capability.json"
ZPKG_PATH = ROOT / ".zpkg.toml"
GITMODULES_PATH = ROOT / ".gitmodules"

CREDENTIAL_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\blin_api_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bcfat_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ObservedContract:
    package_identity: str
    version_requirement: str
    install_directory: str
    submodule_path: str
    submodule_url: str


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_contract(text: str) -> dict[str, object]:
    value = json.loads(text)
    required = {
        "schemaVersion",
        "profile",
        "productionPeer",
        "sourceRepository",
        "packageIdentity",
        "versionRequirement",
        "installDirectory",
        "submodulePath",
        "submoduleUrl",
        "ownershipMode",
        "physicalCheckoutCount",
        "credentialClass",
    }
    if set(value) != required:
        fail(f"capability keys changed: {sorted(set(value) ^ required)}")
    if value["schemaVersion"] != 1:
        fail("schemaVersion must remain 1")
    if value["profile"] != "test-consumer":
        fail("profile must remain test-consumer")
    if value["productionPeer"] != "flags-2-env":
        fail("productionPeer must remain flags-2-env")
    if value["ownershipMode"] != "same-path-adopted-workspace":
        fail("ownershipMode must remain same-path-adopted-workspace")
    if value["physicalCheckoutCount"] != 1:
        fail("the fixture must own exactly one physical checkout")
    if value["credentialClass"] != "none":
        fail("this fixture must remain credential-free")
    return value


def parse_zpkg(text: str) -> tuple[str, str, str]:
    value = tomllib.loads(text)
    dependencies = value.get("dependencies")
    if not isinstance(dependencies, dict) or len(dependencies) != 1:
        fail(".zpkg.toml must declare exactly one dependency")
    package_identity, version = next(iter(dependencies.items()))
    install_directory = value.get("install", {}).get("dir")
    if not isinstance(package_identity, str) or not isinstance(version, str):
        fail("Zed dependency identity and version must be strings")
    if not isinstance(install_directory, str):
        fail("Zed install.dir must be a string")
    return package_identity, version, install_directory


def parse_gitmodules(text: str) -> tuple[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    sections = parser.sections()
    if len(sections) != 1:
        fail(".gitmodules must declare exactly one source checkout")
    section = parser[sections[0]]
    path = section.get("path")
    url = section.get("url")
    if not path or not url:
        fail("submodule path and URL are required")
    return path, url


def observe(contract_text: str, zpkg_text: str, gitmodules_text: str) -> ObservedContract:
    contract = parse_contract(contract_text)
    package_identity, version, install_directory = parse_zpkg(zpkg_text)
    submodule_path, submodule_url = parse_gitmodules(gitmodules_text)

    expected_path = f"{install_directory.rstrip('/')}/{package_identity}"
    if submodule_path != expected_path:
        fail(f"submodule path {submodule_path!r} does not equal adopted Zed path {expected_path!r}")
    if contract["packageIdentity"] != package_identity:
        fail("capability package identity disagrees with .zpkg.toml")
    if contract["versionRequirement"] != version:
        fail("capability version requirement disagrees with .zpkg.toml")
    if contract["installDirectory"] != install_directory:
        fail("capability install directory disagrees with .zpkg.toml")
    if contract["submodulePath"] != submodule_path:
        fail("capability submodule path disagrees with .gitmodules")
    if contract["submoduleUrl"] != submodule_url:
        fail("capability submodule URL disagrees with .gitmodules")

    source_repository = str(contract["sourceRepository"])
    expected_url = f"https://github.com/{source_repository}"
    if submodule_url.rstrip("/").removesuffix(".git").lower() != expected_url.lower():
        fail("submodule URL does not resolve to the canonical source repository")
    if package_identity.lower() != source_repository.lower():
        fail("Zed package identity and canonical source repository disagree")

    serialized = "\n".join((contract_text, zpkg_text, gitmodules_text))
    for pattern in CREDENTIAL_PATTERNS:
        if pattern.search(serialized):
            fail("architecture contract contains credential-like material")

    return ObservedContract(
        package_identity=package_identity,
        version_requirement=version,
        install_directory=install_directory,
        submodule_path=submodule_path,
        submodule_url=submodule_url,
    )


def gitlink_sha(path: str) -> str:
    result = subprocess.run(
        ["git", "ls-tree", "HEAD", "--", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    fields = result.stdout.strip().split()
    if len(fields) != 4 or fields[0] != "160000" or fields[1] != "commit":
        fail(f"{path} is not an exact Git submodule gitlink")
    sha = fields[2]
    if not SHA_PATTERN.fullmatch(sha):
        fail("gitlink does not contain an immutable 40-character commit SHA")
    return sha


def expect_failure(name: str, fn: Callable[[], object], contains: str) -> None:
    try:
        fn()
    except AssertionError as error:
        if contains not in str(error):
            fail(f"negative mutation {name!r} failed for the wrong reason: {error}")
    else:
        fail(f"negative mutation {name!r} unexpectedly passed")


def main() -> None:
    contract_text = CONTRACT_PATH.read_text(encoding="utf-8")
    zpkg_text = ZPKG_PATH.read_text(encoding="utf-8")
    gitmodules_text = GITMODULES_PATH.read_text(encoding="utf-8")
    observed = observe(contract_text, zpkg_text, gitmodules_text)
    sha = gitlink_sha(observed.submodule_path)

    expect_failure(
        "overlapping path",
        lambda: observe(
            contract_text,
            zpkg_text,
            gitmodules_text.replace(observed.submodule_path, ".vendor/duplicate/flags-2-env"),
        ),
        "does not equal adopted Zed path",
    )
    expect_failure(
        "wrong source",
        lambda: observe(
            contract_text,
            zpkg_text,
            gitmodules_text.replace("ORESoftware/flags-2-env", "example/flags-2-env"),
        ),
        "disagrees with .gitmodules",
    )
    expect_failure(
        "second dependency",
        lambda: observe(
            contract_text,
            zpkg_text.replace(
                '"oresoftware/flags-2-env" = "^0.2.0"',
                '"oresoftware/flags-2-env" = "^0.2.0"\n"example/duplicate" = "1.0.0"',
            ),
            gitmodules_text,
        ),
        "exactly one dependency",
    )

    fake_secret = f"github_pat_{'A' * 40}"
    expect_failure(
        "credential material",
        lambda: observe(
            contract_text.replace('"versionRequirement": "^0.2.0"', f'"versionRequirement": "{fake_secret}"'),
            zpkg_text.replace('"^0.2.0"', f'"{fake_secret}"'),
            gitmodules_text,
        ),
        "credential-like material",
    )

    print(
        "architecture-contract OK: "
        f"{observed.package_identity}@{observed.version_requirement} -> "
        f"{observed.submodule_path} gitlink={sha} physical_checkouts=1 negative_mutations=4"
    )


if __name__ == "__main__":
    main()
