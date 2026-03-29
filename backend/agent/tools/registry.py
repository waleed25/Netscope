"""
Unified tool registry — lazy-loading, self-documenting tool system.

Every tool is a ToolDef dataclass registered in TOOL_REGISTRY.
Single source of truth for tool names, descriptions, dispatch, prompt generation.

Prompt building follows the Agent Skills three-level progressive disclosure pattern:
  L1 — build_tool_names() : name + one-liner only (~15 tokens/tool, always injected)
  L2 — build_prompt()     : full descriptions for keyword-matched categories only
  L3 — (future)           : OpenAI tools=[] native function calling via build_tool_schemas()
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any

from agent.tools.audit import get_audit_log

# ── Max output chars fed back to LLM ─────────────────────────────────────────
MAX_OUTPUT = 3000


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class ToolDef:
    name: str                                          # "ping", "capture"
    category: str                                      # "network", "modbus", etc.
    description: str                                   # one-line for LLM prompt
    args_spec: str                                     # "<host>" or "[seconds]" or ""
    runner: Callable[[str], Awaitable[str]]             # async function(args) → result
    safety: str = "safe"                               # "safe" | "read" | "write" | "dangerous"
    keywords: set[str] = field(default_factory=set)    # trigger words for context selection
    always_available: bool = False                     # always shown to LLM
    needs_packets: bool = False                        # only when packets exist
    is_workflow: bool = False                          # composite multi-step


@dataclass
class ToolResult:
    tool: str
    status: str          # "ok" | "error"
    output: str
    duration_ms: float
    safety: str


# ── Registry ─────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, ToolDef] = {}


def register(tool: ToolDef) -> ToolDef:
    """Register a tool. Called at module import time."""
    TOOL_REGISTRY[tool.name] = tool
    return tool


# ── Permission levels for tool safety enforcement ────────────────────────────

_PERMISSION_LEVELS = {"read": 0, "write": 1, "exec": 2, "dangerous": 3}


def check_permission(tool_name: str, allow_dangerous: bool = False) -> bool:
    """Returns True if the tool can be called with the given permissions.
    Dangerous tools require explicit allow_dangerous=True."""
    # Block known exec/dangerous tools unless allow_dangerous is set
    try:
        from shared.manifests.tool_loader import TOOL_MAP, PERMISSION_LEVELS  # noqa: F401
        if tool_name in ("exec_command", "exec_powershell", "exec_bash"):
            return allow_dangerous
    except ImportError:
        pass
    # Fall back to ToolDef.safety for tools in the local registry
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is not None and tool.safety == "dangerous":
        return allow_dangerous
    return True


# ── Dispatch ─────────────────────────────────────────────────────────────────

async def dispatch(
    name: str,
    args: str,
    allow_dangerous: bool = False,
) -> ToolResult:
    """
    Single entry point for all tool execution (except capture, which is special).
    Handles safety gating, ATPA sanitization, timing, truncation, and audit logging.
    """
    from utils.sanitize import sanitize_tool_output

    tool = TOOL_REGISTRY.get(name)
    if not tool:
        return ToolResult(
            tool=name, status="error",
            output=f"[tool error] Unknown tool: '{name}'",
            duration_ms=0, safety="safe",
        )

    # Manifest permission gate: check before the local safety gate
    if not check_permission(name, allow_dangerous=allow_dangerous):
        return ToolResult(
            tool=name, status="error",
            output=f"[safety] Tool '{name}' requires allow_dangerous=True",
            duration_ms=0, safety="dangerous",
        )

    # Safety gate: reject dangerous tools unless explicitly allowed
    if tool.safety == "dangerous" and not allow_dangerous:
        return ToolResult(
            tool=name, status="error",
            output=f"[safety] Tool '{name}' has safety=dangerous and requires explicit user confirmation.",
            duration_ms=0, safety=tool.safety,
        )

    start = time.monotonic()
    try:
        output = await tool.runner(args)
        status = "ok"
    except Exception as e:
        output = f"[{name} error] {e}"
        status = "error"

    duration_ms = (time.monotonic() - start) * 1000

    # ATPA defense: sanitize tool output before it enters the LLM context
    output = sanitize_tool_output(output)

    # Truncate large output
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n...[truncated — {len(output)} chars total]"

    result = ToolResult(
        tool=name, status=status, output=output,
        duration_ms=duration_ms, safety=tool.safety,
    )

    # Audit log
    try:
        get_audit_log().append(result, args)
    except Exception:
        pass  # audit failure is non-fatal

    return result


# ── Tool call parsing ────────────────────────────────────────────────────────

def parse_tool_call(line: str) -> tuple[str, str] | None:
    """
    If `line` contains a TOOL: directive, return (tool_name, args).
    Returns None if the line is not a TOOL: directive or the tool is unknown.
    """
    stripped = line.strip()
    if not stripped.upper().startswith("TOOL:"):
        return None
    rest = stripped[5:].strip()
    parts = rest.split(None, 1)
    if not parts:
        return None
    name = parts[0].lower().strip("`")
    args = parts[1] if len(parts) > 1 else ""
    # Strip common LLM formatting artifacts: brackets, backticks, quotes
    args = args.strip().strip("[]`\"'")
    if name not in TOOL_REGISTRY:
        return None
    return name, args


# ── Prompt builder ───────────────────────────────────────────────────────────

# Category display order
_CATEGORY_ORDER = ["network", "system", "analysis", "rag", "modbus", "ics", "workflow", "trafficmap", "meta", "exec"]

# Tools that are always shown regardless of keyword matching (minimal set)
# Deliberately small — too many always-available tools flood the prompt.
_ALWAYS_SHOW = {"ping", "capture", "system_status"}


def build_tool_names(loaded_only: bool = True) -> str:
    """
    L1 prompt injection: tool names + one-liners only (~15 tokens/tool).

    Injects ALL registered tools as a compact awareness list so the LLM
    knows what capabilities exist before keyword-matched tools are loaded.
    This is the Agent Skills 'metadata' layer — cheap and always present.
    """
    if not TOOL_REGISTRY:
        return ""
    lines = ["Available tools (call with: TOOL: <name> [args]):"]
    for cat in _CATEGORY_ORDER:
        cat_tools = [t for t in TOOL_REGISTRY.values() if t.category == cat]
        if not cat_tools:
            continue
        for t in sorted(cat_tools, key=lambda x: x.name):
            lines.append(f"  {t.name}: {t.description[:80]}")
    return "\n".join(lines)


def build_prompt(
    question: str,
    rag_enabled: bool = False,
    has_packets: bool = False,
    categories: set[str] | None = None,
) -> str:
    """
    L2 prompt injection: full descriptions for keyword-matched categories.

    *categories* — pre-computed set from categories_for_question(); if None,
    falls back to keyword matching against each tool's own keywords set.

    Derived entirely from TOOL_REGISTRY — no manual category lists to maintain.
    """
    q_lower = question.lower()
    sections: dict[str, list[str]] = {}

    for tool in TOOL_REGISTRY.values():
        # Include if: always-show, in matched categories, RAG enabled, or packets present
        in_categories = (categories is not None and tool.category in categories)
        include = (
            tool.name in _ALWAYS_SHOW
            or in_categories
            or any(kw in q_lower for kw in tool.keywords)
            or (tool.category == "rag" and rag_enabled)
            or (tool.needs_packets and has_packets)
        )
        if not include:
            continue

        cat = tool.category
        line = f"  TOOL: {tool.name}"
        if tool.args_spec:
            line += f" {tool.args_spec}"
        # Pad to 38 chars for alignment
        line = line.ljust(38) + f"— {tool.description}"

        sections.setdefault(cat, []).append(line)

    if not sections:
        return ""

    # Assemble in category order
    header = "You have tools. To use one, output EXACTLY one line:  TOOL: <name> [args]\n"
    blocks: list[str] = []
    for cat in _CATEGORY_ORDER:
        if cat not in sections:
            continue
        label = cat.title() if cat != "rag" else "Knowledge Base"
        if cat == "workflow":
            label = "Workflows (multi-step)"
        elif cat == "ics":
            label = "ICS / SCADA"
        elif cat == "meta":
            label = "Agent Management"
        blocks.append(f"{label}:\n" + "\n".join(sorted(sections[cat])))

    rules = (
        "\nRules:\n"
        "- Only call a tool when you need data you don't already have.\n"
        "- After TOOL_RESULT, analyze it and respond — do NOT call the same tool again.\n"
        "- Never invent tool output; always wait for TOOL_RESULT."
    )

    return header + "\n" + "\n\n".join(blocks) + rules


# ── Introspection (for API) ──────────────────────────────────────────────────

def list_tools(ensure_loaded: bool = True) -> list[dict]:
    """Return all registered tools as dicts (for API response).

    *ensure_loaded* — if True (default), lazily loads all tool modules first
    so the response is complete even if a category hasn't been used yet.
    """
    if ensure_loaded:
        try:
            from agent.tools import ensure_all
            ensure_all()
        except ImportError:
            pass  # called before package fully initialized (tests)
    return [
        {
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "args_spec": t.args_spec,
            "safety": t.safety,
            "always_available": t.always_available,
            "needs_packets": t.needs_packets,
            "is_workflow": t.is_workflow,
            "keywords": sorted(t.keywords) if t.keywords else [],
        }
        for t in TOOL_REGISTRY.values()
    ]
