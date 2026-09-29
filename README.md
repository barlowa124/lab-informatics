# lab-informatics

Software for lab data plumbing: LIMS data migration and instrument-output
capture. Two related projects merged into one repository, each a
self-contained package with its own tests and commit history (imported via
subtree merge).

## Packages

| Directory | What it does |
|---|---|
| `labStackDev/` | LIMS migration prototype: versioned CSV normalization, rejection rules, transactional migration with rollback, reconciliation that must account for every parsed record. Synthetic fixtures only. |
| `lab_instrument_gateway/` | `lablink`: instrument-side capture gateway — protocol parsing, a simulator for offline development, FastAPI capture service, and a small dashboard. |

## Running tests

```bash
cd labStackDev && python -m pytest -q tests/
cd lab_instrument_gateway && python -m pytest -q tests/
```

Each subdirectory retains its own `AGENTS.md` with project-specific rules
(synthetic fixtures only, no validated-LIMS/GMP claims), which still apply.

## Why one repo

Both sit at the lab-software boundary: getting data out of instruments and
records into databases, with the same emphasis on byte-preserving capture
and auditable migration rather than validated-system claims.
