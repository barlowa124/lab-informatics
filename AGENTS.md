# Project guidance

- Run `python -m pytest -q tests/` after changes. Scientific comparison tests require pandas and scipy and otherwise skip.
- Migration fixtures are synthetic. Keep production data and local SQLite databases out of Git.
- CSV normalization and rejection rules are versioned in `lims/migrate.py`. Reconciliation must account for every parsed record.
- Preserve source bytes. Do not describe this prototype as a validated LIMS or GMP system.
