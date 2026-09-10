#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
CONTRACT = ROOT / ".cli-flags.toml"
PROVENANCE = json.loads((ROOT / "source-provenance.json").read_text())
CLI = pathlib.Path(os.environ["FLAGS2ENV_CLI"]).resolve()


def git_blob(path: pathlib.Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def run(*args: str, cwd: pathlib.Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def audit(path: pathlib.Path, expect_ok: bool) -> None:
    result = run("audit", str(path), check=False)
    payload = None
    if result.stdout.strip().startswith("{"):
        payload = json.loads(result.stdout)
    if expect_ok:
        if result.returncode != 0:
            raise SystemExit(f"audit unexpectedly failed rc={result.returncode}: {result.stderr}")
        if payload is None or payload.get("ok") is not True or payload.get("errorCount") != 0:
            raise SystemExit(f"healthy contract did not produce zero-error audit: {payload!r}")
    else:
        reported_failure = result.returncode != 0 or (payload is not None and payload.get("ok") is False)
        if not reported_failure:
            raise SystemExit(f"invalid contract was silently admitted: stdout={result.stdout!r} stderr={result.stderr!r}")


def assert_parse(args: list[str], expected: dict[str, str]) -> None:
    result = run(*args)
    actual = json.loads(result.stdout)
    for key, value in expected.items():
        if actual.get(key) != value:
            raise SystemExit(f"{args}: expected {key}={value!r}, got {actual.get(key)!r}; full={actual!r}")


if git_blob(CONTRACT) != PROVENANCE["producerFixtureBlob"]:
    raise SystemExit("tracked Shared Auth CLI contract no longer matches pinned producer fixture blob")
if PROVENANCE["producerRevision"] != "c7f720d7501921b5a1b42c395b5a6fe271f24332":
    raise SystemExit("producer revision pin drifted unexpectedly")

audit(CONTRACT, True)

assert_parse(
    ["shared-auth", "health", "--json"],
    {
        "SHARED_AUTH_COMMAND": "health",
        "SHARED_AUTH_API_BASE": "http://127.0.0.1:8080",
        "SHARED_AUTH_JSON": "true",
        "SHARED_AUTH_HELP": "false",
    },
)
assert_parse(
    ["shared-auth", "status", "--no-json", "--api-base=https://auth.example.test"],
    {
        "SHARED_AUTH_COMMAND": "status",
        "SHARED_AUTH_API_BASE": "https://auth.example.test",
        "SHARED_AUTH_JSON": "false",
        "SHARED_AUTH_HELP": "false",
    },
)
assert_parse(
    ["shared-auth", "help", "-h", "--config=./tenant.shared-auth.toml"],
    {
        "SHARED_AUTH_COMMAND": "help",
        "SHARED_AUTH_API_BASE": "http://127.0.0.1:8080",
        "SHARED_AUTH_JSON": "false",
        "SHARED_AUTH_HELP": "true",
        "SHARED_AUTH_CONFIG": "./tenant.shared-auth.toml",
    },
)

with tempfile.TemporaryDirectory(prefix="shared-auth-flags-canary-") as tmp:
    tmpdir = pathlib.Path(tmp)
    source = CONTRACT.read_text()

    unknown_parse = tmpdir / "unknown-parse-key.toml"
    unknown_parse.write_text(source.replace(
        'errors_env = "SHARED_AUTH_PARSE_ERRORS"\n',
        'errors_env = "SHARED_AUTH_PARSE_ERRORS"\nmystery_parse_key = true\n',
        1,
    ))
    audit(unknown_parse, False)

    unknown_table = tmpdir / "unknown-table.toml"
    unknown_table.write_text(source + '\n[mystery]\nsecret_looking_value = "must-not-be-interpreted"\n')
    audit(unknown_table, False)

print("flags-2-env-test Shared Auth CLI strict contract canary passed")
