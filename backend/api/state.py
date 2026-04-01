"""
Centralized in-memory state shared across all route modules.

All mutable packet/insight/chat state lives here so that
route modules can import it without circular dependencies.
"""
from __future__ import annotations

import asyncio
import pathlib
from collections import deque
from datetime import datetime
from typing import Optional

from config import settings


# ── In-memory stores ──────────────────────────────────────────────────────────
# max_packets_in_memory=0 means unlimited (plain deque, no maxlen).
_max = settings.max_packets_in_memory
_packets: deque[dict] = deque(maxlen=_max if _max > 0 else None)
_insights: deque[dict] = deque(maxlen=100)
_chat_history: deque[dict] = deque(maxlen=200)
_drain_task: Optional[asyncio.Task] = None

# ── Capture file tracking ─────────────────────────────────────────────────────
_current_capture_file: str = ""    # absolute path to the active pcap/pcapng file
_current_capture_name: str = ""    # display name (basename)

# ── Analysis state ────────────────────────────────────────────────────────────
_last_deep_analysis: dict | None = None

# ── Capture directory ─────────────────────────────────────────────────────────
_CAPTURE_DIR = pathlib.Path(settings.rag_data_dir).parent / "captures"


def ensure_capture_dir() -> pathlib.Path:
    _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    return _CAPTURE_DIR


def new_capture_path() -> pathlib.Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ensure_capture_dir() / f"capture_{ts}.pcapng"


# ── Packet accessors ──────────────────────────────────────────────────────────

def get_packets() -> list[dict]:
    return list(_packets)


def get_current_capture_file() -> str:
    """Return the absolute path to the current pcap file (empty string if none)."""
    return _current_capture_file


def clear_packets():
    _packets.clear()


def add_packets(pkts: list[dict]):
    _packets.extend(pkts)


def add_insight(text: str, source: str = "auto"):
    import time
    _insights.append({"text": text, "source": source, "timestamp": time.time()})
