"""
Modbus TCP Simulator — multi-session, register-map-aware.

Each SimulatorSession runs a pymodbus ModbusTcpServer on a dedicated port,
pre-populated with realistic random values derived from a RegisterDef map.
Values are refreshed every `update_interval` seconds to simulate live device
behaviour (random walk within min/max bounds).

Architecture:
  - SimulatorSession  : one TCP server per simulated device group
  - SimulatorManager  : dict of session_id → SimulatorSession, singleton
  - All servers run as asyncio background tasks on the app event loop.

Public API:
  manager.create_session(...)  → session_id: str
  manager.stop_session(sid)
  manager.list_sessions()      → list[dict]
  manager.read_registers(sid)  → list[dict]
  manager.write_register(sid, address, value)
  manager.set_waveform(sid, addr, waveform)
  manager.set_exception_rule(sid, addr, exception_code, rate)
  manager.stop_all()
"""

from __future__ import annotations
import asyncio
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pymodbus.datastore import (
    ModbusServerContext,
    ModbusSequentialDataBlock,
    ModbusDeviceContext,
    ModbusSparseDataBlock,
)
from pymodbus.server import ModbusTcpServer

from modbus.register_maps import RegisterDef
from modbus.diagnostics import diagnostics_engine


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sim_value(reg: RegisterDef, t: float = 0.0) -> float:
    """Generate a realistic simulated float value for a register."""
    span = reg.max_val - reg.min_val
    if span <= 0:
        return reg.min_val
    # Slow sinusoidal variation (period ~5 min) plus small noise
    phase = (t / 300.0) * 2 * math.pi
    mid   = (reg.min_val + reg.max_val) / 2.0
    amp   = span * 0.3
    return mid + amp * math.sin(phase + random.uniform(-0.1, 0.1)) + random.uniform(-span * 0.02, span * 0.02)


def _to_raw_uint16(value: float, reg: RegisterDef) -> int:
    """Convert engineering value to a single raw uint16 register word."""
    raw = int(value * reg.scale)
    # Clamp to uint16 range
    return max(0, min(65535, raw))


def _to_raw_int16(value: float, reg: RegisterDef) -> int:
    """Convert engineering value to a raw int16 word (stored as uint16 in Modbus)."""
    raw = int(value * reg.scale)
    raw = max(-32768, min(32767, raw))
    return raw & 0xFFFF          # two's complement


def _to_raw_uint32(value: float, reg: RegisterDef) -> tuple[int, int]:
    """Convert to a 32-bit unsigned value, split into (high_word, low_word)."""
    raw = int(value * reg.scale)
    raw = max(0, min(0xFFFFFFFF, raw))
    return (raw >> 16) & 0xFFFF, raw & 0xFFFF


def _to_raw_int32(value: float, reg: RegisterDef) -> tuple[int, int]:
    raw = int(value * reg.scale)
    raw = max(-2147483648, min(2147483647, raw))
    u32 = raw & 0xFFFFFFFF
    return (u32 >> 16) & 0xFFFF, u32 & 0xFFFF


def _build_register_block(
    regs: list[RegisterDef],
    t: float = 0.0,
    waveforms: dict[int, Any] | None = None,
) -> dict[int, int]:
    """Build a sparse {address: uint16_word} mapping for all registers.

    If ``waveforms`` is provided and an address is mapped, the waveform's
    ``tick(t)`` value (already a raw uint16) is used instead of the default
    sine+noise generator.
    """
    block: dict[int, int] = {}
    # Take a snapshot to avoid race with concurrent writes from set_waveform()
    waveforms_snapshot = dict(waveforms) if waveforms else {}
    for r in regs:
        # Check if a waveform is registered for this address
        if r.address in waveforms_snapshot:
            raw_val = waveforms_snapshot[r.address].tick(t)
            block[r.address] = int(max(0, min(65535, raw_val)))
            # For 32-bit types the second word is zeroed when waveform overrides
            if r.data_type in ("uint32", "int32", "float32"):
                block[r.address + 1] = 0
            continue

        val = _sim_value(r, t)
        dt = r.data_type
        if dt == "uint16":
            block[r.address] = _to_raw_uint16(val, r)
        elif dt == "int16":
            block[r.address] = _to_raw_int16(val, r)
        elif dt in ("uint32", "int32"):
            if dt == "uint32":
                hi, lo = _to_raw_uint32(val, r)
            else:
                hi, lo = _to_raw_int32(val, r)
            block[r.address]     = hi
            block[r.address + 1] = lo
        elif dt == "float32":
            import struct
            packed = struct.pack(">f", val)
            hi = (packed[0] << 8) | packed[1]
            lo = (packed[2] << 8) | packed[3]
            block[r.address]     = hi
            block[r.address + 1] = lo
    return block


# ── Instrumented datastore block ──────────────────────────────────────────────

class _InstrumentedBlock(ModbusSequentialDataBlock):
    """ModbusSequentialDataBlock that records diagnostics on every read and
    optionally injects Modbus exceptions for configured addresses.

    Parameters
    ----------
    session_id:
        The simulator session this block belongs to — used as the
        ``session_id`` passed to ``diagnostics_engine.record()``.
    fc:
        The Modbus function code this block is serving (3 = holding
        registers, 4 = input registers).
    exception_rules:
        Shared reference to ``SimulatorSession.exception_rules``.  The
        block does NOT own this dict — it is owned by ``SimulatorSession``.
    delay_ms_ref:
        A one-element list used as a mutable float reference so that the
        block can read the current ``response_delay_ms`` without holding a
        pointer to the session object directly.
    """

    def __init__(
        self,
        address: int,
        values: list[int],
        session_id: str,
        fc: int,
        exception_rules: dict[int, tuple[int, float]],
        delay_ms_ref: list[float],
    ) -> None:
        super().__init__(address, values)
        self._session_id = session_id
        self._fc = fc
        self._exception_rules = exception_rules
        self._delay_ms_ref = delay_ms_ref

    # pymodbus calls validate() then getValues() for every read request.
    # We override validate() so we can gate on exception_rules and record
    # diagnostics once per request (validate is the earliest hook).

    def validate(self, address: int, count: int = 1) -> bool:  # type: ignore[override]
        """Return False (triggering an exception response) when an exception
        injection rule fires for *address*.  Always records diagnostics."""
        t0 = time.perf_counter()
        rule = dict(self._exception_rules).get(address)
        if rule is not None:
            exc_code, rate = rule
            if rate > 0.0 and random.random() < rate:
                delay_ms = self._delay_ms_ref[0]
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000)
                rtt_ms = (time.perf_counter() - t0) * 1000 + random.uniform(1, 5)
                diagnostics_engine.record(
                    self._session_id, self._fc, address,
                    rtt_ms, "exception", None, exc_code,
                )
                # Returning False causes pymodbus to send an exception response
                return False
        return super().validate(address, count)

    def getValues(self, address: int, count: int = 1) -> list[int]:  # type: ignore[override]
        """Get register values and record a successful read to diagnostics."""
        t0 = time.perf_counter()
        values = super().getValues(address, count)
        rtt_ms = (time.perf_counter() - t0) * 1000 + random.uniform(1, 5)
        diagnostics_engine.record(
            self._session_id, self._fc, address,
            rtt_ms, "ok", values,
        )
        delay_ms = self._delay_ms_ref[0]
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
        return values


# ── Session dataclass ─────────────────────────────────────────────────────────

@dataclass
class SimulatorSession:
    session_id:      str
    label:           str
    host:            str
    port:            int
    unit_id:         int
    registers:       list[RegisterDef]
    update_interval: float = 5.0          # seconds between value refreshes
    device_type:     str   = ""
    device_name:     str   = ""
    response_delay_ms: float = 0.0        # simulated response latency

    # Per-address waveform overrides: addr -> WaveformBase instance
    _waveforms: dict = field(default_factory=dict, init=False, repr=False)

    # Exception injection rules: addr -> (exception_code, rate_0_to_1)
    exception_rules: dict = field(default_factory=dict, init=False, repr=False)

    # Mutable delay reference shared with instrumented blocks: [delay_ms]
    _delay_ms_ref: list = field(default_factory=lambda: [0.0], init=False, repr=False)

    # Runtime state (populated after start)
    _server:    Any = field(default=None, init=False, repr=False)
    _task:      Any = field(default=None, init=False, repr=False)
    _ctx:       Any = field(default=None, init=False, repr=False)
    _updater:   Any = field(default=None, init=False, repr=False)
    started_at: float = field(default=0.0, init=False)
    status:     str   = field(default="stopped", init=False)
    error:      str   = field(default="", init=False)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _make_context(self) -> ModbusServerContext:
        t = time.time()
        block_data = _build_register_block(self.registers, t, self._waveforms)

        # Build a sparse holding-register block from initial values
        # Fill gaps with 0
        max_addr = max(block_data.keys(), default=0) + 2
        hr_values = [block_data.get(i, 0) for i in range(max_addr)]

        self._delay_ms_ref[0] = self.response_delay_ms

        hr_block = _InstrumentedBlock(
            0, hr_values,
            session_id=self.session_id,
            fc=3,
            exception_rules=self.exception_rules,
            delay_ms_ref=self._delay_ms_ref,
        )
        ir_block = _InstrumentedBlock(
            0, list(hr_values),
            session_id=self.session_id,
            fc=4,
            exception_rules=self.exception_rules,
            delay_ms_ref=self._delay_ms_ref,
        )
        store = ModbusDeviceContext(
            di=ModbusSequentialDataBlock(0, [0] * 100),
            co=ModbusSequentialDataBlock(0, [0] * 100),
            ir=ir_block,
            hr=hr_block,
        )
        ctx = ModbusServerContext(devices={self.unit_id: store}, single=False)
        self._ctx = ctx
        return ctx

    def _refresh_values(self):
        """Update simulated register values in the datastore."""
        if self._ctx is None:
            return
        t = time.time()
        block_data = _build_register_block(self.registers, t, self._waveforms)
        # Keep delay ref in sync with field
        self._delay_ms_ref[0] = self.response_delay_ms
        try:
            store = self._ctx[self.unit_id]
            for addr, val in block_data.items():
                store.setValues(3, addr, [val])   # FC3 holding registers
                store.setValues(4, addr, [val])   # FC4 input registers mirror
        except Exception:
            pass

    async def _update_loop(self):
        """Background task: refresh register values every update_interval seconds."""
        while True:
            await asyncio.sleep(self.update_interval)
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._refresh_values)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    # ── Public ────────────────────────────────────────────────────────────────

    async def start(self):
        ctx = self._make_context()
        self._server = ModbusTcpServer(
            context=ctx,
            address=(self.host, self.port),
        )
        # serve_forever(background=True) starts server in a background task
        self._task = asyncio.create_task(
            self._server.serve_forever(),
            name=f"modbus-sim-{self.session_id}",
        )
        self._updater = asyncio.create_task(
            self._update_loop(),
            name=f"modbus-sim-upd-{self.session_id}",
        )
        self.started_at = time.time()
        self.status = "running"

    async def stop(self):
        self.status = "stopped"
        if self._updater and not self._updater.done():
            self._updater.cancel()
            try:
                await self._updater
            except asyncio.CancelledError:
                pass
        if self._server:
            try:
                await self._server.shutdown()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def read_registers(self) -> list[dict]:
        """Return current simulated values for all defined registers."""
        if self._ctx is None:
            return []
        results = []
        try:
            store = self._ctx[self.unit_id]
            for reg in self.registers:
                try:
                    raw = store.getValues(3, reg.address, count=1)[0]
                    # Decode engineering value
                    dt = reg.data_type
                    if dt == "int16":
                        raw_s = raw if raw < 32768 else raw - 65536
                        eng = raw_s / reg.scale
                    elif dt == "uint32":
                        raw2 = store.getValues(3, reg.address, count=2)
                        u32 = (raw2[0] << 16) | raw2[1]
                        eng = u32 / reg.scale
                    elif dt == "int32":
                        raw2 = store.getValues(3, reg.address, count=2)
                        u32 = (raw2[0] << 16) | raw2[1]
                        i32 = u32 if u32 < 2147483648 else u32 - 4294967296
                        eng = i32 / reg.scale
                    else:
                        eng = raw / reg.scale
                    results.append({
                        "address":     reg.address,
                        "name":        reg.name,
                        "raw":         raw,
                        "value":       round(eng, 4),
                        "unit":        reg.unit,
                        "description": reg.description,
                        "access":      reg.access,
                    })
                except Exception as e:
                    results.append({
                        "address": reg.address,
                        "name":    reg.name,
                        "error":   str(e),
                    })
        except Exception:
            pass
        return results

    def write_register(self, address: int, value: int) -> bool:
        """Write a raw uint16 value to a holding register."""
        if self._ctx is None:
            return False
        try:
            store = self._ctx[self.unit_id]
            store.setValues(3, address, [value & 0xFFFF])
            return True
        except Exception:
            return False

    def to_dict(self) -> dict:
        return {
            "session_id":      self.session_id,
            "label":           self.label,
            "host":            self.host,
            "port":            self.port,
            "unit_id":         self.unit_id,
            "device_type":     self.device_type,
            "device_name":     self.device_name,
            "register_count":  len(self.registers),
            "update_interval": self.update_interval,
            "response_delay_ms": self.response_delay_ms,
            "status":          self.status,
            "started_at":      self.started_at,
            "error":           self.error,
        }


# ── Manager (singleton) ───────────────────────────────────────────────────────

class SimulatorManager:
    def __init__(self):
        self._sessions: dict[str, SimulatorSession] = {}

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]

    def get_session(self, session_id: str) -> SimulatorSession | None:
        return self._sessions.get(session_id)

    async def create_session(
        self,
        registers: list[RegisterDef],
        *,
        label:            str   = "",
        host:             str   = "0.0.0.0",
        port:             int   = 5020,
        unit_id:          int   = 1,
        update_interval:  float = 5.0,
        device_type:      str   = "",
        device_name:      str   = "",
        response_delay_ms: float = 0.0,
    ) -> SimulatorSession:
        sid = str(uuid.uuid4())[:8]
        session = SimulatorSession(
            session_id=sid,
            label=label or f"sim-{sid}",
            host=host,
            port=port,
            unit_id=unit_id,
            registers=registers,
            update_interval=update_interval,
            device_type=device_type,
            device_name=device_name,
            response_delay_ms=response_delay_ms,
        )
        try:
            await session.start()
        except Exception as e:
            session.status = "error"
            session.error  = str(e)
        self._sessions[sid] = session
        return session

    async def stop_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        await session.stop()
        del self._sessions[session_id]
        return True

    def read_registers(self, session_id: str) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        return session.read_registers()

    def write_register(self, session_id: str, address: int, value: int) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        return session.write_register(address, value)

    def set_waveform(self, session_id: str, addr: int, waveform: Any) -> bool:
        """Register a waveform for a specific address.

        The waveform must have a ``tick(t: float) -> int`` method returning a
        raw uint16 value.

        Returns True if the session exists, False otherwise.
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        session._waveforms[addr] = waveform
        return True

    def set_exception_rule(
        self,
        session_id: str,
        addr: int,
        exception_code: int,
        rate: float,
    ) -> bool:
        """Set exception injection for an address.

        Parameters
        ----------
        session_id:
            Target simulator session.
        addr:
            Modbus register address to affect.
        exception_code:
            Modbus exception code (1=illegal function, 2=illegal data addr,
            3=illegal data value, 4=server device failure, etc.).
        rate:
            Probability in [0.0, 1.0] of injecting the exception on each
            request for this address.  0.0 effectively disables the rule.

        Returns True if the session exists, False otherwise.
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        if rate <= 0.0:
            session.exception_rules.pop(addr, None)
        else:
            session.exception_rules[addr] = (exception_code, rate)
        return True

    async def stop_all(self):
        for sid in list(self._sessions.keys()):
            await self.stop_session(sid)


# Global singleton
simulator_manager = SimulatorManager()
