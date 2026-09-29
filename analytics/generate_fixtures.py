"""Generate the dbt seed CSVs by driving the real LIMS registry.

The fixtures are synthetic, but every row is produced by the same code
path the LIMS uses for live records: samples are registered, wells are
assigned, results are attached, and the audit log is written by the
registry itself. The seeds therefore carry the same schema, status
transitions, and hash-chained audit trail as a real run.

The capture seeds are generated the same way. A CaptureService polls the
emulated instrument, including a dropped-link fault, so the readings and
alarms tables carry real quality flags and real rule breaches.

Run from the repo root (takes ~10 s because the instrument model needs
wall-clock time to ramp toward setpoints):

    python analytics/generate_fixtures.py
"""

import csv
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "labStackDev" / "lims"))
sys.path.insert(0, str(ROOT / "labStackDev"))
sys.path.insert(0, str(ROOT / "lab_instrument_gateway"))

from registry import Registry  # noqa: E402
from esign import sign  # noqa: E402
from lablink.capture import CaptureService  # noqa: E402
from lablink.driver import InstrumentClient  # noqa: E402
from lablink.simulator import ThreadedInstrumentServer  # noqa: E402

SEEDS = Path(__file__).resolve().parent / "seeds"

WELLS_24 = [f"{r}{c:02d}" for r in "ABCD" for c in range(1, 7)]


def build_registry() -> Registry:
    reg = Registry(":memory:")

    # Experiment 1: completed and locked, 16 RNA samples on plate P1.
    exp1 = reg.create_experiment(
        "EXP-RNA-0042", "iPSC batch 4 RNA-seq",
        {"pipeline": "salmon_direct", "genome": "GRCh38", "lab": "stem-cell"})
    reg.transition(exp1, "queued")
    reg.transition(exp1, "assigned")
    for i, well in enumerate(WELLS_24[:16]):
        reg.register_sample(f"S{i + 1:03d}", "rna",
                            {"tissue": "iPSC", "batch": 4})
        reg.assign_well(exp1, "P1", well, f"S{i + 1:03d}")
    reg.transition(exp1, "processed")
    reg.transition(exp1, "analyzed")
    for i in range(16):
        body = (f"Name\tLength\tTPM\nENST1\t100\t{1.5 + i * 0.01:.2f}\n"
                ).encode()
        reg.attach_result(exp1, f"quant.sf.S{i + 1:03d}", body)
    reg.transition(exp1, "locked")

    # Sign the lock transition, the e-signature path.
    lock_seq = reg.db.execute(
        "SELECT seq FROM audit_log WHERE entity_id = ? AND action = 'transition'"
        " ORDER BY seq DESC LIMIT 1", (exp1,)).fetchone()["seq"]
    sign(reg, lock_seq, signer="a.barlow", meaning="reviewed",
         key=b"fixture-key")
    reg.db.commit()

    # Experiment 2: in-flight protein quant, 8 samples across two plates.
    exp2 = reg.create_experiment(
        "EXP-PR-0017", "Protein panel lot 12",
        {"pipeline": "bradford", "lab": "stem-cell"})
    reg.transition(exp2, "queued")
    reg.transition(exp2, "assigned")
    for i, well in enumerate(WELLS_24[:8]):
        plate = "P1" if i < 4 else "P2"
        reg.register_sample(f"P{i + 1:03d}", "protein",
                            {"tissue": "supernatant", "batch": 12})
        reg.assign_well(exp2, plate, well, f"P{i + 1:03d}")
    reg.transition(exp2, "processed")

    # Experiment 3: registered only, no samples yet.
    reg.create_experiment(
        "EXP-RNA-0051", "iPSC batch 5 RNA-seq (planned)",
        {"pipeline": "salmon_hybrid", "genome": "GRCh38", "lab": "stem-cell"})

    return reg


CLEAN_POLLS = 6
POLL_GAP_S = 1.0


def build_capture_db(path: Path):
    """Poll the emulated instrument through CaptureService.

    The TEMP channel starts cold (22 C set against a 37 C setpoint), so
    the first few polls produce real temp-out-of-band alarms. A dropped
    link mid-run produces real transport-error rows, and the driver
    reconnects itself afterwards.
    """
    srv = ThreadedInstrumentServer("127.0.0.1", 0, seed=7)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        with InstrumentClient("127.0.0.1", port) as client:
            svc = CaptureService(client, str(path))
            for _ in range(CLEAN_POLLS):
                svc.poll_once()
                time.sleep(POLL_GAP_S)
            client.command("SIM:FAULT DROP")
            svc.poll_once()
            client.command("SIM:FAULT NONE")
            svc.poll_once()
            svc.stop()
    finally:
        srv.shutdown()
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def dump(table: str, cols: list[str], db=None) -> int:
    db = db or build_cache.db
    rows = [dict(r) for r in
            db.execute(f"SELECT {', '.join(cols)}"
                       f" FROM {table} ORDER BY 1")]
    path = SEEDS / f"raw_{table}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


class _Cache:
    db = None


build_cache = _Cache()


def main():
    SEEDS.mkdir(exist_ok=True)
    reg = build_registry()
    build_cache.db = reg.db

    counts = {
        "samples": dump("samples", ["sample_id", "kind", "meta", "created"]),
        "experiments": dump("experiments",
                            ["experiment_id", "name", "status", "meta",
                             "created"]),
        "plates": dump("plates",
                       ["experiment_id", "plate", "well", "sample_id"]),
        "results": dump("results",
                        ["result_id", "experiment_id", "name",
                         "content_sha256", "meta", "created"]),
        "audit_log": dump("audit_log",
                          ["seq", "ts", "entity", "entity_id", "action",
                           "detail", "prev_hash", "hash"]),
        "audit_signature": dump("audit_signature",
                                ["sig_id", "audit_seq", "signer", "meaning",
                                 "ts", "signature"]),
    }

    with tempfile.TemporaryDirectory() as td:
        cap_db = build_capture_db(Path(td) / "capture.db")
        counts["readings"] = dump(
            "readings", ["id", "ts", "channel", "value", "unit",
                         "quality"], db=cap_db)
        counts["alarms"] = dump(
            "alarms", ["id", "ts", "channel", "rule", "value"],
            db=cap_db)
        cap_db.close()

    print(counts)


if __name__ == "__main__":
    main()
