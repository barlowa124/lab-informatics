import concurrent.futures
import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lims.migrate import migrate, plan_migration
from lims.registry import Registry

REPO = Path(__file__).resolve().parent.parent

SAMPLES = b'sample_id,kind\n s-1 ,rna\nS-2,protein\n s-2 ,protein\nS-3,\n'
ASSAYS = b'assay_id,sample_id,assay,value,unit\na-1,s-1,protein,2.5,g/L\na-2,S-2,protein,1,g/L\na-3,S-1,protein,nan,g/L\na-4,S-1,protein,1,unknown\n'

ALL_TABLES = ("samples", "experiments", "results", "audit_log",
              "migration_runs", "migration_sources", "plates")


@pytest.fixture
def reg():
    return Registry(":memory:")


def table_counts(db):
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ALL_TABLES}


def test_plan_normalizes_and_rejects():
    plan = plan_migration(SAMPLES, ASSAYS)
    samples, assays = plan["samples"], plan["assays"]

    assert samples[0]["normalized"]["sample_id"] == "S-1"
    assert samples[0]["accepted"]
    assert "ambiguous_sample_id" in samples[1]["errors"]
    assert "ambiguous_sample_id" in samples[2]["errors"]
    assert not samples[1]["accepted"] and not samples[2]["accepted"]
    assert "missing_kind" in samples[3]["errors"]

    assert sum(r["accepted"] for r in samples) == 1
    assert sum(not r["accepted"] for r in samples) == 3
    assert sum(r["accepted"] for r in assays) == 1
    assert sum(not r["accepted"] for r in assays) == 3

    assert samples[0]["raw"]["sample_id"] == " s-1 "
    assert samples[3]["raw"]["kind"] == ""
    assert assays[0]["raw"]["value"] == "2.5"
    assert assays[2]["raw"]["value"] == "nan"
    assert assays[3]["raw"]["unit"] == "unknown"


def test_migrate_commits_records_and_sources(reg):
    report = migrate(reg, SAMPLES, ASSAYS)
    assert report["committed"] and not report["dry_run"]

    assert reg.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
    assert reg.db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1

    blobs = {r["source"]: (r["sha256"], r["content"]) for r in reg.db.execute(
        "SELECT source, sha256, content FROM migration_sources")}
    assert blobs["samples.csv"] == (hashlib.sha256(SAMPLES).hexdigest(), SAMPLES)
    assert blobs["assays.csv"] == (hashlib.sha256(ASSAYS).hexdigest(), ASSAYS)

    for counts in report["reconciliation"].values():
        assert counts["input"] == counts["accepted"] + counts["rejected"]
    assert report["reconciliation"]["samples"] == {
        "input": 4, "accepted": 1, "rejected": 3}
    assert report["reconciliation"]["assays"] == {
        "input": 4, "accepted": 1, "rejected": 3}

    assert reg.verify_audit_chain()["ok"]

    meta = json.loads(reg.db.execute(
        "SELECT meta FROM results").fetchone()["meta"])
    assert meta["measurement"]["sample_id"] == "S-1"
    assert meta["measurement"]["value"] == 2.5


def test_identical_replay_writes_nothing(reg):
    migrate(reg, SAMPLES, ASSAYS)
    before = table_counts(reg.db)
    report = migrate(reg, SAMPLES, ASSAYS)
    assert report["replayed"]
    assert report["written_this_call"] == {"samples": 0, "assays": 0}
    assert table_counts(reg.db) == before
    assert all(before[t] > 0 for t in
               ("samples", "experiments", "results", "audit_log",
                "migration_runs", "migration_sources"))


def test_dry_run_leaves_database_untouched(reg):
    report = migrate(reg, SAMPLES, ASSAYS, dry_run=True)
    assert report["committed"] is False
    assert report["written_this_call"] == {"samples": 0, "assays": 0}
    for t in ("samples", "experiments", "results", "audit_log"):
        assert reg.db.execute(
            f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    tables = {r[0] for r in reg.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "migration_runs" not in tables
    assert "migration_sources" not in tables


def test_existing_sample_blocks_import(reg):
    reg.register_sample("S-1", "dna")
    report = migrate(reg, SAMPLES, ASSAYS)
    assert report["reconciliation"]["samples"]["accepted"] == 0
    assert report["reconciliation"]["assays"]["accepted"] == 0

    plan = report["records"]
    assert "existing_sample_id" in plan["samples"][0]["errors"]
    assert "sample_not_accepted_in_this_import" in plan["assays"][0]["errors"]

    row = reg.db.execute(
        "SELECT kind FROM samples WHERE sample_id='S-1'").fetchone()
    assert row["kind"] == "dna"
    assert reg.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
    assert reg.db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0


def test_duplicate_assay_ids_reject_both():
    samples = b"sample_id,kind\ns-9,rna\n"
    assays = (b"assay_id,sample_id,assay,value,unit\n"
              b"a-9,s-9,protein,1,g/L\n"
              b" A-9 ,s-9,protein,2,g/L\n")
    plan = plan_migration(samples, assays)
    assert all(not r["accepted"] for r in plan["assays"])
    assert all("ambiguous_assay_id" in r["errors"] for r in plan["assays"])


def test_malformed_inputs_fail_without_writes():
    bad_inputs = [
        (b"sample_id\ns-1\n", ASSAYS),
        (SAMPLES, b"assay_id,sample_id,assay,value\na-1,s-1,p,1\n"),
        (b"sample_id,sample_id,kind\ns-1,x,rna\n", ASSAYS),
        (b"sample_id,kind\ns-1,rna,extra\n", ASSAYS),
        (b"sample_id,kind\n\xff\xfe\n", ASSAYS),
    ]
    for samples, assays in bad_inputs:
        fresh = Registry(":memory:")
        with pytest.raises(ValueError):
            migrate(fresh, samples, assays)
        for t in ("samples", "experiments", "results", "audit_log",
                  "migration_runs", "migration_sources"):
            assert fresh.db.execute(
                f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_nonfinite_and_empty_values_rejected():
    samples = b"sample_id,kind\ns-1,rna\n"
    for bad in (b"inf", b"-inf", b"nan", b""):
        assays = (b"assay_id,sample_id,assay,value,unit\n"
                  b"a-1,s-1,protein," + bad + b",g/L\n")
        plan = plan_migration(samples, assays)
        row = plan["assays"][0]
        assert not row["accepted"]
        assert "invalid_value" in row["errors"]


def test_unsupported_unit_rejected_unconverted():
    plan = plan_migration(SAMPLES, ASSAYS)
    row = plan["assays"][3]
    assert not row["accepted"]
    assert "unsupported_unit" in row["errors"]
    assert row["raw"]["unit"] == "unknown"
    assert row["normalized"]["unit"] == "unknown"
    assert row["normalized"]["value"] == 1.0


def test_commit_failure_rolls_back_everything(reg, monkeypatch):
    original = reg._audit

    def fail_on_commit(entity, entity_id, action, detail=None):
        if action == "commit":
            raise RuntimeError("injected commit failure")
        return original(entity, entity_id, action, detail)

    monkeypatch.setattr(reg, "_audit", fail_on_commit)
    with pytest.raises(RuntimeError):
        migrate(reg, SAMPLES, ASSAYS)

    for t in ALL_TABLES:
        assert reg.db.execute(
            f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    assert not reg.db.in_transaction


def run_cli(*args, cwd=REPO):
    return subprocess.run(
        [sys.executable, "-m", "lims.migrate", *args],
        cwd=cwd, capture_output=True, text=True)


def write_inputs(tmp_path):
    samples, assays = tmp_path / "samples.csv", tmp_path / "assays.csv"
    samples.write_bytes(SAMPLES)
    assays.write_bytes(ASSAYS)
    return samples, assays


def test_cli_dry_run_nonexistent_db(tmp_path):
    samples, assays = write_inputs(tmp_path)
    db, out = tmp_path / "fresh.sqlite3", tmp_path / "out"
    proc = run_cli("--samples", str(samples), "--assays", str(assays),
                   "--db", str(db), "--output", str(out), "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert not db.exists()
    assert (out / "samples.csv").read_bytes() == SAMPLES
    assert (out / "assays.csv").read_bytes() == ASSAYS
    report = json.loads((out / "reconciliation.json").read_text())
    assert report["committed"] is False


def test_cli_replay_does_not_duplicate(tmp_path):
    samples, assays = write_inputs(tmp_path)
    db, out1, out2 = (tmp_path / "db.sqlite3", tmp_path / "out1",
                      tmp_path / "out2")
    args = ["--samples", str(samples), "--assays", str(assays),
            "--db", str(db)]
    assert run_cli(*args, "--output", str(out1)).returncode == 0
    assert run_cli(*args, "--output", str(out2)).returncode == 0
    assert (out2 / "reconciliation.json").exists()

    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM migration_runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_cli_existing_output_dir_errors_without_db_write(tmp_path):
    samples, assays = write_inputs(tmp_path)
    db, out = tmp_path / "db.sqlite3", tmp_path / "out"
    args = ["--samples", str(samples), "--assays", str(assays),
            "--db", str(db), "--output", str(out)]
    assert run_cli(*args).returncode == 0
    before = db.read_bytes()
    proc = run_cli(*args)
    assert proc.returncode != 0
    assert db.read_bytes() == before


def test_cli_dry_run_existing_db_read_only(tmp_path):
    samples, assays = write_inputs(tmp_path)
    db = tmp_path / "db.sqlite3"
    args = ["--samples", str(samples), "--assays", str(assays),
            "--db", str(db)]
    assert run_cli(*args, "--output", str(tmp_path / "out1")).returncode == 0
    before = db.read_bytes()
    proc = run_cli(*args, "--output", str(tmp_path / "out2"), "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert db.read_bytes() == before


def test_unterminated_quoted_field_rejected(reg):
    bad_samples = b'sample_id,kind\ns-1,"rna\n'
    with pytest.raises(ValueError, match="malformed CSV"):
        migrate(reg, bad_samples, ASSAYS)
    for table in ("samples", "experiments", "results", "audit_log"):
        assert reg.db.execute(
            f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

    bad_assays = b'assay_id,sample_id,assay,value,unit\na-1,s-1,protein,"2.5\n'
    with pytest.raises(ValueError, match="malformed CSV"):
        migrate(reg, SAMPLES, bad_assays)


def test_cli_malformed_input_creates_nothing(tmp_path):
    samples = tmp_path / "samples.csv"
    samples.write_bytes(b'sample_id,kind\ns-1,"rna\n')
    assays = tmp_path / "assays.csv"
    assays.write_bytes(ASSAYS)
    db, out = tmp_path / "db.sqlite3", tmp_path / "out"
    proc = run_cli("--samples", str(samples), "--assays", str(assays),
                   "--db", str(db), "--output", str(out))
    assert proc.returncode != 0
    assert not out.exists()
    assert not db.exists()


def test_replay_reports_committed_flags(reg):
    first = migrate(reg, SAMPLES, ASSAYS)
    assert first["committed"] is True
    assert first["previously_committed"] is False
    before = table_counts(reg.db)
    for dry_run in (False, True):
        report = migrate(reg, SAMPLES, ASSAYS, dry_run=dry_run)
        assert report["replayed"] is True
        assert report["committed"] is False
        assert report["previously_committed"] is True
        assert report["written_this_call"] == {"samples": 0, "assays": 0}
        assert not reg.db.in_transaction
    assert table_counts(reg.db) == before


@pytest.mark.parametrize("reserved", ["samples.csv", "assays.csv", "reconciliation.json"])
def test_cli_db_cannot_shadow_output_artifact(tmp_path, reserved):
    samples, assays = write_inputs(tmp_path)
    out = tmp_path / "out"
    db = out / reserved
    proc = run_cli("--samples", str(samples), "--assays", str(assays),
                   "--db", str(db), "--output", str(out))
    assert proc.returncode != 0
    assert not out.exists()
    assert not db.exists()


def test_concurrent_identical_runs_commit_once(tmp_path):
    db_path = tmp_path / "shared.sqlite3"
    Registry(str(db_path)).db.close()
    barrier = threading.Barrier(2)

    def attempt():
        registry = Registry(str(db_path))
        try:
            barrier.wait(timeout=30)
            return migrate(registry, SAMPLES, ASSAYS)
        finally:
            registry.db.close()

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        reports = list(pool.map(lambda _: attempt(), range(2)))
    committed = [r for r in reports if r["committed"]]
    replayed = [r for r in reports if r["replayed"]]
    assert len(committed) == 1
    assert len(replayed) == 1
    assert replayed[0]["previously_committed"] is True

    check = Registry(str(db_path))
    try:
        assert check.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
        assert check.db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
        assert check.verify_audit_chain()["ok"]
    finally:
        check.db.close()
