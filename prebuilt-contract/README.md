# flags-2-env prebuilt contract conformance

This harness independently certifies the policy/manifest slice in
[`ORESoftware/flags-2-env#32`](https://github.com/ORESoftware/flags-2-env/pull/32)
from the `flags-2-env-test` organization.

`source-pin.json` names an immutable producer commit and exactly three public
contract files. The test downloads those files by commit, compiles the
producer validator, constructs a complete Tier-1 artifact tree, and runs one
positive plus adversarial manifests.

The complete positive fixture has both `static` and `shared` libraries for:

- `aarch64-apple-darwin`;
- `x86_64-apple-darwin`;
- `x86_64-unknown-linux-gnu`;
- `aarch64-unknown-linux-gnu`;
- `x86_64-unknown-linux-musl`;
- `aarch64-unknown-linux-musl`.

Negative cases prove fail-closed behavior for an incomplete Tier-1 matrix,
duplicate target/kind identity, target/path mismatch, runtime-floor drift,
invalid shared-library identity, explicit `null`, deferred targets, tampered
bytes, missing source epoch, missing SDK/sysroot provenance, and duplicate
compile flags.

The fixture bytes are deliberately tiny synthetic test data. They are not
release artifacts and do not claim native ABI or runtime certification; those
belong to DEN-2846 through DEN-2849.

Run locally with network access:

```sh
python3 prebuilt-contract/test_contract.py
```
