"""Ollama LLM adapter — for machines with GPU or large RAM."""
from __future__ import annotations
from typing import AsyncIterator
import httpx


class OllamaAdapter:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url.rstrip("/")
        self._model = model

    def model_name(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    async def complete(self, messages: list[dict], **kwargs) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    **kwargs,
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                    **kwargs,
                },
            ) as resp:
                resp.raise_for_status()
                import json as _json
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = _json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except Exception:
                        continue
