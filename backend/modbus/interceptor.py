"""
Modbus traffic interceptor — FrameStore, InterceptorWrap, ProxyServer.

FrameStore      : ring buffer + JSONL file log + WebSocket fanout
InterceptorWrap : patches a live pymodbus asyncio client (TCP or RTU) after connect()
ProxyServer     : transparent TCP forwarder for passive capture
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from asyncio import StreamReader, StreamWriter
from collections import deque
from pathlib import Path
from typing import IO, Any, Literal

from modbus.frame_parser import ParsedFrame, parse_tcp_frame, parse_rtu_frame

logger = logging.getLogger(__name__)


# ── FrameStore ────────────────────────────────────────────────────────────────

class FrameStore:
    """
    Per-session captured frame store.

    Thread-safety: asyncio-only (no threading). All callers must be in the
    same event loop as the ClientSession.
    """

    def __init__(self, session_id: str, max_frames: int = 10_000):
        self.session_id   = session_id
        self.max_frames   = max_frames
        self._ring: deque[ParsedFrame] = deque(maxlen=max_frames)
        self._lock        = asyncio.Lock()
        self._log_file: IO[str] | None = None
        self._log_path: Path | None    = None
        self._ws_clients: set[Any]     = set()

        # counters
        self._tx_frames        = 0
        self._rx_frames        = 0
        self._exception_frames = 0

    async def ingest(self, frame: ParsedFrame) -> None:
        """Append frame to ring, write to JSONL if enabled, broadcast to WS clients."""
        async with self._lock:
            self._ring.append(frame)
            if frame.direction == "tx":
                self._tx_frames += 1
            else:
                self._rx_frames += 1
            if frame.is_exception:
                self._exception_frames += 1

            if self._log_file is not None:
                try:
                    self._log_file.write(
                        json.dumps(dataclasses.asdict(frame)) + "\n"
                    )
                    self._log_file.flush()
                except Exception as exc:
                    logger.warning("FrameStore file write error: %s", exc)

        # Broadcast to WebSocket clients outside the lock (fire-and-forget)
        if self._ws_clients:
            payload = dataclasses.asdict(frame)
            dead: set[Any] = set()
            for ws in list(self._ws_clients):
                try:
                    await asyncio.wait_for(ws.send_json(payload), timeout=0.5)
                except Exception:
                    dead.add(ws)
            self._ws_clients -= dead

    def get_recent(self, n: int = 100) -> list[ParsedFrame]:
        return list(self._ring)[-n:]

    def counters(self) -> dict:
        return {
            "tx_frames":        self._tx_frames,
            "rx_frames":        self._rx_frames,
            "exception_frames": self._exception_frames,
            "total":            self._tx_frames + self._rx_frames,
        }

    def enable_file_log(self, path: Path) -> None:
        self.disable_file_log()
        self._log_path = path
        self._log_file = open(path, "a", encoding="utf-8")
        logger.info("FrameStore[%s]: file logging to %s", self.session_id, path)

    def disable_file_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
            self._log_path = None

    async def add_ws(self, ws: Any) -> None:
        self._ws_clients.add(ws)

    async def remove_ws(self, ws: Any) -> None:
        self._ws_clients.discard(ws)


# ── InterceptorWrap ───────────────────────────────────────────────────────────

class InterceptorWrap:
    """
    Patches a live pymodbus client's asyncio transport in-place after connect().

    Works for both AsyncModbusTcpClient and AsyncModbusSerialClient (pymodbus >= 3.6),
    both of which expose .transport and .protocol after a successful connect().
    """

    def __init__(self):
        self._orig_write:         Any = None
        self._orig_data_received: Any = None
        self._client_ref:         Any = None

    def attach(
        self,
        client: Any,
        store: FrameStore,
        frame_type: Literal["tcp", "rtu"],
    ) -> None:
        if self._orig_write is not None:
            logger.warning(
                "InterceptorWrap.attach: already attached — detach first; skipping."
            )
            return

        transport = getattr(client, "transport", None)
        protocol  = getattr(client, "protocol",  None)

        if transport is None or protocol is None:
            logger.warning(
                "InterceptorWrap.attach: client has no transport/protocol — "
                "pymodbus version mismatch or not yet connected; skipping."
            )
            return

        self._orig_write         = transport.write
        self._orig_data_received = protocol.data_received
        self._client_ref         = client

        parser = parse_rtu_frame if frame_type == "rtu" else parse_tcp_frame

        orig_write         = self._orig_write
        orig_data_received = self._orig_data_received

        def _patched_write(data: bytes) -> None:
            ts = time.time_ns() // 1000
            try:
                _t = asyncio.get_running_loop().create_task(
                    store.ingest(parser(data, "tx", ts))
                )
                _t.add_done_callback(lambda _: None)
            except Exception as exc:
                logger.debug("InterceptorWrap write log error: %s", exc)
            orig_write(data)

        def _patched_data_received(data: bytes) -> None:
            ts = time.time_ns() // 1000
            try:
                _t = asyncio.get_running_loop().create_task(
                    store.ingest(parser(data, "rx", ts))
                )
                _t.add_done_callback(lambda _: None)
            except Exception as exc:
                logger.debug("InterceptorWrap recv log error: %s", exc)
            orig_data_received(data)

        transport.write          = _patched_write
        protocol.data_received   = _patched_data_received

    def detach(self, client: Any) -> None:
        if self._orig_write is not None:
            transport = getattr(client, "transport", None)
            if transport is not None:
                transport.write = self._orig_write
        if self._orig_data_received is not None:
            protocol = getattr(client, "protocol", None)
            if protocol is not None:
                protocol.data_received = self._orig_data_received
        self._orig_write = self._orig_data_received = self._client_ref = None


# ── ProxyServer ───────────────────────────────────────────────────────────────

class ProxyServer:
    """
    Transparent asyncio TCP forwarder.

    When active, the Modbus client connects to 127.0.0.1:local_port instead
    of the real device. Every byte is forwarded bidirectionally and a copy is
    ingested into the FrameStore.
    """

    def __init__(
        self,
        remote_host: str,
        remote_port: int,
        store: FrameStore,
        local_port: int = 0,
    ):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.store       = store
        self._local_port = local_port
        self._server: asyncio.Server | None = None

    @property
    def local_port(self) -> int:
        """Bound local port — valid after start() returns."""
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._local_port

    async def start(self) -> int:
        if self._server is not None:
            logger.warning(
                "ProxyServer.start: already running on port %d; ignoring.",
                self.local_port,
            )
            return self.local_port
        self._server = await asyncio.start_server(
            self._handle_connection, "127.0.0.1", self._local_port
        )
        port = self.local_port
        logger.info(
            "ProxyServer: 127.0.0.1:%d → %s:%d",
            port, self.remote_host, self.remote_port,
        )
        return port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            self._server = None

    async def _handle_connection(
        self, client_reader: StreamReader, client_writer: StreamWriter
    ) -> None:
        try:
            dev_reader, dev_writer = await asyncio.wait_for(
                asyncio.open_connection(self.remote_host, self.remote_port),
                timeout=5.0,
            )
        except Exception as exc:
            logger.warning("ProxyServer: cannot connect to device: %s", exc)
            client_writer.close()
            return

        tasks = [
            asyncio.ensure_future(self._pipe(client_reader, dev_writer,    "tx")),
            asyncio.ensure_future(self._pipe(dev_reader,    client_writer, "rx")),
        ]
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for w in (client_writer, dev_writer):
                try:
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass

    async def _pipe(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        direction: Literal["tx", "rx"],
    ) -> None:
        while True:
            try:
                chunk = await reader.read(4096)
            except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
                break
            except Exception as exc:
                logger.warning(
                    "ProxyServer _pipe unexpected read error [%s]: %s", direction, exc
                )
                break
            if not chunk:
                break
            ts = time.time_ns() // 1000
            try:
                await self.store.ingest(parse_tcp_frame(chunk, direction, ts))
            except Exception as exc:
                logger.debug("ProxyServer ingest error: %s", exc)
            try:
                writer.write(chunk)
                await writer.drain()
            except Exception:
                break
