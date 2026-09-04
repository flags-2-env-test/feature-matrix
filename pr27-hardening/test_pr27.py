#!/usr/bin/env python3
"""Independent adversarial certification for flags-2-env PR #27."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

CI_MARKERS = (
    "CI",
    "CONTINUOUS_INTEGRATION",
    "BUILD_NUMBER",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "BUILDKITE",
    "CIRCLECI",
    "TEAMCITY_VERSION",
    "TF_BUILD",
    "JENKINS_URL",
    "BUILD_BUILDID",
)
FORCE_KEYS = (
    "F2E_FORCE_STDIN_TTY",
    "F2E_FORCE_STDOUT_TTY",
    "F2E_FORCE_STDERR_TTY",
    "F2E_FORCE_CI",
)


class Failure(AssertionError):
    pass


def controlled_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (*CI_MARKERS, *FORCE_KEYS, "COLUMNS"):
        env.pop(key, None)
    env.update(
        {
            "TERM": "xterm-256color",
            "F2E_FORCE_STDIN_TTY": "1",
            "F2E_FORCE_STDOUT_TTY": "1",
            "F2E_FORCE_STDERR_TTY": "1",
        }
    )
    return env


def run(
    argv: Iterable[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(value) for value in argv],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def context(binary: Path, env: dict[str, str]) -> dict[str, object]:
    result = run((binary, "context"), env=env)
    require(
        result.returncode == 0,
        f"context failed ({result.returncode}): {result.stderr}",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise Failure(f"context emitted invalid JSON: {result.stdout!r}") from error
    require(payload.get("version") == 1, f"unexpected context schema: {payload}")
    return payload


def write_tty_contract(root: Path) -> Path:
    contract = root / ".cli-flags.toml"
    contract.write_text(
        """
[flags.interactive]
env = "F2E_TTY_INTERACTIVE"
aliases = ["interactive"]
short = "i"
type = "bool"
default = false
requires_tty = true

[flags.progress]
env = "F2E_TTY_PROGRESS"
aliases = ["progress"]
type = "bool"
default = false
requires_tty = "stdout"
""".lstrip(),
        encoding="utf-8",
    )
    return contract


def shell_env(
    binary: Path,
    contract: Path,
    args: Iterable[str],
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return run(
        (
            binary,
            "shell-env",
            "--config",
            contract,
            "--",
            "fixture",
            *args,
        ),
        cwd=contract.parent,
        env=env,
    )


def assert_tty_parity(binary: Path, temp: Path) -> None:
    tty_root = temp / "tty"
    tty_root.mkdir()
    contract = write_tty_contract(tty_root)

    falsey = ("0", "false", "FALSE", "no", "off", "never")
    for value in falsey:
        env = controlled_env()
        env["CI"] = value
        observed = context(binary, env)
        require(observed["ci"] is False, f"CI={value!r} must be false: {observed}")
        require(
            observed["canPrompt"] is True,
            f"CI={value!r} must not disable prompting: {observed}",
        )
        parsed = shell_env(binary, contract, ("--interactive",), env)
        require(
            "export F2E_TTY_INTERACTIVE='true'" in parsed.stdout,
            f"parser disagrees with context for CI={value!r}: {parsed.stdout}",
        )

    truthy = ("1", "true", "TRUE", "yes", "on", "always", "present")
    for value in truthy:
        env = controlled_env()
        env["CI"] = value
        observed = context(binary, env)
        require(observed["ci"] is True, f"CI={value!r} must be true: {observed}")
        require(
            observed["canPrompt"] is False,
            f"CI={value!r} must disable prompting: {observed}",
        )
        parsed = shell_env(binary, contract, ("--interactive",), env)
        require(
            "requires an interactive terminal" in parsed.stdout,
            f"parser did not block CI={value!r}: {parsed.stdout}",
        )
        require(
            "F2E_TTY_INTERACTIVE" not in parsed.stdout,
            f"blocked flag was still exported for CI={value!r}: {parsed.stdout}",
        )

    for marker in ("JENKINS_URL", "BUILD_BUILDID"):
        env = controlled_env()
        env[marker] = "present"
        observed = context(binary, env)
        require(observed["ci"] is True, f"{marker} was not recognized: {observed}")
        parsed = shell_env(binary, contract, ("--interactive",), env)
        require(
            "requires an interactive terminal" in parsed.stdout,
            f"parser and context disagree for {marker}: {parsed.stdout}",
        )

    force_cases = (
        ("off", "1", False, True),
        ("OFF", "1", False, True),
        ("auto", "false", False, True),
        ("ON", "", True, False),
        ("yes", "", True, False),
    )
    for forced, ambient, expected_ci, expected_prompt in force_cases:
        env = controlled_env()
        if ambient:
            env["CI"] = ambient
        env["F2E_FORCE_CI"] = forced
        observed = context(binary, env)
        require(
            observed["ci"] is expected_ci,
            f"F2E_FORCE_CI={forced!r} produced {observed}",
        )
        require(
            observed["canPrompt"] is expected_prompt,
            f"F2E_FORCE_CI={forced!r} produced {observed}",
        )
        parsed = shell_env(binary, contract, ("--interactive",), env)
        if expected_prompt:
            require(
                "export F2E_TTY_INTERACTIVE='true'" in parsed.stdout,
                f"parser rejected F2E_FORCE_CI={forced!r}: {parsed.stdout}",
            )
        else:
            require(
                "requires an interactive terminal" in parsed.stdout,
                f"parser allowed F2E_FORCE_CI={forced!r}: {parsed.stdout}",
            )

    env = controlled_env()
    env["TERM"] = "dumb"
    observed = context(binary, env)
    require(observed["dumb"] is True and observed["canPrompt"] is False, str(observed))
    parsed = shell_env(binary, contract, ("--interactive",), env)
    require("requires an interactive terminal" in parsed.stdout, parsed.stdout)

    env = controlled_env()
    env["F2E_FORCE_STDOUT_TTY"] = "0"
    blocked = shell_env(binary, contract, ("--progress",), env)
    require("requires a terminal on stdout" in blocked.stdout, blocked.stdout)
    env["F2E_FORCE_STDOUT_TTY"] = "yes"
    allowed = shell_env(binary, contract, ("--progress",), env)
    require("export F2E_TTY_PROGRESS='true'" in allowed.stdout, allowed.stdout)


def write_layering_contract(root: Path, files: str) -> Path:
    contract = root / ".cli-flags.toml"
    contract.write_text(
        f"""
[env]
files = {files}

[flags.port]
env = "F2E_LAYER_PORT"
aliases = ["port"]
type = "int"
default = 3000

[flags.host]
env = "F2E_LAYER_HOST"
aliases = ["host"]
type = "string"
default = "default"
""".lstrip(),
        encoding="utf-8",
    )
    return contract


def assert_dotenv_layering(binary: Path, temp: Path) -> None:
    root = temp / "layering"
    root.mkdir()
    (root / "base.dotenv").write_text(
        "F2E_LAYER_PORT=3100\nF2E_LAYER_HOST=base\n", encoding="utf-8"
    )
    (root / "local.dotenv").write_text("F2E_LAYER_HOST=local\n", encoding="utf-8")
    contract = write_layering_contract(
        root, '["base.dotenv", "local.dotenv"]'
    )
    result = shell_env(binary, contract, (), controlled_env())
    require("export F2E_LAYER_PORT='3100'" in result.stdout, result.stdout)
    require("export F2E_LAYER_HOST='local'" in result.stdout, result.stdout)

    malformed = write_layering_contract(root, '["base.dotenv"] trailing-junk')
    audit = run((binary, "audit", malformed), cwd=root, env=controlled_env())
    require(
        audit.returncode != 0,
        f"env.files accepted trailing TOML junk: {audit.stdout}",
    )

    empty = write_layering_contract(root, "[]")
    result = shell_env(binary, empty, (), controlled_env())
    require("export F2E_LAYER_PORT='3000'" in result.stdout, result.stdout)
    require("export F2E_LAYER_HOST='default'" in result.stdout, result.stdout)


def assert_dotenv_containment(binary: Path, temp: Path) -> None:
    root = temp / "containment"
    outside = temp / "outside"
    root.mkdir()
    outside.mkdir()
    secret = "never-print-this-dotenv-secret"
    (outside / "escape.dotenv").write_text(
        f"F2E_LAYER_PORT=9999\nF2E_LAYER_HOST={secret}\n",
        encoding="utf-8",
    )

    final_link = root / "escape.dotenv"
    final_link.symlink_to(outside / "escape.dotenv")
    contract = write_layering_contract(root, '["escape.dotenv"]')
    audit = run((binary, "audit", contract), cwd=root, env=controlled_env())
    require(
        audit.returncode != 0,
        f"explicit final symlink escaped cwd: {audit.stdout}",
    )
    require(secret not in audit.stdout + audit.stderr, "audit disclosed dotenv value")
    parsed = shell_env(binary, contract, (), controlled_env())
    require(secret not in parsed.stdout + parsed.stderr, "parser disclosed escaped value")
    require("F2E_LAYER_PORT='9999'" not in parsed.stdout, parsed.stdout)

    final_link.unlink()
    linked_parent = root / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    contract = write_layering_contract(root, '["linked-parent/escape.dotenv"]')
    audit = run((binary, "audit", contract), cwd=root, env=controlled_env())
    require(
        audit.returncode != 0,
        f"explicit parent symlink escaped cwd: {audit.stdout}",
    )

    linked_parent.unlink()
    inside = root / "inside"
    inside.mkdir()
    (inside / "real.dotenv").write_text(
        "F2E_LAYER_PORT=4444\nF2E_LAYER_HOST=inside\n",
        encoding="utf-8",
    )
    inside_link = root / "inside-link.dotenv"
    inside_link.symlink_to(inside / "real.dotenv")
    contract = write_layering_contract(root, '["inside-link.dotenv"]')
    parsed = shell_env(binary, contract, (), controlled_env())
    require(
        "export F2E_LAYER_PORT='4444'" in parsed.stdout,
        f"safe in-tree symlink was rejected: {parsed.stdout}\n{parsed.stderr}",
    )


def assert_doctor(binary: Path, temp: Path) -> None:
    root = temp / "doctor"
    root.mkdir()
    contract = root / ".cli-flags.toml"
    contract.write_text(
        """
[env]
files = ["doctor.dotenv"]

[flags.dup]
env = "F2E_DOCTOR_DUP"
aliases = ["dup"]
type = "string"
""".lstrip(),
        encoding="utf-8",
    )
    secret = "doctor-value-must-never-be-printed"
    (root / "doctor.dotenv").write_text(
        "\n".join(
            (
                "F2E_DOCTOR_DUP=first",
                "F2E_DOCTOR_DUP=second",
                f"F2E_DOCTOR_DUP={secret}",
                "BROKEN_LINE",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    result = run((binary, "doctor", contract), cwd=root, env=controlled_env())
    require(result.returncode != 0, f"doctor accepted malformed file: {result.stdout}")
    require(secret not in result.stdout + result.stderr, "doctor disclosed a dotenv value")
    payload = json.loads(result.stdout)
    require(payload.get("ok") is False, f"doctor status disagrees with JSON: {payload}")
    warnings = payload.get("warnings", [])
    require(
        any(
            "doctor.dotenv:3" in warning and "already assigned at line 2" in warning
            for warning in warnings
        ),
        f"doctor did not report the most recent prior assignment: {warnings}",
    )


def extract_function(source: str, name: str) -> str:
    marker = f"static int {name}"
    start = source.find(marker)
    require(start >= 0, f"{name} not found")
    next_start = source.find("\nstatic ", start + len(marker))
    return source[start:] if next_start < 0 else source[start:next_start]


def assert_single_scan_policy(library: Path) -> None:
    source = (library / "src/main.c").read_text(encoding="utf-8")
    pairs = (
        ("f2e_cli_run_audit", "f2e_audit_config_from_file", "f2e_audit_config_status_from_file"),
        ("f2e_cli_run_doctor", "f2e_doctor_from_file", "f2e_doctor_status_from_file"),
        ("f2e_cli_run_env_audit", "f2e_audit_env_file_from_file", "f2e_audit_env_file_status_from_file"),
    )
    for function, report_call, status_call in pairs:
        body = extract_function(source, function)
        require(
            not (report_call in body and status_call in body),
            f"{function} scans mutable input twice; expose one report+status result",
        )


def assert_source_and_packaging_policy(library: Path) -> None:
    parser = (library / "src/parser.c").read_text(encoding="utf-8")
    require(
        "_isatty" not in parser or "#include <io.h>" in parser,
        "Windows _isatty is used without <io.h>",
    )

    require(
        (library / "clients/rust/native/parser.c").read_bytes()
        == (library / "src/parser.c").read_bytes(),
        "Rust vendored parser.c drifted from canonical source",
    )
    require(
        (library / "clients/rust/native/parser.h").read_bytes()
        == (library / "src/parser.h").read_bytes(),
        "Rust vendored parser.h drifted from canonical source",
    )

    tracked = run(("git", "-C", library, "ls-files"), env=controlled_env())
    require(tracked.returncode == 0, tracked.stderr)
    plaintext = [
        path
        for path in tracked.stdout.splitlines()
        if Path(path).name == ".env"
    ]
    require(
        not plaintext,
        f"tracked plaintext .env fixtures conflict with neutral-fixture policy: {plaintext}",
    )

    scan_roots = (
        library / ".github/workflows",
        library / "scripts",
        library / "clients",
    )
    offenders: list[str] = []
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "src/main.c" in text and "terminal_context.c" not in text:
                offenders.append(str(path.relative_to(library)))
    require(
        not offenders,
        "CLI build paths compile main.c without terminal_context.c: "
        + ", ".join(offenders),
    )


def assert_help_width(binary: Path) -> None:
    workspace = tempfile.TemporaryDirectory(prefix="f2e-help-width-")
    root = Path(workspace.name)
    write_tty_contract(root)
    env = controlled_env()
    env["F2E_FORCE_STDOUT_TTY"] = "0"
    env["F2E_FORCE_STDERR_TTY"] = "0"
    result = run((binary, "--help"), cwd=root, env=env)
    require(result.returncode == 0, result.stderr)
    first = result.stdout.splitlines()[0]
    require(len(first) == 80, f"piped help width is {len(first)}, expected 80")

    env["COLUMNS"] = "140"
    result = run((binary, "--help"), cwd=root, env=env)
    require(result.returncode == 0, result.stderr)
    first = result.stdout.splitlines()[0]
    require(len(first) == 140, f"COLUMNS=140 produced width {len(first)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    args = parser.parse_args()

    binary = args.binary.resolve(strict=True)
    library = args.library.resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="flags2env-pr27-") as directory:
        temp = Path(directory)
        assert_tty_parity(binary, temp)
        assert_dotenv_layering(binary, temp)
        assert_dotenv_containment(binary, temp)
        assert_doctor(binary, temp)

    assert_single_scan_policy(library)
    assert_source_and_packaging_policy(library)
    assert_help_width(binary)

    print("flags-2-env PR #27 independent hardening certification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
