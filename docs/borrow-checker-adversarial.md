# Borrow-checker adversarial promotion gate

This independent `flags-2-env-test` lane checks an exact
`ORESoftware/flags-2-env` commit without using the product repository's own
workflow definitions or a vendored submodule that may predate the checker.

Repaired product candidate:

```text
b3b40f4fce95175b95b2d435d51d428593c1aff9
```

Initial (defective) candidate, retained for the record:

```text
d5a09c37e8b2a041dd2590b72b1129d1dbf28d42
```

The candidate's native sanitizer matrix, custom self-test, Kani proof, CBMC
model, and Z3 obligations were green throughout — including while all three
bypasses below were live. That is the point of this lane: those gates prove
the analyzer's abstract state machine, not the analyzer's boundaries.

## Required black-box cases

The workflow runs the candidate as an unmodified command-line program against
disposable C translation units and requires:

1. an unchecked allocation passed to a local helper that dereferences its
   pointer parameter to produce `error[null-deref]`;
2. a string literal containing waiver-shaped text on the line above a leak not
   to suppress `error[leak]`;
3. a comment with an empty waiver reason not to suppress `error[leak]`; and
4. a genuine C comment with a non-empty justification to retain the documented
   waiver behavior;
5. an unchecked allocation passed through a chain of forwarding helpers
   (`outer` → `middle` → `innermost`, where only the last dereferences) to
   produce `error[null-deref]`; and
6. a ternary guard (`p ? use(p) : 0`) to be recognized as a guard, producing
   no diagnostic.

Cases 5 and 6 were added when the repair landed, and they are not the same
kind of test. Case 5 is a defect case: the initial candidate fails it, because
the non-null obligation died at the first call hop. Case 6 is a regression
guard: both candidates pass it, and it exists because the first attempt at
case 5 introduced a false positive on real `parser.c` code — a ternary guard
the analyzer did not model. Enforcing 5 without 6 reports defects in correct
code.

Recorded outcome: the initial candidate fails cases 1, 2, 3, and 5 and passes
4 and 6. The repaired candidate passes all six on both platforms.

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
