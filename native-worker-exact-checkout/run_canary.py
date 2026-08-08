#!/usr/bin/env python3
"""Run positive and fail-closed exact-checkout cases through a pinned worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

EVIDENCE_KEYS = {
    "schemaVersion", "evidenceDigest", "handoffDigest", "requestId",
    "requestDigest", "leaseId", "hostId", "repositoryUrl",
    "requestedCommitSha", "resolvedCommitSha", "treeSha", "originUrl",
    "remotes", "detachedHead", "submoduleGitlinks", "contextDir",
    "profile", "profileDigest", "runner", "startedAt", "completedAt",
}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def live_command(
    *,
    worker_dir: Path,
    repository_url: str,
    commit_sha: str,
    workspace: Path,
    evidence: Path,
    platform: str,
    architecture: str,
) -> list[str]:
    return [
        sys.executable,
        str(worker_dir / "tests" / "live_native_worker_checkout.py"),
        "--repository-url",
        repository_url,
        "--commit-sha",
        commit_sha,
        "--workspace",
        str(workspace),
        "--evidence",
        str(evidence),
        "--platform",
        platform,
        "--architecture",
        architecture,
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-dir", type=Path, required=True)
    parser.add_argument("--submodule-repository-url", required=True)
    parser.add_argument("--submodule-commit-sha", required=True)
    parser.add_argument("--success-repository-url", required=True)
    parser.add_argument("--success-commit-sha", required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--architecture", required=True)
    args = parser.parse_args()

    worker_dir = args.worker_dir.resolve()
    root = args.workspace_root.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    negative_evidence = root / "negative-evidence.json"
    negative = run(
        live_command(
            worker_dir=worker_dir,
            repository_url=args.submodule_repository_url,
            commit_sha=args.submodule_commit_sha,
            workspace=root / "negative-checkout",
            evidence=negative_evidence,
            platform=args.platform,
            architecture=args.architecture,
        )
    )
    if negative.returncode == 0:
        raise RuntimeError("submodule-bearing repository unexpectedly crossed the checkout boundary")
    combined = negative.stdout + "\n" + negative.stderr
    if "submodule_gitlink_forbidden" not in combined:
        raise RuntimeError(
            "negative checkout failed for the wrong reason:\n" + combined[-4000:]
        )
    if negative_evidence.exists():
        raise RuntimeError("failed checkout emitted success evidence")

    positive = run(
        live_command(
            worker_dir=worker_dir,
            repository_url=args.success_repository_url,
            commit_sha=args.success_commit_sha,
            workspace=root / "positive-checkout",
            evidence=args.evidence,
            platform=args.platform,
            architecture=args.architecture,
        )
    )
    if positive.returncode != 0:
        raise RuntimeError(
            "submodule-free exact checkout failed:\n"
            + positive.stdout[-2000:]
            + "\n"
            + positive.stderr[-4000:]
        )

    value = json.loads(args.evidence.read_text(encoding="utf-8"))
    if set(value) != EVIDENCE_KEYS:
        raise RuntimeError(
            f"success evidence field set drifted: {sorted(set(value) ^ EVIDENCE_KEYS)}"
        )
    unsigned = {key: item for key, item in value.items() if key != "evidenceDigest"}
    if value["evidenceDigest"] != digest(unsigned):
        raise RuntimeError("success evidence digest does not cover the complete record")
    if value["requestedCommitSha"] != args.success_commit_sha:
        raise RuntimeError("requested success SHA drifted")
    if value["resolvedCommitSha"] != args.success_commit_sha:
        raise RuntimeError("resolved success SHA drifted")
    if value["originUrl"] != args.success_repository_url:
        raise RuntimeError("success origin drifted")
    if value["detachedHead"] is not True or value["remotes"] != ["origin"]:
        raise RuntimeError("success checkout did not retain the exact detached one-origin contract")
    if value["submoduleGitlinks"] != []:
        raise RuntimeError("success fixture unexpectedly contains gitlinks")

    summary = {
        "schemaVersion": "flags-2-env-test.native-worker-canary-evidence.v1",
        "negativeRepository": args.submodule_repository_url,
        "negativeCommitSha": args.submodule_commit_sha,
        "negativeErrorCode": "submodule_gitlink_forbidden",
        "successRepository": args.success_repository_url,
        "successCommitSha": args.success_commit_sha,
        "successEvidenceDigest": value["evidenceDigest"],
        "platform": args.platform,
        "architecture": args.architecture,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
