"""
System tools: system_status, llm_status, list_models, token_usage.
"""
from __future__ import annotations
from agent.tools.registry import register, ToolDef


async def run_system_status(args: str = "") -> str:
    import json
    from api.routes import system_status as _ep
    result = await _ep()
    return json.dumps(result, default=str)


async def run_llm_status(args: str = "") -> str:
    import json
    from agent.llm_client import check_llm_status
    return json.dumps(await check_llm_status(), default=str)


async def run_list_models(args: str = "") -> str:
    import json
    import httpx
    from config import settings
    try:
        if settings.llm_backend == "ollama":
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
            active = settings.ollama_model
        else:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("http://localhost:1234/v1/models")
                models = [m["id"] for m in resp.json().get("data", [])]
            active = settings.lmstudio_model
        return json.dumps({"models": models, "active": active})
    except Exception as e:
        return json.dumps({"models": [], "active": "", "error": str(e)})


async def run_token_usage(args: str = "") -> str:
    import json
    from agent.llm_client import get_token_usage
    return json.dumps(get_token_usage())


# ── Registration ─────────────────────────────────────────────────────────────

register(ToolDef(
    name="system_status", category="system",
    description="health of all components",
    args_spec="", runner=run_system_status,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="llm_status", category="system",
    description="LLM backend, model, VRAM",
    args_spec="", runner=run_llm_status,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="list_models", category="system",
    description="available LLM models",
    args_spec="", runner=run_list_models,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="token_usage", category="system",
    description="token usage statistics",
    args_spec="", runner=run_token_usage,
    safety="safe", always_available=True,
))
