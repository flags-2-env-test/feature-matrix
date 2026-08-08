# Borrow-checker adversarial promotion gate

This independent `flags-2-env-test` lane checks an exact
`ORESoftware/flags-2-env` commit without using the product repository's own
workflow definitions or a vendored submodule that may predate the checker.

Initial product candidate:

```text
d5a09c37e8b2a041dd2590b72b1129d1dbf28d42
```

The candidate's native sanitizer matrix, custom self-test, Kani proof, CBMC
model, and Z3 obligations are already green. Those gates do not currently
exercise two analyzer-boundary failures found during adversarial review.

## Required black-box cases

The workflow runs the candidate as an unmodified command-line program against
disposable C translation units and requires:

1. an unchecked allocation passed to a local helper that dereferences its
   pointer parameter to produce `error[null-deref]`;
2. a string literal containing waiver-shaped text on the line above a leak not
   to suppress `error[leak]`;
3. a comment with an empty waiver reason not to suppress `error[leak]`; and
4. a genuine C comment with a non-empty justification to retain the documented
   waiver behavior.

The first candidate is expected to fail cases 1–3. This PR must remain draft and
unmerged until the product PR is repaired, this workflow is repinned to its new
exact commit, and both fixed platform jobs pass.

## Evidence and isolation

Ubuntu 24.04 and macOS 15 each:

- check out the test harness and product candidate with persisted credentials
  disabled;
- verify the exact detached product commit;
- require the candidate's own self-test to pass first;
- run the non-skipping adversarial cases;
- require both tracked checkouts to remain clean; and
- retain commit-addressed JSON evidence for 14 days.

The lane has read-only repository permissions. It does not use a PAT, Linear
key, Cloudflare token, R2 credential, provider key, Docker daemon, public
registry, or persistent external service.

Product review: `ORESoftware/flags-2-env#40`.
