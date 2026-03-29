"""LLM capability adapter — unified interface regardless of GPU/CPU/API backend."""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class LLMAdapter(Protocol):
    async def complete(self, messages: list[dict], **kwargs) -> str: ...
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...
    def model_name(self) -> str: ...


def detect_llm(caps, config) -> "LLMAdapter":
    """Select the best LLM adapter for the detected hardware and config.

    Priority:
      1. If config specifies a backend, use it
      2. GPU with sufficient VRAM → Ollama (local GPU)
      3. Sufficient RAM for CPU inference → LlamaCpp
      4. Fallback → OpenAI-compatible API endpoint
    """
    from .ollama import OllamaAdapter
    from .llamacpp import LlamaCppAdapter
    from .openai_api import OpenAIAdapter

    backend = getattr(config, "llm_backend", None)
    if backend == "lmstudio":
        return OpenAIAdapter(base_url=getattr(config, "lmstudio_base_url", "http://localhost:1234/v1"))
    if backend == "openai":
        return OpenAIAdapter(base_url=getattr(config, "openai_base_url", "https://api.openai.com/v1"),
                              api_key=getattr(config, "openai_api_key", ""))
    if backend == "ollama":
        return OllamaAdapter(base_url=getattr(config, "ollama_base_url", "http://localhost:11434"))

    # Auto-detect
    if caps.gpu_vram_gb >= 4:
        return OllamaAdapter(base_url=getattr(config, "ollama_base_url", "http://localhost:11434"))
    elif caps.ram_gb >= 6:
        return LlamaCppAdapter()
    else:
        return OpenAIAdapter(
            base_url=getattr(config, "lmstudio_base_url",
                             getattr(config, "openai_base_url", "http://localhost:1234/v1"))
        )
