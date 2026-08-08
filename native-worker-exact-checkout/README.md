# Independent native worker exact-checkout canary

This test-org lane independently consumes the candidate native worker boundary
from `gha-indie-worker/gha-indie-worker.rs` at exact commit
`3ad79f6cb48de5d380372c37a063a0abadbe456d`.

On fixed Ubuntu 24.04, Windows Server 2025, and macOS 15 references, it:

1. checks out consumer and worker repositories at exact immutable commits with
   persisted checkout authentication disabled;
2. verifies the pinned worker commit and machine-readable policy, including
   injected Git-config/exec-path scrubbing and disabled replace objects;
3. runs the worker handoff, negative, checkout, and scheduler-integration corpus
   from outside the worker repository;
4. asks the worker boundary to clone this canary repository's exact pull-request
   head and requires `submodule_gitlink_forbidden`, preserving its real gitlinks
   as a cross-platform negative fixture;
5. asks the same boundary to clone submodule-free
   `flags-2-env-test/sops-just` at exact commit
   `933a239388449901bf8cccfd3db5c4d79fdec039` and requires success;
6. independently requires the exact evidence field set and recomputes the
   evidence digest over every field, in addition to checking requested SHA equals
   resolved detached `HEAD`, one exact `origin`, and no positive-fixture gitlinks;
   and
7. verifies both tracked source trees remain unchanged.

This split matters: the policy does not silently ignore a repository feature it
does not support, while a separate fixture proves that the supported path still
works on all three operating-system references. The independent digest ratchet
also prevents a wrapper from appending unbound metadata after the worker has
created its evidence record.

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
- AI-agent-bridge review queue: `ORESoftware/ai-agent-bridge.rs#121`
- Linear: `DEN-2582`, `DEN-2583`, and `DEN-2586`
