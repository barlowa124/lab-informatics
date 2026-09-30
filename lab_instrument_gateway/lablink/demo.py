"""End-to-end demo: emulator + driver + capture + API in one process."""
from __future__ import annotations

import os
import secrets

import uvicorn

from .api import API_TOKEN_ENV, create_app
from .driver import InstrumentClient
from .simulator import serve


def main(db_path: str = "lablink.db", host: str = "127.0.0.1",
         port: int = 5025, api_port: int = 8000,
         api_host: str = "127.0.0.1"):
    sim = serve(host, port)
    print(f"emulated instrument on {host}:{port}")
    client = InstrumentClient(host, port)
    client.connect()
    print("idn:", client.identify())
    token = os.environ.get(API_TOKEN_ENV) or secrets.token_urlsafe(16)
    print(f"setpoint bearer token: {token}")
    app = create_app(client, db_path, api_token=token)
    uvicorn.run(app, host=api_host, port=api_port, log_level="warning")


if __name__ == "__main__":
    # Loopback defaults; containers set LABLINK_API_HOST=0.0.0.0.
    main(
        db_path=os.environ.get("LABLINK_DB", "lablink.db"),
        host=os.environ.get("LABLINK_SIM_HOST", "127.0.0.1"),
        port=int(os.environ.get("LABLINK_SIM_PORT", "5025")),
        api_port=int(os.environ.get("LABLINK_API_PORT", "8000")),
        api_host=os.environ.get("LABLINK_API_HOST", "127.0.0.1"),
    )
