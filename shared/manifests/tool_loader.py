"""Manifest-driven tool registration helper."""
from __future__ import annotations
import importlib
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Mapping from tool name → Python import path
# Format: "tool_name": "module.path:function_name"
# This is the bridge between manifest tool names and actual Python functions.
TOOL_MAP: dict[str, str] = {
    # Capture tools
    "capture_start":     "daemon.capture.live_capture:start_capture",
    "capture_stop":      "daemon.capture.live_capture:stop_capture",
    "capture_status":    "daemon.capture.live_capture:capture_status",
    "list_interfaces":   "daemon.capture.live_capture:list_interfaces",
    "read_pcap":         "daemon.capture.live_capture:read_pcap",
    # Modbus tools
    "modbus_sim_create": "backend.modbus.simulator:create_simulator",
    "modbus_sim_read":   "backend.modbus.simulator:read_coils",
    "modbus_sim_write":  "backend.modbus.simulator:write_coils",
    "modbus_client_create": "backend.modbus.client:create_client",
    "modbus_client_read":   "backend.modbus.client:read_registers",
    "modbus_write_multi":   "backend.modbus.client:write_registers",
    "modbus_scan":       "backend.modbus.scanner:scan_network",
    "modbus_diagnostics":"backend.modbus.diagnostics:run_diagnostics",
    "sunspec_discover":  "backend.modbus.sunspec:discover",
    # LLM tools
    "llm_chat":    "backend.agent.chat:chat",
    "llm_analyze": "backend.agent.chat:analyze",
    "llm_stream":  "backend.agent.chat:stream_chat",
    "llm_status":  "backend.agent.tools:llm_status",
    "list_models": "backend.agent.tools:list_models",
    "token_usage": "backend.agent.tools:token_usage",
    # RAG tools
    "rag_search": "backend.rag.retriever:search",
    "rag_ingest": "backend.rag.ingest:ingest_document",
    "rag_status": "backend.agent.tools:rag_status",
    "rag_crawl":  "backend.rag.crawler:crawl_url",
    # Expert tools
    "expert_analyze":  "backend.agent.tools:expert_analyze",
    "generate_insight":"backend.agent.tools:generate_insight",
    "list_insights":   "backend.agent.tools:list_insights",
    # Scheduler
    "schedule_task": "gateway.scheduler:schedule_task",
    "list_tasks":    "gateway.scheduler:list_tasks",
    "cancel_task":   "gateway.scheduler:cancel_task",
    # Exec
    "exec_command":    "daemon.tools.exec:exec_command",
    "exec_powershell": "daemon.tools.exec:exec_powershell",
    "exec_bash":       "daemon.tools.exec:exec_bash",
}

PERMISSION_LEVELS = {"read": 0, "write": 1, "exec": 2, "dangerous": 3}


def resolve_tool_function(tool_name: str) -> Callable | None:
    """Resolve a tool name to its Python function. Returns None if not importable."""
    import_path = TOOL_MAP.get(tool_name)
    if not import_path:
        logger.debug(f"[tool_loader] No mapping for tool: {tool_name}")
        return None
    try:
        module_path, func_name = import_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        logger.debug(f"[tool_loader] Could not load {tool_name} ({import_path}): {e}")
        return None


def get_enabled_tools(manifests: list, process: str) -> dict[str, dict]:
    """Return {tool_name: {fn, permission, module}} for the given process.

    Only includes tools from manifests matching the given process name
    where the Python function is actually importable.
    """
    enabled: dict[str, dict] = {}
    for manifest in manifests:
        if manifest.process != process:
            continue
        permission = manifest.safety.max_permission
        for tool_name in manifest.provides_tools:
            fn = resolve_tool_function(tool_name)
            if fn is not None:
                enabled[tool_name] = {
                    "fn": fn,
                    "permission": permission,
                    "module": manifest.name,
                    "permission_level": PERMISSION_LEVELS.get(permission, 0),
                }
    return enabled
