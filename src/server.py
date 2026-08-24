"""
AI Security Monitor - Real-Time Interactive Web Server & WebSocket Hub
Provides live streaming of threat intel, AI launches, CVEs, and interactive controls.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Set
import sys

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root and src to path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / 'src'))

from monitor import AISecurityMonitor

logger = logging.getLogger("server")

app = FastAPI(
    title="AI Security Monitor - Cyber Intel Radar",
    description="Real-time Interactive Intelligence & AI Threat Radar",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Monitor instance
monitor = AISecurityMonitor(str(ROOT_DIR / "config" / "sources.yaml"))


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts live updates."""
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                dead_connections.add(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)


ws_manager = ConnectionManager()
is_fetching = False
scan_loop_running = False


# Background fetch helper that streams entries over WebSockets
def sync_on_entry_callback(entry: dict):
    """Callback triggered from monitor thread whenever a new entry is saved."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    msg = {
        "type": "new_entry",
        "timestamp": datetime.now().isoformat(),
        "data": entry
    }

    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(msg), loop)
    else:
        asyncio.run(ws_manager.broadcast(msg))


async def run_fetch_pipeline(ignore_rate_limit: bool = True):
    """Runs fetch and broadcasts status and entries."""
    global is_fetching
    if is_fetching:
        return {"status": "already_running"}

    is_fetching = True
    await ws_manager.broadcast({
        "type": "scan_status",
        "status": "started",
        "timestamp": datetime.now().isoformat(),
        "message": "Initiating intelligence sweep across all configured sources..."
    })

    loop = asyncio.get_running_loop()

    def _do_fetch():
        def _cb(entry):
            # Send live entry directly to WS
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast({
                    "type": "new_entry",
                    "timestamp": datetime.now().isoformat(),
                    "data": entry
                }),
                loop
            )

        return monitor.fetch_all(on_entry_found=_cb, ignore_rate_limit=ignore_rate_limit)

    try:
        results = await loop.run_in_executor(None, _do_fetch)
        stats = monitor.get_stats()
        await ws_manager.broadcast({
            "type": "scan_status",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "results": results,
            "stats": stats,
            "message": f"Scan completed: {results.get('total_new', 0)} new intelligence items indexed."
        })
        return results
    except Exception as e:
        logger.error(f"Error during scan: {e}")
        await ws_manager.broadcast({
            "type": "scan_status",
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        })
        return {"error": str(e)}
    finally:
        is_fetching = False


# Periodic background intelligence sweep
async def background_radar_loop():
    """Periodic task polling intelligence sources automatically."""
    await asyncio.sleep(5)
    while True:
        try:
            logger.info("Running scheduled background intelligence sweep...")
            await run_fetch_pipeline(ignore_rate_limit=False)
        except Exception as e:
            logger.error(f"Background scanner error: {e}")
        # Run every 5 minutes (respects source rate limits)
        await asyncio.sleep(300)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_radar_loop())


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial stats and connection handshake
        stats = monitor.get_stats()
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "message": "Connected to AI Security Real-Time Radar"
        })
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
                elif msg.get("action") == "trigger_scan":
                    asyncio.create_task(run_fetch_pipeline(ignore_rate_limit=True))
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# REST API endpoints
@app.get("/api/stats")
async def api_stats():
    """Return database and scanner statistics."""
    stats = monitor.get_stats()
    # Check telegram configuration state
    telegram_cfg = monitor.config.get("delivery", {}).get("telegram", {})
    stats["telegram_configured"] = bool(telegram_cfg.get("bot_token") and telegram_cfg.get("chat_id"))
    stats["is_fetching"] = is_fetching
    return stats


@app.get("/api/entries")
async def api_entries(
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    hours: Optional[int] = None,
    pre_cve: Optional[bool] = Query(False),
    high_velocity: Optional[bool] = Query(False)
):
    """Query intelligence entries with filtering, search, and pagination."""
    since = None
    if hours:
        since = datetime.now() - timedelta(hours=hours)

    all_entries = monitor.db.get_entries(
        since=since,
        category=category,
        limit=limit,
        offset=offset,
        pre_cve_only=pre_cve or False,
        high_velocity_only=high_velocity or False
    )

    if search:
        s = search.lower()
        all_entries = [
            e for e in all_entries
            if s in e.get('title', '').lower()
            or s in (e.get('summary') or '').lower()
            or s in e.get('source_name', '').lower()
            or s in (e.get('attack_vector') or '').lower()
            or s in (e.get('attack_archetype') or '').lower()
            or any(s in str(t).lower() for t in e.get('tags', []))
            or any(s in str(t).lower() for t in e.get('affected_ecosystem', []))
        ]

    return {
        "entries": all_entries,
        "count": len(all_entries),
        "limit": limit,
        "offset": offset
    }


@app.get("/api/sources")
async def api_sources(all_sources: bool = True):
    """List configured and database sources."""
    sources = monitor.db.get_sources(enabled_only=not all_sources)
    return {"sources": sources}


class SourceToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/sources/{source_id}/toggle")
async def api_toggle_source(source_id: int, req: SourceToggleRequest):
    """Enable or disable an intelligence source."""
    with monitor.db.transaction() as conn:
        conn.execute("UPDATE sources SET enabled = ? WHERE id = ?", (1 if req.enabled else 0, source_id))
    return {"status": "success", "source_id": source_id, "enabled": req.enabled}


@app.post("/api/fetch")
async def api_trigger_fetch(background_tasks: BackgroundTasks, force: bool = True):
    """Trigger an on-demand intelligence scan."""
    global is_fetching
    if is_fetching:
        return JSONResponse(status_code=409, content={"status": "already_running", "message": "A scan is already in progress."})

    background_tasks.add_task(run_fetch_pipeline, force)
    return {"status": "initiated", "message": "Live intelligence scan triggered."}


class TelegramDigestRequest(BaseModel):
    schedule: str = "daily"
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


@app.post("/api/telegram/digest")
async def api_send_telegram_digest(req: TelegramDigestRequest):
    """Send digest to Telegram on demand."""
    custom_cfg = {}
    if req.bot_token:
        custom_cfg['bot_token'] = req.bot_token
    if req.chat_id:
        custom_cfg['chat_id'] = req.chat_id

    success = monitor.send_digest('telegram', custom_cfg if custom_cfg else None)
    if success:
        return {"status": "success", "message": "Telegram digest dispatched successfully!"}
    else:
        raise HTTPException(status_code=500, detail="Failed to dispatch Telegram digest. Verify bot_token and chat_id in config/sources.yaml or request payload.")


# Serve the web command center frontend
web_dir = ROOT_DIR / "web"
if (web_dir / "static").exists():
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = ROOT_DIR / "web" / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h1>AI Security Monitor - Web UI not found.</h1>", status_code=404)
