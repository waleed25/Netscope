"""Packet capture capability adapter."""
from __future__ import annotations
from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class CaptureAdapter(Protocol):
    async def start(self, interface: str, filter_expr: str = "") -> None: ...
    async def stop(self) -> None: ...
    def is_running(self) -> bool: ...


def detect_capture(caps) -> "CaptureAdapter":
    """Select best capture adapter for the detected hardware/OS."""
    if caps.npcap:
        from .npcap import NpcapAdapter
        return NpcapAdapter()
    elif caps.libpcap:
        from .libpcap import LibpcapAdapter
        return LibpcapAdapter()
    else:
        from .mock import MockAdapter
        return MockAdapter()
