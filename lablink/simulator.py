"""Emulated benchtop bioreactor speaking the lablink wire protocol over TCP.

The process model is intentionally simple but physical: temperature and
agitation ramp toward their setpoints, pH drifts, dissolved oxygen responds
to agitation, and weight drains slowly. Fault modes (STUCK, NOISY, DROP)
let tests exercise driver-side failure handling without hardware.
"""
from __future__ import annotations

import random
import socket
import socketserver
import threading
import time

from .protocol import CHANNELS, IDENT_RESPONSE, SETTABLE

FAULTS = {"NONE", "STUCK", "NOISY", "DROP"}


class _DeviceState:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        self.fault = "NONE"
        self.error = '0,"No error"'
        self.running = True
        self.setpoints = {"TEMP": 37.0, "PH": 7.2, "DO": 60.0, "AGIT": 400.0}
        self.readings = {
            "TEMP": 22.0,
            "PH": 7.0,
            "DO": 95.0,
            "AGIT": 0.0,
            "WEIGHT": 1000.0,
        }
        self._last = time.monotonic()

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last, 5.0)
        self._last = now
        r = self.readings
        s = self.setpoints
        if not self.running:
            return
        # first-order approach to setpoints plus measurement noise
        r["TEMP"] += (s["TEMP"] - r["TEMP"]) * min(1.0, dt * 0.5)
        r["AGIT"] += (s["AGIT"] - r["AGIT"]) * min(1.0, dt * 2.0)
        r["PH"] += (s["PH"] - r["PH"]) * min(1.0, dt * 0.05) - self._rng.uniform(0, 0.002 * dt)
        r["DO"] += (min(100.0, 40.0 + r["AGIT"] / 15.0) - r["DO"]) * min(1.0, dt * 0.4)
        r["WEIGHT"] -= self._rng.uniform(0.0, 0.05) * dt
        for ch, meta in CHANNELS.items():
            r[ch] = max(meta["lo"], min(meta["hi"], r[ch]))

    def measure(self, channel: str) -> str:
        self._tick()
        if self.fault == "DROP":
            raise ConnectionAbortedError("link dropped")
        v = self.readings[channel]
        if self.fault == "STUCK":
            v = round(v)
        noise = self._rng.gauss(0.0, 0.02 if self.fault != "NOISY" else 0.8)
        return f"{v + noise:.3f}"

    def handle(self, line: str) -> str:
        line = line.strip().upper()
        if not line:
            return ""
        try:
            if line == "*IDN?":
                return IDENT_RESPONSE
            if line == "SYST:ERR?":
                err = self.error
                self.error = '0,"No error"'
                return err
            if line == "STAT?":
                return "RUNNING" if self.running else "IDLE"
            if line.startswith("MEAS:") and line.endswith("?"):
                ch = line[5:-1]
                if ch not in CHANNELS:
                    return '-100,"Unknown channel"'
                return self.measure(ch)
            if line.startswith("CONF:"):
                body = line[5:]
                ch, _, val = body.partition(" ")
                if ch not in SETTABLE:
                    return '-101,"Channel not settable"'
                try:
                    fval = float(val)
                except ValueError:
                    return '-102,"Bad value"'
                meta = CHANNELS[ch]
                if not (meta["lo"] <= fval <= meta["hi"]):
                    return '-103,"Setpoint out of range"'
                self.setpoints[ch] = fval
                return "OK"
            if line == "RUN":
                self.running = True
                return "OK"
            if line == "STOP":
                self.running = False
                return "OK"
            if line.startswith("SIM:FAULT "):
                mode = line.split()[-1]
                if mode in FAULTS:
                    self.fault = mode
                    if mode != "NONE":
                        self.error = f'-301,"Simulated fault {mode}"'
                    return "OK"
                return '-104,"Unknown fault mode"'
            return '-105,"Unknown command"'
        except ConnectionAbortedError:
            raise
        except Exception:
            return '-199,"Internal error"'


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        dev: _DeviceState = self.server.device  # type: ignore[attr-defined]
        while True:
            try:
                raw = self.rfile.readline()
            except (ConnectionResetError, BrokenPipeError):
                return
            if not raw:
                return
            try:
                resp = dev.handle(raw.decode("ascii", errors="replace"))
            except ConnectionAbortedError:
                return
            if resp:
                try:
                    self.wfile.write(resp.encode("ascii") + b"\n")
                    self.wfile.flush()
                except (ConnectionResetError, BrokenPipeError):
                    return


class ThreadedInstrumentServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int, seed: int | None = None):
        self.device = _DeviceState(seed=seed)
        super().__init__((host, port), _Handler)


IDLE_SLEEP_S = 3600


def serve(host: str = "127.0.0.1", port: int = 5025) -> ThreadedInstrumentServer:
    srv = ThreadedInstrumentServer(host, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    s = serve()
    print(f"emulated bioreactor listening on {s.server_address}")
    try:
        while True:
            # Idle until interrupted. The server threads handle requests.
            time.sleep(IDLE_SLEEP_S)
    except KeyboardInterrupt:
        s.shutdown()
