"""OpenAI embeddings adapter fallback (no local models required)."""
from __future__ import annotations
import numpy as np


class OpenAIEmbeddingsAdapter:
    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 api_key: str = "not-needed",
                 model: str = "text-embedding-3-small"):
        self.base_url = base_url
        self.api_key = api_key
        self._model = model

    def model_name(self) -> str:
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._encode_async(texts))

    async def _encode_async(self, texts: list[str]) -> np.ndarray:
        from openai import AsyncOpenAI  # type: ignore
        client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        resp = await client.embeddings.create(model=self._model, input=texts)
        vectors = [item.embedding for item in resp.data]
        return np.array(vectors, dtype=np.float32)
