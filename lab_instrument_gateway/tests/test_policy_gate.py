"""Policy gate: setpoint writes are allow/flag/block'ed and every
verdict lands in a hash-chained decisions log."""
import json

import pytest
from fastapi.testclient import TestClient

from lablink.api import create_app
from lablink.driver import InstrumentClient
from lablink.policy import (PolicyLog, check_log, evaluate, load_policy)
from lablink.simulator import serve


@pytest.fixture()
def device(tmp_path):
    srv = serve(port=0)
    host, port = srv.server_address
    client = InstrumentClient(host, port)
    client.connect()
    yield client, srv, tmp_path / "test.db", tmp_path / "policy.jsonl"
    client.close()
    srv.shutdown()


AUTH = {"Authorization": "Bearer test-token"}
POL = {
    "defaults": {"action": "allow"},
    "rules": [
        {"id": "temp-hard", "channel": "TEMP", "above": 42.0,
         "action": "block", "severity": "high", "reason": "too hot"},
        {"id": "temp-soft", "channel": "TEMP", "above": 38.0,
         "action": "flag", "severity": "medium", "reason": "warm"},
        {"id": "do-blocklist", "channels": ["WEIGHT"],
         "action": "block", "severity": "high", "reason": "not settable"},
    ],
}


def _app(client, db, log):
    return create_app(client, str(db), api_token="test-token",
                      policy=POL, policy_log=str(log))


# --- rule engine ---

def test_evaluate_allow_flag_block():
    pol = load_policy(POL)
    assert evaluate(pol, "TEMP", 37.0).action == "allow"
    assert evaluate(pol, "TEMP", 39.0).action == "flag"
    assert evaluate(pol, "TEMP", 43.0).action == "block"
    # blocklist: any write to WEIGHT regardless of value
    assert evaluate(pol, "WEIGHT", 0.0).action == "block"
    # rule precedence: a blocked channel stays blocked above soft bound
    assert evaluate(pol, "TEMP", 50.0).rule == "temp-hard"


def test_policy_validation():
    with pytest.raises(ValueError):
        load_policy({"rules": [{"channel": "TEMP"}]})
    with pytest.raises(ValueError):
        load_policy({"defaults": {"action": "block"}, "rules": []})


# --- API path ---

def test_allow_writes_and_logs(device):
    client, srv, db, log = device
    with TestClient(_app(client, db, log)) as tc:
        r = tc.post("/api/setpoint/TEMP", params={"value": 36.5},
                    headers=AUTH)
        assert r.status_code == 200
        assert r.json()["policy"]["action"] == "allow"
        assert srv.device.setpoints["TEMP"] == pytest.approx(36.5)
    decisions = [json.loads(l) for l in open(log)]
    assert len(decisions) == 1
    assert decisions[0]["action"] == "allow"
    assert decisions[0]["chain_prev"] == "genesis"
    assert check_log(str(log)) == []


def test_flag_writes_but_marks(device):
    client, srv, db, log = device
    with TestClient(_app(client, db, log)) as tc:
        r = tc.post("/api/setpoint/TEMP", params={"value": 39.5},
                    headers=AUTH)
        assert r.status_code == 200
        assert r.json()["policy"]["action"] == "flag"
        assert r.json()["policy"]["rule"] == "temp-soft"
        assert srv.device.setpoints["TEMP"] == pytest.approx(39.5)
    d = json.loads(open(log).read().strip().splitlines()[-1])
    assert d["action"] == "flag" and d["rule_id"] == "temp-soft"


def test_block_refuses_write_and_logs(device):
    client, srv, db, log = device
    before = dict(srv.device.setpoints)
    with TestClient(_app(client, db, log)) as tc:
        r = tc.post("/api/setpoint/TEMP", params={"value": 44.0},
                    headers=AUTH)
        assert r.status_code == 403
        assert "policy block" in str(r.json())
        # also block an unknown-list channel write attempt
        r2 = tc.post("/api/setpoint/WEIGHT", params={"value": 10.0},
                     headers=AUTH)
        assert r2.status_code == 403
    assert srv.device.setpoints == before  # nothing reached the instrument
    decisions = [json.loads(l) for l in open(log)]
    assert len(decisions) == 2
    assert all(d["action"] == "block" for d in decisions)
    assert decisions[1]["chain_prev"] == decisions[0]["decision_id"]
    assert check_log(str(log)) == []


def test_decisions_endpoint_exposes_log(device):
    client, srv, db, log = device
    with TestClient(_app(client, db, log)) as tc:
        tc.post("/api/setpoint/TEMP", params={"value": 36.5},
                headers=AUTH)
        r = tc.get("/api/policy/decisions")
        assert r.status_code == 200
        body = r.json()
        assert len(body["decisions"]) == 1
        assert body["chain_problems"] == []


def test_decisions_pin_the_policy_that_made_them(device):
    from lablink.policy import policy_sha256
    client, srv, db, log = device
    with TestClient(_app(client, db, log)) as tc:
        tc.post("/api/setpoint/TEMP", params={"value": 36.5},
                headers=AUTH)
        r = tc.get("/api/policy/decisions")
        body = r.json()
        assert body["policy_sha256"] == policy_sha256(load_policy(POL))
        d = body["decisions"][0]
        assert d["policy_sha256"] == body["policy_sha256"]
    # a different policy produces a different sha — the pin is contentful
    pol2 = dict(POL, rules=POL["rules"][:1])
    assert policy_sha256(load_policy(pol2)) != policy_sha256(
        load_policy(POL))


def test_log_tamper_detected(device):
    client, srv, db, log = device
    with TestClient(_app(client, db, log)) as tc:
        tc.post("/api/setpoint/TEMP", params={"value": 36.5},
                headers=AUTH)
        tc.post("/api/setpoint/TEMP", params={"value": 44.0},
                headers=AUTH)
        tc.post("/api/setpoint/TEMP", params={"value": 36.8},
                headers=AUTH)
    lines = open(log).read().strip().splitlines()
    d0 = json.loads(lines[0])
    d0["value"] = 999.0                     # tamper a recorded verdict
    lines[0] = json.dumps(d0)
    del lines[1]                            # erase the blocked decision
    open(log, "w").write("\n".join(lines) + "\n")
    problems = check_log(str(log))
    assert any("tampered" in p for p in problems)
    assert any("chain break" in p for p in problems)


def test_default_policy_file_loads():
    from lablink.policy import DEFAULT_POLICY
    pol = load_policy(DEFAULT_POLICY)
    # sanity: culture-range setpoints all pass the bundled policy
    for ch, v in (("TEMP", 37.0), ("PH", 7.2), ("DO", 60.0),
                  ("AGIT", 300.0)):
        assert evaluate(pol, ch, v).action == "allow"
    # and obvious hazards are caught
    assert evaluate(pol, "TEMP", 44.0).action == "block"
    assert evaluate(pol, "AGIT", 900.0).action == "flag"
