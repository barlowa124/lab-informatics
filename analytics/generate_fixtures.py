"""Generate the dbt seed CSVs by driving the real LIMS registry.

The fixtures are synthetic, but every row is produced by the same code
path the LIMS uses for live records: samples are registered, wells are
assigned, results are attached, and the audit log is written by the
registry itself. The seeds therefore carry the same schema, status
transitions, and hash-chained audit trail as a real run.

Run from the repo root:

    python analytics/generate_fixtures.py
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "labStackDev" / "lims"))
sys.path.insert(0, str(ROOT / "labStackDev"))

from registry import Registry  # noqa: E402
from esign import sign  # noqa: E402

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


def dump(table: str, cols: list[str]) -> int:
    rows = [dict(r) for r in
            build_cache.db.execute(f"SELECT {', '.join(cols)}"
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
    print(counts)


if __name__ == "__main__":
    main()
