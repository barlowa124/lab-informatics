"""E-signature mechanics over the hash-chained audit log.

Each signature is HMAC-SHA256 over
``audit_seq | row_hash | signer | meaning | ts``, stored in
``audit_signature``. The signature binds the signed audit row's own
hash, so editing history breaks the chain *and* invalidates the
signature. Signatures over a row that does not exist are refused.

Scope, stated plainly: HMAC is a symmetric scheme. With a shared key it
proves a signature was produced by a holder of the key bound to that
content — that is the mechanical core of an e-signature workflow, not
public-key identity or non-repudiation. This prototype does not claim
21 CFR Part 11 conformance.

Key source: ``LIMS_SIGNING_KEY`` env var or an explicit key argument.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

try:
    from .registry import LimsError
except ImportError:                    # flat-path use (python lims/...)
    from registry import LimsError

MEANINGS = {"authored", "reviewed", "approved"}


def _key(key: str | bytes | None) -> bytes:
    k = key if key is not None else os.environ.get("LIMS_SIGNING_KEY")
    if not k:
        raise LimsError(
            "no signing key: set LIMS_SIGNING_KEY or pass key=")
    return k if isinstance(k, bytes) else k.encode()


def _mac(key: bytes, audit_seq: int, row_hash: str, signer: str,
         meaning: str, ts: float) -> str:
    payload = f"{audit_seq}|{row_hash}|{signer}|{meaning}|{ts}"
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def sign(reg, audit_seq: int, signer: str, meaning: str,
         key: str | bytes | None = None) -> str:
    """Sign an existing audit row; returns the signature hex."""
    if meaning not in MEANINGS:
        raise LimsError(f"meaning must be one of {sorted(MEANINGS)}")
    row = reg.db.execute(
        "SELECT hash FROM audit_log WHERE seq=?", (audit_seq,)
    ).fetchone()
    if not row:
        raise LimsError(f"no audit row seq={audit_seq}")
    ts = time.time()
    k = _key(key)
    sig = _mac(k, audit_seq, row["hash"], signer, meaning, ts)
    reg.db.execute(
        "INSERT INTO audit_signature (audit_seq, signer, meaning, ts,"
        " signature) VALUES (?,?,?,?,?)",
        (audit_seq, signer, meaning, ts, sig))
    return sig


def verify_signatures(reg, key: str | bytes | None = None) -> dict:
    """Recompute every stored signature against its audit row's current
    hash, and check the audit chain itself. A signature binds the row's
    hash field — field-level tampering that leaves `hash` untouched is
    caught by the chain check, so both are verified together."""
    k = _key(key)
    chain = reg.verify_audit_chain()
    if not chain["ok"]:
        return {"ok": False, "chain": chain,
                "n_signatures": None, "bad": []}
    rows = reg.db.execute(
        "SELECT s.sig_id, s.audit_seq, s.signer, s.meaning, s.ts,"
        " s.signature, a.hash AS row_hash"
        " FROM audit_signature s LEFT JOIN audit_log a"
        " ON a.seq = s.audit_seq").fetchall()
    bad = []
    for r in rows:
        if r["row_hash"] is None:
            bad.append({"sig_id": r["sig_id"], "why": "row deleted"})
            continue
        if not hmac.compare_digest(
                r["signature"],
                _mac(k, r["audit_seq"], r["row_hash"], r["signer"],
                     r["meaning"], r["ts"])):
            bad.append({"sig_id": r["sig_id"],
                        "why": "signature mismatch"})
    return {"ok": not bad, "chain_ok": True,
            "n_signatures": len(rows), "bad": bad}


def unsigned_rows(reg) -> list[int]:
    """Audit seqs with no signature — the 'unsigned work' report."""
    return [r["seq"] for r in reg.db.execute(
        "SELECT seq FROM audit_log WHERE seq NOT IN"
        " (SELECT audit_seq FROM audit_signature) ORDER BY seq")]
