# Modbus Diagnostic Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add wire-level frame capture (Raw Traffic Interceptor), structured MBAP/PDU parsing (FrameParser), and poll-interval jitter tracking (JitterMonitor) to the existing Modbus subsystem.

**Architecture:** Three new Python modules (`frame_parser.py`, `interceptor.py`) and one class addition (`JitterMonitor` in `diagnostics.py`) are wired into `ClientSession` via `__post_init__`/`start()`/`stop()`, with three new REST endpoints and one WebSocket endpoint. The frontend gains a Jitter panel and Traffic tab in `ModbusDiagnostics.tsx`.

**Tech Stack:** Python 3.11, pymodbus ≥ 3.6, asyncio, FastAPI WebSocket, React 18, TypeScript, Tailwind CSS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/modbus/frame_parser.py` | CREATE | Pure MBAP/RTU parser — no I/O, no asyncio |
| `backend/modbus/interceptor.py` | CREATE | `FrameStore` ring buffer + JSONL + WS fanout; `InterceptorWrap` asyncio transport patch; `ProxyServer` TCP forwarder |
| `backend/modbus/diagnostics.py` | MODIFY | Add `JitterMonitor` class; extend `DiagnosticsEngine.get_stats()` signature |
| `backend/modbus/client.py` | MODIFY | Add `frame_store`, `_jitter`, interceptor fields to `ClientSession`; wire into `__post_init__`/`start()`/`_connect()`/`_poll_loop()`/`stop()`/`to_dict()` |
| `backend/api/modbus_routes.py` | MODIFY | `CreateClientRequest` + 2 new fields; 3 new endpoints; extended diagnostics call |
| `frontend/src/lib/api.ts` | MODIFY | `ParsedFrame` type; `createModbusTrafficWebSocket()`; `setModbusTrafficLog()` |
| `frontend/src/components/ModbusDiagnostics.tsx` | MODIFY | `JitterPanel` component; Traffic tab in `RegGrid` |
| `backend/tests/test_frame_parser.py` | CREATE | Tests for TCP + RTU parsing |
| `backend/tests/test_interceptor.py` | CREATE | Tests for `FrameStore`, `InterceptorWrap`, `ProxyServer` |
| `backend/tests/test_jitter_monitor.py` | CREATE | Tests for `JitterMonitor` + extended `get_stats()` |

---

## Task 1: `frame_parser.py` — Dataclasses, FC/Exception tables, TCP parser

**Files:**
- Create: `backend/modbus/frame_parser.py`
- Create: `backend/tests/test_frame_parser.py`

Run all tests from the `backend/` directory: `cd C:\Users\ffd\Documents\netscope-desktop\backend`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_frame_parser.py`:

```python
import pytest
from modbus.frame_parser import (
    parse_tcp_frame,
    MBAPHeader,
    ParsedFrame,
    EXCEPTION_NAMES,
    FC_NAMES,
)


# ── helpers ──────────────────────────────────────────────────────────────────

TS = 1_700_000_000_000_000  # fixed µs timestamp for all tests

# FC3 Read Holding Registers request: TID=1, UID=1, start=0x006C, count=10
TCP_FC3_REQ = bytes([
    0x00, 0x01,  # TID
    0x00, 0x00,  # PID
    0x00, 0x06,  # LEN = 6
    0x01,        # Unit ID
    0x03,        # FC3
    0x00, 0x6C,  # start address = 108
    0x00, 0x0A,  # count = 10
])

# FC3 response: 4 registers (8 bytes data)
TCP_FC3_RESP = bytes([
    0x00, 0x01,  # TID
    0x00, 0x00,  # PID
    0x00, 0x0B,  # LEN = 11
    0x01,        # Unit ID
    0x03,        # FC3
    0x08,        # byte count = 8
    0x00, 0x64, 0x01, 0x2C, 0x00, 0x00, 0xFF, 0xFF,  # 4 registers
])

# FC3 exception response (EC 0x02 = Illegal Data Address)
TCP_FC3_EXC = bytes([
    0x00, 0x01,  # TID
    0x00, 0x00,  # PID
    0x00, 0x03,  # LEN = 3
    0x01,        # Unit ID
    0x83,        # FC3 | 0x80
    0x02,        # exception code
])

# Truncated frame (only MBAP header, no PDU)
TCP_TRUNCATED = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x01])

# Wrong protocol ID
TCP_BAD_PID = bytes([
    0x00, 0x01, 0x00, 0x01, 0x00, 0x06,
    0x01, 0x03, 0x00, 0x00, 0x00, 0x01,
])


# ── TCP tests ─────────────────────────────────────────────────────────────────

def test_parse_tcp_fc3_request_mbap():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.mbap is not None
    assert f.mbap.transaction_id == 1
    assert f.mbap.protocol_id == 0
    assert f.mbap.length == 6
    assert f.mbap.unit_id == 1


def test_parse_tcp_fc3_request_pdu():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.function_code == 3
    assert f.fc_name == "Read Holding Registers"
    assert f.is_exception is False
    assert f.exception_code is None
    assert f.start_address == 0x6C
    assert f.quantity == 10
    assert f.crc_valid is None
    assert f.parse_error is None


def test_parse_tcp_fc3_response():
    f = parse_tcp_frame(TCP_FC3_RESP, "rx", TS)
    assert f.function_code == 3
    assert f.is_exception is False
    assert f.byte_count == 8
    assert f.data_hex is not None
    assert len(f.data_hex) == 16  # 8 bytes → 16 hex chars (no spaces)
    assert f.parse_error is None


def test_parse_tcp_exception_response():
    f = parse_tcp_frame(TCP_FC3_EXC, "rx", TS)
    assert f.is_exception is True
    assert f.function_code == 3        # stripped high bit
    assert f.exception_code == 0x02
    assert f.exception_name == "Illegal Data Address"
    assert f.parse_error is None


def test_parse_tcp_truncated_frame():
    f = parse_tcp_frame(TCP_TRUNCATED, "tx", TS)
    assert f.parse_error is not None
    assert "truncated" in f.parse_error.lower()


def test_parse_tcp_bad_protocol_id():
    f = parse_tcp_frame(TCP_BAD_PID, "tx", TS)
    assert f.parse_error is not None
    assert "protocol" in f.parse_error.lower()


def test_parse_tcp_direction_and_timestamp():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.direction == "tx"
    assert f.ts_us == TS
    assert f.frame_type == "tcp"


def test_parse_tcp_raw_hex_is_full_frame():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.raw_hex == TCP_FC3_REQ.hex()


def test_exception_names_table():
    assert EXCEPTION_NAMES[0x01] == "Illegal Function"
    assert EXCEPTION_NAMES[0x02] == "Illegal Data Address"
    assert EXCEPTION_NAMES[0x0B] == "Gateway Target Device Failed to Respond"


def test_fc_names_table():
    assert FC_NAMES[1] == "Read Coils"
    assert FC_NAMES[3] == "Read Holding Registers"
    assert FC_NAMES[16] == "Write Multiple Registers"
    assert "Unknown" in FC_NAMES.get(99, "FC99 (Unknown)")


def test_unknown_fc_name():
    raw = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x04, 0x01, 0x63, 0x00, 0x01])
    f = parse_tcp_frame(raw, "tx", TS)
    assert "Unknown" in f.fc_name or f.fc_name.startswith("FC")
```

- [ ] **Step 2: Run tests to confirm they all fail**

```
cd C:\Users\ffd\Documents\netscope-desktop\backend
python -m pytest tests/test_frame_parser.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'modbus.frame_parser'`

- [ ] **Step 3: Implement `frame_parser.py`**

Create `backend/modbus/frame_parser.py`:

```python
"""
Modbus frame parser — pure module, no I/O, no asyncio.

Two public functions:
  parse_tcp_frame(raw, direction, ts_us) -> ParsedFrame
  parse_rtu_frame(raw, direction, ts_us) -> ParsedFrame
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ── Tables ────────────────────────────────────────────────────────────────────

EXCEPTION_NAMES: dict[int, str] = {
    0x01: "Illegal Function",
    0x02: "Illegal Data Address",
    0x03: "Illegal Data Value",
    0x04: "Server Device Failure",
    0x05: "Acknowledge",
    0x06: "Server Device Busy",
    0x08: "Memory Parity Error",
    0x0A: "Gateway Path Unavailable",
    0x0B: "Gateway Target Device Failed to Respond",
}

FC_NAMES: dict[int, str] = {
    1:  "Read Coils",
    2:  "Read Discrete Inputs",
    3:  "Read Holding Registers",
    4:  "Read Input Registers",
    5:  "Write Single Coil",
    6:  "Write Single Register",
    7:  "Read Exception Status",
    8:  "Diagnostics",
    11: "Get Comm Event Counter",
    12: "Get Comm Event Log",
    15: "Write Multiple Coils",
    16: "Write Multiple Registers",
    17: "Report Server ID",
    20: "Read File Record",
    21: "Write File Record",
    22: "Mask Write Register",
    23: "Read/Write Multiple Registers",
    43: "Read Device Identification",
}


def _fc_name(fc: int) -> str:
    return FC_NAMES.get(fc, f"FC{fc} (Unknown)")


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class MBAPHeader:
    transaction_id: int
    protocol_id: int
    length: int
    unit_id: int


@dataclass
class ParsedFrame:
    direction: Literal["tx", "rx"]
    ts_us: int
    frame_type: Literal["tcp", "rtu"]
    raw_hex: str

    mbap: MBAPHeader | None

    function_code: int
    fc_name: str
    is_exception: bool
    exception_code: int | None
    exception_name: str | None

    start_address: int | None
    quantity: int | None

    byte_count: int | None
    data_hex: str | None

    crc_valid: bool | None

    parse_error: str | None


def _error_frame(
    raw: bytes,
    direction: str,
    ts_us: int,
    frame_type: Literal["tcp", "rtu"],
    error: str,
) -> ParsedFrame:
    """Return a ParsedFrame with parse_error set; all other fields zeroed."""
    return ParsedFrame(
        direction=direction,
        ts_us=ts_us,
        frame_type=frame_type,
        raw_hex=raw.hex(),
        mbap=None,
        function_code=0,
        fc_name="",
        is_exception=False,
        exception_code=None,
        exception_name=None,
        start_address=None,
        quantity=None,
        byte_count=None,
        data_hex=None,
        crc_valid=None,
        parse_error=error,
    )


# ── TCP parser ────────────────────────────────────────────────────────────────

_TCP_MIN_LEN = 8  # 6 MBAP + 1 FC + at least 1 data byte


def parse_tcp_frame(raw: bytes, direction: str, ts_us: int) -> ParsedFrame:
    """Parse a Modbus TCP (MBAP + PDU) frame into a ParsedFrame."""
    if len(raw) < _TCP_MIN_LEN:
        return _error_frame(raw, direction, ts_us, "tcp",
                            f"truncated: {len(raw)} < {_TCP_MIN_LEN} bytes")

    tid  = (raw[0] << 8) | raw[1]
    pid  = (raw[2] << 8) | raw[3]
    plen = (raw[4] << 8) | raw[5]   # PDU length including unit_id
    uid  = raw[6]

    if pid != 0:
        return _error_frame(raw, direction, ts_us, "tcp",
                            f"protocol_id {pid:#06x} != 0x0000 (not Modbus TCP)")

    mbap = MBAPHeader(transaction_id=tid, protocol_id=pid, length=plen, unit_id=uid)

    # PDU starts at byte 7
    if len(raw) < 7:
        return _error_frame(raw, direction, ts_us, "tcp", "truncated: missing PDU")

    fc_raw = raw[7]
    is_exc = bool(fc_raw & 0x80)
    fc = fc_raw & 0x7F if is_exc else fc_raw

    exc_code: int | None = None
    exc_name: str | None = None
    start_addr: int | None = None
    quantity: int | None = None
    byte_count: int | None = None
    data_hex: str | None = None
    parse_error: str | None = None

    pdu = raw[7:]   # FC byte + data

    if is_exc:
        if len(pdu) < 2:
            parse_error = "truncated: exception frame missing exception code"
        else:
            exc_code = pdu[1]
            exc_name = EXCEPTION_NAMES.get(exc_code, f"Unknown exception {exc_code:#04x}")
    else:
        # Parse request context (tx): FC + start + count
        if direction == "tx" and len(pdu) >= 5:
            start_addr = (pdu[1] << 8) | pdu[2]
            quantity   = (pdu[3] << 8) | pdu[4]
        # Parse response context (rx): FC + byte_count + data
        elif direction == "rx" and len(pdu) >= 2 and fc in (1, 2, 3, 4):
            byte_count = pdu[1]
            data_bytes = pdu[2:2 + byte_count]
            if len(data_bytes) < byte_count:
                parse_error = (
                    f"truncated: expected {byte_count} data bytes, "
                    f"got {len(data_bytes)}"
                )
            data_hex = data_bytes.hex()

    return ParsedFrame(
        direction=direction,
        ts_us=ts_us,
        frame_type="tcp",
        raw_hex=raw.hex(),
        mbap=mbap,
        function_code=fc,
        fc_name=_fc_name(fc),
        is_exception=is_exc,
        exception_code=exc_code,
        exception_name=exc_name,
        start_address=start_addr,
        quantity=quantity,
        byte_count=byte_count,
        data_hex=data_hex,
        crc_valid=None,
        parse_error=parse_error,
    )
```

*(RTU parser added in Task 2)*

- [ ] **Step 4: Run TCP tests — all should pass**

```
python -m pytest tests/test_frame_parser.py -v -k "not rtu"
```

Expected: all `test_parse_tcp_*`, `test_exception_names_table`, `test_fc_names_table`, `test_unknown_fc_name` pass.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/frame_parser.py backend/tests/test_frame_parser.py
git commit -m "feat(modbus): add frame_parser TCP parser + tests"
```

---

## Task 2: `frame_parser.py` — RTU parser + CRC validation

**Files:**
- Modify: `backend/modbus/frame_parser.py` (add `parse_rtu_frame` + `_crc16`)
- Modify: `backend/tests/test_frame_parser.py` (add RTU tests)

- [ ] **Step 1: Add RTU test cases to `test_frame_parser.py`**

Append to `backend/tests/test_frame_parser.py`:

```python
from modbus.frame_parser import parse_rtu_frame


# ── RTU helpers ───────────────────────────────────────────────────────────────

def _crc16(data: bytes) -> bytes:
    """CRC-16/IBM — returns 2 bytes little-endian."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def _rtu(body: bytes) -> bytes:
    """Append a valid CRC to a RTU frame body."""
    return body + _crc16(body)


# FC3 request: UID=1, FC=3, start=0, count=2
RTU_FC3_REQ = _rtu(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02]))

# FC3 response: UID=1, FC=3, 4 bytes data (2 regs)
RTU_FC3_RESP = _rtu(bytes([0x01, 0x03, 0x04, 0x00, 0x64, 0x01, 0x2C]))

# FC3 exception: UID=1, FC=0x83, EC=0x02
RTU_FC3_EXC = _rtu(bytes([0x01, 0x83, 0x02]))

# Bad CRC: valid body but wrong CRC bytes
RTU_BAD_CRC = _rtu(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02]))[:-2] + bytes([0xDE, 0xAD])


# ── RTU tests ─────────────────────────────────────────────────────────────────

def test_parse_rtu_fc3_request():
    f = parse_rtu_frame(RTU_FC3_REQ, "tx", TS)
    assert f.function_code == 3
    assert f.fc_name == "Read Holding Registers"
    assert f.start_address == 0
    assert f.quantity == 2
    assert f.crc_valid is True
    assert f.is_exception is False
    assert f.frame_type == "rtu"
    assert f.mbap is None
    assert f.parse_error is None


def test_parse_rtu_fc3_response():
    f = parse_rtu_frame(RTU_FC3_RESP, "rx", TS)
    assert f.function_code == 3
    assert f.byte_count == 4
    assert f.data_hex == "0064012c"
    assert f.crc_valid is True
    assert f.parse_error is None


def test_parse_rtu_exception():
    f = parse_rtu_frame(RTU_FC3_EXC, "rx", TS)
    assert f.is_exception is True
    assert f.function_code == 3
    assert f.exception_code == 0x02
    assert f.exception_name == "Illegal Data Address"
    assert f.crc_valid is True


def test_parse_rtu_bad_crc():
    f = parse_rtu_frame(RTU_BAD_CRC, "tx", TS)
    assert f.crc_valid is False
    assert f.parse_error is not None
    assert "crc" in f.parse_error.lower()


def test_parse_rtu_truncated():
    f = parse_rtu_frame(bytes([0x01]), "tx", TS)
    assert f.parse_error is not None
    assert "truncated" in f.parse_error.lower()


def test_parse_rtu_raw_hex_includes_crc():
    f = parse_rtu_frame(RTU_FC3_REQ, "tx", TS)
    assert f.raw_hex == RTU_FC3_REQ.hex()
```

- [ ] **Step 2: Run to confirm RTU tests fail**

```
python -m pytest tests/test_frame_parser.py -v -k "rtu"
```

Expected: `ImportError` — `parse_rtu_frame` not yet defined.

- [ ] **Step 3: Add `_crc16` and `parse_rtu_frame` to `frame_parser.py`**

Append to `backend/modbus/frame_parser.py` (after the existing `parse_tcp_frame` function):

```python
# ── RTU CRC ───────────────────────────────────────────────────────────────────

def _crc16(data: bytes) -> int:
    """CRC-16/IBM (polynomial 0xA001) over the given bytes. Returns uint16."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


# ── RTU parser ────────────────────────────────────────────────────────────────

_RTU_MIN_LEN = 4  # UID + FC + at least 1 data byte + 2 CRC = 5; accept 4 for edge frames


def parse_rtu_frame(raw: bytes, direction: str, ts_us: int) -> ParsedFrame:
    """Parse a Modbus RTU (serial) frame into a ParsedFrame."""
    if len(raw) < _RTU_MIN_LEN:
        return _error_frame(raw, direction, ts_us, "rtu",
                            f"truncated: {len(raw)} < {_RTU_MIN_LEN} bytes")

    # CRC is the last 2 bytes, little-endian
    payload   = raw[:-2]
    crc_given = (raw[-1] << 8) | raw[-2]   # little-endian: lo byte first
    crc_calc  = _crc16(payload)
    crc_ok    = crc_given == crc_calc

    uid    = raw[0]
    fc_raw = raw[1]
    is_exc = bool(fc_raw & 0x80)
    fc     = fc_raw & 0x7F if is_exc else fc_raw

    exc_code: int | None = None
    exc_name: int | None = None
    start_addr: int | None = None
    quantity: int | None = None
    byte_count: int | None = None
    data_hex: str | None = None
    parse_error: str | None = None

    if not crc_ok:
        parse_error = f"crc mismatch: expected {crc_calc:#06x}, got {crc_given:#06x}"

    pdu = raw[1:-2]   # FC + data, without UID and CRC

    if is_exc:
        if len(pdu) >= 2:
            exc_code = pdu[1]
            exc_name = EXCEPTION_NAMES.get(exc_code, f"Unknown exception {exc_code:#04x}")
    else:
        if direction == "tx" and len(pdu) >= 5:
            start_addr = (pdu[1] << 8) | pdu[2]
            quantity   = (pdu[3] << 8) | pdu[4]
        elif direction == "rx" and len(pdu) >= 2 and fc in (1, 2, 3, 4):
            byte_count = pdu[1]
            data_bytes = pdu[2:2 + byte_count]
            data_hex   = data_bytes.hex()

    return ParsedFrame(
        direction=direction,
        ts_us=ts_us,
        frame_type="rtu",
        raw_hex=raw.hex(),
        mbap=None,
        function_code=fc,
        fc_name=_fc_name(fc),
        is_exception=is_exc,
        exception_code=exc_code,
        exception_name=exc_name,
        start_address=start_addr,
        quantity=quantity,
        byte_count=byte_count,
        data_hex=data_hex,
        crc_valid=crc_ok,
        parse_error=parse_error,
    )
```

- [ ] **Step 4: Run all frame_parser tests — all should pass**

```
python -m pytest tests/test_frame_parser.py -v
```

Expected: All tests pass. If `test_parse_rtu_exception` fails due to `exc_name` type annotation (`int | None` was used — should be `str | None`), fix the type annotation in `parse_rtu_frame`: change `exc_name: int | None = None` to `exc_name: str | None = None`.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/frame_parser.py backend/tests/test_frame_parser.py
git commit -m "feat(modbus): add RTU frame parser with CRC-16 validation"
```

---

## Task 3: `interceptor.py` — `FrameStore`

**Files:**
- Create: `backend/modbus/interceptor.py`
- Create: `backend/tests/test_interceptor.py`

- [ ] **Step 1: Write failing tests for `FrameStore`**

Create `backend/tests/test_interceptor.py`:

```python
import asyncio
import dataclasses
import json
import time
from pathlib import Path
import tempfile
import pytest

from modbus.frame_parser import ParsedFrame, MBAPHeader
from modbus.interceptor import FrameStore


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
```

- [ ] **Step 2: Run to confirm tests fail**

```
python -m pytest tests/test_interceptor.py -v
```

Expected: `ModuleNotFoundError: No module named 'modbus.interceptor'`

- [ ] **Step 3: Create `interceptor.py` with `FrameStore`**

Create `backend/modbus/interceptor.py`:

```python
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
```

- [ ] **Step 4: Run FrameStore tests — install pytest-asyncio if needed**

```
pip install pytest-asyncio
python -m pytest tests/test_interceptor.py -v
```

If you see `PytestUnraisableExceptionWarning` about missing `asyncio_mode`, add to `backend/pytest.ini` (or `pyproject.toml`):
```ini
[pytest]
asyncio_mode = auto
```

Expected: All 6 FrameStore tests pass.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/interceptor.py backend/tests/test_interceptor.py
git commit -m "feat(modbus): add FrameStore with ring buffer, JSONL log, WS fanout"
```

---

## Task 4: `interceptor.py` — `InterceptorWrap`

**Files:**
- Modify: `backend/modbus/interceptor.py` (append `InterceptorWrap` class)
- Modify: `backend/tests/test_interceptor.py` (append wrap tests)

- [ ] **Step 1: Add `InterceptorWrap` tests to `test_interceptor.py`**

Append to `backend/tests/test_interceptor.py`:

```python
from modbus.interceptor import InterceptorWrap
import unittest.mock as mock


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

    original_write = client.transport.write
    original_data  = client.protocol.data_received

    wrap.attach(client, store, "tcp")
    assert client.transport.write is not original_write  # patched

    wrap.detach(client)
    assert client.transport.write is original_write      # restored
    assert client.protocol.data_received is original_data


@pytest.mark.asyncio
async def test_interceptor_wrap_missing_transport_is_noop():
    """attach() should not raise if pymodbus transport is missing."""
    store  = FrameStore(session_id="s1")
    client = object()   # has neither transport nor protocol
    wrap   = InterceptorWrap()
    wrap.attach(client, store, "tcp")   # must not raise
    # nothing was captured — no crash
    assert store.counters()["total"] == 0
```

- [ ] **Step 2: Run to confirm new tests fail**

```
python -m pytest tests/test_interceptor.py -v -k "wrap"
```

Expected: `ImportError` or `AttributeError` — `InterceptorWrap` not defined.

- [ ] **Step 3: Append `InterceptorWrap` to `interceptor.py`**

Append to `backend/modbus/interceptor.py`:

```python
# ── InterceptorWrap ───────────────────────────────────────────────────────────

class InterceptorWrap:
    """
    Patches a live pymodbus client's asyncio transport in-place after connect().

    Works for both AsyncModbusTcpClient and AsyncModbusSerialClient (pymodbus ≥ 3.6),
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
                asyncio.get_event_loop().create_task(
                    store.ingest(parser(data, "tx", ts))
                )
            except Exception as exc:
                logger.debug("InterceptorWrap write log error: %s", exc)
            orig_write(data)

        def _patched_data_received(data: bytes) -> None:
            ts = time.time_ns() // 1000
            try:
                asyncio.get_event_loop().create_task(
                    store.ingest(parser(data, "rx", ts))
                )
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
```

- [ ] **Step 4: Run all interceptor tests**

```
python -m pytest tests/test_interceptor.py -v
```

Expected: All tests pass (FrameStore tests + InterceptorWrap tests).

- [ ] **Step 5: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/interceptor.py backend/tests/test_interceptor.py
git commit -m "feat(modbus): add InterceptorWrap asyncio transport patcher"
```

---

## Task 5: `interceptor.py` — `ProxyServer`

**Files:**
- Modify: `backend/modbus/interceptor.py` (append `ProxyServer`)
- Modify: `backend/tests/test_interceptor.py` (append proxy tests)

- [ ] **Step 1: Add ProxyServer tests to `test_interceptor.py`**

Append to `backend/tests/test_interceptor.py`:

```python
from modbus.interceptor import ProxyServer


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
    async def _echo(reader: StreamReader, writer: StreamWriter) -> None:
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
    writer.close()

    await asyncio.sleep(0.1)  # let ingest tasks complete

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
```

- [ ] **Step 2: Run to confirm proxy tests fail**

```
python -m pytest tests/test_interceptor.py -v -k "proxy"
```

Expected: `ImportError` — `ProxyServer` not yet defined.

- [ ] **Step 3: Append `ProxyServer` to `interceptor.py`**

Append to `backend/modbus/interceptor.py`:

```python
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

        try:
            await asyncio.gather(
                self._pipe(client_reader, dev_writer,    "tx"),
                self._pipe(dev_reader,    client_writer, "rx"),
            )
        except Exception:
            pass
        finally:
            for w in (client_writer, dev_writer):
                try:
                    w.close()
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
            except Exception:
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
```

- [ ] **Step 4: Run all interceptor tests**

```
python -m pytest tests/test_interceptor.py -v
```

Expected: All tests pass (FrameStore + InterceptorWrap + ProxyServer).

- [ ] **Step 5: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/interceptor.py backend/tests/test_interceptor.py
git commit -m "feat(modbus): add ProxyServer transparent TCP forwarder"
```

---

## Task 6: `JitterMonitor` + extended `DiagnosticsEngine.get_stats()`

**Files:**
- Modify: `backend/modbus/diagnostics.py`
- Create: `backend/tests/test_jitter_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_jitter_monitor.py`:

```python
import dataclasses
import time
import pytest
from modbus.diagnostics import JitterMonitor, DiagnosticsEngine
from modbus.interceptor import FrameStore
from modbus.frame_parser import ParsedFrame, MBAPHeader


# ── JitterMonitor unit tests ──────────────────────────────────────────────────

def test_jitter_monitor_empty_returns_zero_samples():
    jm = JitterMonitor(target_interval_ms=1000.0)
    s = jm.stats()
    assert s["samples"] == 0
    assert s["target_ms"] == 1000.0


def test_jitter_monitor_one_tick_returns_zero_samples():
    jm = JitterMonitor(target_interval_ms=1000.0)
    jm.tick()
    s = jm.stats()
    assert s["samples"] == 0  # need 2 ticks for one interval


def test_jitter_monitor_two_ticks_records_one_interval():
    jm = JitterMonitor(target_interval_ms=100.0)
    jm._last_ns = time.time_ns() - 120_000_000  # simulate 120ms ago
    jm.tick()
    s = jm.stats()
    assert s["samples"] == 1
    assert 100.0 < s["mean_ms"] < 200.0  # rough sanity


def test_jitter_monitor_stats_keys():
    jm = JitterMonitor(target_interval_ms=500.0)
    # Inject 10 synthetic intervals: 490, 495, 500, 505, 510 × 2 each
    for ms in [490, 495, 500, 505, 510, 490, 495, 500, 505, 510]:
        jm._intervals.append(float(ms))

    s = jm.stats()
    assert set(s.keys()) >= {
        "target_ms", "samples", "mean_ms", "std_dev_ms",
        "min_ms", "max_ms", "p50_jitter_ms", "p95_jitter_ms", "timeline_ms",
    }
    assert s["min_ms"] == 490.0
    assert s["max_ms"] == 510.0
    assert s["samples"] == 10


def test_jitter_monitor_p50_jitter_is_deviation_not_raw_interval():
    jm = JitterMonitor(target_interval_ms=1000.0)
    # All intervals are 1010ms — deviation is always 10ms
    for _ in range(20):
        jm._intervals.append(1010.0)
    s = jm.stats()
    assert s["p50_jitter_ms"] == pytest.approx(10.0, abs=0.1)
    assert s["p95_jitter_ms"] == pytest.approx(10.0, abs=0.1)


def test_jitter_monitor_timeline_ms_capped_at_60():
    jm = JitterMonitor(target_interval_ms=100.0)
    for i in range(100):
        jm._intervals.append(float(100 + i))
    s = jm.stats()
    assert len(s["timeline_ms"]) == 60


def test_jitter_monitor_window_cap():
    jm = JitterMonitor(target_interval_ms=100.0, window=5)
    for i in range(10):
        jm._intervals.append(float(100 + i))
    assert len(jm._intervals) == 5  # deque capped


# ── DiagnosticsEngine.get_stats() extension tests ────────────────────────────

def _make_frame(direction: str = "tx") -> ParsedFrame:
    return ParsedFrame(
        direction=direction, ts_us=0, frame_type="tcp",
        raw_hex="", mbap=None, function_code=3,
        fc_name="Read Holding Registers", is_exception=False,
        exception_code=None, exception_name=None,
        start_address=None, quantity=None, byte_count=None,
        data_hex=None, crc_valid=None, parse_error=None,
    )


@pytest.mark.asyncio
async def test_get_stats_includes_jitter_when_provided():
    eng = DiagnosticsEngine()
    jm  = JitterMonitor(target_interval_ms=1000.0)
    for _ in range(5):
        jm._intervals.append(1005.0)

    stats = eng.get_stats("nonexistent", jitter_monitor=jm)
    assert "jitter" in stats
    assert stats["jitter"]["target_ms"] == 1000.0
    assert stats["jitter"]["samples"] == 5


@pytest.mark.asyncio
async def test_get_stats_includes_traffic_when_provided():
    eng   = DiagnosticsEngine()
    store = FrameStore(session_id="s1")
    await store.ingest(_make_frame("tx"))
    await store.ingest(_make_frame("rx"))

    stats = eng.get_stats("nonexistent", frame_store=store)
    assert "traffic" in stats
    assert stats["traffic"]["tx_frames"] == 1
    assert stats["traffic"]["rx_frames"] == 1
    assert len(stats["traffic"]["recent"]) == 2


def test_get_stats_without_optionals_unchanged():
    """Existing callers with only session_id still work."""
    eng = DiagnosticsEngine()
    eng.record("s1", fc=3, addr=40001, rtt_ms=10.0, status="ok", response=[100])
    stats = eng.get_stats("s1")
    assert "jitter"  not in stats
    assert "traffic" not in stats
    assert stats["rtt"]["avg"] == pytest.approx(10.0, abs=0.1)
```

- [ ] **Step 2: Run to confirm tests fail**

```
python -m pytest tests/test_jitter_monitor.py -v
```

Expected: `ImportError: cannot import name 'JitterMonitor' from 'modbus.diagnostics'`

- [ ] **Step 3: Add `JitterMonitor` class to `diagnostics.py`**

Add at the top of `backend/modbus/diagnostics.py`, after the existing imports:

```python
import statistics  # already imported; this is a reminder
```

Append at the bottom of `backend/modbus/diagnostics.py`, before the `diagnostics_engine = DiagnosticsEngine()` singleton line:

```python
# ── JitterMonitor ─────────────────────────────────────────────────────────────

@dataclass
class JitterMonitor:
    """
    Tracks poll-start-to-poll-start interval deviation from a configured target.
    Call tick() at the top of every poll cycle, before any I/O.
    """
    target_interval_ms: float
    window: int = 300

    def __post_init__(self):
        self._intervals: deque = deque(maxlen=self.window)
        self._last_ns: int | None = None

    def tick(self) -> None:
        now = time.time_ns()
        if self._last_ns is not None:
            elapsed_ms = (now - self._last_ns) / 1_000_000
            self._intervals.append(elapsed_ms)
        self._last_ns = now

    def stats(self) -> dict:
        if len(self._intervals) < 2:
            return {"target_ms": self.target_interval_ms, "samples": len(self._intervals)}
        iv = list(self._intervals)
        devs = sorted(abs(x - self.target_interval_ms) for x in iv)
        n = len(devs)
        return {
            "target_ms":      self.target_interval_ms,
            "samples":        n,
            "mean_ms":        round(statistics.mean(iv), 3),
            "std_dev_ms":     round(statistics.stdev(iv), 3),
            "min_ms":         round(min(iv), 3),
            "max_ms":         round(max(iv), 3),
            "p50_jitter_ms":  round(devs[n // 2], 3),
            "p95_jitter_ms":  round(devs[int(n * 0.95)], 3),
            "timeline_ms":    [round(x, 3) for x in iv[-60:]],
        }
```

- [ ] **Step 4: Extend `DiagnosticsEngine.get_stats()` signature**

In `backend/modbus/diagnostics.py`, replace the `get_stats` signature line:

```python
    def get_stats(self, session_id: str) -> dict:
```

with:

```python
    def get_stats(
        self,
        session_id: str,
        jitter_monitor: "JitterMonitor | None" = None,
        frame_store: "Any" = None,
    ) -> dict:
```

Then, before the `return` statement at the end of `get_stats`, add:

```python
        result = {
            "rtt": {"avg": round(avg, 2), "p50": round(p50, 2), "p95": round(p95, 2), "p99": round(p99, 2)},
            "exceptions": exc_list,
            "heatmap": heatmap,
            "timeline": timeline,
            "transactions": txns,
            "req_rate": req_rate,
            "total_polls": total_polls,
        }
        if jitter_monitor is not None:
            result["jitter"] = jitter_monitor.stats()
        if frame_store is not None:
            import dataclasses as _dc
            result["traffic"] = {
                **frame_store.counters(),
                "recent": [_dc.asdict(f) for f in frame_store.get_recent(10)],
            }
        return result
```

And remove the old bare `return {...}` dict at the end of `get_stats`.

**Note:** The existing `return` statement in `get_stats` is at line 147–155. Replace that entire `return { ... }` block with the `result = { ... }` block above.

- [ ] **Step 5: Run all jitter tests**

```
python -m pytest tests/test_jitter_monitor.py -v
```

Expected: All 11 tests pass.

Also confirm existing diagnostics tests still pass:

```
python -m pytest tests/test_modbus_diagnostics.py -v
```

Expected: All pass (new optional params default to `None`, backward-compatible).

- [ ] **Step 6: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/diagnostics.py backend/tests/test_jitter_monitor.py
git commit -m "feat(modbus): add JitterMonitor + extend DiagnosticsEngine.get_stats()"
```

---

## Task 7: Wire `ClientSession` — new fields + lifecycle hooks

**Files:**
- Modify: `backend/modbus/client.py`

No new tests needed at this stage — the wiring is integration-level and covered by existing tests in `test_modbus_client.py` plus the diagnostic/interceptor tests already written. A smoke-test step below confirms nothing is broken.

- [ ] **Step 1: Add imports to `client.py`**

At the top of `backend/modbus/client.py`, after the existing imports, add:

```python
from pathlib import Path
from typing import Literal
from modbus.interceptor import FrameStore, InterceptorWrap, ProxyServer
from modbus.diagnostics import JitterMonitor
```

- [ ] **Step 2: Add new fields to `ClientSession` dataclass**

In `backend/modbus/client.py`, inside the `ClientSession` dataclass, after the `max_connections: int = 1` line, add:

```python
    # Traffic interceptor config
    interceptor_mode: Literal["none", "wrap", "proxy"] = "wrap"
    traffic_log_path: str | None = None

    # Runtime — not user-configured
    frame_store:        FrameStore         = field(default=None, init=False, repr=False)  # type: ignore[assignment]
    _jitter:            JitterMonitor      = field(default=None, init=False, repr=False)  # type: ignore[assignment]
    _interceptor_wrap:  InterceptorWrap | None = field(default=None, init=False, repr=False)
    _proxy_server:      ProxyServer | None     = field(default=None, init=False, repr=False)
    _proxy_host:        str | None             = field(default=None, init=False, repr=False)
    _proxy_port:        int | None             = field(default=None, init=False, repr=False)
```

- [ ] **Step 3: Initialise `frame_store` and `_jitter` in `__post_init__`**

In `ClientSession.__post_init__`, after `self._connect_lock = asyncio.Lock()`, add:

```python
        self.frame_store = FrameStore(session_id=self.session_id)
        self._jitter     = JitterMonitor(target_interval_ms=self.poll_interval * 1000)
```

- [ ] **Step 4: Update `start()` to launch proxy and file log**

Replace the existing `start()` method:

```python
    async def start(self):
        self.started_at = time.time()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"modbus-client-{self.session_id}",
        )
```

with:

```python
    async def start(self):
        self.started_at = time.time()

        if self.interceptor_mode == "proxy":
            self._proxy_server = ProxyServer(
                self.host, self.port, self.frame_store
            )
            local_port = await self._proxy_server.start()
            self._proxy_host = "127.0.0.1"
            self._proxy_port = local_port

        if self.traffic_log_path:
            self.frame_store.enable_file_log(Path(self.traffic_log_path))

        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"modbus-client-{self.session_id}",
        )
```

- [ ] **Step 5: Update `_connect()` to use proxy address and attach wrap**

In `_connect()`, replace:

```python
                cfg = TransportConfig(
                    transport=self.transport,
                    host=self.host,
                    port=self.port,
```

with:

```python
                _host = self._proxy_host or self.host
                _port = self._proxy_port or self.port
                cfg = TransportConfig(
                    transport=self.transport,
                    host=_host,
                    port=_port,
```

Then, after the block `if not connected: ... return False`, before `return True`, add:

```python
            if self.interceptor_mode == "wrap" and self._interceptor_wrap is None:
                frame_type = "rtu" if self.transport in ("rtu", "ascii") else "tcp"
                self._interceptor_wrap = InterceptorWrap()
                self._interceptor_wrap.attach(self._client, self.frame_store, frame_type)
```

- [ ] **Step 6: Update `_poll_loop()` to tick jitter**

In `_poll_loop()`, replace:

```python
    async def _poll_loop(self):
        self.status = "connecting"
        while True:
            try:
                result = await self._poll_once()
```

with:

```python
    async def _poll_loop(self):
        self.status = "connecting"
        while True:
            self._jitter.tick()
            try:
                result = await self._poll_once()
```

- [ ] **Step 7: Update `stop()` to clean up interceptor and proxy**

In `stop()`, after `self._client = None`, add:

```python
        if self._interceptor_wrap is not None:
            try:
                self._interceptor_wrap.detach(self._client)
            except Exception:
                pass
            self._interceptor_wrap = None
        if self._proxy_server is not None:
            await self._proxy_server.stop()
            self._proxy_server = None
        self.frame_store.disable_file_log()
```

- [ ] **Step 8: Update `to_dict()` to include new fields**

In `to_dict()`, add after the last existing key-value pair (before the closing `}`):

```python
            "interceptor_mode": self.interceptor_mode,
            "traffic_log_path": self.traffic_log_path,
            "traffic":          self.frame_store.counters(),
```

- [ ] **Step 9: Run existing client tests to confirm nothing is broken**

```
python -m pytest tests/test_modbus_client.py tests/test_modbus_routes.py -v
```

Expected: All previously-passing tests still pass.

- [ ] **Step 10: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/modbus/client.py
git commit -m "feat(modbus): wire FrameStore + JitterMonitor + InterceptorWrap into ClientSession"
```

---

## Task 8: `modbus_routes.py` — new endpoints + wiring

**Files:**
- Modify: `backend/api/modbus_routes.py`

- [ ] **Step 1: Add `interceptor_mode` and `traffic_log_path` to `CreateClientRequest`**

In `backend/api/modbus_routes.py`, in the `CreateClientRequest` class, after `max_connections: int = 1`, add:

```python
    interceptor_mode: Literal["none", "wrap", "proxy"] = "wrap"
    traffic_log_path: str | None = None
```

Add `from typing import Literal` to the top-level imports if not already present.

- [ ] **Step 2: Thread new fields through the `POST /modbus/client/create` handler**

Find the `create_session(...)` call in the client create handler (around line 360–382 in the existing file). Add these two kwargs to the `create_session(...)` call:

```python
        interceptor_mode=req.interceptor_mode,
        traffic_log_path=req.traffic_log_path,
```

Also update `ClientManager.create_session()` in `client.py` to accept and forward these two params (same pattern as existing params):

In `backend/modbus/client.py`, in `ClientManager.create_session()`, add after `max_connections: int = 1,`:

```python
        interceptor_mode: Literal["none", "wrap", "proxy"] = "wrap",
        traffic_log_path: str | None = None,
```

And in the `ClientSession(...)` constructor call inside `create_session()`, add:

```python
            interceptor_mode=interceptor_mode,
            traffic_log_path=traffic_log_path,
```

- [ ] **Step 3: Update `PATCH /modbus/client/{session_id}` to propagate `poll_interval` to jitter monitor**

Find the `PATCH /client/{session_id}` handler. After `session.poll_interval = req.poll_interval`, add:

```python
        session._jitter.target_interval_ms = req.poll_interval * 1000
```

- [ ] **Step 4: Add `TrafficLogConfig` Pydantic model and three new endpoints**

In `backend/api/modbus_routes.py`, add the new Pydantic model and endpoints after the existing diagnostics endpoint:

```python
# ── Traffic interceptor endpoints ─────────────────────────────────────────────

class TrafficLogConfig(BaseModel):
    enabled: bool
    path: str | None = None


@router.websocket("/client/{session_id}/traffic/ws")
async def modbus_traffic_ws(ws: WebSocket, session_id: str):
    """Stream raw captured frames to a WebSocket subscriber."""
    session = client_manager.get_session(session_id)
    if session is None:
        await ws.close(code=4004)
        return
    await ws.accept()
    await session.frame_store.add_ws(ws)
    try:
        while True:
            await ws.receive_text()     # keepalive only — client sends pings
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await session.frame_store.remove_ws(ws)


@router.post("/client/{session_id}/traffic/log")
async def set_traffic_log(session_id: str, body: TrafficLogConfig):
    """Enable or disable JSONL file logging for a client session."""
    session = client_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.enabled and body.path:
        session.frame_store.enable_file_log(Path(body.path))
    else:
        session.frame_store.disable_file_log()
    return {"ok": True}


@router.get("/client/{session_id}/traffic")
async def get_traffic(session_id: str, n: int = 100):
    """Return the most recent N captured frames from a client session."""
    import dataclasses
    session = client_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "frames": [dataclasses.asdict(f) for f in session.frame_store.get_recent(n)],
        **session.frame_store.counters(),
    }
```

Add `from pathlib import Path` to the imports at the top of `modbus_routes.py` if not already present.

- [ ] **Step 5: Update `GET /modbus/diagnostics/{session_id}` to pass jitter + frame_store**

Replace the existing diagnostics handler:

```python
@router.get("/diagnostics/{session_id}")
async def get_diagnostics(session_id: str):
    """Returns DiagnosticsEngine stats for a session."""
    from modbus.diagnostics import diagnostics_engine
    stats = diagnostics_engine.get_stats(session_id)
    return stats
```

with:

```python
@router.get("/diagnostics/{session_id}")
async def get_diagnostics(session_id: str):
    """Returns DiagnosticsEngine stats + jitter + traffic for a session."""
    from modbus.diagnostics import diagnostics_engine
    session = client_manager.get_session(session_id)
    jitter      = getattr(session, "_jitter",     None) if session else None
    frame_store = getattr(session, "frame_store", None) if session else None
    stats = diagnostics_engine.get_stats(
        session_id,
        jitter_monitor=jitter,
        frame_store=frame_store,
    )
    return stats
```

- [ ] **Step 6: Run the backend test suite**

```
python -m pytest tests/ -v --tb=short
```

Expected: All existing tests pass, no new failures. The three new endpoint tests don't exist yet — that's fine.

- [ ] **Step 7: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add backend/api/modbus_routes.py backend/modbus/client.py
git commit -m "feat(modbus): add traffic interceptor endpoints + extended diagnostics"
```

---

## Task 9: Frontend `api.ts` — `ParsedFrame` type + two new functions

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add `ParsedFrame` interface and `createModbusTrafficWebSocket`**

In `frontend/src/lib/api.ts`, directly after the `createModbusLiveWebSocket` function (around line 1211), insert:

```typescript
// ── Modbus Traffic WebSocket ──────────────────────────────────────────────────

export interface ParsedFrame {
  direction: "tx" | "rx"
  ts_us: number
  frame_type: "tcp" | "rtu"
  raw_hex: string
  mbap?: {
    transaction_id: number
    protocol_id: number
    length: number
    unit_id: number
  }
  function_code: number
  fc_name: string
  is_exception: boolean
  exception_code?: number
  exception_name?: string
  start_address?: number
  quantity?: number
  byte_count?: number
  data_hex?: string
  crc_valid?: boolean
  parse_error?: string
}

export function createModbusTrafficWebSocket(
  sessionId: string,
  onFrame: (frame: ParsedFrame) => void,
  onGiveUp?: () => void,
): () => void {
  return createReconnectingWebSocket(
    `${resolveWSBase()}/api/modbus/client/${encodeURIComponent(sessionId)}/traffic/ws`,
    (_socket: WebSocket) => {
      // no handshake needed — server pushes frames immediately
    },
    (ev: MessageEvent) => {
      try {
        const frame = JSON.parse(ev.data) as ParsedFrame;
        onFrame(frame);
      } catch {}
    },
    onGiveUp,
  );
}

export async function setModbusTrafficLog(
  sessionId: string,
  enabled: boolean,
  path?: string,
): Promise<void> {
  await axios.post(
    `${BASE}/modbus/client/${encodeURIComponent(sessionId)}/traffic/log`,
    { enabled, path: path ?? null },
  );
}
```

- [ ] **Step 2: Confirm TypeScript compiles**

```
cd C:\Users\ffd\Documents\netscope-desktop\frontend
npx tsc --noEmit
```

Expected: No errors. If you see `cannot find name 'resolveWSBase'`, check existing file — it's defined as `resolveWSBase()` near `createModbusLiveWebSocket`. If it's a different name, use the same one.

- [ ] **Step 3: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add frontend/src/lib/api.ts
git commit -m "feat(modbus): add ParsedFrame type + traffic WS factory + log toggle to api.ts"
```

---

## Task 10: Frontend `ModbusDiagnostics.tsx` — Jitter panel + Traffic tab

**Files:**
- Modify: `frontend/src/components/ModbusDiagnostics.tsx`

- [ ] **Step 1: Add imports**

At the top of `ModbusDiagnostics.tsx`, extend the import from `../lib/api` to include:

```typescript
  createModbusTrafficWebSocket,
  setModbusTrafficLog,
  type ParsedFrame,
```

So the import block reads:

```typescript
import {
  getModbusDiagnostics,
  getModbusRegisters,
  writeModbusRegister,
  updateClientSession,
  fetchClientSessions,
  createModbusLiveWebSocket,
  createModbusTrafficWebSocket,
  setModbusTrafficLog,
  type DiagnosticsStats,
  type ModbusWsData,
  type RegisterEntry,
  type ModbusSession,
  type ParsedFrame,
} from "../lib/api";
```

- [ ] **Step 2: Add `JitterPanel` component**

Add the following component to `ModbusDiagnostics.tsx`, after the existing `RttTimeline` function:

```tsx
// ── JitterPanel ───────────────────────────────────────────────────────────────

interface JitterStats {
  target_ms: number
  samples: number
  mean_ms?: number
  std_dev_ms?: number
  min_ms?: number
  max_ms?: number
  p50_jitter_ms?: number
  p95_jitter_ms?: number
  timeline_ms?: number[]
}

function JitterPanel({ data }: { data: JitterStats | undefined }) {
  if (!data || data.samples === 0) {
    return (
      <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2 h-24 flex items-center justify-center">
        <span className="text-[10px] text-[rgb(var(--color-muted))]">No jitter data yet</span>
      </div>
    );
  }

  const timeline = data.timeline_ms ?? [];
  const maxVal   = Math.max(...timeline, data.target_ms * 1.2, 1);

  return (
    <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2">
      <p className="text-[10px] text-[rgb(var(--color-muted))] mb-1 uppercase tracking-wide">
        Jitter Monitor — target {data.target_ms.toFixed(0)} ms
      </p>

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-1 mb-2">
        {[
          { label: "Mean",       value: data.mean_ms,        unit: "ms" },
          { label: "Std Dev",    value: data.std_dev_ms,     unit: "ms" },
          { label: "p50 jitter", value: data.p50_jitter_ms,  unit: "ms" },
          { label: "p95 jitter", value: data.p95_jitter_ms,  unit: "ms" },
        ].map(({ label, value, unit }) => (
          <div key={label} className="text-center">
            <p className="text-[9px] text-[rgb(var(--color-muted))] uppercase">{label}</p>
            <p className="text-[11px] font-mono font-semibold text-[rgb(var(--color-foreground))]">
              {value != null ? `${value.toFixed(1)}${unit}` : "—"}
            </p>
          </div>
        ))}
      </div>

      {/* Sparkline — actual intervals vs target line */}
      {timeline.length > 0 && (
        <svg className="w-full h-10" viewBox={`0 0 ${timeline.length} 40`} preserveAspectRatio="none">
          {/* target line */}
          <line
            x1={0} y1={40 - (data.target_ms / maxVal) * 40}
            x2={timeline.length} y2={40 - (data.target_ms / maxVal) * 40}
            stroke="rgb(var(--color-muted))" strokeWidth="0.5" strokeDasharray="2,2"
          />
          {/* actual interval polyline */}
          <polyline
            points={timeline.map((v, i) =>
              `${i},${(40 - (v / maxVal) * 38).toFixed(1)}`
            ).join(" ")}
            fill="none"
            stroke="rgb(var(--color-accent))"
            strokeWidth="1"
          />
        </svg>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Mount `JitterPanel` in the right column**

Find the existing `<RttTimeline ... />` JSX in the component's render output. Directly after it, add:

```tsx
<JitterPanel data={(diagStats as any)?.jitter} />
```

`diagStats` is the existing state variable holding the diagnostics API response.

- [ ] **Step 4: Add `TrafficTab` component**

Add after `JitterPanel`:

```tsx
// ── TrafficTab ────────────────────────────────────────────────────────────────

function fmtMicros(ts_us: number): string {
  const d = new Date(ts_us / 1000);
  return d.toLocaleTimeString([], { hour12: false }) +
    "." + String(d.getMilliseconds()).padStart(3, "0");
}

function TrafficTab({
  sessionId,
  source,
}: {
  sessionId: string;
  source: "simulator" | "client";
}) {
  const [frames, setFrames]         = useState<ParsedFrame[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [logging, setLogging]       = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (source !== "client" || !sessionId) return;
    const dispose = createModbusTrafficWebSocket(sessionId, (frame) => {
      setFrames((prev) => {
        const next = [...prev, frame];
        return next.length > 500 ? next.slice(next.length - 500) : next;
      });
    });
    return dispose;
  }, [sessionId, source]);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [frames, autoScroll]);

  async function toggleLog() {
    const next = !logging;
    setLogging(next);
    const path = next
      ? `${import.meta.env.VITE_DATA_DIR ?? "."}/modbus_traffic_${sessionId}.jsonl`
      : undefined;
    try {
      await setModbusTrafficLog(sessionId, next, path);
    } catch {
      setLogging(logging); // revert on error
    }
  }

  if (source === "simulator") {
    return (
      <div className="flex items-center justify-center h-32">
        <span className="text-[10px] text-[rgb(var(--color-muted))]">
          Traffic capture only available for client sessions
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* toolbar */}
      <div className="flex items-center gap-2 px-1 py-1 border-b border-[rgb(var(--color-border))]">
        <span className="text-[10px] text-[rgb(var(--color-muted))] font-mono">
          {frames.length} frames
        </span>
        <button
          onClick={() => setAutoScroll((v) => !v)}
          className={`text-[10px] px-1.5 py-0.5 rounded border ${
            autoScroll
              ? "border-[rgb(var(--color-accent))] text-[rgb(var(--color-accent))]"
              : "border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))]"
          }`}
        >
          Auto-scroll
        </button>
        <button
          onClick={toggleLog}
          title={logging ? "Stop file logging" : "Start file logging (JSONL)"}
          className={`text-[10px] px-1.5 py-0.5 rounded border ${
            logging
              ? "border-[rgb(var(--color-danger))] text-[rgb(var(--color-danger))]"
              : "border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))]"
          }`}
        >
          {logging ? "● Log" : "Log"}
        </button>
        <button
          onClick={() => setFrames([])}
          className="text-[10px] px-1.5 py-0.5 rounded border border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))] ml-auto"
        >
          Clear
        </button>
      </div>

      {/* frame table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-[10px] font-mono">
          <thead className="sticky top-0 bg-[rgb(var(--color-surface))]">
            <tr className="text-[rgb(var(--color-muted))] uppercase text-[9px]">
              <th className="px-1 py-0.5 text-left w-28">Time</th>
              <th className="px-1 py-0.5 text-left w-6">Dir</th>
              <th className="px-1 py-0.5 text-left w-6">FC</th>
              <th className="px-1 py-0.5 text-left w-20">Addr / Count</th>
              <th className="px-1 py-0.5 text-left">Exception</th>
              <th className="px-1 py-0.5 text-left">Raw hex</th>
            </tr>
          </thead>
          <tbody>
            {frames.map((f, i) => (
              <tr
                key={i}
                className={
                  f.is_exception
                    ? "bg-red-950/40 text-red-400"
                    : f.direction === "tx"
                    ? "text-[rgb(var(--color-foreground))]"
                    : "text-[rgb(var(--color-muted))]"
                }
              >
                <td className="px-1 py-px">{fmtMicros(f.ts_us)}</td>
                <td className="px-1 py-px">{f.direction.toUpperCase()}</td>
                <td className="px-1 py-px">{f.function_code.toString(16).padStart(2, "0").toUpperCase()}</td>
                <td className="px-1 py-px">
                  {f.start_address != null
                    ? `${f.start_address}×${f.quantity ?? "?"}`
                    : f.byte_count != null
                    ? `${f.byte_count}B`
                    : "—"}
                </td>
                <td className="px-1 py-px">
                  {f.exception_name ?? (f.parse_error ? `⚠ ${f.parse_error}` : "—")}
                </td>
                <td className="px-1 py-px truncate max-w-[120px]">
                  {f.raw_hex.slice(0, 24)}{f.raw_hex.length > 24 ? "…" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Add "Traffic" to `FC_TABS` and wire `TrafficTab` into `RegGrid`**

In `ModbusDiagnostics.tsx`, find the `FC_TABS` constant (around line 31–36):

```typescript
const FC_TABS = [
  { label: "HR",     fc: 3,  start: 40001, count: 50 },
  { label: "IR",     fc: 4,  start: 30001, count: 50 },
  { label: "Coils",  fc: 1,  start: 1,     count: 50 },
  { label: "DI",     fc: 2,  start: 10001, count: 50 },
] as const;

type FcTabId = typeof FC_TABS[number]["label"];
```

Replace with:

```typescript
const FC_TABS = [
  { label: "HR",     fc: 3,  start: 40001, count: 50 },
  { label: "IR",     fc: 4,  start: 30001, count: 50 },
  { label: "Coils",  fc: 1,  start: 1,     count: 50 },
  { label: "DI",     fc: 2,  start: 10001, count: 50 },
] as const;

type FcTabId = typeof FC_TABS[number]["label"] | "Traffic";
```

In the `RegGrid` component, find the tab button row (the row that renders `FC_TABS.map(...)` buttons) and add a Traffic tab button after the existing tabs:

```tsx
<button
  key="Traffic"
  onClick={() => setActiveTab("Traffic" as FcTabId)}
  className={`px-2 py-1 text-[10px] rounded-sm transition-colors ${
    activeTab === "Traffic"
      ? "bg-[rgb(var(--color-accent))] text-white"
      : "text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))]"
  }`}
>
  Traffic
</button>
```

Then, inside `RegGrid`, find the section that renders the register table (conditional on `activeTab`). Add an additional condition at the top of that section:

```tsx
{activeTab === "Traffic" ? (
  <TrafficTab sessionId={sessionId} source={source} />
) : (
  /* existing register table JSX */
)}
```

Where `sessionId` and `source` are props already available in `RegGrid` (look for the `sessionId` and `source` props passed to `RegGrid` in the existing code — they're used for `getModbusRegisters` calls).

- [ ] **Step 6: Confirm TypeScript compiles and dev server starts**

```
cd C:\Users\ffd\Documents\netscope-desktop\frontend
npx tsc --noEmit
npm run dev
```

Expected: No TypeScript errors. Dev server starts. Open `http://localhost:5173`, navigate to Modbus → Diagnostics tab. You should see:
1. The existing RTT Timeline section
2. A new "Jitter Monitor" section below it (shows "No jitter data yet" until a session polls a few times)
3. A "Traffic" tab alongside HR / IR / Coils / DI in the left register grid

- [ ] **Step 7: Commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add frontend/src/components/ModbusDiagnostics.tsx
git commit -m "feat(modbus): add JitterPanel + Traffic tab to ModbusDiagnostics"
```

---

## Task 11: Full test suite pass + backend smoke test

**Files:** No code changes — verification only.

- [ ] **Step 1: Run the full backend test suite**

```
cd C:\Users\ffd\Documents\netscope-desktop\backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All new tests pass. All pre-existing tests that were passing before this feature are still passing.

If `test_modbus_diagnostics.py::test_record_and_get_stats` fails with `KeyError: 'ec'` — this is a **pre-existing bug** in the test file (uses `stats["exceptions"][0]["ec"]` but the code produces `"code"`). This is not a regression from this feature. Confirm by checking `git log --oneline tests/test_modbus_diagnostics.py` — the test predates this branch. Fix by changing `["ec"]` to `["code"]` in that test file and note it as a pre-existing bug fix.

- [ ] **Step 2: Manual smoke test — start the app and exercise the Traffic tab**

```
cd C:\Users\ffd\Documents\netscope-desktop
npm start
```

1. Navigate to Modbus → Simulator tab → create a simulator (any device type, port 5020)
2. Navigate to Modbus → Client tab → create a client pointing at `127.0.0.1:5020`
3. Navigate to Modbus → Diagnostics tab → select the client session
4. In the left grid, click **Traffic** tab
5. Confirm frames appear as the client polls (TX rows + RX rows alternating)
6. Confirm exception rows (if any) appear in red
7. In the right column, confirm the Jitter Monitor panel appears after ~5 polls with mean/p50/p95 values and a sparkline
8. Click the **Log** button in the Traffic tab header — confirm a `.jsonl` file is created in the project root

- [ ] **Step 3: Final commit**

```bash
cd C:\Users\ffd\Documents\netscope-desktop
git add -A
git commit -m "feat(modbus): Diagnostic Suite complete — frame parser, interceptor, jitter monitor"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by task |
|---|---|
| §3 `frame_parser.py` — MBAPHeader, ParsedFrame, EXCEPTION_NAMES, FC_NAMES | Task 1 |
| §3 `parse_tcp_frame` — MBAP parsing, exception detection | Task 1 |
| §3 `parse_rtu_frame` — CRC-16/IBM validation | Task 2 |
| §3.7 parse_error set, never raised | Task 1 & 2 (tests verify `parse_error` not exception) |
| §4.1 `FrameStore` — ring, JSONL, WS fanout, counters | Task 3 |
| §4.2 `InterceptorWrap` — attach/detach, handles missing transport | Task 4 |
| §4.3 `ProxyServer` — start/stop, bidirectional pipe | Task 5 |
| §5.1 `JitterMonitor` — tick, stats, p50/p95 jitter | Task 6 |
| §5.3 `DiagnosticsEngine.get_stats()` extended signature | Task 6 |
| §6 `ClientSession` new fields + lifecycle hooks | Task 7 |
| §6.7 `poll_interval` update propagates to jitter monitor | Task 8 (PATCH handler) |
| §7.1 WS `/traffic/ws`, POST `/traffic/log`, GET `/traffic` | Task 8 |
| §7.2 `CreateClientRequest` new fields | Task 8 |
| §7.3 Extended diagnostics route | Task 8 |
| §8 `api.ts` `ParsedFrame` type | Task 9 |
| §8 `createModbusTrafficWebSocket` | Task 9 |
| §8 `setModbusTrafficLog` | Task 9 |
| §9.1 Jitter panel (sparkline + KPI grid) | Task 10 |
| §9.2 Traffic tab (WS stream, ring 500, exception highlight, log toggle) | Task 10 |

**No placeholders found.** All code blocks are complete.

**Type consistency check:**
- `FrameStore` defined in Task 3, imported in Tasks 4, 5, 7 ✓
- `InterceptorWrap` defined in Task 4, imported in Task 7 ✓
- `ProxyServer` defined in Task 5, imported in Task 7 ✓
- `JitterMonitor` defined in Task 6, imported in Task 7 ✓
- `ParsedFrame` defined in Task 1, imported in Tasks 3, 4, 5, 9, 10 ✓
- `frame_store.counters()` returns `{tx_frames, rx_frames, exception_frames, total}` — used consistently in Task 8 GET endpoint and Task 10 type ✓
- `createModbusTrafficWebSocket` added in Task 9, consumed in Task 10 ✓
