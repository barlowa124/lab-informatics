"""Policy gate for instrument writes, vendored thin from trust-tools'
agent_monitor policy engine.

Setpoint writes are the autonomy boundary: an agent (or a dashboard
user) proposes a value, the gate decides allow | flag | block, and every
decision — including blocked ones — is appended to a hash-chained JSONL
log so the write surface is auditable after the fact.

Policy JSON:
  {"defaults": {"action": "allow"},
   "rules": [{"id": "temp-hard", "channel": "TEMP", "above": 42.0,
              "action": "block", "severity": "high", "reason": "..."}]}

A rule matches a write when the channel matches and `above`/`below` is
violated; a rule with no bound and a matching channel matches
unconditionally (a blocklist). First block wins; flags collect.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ACTIONS = ("allow", "flag", "block")


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


@dataclass
class Verdict:
    action: str           # allow | flag | block
    rule: str | None
    severity: str
    reason: str


def load_policy(path_or_dict) -> dict:
    pol = (json.loads(Path(path_or_dict).read_text())
           if isinstance(path_or_dict, (str, Path))
           else dict(path_or_dict))
    for i, r in enumerate(pol.get("rules", [])):
        if "id" not in r or "action" not in r:
            raise ValueError(f"rule[{i}] needs id and action")
        if r["action"] not in ("flag", "block"):
            raise ValueError(f"rule[{i}] bad action {r['action']!r}")
    if pol.get("defaults", {}).get("action", "allow") != "allow":
        raise ValueError("default action must be allow — writes default "
                         "deny is a different gate, not a policy")
    return pol


def evaluate(pol: dict, channel: str, value: float) -> Verdict:
    """First matching block wins; else first flag; else allow."""
    flagged: Verdict | None = None
    for r in pol.get("rules", []):
        chans = r.get("channels") or ([r["channel"]] if "channel" in r
                                      else None)
        if chans is not None and channel not in chans:
            continue
        hit = ("above" in r and value > r["above"]) or \
              ("below" in r and value < r["below"]) or \
              ("above" not in r and "below" not in r)
        if not hit:
            continue
        v = Verdict(r["action"], r["id"], r.get("severity", "low"),
                    r.get("reason", r["id"]))
        if v.action == "block":
            return v
        if flagged is None:
            flagged = v
    return flagged or Verdict("allow", None, "none", "default")


class PolicyLog:
    """Append-only hash-chained decision log."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = "genesis"
        if self.path.exists() and self.path.stat().st_size:
            self._prev = json.loads(self.path.read_text()
                                    .strip().splitlines()[-1]
                                    )["decision_id"]

    def record(self, verdict: Verdict, channel: str, value: float,
               origin: str | None = None) -> dict:
        body = {
            "v": SCHEMA_VERSION,
            "kind": "policy_decision",
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "op": "setpoint_write",
            "channel": channel,
            "value": value,
            "action": verdict.action,
            "rule_id": verdict.rule,
            "severity": verdict.severity,
            "reason": verdict.reason,
            "origin": origin,
            "chain_prev": self._prev,
        }
        did = "dec-" + hashlib.sha256(_canon(body)).hexdigest()[:16]
        body["decision_id"] = did
        self._prev = did
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
        return body


def _dec_hash(d: dict) -> str:
    body = {k: v for k, v in d.items() if k != "decision_id"}
    return "dec-" + hashlib.sha256(_canon(body)).hexdigest()[:16]


def check_log(path: str) -> list[str]:
    problems = []
    prev = "genesis"
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            d = json.loads(line)
            if _dec_hash(d) != d.get("decision_id"):
                problems.append(f"[{i}] {d.get('decision_id')}: body "
                                "tampered")
            if d.get("chain_prev") != prev:
                problems.append(f"[{i}] {d.get('decision_id')}: chain "
                                "break")
            prev = d.get("decision_id", "?")
    return problems


DEFAULT_POLICY = Path(__file__).resolve().parent / "policy_default.json"
