"""
Shared Pydantic models used across all 3 processes.

These define the canonical wire format for Redis messages.
Each process imports from here rather than defining its own schemas.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Packet schema ─────────────────────────────────────────────────────────────

class PacketData(BaseModel):
    """A single parsed network packet (mirrors the existing dict format)."""
    id: int = 0
    timestamp: float = 0.0
    protocol: str = ""
    src_ip: str = ""
    dst_ip: str = ""
    src_port: str = ""
    dst_port: str = ""
    length: int = 0
    info: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


# ── Capture commands ──────────────────────────────────────────────────────────

class CaptureCommand(BaseModel):
    action: str                      # CaptureAction.*
    interface: str = ""
    bpf_filter: str = ""
    output_path: str = ""
    pcap_path: str = ""              # for READ_PCAP


class CaptureStatusResponse(BaseModel):
    is_capturing: bool = False
    interface: str = ""
    packet_count: int = 0
    capture_file: str = ""


# ── Modbus commands ───────────────────────────────────────────────────────────

class ModbusCommand(BaseModel):
    action: str                      # ModbusAction.*
    session_id: str = ""
    device_type: str = ""
    host: str = ""
    port: int = 502
    unit_id: int = 1
    address: int = 0
    value: int = 0
    values: list[int] = Field(default_factory=list)
    fc: int = 0                      # function code for write_multi
    cidr: str = ""                   # for scan
    params: dict[str, Any] = Field(default_factory=dict)


# ── Chat / AI ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    rag_enabled: bool = False
    use_hyde: bool = False
    analysis_context: Optional[str] = None
    packets_summary: Optional[str] = None   # compact context (not raw packets)


class ChatResponse(BaseModel):
    """A single chunk in a streamed response, or the full response."""
    token: str = ""                  # for streaming
    response: str = ""               # for non-streaming
    done: bool = False               # True on final chunk
    sentinel: str = ""               # e.g. "TOOL_CALL:ping 8.8.8.8"


# ── Insight ───────────────────────────────────────────────────────────────────

class InsightRequest(BaseModel):
    action: str                      # InsightAction.*
    mode: str = "general"
    packets_summary: Optional[str] = None


class InsightResponse(BaseModel):
    insight: str = ""
    mode: str = ""
    done: bool = False


# ── Expert / Analysis ─────────────────────────────────────────────────────────

class ExpertRequest(BaseModel):
    action: str                      # ExpertAction.*
    mode: str = ""
    packets_summary: Optional[str] = None
    capture_file: str = ""
    stream_index: int = 0


class ExpertResponse(BaseModel):
    result: Any = None
    done: bool = False


# ── RAG ───────────────────────────────────────────────────────────────────────

class RAGRequest(BaseModel):
    action: str                      # RAGAction.*
    query: str = ""
    url: str = ""
    source_id: str = ""
    n_results: int = 5
    use_hyde: bool = False


class RAGResponse(BaseModel):
    context: str = ""
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    status: str = ""


# ── Tool request/response (Engine ↔ Daemon) ──────────────────────────────────

class ToolRequest(BaseModel):
    tool_name: str
    args: str = ""
    allow_dangerous: bool = False


class ToolResponse(BaseModel):
    tool: str
    status: str = "ok"               # "ok" | "error"
    output: str = ""
    duration_ms: float = 0.0


# ── State queries (Engine ↔ Gateway) ──────────────────────────────────────────

class StateRequest(BaseModel):
    action: str                      # StateAction.*
    limit: int = 5000
    text: str = ""                   # for add_insight
    source: str = ""                 # for add_insight
    packets: list[dict[str, Any]] = Field(default_factory=list)  # for add_packets


class StateResponse(BaseModel):
    packets: list[dict[str, Any]] = Field(default_factory=list)
    insights: list[dict[str, Any]] = Field(default_factory=list)
    file: str = ""
    name: str = ""


# ── Health heartbeats ─────────────────────────────────────────────────────────

class HealthBeat(BaseModel):
    process: str                     # "gateway", "daemon", "engine"
    status: str = "ok"               # "ok", "starting", "error"
    timestamp: float = 0.0
    detail: str = ""
    uptime_s: float = 0.0
