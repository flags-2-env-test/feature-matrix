#!/usr/bin/env python3
"""Independent conformance tests for ORESoftware/flags-2-env PR #32.

The test organization downloads the public contract at one immutable commit,
constructs a complete six-target/two-kind artifact tree, and then proves the
producer's validator rejects semantic mutations that JSON Schema alone cannot
express.
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
PIN_PATH = HERE / "source-pin.json"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TIER_ONE = {
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl",
}
DEFERRED = {
    "x86_64-pc-windows-msvc",
    "x86_64-pc-windows-gnu",
    "wasm32-wasip1",
    "i686-unknown-linux-gnu",
}
KINDS = ("static", "shared")


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "flags-2-env-test-prebuilt-contract/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            fail(f"download failed with HTTP {response.status}: {url}")
        return response.read()


def materialize_source(root: pathlib.Path) -> dict[str, Any]:
    pin = load_json(PIN_PATH)
    if pin.get("schema") != "flags-2-env-test/source-pin/v1":
        fail("unsupported source pin schema")
    repository = pin.get("repository")
    commit = pin.get("commit")
    files = pin.get("files")
    if repository != "ORESoftware/flags-2-env":
        fail(f"unexpected producer repository: {repository!r}")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        fail("source pin commit must be a full lowercase Git SHA")
    if files != [
        "prebuilt/targets.json",
        "prebuilt/manifest.schema.json",
        "scripts/validate-prebuilt-contract.py",
    ]:
        fail("source pin file set drifted")

    for relative in files:
        url = f"https://raw.githubusercontent.com/{repository}/{commit}/{relative}"
        payload = download(url)
        if not payload:
            fail(f"pinned producer file is empty: {relative}")
        if any(marker in payload for marker in (b"ghp_", b"lin_api_", b"cfat_")):
            fail(f"credential-like content found in producer file: {relative}")
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    validator = root / "scripts/validate-prebuilt-contract.py"
    subprocess.run(
        [sys.executable, "-m", "py_compile", str(validator)],
        check=True,
        cwd=root,
    )
    return pin


def expected_filename(target: str, kind: str) -> str:
    if kind == "static":
        return "libflags2env.a"
    if target.endswith("apple-darwin"):
        return "libflags2env.dylib"
    return "libflags2env.so"


def toolchain(target: str) -> tuple[str, str, str, str, list[str]]:
    if target.endswith("apple-darwin"):
        return (
            "Apple clang 18.0.0",
            "ld64 1230.0",
            "llvm-ar 18.1.8",
            "MacOSX15.0.sdk",
            ["-O2", "-fvisibility=hidden"],
        )
    return (
        "zig cc 0.14.1",
        "lld 19.1.7",
        "llvm-ar 19.1.7",
        f"zig-libc:{target}",
        ["-O2", "-fvisibility=hidden", f"-target={target}"],
    )


def build_valid_fixture(root: pathlib.Path) -> dict[str, Any]:
    policy = load_json(root / "prebuilt/targets.json")
    target_entries = {
        item["triple"]: item
        for item in policy["targets"]
        if isinstance(item, dict) and item.get("tier") == 1
    }
    if set(target_entries) != TIER_ONE:
        fail(f"Tier 1 set drifted: {sorted(target_entries)}")

    artifacts: list[dict[str, Any]] = []
    symbol_digest = hashlib.sha256(b"flags2env_parse\nflags2env_version\n").hexdigest()
    for target in sorted(TIER_ONE):
        compiler, linker, archiver, sdk, flags = toolchain(target)
        for kind in KINDS:
            filename = expected_filename(target, kind)
            relative = pathlib.PurePosixPath("prebuilt") / target / filename
            payload = f"flags-2-env fixture\ntarget={target}\nkind={kind}\n".encode()
            artifact_path = root / pathlib.Path(relative)
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(payload)
            artifact: dict[str, Any] = {
                "target": target,
                "kind": kind,
                "path": relative.as_posix(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "exported_symbols_sha256": symbol_digest,
                "minimum_runtime": target_entries[target]["minimum_runtime"],
                "compiler": compiler,
                "linker": linker,
                "archiver": archiver,
                "sdk_or_sysroot": sdk,
                "compile_flags": flags,
            }
            if kind == "shared":
                artifact["soname_or_install_name"] = (
                    "@rpath/libflags2env.dylib"
                    if target.endswith("apple-darwin")
                    else "libflags2env.so.1"
                )
            artifacts.append(artifact)

    manifest = {
        "schema_version": 1,
        "package_version": "0.3.0-test.1",
        "abi_version": 1,
        "source_commit": "a" * 40,
        "source_input_sha256": "b" * 64,
        "source_date_epoch": 1_767_225_600,
        "artifacts": artifacts,
    }
    (root / "prebuilt/manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def run_validator(root: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/validate-prebuilt-contract.py",
            "--require-manifest",
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def assert_rejected(
    valid_root: pathlib.Path,
    cases_root: pathlib.Path,
    name: str,
    mutate: Callable[[pathlib.Path, dict[str, Any]], None],
    expected_message: str,
) -> None:
    case_root = cases_root / name
    shutil.copytree(valid_root, case_root)
    manifest_path = case_root / "prebuilt/manifest.json"
    manifest = load_json(manifest_path)
    mutate(case_root, manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = run_validator(case_root)
    if result.returncode == 0:
        fail(f"negative case {name!r} unexpectedly passed")
    output = result.stdout + result.stderr
    if expected_message not in output:
        fail(
            f"negative case {name!r} did not report {expected_message!r}:\n{output}"
        )


def inspect_contract(root: pathlib.Path) -> None:
    policy = load_json(root / "prebuilt/targets.json")
    schema = load_json(root / "prebuilt/manifest.schema.json")

    tier_one_entries = [item for item in policy["targets"] if item["tier"] == 1]
    if {item["triple"] for item in tier_one_entries} != TIER_ONE:
        fail("policy Tier 1 targets do not match the reviewed set")
    for item in tier_one_entries:
        owner = item.get("fixture_owner")
        if not isinstance(owner, str) or not owner.startswith(
            "flags-2-env-test/rust-app "
        ):
            fail(f"Tier 1 owner is not a named test-org lane: {owner!r}")
    if set(policy["deferred_targets"]) != DEFERRED:
        fail("deferred target set drifted")
    if policy["artifact_kinds"] != list(KINDS):
        fail("artifact kind policy drifted")

    top_required = set(schema["required"])
    if "source_date_epoch" not in top_required:
        fail("schema must require source_date_epoch")
    artifacts = schema["properties"]["artifacts"]
    if artifacts.get("minItems") != 12 or artifacts.get("uniqueItems") is not True:
        fail("schema must require at least the complete Tier 1 matrix")

    artifact = schema["$defs"]["artifact"]
    if "sdk_or_sysroot" not in artifact["required"]:
        fail("schema must require SDK/sysroot provenance")
    if not artifact.get("allOf"):
        fail("schema must conditionally require shared-library identity")
    for field in ("soname_or_install_name", "sdk_or_sysroot", "provenance", "signature"):
        if artifact["properties"][field].get("type") != "string":
            fail(f"{field} must be omitted when absent, not null")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="flags-prebuilt-contract-") as temp:
        temp_root = pathlib.Path(temp)
        valid_root = temp_root / "valid"
        valid_root.mkdir()
        pin = materialize_source(valid_root)
        inspect_contract(valid_root)
        valid_manifest = build_valid_fixture(valid_root)

        valid_result = run_validator(valid_root)
        if valid_result.returncode != 0:
            fail(
                "valid complete manifest failed producer validation:\n"
                + valid_result.stdout
                + valid_result.stderr
            )
        if "validated prebuilt manifest: 12 artifacts" not in valid_result.stdout:
            fail(f"valid result lacked manifest evidence:\n{valid_result.stdout}")

        cases_root = temp_root / "negative"
        cases_root.mkdir()

        assert_rejected(
            valid_root,
            cases_root,
            "missing-tier1-shared",
            lambda _root, manifest: manifest["artifacts"].pop(),
            "manifest lacks Tier 1 artifacts",
        )

        def duplicate_identity(_root: pathlib.Path, manifest: dict[str, Any]) -> None:
            duplicate = copy.deepcopy(manifest["artifacts"][0])
            duplicate["sha256"] = "c" * 64
            manifest["artifacts"].append(duplicate)

        assert_rejected(
            valid_root,
            cases_root,
            "duplicate-target-kind",
            duplicate_identity,
            "duplicate artifact identity",
        )

        assert_rejected(
            valid_root,
            cases_root,
            "target-path-mismatch",
            lambda _root, manifest: manifest["artifacts"][0].__setitem__(
                "path", "prebuilt/x86_64-unknown-linux-gnu/libflags2env.a"
            ),
            ".path must be",
        )
        assert_rejected(
            valid_root,
            cases_root,
            "runtime-floor-mismatch",
            lambda _root, manifest: manifest["artifacts"][0].__setitem__(
                "minimum_runtime", "glibc 2.17"
            ),
            ".minimum_runtime must match targets.json",
        )

        def static_with_soname(_root: pathlib.Path, manifest: dict[str, Any]) -> None:
            static = next(item for item in manifest["artifacts"] if item["kind"] == "static")
            static["soname_or_install_name"] = "libflags2env.so.1"

        assert_rejected(
            valid_root,
            cases_root,
            "static-soname",
            static_with_soname,
            "soname_or_install_name is invalid for a static library",
        )

        def shared_without_soname(_root: pathlib.Path, manifest: dict[str, Any]) -> None:
            shared = next(item for item in manifest["artifacts"] if item["kind"] == "shared")
            shared.pop("soname_or_install_name")

        assert_rejected(
            valid_root,
            cases_root,
            "shared-missing-soname",
            shared_without_soname,
            ".soname_or_install_name must be a nonempty string",
        )
        assert_rejected(
            valid_root,
            cases_root,
            "null-optional",
            lambda _root, manifest: manifest["artifacts"][0].__setitem__(
                "signature", None
            ),
            ".signature must be a nonempty string",
        )

        def deferred_target(_root: pathlib.Path, manifest: dict[str, Any]) -> None:
            manifest["artifacts"][0]["target"] = "x86_64-pc-windows-msvc"

        assert_rejected(
            valid_root,
            cases_root,
            "deferred-target",
            deferred_target,
            ".target is not active in targets.json",
        )

        def tamper_bytes(root: pathlib.Path, manifest: dict[str, Any]) -> None:
            path = root / manifest["artifacts"][0]["path"]
            path.write_bytes(path.read_bytes() + b"tampered\n")

        assert_rejected(
            valid_root,
            cases_root,
            "tampered-bytes",
            tamper_bytes,
            ".size does not match",
        )
        assert_rejected(
            valid_root,
            cases_root,
            "missing-source-date-epoch",
            lambda _root, manifest: manifest.pop("source_date_epoch"),
            "source_date_epoch must be a nonnegative integer",
        )
        assert_rejected(
            valid_root,
            cases_root,
            "missing-sdk",
            lambda _root, manifest: manifest["artifacts"][0].__setitem__(
                "sdk_or_sysroot", None
            ),
            ".sdk_or_sysroot must be a nonempty string",
        )

        def duplicate_compile_flag(_root: pathlib.Path, manifest: dict[str, Any]) -> None:
            flags = manifest["artifacts"][0]["compile_flags"]
            flags.append(flags[0])

        assert_rejected(
            valid_root,
            cases_root,
            "duplicate-compile-flag",
            duplicate_compile_flag,
            ".compile_flags must not contain duplicates",
        )

        if len(valid_manifest["artifacts"]) != 12:
            fail("fixture did not build the six-target/two-kind matrix")
        print(
            "prebuilt contract conformance OK: "
            f"producer={pin['repository']}@{pin['commit'][:12]}, "
            "1 positive + 11 adversarial manifests"
        )


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"prebuilt contract test failure: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
