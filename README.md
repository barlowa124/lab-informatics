# lab-informatics

[![ci](https://github.com/barlowa124/lab-informatics/actions/workflows/ci.yml/badge.svg)](https://github.com/barlowa124/lab-informatics/actions/workflows/ci.yml)


Software for lab data plumbing. Two related projects merged into one
repository, each a self-contained package with its own tests and commit
history (imported via subtree merge).

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

Both sit at the lab-software boundary: getting data out of instruments,
getting records into databases. Both emphasize byte-preserving capture
and auditable migration over validated-system claims.
