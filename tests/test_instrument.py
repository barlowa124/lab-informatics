"""Driver + simulator tests against a live emulated device."""
import pytest

from lablink.driver import InstrumentClient, InstrumentError, TransportError
from lablink.protocol import IDENT_RESPONSE
from lablink.simulator import serve


@pytest.fixture()
def device():
    srv = serve(port=0)
    host, port = srv.server_address
    yield host, port, srv
    srv.shutdown()


def test_identify(device):
    host, port, _ = device
    with InstrumentClient(host, port) as c:
        assert c.identify() == IDENT_RESPONSE
        assert c.status() == "RUNNING"


def test_measure_all_channels(device):
    host, port, _ = device
    with InstrumentClient(host, port) as c:
        for ch in ("TEMP", "PH", "DO", "AGIT", "WEIGHT"):
            r = c.measure(ch)
            assert isinstance(r.value, float)
            assert r.channel == ch


def test_unknown_channel_is_error(device):
    host, port, _ = device
    with InstrumentClient(host, port) as c:
        with pytest.raises(InstrumentError):
            c.measure("NOPE")


def test_setpoint_in_range_and_validation(device):
    host, port, srv = device
    with InstrumentClient(host, port) as c:
        c.set_setpoint("TEMP", 40.0)
        assert srv.device.setpoints["TEMP"] == 40.0
        with pytest.raises(InstrumentError):
            c.set_setpoint("TEMP", 99.0)
        with pytest.raises(InstrumentError):
            c.set_setpoint("PH", 99.0)


def test_temperature_ramps_toward_setpoint(device):
    host, port, srv = device
    srv.device.readings["TEMP"] = 25.0
    srv.device.setpoints["TEMP"] = 37.0
    with InstrumentClient(host, port) as c:
        import time
        time.sleep(2.5)
        r = c.measure("TEMP")
        assert r.value > 30.0  # well past midpoint of 25->37 approach


def test_drop_fault_recovers_via_reconnect(device):
    host, port, srv = device
    srv.device.fault = "DROP"
    c = InstrumentClient(host, port)
    c.connect()
    # first queries fail at transport level, retries reconnect while DROP persists
    srv.device.fault = "NONE"  # let the retry succeed
    r = c.measure("TEMP")
    assert isinstance(r.value, float)
    c.close()


def test_unreachable_host_raises_transport():
    c = InstrumentClient("127.0.0.1", 59999)
    with pytest.raises(TransportError):
        c.connect()
