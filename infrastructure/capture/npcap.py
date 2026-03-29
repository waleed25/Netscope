"""Npcap capture adapter — Windows only."""
from __future__ import annotations


class NpcapAdapter:
    """Wraps the existing daemon capture logic for Windows Npcap."""
    def __init__(self):
        self._running = False

    def is_running(self) -> bool:
        return self._running

    async def start(self, interface: str, filter_expr: str = "") -> None:
        from daemon.capture.live_capture import start_capture  # type: ignore
        await start_capture(interface=interface, filter_str=filter_expr)
        self._running = True

    async def stop(self) -> None:
        from daemon.capture.live_capture import stop_capture  # type: ignore
        await stop_capture()
        self._running = False
