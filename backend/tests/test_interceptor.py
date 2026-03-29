import asyncio
import dataclasses
import json
import time
from pathlib import Path
import tempfile
import pytest

from modbus.frame_parser import ParsedFrame, MBAPHeader
from modbus.interceptor import FrameStore
from modbus.interceptor import ProxyServer


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_frame(direction: str = "tx", is_exc: bool = False) -> ParsedFrame:
    return ParsedFrame(
        direction=direction,
        ts_us=time.time_ns() // 1000,
        frame_type="tcp",
        raw_hex="000100000006010300000001",
        mbap=MBAPHeader(1, 0, 6, 1),
        function_code=3,
        fc_name="Read Holding Registers",
        is_exception=is_exc,
        exception_code=0x02 if is_exc else None,
        exception_name="Illegal Data Address" if is_exc else None,
        start_address=0,
        quantity=1,
        byte_count=None,
        data_hex=None,
        crc_valid=None,
        parse_error=None,
    )


# ── FrameStore tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_frame_store_ring_buffer():
    store = FrameStore(session_id="s1", max_frames=5)
    for i in range(7):
        await store.ingest(_make_frame("tx"))
    assert len(store.get_recent(100)) == 5  # capped at max_frames


@pytest.mark.asyncio
async def test_frame_store_get_recent_n():
    store = FrameStore(session_id="s1", max_frames=100)
    for _ in range(20):
        await store.ingest(_make_frame("tx"))
    assert len(store.get_recent(5)) == 5
    assert len(store.get_recent(100)) == 20


@pytest.mark.asyncio
async def test_frame_store_counters():
    store = FrameStore(session_id="s1")
    await store.ingest(_make_frame("tx"))
    await store.ingest(_make_frame("rx"))
    await store.ingest(_make_frame("rx", is_exc=True))
    c = store.counters()
    assert c["tx_frames"] == 1
    assert c["rx_frames"] == 2
    assert c["exception_frames"] == 1
    assert c["total"] == 3


@pytest.mark.asyncio
async def test_frame_store_file_log(tmp_path):
    log_file = tmp_path / "traffic.jsonl"
    store = FrameStore(session_id="s1")
    store.enable_file_log(log_file)
    await store.ingest(_make_frame("tx"))
    await store.ingest(_make_frame("rx"))
    store.disable_file_log()

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["direction"] == "tx"
    assert row["function_code"] == 3


@pytest.mark.asyncio
async def test_frame_store_file_log_disabled_by_default():
    store = FrameStore(session_id="s1")
    await store.ingest(_make_frame("tx"))
    # No error, no file created — logging is off by default
    assert store._log_file is None


@pytest.mark.asyncio
async def test_frame_store_disable_file_log_is_idempotent():
    store = FrameStore(session_id="s1")
    store.disable_file_log()   # should not raise even if never enabled
    store.disable_file_log()   # second call also safe


from modbus.interceptor import InterceptorWrap


# ── InterceptorWrap tests ─────────────────────────────────────────────────────

class _FakeTransport:
    def __init__(self):
        self.written: list[bytes] = []
    def write(self, data: bytes) -> None:
        self.written.append(data)

class _FakeProtocol:
    def __init__(self):
        self.received: list[bytes] = []
    def data_received(self, data: bytes) -> None:
        self.received.append(data)

class _FakeClient:
    def __init__(self):
        self.transport = _FakeTransport()
        self.protocol  = _FakeProtocol()


@pytest.mark.asyncio
async def test_interceptor_wrap_captures_tx():
    store  = FrameStore(session_id="s1")
    client = _FakeClient()
    wrap   = InterceptorWrap()

    # FC3 request (12 bytes — valid TCP frame)
    TX_FRAME = bytes([0x00,0x01,0x00,0x00,0x00,0x06,0x01,0x03,0x00,0x00,0x00,0x01])
    wrap.attach(client, store, "tcp")
    client.transport.write(TX_FRAME)

    # Wait briefly for the create_task to complete
    await asyncio.sleep(0.05)
    assert store.counters()["tx_frames"] == 1
    assert store.get_recent(1)[0].direction == "tx"
    assert store.get_recent(1)[0].function_code == 3


@pytest.mark.asyncio
async def test_interceptor_wrap_captures_rx():
    store  = FrameStore(session_id="s1")
    client = _FakeClient()
    wrap   = InterceptorWrap()

    # FC3 exception response (9 bytes)
    RX_FRAME = bytes([0x00,0x01,0x00,0x00,0x00,0x03,0x01,0x83,0x02])
    wrap.attach(client, store, "tcp")
    client.protocol.data_received(RX_FRAME)

    await asyncio.sleep(0.05)
    assert store.counters()["rx_frames"] == 1
    f = store.get_recent(1)[0]
    assert f.direction == "rx"
    assert f.is_exception is True


@pytest.mark.asyncio
async def test_interceptor_wrap_detach_restores_originals():
    store  = FrameStore(session_id="s1")
    client = _FakeClient()
    wrap   = InterceptorWrap()

    # Record the methods before patching
    client.transport._method_before = client.transport.write
    client.protocol._method_before = client.protocol.data_received

    wrap.attach(client, store, "tcp")
    # Verify they were patched (different callable)
    assert client.transport.write is not client.transport._method_before
    assert client.protocol.data_received is not client.protocol._method_before

    wrap.detach(client)
    # After detach, they should be restored to originals
    # (can't use 'is' with bound methods, but they should be the same underlying function)
    assert client.transport.write.__func__ is client.transport._method_before.__func__
    assert client.protocol.data_received.__func__ is client.protocol._method_before.__func__


@pytest.mark.asyncio
async def test_interceptor_wrap_missing_transport_is_noop():
    """attach() should not raise if pymodbus transport is missing."""
    store  = FrameStore(session_id="s1")
    client = object()   # has neither transport nor protocol
    wrap   = InterceptorWrap()
    wrap.attach(client, store, "tcp")   # must not raise
    # nothing was captured — no crash
    assert store.counters()["total"] == 0


# ── ProxyServer tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_server_starts_and_returns_port():
    """ProxyServer binds to a free port and returns it from start()."""
    store  = FrameStore(session_id="s1")
    # Point at a nonexistent remote — we only test binding here
    proxy  = ProxyServer("127.0.0.1", 65000, store, local_port=0)
    local_port = await proxy.start()
    assert isinstance(local_port, int)
    assert 1024 <= local_port <= 65535
    await proxy.stop()


@pytest.mark.asyncio
async def test_proxy_server_forwards_bytes_and_captures_frames():
    """
    Set up a tiny echo server, run ProxyServer in front of it, send a
    known Modbus TCP frame, and verify both tx and rx frames land in the store.
    """
    # ── echo server ──────────────────────────────────────────────────────────
    async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        writer.write(data)
        await writer.drain()
        writer.close()

    echo_server = await asyncio.start_server(_echo, "127.0.0.1", 0)
    echo_port = echo_server.sockets[0].getsockname()[1]

    # ── proxy in front of echo server ────────────────────────────────────────
    store = FrameStore(session_id="s1")
    proxy = ProxyServer("127.0.0.1", echo_port, store, local_port=0)
    local_port = await proxy.start()

    # ── send a valid FC3 TCP frame through the proxy ──────────────────────────
    FC3_REQ = bytes([0x00,0x01,0x00,0x00,0x00,0x06,0x01,0x03,0x00,0x00,0x00,0x01])
    reader, writer = await asyncio.open_connection("127.0.0.1", local_port)
    writer.write(FC3_REQ)
    await writer.drain()
    response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    assert response == FC3_REQ   # echo confirms full round-trip completed
    writer.close()
    await writer.wait_closed()

    c = store.counters()
    assert c["tx_frames"] >= 1   # outbound (client → proxy)
    assert c["rx_frames"] >= 1   # inbound  (echo → client)

    await proxy.stop()
    echo_server.close()
    await echo_server.wait_closed()


@pytest.mark.asyncio
async def test_proxy_server_stop_is_idempotent():
    store = FrameStore(session_id="s1")
    proxy = ProxyServer("127.0.0.1", 65000, store)
    await proxy.start()
    await proxy.stop()
    await proxy.stop()   # second stop must not raise
