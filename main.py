"""FastAPI app: health, REST state API, WebSocket live feed, dashboard static files.
Also boots the Engine on startup and stops it on shutdown."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import CFG
from app.engine import Engine
from app.state.store import Store

logging.basicConfig(
    level=getattr(logging, CFG.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("main")

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"

store: Store | None = None
engine: Engine | None = None
boot_error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, engine, boot_error
    store = Store(CFG.db_path)
    engine = Engine(store)
    try:
        await engine.start()
    except Exception as e:            # e.g. bad config — keep the dashboard up to show the error
        boot_error = str(e)
        log.exception("engine failed to start")
    yield
    if engine:
        await engine.stop()
    if store:
        await store.close()


app = FastAPI(title="Momentum Sniper", lifespan=lifespan)


# ── health / state ────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    ok = engine is not None and engine.status == "running"
    return {
        "status": "ok" if ok or boot_error else "starting",
        "bot": engine.status if engine else "booting",
        "mode": CFG.mode,
        "error": boot_error,
    }


@app.get("/api/state")
async def api_state():
    if engine is None:
        return JSONResponse({"error": boot_error or "starting"}, status_code=503)
    return await engine.snapshot()


@app.get("/api/events")
async def api_events(limit: int = 200):
    if store is None:
        return {"events": []}
    return {"events": await store.events(min(limit, 500))}


@app.get("/api/trades")
async def api_trades(limit: int = 100):
    if store is None:
        return {"closed": []}
    return {"closed": await store.closed_positions(min(limit, 300))}


# ── WebSocket live feed ───────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    if engine is None:
        await ws.close(code=1013)
        return
    await ws.accept()
    cid, queue = await engine.bc.connect()
    send_lock = asyncio.Lock()

    async def safe_send(line: str) -> None:
        async with send_lock:
            await ws.send_text(line)

    async def sender():
        # dedicated task that streams live events from the broadcaster queue
        while True:
            line = await queue.get()
            await safe_send(line)

    send_task = asyncio.create_task(sender())
    try:
        # full snapshot immediately, then every 5s; live events flow via the queue
        while True:
            snap_payload = await engine.snapshot()
            snap_payload["type"] = "snapshot"
            import json as _json
            await safe_send(_json.dumps(snap_payload, ensure_ascii=False, default=str))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        send_task.cancel()
        engine.bc.disconnect(cid)


# ── dashboard ─────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")


@app.get("/")
async def dashboard():
    return FileResponse(DASHBOARD_DIR / "index.html")
