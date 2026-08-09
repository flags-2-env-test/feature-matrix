# Exact-head semantic certification

This lane records the behavior of one immutable `ORESoftware/flags-2-env` commit before conflict resolution.

The pin in `source.json` is deliberately a full 40-character commit SHA. CI checks out that exact object, verifies `HEAD`, runs the producer's own build and test suite, and then runs this repository's independent feature matrix on Linux and macOS.

A green result is **behavioral evidence, not merge approval**. When the source pull request is behind or conflicted, reconstruct its independently valuable feature slices on current `main`, preserve current packaging and fixture fixes, and run this same lane again against the rebuilt head. Never resolve the conflict by choosing one side wholesale or force-pushing over either history.

For pull request 27, the intended reconstruction order is:

1. dotenv file ordering plus secret-safe `doctor` diagnostics;
2. terminal context plus `requires_tty` enforcement;
3. Rust bundled-parser parity and fixture hardening.

Each slice should remain independently reviewable. The final rebuilt head must satisfy both the upstream producer suite and this external contract.
