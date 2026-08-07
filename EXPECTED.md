# What this fixture covers, and why it exists

The twelve language fixtures in this organization each assert the same six argv
results through a different binding. That proves every runtime turns one argv
into one environment map, which is the property most likely to break when the
parser changes.

It is also the only property they check. Everything below is outside their
contract, and this fixture covers it against the canonical CLI.

`.cli-flags.toml` here is **byte-identical** to the one the twelve carry, so
this repository can join the conformance job without weakening it. Cases that
need a different contract keep it under `scenarios/`, never at the root.

## Value sources — new in 0.2.0

A value can come from `flags` (argv), `env_shell` (the live environment), or
`env_file` (`./.env`), ranked in that order by default, with the declared
`[flags.*] default` beneath all three.

The org contract's own defaults are the bottom of that ladder, so each case adds
one rung and shows it displacing the one beneath:

| case | result |
| --- | --- |
| no sources | `PORT=3000` — the declared default |
| `./.env` has `PORT=8080` | `PORT=8080` |
| plus `PORT=7777` exported | `PORT=7777` |
| plus `--port 9999` | `PORT=9999` |

`FLAGS2ENV_DOTENV=0` skips the file entirely and restores pure-argv behaviour.
It can only switch loading **off**, never on, so `[env] load = false` in a
trusted contract cannot be undone by an ambient variable.

### File handling

`./.env` is read only from the process working directory — no upward walk, and
no lookup beside an explicitly passed `--config`. A symlink is followed, but
only when it resolves to a regular file: a fifo left at `./.env` would otherwise
park a blocking `open()` and hang the command outright. Both are asserted.

## Per-key ordering

`[order-of-preference]` re-ranks the sources for individual env keys:

```toml
[order-of-preference]
PORT = (env_file, env_shell, flags)
```

`flags` ranked last means a checked-in value cannot be overridden from the
command line — `--port 9999` does not displace it. Keys the table omits keep the
default order, which the fixture checks in the same run so the two are not
confused.

## Subcommands

A selected command marks itself, contributes its own flags, and leaves flags
scoped to sibling commands out of the map entirely.

The command path is derived from argv. A `./.env` claiming `DEMO_COMMAND=forged`
or `CMD_DEPLOY=true` changes neither: parse-derived keys report what argv
actually contained, so neither a checked-in file nor an ambient variable can
forge them. A flag genuinely scoped to the command that *did* run is still
honoured from `.env`, which is the distinction being asserted.

## Audits

`audit` accepts the org contract, and rejects a preference list naming an
unknown source. `env-audit` warns about declared keys a `.env` omits and rejects
`.env` keys no `[flags.*]` table declares.

## Generated types and completion

TypeScript generation maps `integer → number`, `bool → boolean`,
`string → string`. JSON Schema generation emits the 2020-12 dialect and carries
declared defaults. Bash completion defines its function and offers declared long
aliases; zsh completion is a `#compdef` script.

## Running it

```console
$ docker build -t feature-matrix . && docker run --rm feature-matrix
feature-matrix OK: 25 cases
```

Against a working copy instead of the vendored submodule:

```console
$ FLAGS2ENV_CLI=/path/to/flags-2-env/build/flags2env FIXTURE_ROOT=$PWD ./run.sh
```

A green run means the library under test agrees with every statement above. It
says nothing about the argv contract — that is what the twelve language fixtures
are for.
