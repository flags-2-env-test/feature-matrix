# gha-indie-worker consumer conformance

This directory is an independent, secret-free consumer canary for the native
dispatch contract under development in `gha-indie-worker/gha-indie-worker.rs`.

The workflow pins worker candidate
`8e6be9ce13d07caf189bd4cdd57cb39a019d7b31`, which stacks the native
enrollment/scheduling/lease simulator on the typed dispatch/profile contract.

On Ubuntu 24.04, Windows Server 2025, and macOS 15, the canary:

1. checks out the consumer and worker at exact immutable commits;
2. binds realistic Linux/x64, Windows/x64, and macOS/arm64 jobs through
   `gha-bind-plan`;
3. verifies canonical dispatch-v2 runner targets and sorted capabilities;
4. proves unsupported architecture aliases, target/profile mismatches,
   caller-supplied commands, and native profiles without `native` fail closed;
5. enrolls one lab host per operating-system target in the dependency-free
   fleet simulator;
6. proves exact host assignment with no cross-platform fallback; and
7. proves active duplicate deliveries reuse one lease while terminal
   duplicates return the existing receipt.

## Evidence boundary

These jobs run on GitHub-hosted reference machines. They independently prove
consumer compatibility and protocol behavior across the three operating
systems. They do not prove that physical Apple Silicon or Windows machines are
enrolled in an independent fleet, protected by production device identity,
isolated, cleaned, reimaged, patched, recoverable, or ready for untrusted work.

No GitHub PAT, Linear token, Cloudflare token, R2 credential, signing material,
repository secret, or persistent external service is used by this canary.

## Tracking

- `gha-indie-worker/gha-indie-worker.rs#14` — typed native dispatch/profile binding
- `gha-indie-worker/gha-indie-worker.rs#21` — enrollment, scheduling, and lease lab
- `gha-indie-worker/gha-indie-worker.rs#15` — program tracker
- Linear `DEN-2586` — Linux/macOS/Windows conformance and fault-injection gates
