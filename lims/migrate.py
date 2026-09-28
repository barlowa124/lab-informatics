import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

try:
    from .registry import Registry
except ImportError:
    from registry import Registry

MAPPING_VERSION = "scientific-csv-v2"
SAMPLE_COLUMNS = {"sample_id", "kind"}
ASSAY_COLUMNS = {"assay_id", "sample_id", "assay", "value", "unit"}
IDENTIFIER = re.compile(r"[A-Z0-9][A-Z0-9_-]*\Z")
UNITS = {"g/L", "mg/L", "mmol/L", "AU", "%"}
MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_runs (
    run_id TEXT PRIMARY KEY,
    report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_sources (
    run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
    source TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    content BLOB NOT NULL,
    PRIMARY KEY (run_id, source)
);
"""


def canonical_id(value):
    return value.strip().upper()


def read_rows(content, required):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
    try:
        headers = reader.fieldnames or []
        if len(set(headers)) != len(headers) or not required.issubset(headers):
            raise ValueError(f"expected unique headers including {sorted(required)}")
        rows = []
        for ordinal, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"ragged CSV record {ordinal}")
            rows.append({"record": ordinal, "raw": row})
        return rows
    except csv.Error as exc:
        raise ValueError(f"malformed CSV near line {reader.line_num}: {exc}") from exc


def plan_migration(samples, assays, existing_samples=()):
    sample_rows = read_rows(samples, SAMPLE_COLUMNS)
    assay_rows = read_rows(assays, ASSAY_COLUMNS)
    sample_counts = Counter(canonical_id(r["raw"]["sample_id"]) for r in sample_rows)
    assay_counts = Counter(canonical_id(r["raw"]["assay_id"]) for r in assay_rows)
    existing = {canonical_id(s) for s in existing_samples}
    for row in sample_rows:
        raw = row["raw"]
        key = canonical_id(raw["sample_id"])
        errors = []
        if not IDENTIFIER.fullmatch(key):
            errors.append("invalid_sample_id")
        if sample_counts[key] > 1:
            errors.append("ambiguous_sample_id")
        if key in existing:
            errors.append("existing_sample_id")
        if not raw["kind"].strip():
            errors.append("missing_kind")
        row.update(normalized={"sample_id": key, "kind": raw["kind"].strip()},
                   errors=errors, accepted=not errors)
    accepted_samples = {r["normalized"]["sample_id"] for r in sample_rows if r["accepted"]}
    for row in assay_rows:
        raw = row["raw"]
        key, sample = canonical_id(raw["assay_id"]), canonical_id(raw["sample_id"])
        errors = []
        if not IDENTIFIER.fullmatch(key):
            errors.append("invalid_assay_id")
        if assay_counts[key] > 1:
            errors.append("ambiguous_assay_id")
        if sample not in accepted_samples:
            errors.append("sample_not_accepted_in_this_import")
        if not raw["assay"].strip():
            errors.append("missing_assay")
        if raw["unit"].strip() not in UNITS:
            errors.append("unsupported_unit")
        try:
            value = float(raw["value"])
            if not math.isfinite(value):
                raise ValueError("nonfinite")
        except ValueError:
            value = None
            errors.append("invalid_value")
        row.update(normalized={"assay_id": key, "sample_id": sample,
                               "assay": raw["assay"].strip(), "value": value,
                               "unit": raw["unit"].strip()},
                   errors=errors, accepted=not errors)
    return {"samples": sample_rows, "assays": assay_rows}


def migrate(registry, samples, assays, dry_run=False):
    digests = {"samples.csv": hashlib.sha256(samples).hexdigest(),
               "assays.csv": hashlib.sha256(assays).hexdigest()}
    identity = json.dumps({"mapping_version": MAPPING_VERSION, "sources": digests}, sort_keys=True)
    run_id = hashlib.sha256(identity.encode()).hexdigest()
    db = registry.db
    if db.in_transaction:
        raise ValueError("migration requires a connection without an active transaction")
    if not dry_run:
        db.executescript(MIGRATION_SCHEMA)
    db.execute("BEGIN IMMEDIATE" if not dry_run else "BEGIN")
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "migration_runs" in tables:
            previous = db.execute("SELECT report FROM migration_runs WHERE run_id=?", (run_id,)).fetchone()
            if previous:
                report = json.loads(previous["report"])
                db.rollback()
                return {**report, "replayed": True, "dry_run": dry_run,
                        "committed": False, "previously_committed": True,
                        "written_this_call": {"samples": 0, "assays": 0}}
        existing = [r[0] for r in db.execute("SELECT sample_id FROM samples")]
        plan = plan_migration(samples, assays, existing)
        reconciliation = {}
        for source, rows in plan.items():
            accepted = sum(r["accepted"] for r in rows)
            reconciliation[source] = {"input": len(rows), "accepted": accepted,
                                      "rejected": len(rows) - accepted}
        report = {"mapping_version": MAPPING_VERSION, "run_id": run_id,
                  "source_sha256": digests, "dry_run": dry_run, "replayed": False,
                  "committed": not dry_run, "previously_committed": False,
                  "reconciliation": reconciliation,
                  "records": plan, "written_this_call": {
                      source: 0 if dry_run else counts["accepted"]
                      for source, counts in reconciliation.items()}}
        if dry_run:
            db.rollback()
            return report
        serialized = json.dumps(report, sort_keys=True, allow_nan=False)
        db.execute("INSERT INTO migration_runs VALUES (?,?)", (run_id, serialized))
        for source, content in (("samples.csv", samples), ("assays.csv", assays)):
            db.execute("INSERT INTO migration_sources VALUES (?,?,?,?)",
                       (run_id, source, digests[source], content))
        import time
        now = time.time()
        experiment = "MIG-" + run_id
        if any(counts["accepted"] for counts in reconciliation.values()):
            db.execute("INSERT INTO experiments VALUES (?,?,?,?,?)",
                       (experiment, "Scientific CSV migration", "registered",
                        json.dumps({"run_id": run_id}), now))
            registry._audit("experiment", experiment, "create", {"run_id": run_id})
        for row in plan["samples"]:
            if not row["accepted"]:
                continue
            sample = row["normalized"]
            meta = {"migration_run": run_id, "source_record": row["record"]}
            db.execute("INSERT INTO samples VALUES (?,?,?,?)",
                       (sample["sample_id"], sample["kind"], json.dumps(meta), now))
            registry._audit("sample", sample["sample_id"], "migrate", meta)
        for row in plan["assays"]:
            if not row["accepted"]:
                continue
            assay = row["normalized"]
            content = json.dumps(assay, sort_keys=True, allow_nan=False).encode()
            digest = hashlib.sha256(content).hexdigest()
            meta = {"migration_run": run_id, "source_record": row["record"], "measurement": assay}
            db.execute("INSERT INTO results (experiment_id,name,content_sha256,meta,created) VALUES (?,?,?,?,?)",
                       (experiment, assay["assay_id"], digest, json.dumps(meta), now))
            registry._audit("result", f"{experiment}:{assay['assay_id']}", "migrate",
                            {"sha256": digest, "source_record": row["record"]})
        registry._audit("migration", run_id, "commit", reconciliation)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--assays", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    samples, assays = args.samples.read_bytes(), args.assays.read_bytes()
    read_rows(samples, SAMPLE_COLUMNS)
    read_rows(assays, ASSAY_COLUMNS)
    reserved = {(args.output / name).resolve() for name in ("samples.csv", "assays.csv", "reconciliation.json")}
    if args.db.resolve() in reserved:
        raise ValueError("database path conflicts with an output artifact")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.dry_run and args.db.exists():
        import sqlite3
        registry = Registry()
        source = sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            source.backup(registry.db)
        finally:
            source.close()
    else:
        registry = Registry(":memory:" if args.dry_run else str(args.db))
    try:
        report = migrate(registry, samples, assays, args.dry_run)
        (args.output / "samples.csv").write_bytes(samples)
        (args.output / "assays.csv").write_bytes(assays)
        (args.output / "reconciliation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"run_id": report["run_id"], "committed": report["committed"],
                          "replayed": report["replayed"], "previously_committed": report["previously_committed"],
                          "reconciliation": report["reconciliation"]}, indent=2))
    finally:
        registry.db.close()


if __name__ == "__main__":
    main()
