# Architecture conformance

This independent fixture proves the intentional mixed Zed/Git ownership used by `flags-2-env-test/feature-matrix`:

- Zed declares the logical dependency `oresoftware/flags-2-env` and installs it below `.vendor/.zed`.
- Git records the exact source commit at `.vendor/.zed/oresoftware/flags-2-env`.
- Both tools adopt the same physical checkout; no second materialization is permitted.
- The check is credential-free and validates the immutable Git gitlink without fetching the producer.
- Four adversarial mutations prove that path, source, dependency-cardinality, and credential assertions are not vacuous.

Run with:

```bash
python3 architecture-contract/test_contract.py
```

A successful report includes the exact producer gitlink SHA and `physical_checkouts=1`.
