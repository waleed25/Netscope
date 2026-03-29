"""
WebSocket endpoints.
Packets are PUSHED to clients by the drain loop in routes.py via broadcast_packet().
The WS handler just maintains the connection — it does not read from the queue itself.
"""

from __future__ import annotations
import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent import analyzer

router = APIRouter()

_packet_clients: Set[WebSocket] = set()
_insight_clients: Set[WebSocket] = set()


async def _safe_send(ws: WebSocket, data: str):
    try:
        await ws.send_text(data)
    except Exception:
        pass


async def broadcast_packet(pkt: dict):
    """Called by the drain loop in routes.py to push a packet to all WS clients."""
    if not _packet_clients:
        return
    msg = json.dumps({"type": "packet", "data": pkt})
    dead = set()
    for ws in list(_packet_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _packet_clients.difference_update(dead)


async def broadcast_insight(insight: dict):
    """Push a completed insight to all WS clients."""
    if not _insight_clients:
        return
    msg = json.dumps({"type": "insight", "data": insight})
    dead = set()
    for ws in list(_insight_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _insight_clients.difference_update(dead)


@router.websocket("/ws/packets")
async def websocket_packets(websocket: WebSocket):
    """
    WebSocket kept alive so the server can push packets to the browser.
    The drain loop in routes.py calls broadcast_packet() for each packet.
    """
    await websocket.accept()
    _packet_clients.add(websocket)
    try:
        await _safe_send(websocket, json.dumps({"type": "connected"}))
        # Just keep the connection open — handle pings from client
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                data = json.loads(raw)
                if data.get("type") == "ping":
                    await _safe_send(websocket, json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send server-side keepalive
                await _safe_send(websocket, json.dumps({"type": "ping"}))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws/packets] {e}")
    finally:
        _packet_clients.discard(websocket)


@router.websocket("/ws/insights")
async def websocket_insights(websocket: WebSocket):
    await websocket.accept()
    _insight_clients.add(websocket)
    try:
        await _safe_send(websocket, json.dumps({"type": "connected"}))
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                data = json.loads(raw)
                if data.get("type") == "ping":
                    await _safe_send(websocket, json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                await _safe_send(websocket, json.dumps({"type": "ping"}))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws/insights] {e}")
    finally:
        _insight_clients.discard(websocket)
