"""
Netscope tool registry — lazy-loading, self-documenting tool system.

Tool modules are imported on demand via ensure_category() / ensure_all().
This keeps startup fast and lets build_prompt() load only the categories
relevant to the current query.

Registration side-effects (register(ToolDef(...)) calls at module bottom)
fire on first import — subsequent calls to ensure_category() are no-ops
because the module is already in sys.modules.
"""
from __future__ import annotations
import importlib

from agent.tools.registry import (
    ToolDef,
    ToolResult,
    TOOL_REGISTRY,
    MAX_OUTPUT,
    register,
    dispatch,
    build_prompt,
    build_tool_names,
    parse_tool_call,
    list_tools,
)

# ── Lazy category → module map ────────────────────────────────────────────────

_CATEGORY_MODULES: dict[str, str] = {
    "network":     "agent.tools.network",
    "modbus":      "agent.tools.modbus",
    "analysis":    "agent.tools.analysis",
    "system":      "agent.tools.system",
    "rag":         "agent.tools.rag",
    "workflow":    "agent.tools.workflows",
    "ics":         "agent.tools.ics",
    "expert":      "agent.tools.expert_info",
    "meta":        "agent.tools.meta",
    "trafficmap":  "agent.tools.traffic_map",
    "topology":    "agent.tools.topology_map",
    "exec":        "agent.tools.exec",
}

# Category-level keyword map — used by build_prompt() and ensure_category()
# to decide which modules to lazy-load without needing them imported yet.
CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "network":  {
        "ping", "tracert", "traceroute", "arp", "netstat", "ipconfig",
        "capture", "sniff", "monitor", "interface", "traffic", "live",
        "connectivity", "latency", "slow", "unreachable", "route", "gateway",
    },
    "modbus":   {
        "modbus", "register", "plc", "scada", "ics", "ot", "inverter",
        "sma", "fronius", "meter", "battery", "drive", "unit_id", "coil",
        "holding", "function code", "fc", "industrial",
    },
    "analysis": {
        "packet", "packets", "analyze", "analysis", "insight", "expert",
        "anomaly", "scan", "flow", "audit", "detect",
        "protocol", "conversation", "port_scan", "ics_audit",
        "dnp3", "filter", "display", "tshark", "wireshark",
    },
    "system":   {
        "system", "status", "llm", "model", "token", "health",
        "vram", "backend", "component", "loaded", "models",
    },
    "rag":      {
        "rag", "knowledge", "document", "kb", "search", "lookup",
        "documentation", "manual", "datasheet", "reference", "rfc", "spec",
    },
    "workflow": {
        "audit", "recon", "workflow", "full", "comprehensive",
        "reconnaissance", "network overview",
    },
    "ics":      {
        "ics", "scada", "dnp3", "substation", "crob",
        "display filter", "outstation", "rtu",
    },
    "expert":   {
        "tshark_expert", "expert analysis", "retransmission",
        "malformed", "protocol warning",
    },
    "meta":       {
        "skill", "skills", "create skill", "new skill", "edit skill",
        "list skills", "delete skill", "reload skills", "add capability",
    },
    "trafficmap": {
        "traffic map", "trafficmap", "host graph", "network graph",
        "node graph", "show map", "open map", "who is talking",
        "hosts and flows", "flow map", "ip graph",
        "traffic visualization", "open traffic map",
    },
    "topology": {
        "topology", "topo", "network map", "device map", "diagram",
        "switch port", "firewall port", "physical topology", "layer 2",
        "l2 topology", "switch diagram", "port mapping", "cdp", "lldp",
        "arp map", "network diagram", "draw network", "connected to",
        "plugged into", "which port", "topology scan",
    },
    "exec": {
        "exec", "execute", "run", "command", "shell", "cmd", "powershell",
        "terminal", "script", "bash",
    },
}

# Categories always loaded (tools that should always be available)
_ALWAYS_LOADED: set[str] = {"network", "system"}

_loaded_categories: set[str] = set()


def ensure_category(category: str) -> None:
    """Load a tool module the first time its category is needed (no-op after)."""
    if category in _loaded_categories:
        return
    module_path = _CATEGORY_MODULES.get(category)
    if module_path:
        importlib.import_module(module_path)
        _loaded_categories.add(category)


def ensure_all() -> None:
    """Eagerly load every tool category. Used for /tools API and tests."""
    for category in _CATEGORY_MODULES:
        ensure_category(category)


def categories_for_question(question: str) -> set[str]:
    """Return the set of categories whose keywords appear in *question*."""
    q = question.lower()
    matched = set(_ALWAYS_LOADED)
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in kws):
            matched.add(cat)
    return matched


# Pre-load always-on categories at import time (fast — only 2 modules)
for _cat in _ALWAYS_LOADED:
    ensure_category(_cat)


__all__ = [
    "ToolDef", "ToolResult", "TOOL_REGISTRY", "MAX_OUTPUT",
    "register", "dispatch", "build_prompt", "build_tool_names",
    "parse_tool_call", "list_tools",
    "ensure_category", "ensure_all", "categories_for_question",
    "CATEGORY_KEYWORDS", "_loaded_categories",
]
