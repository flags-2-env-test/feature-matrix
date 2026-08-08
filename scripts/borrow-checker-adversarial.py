#!/usr/bin/env python3
"""Independent adversarial contract for the flags-2-env borrow checker.

The canary deliberately exercises analyzer surfaces that are not represented by
the product's own fixtures.  It never imports or monkey-patches the checker; it
runs the exact candidate as a black box against disposable C translation units.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SCHEMA = "flags2env.borrow-checker-adversarial/v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--clang", default=os.environ.get("CLANG", "clang"))
    return parser.parse_args()


def run_checker(
    *, checker: Path, clang: str, source: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(checker),
            "--clang",
            clang,
            str(source),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> int:
    args = parse_args()
    product = args.product.resolve()
    checker = product / "tools" / "borrow-checker" / "borrow_check.py"
    if not checker.is_file():
        raise SystemExit(f"missing candidate checker: {checker}")
    if shutil.which(args.clang) is None:
        raise SystemExit(f"clang executable not found: {args.clang}")
    if len(args.product_sha) != 40 or any(
        ch not in "0123456789abcdef" for ch in args.product_sha
    ):
        raise SystemExit("--product-sha must be a lowercase 40-character commit")

    cases: list[dict[str, Any]] = [
        {
            "name": "interprocedural-null-dereference",
            "expected_rule": "null-deref",
            "source": """\
#include <stdlib.h>

static void read_first(const char *p) {
  (void)*p;
}

int main(void) {
  char *p = (char *)malloc(4);
  read_first(p);
  free(p);
  return 0;
}
""",
        },
        {
            "name": "string-literal-is-not-a-waiver",
            "expected_rule": "leak",
            "source": """\
#include <stdlib.h>

int main(void) {
  char *p = (char *)malloc(4);
  const char *marker = "borrow-check: allow(leak) -- not a comment";
  return p != 0;
}
""",
        },
        {
            "name": "empty-waiver-reason-is-rejected",
            "expected_rule": "leak",
            "source": """\
#include <stdlib.h>

int main(void) {
  char *p = (char *)malloc(4);
  /* borrow-check: allow(leak) -- */
  return p != 0;
}
""",
        },
        {
            "name": "justified-comment-waiver-remains-supported",
            "expected_rule": None,
            "source": """\
#include <stdlib.h>

int main(void) {
  char *p = (char *)malloc(4);
  /* borrow-check: allow(leak) -- process exits immediately */
  return p != 0;
}
""",
        },
    ]

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="flags2env-borrow-check-") as tmp:
        root = Path(tmp)
        for case in cases:
            source = root / f"{case['name']}.c"
            source.write_text(case["source"], encoding="utf-8")
            proc = run_checker(checker=checker, clang=args.clang, source=source)
            expected_rule = case["expected_rule"]
            marker = (
                f"error[{expected_rule}]" if expected_rule is not None else None
            )
            passed = (
                proc.returncode != 0 and marker in proc.stderr
                if marker is not None
                else proc.returncode == 0
            )
            result = {
                "name": case["name"],
                "expected_rule": expected_rule,
                "returncode": proc.returncode,
                "diagnostic_observed": marker in proc.stderr if marker else False,
                "passed": passed,
            }
            results.append(result)
            if not passed:
                expectation = (
                    f"non-zero with {marker}"
                    if marker is not None
                    else "zero with no diagnostic"
                )
                failures.append(
                    f"{case['name']}: expected {expectation}; "
                    f"returncode={proc.returncode}; stderr={proc.stderr.strip()!r}"
                )

    evidence = {
        "schema": SCHEMA,
        "product_sha": args.product_sha,
        "checker": "tools/borrow-checker/borrow_check.py",
        "cases": results,
        "all_passed": not failures,
        "network_credentials": False,
        "persistent_mutation": False,
    }
    evidence_root = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir()))
    evidence_path = evidence_root / "borrow-checker-adversarial-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(evidence_path.read_text(encoding="utf-8"), end="")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("### flags-2-env borrow-checker adversarial contract\n\n")
            summary.write(f"- Product: `{args.product_sha}`\n")
            summary.write(f"- Schema: `{SCHEMA}`\n")
            for result in results:
                status = "PASS" if result["passed"] else "FAIL"
                summary.write(f"- `{result['name']}`: **{status}**\n")

    if failures:
        for failure in failures:
            print(f"adversarial contract: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
