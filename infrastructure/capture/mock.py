"""Mock capture adapter — for VMs, CI, or devices without capture drivers."""
from __future__ import annotations
import asyncio


class MockAdapter:
    """No-op capture adapter. Used when neither Npcap nor libpcap is available.
    Allows the app to run without packet capture support (PCAP import only)."""
    def __init__(self):
        self._running = False

    def is_running(self) -> bool:
        return self._running

    async def start(self, interface: str = "", filter_expr: str = "") -> None:
        self._running = True
        # No actual capture — mock only

    async def stop(self) -> None:
        self._running = False
