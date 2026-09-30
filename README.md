# lab-informatics

[![ci](https://github.com/barlowa124/lab-informatics/actions/workflows/ci.yml/badge.svg)](https://github.com/barlowa124/lab-informatics/actions/workflows/ci.yml)


Software for lab data plumbing. Two related projects merged into one
repository, each a self-contained package with its own tests and commit
history (imported via subtree merge).


## Where this sits in the portfolio

`lab-informatics` is the **lab data plumbing and integrity** repo: a LIMS-style registry with hash-chained audit trails, HMAC signatures, and reason-for-change (`labStackDev`), plus instrument capture (`lablink`). Sibling repos:
[trust-tools](https://github.com/barlowa124/trust-tools) (agent security
and evals), [bio-qc](https://github.com/barlowa124/bio-qc) (lab-data QC
pipelines), [lab-informatics](https://github.com/barlowa124/lab-informatics)
(lab data plumbing and integrity),
[llm-posttraining](https://github.com/barlowa124/llm-posttraining)
(training-stage behavior work),
[protein-ml](https://github.com/barlowa124/protein-ml) (protein fitness
ML), and [mol-ml](https://github.com/barlowa124/mol-ml) (small-molecule
ML).

## Packages

| Directory | What it does |
|---|---|
| `labStackDev/` | LIMS migration prototype: versioned CSV normalization, rejection rules, transactional migration with rollback, reconciliation that must account for every parsed record. Synthetic fixtures only. |
| `lab_instrument_gateway/` | `lablink`: instrument-side capture gateway — protocol parsing, a simulator for offline development, FastAPI capture service, and a small dashboard. |
| `analytics/` | dbt project (DuckDB) over the LIMS tables — staging/intermediate/mart layers, schema and domain tests, run by CI. See `analytics/README.md`. |

## Running tests

```bash
cd labStackDev && python -m pytest -q tests/
cd lab_instrument_gateway && python -m pytest -q tests/
```

## Docker

`Dockerfile` builds one image covering all three runnable pieces, and
`docker-compose.yml` gives each a service:

```bash
export LABLINK_API_TOKEN=<any-token>   # setpoint writes are bearer-gated
docker compose up lablink              # capture API + dashboard on :8000
docker compose up analytics            # seeds -> dbt build -> docs on :8080
docker compose up lims-demo            # one-shot demo, writes labStackDev/results/
```

The lablink service runs the emulator and capture service in-process, so
no instrument hardware is needed. `LABLINK_API_HOST=0.0.0.0` is set only
in the container, while local runs still default to loopback. The analytics
service regenerates its seed CSVs inside the container by driving the
same Registry and CaptureService code paths, then builds the dbt project
and serves the docs site from `target/` on port 8080.

The lablink container's API binding was verified end-to-end locally (env
overrides launch the emulator, capture service, and API together). The image
itself is authored for `python:3.11-slim` but has not been built here
because Docker is not installed on this machine.

Each subdirectory retains its own `AGENTS.md` with project-specific rules
(synthetic fixtures only, no validated-LIMS/GMP claims), which still apply.

## Why one repo

Both sit at the lab-software boundary: getting data out of instruments,
getting records into databases. Both emphasize byte-preserving capture
and auditable migration over validated-system claims.
