"""
Abstract base class for all Netscope messaging channels.

Implements:
  - DM policy enforcement (pairing / allowlist / open)
  - Per-user rate limiting
  - Per-user conversation history (isolated from desktop _chat_history)
  - OpenClaw-inspired message queue (collect/followup modes)
  - Platform-adaptive response delivery (implemented by subclasses)
  - PCAP upload handling
"""
from __future__ import annotations
import asyncio
import os
import re
import tempfile
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from channels.rate_limiter import RateLimiter
from channels.message_queue import MessageQueueManager, QueueMode


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ChannelMessage:
    channel: str
    user_id: str
    username: str
    text: str
    is_bot: bool       # True = bot reply, False = user message
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChannelStatus:
    name: str
    connected: bool
    state: str          # "connected" | "disconnected" | "qr_pending" | "error"
    error: str | None
    message_count: int


# ── Sanitisation (mirrors chat.py / tools.py _safe_str) ──────────────────────

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def _sanitize(text: str, max_len: int = 4096) -> str:
    """Strip control chars and cap length — prompt-injection defence."""
    cleaned = _CTRL_RE.sub("", str(text))
    return cleaned[:max_len]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _truncate_for_mobile(text: str, limit: int = 1500) -> str:
    """Truncate long responses for phone chat UIs."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n…_(reply 'more' for full output)_"


# ── Abstract channel ──────────────────────────────────────────────────────────

class BaseChannel(ABC):
    name: str = "base"
    _HISTORY_MAXLEN = 40   # 20 conversation turns per user

    def __init__(
        self,
        dm_policy: str = "pairing",
        allowed_user_ids: list[str] | None = None,
        rate_seconds: float = 3.0,
        queue_mode: QueueMode = QueueMode.COLLECT,
    ) -> None:
        self._dm_policy = dm_policy            # "pairing" | "allowlist" | "open"
        self._allowed_ids: set[str] = set(allowed_user_ids or [])
        self._rate_limiter = RateLimiter(rate_seconds)
        self._queue_mgr = MessageQueueManager(queue_mode)

        # Per-user conversation history: key → deque of {"role","content"} dicts
        self._history: dict[str, deque] = {}

        # Global message log (most recent 50 across all users)
        self._message_log: deque[ChannelMessage] = deque(maxlen=50)

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send_message(self, user_id: str, text: str) -> None: ...

    @abstractmethod
    def status(self) -> ChannelStatus: ...

    # ── History ───────────────────────────────────────────────────────────────

    def _get_history(self, user_key: str) -> deque:
        if user_key not in self._history:
            self._history[user_key] = deque(maxlen=self._HISTORY_MAXLEN)
        return self._history[user_key]

    def clear_history(self, user_key: str) -> None:
        if user_key in self._history:
            self._history[user_key].clear()

    def _log(self, channel: str, user_id: str, username: str, text: str, is_bot: bool) -> None:
        self._message_log.append(ChannelMessage(
            channel=channel, user_id=user_id, username=username,
            text=text, is_bot=is_bot,
        ))

    def get_messages(self) -> list[ChannelMessage]:
        return list(self._message_log)

    # ── Access control ────────────────────────────────────────────────────────

    def _check_access(self, user_key: str) -> str | None:
        """
        Returns None if user is allowed.
        Returns a denial reason string if access should be denied
        (caller should reply with this string and stop processing).
        """
        if self._dm_policy == "open":
            return None
        if self._dm_policy == "allowlist":
            uid = user_key.split(":")[-1]
            if uid in self._allowed_ids:
                return None
            return (
                "🔒 You are not on the allowed list for this bot. "
                "Ask the admin to add your ID."
            )
        # "pairing" mode — check allowlist first, then prompt for code
        uid = user_key.split(":")[-1]
        if uid in self._allowed_ids:
            return None
        return None  # Subclass handles pairing flow before calling route_to_agent

    # ── Core routing pipeline ─────────────────────────────────────────────────

    async def route_to_agent(
        self,
        user_key: str,
        text: str,
        send_fn: Callable[[str, str], Awaitable[None]],
        *,
        username: str = "",
    ) -> None:
        """
        Full OpenClaw-inspired pipeline:
        1. Rate limit check
        2. Sanitize text
        3. Enqueue in user's MessageQueue
        4. If queue was empty (not busy), start processing immediately
        """
        # Rate limit
        if not self._rate_limiter.check(user_key):
            await send_fn(user_key, "⏱️ Please wait a few seconds before sending another message.")
            return

        safe_text = _sanitize(text)
        uid = user_key.split(":")[-1]
        self._log(self.name, uid, username, safe_text, is_bot=False)

        uq = self._queue_mgr.get(user_key)

        if uq.is_busy:
            accepted = uq.enqueue(safe_text)
            if accepted:
                await send_fn(user_key, "⏳ I'm still working on your previous request — I'll get to this next.")
            # If not accepted (queue full), silently drop
            return

        # Queue was empty — process immediately
        uq.set_busy(True)
        uq.enqueue(safe_text)

        try:
            while not uq.empty():
                msg = await uq.dequeue()
                await self._process_message(user_key, msg, send_fn, username=username)
        finally:
            uq.set_busy(False)

    async def _process_message(
        self,
        user_key: str,
        text: str,
        send_fn: Callable[[str, str], Awaitable[None]],
        *,
        username: str = "",
    ) -> None:
        """Call the Netscope AI agent and deliver the response."""
        # Import here to avoid circular imports at module load time
        from agent.chat import answer_question
        from api.routes import _packets

        history = list(self._get_history(user_key))
        packets_snapshot = list(_packets)

        # Handle "more" shortcut — return last response untruncated
        if text.strip().lower() == "more":
            # Re-send last bot message from log without truncation
            recent = [m for m in reversed(self._message_log) if m.is_bot]
            if recent:
                await send_fn(user_key, recent[0].text)
            else:
                await send_fn(user_key, "No previous response to expand.")
            return

        try:
            answer = await asyncio.wait_for(
                answer_question(text, packets_snapshot, history, rag_enabled=False, use_hyde=False, is_channel=True),
                timeout=180,
            )
        except asyncio.TimeoutError:
            answer = "⚠️ The request timed out. Please try a simpler query."
        except Exception as exc:
            answer = f"⚠️ Error: {exc}"

        # Update history
        hist = self._get_history(user_key)
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": answer})

        uid = user_key.split(":")[-1]
        self._log(self.name, uid, username, answer, is_bot=True)

        truncated = _truncate_for_mobile(answer)
        await send_fn(user_key, truncated)

    # ── PCAP upload handling ──────────────────────────────────────────────────

    async def handle_pcap_upload(
        self,
        user_key: str,
        file_bytes: bytes,
        filename: str,
        send_fn: Callable[[str, str], Awaitable[None]],
        *,
        username: str = "",
    ) -> None:
        """Save uploaded .pcap → parse → answer 'Analyze this capture'."""
        from capture.pcap_reader import read_pcap

        await send_fn(user_key, f"📦 Received `{filename}` — analyzing…")

        # Write to temp file
        suffix = ".pcapng" if filename.endswith(".pcapng") else ".pcap"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            packets = []
            async for pkt in read_pcap(tmp_path):
                packets.append(pkt)

            if not packets:
                await send_fn(user_key, "❌ Could not parse any packets from that file.")
                return

            # Use captured packets as context for this query
            from agent.chat import answer_question
            history = list(self._get_history(user_key))

            answer = await asyncio.wait_for(
                answer_question(
                    "Analyze this captured traffic. Summarize the top protocols, source/destination IPs, "
                    "and any anomalies or notable patterns. Keep the answer concise.",
                    packets,
                    history,
                    rag_enabled=False,
                    use_hyde=False,
                ),
                timeout=180,
            )

            hist = self._get_history(user_key)
            hist.append({"role": "user", "content": f"[Uploaded PCAP: {filename}]"})
            hist.append({"role": "assistant", "content": answer})

            uid = user_key.split(":")[-1]
            self._log(self.name, uid, username, f"[PCAP upload: {filename}]", is_bot=False)
            self._log(self.name, uid, username, answer, is_bot=True)

            await send_fn(user_key, _truncate_for_mobile(answer))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
