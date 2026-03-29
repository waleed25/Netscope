"""libpcap capture adapter — Linux/Mac."""
from __future__ import annotations


class LibpcapAdapter:
    """Wraps the existing daemon capture logic for Linux/Mac libpcap."""
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
