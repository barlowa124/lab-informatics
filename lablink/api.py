"""FastAPI surface over the capture service plus a minimal live dashboard."""
from __future__ import annotations

from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .capture import CaptureService
from .driver import InstrumentClient, InstrumentError, TransportError
from .protocol import CHANNELS

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


def create_app(client: InstrumentClient, db_path: str) -> FastAPI:
    svc = CaptureService(client, db_path)

    @asynccontextmanager
    async def lifespan(app):
        svc.start()
        yield
        svc.stop()

    app = FastAPI(title="lablink", description="Instrument capture gateway",
                  lifespan=lifespan)
    app.state.capture = svc

    @app.get("/")
    def dashboard():
        if DASHBOARD.exists():
            return FileResponse(DASHBOARD)
        return {"detail": "dashboard file missing", "api": "/docs"}

    @app.get("/api/instrument")
    def instrument():
        try:
            return {"idn": client.identify(), "status": client.status(),
                    "error_register": client.error_register(),
                    "connected": client.connected}
        except TransportError as e:
            return {"connected": False, "error": str(e)}

    @app.get("/api/channels")
    def channels():
        return {k: v for k, v in CHANNELS.items()}

    @app.get("/api/latest")
    def latest():
        return svc.latest()

    @app.get("/api/history/{channel}")
    def history(channel: str, limit: int = 200):
        if channel.upper() not in CHANNELS:
            raise HTTPException(404, f"unknown channel {channel}")
        if not 1 <= limit <= 2000:
            raise HTTPException(422, "limit must be 1-2000")
        return svc.history(channel.upper(), limit)

    @app.get("/api/alarms")
    def alarms(limit: int = 50):
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be 1-500")
        return svc.alarms(limit)

    @app.get("/api/stats")
    def stats():
        return svc.stats

    @app.post("/api/setpoint/{channel}")
    def setpoint(channel: str, value: float):
        channel = channel.upper()
        if channel not in CHANNELS:
            raise HTTPException(404, f"unknown channel {channel}")
        try:
            client.set_setpoint(channel, value)
        except InstrumentError as e:
            raise HTTPException(400, str(e)) from e
        except TransportError as e:
            raise HTTPException(502, str(e)) from e
        return {"ok": True, "channel": channel, "setpoint": value}

    return app
