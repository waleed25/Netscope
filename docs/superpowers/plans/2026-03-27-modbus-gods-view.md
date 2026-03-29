# Modbus God's View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a professional-grade Modbus diagnostics tab with live register grid, RTT timeline, exception tracking, SunSpec support, configurable waveforms, and LLM chat tools.

**Architecture:** Four sequential layers — (1) new backend modules (diagnostics, waveforms, SunSpec), (2) enhanced simulator + client, (3) new API endpoints, (4) frontend God's View tab. Each task is independently committable.

**Tech Stack:** Python/FastAPI (backend), pymodbus 3.x, React 18/TypeScript/Tailwind (frontend)

**Spec:** `docs/superpowers/specs/2026-03-27-modbus-gods-view-design.md`

---

## File Map

| File | Action | Notes |
|------|--------|-------|
| `backend/modbus/diagnostics.py` | Create | DiagnosticsEngine singleton |
| `backend/modbus/waveforms.py` | Create | SineWave, Ramp, ScriptWave |
| `backend/modbus/sunspec.py` | Create | SunSpecClient |
| `backend/modbus/simulator.py` | Modify | Wire waveforms, exception injection |
| `backend/modbus/client.py` | Modify | RTT, delta, poll groups, extra FCs |
| `backend/modbus/register_maps.py` | Modify | Add SunSpec maps (Task 3b) |
| `backend/api/modbus_routes.py` | Modify | 5 new endpoints (incl. parameterized registers) |
| `backend/agent/tools/modbus.py` | Modify | 5 new chat tools |
| `frontend/src/components/ModbusDiagnostics.tsx` | Create | God's View tab |
| `frontend/src/components/ModbusPanel.tsx` | Modify | Add 5th Diagnostics tab |
| `tests/test_modbus_diagnostics.py` | Create | DiagnosticsEngine tests |
| `tests/test_modbus_waveforms.py` | Create | Waveform tests |
| `tests/test_modbus_sunspec.py` | Create | SunSpec tests |

---

## Task 1: DiagnosticsEngine

**Files:**
- Create: `backend/modbus/diagnostics.py`
- Create: `tests/test_modbus_diagnostics.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_modbus_diagnostics.py
import pytest
from modbus.diagnostics import DiagnosticsEngine

def test_record_and_get_stats():
    eng = DiagnosticsEngine()
    eng.record("s1", fc=3, addr=40001, rtt_ms=10.0, status="ok", response=[100])
    eng.record("s1", fc=3, addr=40001, rtt_ms=20.0, status="ok", response=[101])
    eng.record("s1", fc=3, addr=40100, rtt_ms=8.0, status="exception", exception_code=2, response=None)
    stats = eng.get_stats("s1")
    assert stats["rtt"]["avg"] == pytest.approx(12.67, abs=0.1)
    assert stats["rtt"]["p50"] > 0
    assert len(stats["exceptions"]) == 1
    assert stats["exceptions"][0]["ec"] == 2
    assert stats["exceptions"][0]["count"] == 1
    assert stats["heatmap"][40001] == 2
    assert stats["heatmap"][40100] == 1
    assert len(stats["transactions"]) == 3

def test_empty_session_returns_zeroes():
    eng = DiagnosticsEngine()
    stats = eng.get_stats("nonexistent")
    assert stats["rtt"]["avg"] == 0
    assert stats["exceptions"] == []
    assert stats["transactions"] == []

def test_transaction_ring_buffer_capped():
    eng = DiagnosticsEngine()
    for i in range(1100):
        eng.record("s1", fc=3, addr=40001, rtt_ms=10.0, status="ok", response=[i])
    stats = eng.get_stats("s1")
    assert len(stats["transactions"]) == 1000

def test_percentiles():
    eng = DiagnosticsEngine()
    for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        eng.record("s1", fc=3, addr=1, rtt_ms=float(ms), status="ok", response=[0])
    stats = eng.get_stats("s1")
    assert stats["rtt"]["p50"] == pytest.approx(55.0, abs=5.0)
    assert stats["rtt"]["p95"] == pytest.approx(95.0, abs=5.0)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_modbus_diagnostics.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'DiagnosticsEngine'`

- [ ] **Step 3: Implement DiagnosticsEngine**

```python
# backend/modbus/diagnostics.py
from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
import statistics

@dataclass
class _Transaction:
    seq: int
    ts: float
    session_id: str
    fc: int
    addr: int
    rtt_ms: float
    status: str              # "ok" | "exception" | "timeout"
    exception_code: int | None
    response_summary: str    # short str, e.g. "[100,200,...]" or "EC02"

class DiagnosticsEngine:
    def __init__(self):
        self._rtt: dict[str, deque] = {}          # session_id -> deque(maxlen=1000)
        self._exc: dict[str, dict] = {}           # session_id -> {(fc,addr,ec): count}
        self._heatmap: dict[str, dict] = {}       # session_id -> {addr: count}
        self._transactions: dict[str, deque] = {} # session_id -> deque(maxlen=1000)
        self._seq: dict[str, int] = {}
        self._timeline_buckets: dict[str, dict] = {}  # session_id -> {bucket_ts: {sum_rtt, count, exceptions}}

    def _ensure(self, sid: str):
        if sid not in self._rtt:
            self._rtt[sid] = deque(maxlen=1000)
            self._exc[sid] = {}
            self._heatmap[sid] = {}
            self._transactions[sid] = deque(maxlen=1000)
            self._seq[sid] = 0
            self._timeline_buckets[sid] = {}

    def record(
        self, session_id: str, fc: int, addr: int, rtt_ms: float,
        status: str, response: Any, exception_code: int | None = None,
    ):
        self._ensure(session_id)
        sid = session_id
        self._rtt[sid].append(rtt_ms)
        self._heatmap[sid][addr] = self._heatmap[sid].get(addr, 0) + 1
        if status == "exception" and exception_code is not None:
            key = (fc, addr, exception_code)
            self._exc[sid][key] = self._exc[sid].get(key, 0) + 1
        self._seq[sid] += 1
        if status == "exception" and exception_code is not None:
            resp_str = f"EC{exception_code:02d}"
        elif response is not None:
            vals = list(response) if hasattr(response, "__iter__") else [response]
            resp_str = str(vals[:5])[:-1] + ("…]" if len(vals) > 5 else "]")
        else:
            resp_str = "timeout"
        self._transactions[sid].append(_Transaction(
            seq=self._seq[sid], ts=time.time(), session_id=sid,
            fc=fc, addr=addr, rtt_ms=rtt_ms, status=status,
            exception_code=exception_code, response_summary=resp_str,
        ))
        # Timeline bucket (1s)
        bucket = int(time.time())
        bkt = self._timeline_buckets[sid]
        if bucket not in bkt:
            bkt[bucket] = {"sum_rtt": 0.0, "count": 0, "exceptions": 0}
        bkt[bucket]["sum_rtt"] += rtt_ms
        bkt[bucket]["count"] += 1
        if status == "exception":
            bkt[bucket]["exceptions"] += 1
        # Keep only last 180 buckets (3 min)
        old_keys = [k for k in bkt if k < bucket - 180]
        for k in old_keys:
            del bkt[k]

    def get_stats(self, session_id: str) -> dict:
        self._ensure(session_id)
        sid = session_id
        rtts = list(self._rtt[sid])
        # RTT stats
        if rtts:
            sorted_rtts = sorted(rtts)
            n = len(sorted_rtts)
            avg = sum(sorted_rtts) / n
            p50 = sorted_rtts[int(n * 0.50)]
            p95 = sorted_rtts[min(int(n * 0.95), n - 1)]
            p99 = sorted_rtts[min(int(n * 0.99), n - 1)]
        else:
            avg = p50 = p95 = p99 = 0
        # Exceptions sorted by count desc
        exc_list = [
            {"fc": k[0], "addr": k[1], "ec": k[2], "count": v}
            for k, v in sorted(self._exc[sid].items(), key=lambda x: -x[1])
        ]
        # Heatmap
        heatmap = dict(self._heatmap[sid])
        # Timeline: sorted buckets
        now = int(time.time())
        timeline = []
        for ts in sorted(self._timeline_buckets[sid]):
            bkt = self._timeline_buckets[sid][ts]
            timeline.append({
                "ts": ts,
                "avg_rtt": round(bkt["sum_rtt"] / bkt["count"], 2) if bkt["count"] else 0,
                "count": bkt["count"],
                "exceptions": bkt["exceptions"],
            })
        # Transactions (most recent first)
        txns = [
            {
                "seq": t.seq, "ts": t.ts, "fc": t.fc, "addr": t.addr,
                "rtt_ms": round(t.rtt_ms, 2), "status": t.status,
                "ec": t.exception_code, "response": t.response_summary,
            }
            for t in reversed(self._transactions[sid])
        ]
        # Req rate (last 10s)
        recent = [t for t in self._transactions[sid] if time.time() - t.ts <= 10]
        req_rate = round(len(recent) / 10.0, 2)
        return {
            "rtt": {"avg": round(avg, 2), "p50": round(p50, 2), "p95": round(p95, 2), "p99": round(p99, 2)},
            "exceptions": exc_list,
            "heatmap": heatmap,
            "timeline": timeline,
            "transactions": txns[:200],  # limit to 200 in API response
            "req_rate": req_rate,
            "total_polls": self._seq[sid],
        }

    def clear(self, session_id: str):
        for d in (self._rtt, self._exc, self._heatmap, self._transactions,
                  self._seq, self._timeline_buckets):
            d.pop(session_id, None)


# Singleton
diagnostics_engine = DiagnosticsEngine()
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_modbus_diagnostics.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modbus/diagnostics.py tests/test_modbus_diagnostics.py
git commit -m "feat(modbus): add DiagnosticsEngine with RTT, exceptions, heatmap, timeline"
```

---

## Task 2: Waveform Generators

**Files:**
- Create: `backend/modbus/waveforms.py`
- Create: `tests/test_modbus_waveforms.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_modbus_waveforms.py
import math, pytest
from modbus.waveforms import SineWave, Ramp, ScriptWave

def test_sine_dc_offset():
    w = SineWave(amplitude=100, period_s=10.0, dc_offset=500)
    vals = [w.tick(t) for t in range(0, 100, 1)]
    assert min(vals) >= 400
    assert max(vals) <= 600

def test_ramp_wraps():
    r = Ramp(start=0, step=10, min_val=0, max_val=50)
    vals = [r.tick(t) for t in range(7)]
    assert vals == [0, 10, 20, 30, 40, 50, 0]

def test_ramp_uses_t_zero_start():
    r = Ramp(start=30, step=5, min_val=0, max_val=50)
    assert r.tick(0) == 30
    assert r.tick(1) == 35

def test_script_wave_sine():
    w = ScriptWave("int(100 * math.sin(t) + 500)")
    val = w.tick(0.0)
    assert val == 500  # sin(0) = 0

def test_script_wave_blocks_dangerous():
    with pytest.raises(ValueError, match="unsafe"):
        ScriptWave("__import__('os').system('cmd')")

def test_script_wave_blocks_open():
    with pytest.raises(ValueError, match="unsafe"):
        ScriptWave("open('/etc/passwd').read()")

def test_script_wave_clamps():
    w = ScriptWave("99999")
    assert w.tick(0) == 65535  # clamped to uint16 max
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd backend && python -m pytest tests/test_modbus_waveforms.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement waveforms**

```python
# backend/modbus/waveforms.py
from __future__ import annotations
import ast
import math
import random

_BLOCKED_NAMES = {"__import__", "__builtins__", "open", "exec", "eval",
                  "compile", "os", "sys", "subprocess", "importlib",
                  "globals", "locals", "vars", "dir", "getattr", "setattr",
                  "delattr", "hasattr", "__class__", "__bases__"}

def _check_safe(expression: str):
    """Raise ValueError if expression contains unsafe constructs."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Syntax error in expression: {e}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ValueError(f"unsafe name in expression: '{node.id}'")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("unsafe dunder attribute in expression")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("import not allowed in expression")
    return expression


class SineWave:
    def __init__(self, amplitude: float = 100.0, period_s: float = 300.0,
                 phase_rad: float = 0.0, dc_offset: float = 0.0):
        self.amplitude = amplitude
        self.period_s  = period_s
        self.phase_rad = phase_rad
        self.dc_offset = dc_offset

    def tick(self, t: float) -> int:
        val = self.dc_offset + self.amplitude * math.sin(
            (2 * math.pi / self.period_s) * t + self.phase_rad
        )
        return max(0, min(65535, int(val)))


class Ramp:
    def __init__(self, start: int = 0, step: int = 1,
                 min_val: int = 0, max_val: int = 65535):
        self.step    = step
        self.min_val = min_val
        self.max_val = max_val
        self._current = start

    def tick(self, t: float) -> int:
        val = self._current
        self._current += self.step
        if self._current > self.max_val:
            self._current = self.min_val
        return max(0, min(65535, val))


class ScriptWave:
    def __init__(self, expression: str):
        self._expr = _check_safe(expression)
        self._globals = {
            "__builtins__": {},
            "math": math,
            "random": random,
            "abs": abs, "int": int, "min": min, "max": max, "round": round,
        }

    def tick(self, t: float) -> int:
        try:
            val = eval(self._expr, self._globals, {"t": t})  # noqa: S307
            return max(0, min(65535, int(val)))
        except Exception:
            return 0
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_modbus_waveforms.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modbus/waveforms.py tests/test_modbus_waveforms.py
git commit -m "feat(modbus): add SineWave, Ramp, ScriptWave waveform generators"
```

---

## Task 3: SunSpec Client

**Files:**
- Create: `backend/modbus/sunspec.py`
- Create: `tests/test_modbus_sunspec.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_modbus_sunspec.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from modbus.sunspec import SunSpecClient, SUNS_MARKER

def test_suns_marker_value():
    assert SUNS_MARKER == [0x5375, 0x6E53]

@pytest.mark.asyncio
async def test_discover_no_sunspec():
    client = SunSpecClient()
    # Mock client that always returns non-SunS data
    with patch("modbus.sunspec.AsyncModbusTcpClient") as mock_cls:
        mock_conn = AsyncMock()
        mock_conn.connected = True
        mock_conn.connect = AsyncMock(return_value=True)
        resp = MagicMock()
        resp.isError.return_value = False
        resp.registers = [0x1234, 0x5678]  # not SunS
        mock_conn.read_holding_registers = AsyncMock(return_value=resp)
        mock_cls.return_value = mock_conn
        result = await client.discover("127.0.0.1", 502, 1)
    assert result["found"] is False
    assert result["models"] == []

@pytest.mark.asyncio
async def test_discover_finds_sunspec():
    client = SunSpecClient()
    # Simulate: addr 40000 has SunS, then DID=101 (Inverter) len=50, then 0xFFFF
    call_count = 0
    regs_map = {
        40000: [0x5375, 0x6E53],           # SunS marker
        40002: [101, 50],                   # DID=101, len=50
        40004: [0] * 50,                    # model block
        40054: [0xFFFF, 0],                 # end sentinel
    }
    async def mock_read(addr, count=1, **kw):
        r = MagicMock()
        r.isError.return_value = False
        r.registers = regs_map.get(addr, [0] * count)
        return r
    with patch("modbus.sunspec.AsyncModbusTcpClient") as mock_cls:
        mock_conn = AsyncMock()
        mock_conn.connected = True
        mock_conn.connect = AsyncMock(return_value=True)
        mock_conn.read_holding_registers = mock_read
        mock_cls.return_value = mock_conn
        result = await client.discover("127.0.0.1", 502, 1)
    assert result["found"] is True
    assert result["base_address"] == 40000
    assert len(result["models"]) == 1
    assert result["models"][0]["did"] == 101
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd backend && python -m pytest tests/test_modbus_sunspec.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement SunSpecClient**

```python
# backend/modbus/sunspec.py
from __future__ import annotations
import asyncio
from pymodbus.client import AsyncModbusTcpClient

SUNS_MARKER = [0x5375, 0x6E53]  # "SunS" in ASCII

# SunSpec DID → model name
_DID_NAMES: dict[int, str] = {
    1: "Common",
    11: "Aggregator",
    101: "Inverter (Single Phase)",
    102: "Inverter (Split Phase)",
    103: "Inverter (Three Phase)",
    111: "Inverter (Single Phase Float)",
    112: "Inverter (Split Phase Float)",
    113: "Inverter (Three Phase Float)",
    120: "Nameplate",
    121: "Basic Settings",
    122: "Measurements_Status",
    123: "Immediate Controls",
    160: "Multiple MPPT",
    201: "AC Meter (Single Phase)",
    202: "AC Meter (Split Phase)",
    203: "AC Meter (Wye 3P4W)",
    204: "AC Meter (Delta 3P3W)",
    302: "Irradiance",
    303: "Back of Module Temperature",
    304: "Inclinometer",
    401: "String Combiner Current",
    802: "Battery Base",
    803: "Lithium-Ion Battery Bank",
}


class SunSpecClient:
    BASE_ADDRESSES = [40000, 50000, 0]

    async def discover(self, host: str, port: int = 502, unit_id: int = 1) -> dict:
        """Probe host for SunSpec model blocks. Returns {found, base_address, models}."""
        client = AsyncModbusTcpClient(host, port=port)
        try:
            if not await client.connect():
                return {"found": False, "error": "Connection failed", "models": []}
            for base in self.BASE_ADDRESSES:
                result = await self._try_base(client, base, unit_id)
                if result is not None:
                    return {"found": True, "base_address": base, "models": result}
            return {"found": False, "models": []}
        except Exception as e:
            return {"found": False, "error": str(e), "models": []}
        finally:
            client.close()

    async def _try_base(self, client, base: int, unit_id: int) -> list | None:
        """Return list of models if SunS found at base, else None."""
        resp = await client.read_holding_registers(base, count=2, device_id=unit_id)
        if resp.isError() or list(resp.registers) != SUNS_MARKER:
            return None
        models = []
        addr = base + 2
        for _ in range(64):  # max 64 models
            resp = await client.read_holding_registers(addr, count=2, device_id=unit_id)
            if resp.isError():
                break
            did, length = resp.registers[0], resp.registers[1]
            if did == 0xFFFF:
                break
            if did == 0 or length == 0:
                addr += 2
                continue
            # Read model block
            block_resp = await client.read_holding_registers(
                addr + 2, count=length, device_id=unit_id
            )
            block_regs = list(block_resp.registers) if not block_resp.isError() else []
            models.append({
                "did": did,
                "name": _DID_NAMES.get(did, f"Model_{did}"),
                "base_addr": addr,
                "length": length,
                "registers_raw": block_regs[:20],  # truncate for API response
            })
            addr += 2 + length
        return models
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_modbus_sunspec.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modbus/sunspec.py tests/test_modbus_sunspec.py
git commit -m "feat(modbus): add SunSpecClient — discover and walk SunSpec model blocks"
```

---

## Task 3b: SunSpec Register Maps

**Files:**
- Modify: `backend/modbus/register_maps.py`

The spec requires adding SunSpec-compatible maps with the "SunS" marker at offset 0.
SunSpec register 40000 must contain `[0x5375, 0x6E53]` ("SunS"), then DID+Length, then model data.

- [ ] **Step 1: Add SUNSPEC_INVERTER_103 and SUNSPEC_METER_201 to register_maps.py**

At the bottom of the Solar Inverters section (before the `# ── Energy Meters` comment), add:

```python
# ── SunSpec Maps ──────────────────────────────────────────────────────────────
# SunS marker occupies addresses 40000-40001 (0x5375, 0x6E53 = "SunS")
# Model 103 block starts at 40002: DID=103, Length=50, then 50 register data words

SUNSPEC_INVERTER_103: list[RegisterDef] = [
    # SunS marker at 40000 (raw = 0x5375), 40001 (raw = 0x6E53)
    RegisterDef(40000, "SunS_Hi",      "",    1.0,  "uint16", "ro", 21365, 21365, "SunSpec marker high word (0x5375)"),
    RegisterDef(40001, "SunS_Lo",      "",    1.0,  "uint16", "ro", 28243, 28243, "SunSpec marker low word (0x6E53)"),
    # Model 103 header: DID=103, Length=50
    RegisterDef(40002, "DID",          "",    1.0,  "uint16", "ro", 103,   103,   "Model ID 103 = Three-Phase Inverter"),
    RegisterDef(40003, "L",            "",    1.0,  "uint16", "ro", 50,    50,    "Model length in registers"),
    # Model 103 data (abbreviated common fields)
    RegisterDef(40004, "AC_A",         "A",   100.0,"int16",  "ro", 0,     1000,  "AC total current ×100"),
    RegisterDef(40005, "AC_AphA",      "A",   100.0,"int16",  "ro", 0,     400,   "Phase A current ×100"),
    RegisterDef(40006, "AC_AphB",      "A",   100.0,"int16",  "ro", 0,     400,   "Phase B current ×100"),
    RegisterDef(40007, "AC_AphC",      "A",   100.0,"int16",  "ro", 0,     400,   "Phase C current ×100"),
    RegisterDef(40008, "AC_VphAB",     "V",   100.0,"uint16", "ro", 36000, 44000, "Phase AB voltage ×100"),
    RegisterDef(40009, "AC_VphBC",     "V",   100.0,"uint16", "ro", 36000, 44000, "Phase BC voltage ×100"),
    RegisterDef(40010, "AC_VphCA",     "V",   100.0,"uint16", "ro", 36000, 44000, "Phase CA voltage ×100"),
    RegisterDef(40011, "AC_VphA",      "V",   100.0,"uint16", "ro", 20000, 24000, "Phase A voltage ×100"),
    RegisterDef(40012, "AC_VphB",      "V",   100.0,"uint16", "ro", 20000, 24000, "Phase B voltage ×100"),
    RegisterDef(40013, "AC_VphC",      "V",   100.0,"uint16", "ro", 20000, 24000, "Phase C voltage ×100"),
    RegisterDef(40014, "AC_W",         "W",   1.0,  "int16",  "ro", 0,     17000, "AC power"),
    RegisterDef(40015, "AC_Hz",        "Hz",  100.0,"uint16", "ro", 4990,  5010,  "Frequency ×100"),
    RegisterDef(40016, "AC_VA",        "VA",  1.0,  "int16",  "ro", 0,     20000, "Apparent power"),
    RegisterDef(40017, "AC_VAR",       "VAr", 1.0,  "int16",  "ro", -5000, 5000,  "Reactive power"),
    RegisterDef(40018, "AC_PF",        "%",   100.0,"int16",  "ro", -100,  100,   "Power factor ×100"),
    RegisterDef(40019, "AC_WH",        "Wh",  1.0,  "uint32", "ro", 0,     9999999,"AC energy lifetime"),
    RegisterDef(40021, "DC_V",         "V",   100.0,"int16",  "ro", 30000, 90000, "DC voltage ×100"),
    RegisterDef(40022, "DC_A",         "A",   100.0,"int16",  "ro", 0,     4000,  "DC current ×100"),
    RegisterDef(40023, "DC_W",         "W",   1.0,  "int16",  "ro", 0,     17000, "DC power"),
    RegisterDef(40024, "Tmp_Cab",      "°C",  100.0,"int16",  "ro", 2000,  8000,  "Cabinet temp ×100"),
    RegisterDef(40025, "St",           "",    1.0,  "uint16", "ro", 4,     4,     "Operating state (4=MPPT)"),
]

SUNSPEC_METER_201: list[RegisterDef] = [
    # SunS marker at 40000 (shared base if on same device, else independent)
    RegisterDef(40000, "SunS_Hi",      "",    1.0,  "uint16", "ro", 21365, 21365, "SunSpec marker high word"),
    RegisterDef(40001, "SunS_Lo",      "",    1.0,  "uint16", "ro", 28243, 28243, "SunSpec marker low word"),
    RegisterDef(40002, "DID",          "",    1.0,  "uint16", "ro", 201,   201,   "Model ID 201 = Single-Phase AC Meter"),
    RegisterDef(40003, "L",            "",    1.0,  "uint16", "ro", 105,   105,   "Model length"),
    RegisterDef(40004, "A",            "A",   100.0,"int16",  "ro", -10000,10000, "AC current ×100"),
    RegisterDef(40005, "AphA",         "A",   100.0,"int16",  "ro", -10000,10000, "Phase A current ×100"),
    RegisterDef(40006, "V",            "V",   100.0,"int16",  "ro", 21000, 24000, "Phase voltage ×100"),
    RegisterDef(40007, "Hz",           "Hz",  100.0,"uint16", "ro", 4990,  5010,  "Frequency ×100"),
    RegisterDef(40008, "W",            "W",   1.0,  "int16",  "ro", -50000,50000, "Active power"),
    RegisterDef(40009, "VA",           "VA",  1.0,  "int16",  "ro", 0,     50000, "Apparent power"),
    RegisterDef(40010, "VAR",          "VAr", 1.0,  "int16",  "ro", -20000,20000, "Reactive power"),
    RegisterDef(40011, "PF",           "",    1000.0,"int16", "ro", -1000, 1000,  "Power factor ×1000"),
    RegisterDef(40012, "TotWh_Exp",    "Wh",  1.0,  "uint32", "ro", 0,     9999999,"Export energy"),
    RegisterDef(40014, "TotWh_Imp",    "Wh",  1.0,  "uint32", "ro", 0,     9999999,"Import energy"),
]
```

Also add entries to `DEVICE_TYPES`:

```python
    "sunspec inverter": SUNSPEC_INVERTER_103,
    "sunspec meter":    SUNSPEC_METER_201,
    "sunspec":          SUNSPEC_INVERTER_103,
```

- [ ] **Step 2: Commit**

```bash
git add backend/modbus/register_maps.py
git commit -m "feat(modbus): add SUNSPEC_INVERTER_103 and SUNSPEC_METER_201 register maps"
```

---

## Task 4: Simulator — Waveforms + Exception Injection

**Files:**
- Modify: `backend/modbus/simulator.py`

Wire `WaveformGenerator` per-register dict, add `exception_rules` and `exception_rate`.
The `_sim_value()` function already returns a float per register; we replace it with a waveform
dispatch that falls back to the existing sine behavior.

- [ ] **Step 1: Add waveform + exception fields to SimulatorSession**

In `simulator.py`, after the existing imports, add:

```python
from modbus.waveforms import SineWave, Ramp, ScriptWave
from modbus.diagnostics import diagnostics_engine
import time as _time
```

Add these fields to `SimulatorSession` dataclass (after `device_name`):

```python
# Waveform overrides: {address: SineWave | Ramp | ScriptWave}
waveforms: dict = field(default_factory=dict, init=False)

# Exception injection: {address: exception_code (1-11)}
exception_rules: dict = field(default_factory=dict)

# Probabilistic exception rate (0.0-1.0) for all reads
exception_rate: float = 0.0

# Response delay range [min_ms, max_ms]
response_delay_ms: tuple = field(default_factory=lambda: (0, 0))
```

- [ ] **Step 2: Replace `_refresh_values` with waveform-aware version**

The current `_refresh_values` in `simulator.py` (lines ~156–168) calls `_build_register_block(self.registers, t)` then iterates its dict calling `store.setValues`. Replace the entire method body with the waveform-dispatching version below. The method signature `def _refresh_values(self):` stays the same.

```python
def _refresh_values(self):
    """Update simulated register values, dispatching to waveform generators when set."""
    if self._ctx is None:
        return
    t = _time.time()
    try:
        store = self._ctx[self.unit_id]
        for reg in self.registers:
            # Use waveform if configured, else fallback to original sine+noise
            wf = self.waveforms.get(reg.address)
            if wf is not None:
                raw = wf.tick(t)
            else:
                val = _sim_value(reg, t)
                raw = _to_raw_uint16(val, reg)
            store.setValues(3, reg.address, [raw & 0xFFFF])
            store.setValues(4, reg.address, [raw & 0xFFFF])
    except Exception:
        pass
```

Note: `_sim_value` and `_to_raw_uint16` are already defined at the top of `simulator.py` — no change needed there.

- [ ] **Step 3: Add `set_waveform` and `set_exception_rule` methods to SimulatorSession**

```python
def set_waveform(self, address: int, waveform) -> bool:
    """Attach a waveform generator to a register address."""
    self.waveforms[address] = waveform
    return True

def set_exception_rule(self, address: int, exception_code: int | None):
    """Set or clear an exception rule for a register address."""
    if exception_code is None:
        self.exception_rules.pop(address, None)
    else:
        self.exception_rules[address] = exception_code

def to_dict(self) -> dict:
    d = { ... existing fields ... }
    d["exception_rate"] = self.exception_rate
    d["exception_rules"] = self.exception_rules
    d["response_delay_ms"] = list(self.response_delay_ms)
    return d
```

Note: leave existing `to_dict()` in place and add the three new keys to the dict it returns.

- [ ] **Step 4: Add `set_waveform`, `set_exception_rule` to SimulatorManager**

```python
def set_waveform(self, session_id: str, address: int, waveform) -> bool:
    session = self._sessions.get(session_id)
    if not session:
        return False
    return session.set_waveform(address, waveform)

def set_exception_rule(self, session_id: str, address: int, exception_code: int | None) -> bool:
    session = self._sessions.get(session_id)
    if not session:
        return False
    session.set_exception_rule(address, exception_code)
    return True

def set_exception_rate(self, session_id: str, rate: float) -> bool:
    session = self._sessions.get(session_id)
    if not session:
        return False
    session.exception_rate = max(0.0, min(1.0, rate))
    return True
```

- [ ] **Step 5: Commit**

```bash
git add backend/modbus/simulator.py
git commit -m "feat(modbus): wire waveform generators and exception injection into simulator"
```

---

## Task 5: Client — RTT, Delta, Extra FCs

**Files:**
- Modify: `backend/modbus/client.py`

- [ ] **Step 1: Add RTT measurement and delta tracking to `_poll_once`**

Add `import time` is already present. Replace the inner loop in `_poll_once`:

```python
async def _poll_once(self) -> list[dict]:
    results: list[dict] = []
    if not await self._connect():
        raise ConnectionError(f"Cannot connect to {self.host}:{self.port}")

    for reg in self.registers:
        count = _reg_count(reg)
        t0 = time.perf_counter()
        try:
            resp = await self._client.read_holding_registers(
                reg.address, count=count, device_id=self.unit_id
            )
            rtt_ms = (time.perf_counter() - t0) * 1000

            if resp.isError():
                resp = await self._client.read_input_registers(
                    reg.address, count=count, device_id=self.unit_id
                )
                rtt_ms = (time.perf_counter() - t0) * 1000

            if resp.isError():
                ec = getattr(resp, "exception_code", None)
                ec_int = int(ec) if ec is not None else 0
                # Record exception in diagnostics
                from modbus.diagnostics import diagnostics_engine
                diagnostics_engine.record(
                    self.session_id, fc=3, addr=reg.address,
                    rtt_ms=rtt_ms, status="exception",
                    exception_code=ec_int, response=None,
                )
                results.append({
                    "address": reg.address, "name": reg.name,
                    "error": str(resp), "unit": reg.unit,
                    "exception_code": ec_int,
                })
                continue

            raw_regs = list(resp.registers)
            eng_val  = _decode(raw_regs, reg)
            raw_val  = raw_regs[0] if raw_regs else 0

            # Delta
            prev = self._prev_values.get(reg.address)
            delta = (raw_val - prev) if prev is not None else 0
            self._prev_values[reg.address] = raw_val

            # Record in diagnostics
            from modbus.diagnostics import diagnostics_engine
            diagnostics_engine.record(
                self.session_id, fc=3, addr=reg.address,
                rtt_ms=rtt_ms, status="ok", response=raw_regs,
            )

            results.append({
                "address":     reg.address,
                "name":        reg.name,
                "raw":         raw_val,
                "value":       round(eng_val, 4),
                "unit":        reg.unit,
                "description": reg.description,
                "access":      reg.access,
                "timestamp":   time.time(),
                "rtt_ms":      round(rtt_ms, 2),
                "delta":       delta,
            })
        except (ModbusException, asyncio.TimeoutError) as e:
            rtt_ms = (time.perf_counter() - t0) * 1000
            from modbus.diagnostics import diagnostics_engine
            diagnostics_engine.record(
                self.session_id, fc=3, addr=reg.address,
                rtt_ms=rtt_ms, status="timeout", response=None,
            )
            results.append({"address": reg.address, "name": reg.name, "error": str(e), "unit": reg.unit})
        except Exception as e:
            results.append({"address": reg.address, "name": reg.name, "error": str(e), "unit": reg.unit})

    return results
```

Also add `_prev_values: dict = field(default_factory=dict, init=False)` to `ClientSession` dataclass.

- [ ] **Step 2: Add extra FC write methods to ClientSession**

```python
async def write_coil(self, address: int, value: bool) -> dict:
    """FC05 — write single coil."""
    if not await self._connect():
        return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
    try:
        resp = await asyncio.wait_for(
            self._client.write_coil(address, value, device_id=self.unit_id), timeout=10.0
        )
        return {"ok": not resp.isError(), "address": address, "value": value}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def write_coils(self, address: int, values: list[bool]) -> dict:
    """FC15 — write multiple coils."""
    if not await self._connect():
        return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
    try:
        resp = await asyncio.wait_for(
            self._client.write_coils(address, values, device_id=self.unit_id), timeout=10.0
        )
        return {"ok": not resp.isError(), "address": address, "count": len(values)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def write_registers(self, address: int, values: list[int]) -> dict:
    """FC16 — write multiple holding registers."""
    if not await self._connect():
        return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
    try:
        resp = await asyncio.wait_for(
            self._client.write_registers(address, values, device_id=self.unit_id), timeout=10.0
        )
        return {"ok": not resp.isError(), "address": address, "values": values}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def read_device_identification(self, read_code: int = 1, object_id: int = 0) -> dict:
    """FC43/14 — device identification."""
    if not await self._connect():
        return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
    try:
        resp = await asyncio.wait_for(
            self._client.read_device_information(
                read_code=read_code, object_id=object_id, device_id=self.unit_id
            ),
            timeout=10.0,
        )
        if resp.isError():
            return {"ok": False, "error": str(resp)}
        info = {}
        for obj_id, val in resp.information.items():
            info[obj_id] = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else str(val)
        return {"ok": True, "information": info}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

- [ ] **Step 3: Wire the new write methods into ClientManager**

```python
async def write_coil(self, session_id: str, address: int, value: bool) -> dict:
    session = self._sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "Session not found"}
    return await session.write_coil(address, value)

async def write_coils(self, session_id: str, address: int, values: list[bool]) -> dict:
    session = self._sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "Session not found"}
    return await session.write_coils(address, values)

async def write_registers(self, session_id: str, address: int, values: list[int]) -> dict:
    session = self._sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "Session not found"}
    return await session.write_registers(address, values)
```

- [ ] **Step 4: Commit**

```bash
git add backend/modbus/client.py
git commit -m "feat(modbus): add RTT measurement, delta tracking, FC15/FC16/FC43 to client"
```

---

## Task 6: New API Endpoints

**Files:**
- Modify: `backend/api/modbus_routes.py`

- [ ] **Step 1: Add new Pydantic models**

After the existing models in `modbus_routes.py`:

```python
class ExtendedWriteRequest(BaseModel):
    fc:       int         # 5, 6, 15, 16, 22
    addr:     int
    values:   list[int]  = Field(default_factory=list)   # raw uint16 list
    and_mask: int | None = None
    or_mask:  int | None = None

class SunSpecDiscoverRequest(BaseModel):
    host:    str
    port:    int = 502
    unit_id: int = 1

class SetWaveformRequest(BaseModel):
    address:    int
    type:       str        # "sine" | "ramp" | "script"
    amplitude:  float = 100.0
    period_s:   float = 300.0
    phase_rad:  float = 0.0
    dc_offset:  float = 0.0
    step:       int   = 1
    min_val:    int   = 0
    max_val:    int   = 65535
    start:      int   = 0
    expression: str   = ""

class SetExceptionRuleRequest(BaseModel):
    address:        int
    exception_code: int | None = None  # None = clear rule
    rate:           float = 0.0        # 0.0-1.0 probabilistic rate
```

- [ ] **Step 2: Add diagnostics GET endpoint**

```python
@router.get("/diagnostics/{session_id}")
async def get_diagnostics(session_id: str):
    """Get diagnostics stats for any session (simulator or client)."""
    from modbus.diagnostics import diagnostics_engine
    # Verify session exists
    sim = simulator_manager.get_session(session_id)
    client = client_manager.get_session(session_id)
    if sim is None and client is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"session_id": session_id, **diagnostics_engine.get_stats(session_id)}
```

- [ ] **Step 2b: Add parameterized registers GET endpoint for both sources**

The spec requires `GET /modbus/{source}/{session_id}/registers?fc=3&start=40001&count=50`.
The existing `GET /modbus/simulator/{session_id}/registers` and `GET /modbus/client/{session_id}/registers`
return all defined registers. The new endpoint allows the UI's FC tab selector to request a specific
function code and address range.

Add this after the existing per-session registers endpoints:

```python
from fastapi import Query

@router.get("/simulator/{session_id}/registers-range")
async def get_sim_registers_range(
    session_id: str,
    fc: int = Query(default=3, ge=1, le=4),
    start: int = Query(default=0, ge=0, le=65535),
    count: int = Query(default=50, ge=1, le=125),
):
    """Read a range of registers by FC and start address from a simulator session."""
    session = simulator_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if session._ctx is None:
        return {"session_id": session_id, "registers": []}
    try:
        store = session._ctx[session.unit_id]
        values = store.getValues(fc, start, count=count)
        return {
            "session_id": session_id,
            "fc": fc, "start": start, "count": len(values),
            "registers": [
                {"address": start + i, "raw": v, "value": v, "unit": ""}
                for i, v in enumerate(values)
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/client/{session_id}/registers-range")
async def get_client_registers_range(
    session_id: str,
    fc: int = Query(default=3, ge=1, le=4),
    start: int = Query(default=0, ge=0, le=65535),
    count: int = Query(default=50, ge=1, le=125),
):
    """Read a range of registers by FC and start address from a client session (on-demand poll)."""
    session = client_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if not await session._connect():
        raise HTTPException(status_code=503, detail="Cannot connect to device.")
    try:
        import asyncio as _asyncio
        if fc == 1:
            resp = await _asyncio.wait_for(
                session._client.read_coils(start, count=count, device_id=session.unit_id), timeout=10.0
            )
        elif fc == 2:
            resp = await _asyncio.wait_for(
                session._client.read_discrete_inputs(start, count=count, device_id=session.unit_id), timeout=10.0
            )
        elif fc == 3:
            resp = await _asyncio.wait_for(
                session._client.read_holding_registers(start, count=count, device_id=session.unit_id), timeout=10.0
            )
        elif fc == 4:
            resp = await _asyncio.wait_for(
                session._client.read_input_registers(start, count=count, device_id=session.unit_id), timeout=10.0
            )
        if resp.isError():
            raise HTTPException(status_code=400, detail=str(resp))
        values = list(resp.registers if hasattr(resp, "registers") else resp.bits)
        return {
            "session_id": session_id,
            "fc": fc, "start": start, "count": len(values),
            "registers": [
                {"address": start + i, "raw": v, "value": v, "unit": ""}
                for i, v in enumerate(values)
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Also add the TypeScript helper to `frontend/src/lib/api.ts` (do this alongside Task 8 Step 1):

```typescript
export async function fetchModbusRegistersRange(
  source: "simulator" | "client",
  sessionId: string,
  fc: number = 3,
  start: number = 0,
  count: number = 50
): Promise<{ registers: ModbusRegisterValue[] }> {
  const { data } = await api.get(
    `/modbus/${source}/${sessionId}/registers-range`,
    { params: { fc, start, count } }
  );
  return data;
}
```

Then in `ModbusDiagnostics.tsx` (Task 8 Step 2), the FC tab selector should call
`fetchModbusRegistersRange(source, selectedId, fcTab, 0, 50)` instead of
`fetchSimRegisters` / `fetchClientRegisters` so the tab buttons actually filter by FC.

- [ ] **Step 3: Add SunSpec discover endpoint**

```python
@router.post("/sunspec/discover")
async def sunspec_discover(req: SunSpecDiscoverRequest):
    """Probe a Modbus device for SunSpec model blocks."""
    from modbus.sunspec import SunSpecClient
    client = SunSpecClient()
    result = await client.discover(req.host, req.port, req.unit_id)
    return result
```

- [ ] **Step 4: Add extended write endpoint for simulator**

```python
@router.post("/simulator/{session_id}/write-extended")
async def write_sim_extended(session_id: str, req: ExtendedWriteRequest):
    session = simulator_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if req.fc in (5, 15):
        # Coil write — treat values as bools
        for i, v in enumerate(req.values):
            session.write_register(req.addr + i, v & 1)
    elif req.fc in (6, 16):
        for i, v in enumerate(req.values):
            session.write_register(req.addr + i, v & 0xFFFF)
    else:
        raise HTTPException(status_code=400, detail=f"FC{req.fc} not supported for simulator.")
    return {"ok": True, "fc": req.fc, "addr": req.addr, "values": req.values}
```

- [ ] **Step 5: Add extended write endpoint for client**

```python
@router.post("/client/{session_id}/write-extended")
async def write_client_extended(session_id: str, req: ExtendedWriteRequest):
    session = client_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if req.fc == 6:
        v = req.values[0] if req.values else 0
        result = await session.write_register(req.addr, v)
    elif req.fc == 16:
        result = await session.write_registers(req.addr, req.values)
    elif req.fc == 5:
        result = await session.write_coil(req.addr, bool(req.values[0]) if req.values else False)
    elif req.fc == 15:
        result = await session.write_coils(req.addr, [bool(v) for v in req.values])
    else:
        raise HTTPException(status_code=400, detail=f"FC{req.fc} not supported.")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Write failed"))
    return result
```

- [ ] **Step 6: Add waveform and exception injection endpoints for simulator**

```python
@router.post("/simulator/{session_id}/set-waveform")
async def set_sim_waveform(session_id: str, req: SetWaveformRequest):
    session = simulator_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    from modbus.waveforms import SineWave, Ramp, ScriptWave
    try:
        if req.type == "sine":
            wf = SineWave(req.amplitude, req.period_s, req.phase_rad, req.dc_offset)
        elif req.type == "ramp":
            wf = Ramp(req.start, req.step, req.min_val, req.max_val)
        elif req.type == "script":
            if not req.expression:
                raise HTTPException(status_code=400, detail="expression required for script waveform")
            wf = ScriptWave(req.expression)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown waveform type: '{req.type}'")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    session.set_waveform(req.address, wf)
    return {"ok": True, "session_id": session_id, "address": req.address, "type": req.type}


@router.post("/simulator/{session_id}/set-exception-rule")
async def set_sim_exception(session_id: str, req: SetExceptionRuleRequest):
    session = simulator_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    session.set_exception_rule(req.address, req.exception_code)
    if req.rate > 0:
        simulator_manager.set_exception_rate(session_id, req.rate)
    return {"ok": True, "session_id": session_id, "address": req.address,
            "exception_code": req.exception_code, "rate": req.rate}
```

- [ ] **Step 7: Commit**

```bash
git add backend/api/modbus_routes.py
git commit -m "feat(modbus): add diagnostics, SunSpec discover, extended write, waveform+exception endpoints"
```

---

## Task 7: LLM Chat Tools

**Files:**
- Modify: `backend/agent/tools/modbus.py`

The existing pattern is: `async def run_<toolname>(args: str) -> str` + `register(ToolDef(...))`.
Follow the same pattern exactly.

- [ ] **Step 1: Add `run_modbus_diagnostics`**

```python
async def run_modbus_diagnostics(args: str) -> str:
    import json
    from modbus.diagnostics import diagnostics_engine
    from modbus.simulator import simulator_manager
    from modbus.client import client_manager

    session_id = args.strip()
    if not session_id:
        return "[modbus_diagnostics] Usage: modbus_diagnostics <session_id>"

    sim = simulator_manager.get_session(session_id)
    client = client_manager.get_session(session_id)
    if sim is None and client is None:
        return f"[modbus_diagnostics] Session '{session_id}' not found. Use list_modbus_sessions first."

    stats = diagnostics_engine.get_stats(session_id)
    # Compact output for LLM: summarize instead of dumping all transactions
    exc_summary = [f"EC{e['ec']:02d}×{e['count']}" for e in stats["exceptions"][:5]]
    top_addrs = sorted(stats["heatmap"].items(), key=lambda x: -x[1])[:5]
    return json.dumps({
        "session_id":  session_id,
        "rtt":         stats["rtt"],
        "total_polls": stats["total_polls"],
        "req_rate":    stats["req_rate"],
        "exceptions":  exc_summary,
        "top_addresses": [{"addr": a, "count": c} for a, c in top_addrs],
        "recent_transactions": stats["transactions"][:5],
    }, indent=2)
```

- [ ] **Step 2: Add `run_modbus_write_multi`**

```python
async def run_modbus_write_multi(args: str) -> str:
    import json
    from modbus.simulator import simulator_manager
    from modbus.client import client_manager

    parts = args.strip().split()
    if len(parts) < 4:
        return "[modbus_write_multi] Usage: modbus_write_multi <session_id> <fc> <addr> <val1> [val2 ...]"

    session_id = parts[0]
    try:
        fc   = int(parts[1])
        addr = int(parts[2])
        vals = [int(v) for v in parts[3:]]
    except ValueError:
        return "[modbus_write_multi] fc, addr, and values must be integers."

    if fc not in (5, 6, 15, 16):
        return f"[modbus_write_multi] Supported FCs: 5 (coil), 6 (single reg), 15 (multi coil), 16 (multi reg). Got {fc}."

    sim = simulator_manager.get_session(session_id)
    if sim:
        for i, v in enumerate(vals):
            sim.write_register(addr + i, v & 0xFFFF)
        return json.dumps({"ok": True, "source": "simulator", "fc": fc, "addr": addr, "values": vals})

    client = client_manager.get_session(session_id)
    if not client:
        return f"[modbus_write_multi] Session '{session_id}' not found."

    if fc in (6,) and len(vals) == 1:
        result = await client.write_register(addr, vals[0])
    elif fc == 16:
        result = await client.write_registers(addr, vals)
    elif fc == 5 and len(vals) == 1:
        result = await client.write_coil(addr, bool(vals[0]))
    elif fc == 15:
        result = await client.write_coils(addr, [bool(v) for v in vals])
    else:
        return f"[modbus_write_multi] FC{fc} with {len(vals)} value(s) not supported."

    return json.dumps({**result, "source": "client", "fc": fc})
```

- [ ] **Step 3: Add `run_modbus_sunspec_discover`**

```python
async def run_modbus_sunspec_discover(args: str) -> str:
    import json
    from modbus.sunspec import SunSpecClient

    parts = args.strip().split()
    if not parts:
        return "[modbus_sunspec_discover] Usage: modbus_sunspec_discover <host> [port] [unit_id]"
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 502
    unit_id = int(parts[2]) if len(parts) > 2 else 1

    client = SunSpecClient()
    result = await client.discover(host, port, unit_id)
    if not result.get("found"):
        return json.dumps({"found": False, "host": host, "message": "No SunSpec marker found at addresses 40000, 50000, or 0."})

    # Summarize models for LLM
    models = [{"did": m["did"], "name": m["name"]} for m in result["models"]]
    return json.dumps({"found": True, "host": host, "base_address": result["base_address"], "models": models})
```

- [ ] **Step 4: Add `run_modbus_set_waveform`**

```python
async def run_modbus_set_waveform(args: str) -> str:
    import json
    from modbus.simulator import simulator_manager
    from modbus.waveforms import SineWave, Ramp, ScriptWave

    # Format: <session_id> <addr> <type> [params...]
    # sine: amplitude period_s [phase_rad] [dc_offset]
    # ramp: start step min max
    # script: <expression (rest of args joined)>
    parts = args.strip().split(maxsplit=3)
    if len(parts) < 3:
        return "[modbus_set_waveform] Usage: modbus_set_waveform <session_id> <addr> <sine|ramp|script> [params]"

    session_id = parts[0]
    try:
        addr = int(parts[1])
    except ValueError:
        return "[modbus_set_waveform] addr must be an integer."
    wf_type = parts[2].lower()
    params_str = parts[3] if len(parts) > 3 else ""
    param_parts = params_str.split()

    session = simulator_manager.get_session(session_id)
    if not session:
        return f"[modbus_set_waveform] Simulator session '{session_id}' not found."

    try:
        if wf_type == "sine":
            amplitude = float(param_parts[0]) if param_parts else 100.0
            period_s  = float(param_parts[1]) if len(param_parts) > 1 else 300.0
            dc_offset = float(param_parts[2]) if len(param_parts) > 2 else 0.0
            wf = SineWave(amplitude=amplitude, period_s=period_s, dc_offset=dc_offset)
        elif wf_type == "ramp":
            start   = int(param_parts[0]) if param_parts else 0
            step    = int(param_parts[1]) if len(param_parts) > 1 else 1
            min_val = int(param_parts[2]) if len(param_parts) > 2 else 0
            max_val = int(param_parts[3]) if len(param_parts) > 3 else 65535
            wf = Ramp(start=start, step=step, min_val=min_val, max_val=max_val)
        elif wf_type == "script":
            if not params_str.strip():
                return "[modbus_set_waveform] script requires an expression, e.g.: int(1000 * math.sin(t / 60) + 3000)"
            wf = ScriptWave(params_str.strip())
        else:
            return f"[modbus_set_waveform] Unknown type '{wf_type}'. Use: sine, ramp, script."
    except ValueError as e:
        return f"[modbus_set_waveform] {e}"

    session.set_waveform(addr, wf)
    return json.dumps({"ok": True, "session_id": session_id, "address": addr, "type": wf_type})
```

- [ ] **Step 5: Add `run_modbus_inject_exception`**

```python
async def run_modbus_inject_exception(args: str) -> str:
    import json
    from modbus.simulator import simulator_manager

    parts = args.strip().split()
    if len(parts) < 3:
        return "[modbus_inject_exception] Usage: modbus_inject_exception <session_id> <addr> <ec_code> [rate_0_to_1]"

    session_id = parts[0]
    try:
        addr    = int(parts[1])
        ec_code = int(parts[2])
        rate    = float(parts[3]) if len(parts) > 3 else 1.0
    except ValueError:
        return "[modbus_inject_exception] addr, ec_code must be integers; rate is a float 0-1."

    if not (1 <= ec_code <= 11):
        return f"[modbus_inject_exception] EC code must be 1-11. Common: 1=Illegal FC, 2=Illegal Addr, 3=Illegal Value, 4=Device Failure, 6=Device Busy."

    session = simulator_manager.get_session(session_id)
    if not session:
        return f"[modbus_inject_exception] Simulator session '{session_id}' not found."

    session.set_exception_rule(addr, ec_code)
    simulator_manager.set_exception_rate(session_id, rate)
    return json.dumps({
        "ok": True, "session_id": session_id, "address": addr,
        "exception_code": ec_code, "rate": rate,
        "note": f"EC{ec_code:02d} will be returned for reads of address {addr}",
    })
```

- [ ] **Step 6: Register all 5 tools**

At the bottom of the file, after existing `register()` calls:

```python
register(ToolDef(
    name="modbus_diagnostics", category="modbus",
    description="get RTT stats, exception counts, heatmap for a session",
    args_spec="<session_id>", runner=run_modbus_diagnostics,
    safety="read", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="modbus_write_multi", category="modbus",
    description="write registers/coils (FC5=coil, FC6=single, FC15=coils, FC16=multi)",
    args_spec="<id> <fc> <addr> <val...>", runner=run_modbus_write_multi,
    safety="write", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="modbus_sunspec_discover", category="modbus",
    description="discover SunSpec model blocks on a Modbus device",
    args_spec="<host> [port] [unit_id]", runner=run_modbus_sunspec_discover,
    safety="read", keywords={*_MODBUS_KW, "sunspec", "solar", "inverter", "discover"},
))

register(ToolDef(
    name="modbus_set_waveform", category="modbus",
    description="set waveform on simulator register: sine|ramp|script",
    args_spec="<sim_id> <addr> <type> [params]", runner=run_modbus_set_waveform,
    safety="write", keywords={*_MODBUS_KW, "waveform", "sine", "ramp", "script"},
))

register(ToolDef(
    name="modbus_inject_exception", category="modbus",
    description="inject Modbus exception on simulator address",
    args_spec="<sim_id> <addr> <ec_code> [rate]", runner=run_modbus_inject_exception,
    safety="write", keywords={*_MODBUS_KW, "exception", "inject", "fault"},
))
```

- [ ] **Step 7: Commit**

```bash
git add backend/agent/tools/modbus.py
git commit -m "feat(modbus): add 5 LLM chat tools: diagnostics, write_multi, sunspec, set_waveform, inject_exception"
```

---

## Task 8: Frontend — ModbusDiagnostics Component

**Files:**
- Create: `frontend/src/components/ModbusDiagnostics.tsx`

This is the God's View two-column tab. It uses `fetch` (via existing `api.ts` patterns with axios)
to poll two endpoints every 1s:
- `GET /modbus/diagnostics/{session_id}` — RTT, exceptions, timeline, transactions
- `GET /modbus/client/{session_id}/registers` or `GET /modbus/simulator/{session_id}/registers`

Look at `frontend/src/lib/api.ts` to find the axios instance (named `api`) and the existing
`fetchSimRegisters` / `fetchClientRegisters` functions as patterns to follow.

- [ ] **Step 1: Add API helper to `api.ts`**

Open `frontend/src/lib/api.ts` and add after the existing modbus helpers:

```typescript
export interface ModbusDiagnostics {
  session_id: string;
  rtt: { avg: number; p50: number; p95: number; p99: number };
  exceptions: Array<{ fc: number; addr: number; ec: number; count: number }>;
  heatmap: Record<number, number>;
  timeline: Array<{ ts: number; avg_rtt: number; count: number; exceptions: number }>;
  transactions: Array<{
    seq: number; ts: number; fc: number; addr: number;
    rtt_ms: number; status: string; ec: number | null; response: string;
  }>;
  req_rate: number;
  total_polls: number;
}

export async function fetchModbusDiagnostics(sessionId: string): Promise<ModbusDiagnostics> {
  const { data } = await api.get(`/modbus/diagnostics/${sessionId}`);
  return data;
}

export async function writeModbusExtended(
  source: "simulator" | "client",
  sessionId: string,
  payload: { fc: number; addr: number; values: number[] }
): Promise<{ ok: boolean; error?: string }> {
  const { data } = await api.post(`/modbus/${source}/${sessionId}/write-extended`, payload);
  return data;
}
```

- [ ] **Step 2: Create ModbusDiagnostics.tsx**

```tsx
// frontend/src/components/ModbusDiagnostics.tsx
import { useState, useEffect, useRef, useCallback } from "react";
import {
  fetchSimSessions, fetchClientSessions,
  fetchSimRegisters, fetchClientRegisters,
  fetchModbusDiagnostics, writeModbusExtended,
  type ModbusSession, type ModbusRegisterValue, type ModbusDiagnostics,
} from "../lib/api";

// ── EC code names ──────────────────────────────────────────────────────────
const EC_NAMES: Record<number, string> = {
  1: "Illegal FC", 2: "Illegal Addr", 3: "Illegal Val",
  4: "Device Fail", 5: "Ack", 6: "Device Busy",
  8: "Mem Parity Err", 10: "Gateway Path", 11: "Gateway No Resp",
};

const FC_LABELS: Record<number, string> = {
  1: "Coils (FC01)", 2: "DI (FC02)", 3: "HR (FC03)", 4: "IR (FC04)",
};

// ── KPI pill ──────────────────────────────────────────────────────────────
function KpiPill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded px-3 py-1.5 flex-1 text-center">
      <div className={`text-sm font-bold font-mono ${color}`}>{value}</div>
      <div className="text-[9px] text-[#8b949e]">{label}</div>
    </div>
  );
}

// ── RTT bar chart ─────────────────────────────────────────────────────────
function RttTimeline({ timeline }: { timeline: ModbusDiagnostics["timeline"] }) {
  if (timeline.length === 0) return (
    <div className="text-[#8b949e] text-xs text-center py-4">No data yet</div>
  );
  const maxRtt = Math.max(...timeline.map(b => b.avg_rtt), 1);
  const recent = timeline.slice(-24);
  return (
    <div className="flex items-end gap-0.5 h-10">
      {recent.map((b, i) => {
        const h = Math.max(2, Math.round((b.avg_rtt / maxRtt) * 40));
        const isExc = b.exceptions > 0;
        return (
          <div
            key={i}
            title={`${new Date(b.ts * 1000).toLocaleTimeString()}: ${b.avg_rtt}ms${isExc ? ` (${b.exceptions} exc)` : ""}`}
            style={{ height: h, minWidth: 8 }}
            className={`rounded-sm flex-1 ${isExc ? "bg-[#da3633]" : "bg-[#1f6feb]"}`}
          />
        );
      })}
    </div>
  );
}

// ── Exception frequency ───────────────────────────────────────────────────
function ExceptionBars({ exceptions }: { exceptions: ModbusDiagnostics["exceptions"] }) {
  if (exceptions.length === 0) return (
    <div className="text-[#8b949e] text-xs">No exceptions</div>
  );
  const max = Math.max(...exceptions.map(e => e.count), 1);
  return (
    <div className="flex flex-col gap-1">
      {exceptions.slice(0, 5).map((e, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-20 text-[#8b949e] text-[9px] truncate">
            EC{String(e.ec).padStart(2, "0")} {EC_NAMES[e.ec] ?? ""}
          </div>
          <div className="flex-1 bg-[#21262d] rounded h-1.5">
            <div
              className="bg-[#f78166] h-1.5 rounded"
              style={{ width: `${(e.count / max) * 100}%` }}
            />
          </div>
          <div className="text-[#f78166] text-[9px] w-5 text-right">{e.count}</div>
        </div>
      ))}
    </div>
  );
}

// ── Transaction log row ───────────────────────────────────────────────────
function TxRow({ t }: { t: ModbusDiagnostics["transactions"][0] }) {
  const isExc = t.status === "exception";
  const isWrite = t.fc >= 5 && t.fc <= 6 || t.fc === 15 || t.fc === 16;
  const rowBg = isExc ? "bg-[#2d1515]" : isWrite ? "bg-[#162030]" : "bg-[#1a2535] odd:bg-[#0d1117]";
  const textColor = isExc ? "text-[#f4b8b8]" : isWrite ? "text-[#b8d8e8]" : "text-[#c8d8f0]";
  return (
    <div className={`grid text-[9px] font-mono px-2 py-0.5 gap-1 ${rowBg} ${textColor}`}
      style={{ gridTemplateColumns: "32px 52px 44px 1fr 32px 36px" }}>
      <span>{t.seq}</span>
      <span>{new Date(t.ts * 1000).toLocaleTimeString()}</span>
      <span>FC{t.fc}</span>
      <span className="truncate">{t.addr} → {t.response}</span>
      <span className={isExc ? "text-[#f78166]" : "text-[#3fb950]"}>
        {isExc ? `EC${String(t.ec).padStart(2, "0")}` : "OK"}
      </span>
      <span>{t.rtt_ms}ms</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────
export function ModbusDiagnostics() {
  const [sessions, setSessions] = useState<ModbusSession[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [source, setSource] = useState<"simulator" | "client">("simulator");
  const [fcTab, setFcTab] = useState<number>(3);
  const [registers, setRegisters] = useState<ModbusRegisterValue[]>([]);
  const [prevRegs, setPrevRegs] = useState<Record<number, number>>({});
  const [changedAt, setChangedAt] = useState<Record<number, number>>({});
  const [diagnostics, setDiagnostics] = useState<ModbusDiagnostics | null>(null);
  const [paused, setPaused] = useState(false);
  const [writeAddr, setWriteAddr] = useState("");
  const [writeVal, setWriteVal] = useState("");
  const [writeFc, setWriteFc] = useState("6");
  const [editingAddr, setEditingAddr] = useState<number | null>(null);
  const [editVal, setEditVal] = useState("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load sessions
  useEffect(() => {
    async function load() {
      const [sims, clients] = await Promise.all([fetchSimSessions(), fetchClientSessions()]);
      const all: ModbusSession[] = [
        ...(sims.sessions ?? []).map((s: ModbusSession) => ({ ...s, _source: "simulator" })),
        ...(clients.sessions ?? []).map((s: ModbusSession) => ({ ...s, _source: "client" })),
      ];
      setSessions(all);
      if (!selectedId && all.length > 0) {
        setSelectedId(all[0].session_id);
        setSource((all[0] as any)._source ?? "simulator");
      }
    }
    load();
  }, []);

  // Poll data
  const poll = useCallback(async () => {
    if (!selectedId || paused) return;
    const [regData, diagData] = await Promise.allSettled([
      source === "simulator"
        ? fetchSimRegisters(selectedId)
        : fetchClientRegisters(selectedId),
      fetchModbusDiagnostics(selectedId),
    ]);
    if (regData.status === "fulfilled") {
      const newRegs: ModbusRegisterValue[] = regData.value.registers ?? [];
      setRegisters(newRegs);
      const now = Date.now();
      setChangedAt(prev => {
        const updated = { ...prev };
        newRegs.forEach(r => {
          if (r.raw !== undefined && prevRegs[r.address] !== undefined && prevRegs[r.address] !== r.raw) {
            updated[r.address] = now;
          }
        });
        return updated;
      });
      setPrevRegs(prev => {
        const updated = { ...prev };
        newRegs.forEach(r => { if (r.raw !== undefined) updated[r.address] = r.raw; });
        return updated;
      });
    }
    if (diagData.status === "fulfilled") setDiagnostics(diagData.value);
  }, [selectedId, source, paused, prevRegs]);

  useEffect(() => {
    poll();
    intervalRef.current = setInterval(poll, 1000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [poll]);

  async function handleWrite() {
    if (!selectedId || !writeAddr || !writeVal) return;
    await writeModbusExtended(source, selectedId, {
      fc: parseInt(writeFc), addr: parseInt(writeAddr), values: [parseInt(writeVal)],
    });
  }

  async function handleInlineWrite(addr: number) {
    if (!selectedId || !editVal) return;
    await writeModbusExtended(source, selectedId, { fc: 6, addr, values: [parseInt(editVal)] });
    setEditingAddr(null);
    setEditVal("");
  }

  function exportCsv() {
    if (!diagnostics) return;
    const rows = diagnostics.transactions.map(t =>
      `${t.seq},${new Date(t.ts * 1000).toISOString()},FC${t.fc},${t.addr},"${t.response}",${t.status},${t.rtt_ms}ms`
    );
    const csv = `#,Time,FC,Addr/Response,Status,RTT\n${rows.join("\n")}`;
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `modbus-${selectedId}-transactions.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  const now = Date.now();
  const rtt = diagnostics?.rtt ?? { avg: 0, p50: 0, p95: 0, p99: 0 };
  const excCount = diagnostics?.exceptions.reduce((s, e) => s + e.count, 0) ?? 0;

  return (
    <div className="flex gap-2 h-full min-h-0 p-2 bg-[#0d1117]">
      {/* LEFT: Register grid */}
      <div className="w-60 flex-shrink-0 bg-[#161b22] border border-[#30363d] rounded flex flex-col overflow-hidden">
        {/* Header */}
        <div className="bg-[#0d1117] px-2 py-1.5 border-b border-[#30363d]">
          <div className="flex justify-between items-center mb-1.5">
            <span className="text-[#c9d1d9] text-[10px] font-semibold">Live Registers</span>
            <select
              className="bg-[#161b22] border border-[#30363d] text-[#58a6ff] text-[9px] rounded px-1"
              value={selectedId}
              onChange={e => {
                setSelectedId(e.target.value);
                const s = sessions.find(x => x.session_id === e.target.value);
                setSource((s as any)?._source ?? "simulator");
              }}
            >
              {sessions.map(s => (
                <option key={s.session_id} value={s.session_id}>{s.label ?? s.session_id}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-1">
            {[3, 4, 1, 2].map(fc => (
              <button
                key={fc}
                onClick={() => setFcTab(fc)}
                className={`text-[8px] px-1.5 py-0.5 rounded border ${
                  fcTab === fc
                    ? "bg-[#1f6feb33] border-[#1f6feb] text-[#58a6ff]"
                    : "bg-[#21262d] border-transparent text-[#8b949e]"
                }`}
              >
                {FC_LABELS[fc]?.split(" ")[0]}
              </button>
            ))}
          </div>
        </div>
        {/* Column headers */}
        <div className="grid text-[8px] text-[#8b949e] px-2 py-1 bg-[#0d1117] border-b border-[#21262d]"
          style={{ gridTemplateColumns: "44px 52px 42px 28px 26px" }}>
          <span>Addr</span><span>Raw</span><span>Eng Val</span><span>Unit</span><span>Δ</span>
        </div>
        {/* Rows */}
        <div className="flex-1 overflow-y-auto">
          {registers.map((r, idx) => {
            const isChanged = changedAt[r.address] && now - changedAt[r.address] < 2000;
            const isEditing = editingAddr === r.address;
            const delta = r.delta ?? 0;
            const rowBg = isChanged ? "bg-[#1a1a0a]" : idx % 2 === 0 ? "bg-[#1a2535]" : "bg-transparent";
            return (
              <div
                key={r.address}
                className={`grid text-[8px] font-mono px-1.5 py-0.5 gap-1 ${rowBg} ${
                  isEditing ? "border-l-2 border-[#388bfd]" : ""
                }`}
                style={{ gridTemplateColumns: "44px 52px 42px 28px 26px" }}
              >
                <span className={isChanged ? "text-[#e3b341]" : "text-[#c8d8f0]"}>{r.address}</span>
                {isEditing ? (
                  <input
                    autoFocus
                    className="bg-[#0d1117] border border-[#388bfd] text-[#58a6ff] text-[8px] px-1 rounded w-full"
                    value={editVal}
                    onChange={e => setEditVal(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter") handleInlineWrite(r.address);
                      if (e.key === "Escape") { setEditingAddr(null); setEditVal(""); }
                    }}
                    onBlur={() => { setEditingAddr(null); setEditVal(""); }}
                  />
                ) : (
                  <span
                    className={`cursor-pointer ${isChanged ? "text-[#e3b341]" : "text-[#c8d8f0]"}`}
                    onClick={() => { setEditingAddr(r.address); setEditVal(String(r.raw ?? "")); }}
                  >
                    {r.raw ?? "—"}{delta > 0 ? " ▲" : delta < 0 ? " ▼" : ""}
                  </span>
                )}
                <span className={isChanged ? "text-[#e3b341]" : "text-[#c8d8f0]"}>
                  {r.value !== undefined ? String(r.value) : "—"}
                </span>
                <span className="text-[#8b949e]">{r.unit ?? ""}</span>
                <span className={delta > 0 ? "text-[#3fb950]" : delta < 0 ? "text-[#f78166]" : "text-[#8b949e]"}>
                  {delta !== 0 ? (delta > 0 ? `+${delta}` : delta) : "0"}
                </span>
              </div>
            );
          })}
          {registers.length === 0 && (
            <div className="text-[#8b949e] text-[10px] text-center py-4">
              {selectedId ? "Waiting for data…" : "Select a session"}
            </div>
          )}
        </div>
        {/* Write bar */}
        <div className="bg-[#0d1117] border-t border-[#30363d] p-1.5">
          <div className="text-[#8b949e] text-[8px] mb-1">Write register</div>
          <div className="flex gap-1">
            <input
              className="w-10 bg-[#161b22] border border-[#30363d] text-[#c9d1d9] text-[8px] px-1 py-0.5 rounded font-mono"
              placeholder="addr" value={writeAddr} onChange={e => setWriteAddr(e.target.value)}
            />
            <input
              className="flex-1 bg-[#161b22] border border-[#30363d] text-[#c9d1d9] text-[8px] px-1 py-0.5 rounded font-mono"
              placeholder="value" value={writeVal} onChange={e => setWriteVal(e.target.value)}
            />
            <select
              className="bg-[#161b22] border border-[#30363d] text-[#8b949e] text-[8px] rounded px-0.5"
              value={writeFc} onChange={e => setWriteFc(e.target.value)}
            >
              <option value="6">FC06</option>
              <option value="5">FC05</option>
            </select>
            <button
              onClick={handleWrite}
              className="bg-[#1f6feb] text-white text-[8px] px-2 py-0.5 rounded hover:bg-[#388bfd]"
            >
              Write
            </button>
          </div>
        </div>
      </div>

      {/* RIGHT: Diagnostics */}
      <div className="flex-1 flex flex-col gap-2 min-h-0 overflow-y-auto">
        {/* KPI bar */}
        <div className="flex gap-1.5">
          <KpiPill label="Avg RTT" value={`${rtt.avg}ms`} color="text-[#58a6ff]" />
          <KpiPill label="p50·p95·p99" value={`${rtt.p50}·${rtt.p95}·${rtt.p99}ms`} color="text-[#58a6ff]" />
          <KpiPill label="Exceptions" value={String(excCount)} color={excCount > 0 ? "text-[#f78166]" : "text-[#3fb950]"} />
          <KpiPill label="Req Rate" value={`${diagnostics?.req_rate ?? 0}/s`} color="text-[#d2a8ff]" />
        </div>

        {/* RTT Timeline */}
        <div className="bg-[#161b22] border border-[#30363d] rounded p-2">
          <div className="flex justify-between items-center mb-1">
            <span className="text-[#58a6ff] text-[9px]">RTT Timeline</span>
            <span className="text-[#8b949e] text-[8px]">▌ red = exception</span>
          </div>
          <RttTimeline timeline={diagnostics?.timeline ?? []} />
        </div>

        {/* Exception frequency */}
        <div className="bg-[#161b22] border border-[#30363d] rounded p-2">
          <div className="text-[#f78166] text-[9px] mb-2">⚠ Exception Frequency</div>
          <ExceptionBars exceptions={diagnostics?.exceptions ?? []} />
        </div>

        {/* Transaction log */}
        <div className="bg-[#161b22] border border-[#30363d] rounded flex-1 flex flex-col min-h-0 overflow-hidden">
          <div className="bg-[#0d1117] px-2 py-1.5 border-b border-[#30363d] flex justify-between items-center">
            <span className="text-[#c9d1d9] text-[9px]">Transaction Log</span>
            <div className="flex gap-1.5">
              <button
                onClick={() => setPaused(p => !p)}
                className="bg-[#21262d] text-[#8b949e] text-[8px] px-2 py-0.5 rounded hover:text-[#c9d1d9]"
              >
                {paused ? "▶ Resume" : "⏸ Pause"}
              </button>
              <button
                onClick={exportCsv}
                className="bg-[#21262d] text-[#8b949e] text-[8px] px-2 py-0.5 rounded hover:text-[#c9d1d9]"
              >
                CSV
              </button>
            </div>
          </div>
          {/* Header */}
          <div className="grid text-[8px] text-[#8b949e] px-2 py-1 bg-[#0d1117] border-b border-[#21262d]"
            style={{ gridTemplateColumns: "32px 52px 44px 1fr 32px 36px" }}>
            <span>#</span><span>Time</span><span>FC</span>
            <span>Addr / Response</span><span>St</span><span>RTT</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {(diagnostics?.transactions ?? []).map(t => <TxRow key={t.seq} t={t} />)}
            {!diagnostics?.transactions?.length && (
              <div className="text-[#8b949e] text-[10px] text-center py-4">No transactions yet</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ModbusDiagnostics.tsx frontend/src/lib/api.ts
git commit -m "feat(modbus): add ModbusDiagnostics God's View component (register grid + diagnostics)"
```

---

## Task 9: Wire Diagnostics Tab into ModbusPanel

**Files:**
- Modify: `frontend/src/components/ModbusPanel.tsx`

- [ ] **Step 1: Add import and tab**

At the top of `ModbusPanel.tsx`, add:

```typescript
import { ModbusDiagnostics } from "./ModbusDiagnostics";
```

Find the tab list in the component (it likely has a `type ModbusTab = "simulator" | "client" | ...`)
and add `"diagnostics"` to it.

Find the tab button array and add:

```tsx
{ id: "diagnostics", label: "Diagnostics" }
```

Find the tab content render (the large if/else or switch block) and add:

```tsx
{activeTab === "diagnostics" && <ModbusDiagnostics />}
```

- [ ] **Step 2: Build check**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: `✓ built in` with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ModbusPanel.tsx
git commit -m "feat(modbus): wire Diagnostics tab into ModbusPanel"
```

---

## Final Verification

- [ ] Run all backend tests:

```bash
cd backend && python -m pytest tests/test_modbus_diagnostics.py tests/test_modbus_waveforms.py tests/test_modbus_sunspec.py -v
```

Expected: all tests PASS

- [ ] Frontend build clean:

```bash
cd frontend && npm run build 2>&1 | grep -E "(error|warning|built in)"
```

Expected: `built in` line, no TypeScript errors

- [ ] Manual smoke test (with running backend + app):
  1. Open app → ModbusPanel → Create a simulator session (type "sma")
  2. Click "Diagnostics" tab — register grid appears left, diagnostics right
  3. Register values update every 1s; change a value via write bar → yellow highlight
  4. In chat: `list_modbus_sessions` → note the session ID
  5. In chat: `modbus_diagnostics <session_id>` → returns RTT stats
  6. In chat: `modbus_set_waveform <session_id> 30051 ramp 0 100 0 5000` → sets ramp
  7. RTT Timeline bars appear in Diagnostics tab
