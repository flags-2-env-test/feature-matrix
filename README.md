# feature-matrix

Feature coverage for [`oresoftware/flags-2-env`](https://github.com/ORESoftware/flags-2-env),
complementing the twelve language fixtures in this organization.

Those twelve prove that every binding turns the same argv into the same
environment map. They say nothing about the rest of the library. This one covers
that remainder against the canonical CLI: the value sources added in 0.2.0
(`./.env`, live environment, per-key `[order-of-preference]`), subcommands and
their forge-resistance, both audits, generated types, and shell completion.

`.cli-flags.toml` is byte-identical to the one the twelve carry, so this
repository can join the conformance job without weakening it. Scenarios needing
a different contract keep it under `scenarios/`.

See [EXPECTED.md](EXPECTED.md) for the contract each case asserts.

```console
$ docker build -t feature-matrix . && docker run --rm feature-matrix
feature-matrix OK: 25 cases
```
