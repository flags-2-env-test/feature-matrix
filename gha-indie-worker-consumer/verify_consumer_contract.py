#!/usr/bin/env python3
"""Independent consumer conformance for gha-indie-worker native dispatches."""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform as host_platform
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WORKER_SHA = "8e6be9ce13d07caf189bd4cdd57cb39a019d7b31"
RUST_TOOLCHAIN = "1.97.0"
REPOSITORY_URL = "https://github.com/flags-2-env-test/feature-matrix.git"
MANIFEST_DIGEST = "sha256:" + "f" * 64
PROFILE_DIGESTS = {
    "linux-rust": "sha256:" + "1" * 64,
    "windows-msvc": "sha256:" + "2" * 64,
    "macos-xcode": "sha256:" + "3" * 64,
}


class ConformanceFailure(RuntimeError):
    """Raised when the external consumer contract is violated."""


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        raise ConformanceFailure(
            "command failed\n"
            f"command: {command!r}\n"
            f"exit: {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def parse_cli_error(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if completed.returncode == 0:
        raise ConformanceFailure("expected the binder to fail closed")
    for line in reversed(completed.stderr.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("code"), str):
            return value
    raise ConformanceFailure(
        f"binder failure did not end in structured JSON:\n{completed.stderr}"
    )


def expect_error(
    command: list[str],
    expected_code: str,
    *,
    env: dict[str, str],
) -> str:
    error = parse_cli_error(run(command, env=env, check=False))
    actual = error["code"]
    if actual != expected_code:
        raise ConformanceFailure(
            f"expected error code {expected_code!r}, received {actual!r}: {error}"
        )
    return actual


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def job(base_job_id: str, platform: str, architecture: str) -> dict[str, Any]:
    return {
        "id": base_job_id,
        "baseJobId": base_job_id,
        "name": base_job_id,
        "needs": [],
        "needsInstances": [],
        "runsOn": ["self-hosted", "gha-indie-worker", platform, architecture],
        "reusableWorkflow": None,
        "condition": None,
        "matrix": {},
        "env": {},
        "steps": [],
        "failFast": True,
        "maxParallel": 1,
        "timeoutMinutes": None,
        "continueOnError": None,
    }


def build_plan() -> dict[str, Any]:
    return {
        "schemaVersion": "gha-indie-worker.plan.v1",
        "name": "flags-2-env-feature-matrix",
        "jobOrder": ["linux", "windows", "macos"],
        "jobs": [
            job("linux", "linux", "x64"),
            job("windows", "windows", "x64"),
            job("macos", "macos", "arm64"),
        ],
    }


def build_catalog() -> dict[str, Any]:
    return {
        "schemaVersion": "gha-indie-worker.profile-catalog.v2",
        "profiles": [
            {
                "name": "linux-rust",
                "digest": PROFILE_DIGESTS["linux-rust"],
                "runner": {
                    "platform": "linux",
                    "architecture": "x64",
                    "capabilities": ["cargo-cache"],
                },
            },
            {
                "name": "windows-msvc",
                "digest": PROFILE_DIGESTS["windows-msvc"],
                "runner": {
                    "platform": "windows",
                    "architecture": "x64",
                    "capabilities": [
                        "windows-sdk",
                        "native",
                        "powershell",
                        "msvc",
                    ],
                },
            },
            {
                "name": "macos-xcode",
                "digest": PROFILE_DIGESTS["macos-xcode"],
                "runner": {
                    "platform": "macos",
                    "architecture": "arm64",
                    "capabilities": [
                        "xcode",
                        "native",
                        "swift",
                        "ios-simulator",
                    ],
                },
            },
        ],
    }


def cargo_command(manifest: Path, *arguments: str) -> list[str]:
    return [
        "cargo",
        "run",
        "--locked",
        "--quiet",
        "--manifest-path",
        str(manifest),
        "--bin",
        "gha-bind-plan",
        "--",
        *arguments,
    ]


def verify_worker_checkout(worker_dir: Path) -> None:
    actual = run(["git", "-C", str(worker_dir), "rev-parse", "HEAD"]).stdout.strip()
    if actual != WORKER_SHA:
        raise ConformanceFailure(
            f"worker checkout drifted: expected {WORKER_SHA}, received {actual}"
        )


def bind_consumer_dispatches(
    *,
    worker_dir: Path,
    consumer_commit: str,
    scratch: Path,
) -> tuple[dict[str, Any], list[str]]:
    if len(consumer_commit) != 40 or any(
        character not in "0123456789abcdef" for character in consumer_commit
    ):
        raise ConformanceFailure("consumer commit must be an exact lowercase 40-hex SHA")

    manifest = worker_dir / "crates" / "gha-indie-protocol" / "Cargo.toml"
    if not manifest.is_file():
        raise ConformanceFailure(f"worker protocol manifest is missing: {manifest}")

    environment = os.environ.copy()
    environment["RUSTUP_TOOLCHAIN"] = RUST_TOOLCHAIN

    plan = build_plan()
    catalog = build_catalog()
    plan_path = scratch / "plan.json"
    catalog_path = scratch / "catalog.json"
    bindings_path = scratch / "bindings.json"
    dispatch_path = scratch / "dispatch.json"
    write_json(plan_path, plan)
    write_json(catalog_path, catalog)

    catalog_digest = run(
        cargo_command(manifest, "--catalog-digest", str(catalog_path)),
        env=environment,
    ).stdout.strip()
    bindings = {
        "schemaVersion": "gha-indie-worker.bindings.v1",
        "repositoryUrl": REPOSITORY_URL,
        "commitSha": consumer_commit,
        "profileCatalogDigest": catalog_digest,
        "jobs": {
            "linux": {
                "profile": "linux-rust",
                "profileDigest": PROFILE_DIGESTS["linux-rust"],
                "contextDir": ".",
            },
            "windows": {
                "profile": "windows-msvc",
                "profileDigest": PROFILE_DIGESTS["windows-msvc"],
                "contextDir": ".",
            },
            "macos": {
                "profile": "macos-xcode",
                "profileDigest": PROFILE_DIGESTS["macos-xcode"],
                "contextDir": ".",
            },
        },
    }
    write_json(bindings_path, bindings)

    dispatch_text = run(
        cargo_command(
            manifest,
            str(plan_path),
            str(catalog_path),
            str(bindings_path),
        ),
        env=environment,
    ).stdout
    dispatch = json.loads(dispatch_text)
    write_json(dispatch_path, dispatch)

    if dispatch.get("schemaVersion") != "gha-indie-worker.dispatch-batch.v2":
        raise ConformanceFailure("unexpected dispatch batch schema")
    requests = dispatch.get("requests")
    if not isinstance(requests, list) or len(requests) != 3:
        raise ConformanceFailure("expected exactly three platform dispatch requests")

    expected_targets = {
        "linux": {
            "platform": "linux",
            "architecture": "x64",
            "capabilities": ["cargo-cache"],
        },
        "windows": {
            "platform": "windows",
            "architecture": "x64",
            "capabilities": ["msvc", "native", "powershell", "windows-sdk"],
        },
        "macos": {
            "platform": "macos",
            "architecture": "arm64",
            "capabilities": ["ios-simulator", "native", "swift", "xcode"],
        },
    }
    for request in requests:
        base_job_id = request["baseJobId"]
        if request["runner"] != expected_targets[base_job_id]:
            raise ConformanceFailure(
                f"runner target drift for {base_job_id}: {request['runner']!r}"
            )
        if request["repositoryUrl"] != REPOSITORY_URL:
            raise ConformanceFailure("repository identity drifted")
        if request["commitSha"] != consumer_commit:
            raise ConformanceFailure("consumer commit identity drifted")
        if not request["requestId"].startswith("gha:"):
            raise ConformanceFailure("request ID is not canonical")
        if not request["requestDigest"].startswith("sha256:"):
            raise ConformanceFailure("request digest is not canonical")

    serialized = json.dumps(dispatch, sort_keys=True)
    for forbidden in ('"run"', '"uses"', "curl ", "TOKEN", "SECRET"):
        if forbidden in serialized:
            raise ConformanceFailure(f"dispatch leaked forbidden input: {forbidden}")

    negative_codes: list[str] = []

    alias_plan = copy.deepcopy(plan)
    alias_plan["jobs"][1]["runsOn"].append("x86_64")
    alias_path = scratch / "alias-plan.json"
    write_json(alias_path, alias_plan)
    negative_codes.append(
        expect_error(
            cargo_command(
                manifest,
                str(alias_path),
                str(catalog_path),
                str(bindings_path),
            ),
            "unsupported_runner_label",
            env=environment,
        )
    )

    mismatch_plan = copy.deepcopy(plan)
    mismatch_plan["jobs"][1]["runsOn"][-1] = "arm64"
    mismatch_path = scratch / "mismatch-plan.json"
    write_json(mismatch_path, mismatch_plan)
    negative_codes.append(
        expect_error(
            cargo_command(
                manifest,
                str(mismatch_path),
                str(catalog_path),
                str(bindings_path),
            ),
            "profile_runner_target_mismatch",
            env=environment,
        )
    )

    commandful_plan = copy.deepcopy(plan)
    commandful_plan["jobs"][0]["steps"] = [
        {
            "index": 0,
            "id": None,
            "name": "caller command",
            "condition": None,
            "uses": None,
            "run": "echo caller-controlled",
            "shell": None,
            "workingDirectory": None,
            "with": {},
            "env": {},
            "continueOnError": None,
            "timeoutMinutes": None,
        }
    ]
    commandful_path = scratch / "commandful-plan.json"
    write_json(commandful_path, commandful_plan)
    negative_codes.append(
        expect_error(
            cargo_command(
                manifest,
                str(commandful_path),
                str(catalog_path),
                str(bindings_path),
            ),
            "caller_steps_not_executable",
            env=environment,
        )
    )

    invalid_catalog = copy.deepcopy(catalog)
    invalid_catalog["profiles"][1]["runner"]["capabilities"] = ["msvc"]
    invalid_catalog_path = scratch / "missing-native-catalog.json"
    write_json(invalid_catalog_path, invalid_catalog)
    negative_codes.append(
        expect_error(
            cargo_command(
                manifest,
                "--catalog-digest",
                str(invalid_catalog_path),
            ),
            "native_capability_required",
            env=environment,
        )
    )

    return dispatch, negative_codes


def exercise_scheduler(
    *,
    worker_dir: Path,
    dispatch: dict[str, Any],
) -> dict[str, Any]:
    sys.path.insert(0, str(worker_dir))
    from tools.native_fleet_protocol import (  # type: ignore[import-not-found]
        NativeFleet,
        capability_payload,
        sign_capability_envelope,
    )

    now = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)
    fleet = NativeFleet()
    credentials: dict[str, Any] = {}
    expected_hosts = {
        "linux": "linux-feature-matrix-01",
        "windows": "windows-feature-matrix-01",
        "macos": "macos-feature-matrix-01",
    }

    for request in dispatch["requests"]:
        base_job_id = request["baseJobId"]
        runner = request["runner"]
        host_id = expected_hosts[base_job_id]
        bootstrap = fleet.issue_bootstrap(
            host_id=host_id,
            platform=runner["platform"],
            architecture=runner["architecture"],
            trust_tier="public-trusted",
            now=now,
        )
        credential = fleet.enroll(bootstrap, host_id=host_id, now=now)
        payload = capability_payload(
            host_id=host_id,
            platform=runner["platform"],
            architecture=runner["architecture"],
            trust_tier="public-trusted",
            profiles=[(request["profile"], request["profileDigest"])],
            capabilities=runner["capabilities"],
        )
        envelope = sign_capability_envelope(
            credential,
            payload,
            now,
            now + timedelta(minutes=5),
        )
        fleet.advertise(envelope, now=now)
        credentials[host_id] = credential

    assignments: list[dict[str, Any]] = []
    duplicate_checks = 0
    terminal_replay_checks = 0
    for offset, request in enumerate(dispatch["requests"]):
        result = fleet.schedule(
            request,
            required_trust_tier="public-trusted",
            now=now + timedelta(seconds=offset),
        )
        if result.lease is None:
            raise ConformanceFailure(
                f"scheduler found no exact host for {request['baseJobId']}"
            )
        expected_host = expected_hosts[request["baseJobId"]]
        if result.lease.host_id != expected_host:
            raise ConformanceFailure(
                f"{request['baseJobId']} routed to {result.lease.host_id}, "
                f"expected {expected_host}"
            )

        duplicate = fleet.schedule(
            request,
            required_trust_tier="public-trusted",
            now=now + timedelta(seconds=offset),
        )
        if not duplicate.duplicate or duplicate.lease is None:
            raise ConformanceFailure("active duplicate did not reuse its lease")
        if duplicate.lease.lease_id != result.lease.lease_id:
            raise ConformanceFailure("active duplicate received a second authority")
        duplicate_checks += 1

        receipt = fleet.complete(
            credentials[expected_host],
            lease_id=result.lease.lease_id,
            nonce=result.lease.nonce,
            status="success",
            run_manifest_digest=MANIFEST_DIGEST,
            now=now + timedelta(minutes=1, seconds=offset),
        )
        terminal = fleet.schedule(
            request,
            required_trust_tier="public-trusted",
            now=now + timedelta(minutes=1, seconds=offset),
        )
        if (
            not terminal.duplicate
            or terminal.lease is not None
            or terminal.terminal_receipt != receipt
        ):
            raise ConformanceFailure("terminal duplicate did not return its receipt")
        terminal_replay_checks += 1

        wrong_platform_rejections = sum(
            "platform:mismatch" in reasons
            for host_id, reasons in result.rejection_reasons.items()
            if host_id != expected_host
        )
        if wrong_platform_rejections != 2:
            raise ConformanceFailure(
                f"expected two cross-platform rejections, got "
                f"{wrong_platform_rejections}"
            )
        assignments.append(
            {
                "baseJobId": request["baseJobId"],
                "requestId": request["requestId"],
                "hostId": expected_host,
                "platform": request["runner"]["platform"],
                "architecture": request["runner"]["architecture"],
                "profile": request["profile"],
                "profileDigest": request["profileDigest"],
            }
        )

    return {
        "assignments": assignments,
        "activeDuplicateLeaseChecks": duplicate_checks,
        "terminalReceiptReplayChecks": terminal_replay_checks,
    }


def write_summary(evidence: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## gha-indie-worker consumer conformance",
        "",
        f"- Worker head: `{evidence['workerCommit']}`",
        f"- Consumer commit: `{evidence['consumerCommit']}`",
        f"- Host OS: `{evidence['referenceHost']}`",
        f"- Dispatches bound: `{evidence['dispatchCount']}`",
        f"- Negative gates: `{', '.join(evidence['negativeErrorCodes'])}`",
        f"- Exact assignments: `{len(evidence['scheduler']['assignments'])}`",
        (
            "- Evidence boundary: GitHub-hosted reference conformance only; "
            "no physical native-fleet readiness claim."
        ),
        "",
    ]
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-dir", type=Path, required=True)
    parser.add_argument("--consumer-commit", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()

    worker_dir = arguments.worker_dir.resolve()
    verify_worker_checkout(worker_dir)

    with tempfile.TemporaryDirectory(prefix="gha-indie-consumer-") as temp_dir:
        scratch = Path(temp_dir)
        dispatch, negative_codes = bind_consumer_dispatches(
            worker_dir=worker_dir,
            consumer_commit=arguments.consumer_commit,
            scratch=scratch,
        )
        scheduler = exercise_scheduler(
            worker_dir=worker_dir,
            dispatch=dispatch,
        )

    evidence = {
        "schemaVersion": "flags-2-env-test.gha-indie-worker-consumer-evidence.v1",
        "consumerRepository": REPOSITORY_URL,
        "consumerCommit": arguments.consumer_commit,
        "workerCommit": WORKER_SHA,
        "referenceHost": host_platform.platform(),
        "pythonVersion": host_platform.python_version(),
        "rustToolchain": RUST_TOOLCHAIN,
        "dispatchSchema": dispatch["schemaVersion"],
        "dispatchCount": len(dispatch["requests"]),
        "negativeErrorCodes": negative_codes,
        "scheduler": scheduler,
        "claimBoundary": (
            "GitHub-hosted operating-system reference conformance; not evidence "
            "of physical host enrollment, production device identity, isolation, "
            "cleanup, reimage, capacity, or recovery readiness."
        ),
    }
    arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
    arguments.evidence.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_summary(evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
