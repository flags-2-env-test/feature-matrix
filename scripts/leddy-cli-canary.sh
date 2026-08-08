#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: leddy-cli-canary.sh LEDDY_BIN" >&2; exit 64; }
leddy="$1"
[[ -x "$leddy" ]] || { echo "leddy binary is not executable: $leddy" >&2; exit 66; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

run_expect() {
  local expected="$1"
  shift
  set +e
  "$@" >"$work/stdout" 2>"$work/stderr"
  local status=$?
  set -e
  if [[ $status -ne $expected ]]; then
    echo "expected exit $expected, got $status: $*" >&2
    cat "$work/stdout" >&2 || true
    cat "$work/stderr" >&2 || true
    exit 1
  fi
}

# The root help comes from the flags-2-env contract and must expose every Leddy
# subcommand without leaking ignored credentials.
run_expect 0 "$leddy" --help
grep -F 'publish' "$work/stdout"
grep -F 'preview' "$work/stdout"
grep -F 'clear' "$work/stdout"
grep -F 'health' "$work/stdout"
if grep -Fq 'LEDDY_API_TOKEN' "$work/stdout"; then
  echo "credential-only LEDDY_API_TOKEN leaked into help" >&2
  exit 1
fi

# Command-scoped help must contain preview geometry flags.
run_expect 0 "$leddy" preview --help
grep -F -- '--width' "$work/stdout"
grep -F -- '--height' "$work/stdout"
grep -F -- '--at' "$work/stdout"

# Environment values feed the same contract. Preview is offline, so this tests
# precedence without needing any service or credential.
LEDDY_MATRIX_WIDTH=48 LEDDY_MATRIX_HEIGHT=8 LEDDY_SCROLL_SPEED=18 \
  "$leddy" preview --text HI --at 1000 >"$work/env-preview"
grep -F '48x8' "$work/env-preview"

# Explicit flags must override environment values.
LEDDY_MATRIX_WIDTH=48 LEDDY_MATRIX_HEIGHT=8 LEDDY_SCROLL_SPEED=18 \
  "$leddy" preview --text HI --width 64 --height 10 --speed 30 --at 1000 \
  >"$work/flag-preview"
grep -F '64x10' "$work/flag-preview"

# Preview-only flags must fail closed on other commands instead of being
# silently accepted by the shared parser.
run_expect 2 "$leddy" publish --text HI --width 64
grep -Ei 'unknown|unexpected|width' "$work/stderr" >/dev/null

# Invalid enum-like values must be usage errors, not runtime failures.
run_expect 2 "$leddy" preview --text HI --direction diagonal
run_expect 2 "$leddy" preview --text HI --repeat 0

# Exercise the upstream inline-value truncation regression with a >97-byte
# --flag=value token. The command is offline and should parse the full text.
long_text='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
run_expect 0 "$leddy" preview "--text=$long_text" --width 128 --height 8 --at 1000
grep -F '128x8' "$work/stdout"

# A completed one-shot message is a valid blank display, not an error.
run_expect 0 "$leddy" preview --text HI --repeat once --speed 1000 --width 100 --height 8 --at 60000
grep -Ei 'blank|finished|empty' "$work/stdout" >/dev/null

# Static completions must be generated from the same contract without exposing
# ignored credentials.
run_expect 0 "$leddy" completion --shell bash
cp "$work/stdout" "$work/bash-completion"
run_expect 0 "$leddy" completion --shell zsh
cp "$work/stdout" "$work/zsh-completion"
for file in "$work/bash-completion" "$work/zsh-completion"; do
  test -s "$file"
  grep -F 'preview' "$file" >/dev/null
  if grep -Fq 'LEDDY_API_TOKEN' "$file"; then
    echo "credential-only LEDDY_API_TOKEN leaked into completion" >&2
    exit 1
  fi
done

printf 'Leddy flags-2-env canary passed\n'
