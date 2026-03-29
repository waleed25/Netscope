"""
State proxy — fetch packet/insight/capture data from the Gateway via Redis.

This module replaces all direct imports from `api.routes` that previously
coupled agent tools to the Gateway's in-memory state.

Usage in tools (replaces `from api.routes import _packets`):
    from engine.state_proxy import get_packets, get_insights, get_current_capture_file
    packets = await get_packets()
"""
from __future__ import annotations

from typing import Any

from shared import events
from shared.bus import RedisBus

_bus: RedisBus | None = None


def set_bus(bus: RedisBus):
    """Called once from engine/main.py after connecting to Redis."""
    global _bus
    _bus = bus


async def get_packets(limit: int = 5000) -> list[dict[str, Any]]:
    """Fetch current packets from Gateway's in-memory store via Redis RPC."""
    if _bus is None:
        return []
    resp = await _bus.request(
        events.STATE_REQUEST,
        {"action": events.StateAction.GET_PACKETS, "limit": limit},
        events.STATE_RESPONSE,
        timeout_s=5.0,
    )
    if resp is None:
        return []
    return resp.get("packets", [])


async def get_current_capture_file() -> str:
    """Fetch the path to the current capture file from Gateway."""
    if _bus is None:
        return ""
    resp = await _bus.request(
        events.STATE_REQUEST,
        {"action": events.StateAction.GET_CAPTURE_FILE},
        events.STATE_RESPONSE,
        timeout_s=2.0,
    )
    if resp is None:
        return ""
    return resp.get("file", "")


async def get_insights(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch current insights from Gateway's in-memory store."""
    if _bus is None:
        return []
    resp = await _bus.request(
        events.STATE_REQUEST,
        {"action": events.StateAction.GET_INSIGHTS, "limit": limit},
        events.STATE_RESPONSE,
        timeout_s=2.0,
    )
    if resp is None:
        return []
    return resp.get("insights", [])


async def add_insight(text: str, source: str = "auto"):
    """Push a new insight to the Gateway."""
    if _bus is None:
        return
    await _bus.publish(events.STATE_REQUEST, {
        "action": events.StateAction.ADD_INSIGHT,
        "text": text,
        "source": source,
    })


async def clear_packets():
    """Tell the Gateway to clear its packet buffer."""
    if _bus is None:
        return
    await _bus.publish(events.STATE_REQUEST, {
        "action": events.StateAction.CLEAR_PACKETS,
    })


async def add_packets(packets: list[dict[str, Any]]):
    """Push packets to the Gateway's buffer."""
    if _bus is None:
        return
    await _bus.publish(events.STATE_REQUEST, {
        "action": events.StateAction.ADD_PACKETS,
        "packets": packets,
    })
