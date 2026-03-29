"""
NetScope Gateway — lightweight API + WebSocket process.

This is the process that serves HTTP and WebSocket connections to the frontend.
It proxies all heavyweight operations to the Daemon and Engine via Redis.

Responsibilities:
  - Serve REST API (captures, chat, modbus, RAG, etc.) — proxy to Daemon/Engine
  - Serve WebSocket connections (packet stream, insights)
  - Maintain in-memory packet/insight/chat stores
  - Run Telegram/WhatsApp channels
  - Run APScheduler jobs
  - Run network diagnostic tools (ping, tracert, arp, netstat, ipconfig)

This process runs at USER privilege level — no Administrator required.

Communication:
  - Subscribes to:  capture.packets (Pub/Sub), state.request, health.*
  - Publishes to:   capture.command, chat.request, modbus.command, etc.
  - Health:         ns:health.gateway (heartbeat)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_GATEWAY_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _GATEWAY_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))          # for `shared.*`
sys.path.insert(0, str(_GATEWAY_DIR))            # for local modules
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))  # transitional: use existing backend modules

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.bus import RedisBus
from shared import events

logging.basicConfig(
    level=logging.INFO,
    format="[gateway] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gateway")

# ── Global bus instance ──────────────────────────────────────────────────────
bus = RedisBus(process_name="gateway")


def get_bus() -> RedisBus:
    """Accessor for route modules to get the gateway's bus instance."""
    return bus


# ── State management ─────────────────────────────────────────────────────────
# The Gateway owns in-memory state (packets, insights, chat history).
# Other processes fetch this via state.request → state.response.

from collections import deque

_packets: deque[dict] = deque(maxlen=10000)
_insights: deque[dict] = deque(maxlen=100)
_chat_history: deque[dict] = deque(maxlen=200)
_current_capture_file: str = ""
_current_capture_name: str = ""


async def handle_state_requests():
    """Listen for state.request from Engine and serve local state."""
    logger.info("Listening on %s", events.STATE_REQUEST)

    async for msg_id, data in bus.subscribe(events.STATE_REQUEST, last_id="$"):
        action = data.get("action", "")
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.STATE_RESPONSE)

        try:
            if action == events.StateAction.GET_PACKETS:
                limit = data.get("limit", 5000)
                pkts = list(_packets)[-limit:]
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "packets": pkts,
                })

            elif action == events.StateAction.GET_CAPTURE_FILE:
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "file": _current_capture_file,
                    "name": _current_capture_name,
                })

            elif action == events.StateAction.GET_INSIGHTS:
                limit = data.get("limit", 10)
                items = list(_insights)[-limit:]
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "insights": items,
                })

            elif action == events.StateAction.ADD_INSIGHT:
                import time
                _insights.append({
                    "text": data.get("text", ""),
                    "source": data.get("source", "auto"),
                    "timestamp": time.time(),
                })

            elif action == events.StateAction.CLEAR_PACKETS:
                _packets.clear()

            elif action == events.StateAction.ADD_PACKETS:
                pkts = data.get("packets", [])
                _packets.extend(pkts)

        except Exception as exc:
            logger.error("state.request error (%s): %s", action, exc)


# ── Packet bridge: Redis Pub/Sub → local store + WebSocket ───────────────────

_ws_packet_clients: set = set()
_ws_insight_clients: set = set()


async def packet_bridge():
    """Subscribe to Daemon's live packets and store + broadcast them."""
    logger.info("Subscribing to %s", events.PUBSUB_PACKETS)

    async for pkt_data in bus.pubsub_subscribe(events.PUBSUB_PACKETS):
        _packets.append(pkt_data)

        # Fan out to WebSocket clients
        if _ws_packet_clients:
            msg = json.dumps({"type": "packet", "data": pkt_data})
            dead = set()
            for ws in list(_ws_packet_clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            _ws_packet_clients.difference_update(dead)


# ── FastAPI app ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the gateway."""
    # Connect to Redis
    await bus.connect(retry=True, max_retries=60, delay=1.0)
    logger.info("Connected to Redis — gateway ready")

    # Start background tasks
    tasks = [
        asyncio.create_task(handle_state_requests()),
        asyncio.create_task(packet_bridge()),
        asyncio.create_task(bus.heartbeat_loop(events.HEALTH_GATEWAY, interval_s=5.0)),
    ]

    yield

    # Shutdown
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await bus.close()
    logger.info("Gateway shut down cleanly")


app = FastAPI(
    title="NetScope Gateway",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow Electron frontend
import os as _os
_port = _os.environ.get("GATEWAY_PORT", _os.environ.get("PORT", "8000"))
_cors_origins = [
    "null",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    f"http://127.0.0.1:{_port}",
    f"http://localhost:{_port}",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Mount routes ─────────────────────────────────────────────────────────────
# During the transition, we mount the existing backend routes unchanged.
# They still work because api.state is imported.
# Post-migration, these will be replaced with proxy routes.

try:
    from api.routes import router as legacy_router
    app.include_router(legacy_router, prefix="/api")
    logger.info("Mounted legacy API routes")
except ImportError as exc:
    logger.warning("Could not mount legacy routes: %s", exc)

try:
    from api.websocket import router as ws_router
    app.include_router(ws_router)
    logger.info("Mounted WebSocket routes")
except ImportError as exc:
    logger.warning("Could not mount WebSocket routes: %s", exc)

try:
    from channels.router import router as channels_router
    app.include_router(channels_router, prefix="/api/channels")
    logger.info("Mounted channels routes")
except ImportError as exc:
    logger.warning("Could not mount channels routes: %s", exc)

try:
    from api.modbus_routes import router as modbus_router
    from api.rag_routes import router as rag_router
    from api.scheduler_routes import router as scheduler_router
    app.include_router(modbus_router, prefix="/api")
    app.include_router(rag_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")
    logger.info("Mounted modbus, rag, scheduler routes")
except ImportError as exc:
    logger.warning("Could not mount modbus/rag/scheduler routes: %s", exc)

from gateway.features_route import router as features_router
app.include_router(features_router, prefix="/api")
logger.info("Mounted features/capabilities routes")

from gateway.wizard_route import router as wizard_router
app.include_router(wizard_router, prefix="/api")
logger.info("Mounted wizard routes")

from gateway.report_route import router as report_router
app.include_router(report_router, prefix="/api")
logger.info("Mounted report routes")


# ── Health endpoint ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint for Electron to poll."""
    return {
        "status": "ok",
        "process": "gateway",
        "redis_connected": bus.connected,
        "packets_in_memory": len(_packets),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
