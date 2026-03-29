"""Sentence-transformers embeddings adapter (GPU or CPU)."""
from __future__ import annotations
import numpy as np


class SentenceTFAdapter:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None

    def model_name(self) -> str:
        return self._model_name

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer(self._model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        return self._model.encode(texts, convert_to_numpy=True)
