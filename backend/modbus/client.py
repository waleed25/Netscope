"""
Modbus TCP/RTU/ASCII Client â€” multi-session, register-map-aware.

Each ClientSession maintains a persistent async Modbus client connection to
a real (or simulated) Modbus device and polls all mapped registers on a
configurable interval.

Architecture:
  - ClientSession  : one async client per device
  - ClientManager  : dict of session_id â†’ ClientSession, singleton
  - Poll loop runs as an asyncio background task.

Public API:
  manager.create_session(device_config, ...)  â†’ session_id
  manager.stop_session(sid)
  manager.list_sessions()          â†’ list[dict]
  manager.get_latest(sid)          â†’ list[dict]
  manager.read_now(sid)            â†’ list[dict]  (on-demand)
  manager.write_register(sid, address, value, unit_id)
"""

from __future__ import annotations
import asyncio
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pymodbus.exceptions import ModbusException

from modbus.register_maps import RegisterDef
from modbus.diagnostics import diagnostics_engine
from modbus.transport import decode_registers_raw, effective_byte_order, _reg_count
from modbus.interceptor import FrameStore, InterceptorWrap, ProxyServer
from modbus.diagnostics import JitterMonitor


logger = logging.getLogger(__name__)


# â”€â”€ Decode helpers (legacy â€” kept for read_range and backward compat) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _decode(regs: list[int], reg_def: RegisterDef) -> float:
    """Decode raw register word(s) to an engineering float value (legacy)."""
    dt = reg_def.data_type
    if dt == "uint16":
        return regs[0] / reg_def.scale
    if dt == "int16":
        raw = regs[0] if regs[0] < 32768 else regs[0] - 65536
        return raw / reg_def.scale
    if dt == "uint32":
        if len(regs) < 2:
            return 0.0
        u32 = (regs[0] << 16) | regs[1]
        return u32 / reg_def.scale
    if dt == "int32":
        if len(regs) < 2:
            return 0.0
        u32 = (regs[0] << 16) | regs[1]
        i32 = u32 if u32 < 2147483648 else u32 - 4294967296
        return i32 / reg_def.scale
    if dt == "float32":
        if len(regs) < 2:
            return 0.0
        packed = struct.pack(">HH", regs[0], regs[1])
        return struct.unpack(">f", packed)[0]
    return float(regs[0])


# â”€â”€ Session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class ClientSession:
    # Required fields
    session_id:   str
    label:        str
    host:         str
    port:         int
    unit_id:      int
    registers:    list[RegisterDef]

    # Optional â€” backward compatible
    poll_interval: float = 10.0
    device_type:  str   = ""
    device_name:  str   = ""

    # Transport config (new â€” all optional with defaults)
    transport:               str   = "tcp"
    serial_port:             str   = ""
    baudrate:                int   = 9600
    bytesize:                int   = 8
    parity:                  str   = "N"
    stopbits:                int   = 1
    timeout:                 float = 5.0   # connection timeout (seconds); 5.0 suits RTU links

    # Polling / decoding config (new)
    byte_order:              str   = "ABCD"
    zero_based_addressing:   bool  = True
    block_read_max_gap:      int   = 1
    block_read_max_size:     int   = 0   # 0 = use transport default (125)
    enabled_fcs:             list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 15, 16, 22, 23, 43])
    max_connections:         int   = 1

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

    # Internal state
    _client:       Any             = field(default=None, init=False, repr=False)
    _task:         Any             = field(default=None, init=False, repr=False)
    _connect_lock: Any             = field(default=None, init=False, repr=False)  # asyncio.Lock
    _latest:       list[dict]      = field(default_factory=list, init=False)
    _prev_values:  dict[int, int]  = field(default_factory=dict, init=False)
    _quality_state: dict           = field(default_factory=dict, init=False, repr=False)
    started_at:    float           = field(default=0.0, init=False)
    last_poll_at:  float           = field(default=0.0, init=False)
    poll_count:    int             = field(default=0, init=False)
    error_count:   int             = field(default=0, init=False)
    status:        str             = field(default="stopped", init=False)
    last_error:    str             = field(default="", init=False)

    def __post_init__(self):
        self._connect_lock = asyncio.Lock()
        self.frame_store = FrameStore(session_id=self.session_id)
        self._jitter     = JitterMonitor(target_interval_ms=self.poll_interval * 1000)
        # Initialise all registers with "uncertain" quality
        for r in self.registers:
            self._quality_state[r.address] = "uncertain"

    # â”€â”€ Internal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def set_poll_interval(self, interval_s: float) -> None:
        """Update poll interval and keep jitter monitor target in sync."""
        self.poll_interval = interval_s
        self._jitter.target_interval_ms = interval_s * 1000

    async def _connect(self) -> bool:
        """Ensure the pymodbus client exists and is connected. Thread-safe via asyncio.Lock."""
        async with self._connect_lock:
            if self._client is None:
                from modbus.transport import TransportConfig, build_client
                _host = self.host if self._proxy_host is None else self._proxy_host
                _port = self.port if self._proxy_port is None else self._proxy_port
                cfg = TransportConfig(
                    transport=self.transport,
                    host=_host,
                    port=_port,
                    serial_port=self.serial_port,
                    baudrate=self.baudrate,
                    bytesize=self.bytesize,
                    parity=self.parity,
                    stopbits=self.stopbits,
                    timeout=self.timeout,
                )
                self._client = build_client(cfg)
            if not self._client.connected:
                try:
                    connected = await self._client.connect()
                except Exception:
                    connected = False
                if not connected:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                    self._client = None
                    return False
            if self.interceptor_mode == "wrap" and self._interceptor_wrap is None:
                frame_type = "rtu" if self.transport in ("rtu", "ascii") else "tcp"
                self._interceptor_wrap = InterceptorWrap()
                self._interceptor_wrap.attach(self._client, self.frame_store, frame_type)
            return True

    async def _poll_once(self) -> list[dict]:
        from modbus.block_reader import coalesce, read_blocks

        if not await self._connect():
            raise ConnectionError(f"Cannot connect to {self.host}:{self.port}")

        # Filter registers whose FC is enabled
        _FC_MAP = {"holding": 3, "input": 4, "coil": 1, "discrete": 2}
        active = [r for r in self.registers if _FC_MAP.get(r.register_type, 3) in self.enabled_fcs]

        effective_max = self.block_read_max_size if self.block_read_max_size > 0 else 125
        blocks = coalesce(active, self.block_read_max_gap, effective_max)

        # address_offset is applied only to the wire FC call, not to the
        # fan-out offset calculation (reg.address - block.start_address).
        address_offset = 0 if self.zero_based_addressing else -1

        results_by_addr = await read_blocks(
            self._client, blocks, self.unit_id,
            self.session_id, self.byte_order, self._prev_values,
            address_offset=address_offset,
        )

        # Quality tagging
        now = time.time()
        stale_threshold = self.poll_interval * 3
        for addr, entry in results_by_addr.items():
            if "error" in entry:
                self._quality_state[addr] = "bad"
            elif (now - entry.get("timestamp", now)) > stale_threshold:
                self._quality_state[addr] = "stale"
            else:
                self._quality_state[addr] = "good"
            entry["quality"] = self._quality_state.get(addr, "uncertain")

        return [
            results_by_addr[r.address]
            for r in self.registers
            if r.address in results_by_addr
        ]

    async def _poll_loop(self):
        self.status = "connecting"
        while True:
            self._jitter.tick()
            try:
                result = await self._poll_once()
                self._latest  = result
                self.last_poll_at = time.time()
                self.poll_count  += 1
                self.status       = "polling"
                self.last_error   = ""
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.error_count += 1
                self.last_error   = str(e)
                self.status       = "error"
                # Reconnect on next cycle
                if self._client:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                    self._client = None
            try:
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                raise

    # â”€â”€ Public â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def start(self):
        self.started_at = time.time()

        if self.interceptor_mode == "proxy":
            self._proxy_server = ProxyServer(
                self.host, self.port, self.frame_store
            )
            try:
                local_port = await self._proxy_server.start()
            except Exception as exc:
                logger.warning(
                    "ClientSession %s: ProxyServer failed to start: %s — "
                    "falling back to direct connect",
                    self.session_id, exc,
                )
                self._proxy_server = None
            else:
                self._proxy_host = "127.0.0.1"
                self._proxy_port = local_port

        if self.traffic_log_path:
            self.frame_store.enable_file_log(Path(self.traffic_log_path))

        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"modbus-client-{self.session_id}",
        )

    async def stop(self):
        self.status = "stopped"
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._interceptor_wrap is not None:
            try:
                self._interceptor_wrap.detach(self._client)
            except Exception:
                pass
            self._interceptor_wrap = None
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        if self._proxy_server is not None:
            await self._proxy_server.stop()
            self._proxy_server = None
        self.frame_store.disable_file_log()

    async def read_now(self) -> list[dict]:
        """Perform a single on-demand poll (bypasses the background loop)."""
        return await self._poll_once()

    async def read_range(self, start: int, count: int, fc: int = 3) -> list[dict]:
        """
        Live read of `count` registers at Modbus 5-digit address `start`.

        Converts Modbus 5-digit notation â†’ 0-based wire address:
          FC3 (HR):    wire = start - 40001  (if start >= 40001, else start)
          FC4 (IR):    wire = start - 30001  (if start >= 30001, else start)
          FC2 (DI):    wire = start - 10001  (if start >= 10001, else start)
          FC1 (Coils): wire = start - 1      (if start >= 1,     else start)

        Results use the original 5-digit address for display and are enriched
        with name/unit from the background register map when available.
        """
        if fc not in self.enabled_fcs:
            raise ValueError(f"FC{fc} is disabled for this session")

        if not await self._connect():
            raise ConnectionError(f"Cannot connect to {self.host}:{self.port}")

        if fc == 3:
            wire = start - 40001 if start >= 40001 else start
        elif fc == 4:
            wire = start - 30001 if start >= 30001 else start
        elif fc == 2:
            wire = start - 10001 if start >= 10001 else start
        else:  # FC1 coils
            wire = start - 1 if start >= 1 else start
        wire = max(0, wire)

        t0 = time.perf_counter()
        try:
            if fc == 3:
                resp = await self._client.read_holding_registers(wire, count=count, device_id=self.unit_id)
            elif fc == 4:
                resp = await self._client.read_input_registers(wire, count=count, device_id=self.unit_id)
            elif fc == 1:
                resp = await self._client.read_coils(wire, count=count, device_id=self.unit_id)
            elif fc == 2:
                resp = await self._client.read_discrete_inputs(wire, count=count, device_id=self.unit_id)
            else:
                raise ValueError(f"Unsupported FC: {fc}")
        except ValueError:
            raise
        except Exception as exc:
            # pymodbus raised (includes ModbusIOException from cancelled state) — reset and report
            async with self._connect_lock:
                try:
                    if self._client:
                        self._client.close()
                except Exception:
                    pass
                self._client = None
            raise ConnectionError(f"Read failed FC{fc}@{wire}: {exc}") from exc

        rtt_ms = (time.perf_counter() - t0) * 1000

        if resp.isError():
            exc_code = getattr(resp, "exception_code", None)
            diagnostics_engine.record(
                self.session_id, fc, wire, rtt_ms, "exception", None, exc_code,
            )
            raise RuntimeError(f"Modbus error FC{fc}@{wire}: {resp}")

        raw_list = list(
            resp.registers if hasattr(resp, "registers") else [int(b) for b in resp.bits]
        )
        diagnostics_engine.record(
            self.session_id, fc, wire, rtt_ms, "ok", raw_list[:5], None,
        )

        # Build wire-address â†’ RegisterDef lookup for name/unit enrichment
        map_by_wire: dict[int, RegisterDef] = {r.address: r for r in self.registers}

        results: list[dict] = []
        for i, raw in enumerate(raw_list[:count]):
            display_addr = start + i
            reg_def = map_by_wire.get(wire + i)
            prev = self._prev_values.get(display_addr)
            if prev is None:
                delta = 0
            else:
                diff = (raw - prev) & 0xFFFF
                delta = diff if diff <= 32767 else diff - 65536
            self._prev_values[display_addr] = raw
            if reg_def:
                eff_bo = effective_byte_order(self.byte_order, reg_def.byte_order)
                eng_val, _ = decode_registers_raw([raw], reg_def, eff_bo)
            else:
                eng_val = float(raw)
            results.append({
                "address": display_addr,
                "raw":     raw,
                "value":   round(eng_val, 4),
                "unit":    reg_def.unit if reg_def else "",
                "name":    reg_def.name if reg_def else "",
                "delta":   delta,
            })
        return results

    async def write_register(self, address: int, value: int) -> dict:
        """Write a single holding register (raw uint16) â€” FC06."""
        if 6 not in self.enabled_fcs:
            return {"ok": False, "error": "FC6 (Write Single Register) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.write_register(address, value, device_id=self.unit_id)
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 6, address, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            diagnostics_engine.record(
                self.session_id, 6, address, rtt_ms,
                "ok", [value], None,
            )
            return {"ok": True, "address": address, "value": value}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def write_coil(self, address: int, value: bool) -> dict:
        """Write a single coil â€” FC05."""
        if 5 not in self.enabled_fcs:
            return {"ok": False, "error": "FC5 (Write Single Coil) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.write_coil(address=address, value=value, device_id=self.unit_id)
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 5, address, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            diagnostics_engine.record(
                self.session_id, 5, address, rtt_ms,
                "ok", [int(value)], None,
            )
            return {"ok": True, "address": address, "value": value}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def write_coils(self, address: int, values: list[bool]) -> dict:
        """Write multiple coils â€” FC15."""
        if 15 not in self.enabled_fcs:
            return {"ok": False, "error": "FC15 (Write Multiple Coils) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.write_coils(address=address, values=values, device_id=self.unit_id)
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 15, address, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            diagnostics_engine.record(
                self.session_id, 15, address, rtt_ms,
                "ok", [int(v) for v in values], None,
            )
            return {"ok": True, "address": address, "values": values}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def write_registers(self, address: int, values: list[int]) -> dict:
        """Write multiple holding registers â€” FC16."""
        if 16 not in self.enabled_fcs:
            return {"ok": False, "error": "FC16 (Write Multiple Registers) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.write_registers(address=address, values=values, device_id=self.unit_id)
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 16, address, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            diagnostics_engine.record(
                self.session_id, 16, address, rtt_ms,
                "ok", values, None,
            )
            return {"ok": True, "address": address, "values": values}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def mask_write_register(self, address: int, and_mask: int, or_mask: int) -> dict:
        """Mask write a register â€” FC22."""
        if 22 not in self.enabled_fcs:
            return {"ok": False, "error": "FC22 (Mask Write Register) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.mask_write_register(
                    address=address, and_mask=and_mask, or_mask=or_mask, device_id=self.unit_id
                )
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 22, address, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            diagnostics_engine.record(
                self.session_id, 22, address, rtt_ms,
                "ok", [and_mask, or_mask], None,
            )
            return {"ok": True, "address": address, "and_mask": and_mask, "or_mask": or_mask}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def read_write_registers(
        self,
        read_addr: int,
        read_count: int,
        write_addr: int,
        values: list[int],
    ) -> dict:
        """Read/write multiple registers â€” FC23."""
        if 23 not in self.enabled_fcs:
            return {"ok": False, "error": "FC23 (Read/Write Multiple Registers) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.readwrite_registers(
                    read_address=read_addr,
                    read_count=read_count,
                    write_address=write_addr,
                    write_registers=values,
                    device_id=self.unit_id,
                )
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 23, read_addr, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            read_regs = list(resp.registers)
            diagnostics_engine.record(
                self.session_id, 23, read_addr, rtt_ms,
                "ok", read_regs, None,
            )
            return {"ok": True, "read_address": read_addr, "values": read_regs}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def read_device_identification(self, read_code: int = 1, object_id: int = 0) -> dict:
        """Read device identification â€” FC43/14."""
        if 43 not in self.enabled_fcs:
            return {"ok": False, "error": "FC43 (Read Device Identification) is disabled for this session"}
        if not await self._connect():
            return {"ok": False, "error": f"Cannot connect to {self.host}:{self.port}"}
        try:
            t0 = time.perf_counter()
            resp = await self._client.read_device_information(
                    read_code=read_code, object_id=object_id, device_id=self.unit_id
                )
            rtt_ms = (time.perf_counter() - t0) * 1000
            if resp.isError():
                exc_code = getattr(resp, "exception_code", None)
                diagnostics_engine.record(
                    self.session_id, 43, 0, rtt_ms,
                    "exception", None, exc_code,
                )
                return {"ok": False, "error": str(resp)}
            diagnostics_engine.record(
                self.session_id, 43, 0, rtt_ms,
                "ok", None, None,
            )
            info = getattr(resp, "information", {})
            return {"ok": True, "information": info}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_values_with_delta(self) -> list[dict]:
        """Returns [{address, raw, delta}] for all addresses seen in the latest poll."""
        return [
            {"address": entry["address"], "raw": entry["raw"], "delta": entry.get("delta", 0)}
            for entry in self._latest
            if "error" not in entry
        ]

    def get_latest(self) -> list[dict]:
        return self._latest

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
            "poll_interval":   self.poll_interval,
            "poll_count":      self.poll_count,
            "error_count":     self.error_count,
            "last_poll_at":    self.last_poll_at,
            "last_error":      self.last_error,
            "status":          self.status,
            "started_at":      self.started_at,
            # Extended fields
            "transport":       self.transport,
            "serial_port":     self.serial_port,
            "baudrate":        self.baudrate,
            "bytesize":        self.bytesize,
            "parity":          self.parity,
            "stopbits":        self.stopbits,
            "timeout":         self.timeout,
            "byte_order":      self.byte_order,
            "zero_based_addressing": self.zero_based_addressing,
            "block_read_max_gap":    self.block_read_max_gap,
            "block_read_max_size":   self.block_read_max_size,
            "enabled_fcs":     self.enabled_fcs,
            "max_connections": self.max_connections,
            "interceptor_mode": self.interceptor_mode,
            "traffic_log_path": self.traffic_log_path,
            "traffic":          self.frame_store.counters(),
        }


# â”€â”€ Manager (singleton) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ClientManager:
    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]

    def get_session(self, session_id: str) -> ClientSession | None:
        return self._sessions.get(session_id)

    async def create_session(
        self,
        registers:   list[RegisterDef],
        *,
        label:         str   = "",
        host:          str   = "127.0.0.1",
        port:          int   = 502,
        unit_id:       int   = 1,
        poll_interval: float = 10.0,
        device_type:   str   = "",
        device_name:   str   = "",
        # Transport
        transport:              str   = "tcp",
        serial_port:            str   = "",
        baudrate:               int   = 9600,
        bytesize:               int   = 8,
        parity:                 str   = "N",
        stopbits:               int   = 1,
        timeout:                float = 5.0,
        # Polling / decoding
        byte_order:             str  = "ABCD",
        zero_based_addressing:  bool = True,
        block_read_max_gap:     int  = 1,
        block_read_max_size:    int  = 0,
        enabled_fcs:            list[int] | None = None,
        max_connections:        int  = 1,
        interceptor_mode: Literal["none", "wrap", "proxy"] = "wrap",
        traffic_log_path: str | None = None,
    ) -> ClientSession:
        sid = str(uuid.uuid4())[:8]
        session = ClientSession(
            session_id=sid,
            label=label or f"client-{sid}",
            host=host,
            port=port,
            unit_id=unit_id,
            registers=registers,
            poll_interval=poll_interval,
            device_type=device_type,
            device_name=device_name,
            transport=transport,
            serial_port=serial_port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=timeout,
            byte_order=byte_order,
            zero_based_addressing=zero_based_addressing,
            block_read_max_gap=block_read_max_gap,
            block_read_max_size=block_read_max_size,
            enabled_fcs=enabled_fcs if enabled_fcs is not None else [1, 2, 3, 4, 5, 6, 15, 16, 22, 23, 43],
            max_connections=max_connections,
            interceptor_mode=interceptor_mode,
            traffic_log_path=traffic_log_path,
        )
        await session.start()
        self._sessions[sid] = session
        return session

    async def stop_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        await session.stop()
        del self._sessions[session_id]
        return True

    def get_latest(self, session_id: str) -> list[dict] | None:
        session = self._sessions.get(session_id)
        return session.get_latest() if session else None

    def get_values_with_delta(self, session_id: str) -> list[dict]:
        session = self._sessions.get(session_id)
        if session is None:
            return []
        return session.get_values_with_delta()

    async def read_now(self, session_id: str) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        return await session.read_now()

    async def read_range(
        self, session_id: str, start: int, count: int, fc: int = 3
    ) -> list[dict]:
        """Live read of arbitrary register range. See ClientSession.read_range for details."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.read_range(start, count, fc)

    async def write_register(
        self, session_id: str, address: int, value: int
    ) -> dict:
        session = self._sessions.get(session_id)
        if not session:
            return {"ok": False, "error": "Session not found"}
        return await session.write_register(address, value)

    async def write_coil(self, session_id: str, addr: int, value: bool) -> dict:
        """FC05 â€” write single coil."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.write_coil(addr, value)

    async def write_coils(self, session_id: str, addr: int, values: list[bool]) -> dict:
        """FC15 â€” write multiple coils."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.write_coils(addr, values)

    async def write_registers(self, session_id: str, addr: int, values: list[int]) -> dict:
        """FC16 â€” write multiple registers."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.write_registers(addr, values)

    async def mask_write_register(
        self, session_id: str, addr: int, and_mask: int, or_mask: int
    ) -> dict:
        """FC22 â€” mask write register."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.mask_write_register(addr, and_mask, or_mask)

    async def read_write_registers(
        self,
        session_id: str,
        read_addr: int,
        read_count: int,
        write_addr: int,
        values: list[int],
    ) -> dict:
        """FC23 â€” read/write multiple registers."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.read_write_registers(read_addr, read_count, write_addr, values)

    async def read_device_identification(
        self, session_id: str, read_code: int = 1, object_id: int = 0
    ) -> dict:
        """FC43/14 â€” read device identification."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return await session.read_device_identification(read_code, object_id)

    async def stop_all(self):
        for sid in list(self._sessions.keys()):
            await self.stop_session(sid)


# Global singleton
client_manager = ClientManager()
