"""llama.cpp LLM adapter — for CPU-only machines with 6+ GB RAM."""
from __future__ import annotations
from typing import AsyncIterator


class LlamaCppAdapter:
    """Adapter for llama-cpp-python (CPU inference).
    Lazy-imports llama_cpp to avoid import failure on machines where it's not installed.
    """
    def __init__(self, model_path: str = ""):
        self._model_path = model_path
        self._llm = None

    def model_name(self) -> str:
        return self._model_path or "llama.cpp"

    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama  # type: ignore
            self._llm = Llama(model_path=self._model_path, n_ctx=4096)

    async def complete(self, messages: list[dict], **kwargs) -> str:
        import asyncio
        self._load()
        # llama_cpp is sync — run in thread pool
        prompt = _messages_to_prompt(messages)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._llm(prompt, max_tokens=kwargs.get("max_tokens", 512))
        )
        return result["choices"][0]["text"]

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        import asyncio
        self._load()
        prompt = _messages_to_prompt(messages)
        loop = asyncio.get_running_loop()
        # Sync generator — yield chunks via queue
        import queue, threading
        q: queue.Queue = queue.Queue()

        def _run():
            try:
                for chunk in self._llm(
                    prompt,
                    max_tokens=kwargs.get("max_tokens", 512),
                    stream=True
                ):
                    q.put(chunk["choices"][0]["text"])
            finally:
                q.put(None)

        threading.Thread(target=_run, daemon=True).start()
        while True:
            text = await loop.run_in_executor(None, q.get)
            if text is None:
                break
            yield text


def _messages_to_prompt(messages: list[dict]) -> str:
    """Simple ChatML-style prompt construction for llama.cpp."""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"<|{role}|>\n{content}")
    parts.append("<|assistant|>")
    return "\n".join(parts)
