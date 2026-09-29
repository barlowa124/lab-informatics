# analytics

dbt project over the LIMS registry tables in `labStackDev`. The registry
records samples, experiments, plate-well assignments, and results, all
under a hash-chained audit log. This project models them into staging,
intermediate, and mart layers so the lab's activity can be queried as
clean tables.

The warehouse is DuckDB (`dbt-duckdb`). The models use ANSI-portable SQL
and standard dbt features, so they translate to a Snowflake-class
warehouse with only source configuration changes. Nothing here claims
production Snowflake deployment.

## Layout

```text
seeds/raw_*.csv  -> staging (views) -> intermediate (views) -> marts (tables)
```

`generate_fixtures.py` produces the seeds by driving the real `Registry`
API. Samples are registered, wells assigned, results attached, and the
audit log is written by the registry itself, including one e-signature
over the lock transition. The capture seeds are produced the same way.
A `CaptureService` polls the emulated instrument, including a
dropped-link fault that yields real transport-error rows, and the cold
start produces genuine `temp-out-of-band` alarms while the vessel ramps
to setpoint. Seeds are checked in so `dbt build` works standalone.

| Layer | Model | Grain |
|---|---|---|
| staging | `stg_samples`, `stg_experiments`, `stg_plates`, `stg_results`, `stg_audit_log`, `stg_audit_signature` | one row per source row, `meta` JSON unpacked, epoch floats to timestamps |
| staging | `stg_readings`, `stg_alarms` | one row per captured reading / raised alarm |
| intermediate | `int_well_assignments`, `int_state_durations` | well-to-sample-to-experiment join; `LEAD()` over audit transitions gives time-in-state |
| marts | `dim_sample`, `dim_experiment` | conformed entities |
| marts | `fct_plate_well`, `fct_result` | one row per well assignment / attached result |
| marts | `fct_reading`, `fct_alarm` | one row per channel reading / alarm, alarms joined to the reading that breached |
| marts | `mart_experiment_audit` | per-experiment lifecycle rollup: transition count, time in pipeline, signature coverage |
| marts | `mart_channel_health` | per-channel rollup: quality mix, ok-rate, value range, alarm count |

Measured output on the committed seeds: 24 samples, 3 experiments, 24
well assignments, 16 results, 75 audit rows, 1 signature, 40 readings
(35 ok, 5 transport-error), 4 alarms.

## Why a star schema here

The fact tables are `fct_plate_well` (assignments) and `fct_result`
(attachments); both are long and event-like, so keeping conformed
`dim_sample`/`dim_experiment` around them pays off when the same dims
join across facts. A one-big-table denormalization would be fine at this
fixture size, and for a single dashboard it would be the simpler call,
but it bakes the sample-and-experiment attribute joins into every
downstream query and duplicates the audit rollups per row. The star
layout keeps each entity's attributes in one place, which is the shape
that survives contact with more facts later (runs, QC flags, storage
locations).

## Tests

65 data tests plus four singular domain tests.

- `assert_audit_seq_contiguous` requires the audit log's `seq` to have
  no gaps. The hash chain proves ordering, and contiguity proves no row
  was silently dropped.
- `assert_locked_experiments_signed` requires every `locked` experiment
  to carry at least one e-signature, the review step the registry
  expects before a record is finalized.
- `assert_alarms_backed_by_ok_reading` requires every alarm to join to
  the `ok` reading that breached its rule. The capture service writes
  both rows in one persist pass, so a dangling alarm means it fired
  without evidence.
- `assert_error_readings_null_value` requires failed captures to carry
  a null value and ok readings to carry a number, so bad readings can't
  be averaged into channel stats.

## Run it

```bash
pip install "dbt-duckdb>=1.8,<1.10"
cd analytics
DBT_PROFILES_DIR=. dbt build
```

`dbt build` seeds the raw tables, builds all models, and runs the test
suite in one pass. `lab_lims.duckdb` is gitignored. Regenerate seeds with
`python analytics/generate_fixtures.py` from the repo root.
