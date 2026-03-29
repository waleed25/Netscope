# Modbus TCP/RTU Diagnostic Suite — Design Spec
**Date:** 2026-03-28
**Status:** Approved
**Scope:** Three new capabilities added to the existing `backend/modbus/` flat-module stack:
1. Raw Traffic Interceptor (wire-level frame capture)
2. Frame Parser (structured MBAP/PDU → JSON)
3. Scan Rate Jitter Monitor (poll interval deviation tracking)

---

## 1. Context

The existing Modbus implementation (`backend/modbus/`) already provides:
- Multi-session async TCP/RTU/ASCII client with background polling (`client.py`)
- Multi-session TCP simulator with waveform generators (`simulator.py`, `waveforms.py`)
- All standard FCs (01–06, 15–16, 22–23, 43), byte-order handling, block coalescing
- Application-level diagnostics: RTT telemetry, exception histograms, address heatmaps (`diagnostics.py`)
- WebSocket live register streaming (`/api/modbus/client/{id}/ws`)
- 5-tab frontend panel: Simulator, Client, Scanner, Device Maps, Diagnostics

**What this spec adds:**

| Gap | Solution |
|-----|----------|
| No wire-level frame capture | `interceptor.py` — asyncio transport wrap + TCP proxy |
| No MBAP/PDU structural view | `frame_parser.py` — pure parser returning `ParsedFrame` |
| No poll interval deviation tracking | `JitterMonitor` class in `diagnostics.py` |

---

## 2. Architectural Approach: Option 1 — Targeted Additions

Three new files, two modified files in the flat `backend/modbus/` package:

```
backend/modbus/
  frame_parser.py       NEW  pure MBAP/RTU parser (no I/O, no deps)
  interceptor.py        NEW  FrameStore + InterceptorWrap + ProxyServer
  diagnostics.py        MOD  add JitterMonitor class
  client.py             MOD  wire interceptor + jitter into ClientSession

backend/api/
  modbus_routes.py      MOD  3 new endpoints + extended diagnostics response

frontend/src/lib/
  api.ts                MOD  ParsedFrame type + 2 new functions

frontend/src/components/
  ModbusDiagnostics.tsx MOD  Jitter panel + Traffic tab in RegGrid
```

**Data flow:**

```
ClientSession._poll_loop()
    │
    ├─ jitter.tick()                        ← JitterMonitor (diagnostics.py)
    │
    └─ pymodbus send/recv
           │
           ├─ [wrap mode]  asyncio transport patched write() + data_received()
           │
           └─ [proxy mode] asyncio forwarder (ProxyServer)
                       │
                  FrameStore.ingest(ParsedFrame)
                       │
                  ├─ ring buffer  (deque, maxlen=10 000)
                  ├─ JSONL file   (optional, per-session toggle)
                  └─ WebSocket broadcast → /ws/modbus/traffic/{id}/ws
```

---

## 3. Module: `frame_parser.py`

Pure module — no asyncio, no I/O. Fully unit-testable in isolation.

### 3.1 Dataclasses

```python
@dataclass
class MBAPHeader:
    transaction_id: int   # bytes 0–1
    protocol_id: int      # bytes 2–3 (always 0x0000)
    length: int           # bytes 4–5 (PDU length + 1)
    unit_id: int          # byte 6

@dataclass
class ParsedFrame:
    direction: Literal["tx", "rx"]
    ts_us: int                        # time.time_ns() // 1000
    frame_type: Literal["tcp", "rtu"]
    raw_hex: str                      # full frame as hex string

    # TCP only
    mbap: MBAPHeader | None

    # PDU — both TCP and RTU
    function_code: int
    fc_name: str                      # e.g. "Read Holding Registers"
    is_exception: bool
    exception_code: int | None        # 0x01–0x0B
    exception_name: str | None        # e.g. "Illegal Data Address"

    # Request context (tx frames)
    start_address: int | None
    quantity: int | None

    # Response context (rx frames)
    byte_count: int | None
    data_hex: str | None

    # RTU only
    crc_valid: bool | None            # None for TCP frames

    parse_error: str | None           # set on malformed/truncated input (never raised)
```

### 3.2 Public API

```python
def parse_tcp_frame(raw: bytes, direction: str, ts_us: int) -> ParsedFrame: ...
def parse_rtu_frame(raw: bytes, direction: str, ts_us: int) -> ParsedFrame: ...
```

### 3.3 Exception Code Table

```python
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
```

### 3.4 Exception Detection

If `function_code & 0x80`: frame is an exception response. Strip high bit to get original FC; next byte is `exception_code`.

### 3.5 RTU CRC Validation

CRC-16/IBM (polynomial `0xA001`) computed over all bytes except the trailing two, compared against the trailing 2 bytes (little-endian). Mismatch sets `crc_valid=False` and `parse_error="CRC mismatch"`.

### 3.6 FC Name Table

A static `FC_NAMES: dict[int, str]` mapping standard function codes (1–6, 7, 8, 11, 12, 15, 16, 17, 20, 21, 22, 23, 43) to human-readable names. Unknown FCs render as `"FC{n} (Unknown)"`.

### 3.7 Error Handling

`parse_error` is set (never raised) on:
- Frame shorter than minimum length
- MBAP `protocol_id != 0`
- Data section truncated relative to `byte_count`
- CRC mismatch (RTU only)

The interceptor logs and continues — a bad frame never crashes the capture pipeline.

---

## 4. Module: `interceptor.py`

### 4.1 `FrameStore`

Owned one-per-`ClientSession`. Handles storage and fanout.

```python
@dataclass
class FrameStore:
    session_id: str
    max_frames: int = 10_000

    _ring: deque[ParsedFrame]           # maxlen=max_frames
    _lock: asyncio.Lock
    _log_file: TextIO | None            # JSONL writer, None if disabled
    _log_path: Path | None
    _ws_clients: set[WebSocket]

    async def ingest(self, frame: ParsedFrame) -> None: ...
    # 1. append to ring (under lock)
    # 2. write dataclasses.asdict(frame) as JSONL line if file open
    # 3. broadcast to WebSocket clients — fire-and-forget, slow clients dropped

    def get_recent(self, n: int = 100) -> list[ParsedFrame]: ...
    def enable_file_log(self, path: Path) -> None: ...
    def disable_file_log(self) -> None: ...       # flush + close
    async def add_ws(self, ws: WebSocket) -> None: ...
    async def remove_ws(self, ws: WebSocket) -> None: ...
    def counters(self) -> dict: ...
    # returns: { tx_frames, rx_frames, exception_frames, total }
```

**Slow client policy:** `send_json` wrapped in `asyncio.shield` + short timeout; exception → `remove_ws`. Ingest never blocks.

### 4.2 `InterceptorWrap` — in-process transport patching

Patches a live pymodbus client after `client.connect()`. Stores originals for clean detach.

```python
class InterceptorWrap:
    def attach(self, client, store: FrameStore, frame_type: Literal["tcp","rtu"]) -> None:
        # Replaces client.transport.write and client.protocol.data_received
        # with logging wrappers that call store.ingest() via create_task()

    def detach(self, client) -> None:
        # Restores originals stored during attach()
```

**Pymodbus version note:** Targets pymodbus ≥ 3.6. Accesses `client.transport` and `client.protocol` after a successful `connect()`. Both `AsyncModbusTcpClient` and `AsyncModbusSerialClient` expose these same attributes in pymodbus 3.6+ — the serial client uses an asyncio serial transport with the identical interface. If either attribute is absent (version mismatch or failed connect), `attach()` logs a warning and no-ops rather than raising.

### 4.3 `ProxyServer` — transparent TCP forwarder

Standalone asyncio server. Started as a background task before `client.connect()`.

```python
class ProxyServer:
    def __init__(self, remote_host: str, remote_port: int,
                 store: FrameStore, local_port: int = 0): ...
    # local_port=0 → OS assigns free port

    async def start(self) -> int: ...      # returns bound local_port
    async def stop(self) -> None: ...

    async def _handle(self, cr: StreamReader, cw: StreamWriter) -> None:
        # Opens connection to remote_host:remote_port
        # Runs two _pipe() coroutines concurrently via asyncio.gather()

    async def _pipe(self, reader: StreamReader, writer: StreamWriter,
                    direction: Literal["tx","rx"]) -> None:
        # Reads chunks up to 4096 bytes
        # Calls store.ingest(parse_tcp_frame(chunk, direction, ts_us))
        # Forwards chunk to writer
        # Exits cleanly on EOF or connection reset
```

When `interceptor_mode == "proxy"`, `ClientSession.start()` starts the proxy first, then sets `_proxy_host = "127.0.0.1"` and `_proxy_port = local_port`. `_connect()` uses these rewritten values.

---

## 5. Module: `diagnostics.py` — `JitterMonitor` addition

### 5.1 Class

```python
@dataclass
class JitterMonitor:
    target_interval_ms: float          # mirrors ClientSession.poll_interval * 1000
    window: int = 300                  # rolling sample count

    _intervals: deque[float]           # actual ms between poll starts, maxlen=window
    _last_ns: int | None = None

    def tick(self) -> None:
        """Call at the top of every poll cycle (before any I/O)."""
        now = time.time_ns()
        if self._last_ns is not None:
            self._intervals.append((now - self._last_ns) / 1_000_000)
        self._last_ns = now

    def stats(self) -> dict:
        """Returns statistical summary + last 60 samples for sparkline."""
```

### 5.2 Stats Output

```json
{
  "target_ms":      1000.0,
  "samples":        287,
  "mean_ms":        1001.4,
  "std_dev_ms":     6.2,
  "min_ms":         997.1,
  "max_ms":         1031.8,
  "p50_jitter_ms":  3.1,
  "p95_jitter_ms":  14.7,
  "timeline_ms":    [999.2, 1003.1, 998.7]  // last 60 samples
}
```

`p50_jitter_ms` and `p95_jitter_ms` are percentiles of `|actual - target|` deviations, not of raw intervals.

Returns `{ "target_ms": ..., "samples": 0 }` when fewer than 2 samples collected.

### 5.3 `DiagnosticsEngine.get_stats()` signature extension

```python
def get_stats(
    self,
    jitter_monitor: JitterMonitor | None = None,
    frame_store: FrameStore | None = None,
) -> dict:
    stats = { ...existing keys... }
    if jitter_monitor:
        stats["jitter"] = jitter_monitor.stats()
    if frame_store:
        stats["traffic"] = {
            **frame_store.counters(),
            "recent": [dataclasses.asdict(f) for f in frame_store.get_recent(10)],
        }
    return stats
```

Existing consumers unaffected — new keys are purely additive.

---

## 6. Module: `client.py` — `ClientSession` wiring

### 6.1 New Fields

```python
@dataclass
class ClientSession:
    # ... existing fields unchanged ...

    interceptor_mode: Literal["none", "wrap", "proxy"] = "wrap"
    traffic_log_path: str | None = None

    # runtime state (not user-configured, not serialised to API)
    frame_store: FrameStore         = field(init=False)
    _jitter: JitterMonitor          = field(init=False)
    _interceptor_wrap: InterceptorWrap | None  = field(default=None, init=False)
    _proxy_server: ProxyServer | None          = field(default=None, init=False)
    _proxy_host: str | None                    = field(default=None, init=False)
    _proxy_port: int | None                    = field(default=None, init=False)
```

`FrameStore` and `JitterMonitor` initialised in `__post_init__` using `session_id` and `poll_interval * 1000`.

### 6.2 `start()` additions

```python
async def start(self) -> None:
    if self.interceptor_mode == "proxy":
        self._proxy_server = ProxyServer(self.host, self.port, self.frame_store)
        local_port = await self._proxy_server.start()
        self._proxy_host, self._proxy_port = "127.0.0.1", local_port

    if self.traffic_log_path:
        self.frame_store.enable_file_log(Path(self.traffic_log_path))

    self._task = asyncio.create_task(self._poll_loop())   # existing
```

### 6.3 `_connect()` addition

After successful `await self._client.connect()`:
```python
if self.interceptor_mode == "wrap":
    self._interceptor_wrap = InterceptorWrap()
    frame_type = "rtu" if self.transport in ("rtu", "ascii") else "tcp"
    self._interceptor_wrap.attach(self._client, self.frame_store, frame_type)
```

If `interceptor_mode == "proxy"`, no patching needed — proxy handles capture.
The connection target is `self._proxy_host or self.host` / `self._proxy_port or self.port` when proxy is active, so `_connect()` falls back to the real host if the proxy failed to start.

### 6.4 `_poll_loop()` addition

```python
async def _poll_loop(self) -> None:
    while True:
        self._jitter.tick()               # NEW — first line
        await self._poll_once()
        await asyncio.sleep(self.poll_interval)
```

### 6.5 `stop()` addition

```python
async def stop(self) -> None:
    # ... existing cancel/close ...
    if self._interceptor_wrap:
        self._interceptor_wrap.detach(self._client)
        self._interceptor_wrap = None
    if self._proxy_server:
        await self._proxy_server.stop()
        self._proxy_server = None
    self.frame_store.disable_file_log()
```

### 6.6 `to_dict()` addition

```python
"interceptor_mode": self.interceptor_mode,
"traffic_log_path": self.traffic_log_path,
"traffic": self.frame_store.counters(),
```

### 6.7 `poll_interval` update propagation

When `updateClientSession()` changes `poll_interval`, also update:
```python
session._jitter.target_interval_ms = new_interval * 1000
```

---

## 7. API: `modbus_routes.py` additions

### 7.1 New Endpoints

#### WebSocket — raw frame stream
```
WS /api/modbus/client/{session_id}/traffic/ws
```
- Accepts connection, registers WebSocket with `session.frame_store.add_ws()`
- Loops on `receive_text()` for keepalive only
- On `WebSocketDisconnect` or exception: calls `remove_ws()` in `finally`

#### REST — toggle file logging
```
POST /api/modbus/client/{session_id}/traffic/log
Body: { "enabled": bool, "path": str | null }
```
```python
class TrafficLogConfig(BaseModel):
    enabled: bool
    path: str | None = None
```
Returns `{ "ok": true }`.

#### REST — fetch recent frames
```
GET /api/modbus/client/{session_id}/traffic?n=100
```
Returns:
```json
{
  "frames": [ ...ParsedFrame dicts... ],
  "tx_frames": 741,
  "rx_frames": 738,
  "exception_frames": 3,
  "total": 1479
}
```

### 7.2 Extended `POST /api/modbus/client/create` body

```python
class CreateClientSessionRequest(BaseModel):
    # ... existing fields unchanged ...
    interceptor_mode: Literal["none", "wrap", "proxy"] = "wrap"
    traffic_log_path: str | None = None
```

Default `"wrap"` means all new sessions automatically get interceptor coverage.

### 7.3 Extended `GET /api/modbus/diagnostics/{session_id}` response

Route handler passes `session._jitter` and `session.frame_store` into `DiagnosticsEngine.get_stats()`. Response gains `"jitter"` and `"traffic"` top-level keys (see Section 5.2 and 5.3). No breaking changes.

---

## 8. Frontend: `api.ts` additions

### 8.1 New Type

```typescript
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
```

### 8.2 New Functions

```typescript
// WebSocket factory — mirrors createModbusLiveWebSocket pattern
export function createModbusTrafficWebSocket(
  sessionId: string,
  onFrame: (frame: ParsedFrame) => void,
  onGiveUp?: () => void,
): () => void   // returns disposer

// File log toggle
export async function setModbusTrafficLog(
  sessionId: string,
  enabled: boolean,
  path?: string,
): Promise<void>
```

---

## 9. Frontend: `ModbusDiagnostics.tsx` additions

### 9.1 Jitter Panel (new section in right column)

Placed below the existing RTT timeline. Reads `jitter` key from the existing `GET /api/modbus/diagnostics/{id}` poll (already runs every 2 s). No new API call.

Layout:
```
┌─ Jitter Monitor ──────────────────────────────────────┐
│  Target: 1000 ms                                       │
│                                                        │
│  Mean      Std Dev    p50 Jitter   p95 Jitter          │
│  1001.4ms   6.2ms      3.1ms       14.7ms              │
│                                                        │
│  [sparkline: last 60 actual intervals vs target line]  │
└────────────────────────────────────────────────────────┘
```

Sparkline: lightweight inline SVG polyline (same pattern as existing RTT timeline). No new charting dependency.

### 9.2 Traffic Tab (new tab in `RegGrid`)

Add `"Traffic"` to the `FC_TABS` row alongside HR / IR / Coils / DI.

When active, renders a frame log table instead of the register grid:

| Time | Dir | FC | Addr / Count | Exception | Raw hex |
|------|-----|----|--------------|-----------|---------|

- **Data source:** `createModbusTrafficWebSocket(sessionId)` — live stream
- **Frontend ring buffer:** last 500 frames in local state; oldest dropped from top
- **Auto-scroll:** toggleable, on by default
- **Exception rows:** `bg-red-950/40 text-red-400` highlight
- **File log toggle:** button in tab header → `setModbusTrafficLog()` → shows active path in tooltip

---

## 10. Change Summary

| File | Change | Reason |
|------|--------|--------|
| `backend/modbus/frame_parser.py` | NEW | Pure TCP/RTU parser |
| `backend/modbus/interceptor.py` | NEW | FrameStore + InterceptorWrap + ProxyServer |
| `backend/modbus/diagnostics.py` | MOD | Add JitterMonitor; extend get_stats() signature |
| `backend/modbus/client.py` | MOD | Wire interceptor + jitter into ClientSession |
| `backend/api/modbus_routes.py` | MOD | 3 new endpoints + extended diagnostics response |
| `frontend/src/lib/api.ts` | MOD | ParsedFrame type + 2 new functions |
| `frontend/src/components/ModbusDiagnostics.tsx` | MOD | Jitter panel + Traffic tab |

---

## 11. Out of Scope

- Frontend for proxy mode configuration (interceptor_mode selectable via existing session create form)
- Persistent time-series DB export (JSONL file log covers field use case)
- TLS/security layer on Modbus transport
- RTU serial sniffer (interceptor covers serial via wrap mode on AsyncModbusSerialClient)
- Rate limiting on new endpoints (tracked in project Pending Improvements list)
