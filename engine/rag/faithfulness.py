"""
Post-generation faithfulness checker using Vectara HHEM-2.1-Open.

HHEM (Hallucination Evaluation Model) is a T5-based binary classifier
that scores whether a generated claim is consistent with a given context.

  score = 1.0  → fully consistent (not hallucinated)
  score = 0.0  → contradicts / not supported by context (hallucinated)

The model (~400MB) downloads automatically from HuggingFace on first use
and runs entirely on CPU — no GPU or API key required.

Threshold: FAITHFULNESS_THRESHOLD (default 0.5).
Responses below threshold are flagged; the caller decides whether to retry
or show a warning to the user.

Public API:
  check_faithfulness(response, context_chunks) -> FaithfulnessResult
  is_ready()                                   -> bool
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

FAITHFULNESS_THRESHOLD = 0.5   # responses below this score get flagged
MODEL_NAME = "vectara/hallucination_evaluation_model"

# Module-level pipeline singleton (lazy init)
_hhem_pipeline = None
_hhem_available: bool | None = None   # None = not checked yet


@dataclass
class FaithfulnessResult:
    score:      float         # 0.0–1.0 (higher = more faithful)
    passed:     bool          # score >= FAITHFULNESS_THRESHOLD
    label:      str           # "consistent" or "hallucinated"
    checked:    bool = True   # False if HHEM was unavailable
    error:      str  = ""


# ── Singleton loader ──────────────────────────────────────────────────────────

def _get_hhem() -> Any | None:
    """Lazily load the HHEM pipeline. Returns None if unavailable."""
    global _hhem_pipeline, _hhem_available

    if _hhem_available is False:
        return None
    if _hhem_pipeline is not None:
        return _hhem_pipeline

    try:
        from transformers import pipeline as hf_pipeline
        _hhem_pipeline = hf_pipeline(
            "text-classification",
            model=MODEL_NAME,
            device="cpu",        # CPU-only
            truncation=True,
            max_length=512,
        )
        _hhem_available = True
        log.info("[faithfulness] HHEM model loaded successfully")
        return _hhem_pipeline
    except Exception as exc:
        _hhem_available = False
        log.warning("[faithfulness] HHEM unavailable: %s", exc)
        return None


def is_ready() -> bool:
    """Return True if HHEM is loaded and functional."""
    return _get_hhem() is not None


# ── Core check ────────────────────────────────────────────────────────────────

def _run_hhem(response: str, context: str) -> FaithfulnessResult:
    """
    Run HHEM synchronously.
    Input format: "{context} [SEP] {claim}"
    """
    pipe = _get_hhem()
    if pipe is None:
        return FaithfulnessResult(score=1.0, passed=True, label="unknown", checked=False)

    # Truncate to avoid overwhelming the 512-token model
    ctx_part  = context[:800]
    resp_part = response[:400]
    text      = f"{ctx_part} [SEP] {resp_part}"

    try:
        result = pipe(text)[0]
        label  = result["label"].lower()    # "consistent" or "hallucinated"
        raw    = float(result["score"])

        # HHEM returns confidence for the predicted label.
        # Normalise to a 0–1 faithfulness score:
        #   label=consistent   → score = raw confidence
        #   label=hallucinated → score = 1 - raw confidence
        if label == "consistent":
            faith_score = raw
        else:
            faith_score = 1.0 - raw

        return FaithfulnessResult(
            score   = round(faith_score, 4),
            passed  = faith_score >= FAITHFULNESS_THRESHOLD,
            label   = label,
            checked = True,
        )
    except Exception as exc:
        return FaithfulnessResult(
            score=1.0, passed=True, label="unknown", checked=False, error=str(exc)
        )


async def check_faithfulness(
    response:       str,
    context_chunks: list[Any],   # list[ChunkResult] from retriever
) -> FaithfulnessResult:
    """
    Async faithfulness check.

    *context_chunks* is the list of ChunkResult objects returned by
    retriever.retrieve_for_query(). Their window_text fields are joined
    to form the reference context for HHEM.
    """
    if not context_chunks:
        # No context to check against — cannot evaluate
        return FaithfulnessResult(score=1.0, passed=True, label="no_context", checked=False)

    # Build the reference context string from retrieved windows
    context_parts = []
    for chunk in context_chunks[:3]:   # top-3 most relevant
        wt = getattr(chunk, "window_text", "") or str(chunk)
        context_parts.append(wt[:600])
    context = "\n---\n".join(context_parts)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _run_hhem(response, context),
    )
    return result


# Allow import-time type annotation without importing the dataclass
from typing import Any
