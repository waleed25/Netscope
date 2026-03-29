"""
Redis Stream names and event type constants.

Single source of truth — imported by gateway, daemon, and engine.
All inter-process communication uses these stream names.
"""
from __future__ import annotations


# ── Stream names ──────────────────────────────────────────────────────────────

# Capture lifecycle  (Gateway ↔ Daemon)
CAPTURE_COMMAND    = "ns:capture.command"       # Gateway → Daemon
CAPTURE_PACKETS    = "ns:capture.packets"       # Daemon → Gateway  (high-volume stream)
CAPTURE_STATUS     = "ns:capture.status"        # Daemon → Gateway  (reply channel)

# Modbus  (Gateway ↔ Daemon)
MODBUS_COMMAND     = "ns:modbus.command"
MODBUS_RESPONSE    = "ns:modbus.response"

# Chat / Agent  (Gateway ↔ Engine)
CHAT_REQUEST       = "ns:chat.request"
CHAT_RESPONSE      = "ns:chat.response"         # streamed tokens or final response

# Insights  (Gateway ↔ Engine)
INSIGHT_REQUEST    = "ns:insight.request"
INSIGHT_RESPONSE   = "ns:insight.response"

# Expert analysis  (Gateway ↔ Engine)
EXPERT_REQUEST     = "ns:expert.request"
EXPERT_RESPONSE    = "ns:expert.response"

# RAG  (Gateway ↔ Engine)
RAG_REQUEST        = "ns:rag.request"
RAG_RESPONSE       = "ns:rag.response"

# Tool requests  (Engine ↔ Daemon)
# When an AI tool needs data from the Daemon (e.g. Modbus read, capture start)
TOOL_REQUEST       = "ns:tool.request"          # Engine → Daemon
TOOL_RESPONSE      = "ns:tool.response"         # Daemon → Engine

# State queries  (Engine ↔ Gateway)
# When an AI tool needs packets/insights from the Gateway's in-memory store
STATE_REQUEST      = "ns:state.request"         # Engine → Gateway
STATE_RESPONSE     = "ns:state.response"        # Gateway → Engine

# Health heartbeats  (All → All)
HEALTH_GATEWAY     = "ns:health.gateway"
HEALTH_DAEMON      = "ns:health.daemon"
HEALTH_ENGINE      = "ns:health.engine"

# Real-time Pub/Sub channels (not streams — for 1-to-many broadcast)
PUBSUB_PACKETS     = "ns:pubsub:packets"        # Daemon publishes live packets
PUBSUB_INSIGHTS    = "ns:pubsub:insights"        # Engine publishes insights

# Module lifecycle  (broadcast to all processes)
MODULE_LOADED      = "ns:module.loaded"         # broadcast when a module is installed live
MODULE_UNLOADED    = "ns:module.unloaded"       # broadcast when a module is removed


# ── Action enums ──────────────────────────────────────────────────────────────

class CaptureAction:
    START            = "start"
    STOP             = "stop"
    STATUS           = "status"
    LIST_INTERFACES  = "list_interfaces"
    READ_PCAP        = "read_pcap"


class ModbusAction:
    SIM_CREATE       = "sim_create"
    SIM_READ         = "sim_read"
    SIM_WRITE        = "sim_write"
    SIM_STOP         = "sim_stop"
    CLIENT_CREATE    = "client_create"
    CLIENT_READ      = "client_read"
    CLIENT_WRITE     = "client_write"
    CLIENT_STOP      = "client_stop"
    SCAN             = "scan"
    LIST_SESSIONS    = "list_sessions"
    DIAGNOSTICS      = "diagnostics"
    WRITE_MULTI      = "write_multi"
    SUNSPEC_DISCOVER = "sunspec_discover"
    SET_WAVEFORM     = "set_waveform"
    INJECT_EXCEPTION = "inject_exception"
    ANALYZE_PCAP     = "analyze_pcap"
    FORENSICS        = "forensics"


class ChatAction:
    CHAT             = "chat"
    CHAT_STREAM      = "chat_stream"
    CLEAR_HISTORY    = "clear_history"


class InsightAction:
    GENERATE         = "generate"
    GENERATE_STREAM  = "generate_stream"
    LIST_MODES       = "list_modes"


class ExpertAction:
    ANALYZE          = "analyze"
    DEEP_ANALYSIS    = "deep_analysis"
    TCP_HEALTH       = "tcp_health"
    STREAM_FOLLOW    = "stream_follow"
    LATENCY          = "latency"
    IO_GRAPH         = "io_graph"
    NARRATIVE        = "narrative"


class RAGAction:
    QUERY            = "query"
    INGEST           = "ingest"
    INGEST_URL       = "ingest_url"
    STATUS           = "status"
    DELETE           = "delete"
    LIST_SOURCES     = "list_sources"


class StateAction:
    GET_PACKETS       = "get_packets"
    GET_CAPTURE_FILE  = "get_capture_file"
    GET_INSIGHTS      = "get_insights"
    ADD_INSIGHT       = "add_insight"
    CLEAR_PACKETS     = "clear_packets"
    ADD_PACKETS       = "add_packets"


class LLMAction:
    STATUS           = "llm_status"
    SET_BACKEND      = "set_backend"
    GET_TOKENS       = "get_tokens"
    RESET_TOKENS     = "reset_tokens"
    GET_CONTEXT      = "get_context"
    LIST_MODELS      = "list_models"
    SET_MODEL        = "set_model"
    GET_THINKING     = "get_thinking"
    SET_THINKING     = "set_thinking"
    PULL_MODEL       = "pull_model"


class SkillsAction:
    LIST             = "list"
    GET              = "get"
    CREATE           = "create"
    UPDATE           = "update"
    DELETE           = "delete"
    RELOAD           = "reload"
