#!/usr/bin/env python3
"""Independent consumer conformance including checkpoint/restart replay."""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform as host_platform
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import verify_consumer_contract as legacy

WORKER_SHA = "72055c9af579a94c97054800cf736a53fa8eea50"
CHECKPOINT_KEY_ID = "external-consumer-checkpoint-v1"
CHECKPOINT_KEY = b"independent-checkpoint-integrity-key-v1!!"

legacy.WORKER_SHA = WORKER_SHA


class ConformanceFailure(RuntimeError):
    """A stable external-consumer assertion failure."""


def exercise_checkpoint_restart(
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

    now = datetime(2026, 8, 8, 7, 0, tzinfo=timezone.utc)
    fleet = NativeFleet()
    credentials: dict[str, Any] = {}
    expected_hosts = {
        "linux": "linux-restart-canary-01",
        "windows": "windows-restart-canary-01",
        "macos": "macos-restart-canary-01",
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

    active_leases: dict[str, Any] = {}
    for offset, request in enumerate(dispatch["requests"]):
        result = fleet.schedule(
            request,
            required_trust_tier="public-trusted",
            now=now + timedelta(seconds=offset),
        )
        if result.lease is None:
            raise ConformanceFailure(
                f"restart canary found no host for {request['baseJobId']}"
            )
        expected_host = expected_hosts[request["baseJobId"]]
        if result.lease.host_id != expected_host:
            raise ConformanceFailure(
                f"restart canary routed {request['baseJobId']} to "
                f"{result.lease.host_id}, expected {expected_host}"
            )
        active_leases[request["requestId"]] = result.lease

    active_checkpoint = fleet.checkpoint(
        integrity_key_id=CHECKPOINT_KEY_ID,
        integrity_key=CHECKPOINT_KEY,
        now=now + timedelta(seconds=10),
    )
    serialized_checkpoint = json.dumps(active_checkpoint, sort_keys=True)
    for credential in credentials.values():
        encoded_secret = base64.urlsafe_b64encode(credential.secret).decode().rstrip("=")
        if credential.secret.hex() in serialized_checkpoint or encoded_secret in serialized_checkpoint:
            raise ConformanceFailure("checkpoint stored raw identity secret material")

    identity_secrets = {
        credential.key_id: credential.secret
        for credential in credentials.values()
    }
    restored = NativeFleet.restore_checkpoint(
        active_checkpoint,
        integrity_keys={CHECKPOINT_KEY_ID: CHECKPOINT_KEY},
        identity_secrets=identity_secrets,
        now=now + timedelta(seconds=20),
    )

    active_replay_checks = 0
    terminal_receipts: dict[str, Any] = {}
    for offset, request in enumerate(dispatch["requests"]):
        duplicate = restored.schedule(
            request,
            required_trust_tier="public-trusted",
            now=now + timedelta(seconds=20 + offset),
        )
        original = active_leases[request["requestId"]]
        if (
            not duplicate.duplicate
            or duplicate.lease is None
            or duplicate.lease.lease_id != original.lease_id
        ):
            raise ConformanceFailure(
                f"active lease was not replayed after restart for "
                f"{request['baseJobId']}"
            )
        active_replay_checks += 1

        host_id = expected_hosts[request["baseJobId"]]
        receipt = restored.complete(
            credentials[host_id],
            lease_id=duplicate.lease.lease_id,
            nonce=duplicate.lease.nonce,
            status="success",
            run_manifest_digest=legacy.MANIFEST_DIGEST,
            now=now + timedelta(seconds=30 + offset),
        )
        terminal_receipts[request["requestId"]] = receipt

    terminal_checkpoint = restored.checkpoint(
        integrity_key_id=CHECKPOINT_KEY_ID,
        integrity_key=CHECKPOINT_KEY,
        now=now + timedelta(seconds=40),
    )
    restored_terminal = NativeFleet.restore_checkpoint(
        terminal_checkpoint,
        integrity_keys={CHECKPOINT_KEY_ID: CHECKPOINT_KEY},
        identity_secrets=identity_secrets,
        now=now + timedelta(seconds=50),
    )

    terminal_replay_checks = 0
    for offset, request in enumerate(dispatch["requests"]):
        replay = restored_terminal.schedule(
            request,
            required_trust_tier="public-trusted",
            now=now + timedelta(seconds=50 + offset),
        )
        if (
            not replay.duplicate
            or replay.lease is not None
            or replay.terminal_receipt != terminal_receipts[request["requestId"]]
        ):
            raise ConformanceFailure(
                f"terminal receipt was not replayed after restart for "
                f"{request['baseJobId']}"
            )
        terminal_replay_checks += 1

    state = active_checkpoint.get("state", {})
    return {
        "checkpointSchema": active_checkpoint.get("schemaVersion"),
        "stateSchema": state.get("schemaVersion"),
        "activeLeaseReplayAfterRestartChecks": active_replay_checks,
        "terminalReceiptReplayAfterRestartChecks": terminal_replay_checks,
        "identitySecretBytesStored": False,
        "identitySecretResolverEntries": len(identity_secrets),
    }


def write_summary(evidence: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    restart = evidence["checkpointRestart"]
    lines = [
        "## gha-indie-worker consumer conformance v2",
        "",
        f"- Worker head: `{evidence['workerCommit']}`",
        f"- Consumer commit: `{evidence['consumerCommit']}`",
        f"- Host OS: `{evidence['referenceHost']}`",
        f"- Dispatches bound: `{evidence['dispatchCount']}`",
        f"- Exact assignments: `{len(evidence['scheduler']['assignments'])}`",
        (
            "- Restart replay checks: "
            f"`{restart['activeLeaseReplayAfterRestartChecks']}` active / "
            f"`{restart['terminalReceiptReplayAfterRestartChecks']}` terminal"
        ),
        "- Checkpoint stores identity secret bytes: `false`",
        (
            "- Evidence boundary: GitHub-hosted reference conformance and "
            "dependency-free checkpoint semantics only; no production native-fleet "
            "or durable-database readiness claim."
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
    legacy.verify_worker_checkout(worker_dir)

    with tempfile.TemporaryDirectory(prefix="gha-indie-consumer-v2-") as temp_dir:
        scratch = Path(temp_dir)
        dispatch, negative_codes = legacy.bind_consumer_dispatches(
            worker_dir=worker_dir,
            consumer_commit=arguments.consumer_commit,
            scratch=scratch,
        )
        scheduler = legacy.exercise_scheduler(
            worker_dir=worker_dir,
            dispatch=dispatch,
        )
        checkpoint_restart = exercise_checkpoint_restart(
            worker_dir=worker_dir,
            dispatch=dispatch,
        )

    evidence = {
        "schemaVersion": "flags-2-env-test.gha-indie-worker-consumer-evidence.v2",
        "consumerRepository": legacy.REPOSITORY_URL,
        "consumerCommit": arguments.consumer_commit,
        "workerCommit": WORKER_SHA,
        "referenceHost": host_platform.platform(),
        "pythonVersion": host_platform.python_version(),
        "rustToolchain": legacy.RUST_TOOLCHAIN,
        "dispatchSchema": dispatch["schemaVersion"],
        "dispatchCount": len(dispatch["requests"]),
        "negativeErrorCodes": negative_codes,
        "scheduler": scheduler,
        "checkpointRestart": checkpoint_restart,
        "claimBoundary": (
            "GitHub-hosted operating-system reference conformance and "
            "dependency-free checkpoint/restart semantics; not evidence of "
            "physical host enrollment, production identity, transactional durable "
            "storage, isolation, cleanup, reimage, capacity, or recovery readiness."
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
