"""
Unified LLM client using the openai SDK.
Supports both Ollama and LM Studio via base_url override.
Tracks token usage globally.
"""

from __future__ import annotations
import asyncio
import re
from openai import AsyncOpenAI
from config import settings, get_active_llm_config
from typing import AsyncGenerator

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Hard timeout for any single LLM completion request.
# Local models on CPU can be slow; 120s prevents indefinite hangs.
_LLM_TIMEOUT_SECONDS = 120

# Global token usage counters
_token_usage = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "requests": 0,
}


def get_token_usage() -> dict:
    return dict(_token_usage)


def reset_token_usage():
    _token_usage["prompt_tokens"] = 0
    _token_usage["completion_tokens"] = 0
    _token_usage["total_tokens"] = 0
    _token_usage["requests"] = 0


def _update_usage(usage):
    if usage:
        _token_usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
        _token_usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        _token_usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
        _token_usage["requests"] += 1


# ── Thinking toggle (runtime, not config-file) ───────────────────────────────
# Set via POST /api/llm/thinking.  Passed as extra_body={"think": …} to
# Ollama for models that support extended reasoning (qwen3, deepseek-r1…).
# LM Studio ignores unknown extra_body fields silently.

_thinking_enabled: bool = False


def get_thinking_enabled() -> bool:
    return _thinking_enabled


def set_thinking_enabled(value: bool) -> None:
    global _thinking_enabled
    _thinking_enabled = value


_cached_client: AsyncOpenAI | None = None
_cached_client_key: str = ""


def get_client() -> tuple[AsyncOpenAI, str]:
    """Return (client, model_name) for the currently active LLM backend.

    Reuses a cached AsyncOpenAI instance (persistent TCP connection via httpx)
    as long as the backend config hasn't changed.
    """
    global _cached_client, _cached_client_key
    cfg = get_active_llm_config()
    key = f"{cfg['base_url']}|{cfg['api_key']}"
    if _cached_client is None or key != _cached_client_key:
        _cached_client = AsyncOpenAI(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
        )
        _cached_client_key = key
    return _cached_client, cfg["model"]


async def chat_completion(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send messages to the LLM, return full response text, track token usage."""
    client, model = get_client()
    # Only inject think:true when the user has explicitly enabled thinking.
    # Passing think:false to models that don't support it causes 400 errors on
    # some Ollama versions, so we omit the param entirely when it's off.
    extra: dict = {"think": True} if (_thinking_enabled and settings.llm_backend == "ollama") else {}
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature if temperature is not None else settings.llm_temperature,
                max_tokens=max_tokens if max_tokens is not None else settings.llm_max_tokens,
                stream=False,
                **({"extra_body": extra} if extra else {}),
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"LLM request timed out after {_LLM_TIMEOUT_SECONDS}s. "
            "Check that the model is loaded and the backend is responsive."
        )
    _update_usage(response.usage)
    text = response.choices[0].message.content or ""
    return _THINK_RE.sub("", text).strip()


# ── Think-tag parser ─────────────────────────────────────────────────────────

async def _strip_think_tags(
    stream: AsyncGenerator[str, None],
) -> AsyncGenerator[tuple[str, bool], None]:
    """Detect <think>...</think> tags in a token stream.

    Yields (text, is_reasoning) tuples.  Tags themselves are consumed
    and never yielded.  Handles tags split across multiple chunks.
    """
    in_think = False
    buf = ""
    async for token in stream:
        buf += token
        while buf:
            if not in_think:
                idx = buf.find("<think>")
                if idx >= 0:
                    if idx > 0:
                        yield (buf[:idx], False)
                    buf = buf[idx + 7:]
                    in_think = True
                else:
                    hold = 0
                    for k in range(1, min(7, len(buf) + 1)):
                        if "<think>".startswith(buf[-k:]):
                            hold = k
                            break
                    if hold:
                        if len(buf) > hold:
                            yield (buf[:-hold], False)
                        buf = buf[-hold:]
                        break
                    else:
                        yield (buf, False)
                        buf = ""
            else:
                idx = buf.find("</think>")
                if idx >= 0:
                    if idx > 0:
                        yield (buf[:idx], True)
                    buf = buf[idx + 8:]
                    in_think = False
                else:
                    hold = 0
                    for k in range(1, min(8, len(buf) + 1)):
                        if "</think>".startswith(buf[-k:]):
                            hold = k
                            break
                    if hold:
                        if len(buf) > hold:
                            yield (buf[:-hold], True)
                        buf = buf[-hold:]
                        break
                    else:
                        yield (buf, True)
                        buf = ""
    if buf:
        yield (buf, in_think)


async def chat_completion_stream(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncGenerator[tuple[str, bool], None]:
    """Send messages to LLM, yield (token, is_reasoning) tuples as they stream."""
    client, model = get_client()
    extra: dict = {"think": True} if (_thinking_enabled and settings.llm_backend == "ollama") else {}
    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature if temperature is not None else settings.llm_temperature,
                max_tokens=max_tokens if max_tokens is not None else settings.llm_max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **({"extra_body": extra} if extra else {}),
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"LLM stream request timed out after {_LLM_TIMEOUT_SECONDS}s."
        )

    # Two reasoning formats (mutually exclusive per model):
    # 1. Native: delta.reasoning field (Ollama qwen3.5+, OpenAI o-series)
    # 2. Legacy: <think>...</think> tags inside delta.content (older qwen3)

    has_native = False
    in_think = False

    async for chunk in stream:
        if chunk.usage:
            _update_usage(chunk.usage)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # Native reasoning field (qwen3.5+, o-series)
        reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
        if reasoning:
            has_native = True
            yield (reasoning, True)

        content = delta.content or ""
        if not content:
            continue

        if has_native:
            yield (content, False)
        else:
            # Legacy: inline <think> tag detection
            if not in_think and "<think>" in content:
                before, _, content = content.partition("<think>")
                if before:
                    yield (before, False)
                in_think = True
            if in_think and "</think>" in content:
                before, _, after = content.partition("</think>")
                if before:
                    yield (before, True)
                in_think = False
                if after:
                    yield (after, False)
            elif content:
                yield (content, in_think)


async def check_llm_status() -> dict:
    """Check if the current LLM backend is reachable, and fetch VRAM usage."""
    import httpx
    cfg = get_active_llm_config()
    base = cfg["base_url"].replace("/v1", "").rstrip("/")

    reachable = False
    vram_info: dict = {}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base}/")
            reachable = resp.status_code < 500

            # Ollama exposes /api/ps — list of loaded models with VRAM sizes.
            # LM Studio does not have this endpoint; we skip gracefully on error.
            if reachable and settings.llm_backend == "ollama":
                try:
                    ps = await client.get(f"{base}/api/ps", timeout=2.0)
                    if ps.status_code == 200:
                        models = ps.json().get("models") or []
                        # Sum across all loaded models
                        total_vram  = sum(m.get("size_vram", 0) for m in models)
                        total_size  = sum(m.get("size", 0)      for m in models)
                        active_model = next(
                            (m for m in models if m.get("name") == cfg["model"]),
                            models[0] if models else None,
                        )
                        vram_info = {
                            "vram_used_bytes":  total_vram,
                            "model_size_bytes": total_size,
                            # Per active model details
                            "context_length":   active_model.get("context_length") if active_model else None,
                            "expires_at":       active_model.get("expires_at")     if active_model else None,
                        }
                except Exception:
                    pass
    except Exception:
        pass

    return {
        "backend":    settings.llm_backend,
        "base_url":   cfg["base_url"],
        "model":      cfg["model"],
        "reachable":  reachable,
        "token_usage": get_token_usage(),
        **vram_info,
    }
