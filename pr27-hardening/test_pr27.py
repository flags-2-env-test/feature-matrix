#!/usr/bin/env python3
"""Integrity-check and execute the recovered PR 27 adversarial harness."""

from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

PAYLOAD = Path(__file__).with_name("test_pr27.py.gz.b64")
EXPECTED_SHA256 = "b655f5243da5be0d5e46c3e1e1e48fc96bf078f74e53fd47872464b4fcf27227"


def main() -> None:
    encoded = "".join(PAYLOAD.read_text(encoding="ascii").split())
    source = gzip.decompress(base64.b64decode(encoded, validate=True))
    observed = hashlib.sha256(source).hexdigest()
    if observed != EXPECTED_SHA256:
        raise SystemExit(
            f"recovered harness checksum mismatch: expected {EXPECTED_SHA256}, got {observed}"
        )

    namespace = {
        "__name__": "__main__",
        "__file__": str(Path(__file__).with_name("recovered_test_pr27.py")),
        "__package__": None,
        "__builtins__": __builtins__,
    }
    exec(compile(source, namespace["__file__"], "exec"), namespace)


if __name__ == "__main__":
    main()
