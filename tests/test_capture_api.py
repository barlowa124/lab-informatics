"""Capture service and API tests."""
import pytest
from fastapi.testclient import TestClient

from lablink.api import create_app
from lablink.capture import AlarmRule, CaptureService
from lablink.driver import InstrumentClient
from lablink.simulator import serve


@pytest.fixture()
def device(tmp_path):
    srv = serve(port=0)
    host, port = srv.server_address
    client = InstrumentClient(host, port)
    client.connect()
    yield client, srv, tmp_path / "test.db"
    client.close()
    srv.shutdown()


def test_poll_writes_typed_rows(device):
    client, srv, db = device
    svc = CaptureService(client, str(db))
    rows = svc.poll_once()
    assert len(rows) == 5
    assert all(r.quality == "ok" for r in rows)
    latest = svc.latest()
    assert {r["channel"] for r in latest} == {"TEMP", "PH", "DO", "AGIT", "WEIGHT"}
    svc.stop()


def test_transport_fault_still_writes_error_rows(device):
    client, srv, db = device
    svc = CaptureService(client, str(db))
    srv.device.fault = "DROP"
    rows = svc.poll_once()
    assert all(r.quality == "transport-error" for r in rows)
    assert svc.stats["transport_error"] == 5
    svc.stop()


def test_alarm_rule_fires_and_persists(device):
    client, srv, db = device
    svc = CaptureService(client, str(db),
                         rules=[AlarmRule("TEMP", 40.0, 41.0, "temp-too-low")])
    svc.poll_once()
    al = svc.alarms()
    assert al and al[0]["rule"] == "temp-too-low"
    svc.stop()


def test_api_endpoints(device):
    client, srv, db = device
    app = create_app(client, str(db))
    with TestClient(app) as tc:
        assert tc.get("/api/instrument").json()["connected"] is True
        assert "TEMP" in tc.get("/api/channels").json()
        svc_rows = tc.get("/api/latest").json()
        assert len(svc_rows) == 5
        hist = tc.get("/api/history/TEMP").json()
        assert hist and hist[0]["value"] == pytest.approx(hist[0]["value"])
        r = tc.post("/api/setpoint/PH", params={"value": 7.4})
        assert r.json()["ok"] is True
        assert tc.get("/api/history/NOPE").status_code == 404


def test_nan_rows_do_not_poison_latest(device):
    client, srv, db = device
    svc = CaptureService(client, str(db))
    svc.poll_once()
    srv.device.fault = "DROP"
    svc.poll_once()
    latest = {r["channel"]: r for r in svc.latest()}
    assert latest["TEMP"]["quality"] == "transport-error"
    assert latest["TEMP"]["value"] is None
    svc.stop()
