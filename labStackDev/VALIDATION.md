# VALIDATION.md: labStackDev LIMS prototype

This document maps the system's integrity properties onto the
IQ/OQ/PQ validation vocabulary used in regulated-lab software. **This
is a validation-plan demonstration on a prototype. It documents how
the system would be qualified, and does not claim the system is
validated, GxP-compliant, or 21 CFR Part 11 conformant.** No external
assessment exists.

## Scope

`lims/registry.py` (sample registry, experiment status machine, plate
assignment, result attachment, hash-chained audit log) and
`lims/esign.py` (HMAC-bound signatures over audit rows, reason-for-change
on mutations). SQLite-only, stdlib-only.

## Installation qualification (IQ)

| Item | Evidence |
|---|---|
| Runtime | CPython 3.9+, no third-party dependencies for `lims/` |
| Tests suite presence | `tests/` runs via `python -m pytest -q tests/` |
| Expected baseline | 60 passed, 1 skipped (pandas/scipy-dependent skip) |

## Operational qualification (OQ)

OQ evidence is the test suite. Each requirement below names the test
that exercises it. `tests/test_lims.py`, `tests/test_esign.py`.

| Requirement | Test(s) |
|---|---|
| Audit rows hash-chain (edit/reorder breaks linkage) | `test_audit_chain_verifies_and_detects_tamper`, `test_verify_catches_tamper`, `test_audit_checkpoint_*` |
| Status machine is forward-only | `test_status_machine_forward_only` |
| Locked experiments reject mutation | `test_locked_experiment_refuses_mutation` |
| Signature verifies against signer key | `test_sign_and_verify` |
| Wrong key / forged signature detected | `test_wrong_key_fails` |
| Field-level tamper invalidates via chain+signature check | `test_tampered_row_invalidates_signature` |
| Signing a nonexistent audit row refused | `test_sign_missing_row_refused` |
| Signature meaning restricted to authored/reviewed/approved | `test_bad_meaning_refused` |
| Missing signing key fails closed | `test_no_key_raises` |
| Unsigned-audit-row report | `test_unsigned_rows_report` |
| Reason-for-change lands inside the hashed detail | `test_reason_lands_in_chain` |
| Reason optional, chain still verifies | `test_reason_optional` |

## Performance qualification (PQ)

`python lims/demo_lims.py` runs a scripted sample lifecycle
(register → queue → assign → process → analyze → lock) against a fresh
database and writes `results/lims_summary.json` +
`results/lims_audit_log.csv`. It exercises the intended-use path end to
end on synthetic data.

## Known limits

- HMAC signing is symmetric. Verification requires the same key, so it
  demonstrates content binding, not non-repudiation or identity proof.
- No access control, no timestamp authority, no retention policy.
  All three are required for a real Part 11 claim. None are implemented here.
- Migration reconciliation rules live in `lims/migrate.py` and are
  versioned with the code. They are part of what a real validation
  would freeze.
