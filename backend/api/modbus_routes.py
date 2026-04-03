"""
REST API routes for the Modbus Simulator + Client subsystem.

Endpoints:
  # Device maps
  GET  /modbus/device-types
  GET  /modbus/device-types/{key}

  # Device list upload
  POST /modbus/devices/upload
  GET  /modbus/devices/template

  # Simulator
  GET    /modbus/simulator/sessions
  POST   /modbus/simulator/create
  POST   /modbus/simulator/create-from-devices
  DELETE /modbus/simulator/{session_id}
  GET    /modbus/simulator/{session_id}/registers
  POST   /modbus/simulator/{session_id}/write
  POST   /modbus/simulator/{session_id}/waveform
  POST   /modbus/simulator/{session_id}/exception_rule

  # Client
  GET    /modbus/client/sessions
  POST   /modbus/client/create
  POST   /modbus/client/create-from-devices
  DELETE /modbus/client/{session_id}
  GET    /modbus/client/{session_id}/registers
  POST   /modbus/client/{session_id}/read-now
  POST   /modbus/client/{session_id}/write

  # Generic source endpoints (simulator or client)
  GET  /modbus/{source}/{session_id}/registers
  POST /modbus/{source}/{session_id}/write

  # Diagnostics
  GET  /modbus/diagnostics/{session_id}

  # SunSpec
  POST /modbus/sunspec/discover

  # Scanner
  POST /modbus/scan
"""

from __future__ import annotations
import io
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from config import settings
from api.websocket import _check_ws_origin
from modbus.register_maps import DEVICE_TYPES, lookup, registers_summary
from modbus.device_loader import load_file, devices_to_dict
from modbus.simulator import simulator_manager
from modbus.client import client_manager
from modbus.scanner import scan_network, scan_hosts

import logging as _logging

logger = _logging.getLogger(__name__)

router = APIRouter(prefix="/modbus", tags=["modbus"])


# ── Path validation helper ─────────────────────────────────────────────────────

def _validate_log_path(raw: str) -> Path:
    """Resolve and validate that the log path is within the allowed logs directory."""
    # Allow paths only inside the project's backend/logs directory
    allowed_dir = (Path(__file__).parent.parent / "logs").resolve()
    allowed_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(raw).resolve()
    try:
        candidate.relative_to(allowed_dir)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Log path must be inside {allowed_dir}",
        )
    if candidate.suffix not in (".jsonl", ".log", ".txt"):
        raise HTTPException(
            status_code=400,
            detail="Log file must have .jsonl, .log, or .txt extension",
        )
    return candidate


# ── Pydantic request models ────────────────────────────────────────────────────

class CreateSimRequest(BaseModel):
    device_type:     str   = ""
    device_name:     str   = ""
    host:            str   = "127.0.0.1"   # loopback-only by default — set "0.0.0.0" explicitly for LAN access
    port:            int   = 5020
    unit_id:         int   = 1
    label:           str   = ""
    update_interval: float = 5.0


class CreateSimFromDevicesRequest(BaseModel):
    devices:   list[dict] = Field(default_factory=list)
    base_port: int        = 5020


class WriteRegisterRequest(BaseModel):
    address: int = Field(..., ge=0, le=65535)
    value:   int = Field(..., ge=0, le=65535)


class CreateClientRequest(BaseModel):
    host:          str   = "127.0.0.1"
    port:          int   = 502
    unit_id:       int   = 1
    device_type:   str   = ""
    device_name:   str   = ""
    label:         str   = ""
    poll_interval: float = 10.0
    # Transport
    transport:              str       = "tcp"
    serial_port:            str       = ""
    baudrate:               int       = 9600
    bytesize:               int       = 8
    parity:                 str       = "N"
    stopbits:               int       = 1
    timeout:                float     = 5.0
    # Polling / decoding
    byte_order:             str       = "ABCD"
    zero_based_addressing:  bool      = True
    block_read_max_gap:     int       = 1
    block_read_max_size:    int       = 0
    enabled_fcs:            list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 15, 16, 22, 23, 43])
    max_connections:        int       = 1
    interceptor_mode: str = "wrap"
    traffic_log_path: str | None = None

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, v: str) -> str:
        allowed = ("tcp", "rtu", "ascii")
        if v not in allowed:
            raise ValueError(f"transport must be one of {allowed}")
        return v

    @field_validator("parity")
    @classmethod
    def validate_parity(cls, v: str) -> str:
        allowed = ("N", "E", "O")
        if v not in allowed:
            raise ValueError(f"parity must be one of {allowed}")
        return v

    @field_validator("byte_order")
    @classmethod
    def validate_byte_order(cls, v: str) -> str:
        allowed = ("ABCD", "BADC", "CDAB", "DCBA")
        if v not in allowed:
            raise ValueError(f"byte_order must be one of {allowed}")
        return v

    @field_validator("enabled_fcs")
    @classmethod
    def validate_enabled_fcs(cls, v: list[int]) -> list[int]:
        valid = {1, 2, 3, 4, 5, 6, 15, 16, 22, 23, 43}
        invalid = set(v) - valid
        if invalid:
            raise ValueError(f"Invalid FC values: {invalid}. Allowed: {sorted(valid)}")
        return v

    @field_validator("max_connections")
    @classmethod
    def validate_max_connections(cls, v: int) -> int:
        if not (1 <= v <= 10):
            raise ValueError("max_connections must be between 1 and 10")
        return v

    @field_validator("interceptor_mode")
    @classmethod
    def validate_interceptor_mode(cls, v: str) -> str:
        allowed = ("none", "wrap", "proxy")
        if v not in allowed:
            raise ValueError(f"interceptor_mode must be one of {allowed}")
        return v


class UpdateSessionRequest(BaseModel):
    enabled_fcs:   list[int] | None = None
    byte_order:    str | None       = None
    poll_interval: float | None     = None

    @field_validator("enabled_fcs")
    @classmethod
    def validate_enabled_fcs(cls, v: list[int] | None) -> list[int] | None:
        if v is not None:
            valid = {1, 2, 3, 4, 5, 6, 15, 16, 22, 23, 43}
            invalid = set(v) - valid
            if invalid:
                raise ValueError(f"Invalid FC values: {invalid}. Allowed: {sorted(valid)}")
        return v

    @field_validator("byte_order")
    @classmethod
    def validate_byte_order(cls, v: str | None) -> str | None:
        if v is not None:
            allowed = ("ABCD", "BADC", "CDAB", "DCBA")
            if v not in allowed:
                raise ValueError(f"byte_order must be one of {allowed}")
        return v


class CreateClientFromDevicesRequest(BaseModel):
    devices:       list[dict] = Field(default_factory=list)
    poll_interval: float      = 10.0


class ScanRequest(BaseModel):
    targets:    str         = ""          # CIDR or comma-separated IPs
    ports:      list[int]   = Field(default_factory=lambda: [502])
    unit_ids:   list[int]   = Field(default_factory=lambda: list(range(1, 5)))
    timeout:    float       = 2.0


# ── Device maps ────────────────────────────────────────────────────────────────

@router.get("/device-types")
async def list_device_types():
    """List all registered device-type keywords and their register counts."""
    summary = {
        key: {"count": len(regs), "registers": registers_summary(regs)}
        for key, regs in DEVICE_TYPES.items()
    }
    return {"device_types": summary}


@router.get("/device-types/{key}")
async def get_device_type(key: str):
    """Return the full register map for a given key."""
    regs = DEVICE_TYPES.get(key.lower())
    if regs is None:
        raise HTTPException(status_code=404, detail=f"Unknown device type key: '{key}'")
    return {
        "key": key,
        "registers": [
            {
                "address":     r.address,
                "name":        r.name,
                "unit":        r.unit,
                "scale":       r.scale,
                "data_type":   r.data_type,
                "access":      r.access,
                "min_val":     r.min_val,
                "max_val":     r.max_val,
                "description": r.description,
            }
            for r in regs
        ],
    }


# ── Device list upload ─────────────────────────────────────────────────────────

@router.post("/devices/upload")
async def upload_device_list(file: UploadFile = File(...)):
    """Upload a CSV or Excel device list; returns matched devices with register maps."""
    filename = file.filename or "upload.csv"
    content  = await file.read()
    try:
        devices = load_file(filename, content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {exc}")
    return {
        "filename":     filename,
        "device_count": len(devices),
        "devices":      devices_to_dict(devices),
    }


@router.get("/devices/template")
async def device_template():
    """Download a CSV template for the device list upload."""
    csv_content = (
        "ip,port,unit_id,device_type,device_name,description\n"
        "192.168.1.10,502,1,inverter,SMA Tripower 25000TL,Main building PV\n"
        "192.168.1.11,502,1,inverter,Fronius Symo 15.0-3,Warehouse PV\n"
        "192.168.1.20,502,1,meter,Carlo Gavazzi EM24,Grid meter\n"
        "192.168.1.30,502,1,battery,BYD HVM 11.0,Battery storage\n"
        "192.168.1.40,502,1,drive,ABB ACS880,Pump drive\n"
        "192.168.1.50,502,1,plc,Generic PLC,Control unit\n"
    )
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=modbus_devices_template.csv"},
    )


# ── Simulator endpoints ────────────────────────────────────────────────────────

@router.get("/simulator/sessions")
async def list_sim_sessions():
    return {"sessions": simulator_manager.list_sessions()}


@router.post("/simulator/create")
async def create_sim_session(req: CreateSimRequest):
    _key, registers = lookup(req.device_type, req.device_name)
    if not registers:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No register map found for device_type='{req.device_type}' "
                f"device_name='{req.device_name}'. "
                "Use GET /modbus/device-types for valid keys."
            ),
        )
    session = await simulator_manager.create_session(
        registers,
        label=req.label,
        host=req.host,
        port=req.port,
        unit_id=req.unit_id,
        update_interval=req.update_interval,
        device_type=req.device_type,
        device_name=req.device_name,
    )
    return session.to_dict()


@router.post("/simulator/create-from-devices")
async def create_sim_from_devices(req: CreateSimFromDevicesRequest):
    """Create one simulator session per device in the uploaded device list."""
    created = []
    port = req.base_port
    for d in req.devices:
        device_type = d.get("device_type", "")
        device_name = d.get("device_name", "")
        label       = d.get("label", "") or d.get("description", "") or f"{device_name} sim"
        unit_id     = int(d.get("unit_id", 1) or 1)
        _key, registers = lookup(device_type, device_name)
        if not registers:
            continue
        session = await simulator_manager.create_session(
            registers,
            label=label,
            host="0.0.0.0",
            port=port,
            unit_id=unit_id,
            device_type=device_type,
            device_name=device_name,
        )
        created.append(session.to_dict())
        port += 1
    return {"created": len(created), "sessions": created}


@router.delete("/simulator/{session_id}")
async def stop_sim_session(session_id: str):
    ok = await simulator_manager.stop_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Simulator session '{session_id}' not found.")
    return {"status": "stopped", "session_id": session_id}


@router.get("/simulator/{session_id}/registers")
async def get_sim_registers(session_id: str):
    session = simulator_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Simulator session '{session_id}' not found.")
    return {
        "session_id": session_id,
        "registers":  session.read_registers(),
    }


@router.post("/simulator/{session_id}/write")
async def write_sim_register(session_id: str, req: WriteRegisterRequest):
    session = simulator_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Simulator session '{session_id}' not found.")
    ok = session.write_register(req.address, req.value)
    if not ok:
        raise HTTPException(status_code=400, detail="Write failed — session context not ready.")
    return {"ok": True, "address": req.address, "value": req.value}


# ── Client endpoints ───────────────────────────────────────────────────────────

@router.get("/client/sessions")
async def list_client_sessions():
    return {"sessions": client_manager.list_sessions()}


@router.post("/client/create")
async def create_client_session(req: CreateClientRequest):
    _key, registers = lookup(req.device_type, req.device_name)
    # Empty register map is fine — session still connects; on-demand reads work via generic endpoint
    # Validate log path before passing to session (prevents path traversal)
    validated_log_path: str | None = None
    if req.traffic_log_path:
        validated_log_path = str(_validate_log_path(req.traffic_log_path))

    session = await client_manager.create_session(
        registers,
        label=req.label,
        host=req.host,
        port=req.port,
        unit_id=req.unit_id,
        poll_interval=req.poll_interval,
        device_type=req.device_type,
        device_name=req.device_name,
        transport=req.transport,
        serial_port=req.serial_port,
        baudrate=req.baudrate,
        bytesize=req.bytesize,
        parity=req.parity,
        stopbits=req.stopbits,
        timeout=req.timeout,
        byte_order=req.byte_order,
        zero_based_addressing=req.zero_based_addressing,
        block_read_max_gap=req.block_read_max_gap,
        block_read_max_size=req.block_read_max_size,
        enabled_fcs=req.enabled_fcs,
        max_connections=req.max_connections,
        interceptor_mode=req.interceptor_mode,
        traffic_log_path=validated_log_path,
    )
    return session.to_dict()


@router.patch("/client/{session_id}")
async def update_client_session(session_id: str, req: UpdateSessionRequest):
    """Update mutable session settings (enabled_fcs, byte_order, poll_interval)."""
    session = client_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Client session '{session_id}' not found.")
    if req.enabled_fcs is not None:
        session.enabled_fcs = req.enabled_fcs
    if req.byte_order is not None:
        session.byte_order = req.byte_order
    if req.poll_interval is not None:
        session.set_poll_interval(req.poll_interval)
    return session.to_dict()


@router.post("/client/create-from-devices")
async def create_client_from_devices(req: CreateClientFromDevicesRequest):
    """Create one client poll session per device in the uploaded list."""
    created = []
    for d in req.devices:
        device_type = d.get("device_type", "")
        device_name = d.get("device_name", "")
        host        = d.get("ip", d.get("host", "127.0.0.1"))
        port        = int(d.get("port", 502) or 502)
        unit_id     = int(d.get("unit_id", 1) or 1)
        label       = d.get("label", "") or d.get("description", "") or f"{device_name} @ {host}"
        _key, registers = lookup(device_type, device_name)
        if not registers:
            continue
        session = await client_manager.create_session(
            registers,
            label=label,
            host=host,
            port=port,
            unit_id=unit_id,
            poll_interval=req.poll_interval,
            device_type=device_type,
            device_name=device_name,
        )
        created.append(session.to_dict())
    return {"created": len(created), "sessions": created}


@router.delete("/client/{session_id}")
async def stop_client_session(session_id: str):
    ok = await client_manager.stop_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Client session '{session_id}' not found.")
    return {"status": "stopped", "session_id": session_id}


@router.get("/client/{session_id}/registers")
async def get_client_registers(
    session_id: str,
    fc: int | None = None,
    start: int | None = None,
    count: int | None = None,
):
    """
    Returns client register data.
    - When fc/start/count are provided (ModbusDiagnostics RegGrid): live on-demand read
      with 5-digit Modbus address conversion (40001→wire 0, etc.).
    - When called without params (ModbusPanel SessionCard): returns last polled values.
    """
    session = client_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Client session '{session_id}' not found.")

    if fc is not None and start is not None and count is not None:
        # Live read — used by ModbusDiagnostics RegGrid
        try:
            registers = await client_manager.read_range(session_id, start, count, fc)
        except ConnectionError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return {"session_id": session_id, "registers": registers}

    # Cached poll data — used by ModbusPanel SessionCard
    data = client_manager.get_latest(session_id)
    return {"session_id": session_id, "registers": data or []}


@router.post("/client/{session_id}/read-now")
async def client_read_now(session_id: str):
    data = await client_manager.read_now(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Client session '{session_id}' not found.")
    return {"session_id": session_id, "registers": data}


@router.post("/client/{session_id}/write")
async def write_client_register(session_id: str, req: WriteRegisterRequest):
    session = client_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Client session '{session_id}' not found.")
    result = await session.write_register(req.address, req.value)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Write failed"))
    return result


# ── Scanner endpoint ───────────────────────────────────────────────────────────

@router.post("/scan")
async def run_scan(req: ScanRequest):
    """
    Scan for Modbus devices.
    `targets` can be:
      - CIDR notation:          "192.168.1.0/24"
      - Comma-separated IPs:    "192.168.1.10,192.168.1.11"
      - Single IP:              "192.168.1.10"
    """
    targets = req.targets.strip()
    if not targets:
        raise HTTPException(status_code=400, detail="'targets' must be a CIDR or comma-separated IP list.")

    try:
        if "/" in targets:
            results = await scan_network(
                targets,
                ports=req.ports,
                unit_ids=req.unit_ids,
                timeout=req.timeout,
            )
        else:
            hosts = [h.strip() for h in targets.split(",") if h.strip()]
            results = await scan_hosts(
                hosts,
                ports=req.ports,
                unit_ids=req.unit_ids,
                timeout=req.timeout,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan error: {exc}")

    return {
        "targets": targets,
        "found":   len(results),
        "results": results,
    }


# ── Diagnostics endpoint ───────────────────────────────────────────────────────

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


# ── Traffic interceptor endpoints ─────────────────────────────────────────────

class TrafficLogConfig(BaseModel):
    enabled: bool
    path: str | None = None


@router.websocket("/client/{session_id}/traffic/ws")
async def modbus_traffic_ws(ws: WebSocket, session_id: str):
    """Stream raw captured frames to a WebSocket subscriber."""
    if not _check_ws_origin(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
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
    except Exception as exc:
        logger.warning(
            "modbus_traffic_ws[%s]: unexpected error: %s", session_id, exc
        )
    finally:
        await session.frame_store.remove_ws(ws)


@router.post("/client/{session_id}/traffic/log")
async def set_traffic_log(session_id: str, body: TrafficLogConfig):
    """Enable or disable JSONL file logging for a client session."""
    session = client_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.enabled and body.path:
        safe_path = _validate_log_path(body.path)
        session.frame_store.enable_file_log(safe_path)
    else:
        session.frame_store.disable_file_log()
    return {"ok": True}


@router.get("/client/{session_id}/traffic")
async def get_traffic(session_id: str, n: int = 100):
    """Return the most recent N captured frames from a client session."""
    session = client_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    n = max(1, min(n, 10_000))
    return {
        "frames": [asdict(f) for f in session.frame_store.get_recent(n)],
        **session.frame_store.counters(),
    }


# ── SunSpec discover endpoint ──────────────────────────────────────────────────

class SunSpecDiscoverRequest(BaseModel):
    host:    str = "127.0.0.1"
    port:    int = 502
    unit_id: int = 1


@router.post("/sunspec/discover")
async def sunspec_discover(body: SunSpecDiscoverRequest):
    """Probe device for SunSpec model blocks."""
    from modbus.sunspec import SunSpecClient
    result = await SunSpecClient.discover(body.host, body.port, body.unit_id)
    return result


# ── Waveform + exception_rule endpoints ────────────────────────────────────────

class WaveformRequest(BaseModel):
    addr:          int
    waveform_type: str           # "sine", "ramp", "script"
    # Sine params
    amplitude:     float = 1000.0
    period_s:      float = 10.0
    phase_rad:     float = 0.0
    dc_offset:     float = 1000.0
    # Ramp params
    start:         int   = 0
    step:          int   = 10
    min_val:       int   = 0
    max_val:       int   = 65535
    # Script params
    expression:    str   = ""


@router.post("/simulator/{session_id}/waveform")
async def set_waveform(session_id: str, body: WaveformRequest):
    """Configure a waveform generator for a simulator register address."""
    from modbus.waveforms import SineWave, Ramp, ScriptWave

    wtype = body.waveform_type.lower()
    try:
        if wtype == "sine":
            waveform = SineWave(
                amplitude=body.amplitude,
                period_s=body.period_s,
                phase_rad=body.phase_rad,
                dc_offset=body.dc_offset,
            )
        elif wtype == "ramp":
            waveform = Ramp(
                start=body.start,
                step=body.step,
                min_val=body.min_val,
                max_val=body.max_val,
            )
        elif wtype == "script":
            waveform = ScriptWave(expression=body.expression)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown waveform_type '{body.waveform_type}'. Use 'sine', 'ramp', or 'script'.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ok = simulator_manager.set_waveform(session_id, body.addr, waveform)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"ok": True, "addr": body.addr, "waveform_type": body.waveform_type}


class ExceptionRuleRequest(BaseModel):
    addr:           int
    exception_code: int    # 1-11 (Modbus exception codes)
    rate:           float  # 0.0 to 1.0 (probability)


@router.post("/simulator/{session_id}/exception_rule")
async def set_exception_rule(session_id: str, body: ExceptionRuleRequest):
    """Set an exception injection rule for a simulator register address."""
    ok = simulator_manager.set_exception_rule(
        session_id, body.addr, body.exception_code, body.rate
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"ok": True, "addr": body.addr, "exception_code": body.exception_code, "rate": body.rate}


# ── Generic source register + write endpoints ──────────────────────────────────
# NOTE: these routes use path param {source} = "simulator" | "client".
# They must be declared AFTER the specific /simulator/... and /client/... routes
# above so that FastAPI's router resolves named static segments first.

@router.get("/{source}/{session_id}/registers")
async def get_registers(
    source:     str,
    session_id: str,
    fc:         int = 3,      # function code: 1, 2, 3, or 4
    start:      int = 40001,  # start address (Modbus convention: 40001-based)
    count:      int = 50,     # number of registers to return
):
    """
    Returns live register values from simulator or client.
    For simulator: returns current values from the in-memory register block.
    For client: returns values from last poll (get_values_with_delta).
    """
    src = source.lower()
    if src not in ("simulator", "client"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Use 'simulator' or 'client'.",
        )

    # Build address lookup from register_maps if session has a device_type
    def _lookup_reg(device_type: str, device_name: str, addr: int):
        """Return (name, unit) from the register map, or ('', '') if not found."""
        _key, regs = lookup(device_type, device_name)
        for r in regs:
            if r.address == addr:
                return r.name, r.unit
        return "", ""

    if src == "simulator":
        session = simulator_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Simulator session '{session_id}' not found."
            )
        # Build a full register dict from read_registers()
        all_regs = {r["address"]: r for r in session.read_registers()}
        registers = []
        for addr in range(start, start + count):
            entry = all_regs.get(addr)
            if entry:
                registers.append({
                    "address": addr,
                    "raw":     entry.get("raw", 0),
                    "value":   entry.get("value", 0.0),
                    "unit":    entry.get("unit", ""),
                    "name":    entry.get("name", ""),
                    "delta":   0,
                })
            else:
                registers.append({
                    "address": addr,
                    "raw":     0,
                    "value":   0.0,
                    "unit":    "",
                    "name":    "",
                    "delta":   0,
                })
        return {
            "session_id": session_id,
            "source":     src,
            "fc":         fc,
            "registers":  registers,
        }

    else:  # client — live on-demand read with 5-digit address conversion
        session = client_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Client session '{session_id}' not found."
            )
        try:
            registers = await client_manager.read_range(session_id, start, count, fc)
        except ConnectionError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return {
            "session_id": session_id,
            "source":     src,
            "fc":         fc,
            "registers":  registers,
        }


class WriteRequest(BaseModel):
    fc:         int        = 6        # function code: 5, 6, 15, 16, 22, 23
    addr:       int        = 0
    values:     list[int]  = Field(default_factory=list)
    and_mask:   int        = 0xFFFF   # for FC22
    or_mask:    int        = 0x0000   # for FC22
    read_addr:  int        = 0        # for FC23
    read_count: int        = 0        # for FC23


@router.post("/{source}/{session_id}/write")
async def write_registers(source: str, session_id: str, body: WriteRequest):
    """
    Dispatch write to the appropriate FC on the client or simulator.
    - source="simulator": FC06 only (directly updates internal register block)
    - source="client": dispatches to session write methods by FC
    """
    src = source.lower()
    if src not in ("simulator", "client"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Use 'simulator' or 'client'.",
        )

    if src == "simulator":
        session = simulator_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Simulator session '{session_id}' not found."
            )
        value = body.values[0] if body.values else 0
        ok = session.write_register(body.addr, value)
        if not ok:
            raise HTTPException(status_code=400, detail="Write failed — session context not ready.")
        return {"ok": True, "address": body.addr, "values": body.values}

    else:  # client
        session = client_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Client session '{session_id}' not found."
            )
        fc = body.fc
        # Convert 5-digit Modbus display addresses to 0-based wire addresses,
        # mirroring the same conversion done by read_range / GET registers.
        def _wire(addr: int, is_coil: bool = False) -> int:
            if is_coil:
                return max(0, addr - 1) if addr >= 1 else addr
            # Holding / input register (FC 6, 16, 22, 23)
            if addr >= 40001:
                return addr - 40001
            if addr >= 30001:
                return addr - 30001
            return max(0, addr)
        try:
            if fc == 5:
                val = bool(body.values[0]) if body.values else False
                result = await session.write_coil(_wire(body.addr, is_coil=True), val)
            elif fc == 6:
                val = body.values[0] if body.values else 0
                result = await session.write_register(_wire(body.addr), val)
            elif fc == 15:
                result = await session.write_coils(_wire(body.addr, is_coil=True), [bool(v) for v in body.values])
            elif fc == 16:
                result = await session.write_registers(_wire(body.addr), body.values)
            elif fc == 22:
                result = await session.mask_write_register(_wire(body.addr), body.and_mask, body.or_mask)
            elif fc == 23:
                result = await session.read_write_registers(
                    _wire(body.read_addr), body.read_count, _wire(body.addr), body.values
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported function code {fc}. Supported: 5, 6, 15, 16, 22, 23.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Write error: {exc}")

        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Write failed"))
        return result


# ── WebSocket: real-time client streaming ────────────────────────────────────
import asyncio as _asyncio
import json as _json
import time as _time

@router.websocket("/client/{session_id}/ws")
async def modbus_client_ws(websocket: WebSocket, session_id: str):
    """
    Bidirectional WebSocket for a Modbus client session.

    Client → Server (JSON):
      {"cmd":"scan",  "fc":3, "start":40001, "count":10, "interval":1.0}
      {"cmd":"write", "fc":6, "addr":40002, "values":[42]}
      {"cmd":"stop"}

    Server → Client (JSON):
      {"type":"init",         "session":{...}}
      {"type":"data",         "registers":[...], "ts":1234567890.1}
      {"type":"write_result", "ok":true|false, "addr":40002, "value":42, "error":"..."}
      {"type":"error",        "message":"..."}
      {"type":"status",       "status":"polling", "error":""}
    """
    if not _check_ws_origin(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    session = client_manager.get_session(session_id)
    if not session:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    # Send initial session info
    await websocket.send_text(_json.dumps({
        "type": "init",
        "session": {
            "session_id": session.session_id,
            "host": session.host,
            "port": session.port,
            "unit_id": session.unit_id,
            "status": session.status,
            "last_error": session.last_error,
            "enabled_fcs": session.enabled_fcs,
        }
    }))

    scan_task = None
    scan_cfg  = {}  # {fc, start, count, interval}
    live_cfg  = {}  # {interval}

    async def _run_scan():
        """Continuously push register reads to the WebSocket at the configured interval."""
        while True:
            fc       = scan_cfg.get("fc", 3)
            start    = scan_cfg.get("start", 40001)
            count    = scan_cfg.get("count", 10)
            interval = max(scan_cfg.get("interval", 1.0), 0.1)
            try:
                regs = await client_manager.read_range(session_id, start, count, fc)
                await websocket.send_text(_json.dumps({
                    "type": "data",
                    "registers": regs,
                    "ts": _time.time(),
                }))
            except Exception as exc:
                try:
                    await websocket.send_text(_json.dumps({
                        "type": "error",
                        "message": str(exc),
                    }))
                except Exception:
                    return

            # Push latest session status each cycle
            try:
                await websocket.send_text(_json.dumps({
                    "type": "status",
                    "status": session.status,
                    "error": session.last_error or "",
                }))
            except Exception:
                return

            await _asyncio.sleep(interval)

    async def _run_live():
        """Stream already-polled _latest registers without extra Modbus traffic."""
        while True:
            interval = max(live_cfg.get("interval", 1.0), 0.1)
            try:
                latest = session._latest  # already-polled data
                await websocket.send_text(_json.dumps({
                    "type": "data",
                    "registers": latest,
                    "ts": _time.time(),
                }))
            except Exception:
                return
            # Also push status
            try:
                await websocket.send_text(_json.dumps({
                    "type": "status",
                    "status": session.status,
                    "poll_count": session.poll_count,
                    "error_count": session.error_count,
                    "error": session.last_error or "",
                }))
            except Exception:
                return
            await _asyncio.sleep(interval)

    async def _cancel_task():
        """Cancel scan_task if running and wait for it."""
        nonlocal scan_task
        if scan_task and not scan_task.done():
            scan_task.cancel()
            try:
                await scan_task
            except _asyncio.CancelledError:
                pass
        scan_task = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = _json.loads(raw)
            except ValueError:
                continue

            cmd = msg.get("cmd", "")

            if cmd == "scan":
                scan_cfg = {
                    "fc":       int(msg.get("fc", 3)),
                    "start":    int(msg.get("start", 40001)),
                    "count":    int(msg.get("count", 10)),
                    "interval": float(msg.get("interval", 1.0)),
                }
                # Restart scan task
                await _cancel_task()
                scan_task = _asyncio.create_task(_run_scan())

            elif cmd == "live":
                live_cfg = {
                    "interval": float(msg.get("interval", 1.0)),
                }
                await _cancel_task()
                scan_task = _asyncio.create_task(_run_live())

            elif cmd in ("stop", "stop_live"):
                await _cancel_task()

            elif cmd == "write":
                fc     = int(msg.get("fc", 6))
                addr   = int(msg.get("addr", 0))
                values = [int(v) for v in msg.get("values", [])]
                # Convert 5-digit display address → 0-based wire address
                is_coil_fc = fc in (5, 15)
                if is_coil_fc:
                    wire_addr = max(0, addr - 1) if addr >= 1 else addr
                elif addr >= 40001:
                    wire_addr = addr - 40001
                elif addr >= 30001:
                    wire_addr = addr - 30001
                else:
                    wire_addr = max(0, addr)
                try:
                    if fc == 6:
                        result = await session.write_register(wire_addr, values[0] if values else 0)
                    elif fc == 5:
                        result = await session.write_coil(wire_addr, bool(values[0]) if values else False)
                    elif fc == 16:
                        result = await session.write_registers(wire_addr, values)
                    elif fc == 15:
                        result = await session.write_coils(wire_addr, [bool(v) for v in values])
                    else:
                        result = {"ok": False, "error": f"Unsupported write FC: {fc}"}
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                await websocket.send_text(_json.dumps({
                    "type": "write_result",
                    "ok":   result.get("ok", False),
                    "addr": addr,
                    "value": values[0] if values else None,
                    "error": result.get("error", ""),
                }))

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if scan_task and not scan_task.done():
            scan_task.cancel()
            try:
                await scan_task
            except _asyncio.CancelledError:
                pass
