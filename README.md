# lablink - instrument gateway

Software that talks to a lab instrument, captures its readings, and serves them over an API.

No hardware is required: the device is an emulator (`lablink/simulator.py`) that speaks an
ASCII, SCPI-flavored command set over TCP. The driver code path is the same one a physical
RS-232 or TCP instrument would use: open a socket, send newline-terminated commands, parse
one-line responses, poll the error register, reconnect when the link dies. Swapping the
emulator for a real instrument means changing the transport, not the driver.

## layout

- `lablink/simulator.py` - emulated benchtop bioreactor. Temperature and agitation ramp to
  setpoints, pH drifts, dissolved oxygen responds to agitation, weight drains. Fault modes
  (`SIM:FAULT STUCK|NOISY|DROP`) exist so tests can exercise driver failure handling.
- `lablink/driver.py` - `InstrumentClient`: connect/reconnect, `query`/`command`,
  `MEAS:<ch>?` readings, `CONF:<ch> <value>` setpoints, `SYST:ERR?` error register.
  One transaction at a time on the shared socket so the capture loop and API calls
  cannot interleave frames.
- `lablink/capture.py` - polling service. Each channel is read on an interval, validated
  into a typed `ReadingRow`, persisted to SQLite, and checked against alarm rules.
  Transport and device errors are stored as rows too. A silent gap in instrument data is
  worse than an honest error row.
- `lablink/api.py` - FastAPI: `/api/instrument`, `/api/latest`, `/api/history/{ch}`,
  `/api/alarms`, `/api/setpoint/{ch}`, plus a small live dashboard at `/`.
- `dashboard/index.html` - dependency-free status page.

## run it

```bash
pip install -e .
python -m lablink.demo          # emulator on :5025, API+dashboard on :8000
# open http://127.0.0.1:8000
```

Inject a fault while it runs:

```bash
printf 'SIM:FAULT DROP\n' | nc 127.0.0.1 5025   # watch quality rows turn transport-error
printf 'SIM:FAULT NONE\n' | nc 127.0.0.1 5025   # driver reconnects on its own
```

## protocol

| command | response | meaning |
|---|---|---|
| `*IDN?` | `LABLINK,THRIVE-1000,BIOREACTOR,1.4.2` | identity |
| `MEAS:TEMP?` | `36.982` | measure a channel (TEMP, PH, DO, AGIT, WEIGHT) |
| `CONF:TEMP 37.5` | `OK` | move a setpoint |
| `SYST:ERR?` | `0,"No error"` | pop the error register |
| `STAT?` | `RUNNING` | run state |
| `RUN` / `STOP` | `OK` | start/stop the process |
| `SIM:FAULT <mode>` | `OK` | test-only fault injection |

Errors are returned as `-<code>,"<message>"` and surface as `InstrumentError`.

## tests

```bash
pip install -e .[dev]
python -m pytest tests/
```

15 tests cover protocol round-trips, setpoint validation, measurement drift, link-drop
reconnect, negative-value parsing, concurrent transaction safety, error-register reads, error-row persistence,
alarm firing, and the API surface.

## honest scope

This is instrument software development without the instrument. It demonstrates the
parts that carry over to real hardware - wire protocols, timeouts, reconnects, error
registers, typed capture, alarms, provenance - and not the parts that do not, like
electrical noise, connector quirks, or vendor SDK licensing. The emulator's process
model is a first-order approximation, not a validated bioreactor model.
