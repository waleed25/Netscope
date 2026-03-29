"""
Per-user async message queue — inspired by OpenClaw's queue system.

Modes:
  COLLECT  — discard the previously queued message when a new one arrives
             (keeps only the latest pending message per user)
  FOLLOWUP — append to queue, process in order (FIFO)

Max depth: 3 messages.  Excess messages are silently dropped.
"""
from __future__ import annotations
import asyncio
from enum import Enum


class QueueMode(str, Enum):
    COLLECT = "collect"
    FOLLOWUP = "followup"


_MAX_DEPTH = 3


class UserQueue:
    """Per-user message queue with busy-lock tracking."""

    def __init__(self, mode: QueueMode = QueueMode.COLLECT) -> None:
        self._mode = mode
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_MAX_DEPTH)
        self._busy = False

    @property
    def is_busy(self) -> bool:
        return self._busy

    def set_busy(self, v: bool) -> None:
        self._busy = v

    def enqueue(self, text: str) -> bool:
        """
        Try to enqueue a message.
        In COLLECT mode: drain the queue first (discard stale messages), then put.
        In FOLLOWUP mode: append if space available.
        Returns True if accepted, False if dropped.
        """
        if self._mode == QueueMode.COLLECT:
            # Drain current contents (keep only latest)
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        if self._queue.full():
            return False  # Dropped

        try:
            self._queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            return False

    async def dequeue(self) -> str:
        return await self._queue.get()

    def empty(self) -> bool:
        return self._queue.empty()


class MessageQueueManager:
    """Factory for per-user UserQueue instances."""

    def __init__(self, mode: QueueMode = QueueMode.COLLECT) -> None:
        self._mode = mode
        self._queues: dict[str, UserQueue] = {}

    def get(self, user_key: str) -> UserQueue:
        if user_key not in self._queues:
            self._queues[user_key] = UserQueue(self._mode)
        return self._queues[user_key]

    def remove(self, user_key: str) -> None:
        self._queues.pop(user_key, None)
