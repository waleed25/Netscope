# Modbus God's View — Design Spec

**Date:** 2026-03-27
**Status:** Approved

---

## Problem

The current Modbus implementation is minimal: sine-only waveform generation, FC03/FC04 reads only, no
RTT measurement, no exception tracking, no diagnostics. Users cannot see what is happening at the
packet level, diagnose device issues, or manipulate registers from chat.

## Goal

A professional-grade Modbus implementation with:
- **God's View** diagnostics tab: live register grid (ModScan-style) + RTT timeline + exception
  frequency + per-request transaction log
- **Rich simulator**: configurable waveforms (sine/ramp/script), exception injection, response delay
- **Rich client**: RTT measurement, exception parsing, delta tracking, FC05/06/15/16/22/23/43
- **SunSpec support**: auto-discover and decode SunSpec model blocks
- **Chat integration**: LLM can run all features via 5 new tools

---

## Architecture

### New backend modules

| File | Responsibility |
|------|----------------|
| `backend/modbus/diagnostics.py` | `DiagnosticsEngine` — per-session RTT ring buffer, exception counts, register heatmap, 1s traffic timeline, transaction ring buffer |
| `backend/modbus/waveforms.py` | `SineWave`, `Ramp`, `ScriptWave` (sandboxed) |
| `backend/modbus/sunspec.py` | `SunSpecClient` — probes SunS marker, walks model blocks, applies scale factors |

### Modified backend modules

| File | Changes |
|------|---------|
| `backend/modbus/simulator.py` | Wire `WaveformGenerator` per-register, add `exception_rules`, `exception_rate`, `response_delay_ms` fields |
| `backend/modbus/client.py` | RTT measurement, exception code parsing, delta tracking, poll groups, FC05/06/15/16/22/23/43 |
| `backend/modbus/register_maps.py` | Add `SUNSPEC_INVERTER_103`, `SUNSPEC_METER_201` maps with SunS marker |
| `backend/api/modbus_routes.py` | 4 new endpoints: diagnostics GET, registers GET with fc/start/count, write POST extended FCs, SunSpec discover POST |
| `backend/agent/tools/modbus.py` | 5 new LLM tools |

### New frontend components

| File | Responsibility |
|------|----------------|
| `frontend/src/components/ModbusDiagnostics.tsx` | God's View two-column tab: register grid left, diagnostics right |

### Modified frontend

| File | Change |
|------|--------|
| `frontend/src/components/ModbusPanel.tsx` | Add "Diagnostics" as 5th tab |

---

## Backend Details

### DiagnosticsEngine (`diagnostics.py`)

```python
class DiagnosticsEngine:
    # Per-session state
    _rtt_buffer: dict[str, deque]        # deque(maxlen=1000), float ms per entry
    _exception_counts: dict[str, dict]   # {session_id: {(fc, addr, ec): count}}
    _heatmap: dict[str, dict]            # {session_id: {addr: access_count}}
    _timeline: dict[str, list]           # 1s bucket: [{ts, avg_rtt, count, exceptions}]
    _transactions: dict[str, deque]      # deque(maxlen=1000) of transaction dicts

    def record(session_id, fc, addr, rtt_ms, status, response): ...
    def get_stats(session_id) -> dict:
        # Returns {rtt: {avg, p50, p95, p99}, exceptions: [...], heatmap: {...},
        #          timeline: [...], transactions: [...]}
```

Singleton `diagnostics_engine` imported by both simulator and client modules.

### Waveforms (`waveforms.py`)

```python
class SineWave:
    def __init__(self, amplitude, period_s, phase_rad=0.0, dc_offset=0.0): ...
    def tick(self, t: float) -> int: ...       # returns raw uint16

class Ramp:
    def __init__(self, start, step, min_val, max_val): ...
    def tick(self, t: float) -> int: ...       # increments, wraps at max_val

class ScriptWave:
    ALLOWED_NAMES = {"math", "t", "random", "abs", "int", "min", "max", "round"}
    def __init__(self, expression: str): ...   # validates at init, raises ValueError if unsafe
    def tick(self, t: float) -> int: ...       # eval with restricted globals
```

### Client poll groups

Replace `poll_interval: float` with `poll_groups: list[PollGroup]`:

```python
@dataclass
class PollGroup:
    registers: list[RegisterDef]
    interval_s: float
```

Each group spawns its own asyncio task. RTT measured with `time.perf_counter()` around each
`read_holding_registers()` call. Exception codes parsed from `ExceptionResponse.exception_code`.
Delta tracked per address in `_prev_values: dict[addr, int]`.

### Additional function codes (client)

- `write_coil(addr, value)` — FC05
- `write_register(addr, value)` — FC06 (already exists)
- `write_coils(addr, values)` — FC15
- `write_registers(addr, values)` — FC16
- `mask_write_register(addr, and_mask, or_mask)` — FC22
- `read_write_registers(read_addr, read_count, write_addr, values)` — FC23
- `read_device_information(unit_id, read_code, object_id)` — FC43/14

### SunSpec (`sunspec.py`)

```python
class SunSpecClient:
    BASE_ADDRESSES = [40000, 50000, 0]  # probe order per SunSpec spec
    SUNS_MARKER = [0x5375, 0x6E53]      # "SunS"

    async def discover(host, port, unit_id) -> list[dict]:
        # 1. Probe each base address for SunS marker
        # 2. Walk DID+Length blocks: addr += 2 + length
        # 3. Stop at sentinel DID=0xFFFF
        # 4. For each block: decode registers, apply *_SF scale factors
        # 5. Return [{did, name, base_addr, registers: {name: {value, unit}}}]
```

### New API endpoints

```
GET  /modbus/diagnostics/{session_id}
     → {rtt, exceptions, heatmap, timeline, transactions}

GET  /modbus/{source}/{session_id}/registers?fc=3&start=40001&count=50
     source = "simulator" or "client"
     → {session_id, registers: [{address, raw, value, unit, delta, name}]}

POST /modbus/{source}/{session_id}/write
     body: {fc: int, addr: int, values: list[int], and_mask?: int, or_mask?: int}
     fc=5 (coil), 6 (single reg), 15 (multi coil), 16 (multi reg), 22 (mask), 23 (rw)
     → {ok, address, values}

POST /modbus/sunspec/discover
     body: {host: str, port: int = 502, unit_id: int = 1}
     → {found: bool, base_address: int, models: [...]}
```

---

## God's View UI

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  240px (fixed left)           │  flex-1 (right)              │
│  ─ Live Registers ────────    │  ─ KPI bar ───────────────   │
│  session selector · FC tabs   │  Avg RTT · p50/95/99         │
│  ─────────────────────────    │  Exceptions · Req Rate       │
│  Addr · Raw · Eng · Unit · Δ  │  ─ RTT Timeline ──────────   │
│  rows: yellow flash on change │  bar chart, red on exception │
│  click raw cell → edit inline │  ─ Exception Frequency ───   │
│  ─────────────────────────    │  horizontal bars per EC code │
│  Write bar                    │  ─ Transaction Log ────────   │
│  addr + val + FC + Write btn  │  #·Time·FC·Addr/Rsp·St·RTT  │
└─────────────────────────────────────────────────────────────┘
```

### Register grid behavior
- FC tabs: HR (FC03), IR (FC04), Coils (FC01), DI (FC02)
- Yellow highlight + amber value on changed rows, fades after 1s
- Directional arrows ▲▼ on recently changed values
- Blue left-border + inline edit on selected row
- Polls `GET /modbus/{source}/{session_id}/registers?fc=3` every 1s

### Diagnostics panel behavior
- KPI bar: Avg RTT (blue), p50/p95/p99 (blue), Exceptions count (red), Req Rate (purple)
- RTT Timeline: bar chart, red bars on exception ticks, x-axis timestamps, last 2 min
- Exception Frequency: horizontal bar chart, sorted by count desc, color-coded by severity
- Transaction Log: Wireshark-style row colors
  - Blue bg: normal read
  - Red bg (`#2d1515`): exception response
  - Teal bg (`#162030`): write operation
  - Columns: # · Time · FC · Addr/Response · Status · RTT
  - Pause button: stops auto-scroll + polling
  - CSV export button: downloads transactions as CSV

---

## LLM Chat Tools

Five new tools added to `backend/agent/tools/modbus.py`:

| Tool | Args | Returns |
|------|------|---------|
| `modbus_diagnostics` | `<session_id>` | RTT stats, exception counts, heatmap summary |
| `modbus_write_multi` | `<session_id> <fc> <addr> <val1> [val2...]` | Write result |
| `modbus_sunspec_discover` | `<host> [port] [unit_id]` | Model list with decoded values |
| `modbus_set_waveform` | `<session_id> <addr> <sine|ramp|script> [params...]` | Updated waveform |
| `modbus_inject_exception` | `<session_id> <addr> <ec_code> <rate_0_to_1>` | Injection config |

---

## Verification

1. `ModbusPanel` renders 5th "Diagnostics" tab
2. Register grid updates live at 1s; write bar sends FC06 and value updates
3. RTT Timeline shows red spikes on exceptions
4. Transaction log: correct row colors; CSV export downloads a file
5. LLM: `modbus_diagnostics <session_id>` returns RTT + exception summary in chat
6. LLM: `modbus_sunspec_discover 127.0.0.1` returns model list
7. `npm run build` clean (no TypeScript errors)
