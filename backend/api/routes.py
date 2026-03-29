"""
REST API routes for the Wireshark AI Agent.
"""

from __future__ import annotations
import os
import asyncio
import logging
import traceback
import tempfile
import shutil
import subprocess
import pathlib

from utils import proc
from datetime import datetime
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

from config import settings
from capture import live_capture
from capture.pcap_reader import read_pcap_list
from agent import analyzer, chat as chat_agent, expert as expert_agent
from agent.llm_client import check_llm_status, get_token_usage, reset_token_usage
from agent.tools.analysis_pipeline import (
    run_deep_analysis,
    tcp_health as tcp_health_fn,
    stream_inventory as stream_inventory_fn,
    latency_breakdown as latency_breakdown_fn,
    io_timeline as io_timeline_fn,
)
from agent.tools.narrative import generate_narrative

router = APIRouter()

# ── Version ───────────────────────────────────────────────────────────────────

def _read_version() -> str:
    """Read version from root package.json (single source of truth)."""
    import json
    try:
        pkg = pathlib.Path(__file__).parent.parent.parent / "package.json"
        return json.loads(pkg.read_text(encoding="utf-8"))["version"]
    except Exception:
        return "1.0.0"

APP_VERSION = _read_version()


@router.get("/version")
async def get_version():
    """
    Return the current backend version string.
    Used by the frontend update-checker to compare against the latest
    published release and decide whether to prompt the user.
    """
    return {"version": APP_VERSION}


# ── System status ─────────────────────────────────────────────────────────────

@router.get("/status")
async def system_status():
    """
    Aggregate health/availability for every major subsystem.
    Each component reports: ok (bool), detail (str), latency_ms (float | None).
    """
    import time

    results: dict[str, dict] = {}

    # ── Helper ────────────────────────────────────────────────────────────────
    async def probe(name: str, coro):
        t0 = time.perf_counter()
        try:
            detail = await coro
            results[name] = {
                "ok": True,
                "detail": detail or "reachable",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except Exception as exc:
            results[name] = {
                "ok": False,
                "detail": str(exc),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }

    # ── Backend API itself ────────────────────────────────────────────────────
    results["backend_api"] = {
        "ok": True,
        "detail": f"v{APP_VERSION}",
        "latency_ms": 0.0,
    }

    # ── Packet capture engine ─────────────────────────────────────────────────
    async def _capture():
        from capture import live_capture
        ifaces = await live_capture.get_interfaces()
        return f"{len(ifaces)} interface(s) available"

    # ── LLM backend ───────────────────────────────────────────────────────────
    async def _llm():
        from agent.llm_client import check_llm_status
        st = await check_llm_status()
        if not st.get("reachable"):
            raise RuntimeError(f"{st.get('backend','llm')} not reachable at {st.get('base_url','')}")
        return f"{st.get('backend')} · {st.get('model')} @ {st.get('base_url')}"

    # ── Ollama service ────────────────────────────────────────────────────────
    async def _ollama():
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            return f"{len(models)} model(s) loaded"

    # ── LM Studio service ─────────────────────────────────────────────────────
    async def _lmstudio():
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:1234/v1/models")
            r.raise_for_status()
            models = r.json().get("data", [])
            return f"{len(models)} model(s) loaded"

    # ── RAG / knowledge base ──────────────────────────────────────────────────
    async def _rag():
        from rag.ingest import _collection
        if _collection is None:
            return "not initialised (no documents ingested yet)"
        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(None, _collection.count)
        return f"{count} chunk(s) indexed"

    # ── Modbus simulator ──────────────────────────────────────────────────────
    async def _modbus_sim():
        from modbus.simulator import simulator_manager
        sessions = list(simulator_manager._sessions.values()) if hasattr(simulator_manager, "_sessions") else []
        return f"{len(sessions)} simulator session(s) active"

    # ── Modbus client ─────────────────────────────────────────────────────────
    async def _modbus_client():
        from modbus.client import client_manager
        sessions = list(client_manager._sessions.values()) if hasattr(client_manager, "_sessions") else []
        return f"{len(sessions)} client session(s) active"

    # ── WebSocket hub ─────────────────────────────────────────────────────────
    async def _ws():
        from api.websocket import _packet_clients, _insight_clients
        total = len(_packet_clients) + len(_insight_clients)
        return f"{len(_packet_clients)} packet + {len(_insight_clients)} insight subscriber(s)"

    # ── Run all probes concurrently ───────────────────────────────────────────
    await asyncio.gather(
        probe("packet_capture",     _capture()),
        probe("llm_backend",        _llm()),
        probe("ollama",             _ollama()),
        probe("lmstudio",           _lmstudio()),
        probe("rag_knowledge_base", _rag()),
        probe("modbus_simulator",   _modbus_sim()),
        probe("modbus_client",      _modbus_client()),
        probe("websocket_hub",      _ws()),
    )

    return {
        "version": APP_VERSION,
        "components": results,
    }


# ── In-memory stores ──────────────────────────────────────────────────────────
# Centralized in api.state to avoid circular imports across route modules.
from api.state import (
    _packets, _insights, _chat_history,
    _CAPTURE_DIR,
    ensure_capture_dir as _ensure_capture_dir,
    new_capture_path as _new_capture_path,
    get_packets, get_current_capture_file,
    clear_packets, add_packets, add_insight,
)
import api.state as _state

# Backward-compatible re-exports for agent tools.
# Tools that do `from api.routes import _packets` get the actual deque object (reference).
# But _current_capture_file is a string (immutable) — tools should import from api.state.
# During transition, we expose it as a module-level attribute via __getattr__.

_drain_task: Optional[asyncio.Task] = None


def __getattr__(name: str):
    """Module-level __getattr__ to delegate state lookups to api.state."""
    _state_attrs = {
        "_current_capture_file": "_current_capture_file",
        "_current_capture_name": "_current_capture_name",
        "_last_deep_analysis": "_last_deep_analysis",
    }
    if name in _state_attrs:
        return getattr(_state, _state_attrs[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ── Pydantic models ───────────────────────────────────────────────────────────

class CaptureStartRequest(BaseModel):
    interface: str
    bpf_filter: str = ""


class ChatRequest(BaseModel):
    message:          str
    stream:           bool      = False
    rag_enabled:      bool      = False   # inject knowledge-base context
    use_hyde:         bool      = False   # HyDE query expansion before retrieval
    analysis_context: str | None = None  # compact deep analysis summary for chat context


class LLMBackendRequest(BaseModel):
    backend: str


class ModelSelectRequest(BaseModel):
    model: str


# ── Capture endpoints ─────────────────────────────────────────────────────────

@router.get("/interfaces")
async def get_interfaces():
    try:
        interfaces = await live_capture.get_interfaces()
        return {"interfaces": interfaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interfaces/local-ips")
async def get_local_ips():
    """Return IPv4 addresses bound to local network interfaces (excludes loopback)."""
    import socket
    try:
        import psutil
        ips: set[str] = set()
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and a.address and not a.address.startswith("127."):
                    ips.add(a.address)
        return {"ips": sorted(ips)}
    except ImportError:
        pass
    # Fallback when psutil is unavailable
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        return {"ips": [ip] if ip and not ip.startswith("127.") else []}
    except Exception:
        return {"ips": []}


class TopologyScanRequest(BaseModel):
    cidr: str = ""


@router.get("/topology")
async def get_topology():
    """Build and return network topology from the current capture file."""
    try:
        from agent.tools.topology_map import build_topology
        packets     = get_packets()
        capture_file = _state._current_capture_file or None
        # build_topology runs subprocess.run (tshark) — must not block the event loop
        topo = await asyncio.to_thread(build_topology, packets, capture_file)
        return topo
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/topology/scan")
async def post_topology_scan(req: TopologyScanRequest):
    """Run an active subnet scan and return the enriched topology."""
    try:
        from agent.tools.topology_map import build_topology, _is_private
        from capture.subnet_scanner import scan_subnet
        from collections import Counter

        cidr = req.cidr.strip()
        if not cidr:
            # Auto-detect from captured traffic
            packets = get_packets()
            subnet_counter: Counter = Counter()
            for pkt in packets:
                for field in ("src_ip", "dst_ip"):
                    ip = pkt.get(field, "")
                    if ip and _is_private(ip):
                        parts = ip.split(".")
                        if len(parts) == 4:
                            subnet_counter[".".join(parts[:3])] += 1
            if subnet_counter:
                top = subnet_counter.most_common(1)[0][0]
                cidr = f"{top}.0/24"
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No CIDR provided and no private-IP traffic found to auto-detect subnet.",
                )

        try:
            raw = await asyncio.wait_for(
                scan_subnet(cidr, max_concurrent=64, timeout=1.0),
                timeout=30.0,
            )
            scan_dicts = [h.to_dict() for h in raw if h.alive]
        except asyncio.TimeoutError:
            scan_dicts = []

        packets      = get_packets()
        capture_file = _state._current_capture_file or None
        topo = await asyncio.to_thread(build_topology, packets, capture_file, scan_dicts)
        topo["scan_cidr"] = cidr
        topo["scan_hosts_found"] = len(scan_dicts)
        return topo
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/capture/start")
async def start_capture(req: CaptureStartRequest):
    global _drain_task
    if live_capture.is_capturing():
        raise HTTPException(status_code=400, detail="Capture already running.")
    clear_packets()
    cap_path = _new_capture_path()
    _state._current_capture_file = str(cap_path)
    _state._current_capture_name = cap_path.name
    await live_capture.start_capture(req.interface, req.bpf_filter, output_path=str(cap_path))
    # Start the persistent drain loop as a background asyncio task
    if _drain_task and not _drain_task.done():
        _drain_task.cancel()
    _drain_task = asyncio.create_task(_drain_loop())
    return {"status": "capturing", "interface": req.interface, "filter": req.bpf_filter,
            "capture_file": cap_path.name}


@router.post("/capture/stop")
async def stop_capture():
    global _drain_task
    await live_capture.stop_capture()
    if _drain_task and not _drain_task.done():
        _drain_task.cancel()
        try:
            await _drain_task
        except asyncio.CancelledError:
            pass
    _drain_task = None
    return {"status": "stopped", "packets_captured": len(_packets)}


@router.get("/capture/status")
async def capture_status():
    return {
        "is_capturing": live_capture.is_capturing(),
        "interface": live_capture.get_active_interface(),
        "packet_count": len(_packets),
    }


@router.get("/capture/current-file")
async def current_capture_file():
    """Return info about the current capture file (from live capture or last upload)."""
    if not _state._current_capture_file:
        return {"file": None, "name": None, "size_bytes": 0}
    p = pathlib.Path(_state._current_capture_file)
    size = p.stat().st_size if p.exists() else 0
    return {"file": _state._current_capture_file, "name": _state._current_capture_name, "size_bytes": size}


# ── Capture file management ───────────────────────────────────────────────────

@router.get("/capture/files")
async def list_capture_files():
    """List all saved capture files in the captures directory."""
    cap_dir = _ensure_capture_dir()
    files = []
    for p in sorted(cap_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.suffix in (".pcap", ".pcapng", ".cap") and p.is_file():
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
                "is_active": str(p) == _state._current_capture_file,
            })
    return {"files": files}


@router.delete("/capture/files/{name}")
async def delete_capture_file(name: str):
    """Delete a saved capture file by name."""
    # Safety: reject path traversal
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    cap_dir = _ensure_capture_dir()
    target = (cap_dir / name).resolve()
    if not str(target).startswith(str(cap_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.suffix not in (".pcap", ".pcapng", ".cap"):
        raise HTTPException(status_code=400, detail="Not a capture file.")
    target.unlink()
    # Clear active file reference if this was the active capture
    if _state._current_capture_file == str(target):
        _state._current_capture_file = ""
        _state._current_capture_name = ""
    return {"status": "deleted", "name": name}


@router.post("/capture/load/{name}")
async def load_capture_file(name: str):
    """Load a saved capture file as the active capture (replaces current packets)."""
    # Safety: reject path traversal
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    cap_dir = _ensure_capture_dir()
    target = (cap_dir / name).resolve()
    if not str(target).startswith(str(cap_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.suffix not in (".pcap", ".pcapng", ".cap"):
        raise HTTPException(status_code=400, detail="Not a capture file.")
    clear_packets()
    packets = await read_pcap_list(str(target))
    add_packets(packets)
    _state._current_capture_file = str(target)
    _state._current_capture_name = target.name
    return {"status": "loaded", "name": name, "packet_count": len(packets)}


@router.post("/capture/clear")
async def clear_capture():
    """Clear all in-memory packets and reset the active capture file reference."""
    if live_capture.is_capturing():
        raise HTTPException(status_code=400, detail="Stop capture before clearing.")
    clear_packets()
    _state._current_capture_file = ""
    _state._current_capture_name = ""
    return {"status": "cleared"}


# ── pcap upload ───────────────────────────────────────────────────────────────

_MAX_PCAP_BYTES = 200 * 1024 * 1024  # 200 MB hard limit


@router.post("/pcap/upload")
async def upload_pcap(file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename.endswith((".pcap", ".pcapng", ".cap")):
        raise HTTPException(status_code=400, detail="File must be .pcap, .pcapng, or .cap")

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pcap") as tmp:
            tmp_path = tmp.name
            total_bytes = 0
            # Stream to disk in 1 MB chunks to avoid loading large captures into RAM
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > _MAX_PCAP_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {_MAX_PCAP_BYTES // (1024 * 1024)} MB limit",
                    )
                tmp.write(chunk)
    except HTTPException:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    try:
        clear_packets()
        packets = await read_pcap_list(tmp_path)
        add_packets(packets)
        # Save a permanent copy to the captures directory
        dest = _ensure_capture_dir() / filename
        shutil.copy2(tmp_path, str(dest))
        _state._current_capture_file = str(dest)
        _state._current_capture_name = filename
        return {"status": "parsed", "filename": filename, "packet_count": len(packets),
                "capture_file": filename}
    finally:
        os.unlink(tmp_path)


# ── Packet query ──────────────────────────────────────────────────────────────

async def _tshark_filter_ids(pcap_path: str, display_filter: str) -> set[int] | None:
    """
    Run tshark with a display filter and return the set of matching 0-based packet IDs.
    Returns None on error (caller should treat as invalid filter).
    """
    cmd = [
        "tshark", "-r", pcap_path,
        "-Y", display_filter,
        "-T", "fields", "-e", "frame.number",
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None  # invalid filter or tshark error
        ids: set[int] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    ids.add(int(line) - 1)  # tshark frame numbers are 1-based; our ids are 0-based
                except ValueError:
                    pass
        return ids
    except Exception:
        return None


@router.get("/packets")
async def get_packets_endpoint(
    offset: int = 0,
    limit: int = 200,
    protocol: str = "",
    display_filter: str = Query(default=""),
):
    pkts = list(_packets)  # convert deque to list to support slicing
    if protocol:
        pkts = [p for p in pkts if p.get("protocol", "").upper() == protocol.upper()]

    if display_filter:
        if not _state._current_capture_file or not os.path.exists(_state._current_capture_file):
            raise HTTPException(status_code=400, detail="No capture file available for tshark filtering.")
        matching_ids = await _tshark_filter_ids(_state._current_capture_file, display_filter)
        if matching_ids is None:
            raise HTTPException(status_code=422, detail=f"Invalid tshark display filter: {display_filter!r}")
        pkts = [p for p in pkts if p.get("id") in matching_ids]

    total = len(pkts)
    return {"total": total, "offset": offset, "limit": limit, "packets": pkts[offset: offset + limit]}


# ── Chat ──────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    if req.stream:
        async def stream_gen():
            llm_text = ""
            try:
                # Check if we should generate A2UI
                from agent.a2ui_generator import should_generate_a2ui, generate_a2ui_response
                a2ui_component, a2ui_props = should_generate_a2ui(
                    req.message, 
                    {"packets": list(_packets)}
                )
                
                # If A2UI, yield it first
                if a2ui_component:
                    yield generate_a2ui_response(a2ui_component, a2ui_props)
                
                async for chunk in chat_agent.answer_question_stream(
                    req.message, _packets, _chat_history,
                    rag_enabled=req.rag_enabled, use_hyde=req.use_hyde,
                    analysis_context=req.analysis_context,
                ):
                    yield chunk
                    # Sentinel chunks start/end with \x00 — don't add to LLM text history
                    if not chunk.startswith("\x00"):
                        llm_text += chunk
                _chat_history.append({"role": "user", "content": req.message})
                _chat_history.append({"role": "assistant", "content": llm_text})
            except Exception as _exc:
                logger.error("chat stream_gen error: %s\n%s", _exc, traceback.format_exc())
                yield f"\n\n[Error: {type(_exc).__name__}: {_exc}]"
        return StreamingResponse(
            stream_gen(),
            media_type="text/plain",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # Non-streaming
    response = await chat_agent.answer_question(
        req.message, _packets, _chat_history,
        rag_enabled=req.rag_enabled, use_hyde=req.use_hyde,
        analysis_context=req.analysis_context,
    )
    _chat_history.append({"role": "user", "content": req.message})
    _chat_history.append({"role": "assistant", "content": response})
    return {"response": response}


@router.get("/chat/history")
async def get_chat_history():
    return {"history": _chat_history}


@router.delete("/chat/history")
async def clear_chat():
    _chat_history.clear()
    return {"status": "cleared"}


# ── Insights ──────────────────────────────────────────────────────────────────

@router.get("/insights")
async def get_insights():
    return {"insights": _insights}


class InsightRequest(BaseModel):
    mode: str = "general"


@router.get("/insights/modes")
async def insight_modes():
    return {"modes": analyzer.INSIGHT_MODES}


@router.post("/insights/generate")
async def trigger_insight(req: InsightRequest = InsightRequest()):
    if not _packets:
        raise HTTPException(status_code=400, detail="No packets captured yet.")
    result = await analyzer.generate_insights(_packets, mode=req.mode)
    add_insight(result, req.mode)
    return {"insight": result}


@router.post("/insights/generate/stream")
async def trigger_insight_stream(req: InsightRequest = InsightRequest()):
    """Stream insight tokens as plain text (same sentinel format as /chat)."""
    if not _packets:
        raise HTTPException(status_code=400, detail="No packets captured yet.")
    snapshot = list(_packets)

    async def _gen():
        import time
        full_text = ""
        try:
            async for token in analyzer.generate_insights_stream(snapshot, mode=req.mode):
                full_text += token
                yield token
        except Exception as exc:
            yield f"\n\n[Error generating insight: {exc}]"
        else:
            add_insight(full_text, req.mode)
            from api.websocket import broadcast_insight
            await broadcast_insight({"text": full_text, "source": req.mode,
                                     "timestamp": time.time()})

    return StreamingResponse(
        _gen(),
        media_type="text/plain",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── LLM ──────────────────────────────────────────────────────────────────────

@router.get("/llm/status")
async def llm_status():
    return await check_llm_status()


@router.post("/llm/backend")
async def set_llm_backend(req: LLMBackendRequest):
    if req.backend not in ("ollama", "lmstudio"):
        raise HTTPException(status_code=400, detail="backend must be 'ollama' or 'lmstudio'")
    settings.llm_backend = req.backend
    return {"backend": settings.llm_backend}


@router.get("/llm/tokens")
async def get_tokens():
    return get_token_usage()


@router.post("/llm/tokens/reset")
async def reset_tokens():
    reset_token_usage()
    return {"status": "reset"}


@router.get("/llm/context")
async def llm_context():
    """
    Return context window size for the active model plus current token usage.
    Context size is fetched from Ollama /api/show (or a known fallback for LM Studio).
    """
    from agent.llm_client import get_token_usage
    usage = get_token_usage()

    context_length: int = 4096  # safe fallback

    if settings.llm_backend == "ollama":
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(
                    "http://localhost:11434/api/show",
                    json={"model": settings.ollama_model},
                )
                data = resp.json()
                mi = data.get("model_info", {})
                # Key is family-prefixed, e.g. "qwen2.context_length"
                for key, val in mi.items():
                    if key.endswith(".context_length") and isinstance(val, int):
                        context_length = val
                        break
        except Exception:
            pass
    else:
        # LM Studio doesn't expose context length easily; use a common default
        context_length = 4096

    return {
        "context_length": context_length,
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "requests": usage["requests"],
    }


@router.get("/llm/models")
async def list_models():
    try:
        if settings.llm_backend == "ollama":
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
            active = settings.ollama_model
        else:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("http://localhost:1234/v1/models")
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
            active = settings.lmstudio_model
        return {"models": models, "active": active}
    except Exception as e:
        return {"models": [], "active": "", "error": str(e)}


@router.post("/llm/model")
async def set_model(req: ModelSelectRequest):
    if settings.llm_backend == "ollama":
        settings.ollama_model = req.model
    else:
        settings.lmstudio_model = req.model
    return {"model": req.model}


# ── Thinking toggle ───────────────────────────────────────────────────────────

class ThinkingRequest(BaseModel):
    enabled: bool


@router.get("/llm/thinking")
async def get_thinking():
    """Return current thinking (extended reasoning) state."""
    from agent.llm_client import get_thinking_enabled
    return {"enabled": get_thinking_enabled()}


@router.post("/llm/thinking")
async def set_thinking(req: ThinkingRequest):
    """Enable or disable extended reasoning (think param) for capable models."""
    from agent.llm_client import set_thinking_enabled
    set_thinking_enabled(req.enabled)
    return {"enabled": req.enabled}


# ── Backend self-restart (dev / non-Electron fallback) ───────────────────────

@router.post("/restart")
async def restart_backend():
    """
    Schedule a graceful self-restart in 500 ms.
    In Electron the frontend uses IPC instead; this endpoint is a fallback
    for dev-mode uvicorn (with --reload) or any process manager that
    auto-restarts on exit (systemd, pm2, etc.).
    """
    import asyncio, os, signal

    async def _exit():
        await asyncio.sleep(0.5)
        sig = getattr(signal, "SIGTERM", None) or getattr(signal, "SIGBREAK", signal.SIGINT)
        os.kill(os.getpid(), sig)

    asyncio.create_task(_exit())
    return {"status": "restarting"}


class PullModelRequest(BaseModel):
    model: str


import re as _re_pull
_MODEL_NAME_RE = _re_pull.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")


@router.post("/llm/pull")
async def pull_model(req: PullModelRequest):
    """
    Pull (download) an Ollama model. Streams progress as SSE.
    Only works when llm_backend == 'ollama'.
    """
    if settings.llm_backend != "ollama":
        raise HTTPException(status_code=400, detail="Model pulling is only supported with the Ollama backend.")
    if not _MODEL_NAME_RE.match(req.model):
        raise HTTPException(status_code=400, detail=f"Invalid model name: {req.model}")

    import json as _json

    async def _stream():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    "http://localhost:11434/api/pull",
                    json={"name": req.model},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield f"data: {_json.dumps({'status': 'error', 'error': body.decode()})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        yield f"data: {line}\n\n"
        except Exception as exc:
            yield f"data: {_json.dumps({'status': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Background helpers ────────────────────────────────────────────────────────

async def _drain_loop():
    """
    Persistent async task: drains the capture queue, stores packets in memory,
    and broadcasts each packet to all connected WebSocket clients.
    Auto-triggers LLM insight every N packets.
    """
    # Import here to avoid circular import at module load time
    from api.websocket import broadcast_packet

    queue = await live_capture.get_packet_queue()

    print("[drain] Drain loop started")
    try:
        while live_capture.is_capturing() or not queue.empty():
            drained = 0
            while not queue.empty():
                try:
                    pkt = queue.get_nowait()
                    add_packets([pkt])
                    await broadcast_packet(pkt)
                    drained += 1
                    # Yield every 50 packets to avoid starving the event loop
                    if drained % 50 == 0:
                        await asyncio.sleep(0)
                except asyncio.QueueEmpty:
                    break
                except Exception as e:
                    print(f"[drain] Drain packet error: {e}")

            await asyncio.sleep(0.02)  # 20ms poll — ~50 drain cycles/sec
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[drain] Drain loop error: {e}")
    finally:
        print(f"[drain] Drain loop ended — {len(_packets)} packets stored")


async def _auto_insight(packets: list[dict], source: str):
    try:
        text = await analyzer.generate_insights(packets)
        add_insight(text, source)
        from api.websocket import broadcast_insight
        import time
        await broadcast_insight({"text": text, "source": source, "timestamp": time.time()})
        print(f"[insight] Insight generated: {source} — {len(packets)} packets")
    except Exception as e:
        print(f"[insight] Insight generation error: {e}")


# ── Network Tools ─────────────────────────────────────────────────────────────

class ToolAnalyzeRequest(BaseModel):
    tool: str
    output: str


# Map of tool name → (executable, arg_builder)
_TOOL_PATHS: dict[str, str] = {
    "ping":     shutil.which("ping")    or r"C:\Windows\System32\PING.EXE",
    "tracert":  shutil.which("tracert") or r"C:\Windows\System32\TRACERT.EXE",
    "arp":      shutil.which("arp")     or r"C:\Windows\System32\ARP.EXE",
    "netstat":  shutil.which("netstat") or r"C:\Windows\System32\NETSTAT.EXE",
    "ipconfig": shutil.which("ipconfig")or r"C:\Windows\System32\ipconfig.exe",
}

import re as _re

# Allowlists for flags that may be passed to each tool via the `extra` param.
# Only tokens matching these patterns are accepted; anything else is rejected.
_NETSTAT_ALLOWED  = {"-a", "-n", "-o", "-ano", "-an", "-ao", "-no", "-b", "-e", "-s", "-p"}
_IPCONFIG_ALLOWED = {"/all", "/release", "/renew", "/flushdns", "/displaydns",
                     "/registerdns", "/showclassid", "/setclassid"}


_TARGET_RE = _re.compile(
    r"^(?:"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"  # FQDN
    r"|(?:\d{1,3}\.){3}\d{1,3}"                                              # IPv4
    r"|[0-9a-fA-F:]{2,39}"                                                   # IPv6 (simplified)
    r")$"
)


def _validate_target(target: str) -> str:
    """
    Validate and return a safe host/IP string for ping/tracert/arp.
    Raises HTTPException 400 on invalid input.
    """
    t = target.strip()
    if not t:
        return t  # caller provides default
    if len(t) > 255:
        raise HTTPException(status_code=400, detail="Target too long.")
    if not _TARGET_RE.match(t):
        raise HTTPException(status_code=400, detail=f"Invalid target '{t}': must be hostname or IP address.")
    return t


def _validate_flags(tool: str, raw: str) -> list[str]:
    """
    Split *raw* into tokens and validate each against the per-tool allowlist.
    Returns the validated list. Raises HTTPException on any disallowed token.
    """
    tokens = raw.strip().split()
    if not tokens:
        return []
    allowlist = _NETSTAT_ALLOWED if tool == "netstat" else _IPCONFIG_ALLOWED
    for tok in tokens:
        if tok.lower() not in allowlist:
            raise HTTPException(
                status_code=400,
                detail=f"Flag '{tok}' is not allowed for {tool}. "
                       f"Allowed values: {', '.join(sorted(allowlist))}",
            )
    return tokens


def _build_args(tool: str, target: str, extra: str) -> list[str]:
    """Return the full argv list for a given tool."""
    exe = _TOOL_PATHS.get(tool)
    if not exe or not os.path.isfile(exe):
        raise HTTPException(status_code=404, detail=f"'{tool}' not found on this system.")

    if tool == "ping":
        return [exe, "-n", "4", _validate_target(target) or "8.8.8.8"]
    if tool == "tracert":
        return [exe, "-d", _validate_target(target) or "8.8.8.8"]
    if tool == "arp":
        t = _validate_target(target) if target else ""
        return [exe, "-a"] + ([t] if t else [])
    if tool == "netstat":
        flags = _validate_flags("netstat", extra) or ["-ano"]
        return [exe] + flags
    if tool == "ipconfig":
        flags = _validate_flags("ipconfig", extra) or ["/all"]
        return [exe] + flags
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


async def _stream_tool(argv: list[str]):
    """Run a subprocess and yield its stdout lines as SSE data events."""
    loop = asyncio.get_running_loop()
    out_lines: asyncio.Queue[str | None] = asyncio.Queue()

    def _run():
        try:
            child = proc.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in child.stdout:
                loop.call_soon_threadsafe(out_lines.put_nowait, line.rstrip("\r\n"))
            child.wait()
        except Exception as exc:
            loop.call_soon_threadsafe(out_lines.put_nowait, f"[error] {exc}")
        finally:
            loop.call_soon_threadsafe(out_lines.put_nowait, None)  # sentinel

    thread = loop.run_in_executor(None, _run)

    while True:
        line = await out_lines.get()
        if line is None:
            break
        # Server-Sent Events format
        yield f"data: {line}\n\n"

    await thread
    yield "data: [DONE]\n\n"


@router.get("/tools")
async def list_tools():
    """List all registered tools with metadata."""
    from agent.tools import list_tools as _list_tools
    return {"tools": _list_tools(), "count": len(_list_tools())}


@router.get("/tools/audit")
async def tools_audit(n: int = Query(50, ge=1, le=200)):
    """Return recent tool execution audit log entries."""
    from agent.tools.audit import get_audit_log
    return {"entries": get_audit_log().recent(n)}


@router.get("/tools/run")
async def run_tool(
    tool: str = Query(..., description="ping | tracert | arp | netstat | ipconfig"),
    target: str = Query("", description="IP / hostname for ping & tracert"),
    extra: str = Query("", description="Extra flags for netstat / ipconfig"),
):
    """Stream tool output as Server-Sent Events."""
    argv = _build_args(tool, target, extra)
    return StreamingResponse(
        _stream_tool(argv),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tools/analyze")
async def analyze_tool_output(req: ToolAnalyzeRequest):
    """Send captured tool output to the LLM for analysis."""
    prompt = (
        f"The user ran the network diagnostic tool '{req.tool}' on Windows.\n"
        f"Here is the output:\n\n```\n{req.output}\n```\n\n"
        "Briefly explain what this output means, highlight anything notable "
        "(unusual ports, high latency hops, ARP conflicts, etc.), "
        "and suggest any follow-up actions if appropriate."
    )
    response = await chat_agent.answer_question(prompt, [], [])
    return {"analysis": response}


# ── Subnet Scanner ────────────────────────────────────────────────────────────

from capture.subnet_scanner import scan_subnet_stream  # noqa: E402


@router.get("/tools/my-subnet")
async def detect_my_subnet():
    """
    Detect the current machine's local IP addresses, subnet masks, and CIDR
    notation for each active network interface.  Returns a list so the user
    can pick which NIC to scan.
    """
    import ipaddress
    import socket
    import subprocess
    import platform
    import re as _re_subnet

    interfaces: list[dict] = []

    if platform.system() == "Windows":
        # Parse ipconfig /all for adapter name, IP, and subnet mask
        try:
            out = proc.run(
                ["ipconfig", "/all"],
                capture_output=True, text=True, timeout=5,
            )
            current_adapter = ""
            current_ip = ""
            for line in out.stdout.splitlines():
                # Adapter header lines end with ":"
                adapter_match = _re_subnet.match(r"^(\S.*?)\s*adapter\s+(.*?):", line, _re_subnet.IGNORECASE)
                if adapter_match:
                    current_adapter = adapter_match.group(2).strip()
                    current_ip = ""
                    continue
                # IPv4 Address line
                ip_match = _re_subnet.search(r"IPv4 Address[.\s]*:\s*([\d.]+)", line)
                if ip_match:
                    current_ip = ip_match.group(1)
                    continue
                # Subnet Mask line (always follows IPv4 line)
                mask_match = _re_subnet.search(r"Subnet Mask[.\s]*:\s*([\d.]+)", line)
                if mask_match and current_ip:
                    mask = mask_match.group(1)
                    try:
                        net = ipaddress.IPv4Network(f"{current_ip}/{mask}", strict=False)
                        interfaces.append({
                            "adapter": current_adapter,
                            "ip": current_ip,
                            "mask": mask,
                            "cidr": str(net),
                            "prefix": net.prefixlen,
                            "hosts": max(0, net.num_addresses - 2),
                        })
                    except ValueError:
                        pass
                    current_ip = ""
        except Exception:
            pass
    else:
        # Linux / macOS — use ip addr or ifconfig
        try:
            out = proc.run(
                ["ip", "-4", "-o", "addr", "show"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    iface = parts[1]
                    cidr_str = parts[3]  # e.g. "192.168.1.5/24"
                    try:
                        iface_net = ipaddress.IPv4Interface(cidr_str)
                        net = iface_net.network
                        interfaces.append({
                            "adapter": iface,
                            "ip": str(iface_net.ip),
                            "mask": str(net.netmask),
                            "cidr": str(net),
                            "prefix": net.prefixlen,
                            "hosts": max(0, net.num_addresses - 2),
                        })
                    except ValueError:
                        pass
        except FileNotFoundError:
            # Fallback to ifconfig
            try:
                out = proc.run(
                    ["ifconfig"],
                    capture_output=True, text=True, timeout=5,
                )
                current_iface = ""
                for line in out.stdout.splitlines():
                    iface_match = _re_subnet.match(r"^(\S+):", line)
                    if iface_match:
                        current_iface = iface_match.group(1)
                    inet_match = _re_subnet.search(r"inet\s+([\d.]+)\s+netmask\s+([\d.]+|0x[0-9a-f]+)", line)
                    if inet_match:
                        ip_str = inet_match.group(1)
                        mask_raw = inet_match.group(2)
                        if mask_raw.startswith("0x"):
                            mask_int = int(mask_raw, 16)
                            mask_str = str(ipaddress.IPv4Address(mask_int))
                        else:
                            mask_str = mask_raw
                        try:
                            net = ipaddress.IPv4Network(f"{ip_str}/{mask_str}", strict=False)
                            interfaces.append({
                                "adapter": current_iface,
                                "ip": ip_str,
                                "mask": mask_str,
                                "cidr": str(net),
                                "prefix": net.prefixlen,
                                "hosts": max(0, net.num_addresses - 2),
                            })
                        except ValueError:
                            pass
            except Exception:
                pass

    # Filter out loopback and APIPA
    interfaces = [
        i for i in interfaces
        if not i["ip"].startswith("127.")
        and not i["ip"].startswith("169.254.")
    ]

    return {"interfaces": interfaces}


@router.get("/tools/subnet-scan")
async def subnet_scan(
    cidr: str = Query(..., description="CIDR notation or single IP, e.g. 192.168.1.0/24"),
    timeout: float = Query(1.0, description="Per-host timeout in seconds", ge=0.1, le=10.0),
    concurrency: int = Query(128, description="Max concurrent probes", ge=1, le=512),
):
    """
    Ping-sweep a subnet and stream results as SSE JSON events.

    Each event is a JSON object:
      { "type": "result",   "data": { ip, alive, hostname, netbios, mac, vendor, latency_ms } }
      { "type": "progress", "data": { scanned, total } }
      { "type": "done",     "data": { total, alive } }
      { "type": "error",    "data": { message } }
    """
    import ipaddress, json

    async def _generate():
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            total   = max(1, network.num_addresses - 2) if network.num_addresses > 2 else 1
            scanned = 0
            alive   = 0

            yield f"data: {json.dumps({'type': 'progress', 'data': {'scanned': 0, 'total': total}})}\n\n"

            async for result in scan_subnet_stream(cidr, max_concurrent=concurrency, timeout=timeout):
                scanned += 1
                if result.alive:
                    alive += 1
                yield f"data: {json.dumps({'type': 'result', 'data': result.to_dict()})}\n\n"
                yield f"data: {json.dumps({'type': 'progress', 'data': {'scanned': scanned, 'total': total}})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'data': {'total': scanned, 'alive': alive}})}\n\n"

        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(exc)}})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': f'Scan failed: {exc}'}})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Expert Analysis ───────────────────────────────────────────────────────────

_EXPERT_MODES = {
    "ics_audit":      expert_agent.ics_audit,
    "port_scan":      expert_agent.port_scan_detection,
    "flow_analysis":  expert_agent.flow_analysis,
    "conversations":  expert_agent.conversations,
    "anomaly_detect": expert_agent.anomaly_detect,
}


@router.get("/expert/modes")
async def expert_modes():
    """List available expert analysis modes."""
    return {
        "modes": [
            {
                "id": "ics_audit",
                "label": "ICS / SCADA Audit",
                "description": "Modbus, DNP3, OPC-UA inventory, dangerous function codes, security policy violations",
                "icon": "shield",
            },
            {
                "id": "port_scan",
                "label": "Port Scan Detection",
                "description": "SYN scan, horizontal scan, RST storm detection",
                "icon": "scan",
            },
            {
                "id": "flow_analysis",
                "label": "Flow Analysis",
                "description": "Top flows by packets and bytes, long-lived connections, ICS flow summary",
                "icon": "activity",
            },
            {
                "id": "conversations",
                "label": "Conversations",
                "description": "All unique bidirectional IP pairs with protocol breakdown",
                "icon": "arrows-left-right",
            },
            {
                "id": "anomaly_detect",
                "label": "Anomaly Detection",
                "description": "Statistical outliers, protocol mismatches, broadcast storms, large packets",
                "icon": "alert-triangle",
            },
        ]
    }


class ExpertAnalyzeRequest(BaseModel):
    mode: str
    with_llm: bool = True


@router.post("/expert/analyze")
async def expert_analyze(req: ExpertAnalyzeRequest):
    """
    Run one expert analysis mode against the current packet buffer.
    Optionally generates LLM commentary.
    """
    fn = _EXPERT_MODES.get(req.mode)
    if not fn:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{req.mode}'. Valid: {list(_EXPERT_MODES)}",
        )
    if not _packets:
        raise HTTPException(status_code=400, detail="No packets captured yet.")

    # Run the synchronous analysis in a thread to avoid blocking the event loop
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, fn, _packets)

    commentary = ""
    if req.with_llm:
        try:
            commentary = await expert_agent.llm_commentary(req.mode, result)
        except Exception as exc:
            commentary = f"[LLM error] {exc}"

    return {
        "mode": req.mode,
        "result": result,
        "commentary": commentary,
    }


@router.post("/expert/analyze/stream")
async def expert_analyze_stream(req: ExpertAnalyzeRequest):
    """
    Run expert analysis and stream the LLM commentary token-by-token.
    The structured result is emitted first as a single JSON sentinel line,
    then the LLM tokens follow as plain text.

    Stream format:
      \x00EXPERT_RESULT:<json>\x00   — full analysis dict (once)
      <token>...                     — LLM commentary tokens
    """
    import json

    fn = _EXPERT_MODES.get(req.mode)
    if not fn:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{req.mode}'. Valid: {list(_EXPERT_MODES)}",
        )
    if not _packets:
        raise HTTPException(status_code=400, detail="No packets captured yet.")

    # Snapshot packets to avoid mutation mid-stream
    snapshot = list(_packets)

    async def _gen():
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, fn, snapshot)
        yield f"\x00EXPERT_RESULT:{json.dumps(result, default=str)}\x00"

        if req.with_llm:
            import json as _json
            trimmed = _json.dumps(result, default=str)
            if len(trimmed) > 3000:
                trimmed = trimmed[:3000] + "\n... [truncated]"

            from agent.llm_client import chat_completion_stream
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a senior OT/ICS network security analyst. "
                        "Summarize findings concisely using markdown. "
                        "Highlight critical risks and suggest concrete remediation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Expert analysis: **{req.mode}**\n\n"
                        f"```json\n{trimmed}\n```\n\n"
                        "Provide: 1) Critical findings, 2) Operational impact, 3) Recommended actions."
                    ),
                },
            ]
            async for token, is_reasoning in chat_completion_stream(messages, max_tokens=600):
                if not is_reasoning:
                    yield token

    return StreamingResponse(
        _gen(),
        media_type="text/plain",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── Agent Memory ─────────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory():
    """Return the agent's persistent memory store."""
    from agent.memory import get_memory_store
    store = get_memory_store()
    return store.to_dict()


class FactRequest(BaseModel):
    text: str


@router.post("/memory/fact")
async def add_memory_fact(req: FactRequest):
    """Add a network observation fact to persistent memory."""
    from agent.memory import get_memory_store
    text = req.text.strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "Fact text must be 1-500 characters.")
    store = get_memory_store()
    store.add_fact(text)
    return {"ok": True, "facts": store.get_facts()}


@router.delete("/memory/fact")
async def remove_memory_fact(req: FactRequest):
    """Remove a fact from persistent memory."""
    from agent.memory import get_memory_store
    store = get_memory_store()
    removed = store.remove_fact(req.text.strip())
    return {"ok": removed, "facts": store.get_facts()}


# ── Autonomous mode ──────────────────────────────────────────────────────────

class AutonomousRequest(BaseModel):
    enabled: bool

@router.get("/agent/autonomous")
async def get_autonomous():
    from agent.chat import get_autonomous_mode
    return {"enabled": get_autonomous_mode()}

@router.post("/agent/autonomous")
async def set_autonomous(req: AutonomousRequest):
    from agent.chat import set_autonomous_mode
    set_autonomous_mode(req.enabled)
    return {"enabled": req.enabled}


# ── Shell mode (exec without full autonomous) ─────────────────────────────────

class ShellRequest(BaseModel):
    enabled: bool

@router.get("/agent/shell")
async def get_shell():
    from agent.chat import get_shell_mode
    return {"enabled": get_shell_mode()}

@router.post("/agent/shell")
async def set_shell(req: ShellRequest):
    from agent.chat import set_shell_mode
    set_shell_mode(req.enabled)
    return {"enabled": req.enabled}


# ── Background autonomous tasks ─────────────────────────────────────────────

class TaskRequest(BaseModel):
    goal: str
    max_rounds: int = 20

@router.post("/agent/task")
async def create_agent_task(req: TaskRequest, background_tasks: BackgroundTasks):
    from agent.tasks import create_task, run_task
    task = create_task(req.goal)
    background_tasks.add_task(run_task, task.task_id, req.goal, req.max_rounds)
    return {"task_id": task.task_id, "status": "running"}

@router.get("/agent/tasks")
async def list_agent_tasks():
    from agent.tasks import list_tasks
    return {"tasks": list_tasks()}

@router.get("/agent/task/{task_id}")
async def get_agent_task(task_id: str):
    from agent.tasks import get_task
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {
        "task_id": task.task_id,
        "goal": task.goal,
        "status": task.status,
        "progress": task.progress,
        "final_answer": task.final_answer,
        "created_at": task.created_at,
        "finished_at": task.finished_at,
    }


# ── Analysis endpoints ─────────────────────────────────────────────────────────

@router.post("/analysis/deep")
async def analysis_deep(pcap_path: str = ""):
    """Run full analysis pipeline. Returns JSON. Call /analysis/narrative next for LLM prose."""
    path = pcap_path or _state._current_capture_file or None
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, run_deep_analysis, list(_packets), path
    )
    _state._last_deep_analysis = result
    return result


@router.get("/analysis/narrative")
async def analysis_narrative():
    """Stream LLM narrative for the most recent deep analysis. Call after /analysis/deep."""
    if _state._last_deep_analysis is None:
        raise HTTPException(status_code=400, detail="No analysis has been run yet. Call POST /analysis/deep first.")

    async def stream_gen():
        async for token in generate_narrative(_state._last_deep_analysis):
            yield token

    return StreamingResponse(
        stream_gen(),
        media_type="text/plain",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/analysis/tcp-health")
async def analysis_tcp_health(pcap_path: str = ""):
    path = pcap_path or _state._current_capture_file or None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, tcp_health_fn, list(_packets), path)


@router.get("/analysis/streams")
async def analysis_streams(pcap_path: str = ""):
    path = pcap_path or _state._current_capture_file or None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, stream_inventory_fn, list(_packets), path)


@router.get("/analysis/latency")
async def analysis_latency(pcap_path: str = ""):
    path = pcap_path or _state._current_capture_file or None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, latency_breakdown_fn, list(_packets), path)


@router.get("/analysis/io-timeline")
async def analysis_io_timeline():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, io_timeline_fn, list(_packets))
