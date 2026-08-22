#!/usr/bin/env bash
# Feature coverage for oresoftware/flags-2-env.
#
# The twelve language fixtures in this organization all assert the same six
# argv results, which proves every binding turns one argv into one environment
# map. They deliberately say nothing about the rest of the library. This fixture
# covers that remainder against the canonical CLI: the value sources introduced
# in 0.2.0, subcommands, both audits, code generation, and completion.
#
# Every case is an exact-match assertion. Exiting non-zero on the first
# disagreement is what makes `docker run` the whole test.
set -uo pipefail

CLI=${FLAGS2ENV_CLI:-/app/.vendor/.zed/oresoftware/flags-2-env/build/flags2env}
ROOT=${FIXTURE_ROOT:-/app}
pass=0
fail=0

# The library reads ./.env from the working directory, so every case that is not
# about .env must run somewhere without one, and with the ambient environment
# cleared. Otherwise a stray file or exported variable silently rewrites the
# expected map and the fixture reports the wrong thing.
clean() {
  env -u PORT -u DEBUG -u VERBOSE -u APP_ENV -u COLOR -u FLAGS2ENV_DOTENV "$@"
}

check() {
  local label=$1 expected=$2 actual=$3
  if [ "$actual" = "$expected" ]; then
    pass=$((pass + 1))
    printf 'ok   %s\n' "$label"
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n       expected: %s\n       actual:   %s\n' "$label" "$expected" "$actual"
  fi
}

contains() {
  local label=$1 needle=$2 haystack=$3
  case "$haystack" in
    *"$needle"*)
      pass=$((pass + 1)); printf 'ok   %s\n' "$label" ;;
    *)
      fail=$((fail + 1))
      printf 'FAIL %s\n       expected to contain: %s\n       actual: %s\n' \
        "$label" "$needle" "$(printf '%s' "$haystack" | head -c 200)" ;;
  esac
}

# ---------------------------------------------------------------- value sources
#
# Precedence is flags > env_shell > env_file > the declared default. The
# organization contract's own defaults are the bottom of that ladder, so each
# case below adds exactly one rung and shows it displacing the one beneath.

work=$(mktemp -d)
cp "$ROOT/.cli-flags.toml" "$work/.cli-flags.toml"
cd "$work" || exit 1

check "default only (matches the org contract)" \
  '{"PORT":"3000","DEBUG":"false","APP_ENV":"development","COLOR":"true"}' \
  "$(clean "$CLI" demo)"

printf 'PORT=8080\nAPP_ENV=from-dotenv\n' > .env

check "env_file displaces the default" \
  '{"PORT":"8080","DEBUG":"false","APP_ENV":"from-dotenv","COLOR":"true"}' \
  "$(clean "$CLI" demo)"

check "env_shell displaces env_file" \
  '{"PORT":"7777","DEBUG":"false","APP_ENV":"from-dotenv","COLOR":"true"}' \
  "$(clean PORT=7777 "$CLI" demo)"

check "flags displace env_shell" \
  '{"PORT":"9999","DEBUG":"false","APP_ENV":"from-dotenv","COLOR":"true"}' \
  "$(clean PORT=7777 "$CLI" demo --port 9999)"

check "FLAGS2ENV_DOTENV=0 restores pure-argv behaviour" \
  '{"PORT":"8181","DEBUG":"true","APP_ENV":"production","COLOR":"true"}' \
  "$(clean FLAGS2ENV_DOTENV=0 "$CLI" demo --port 8181 --debug=t --mode production)"

# A ./.env symlink is followed, but only to a regular file. A fifo left there
# would otherwise park a blocking open() and hang the command outright.
mkdir -p shared && printf 'PORT=4242\n' > shared/team.env
rm -f .env && ln -s shared/team.env .env
check "a ./.env symlink is followed" \
  '{"PORT":"4242","DEBUG":"false","APP_ENV":"development","COLOR":"true"}' \
  "$(clean "$CLI" demo)"

rm -f .env
if command -v mkfifo >/dev/null 2>&1 && mkfifo .env 2>/dev/null; then
  check "a ./.env fifo is declined rather than waited on" \
    '{"PORT":"3000","DEBUG":"false","APP_ENV":"development","COLOR":"true"}' \
    "$(clean timeout 10 "$CLI" demo)"
  rm -f .env
fi

# ---------------------------------------------------------- short flag bundles
#
# The candidate parser must accept both established boolean-only groups and
# getopt-style groups whose final short consumes a value. Inline and separated
# value spellings are separate cases so a parser cannot pass by supporting only
# one of them.

cd "$ROOT/scenarios/bundles" || exit 1
check "boolean-only short bundle" \
  '{"DEBUG":"true","VERBOSE":"true"}' \
  "$(clean "$CLI" demo -dv)"

check "mixed short bundle consumes a separated value" \
  '{"DEBUG":"true","VERBOSE":"true","PORT":"8181"}' \
  "$(clean "$CLI" demo -dvp 8181)"

check "mixed short bundle consumes an inline value" \
  '{"DEBUG":"true","VERBOSE":"true","PORT":"8282"}' \
  "$(clean "$CLI" demo -dvp8282)"

# ------------------------------------------------------- order-of-preference
#
# Per-key source ranking. PORT pins env_file above everything, so not even an
# explicit --port displaces it; APP_ENV keeps the default order for contrast.

cd "$ROOT/scenarios/order" || exit 1
check "order-of-preference pins env_file above flags" \
  '{"PORT":"8080","DEBUG":"false","APP_ENV":"from-flag","COLOR":"true"}' \
  "$(clean PORT=7777 APP_ENV=from-shell "$CLI" demo --port 9999 --mode from-flag)"

check "an unlisted key keeps the default order" \
  '{"PORT":"8080","DEBUG":"false","APP_ENV":"from-shell","COLOR":"true"}' \
  "$(clean APP_ENV=from-shell "$CLI" demo)"

# ------------------------------------------------------------------ subcommands

cd "$ROOT/scenarios/commands" || exit 1
check "no command selected" \
  '{"DEMO_COMMAND":"","GLOBAL":"g"}' \
  "$(clean "$CLI" demo)"

check "a command marks itself and applies its own flags" \
  '{"DEMO_COMMAND":"build","CMD_BUILD":"true","GLOBAL":"g","BUILD_TARGET":"wasm"}' \
  "$(clean "$CLI" demo build --target wasm)"

check "a flag scoped to another command stays out" \
  '{"DEMO_COMMAND":"deploy","CMD_DEPLOY":"true","GLOBAL":"g","DEPLOY_REGION":"eu"}' \
  "$(clean "$CLI" demo deploy --region eu)"

# The scenario .env claims DEMO_COMMAND=forged and CMD_DEPLOY=true, and also
# sets BUILD_TARGET. Only the last of those is a real flag env, so only it is
# honoured: the command path stays what argv said, and the marker for a command
# that did not run never appears. BUILD_TARGET="" is the .env legitimately
# setting an empty value on a flag scoped to the command that did run.
check "a .env cannot forge the command path or a command marker" \
  '{"DEMO_COMMAND":"build","CMD_BUILD":"true","GLOBAL":"g","BUILD_TARGET":""}' \
  "$(clean "$CLI" demo build)"

# ----------------------------------------------------------------------- audits

cd "$ROOT" || exit 1
check "audit accepts the organization contract" \
  '{"ok":true,"errorCount":0,"warningCount":0,"errors":[],"warnings":[]}' \
  "$("$CLI" audit "$ROOT/.cli-flags.toml")"

contains "audit rejects an unknown preference source" \
  'names an unknown source' \
  "$("$CLI" audit "$ROOT/scenarios/invalid-order/.cli-flags.toml" 2>&1)"

contains "env-audit reports keys the .env omits" \
  'is not present in .env' \
  "$("$CLI" env-audit "$ROOT/scenarios/envaudit/.cli-flags.toml" "$ROOT/scenarios/envaudit/.env" 2>&1)"

contains "env-audit rejects an undeclared .env key" \
  'is not declared by .cli-flags.toml' \
  "$("$CLI" env-audit "$ROOT/scenarios/envaudit/.cli-flags.toml" "$ROOT/scenarios/envaudit/undeclared.env" 2>&1)"

# ------------------------------------------------------------- generated types

ts=$("$CLI" generate typescript "$ROOT/.cli-flags.toml" --name DemoConfig)
contains "typescript: integer maps to number" 'PORT: number;' "$ts"
contains "typescript: bool maps to boolean" 'DEBUG: boolean;' "$ts"
contains "typescript: string maps to string" 'APP_ENV: string;' "$ts"

schema=$("$CLI" generate json-schema "$ROOT/.cli-flags.toml" --name DemoConfig)
contains "json-schema declares the 2020-12 dialect" '2020-12' "$schema"
contains "json-schema carries the declared default" '3000' "$schema"

# --------------------------------------------------------------- completion

bash_completion=$("$CLI" completion bash demo "$ROOT/.cli-flags.toml")
contains "bash completion defines its function" '_flags2env_complete_demo()' "$bash_completion"
contains "bash completion offers a declared long flag" '--listen-port' "$bash_completion"

zsh_completion=$("$CLI" completion zsh demo "$ROOT/.cli-flags.toml")
contains "zsh completion is a compdef" '#compdef' "$zsh_completion"

# ---------------------------------------------------------------------- report

printf '\n'
if [ "$fail" -ne 0 ]; then
  printf 'feature-matrix FAILED: %d passed, %d failed\n' "$pass" "$fail"
  exit 1
fi
printf 'feature-matrix OK: %d cases\n' "$pass"
