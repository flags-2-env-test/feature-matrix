# Independent native worker exact-checkout canary

This test-org lane independently consumes the candidate native worker boundary
from `gha-indie-worker/gha-indie-worker.rs` at exact commit
`4ff9865bc71c047bbfad8fdf797a3545b19f85de`.

On fixed Ubuntu 24.04, Windows Server 2025, and macOS 15 references, it:

1. checks out consumer and worker repositories at exact immutable commits with
   persisted checkout authentication disabled;
2. verifies the pinned worker commit and machine-readable policy;
3. runs the worker handoff, negative, checkout, and scheduler-integration corpus
   from outside the worker repository;
4. asks the worker boundary to clone this test repository's pull-request head by
   exact SHA without a branch, tag, embedded credential, or fallback transport;
5. ratchets requested SHA equals resolved detached `HEAD`, one exact `origin`, no
   submodule gitlinks, and digest-bound evidence; and
6. verifies both tracked source trees remain unchanged.

The lane does not use the GitHub PAT, Linear token, Cloudflare token, R2 keys,
repository secrets, signing material, or a persistent external service.

## Evidence boundary

This proves external consumer compatibility and hosted operating-system
portability for the exact-checkout operation. It does not prove physical Apple
Silicon or Windows host enrollment, production device identity, sandbox
isolation, cleanup or reimage, workflow-step execution, failover, capacity, or
release-signing readiness.

## Coordination

- Worker implementation: `gha-indie-worker/gha-indie-worker.rs#24`
- Scheduler and lease prerequisite: `gha-indie-worker/gha-indie-worker.rs#21`
- Typed dispatch prerequisite: `gha-indie-worker/gha-indie-worker.rs#14`
- Program tracker: `gha-indie-worker/gha-indie-worker.rs#15`
- Linear: `DEN-2582`, `DEN-2583`, and `DEN-2586`
