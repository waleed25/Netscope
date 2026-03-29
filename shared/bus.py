"""
Redis Streams helper — async publish/subscribe/request-reply.

Each process creates one RedisBus instance at startup and uses it
for all inter-process communication.

Features:
  - publish()          → add to a Redis Stream (persistent, ordered)
  - subscribe()        → consume from a Stream (blocking generator)
  - request()          → publish + wait for correlated reply (RPC pattern)
  - pubsub_publish()   → Redis Pub/Sub broadcast (ephemeral, 1-to-many)
  - pubsub_subscribe() → Redis Pub/Sub listener

Dependencies: redis[hiredis] >= 5.0
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisBus:
    """Async wrapper around Redis Streams and Pub/Sub for inter-process messaging."""

    def __init__(self, url: str = "redis://localhost:6379", process_name: str = "unknown"):
        self._url = url
        self._process_name = process_name
        self._redis: aioredis.Redis | None = None
        self._consumer_name = f"{process_name}-{uuid.uuid4().hex[:8]}"
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, retry: bool = True, max_retries: int = 30, delay: float = 1.0):
        """Connect to Redis with optional retry loop."""
        for attempt in range(1, max_retries + 1):
            try:
                self._redis = aioredis.from_url(
                    self._url,
                    decode_responses=True,
                    max_connections=20,
                )
                await self._redis.ping()
                self._connected = True
                logger.info("[bus:%s] Connected to Redis at %s", self._process_name, self._url)
                return
            except Exception as exc:
                if not retry or attempt >= max_retries:
                    raise ConnectionError(
                        f"[bus:{self._process_name}] Failed to connect to Redis "
                        f"at {self._url} after {attempt} attempts: {exc}"
                    ) from exc
                logger.warning(
                    "[bus:%s] Redis connection attempt %d/%d failed: %s — retrying in %.1fs",
                    self._process_name, attempt, max_retries, exc, delay,
                )
                await asyncio.sleep(delay)

    async def close(self):
        """Cleanly close the Redis connection."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._connected = False
            logger.info("[bus:%s] Disconnected from Redis", self._process_name)

    # ── Stream: Publish ──────────────────────────────────────────────────────

    async def publish(self, stream: str, data: dict[str, Any], maxlen: int = 10000) -> str:
        """
        Add a message to a Redis Stream.
        Returns the auto-generated message ID (e.g. "1234567890-0").
        """
        # Serialize non-string values to JSON so Redis stores them faithfully
        fields: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(v, str):
                fields[k] = v
            else:
                fields[k] = json.dumps(v, default=str)

        msg_id = await self._redis.xadd(stream, fields, maxlen=maxlen)
        return msg_id

    # ── Stream: Subscribe (blocking generator) ────────────────────────────────

    async def subscribe(
        self,
        stream: str,
        last_id: str = "$",
        block_ms: int = 200,
    ) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        """
        Yield (msg_id, data) from a Redis Stream, starting after last_id.

        Use last_id="$" to get only NEW messages (default).
        Use last_id="0" to replay all existing messages.

        This is an infinite generator — it blocks waiting for new messages.
        Cancel the task to stop consuming.
        """
        while self._connected:
            try:
                entries = await self._redis.xread(
                    {stream: last_id}, count=100, block=block_ms
                )
                if not entries:
                    continue
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        data = {k: _try_json(v) for k, v in fields.items()}
                        last_id = msg_id
                        yield msg_id, data
            except asyncio.CancelledError:
                return
            except aioredis.ConnectionError:
                logger.warning("[bus:%s] Redis connection lost, reconnecting...", self._process_name)
                await asyncio.sleep(1.0)
                try:
                    await self._redis.ping()
                except Exception:
                    await asyncio.sleep(2.0)
            except Exception as exc:
                logger.error("[bus:%s] subscribe(%s) error: %s", self._process_name, stream, exc)
                await asyncio.sleep(0.5)

    # ── Request-Reply pattern ─────────────────────────────────────────────────

    async def request(
        self,
        request_stream: str,
        data: dict[str, Any],
        reply_stream: str,
        timeout_s: float = 30.0,
    ) -> dict[str, Any] | None:
        """
        Publish a request to *request_stream* and wait for a correlated reply
        on *reply_stream*.

        The responder MUST copy `_correlation_id` into its reply message.

        Returns the reply dict, or None on timeout.
        """
        correlation_id = uuid.uuid4().hex
        data["_correlation_id"] = correlation_id
        data["_reply_to"] = reply_stream

        # Snapshot the current tail of the reply stream BEFORE publishing.
        # Using "$" would miss replies that arrive before our first xread().
        try:
            info = await self._redis.xinfo_stream(reply_stream)
            reply_last_id = info.get("last-generated-id", "0-0")
        except Exception:
            # Stream doesn't exist yet — start from the beginning
            reply_last_id = "0-0"

        await self.publish(request_stream, data)

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining_ms = max(100, int((deadline - time.monotonic()) * 1000))
            try:
                entries = await self._redis.xread(
                    {reply_stream: reply_last_id},
                    count=10,
                    block=min(remaining_ms, 1000),
                )
            except asyncio.CancelledError:
                return None
            except Exception:
                await asyncio.sleep(0.2)
                continue

            if not entries:
                continue

            for _stream_name, messages in entries:
                for msg_id, fields in messages:
                    reply_last_id = msg_id
                    reply_data = {k: _try_json(v) for k, v in fields.items()}
                    if reply_data.get("_correlation_id") == correlation_id:
                        return reply_data

        logger.warning(
            "[bus:%s] request(%s) timed out after %.1fs",
            self._process_name, request_stream, timeout_s,
        )
        return None

    # ── Pub/Sub: Broadcast (ephemeral, 1-to-many) ────────────────────────────

    async def pubsub_publish(self, channel: str, data: dict[str, Any]):
        """Publish a message to a Redis Pub/Sub channel (fire-and-forget)."""
        await self._redis.publish(channel, json.dumps(data, default=str))

    async def pubsub_subscribe(self, channel: str) -> AsyncGenerator[dict[str, Any], None]:
        """
        Subscribe to a Redis Pub/Sub channel and yield parsed messages.

        This is an infinite generator. Cancel the task to stop.
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        yield json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        yield {"raw": message["data"]}
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    # ── Health heartbeat helper ───────────────────────────────────────────────

    async def heartbeat_loop(self, stream: str, interval_s: float = 5.0):
        """
        Publish periodic health heartbeats to a Redis Stream.
        Run this as a background task in each process.
        """
        start_time = time.monotonic()
        while self._connected:
            try:
                await self.publish(stream, {
                    "process": self._process_name,
                    "status": "ok",
                    "timestamp": time.time(),
                    "uptime_s": round(time.monotonic() - start_time, 1),
                }, maxlen=100)
            except Exception:
                pass
            await asyncio.sleep(interval_s)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _try_json(value: str) -> Any:
    """Attempt to parse a string as JSON; return the raw string on failure."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value
