"""Demo: register a synthetic RNA-seq batch through the LIMS and emit
committed artifacts (registry summary + audit log CSV).

Run: python lims/demo_lims.py
"""

import json
from pathlib import Path

from registry import LimsError, Registry

RESULTS = Path(__file__).resolve().parent.parent / "results"


def main():
    reg = Registry(":memory:")

    exp = reg.create_experiment(
        "EXP-RNA-0042", "iPSC batch 4 RNA-seq",
        {"pipeline": "salmon_direct", "genome": "GRCh38"})
    reg.transition(exp, "queued")
    reg.transition(exp, "assigned")

    wells = [f"{r}{c:02d}" for r in "ABCD" for c in range(1, 5)]
    for i, well in enumerate(wells):
        reg.register_sample(f"S{i + 1:03d}", "rna",
                            {"tissue": "iPSC", "batch": 4})
        reg.assign_well(exp, "P1", well, f"S{i + 1:03d}")

    reg.transition(exp, "processed")
    reg.transition(exp, "analyzed")
    reg.attach_result(exp, "quant.sf.S001",
                      b"Name\tLength\tTPM\nENST1\t100\t1.5\n")
    reg.transition(exp, "locked")

    try:
        reg.assign_well(exp, "P1", "E01", "S017")
        refused = False
    except LimsError:
        refused = True

    chain = reg.verify_audit_chain()
    RESULTS.mkdir(exist_ok=True)

    import csv
    audit_rows = [dict(r) for r in reg.db.execute(
        "SELECT seq, ts, entity, entity_id, action, detail, hash"
        " FROM audit_log ORDER BY seq")]
    with open(RESULTS / "lims_audit_log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=audit_rows[0].keys())
        w.writeheader()
        w.writerows(audit_rows)

    summary = {
        "experiment": exp,
        "status": reg._status(exp),
        "n_samples": len(wells),
        "plate_wells_assigned": len(reg.plate_map(exp, "P1")),
        "results_attached": reg.db.execute(
            "SELECT COUNT(*) c FROM results").fetchone()["c"],
        "mutation_after_lock_refused": refused,
        "audit_chain": chain,
        "audit_rows": len(audit_rows),
    }
    (RESULTS / "lims_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
