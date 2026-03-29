"""Embeddings capability adapter."""
from __future__ import annotations
from typing import Protocol, runtime_checkable
import numpy as np


@runtime_checkable
class EmbeddingsAdapter(Protocol):
    def encode(self, texts: list[str]) -> "np.ndarray": ...
    def model_name(self) -> str: ...


def detect_embeddings(caps) -> "EmbeddingsAdapter":
    """Select best embeddings adapter for detected hardware."""
    from .sentence_tf import SentenceTFAdapter
    from .openai_emb import OpenAIEmbeddingsAdapter

    if caps.ram_gb >= 4:
        return SentenceTFAdapter()
    else:
        return OpenAIEmbeddingsAdapter()
