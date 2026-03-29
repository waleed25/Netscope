"""OpenAI-compatible API adapter — for LM Studio, OpenAI, or any compatible endpoint."""
from __future__ import annotations
from typing import AsyncIterator


class OpenAIAdapter:
    """Adapter for any OpenAI-compatible API (OpenAI, LM Studio, vLLM, etc.)."""
    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 api_key: str = "not-needed",
                 model: str = "gpt-3.5-turbo"):
        self.base_url = base_url
        self.api_key = api_key
        self._model = model

    def model_name(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    def _client(self):
        from openai import AsyncOpenAI  # type: ignore
        return AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)

    async def complete(self, messages: list[dict], **kwargs) -> str:
        client = self._client()
        resp = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=False,
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        client = self._client()
        async with client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            **kwargs,
        ) as resp:
            async for chunk in resp:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
