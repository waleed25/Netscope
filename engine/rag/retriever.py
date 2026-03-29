"""
Context-aware retrieval pipeline.

Query flow:
  1. (Optional) HyDE: generate a hypothetical answer, embed that instead
  2. Semantic query → ChromaDB top-50 (cosine similarity)
  3. Lexical query  → BM25 top-50
  4. Reciprocal Rank Fusion → merged top-50
  5. FlashRank cross-encoder reranking → top-N
  6. Similarity threshold gate: if best score < MIN_SCORE → "not in KB"
  7. Window expansion: swap embed_text for window_text from metadata
  8. Format for prompt injection

Public API:
  retrieve(query, n_results, source_filter, use_hyde) -> list[ChunkResult]
  format_for_prompt(chunks)                           -> str
  retrieve_for_query(query, n_results, use_hyde)      -> str  (async)
  has_documents()                                     -> bool
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

# Minimum cosine similarity score to consider a result "in KB".
# ChromaDB returns cosine distances (0=identical, 2=opposite).
# We convert: similarity = 1 - distance/2  (gives 0..1 range)
MIN_SIMILARITY = 0.30   # below this → "not in KB"
MAX_RESULTS    = 5


@dataclass
class ChunkResult:
    doc_id:         str
    source:         str
    window_text:    str
    context_prefix: str
    embed_text:     str
    similarity:     float   # 0..1, higher = more relevant
    rerank_score:   float   # FlashRank score (higher = better)
    page:           int


# ── Utility ───────────────────────────────────────────────────────────────────

def has_documents() -> bool:
    """Return True if the vector store has any documents."""
    try:
        from rag.ingest import total_chunk_count
        return total_chunk_count() > 0
    except Exception:
        return False


def _cosine_distance_to_similarity(distance: float) -> float:
    """Convert ChromaDB cosine distance (0..2) to similarity (0..1)."""
    return max(0.0, 1.0 - distance / 2.0)


# ── HyDE expansion ────────────────────────────────────────────────────────────

async def _hyde_expand(query: str) -> str:
    """
    Generate a hypothetical document that would answer *query*.
    Returns the hypothetical text for embedding (not presented to user).
    """
    prompt = (
        "Write a short, factual technical paragraph (3–5 sentences) that directly "
        f"answers the following question:\n\n{query}\n\n"
        "Focus on Wireshark, PAN-OS CLI, network security, or OT/ICS as relevant. "
        "Be specific with command syntax and technical terms. "
        "Reply with only the paragraph, no preamble."
    )
    try:
        from agent.llm_client import chat_completion
        hyp = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )
        return hyp.strip()
    except Exception:
        return query   # fall back to original query on error


# ── Semantic retrieval ────────────────────────────────────────────────────────

# Instruction prepended to queries at retrieval time.
# Must differ from the ingest-side INGEST_INSTRUCTION so the model
# produces appropriately asymmetric query vs. passage embeddings.
QUERY_INSTRUCTION = "Instruct: Given a technical question, retrieve the most relevant document passage that answers it.\nQuery: "


def _semantic_query(
    query_text: str,
    n: int = 50,
    source_filter: str | None = None,
) -> list[dict]:
    """
    Embed *query_text* and query ChromaDB.
    Returns list of {id, document, metadata, distance} dicts.
    """
    from rag.ingest import get_collection, get_embedder

    col      = get_collection()
    embedder = get_embedder()

    # Prepend Qwen3-Embedding query instruction for asymmetric retrieval.
    instructed_query = QUERY_INSTRUCTION + query_text
    q_vec = embedder.encode([instructed_query], normalize_embeddings=True).tolist()

    where = {"source": source_filter} if source_filter else None
    try:
        res = col.query(
            query_embeddings=q_vec,
            n_results=min(n, col.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    results = []
    ids       = res.get("ids",        [[]])[0]
    docs      = res.get("documents",  [[]])[0]
    metas     = res.get("metadatas",  [[]])[0]
    distances = res.get("distances",  [[]])[0]

    for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
        results.append({
            "id":         doc_id,
            "document":   doc,
            "metadata":   meta or {},
            "distance":   dist,
            "similarity": _cosine_distance_to_similarity(dist),
        })
    return results


# ── BM25 retrieval ────────────────────────────────────────────────────────────

def _bm25_query(query_text: str, n: int = 50) -> list[dict]:
    """
    Query the in-memory BM25 index.
    Returns list of {id, score} dicts ordered by score descending.
    """
    from rag.ingest import get_bm25, _bm25_ids, get_collection

    bm25 = get_bm25()
    if bm25 is None or not _bm25_ids:
        return []

    tokens = query_text.lower().split()
    scores = bm25.get_scores(tokens)

    # Pair with IDs and sort
    id_score = sorted(
        zip(_bm25_ids, scores),
        key=lambda x: x[1],
        reverse=True,
    )[:n]

    # Collect all positive-score IDs, then fetch in a single batched call
    col = get_collection()
    positive = [(doc_id, score) for doc_id, score in id_score if score > 0]
    if not positive:
        return []

    all_ids = [doc_id for doc_id, _ in positive]
    score_map = {doc_id: score for doc_id, score in positive}

    try:
        res  = col.get(ids=all_ids, include=["documents", "metadatas"])
        docs  = res.get("documents") or []
        metas = res.get("metadatas") or []
        ids   = res.get("ids") or []
    except Exception:
        return []

    results = []
    for doc_id, doc, meta in zip(ids, docs, metas):
        results.append({
            "id":         doc_id,
            "document":   doc or "",
            "metadata":   meta or {},
            "bm25_score": float(score_map.get(doc_id, 0.0)),
        })

    # Re-sort by original BM25 score (ChromaDB may return in insertion order)
    results.sort(key=lambda x: x["bm25_score"], reverse=True)
    return results


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def _rrf(
    semantic: list[dict],
    lexical:  list[dict],
    k: int = 60,
) -> list[dict]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.
    Returns unified list sorted by RRF score descending.
    """
    scores: dict[str, float] = {}
    meta_store: dict[str, dict] = {}

    for rank, item in enumerate(semantic):
        doc_id = item["id"]
        scores[doc_id]     = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        meta_store[doc_id] = item

    for rank, item in enumerate(lexical):
        doc_id = item["id"]
        scores[doc_id]     = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        if doc_id not in meta_store:
            meta_store[doc_id] = item

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = []
    for doc_id, rrf_score in merged:
        item = dict(meta_store[doc_id])
        item["rrf_score"] = rrf_score
        result.append(item)
    return result


# ── FlashRank reranking ───────────────────────────────────────────────────────

# Singleton reranker — loaded once on first use to avoid per-call model loading.
_ranker = None


def _get_ranker():
    global _ranker
    if _ranker is None:
        from flashrank import Ranker
        _ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir=None)
    return _ranker


def _rerank(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    """
    Rerank *candidates* with FlashRank cross-encoder.
    Falls back to RRF order on error.
    """
    if not candidates:
        return []
    try:
        from flashrank import RerankRequest

        ranker   = _get_ranker()
        passages = [
            {"id": i, "text": c.get("document", ""), "meta": c}
            for i, c in enumerate(candidates)
        ]
        req      = RerankRequest(query=query, passages=passages)
        reranked = ranker.rerank(req)

        result = []
        for r in reranked[:top_n]:
            item = dict(r["meta"])
            item["rerank_score"] = float(r.get("score", 0.0))
            result.append(item)
        return result
    except Exception:
        # FlashRank unavailable — fall back to RRF order
        for item in candidates:
            item["rerank_score"] = item.get("rrf_score", 0.0)
        return candidates[:top_n]


# ── Main retrieve function ────────────────────────────────────────────────────

def retrieve(
    query:         str,
    n_results:     int = MAX_RESULTS,
    source_filter: str | None = None,
    embed_text:    str | None = None,   # pre-computed (e.g. from HyDE)
) -> list[ChunkResult]:
    """
    Synchronous retrieval. If *embed_text* is given it is used for the
    semantic query instead of *query* (used for HyDE).
    """
    semantic_query_text = embed_text or query

    semantic  = _semantic_query(semantic_query_text, n=50, source_filter=source_filter)
    lexical   = _bm25_query(query, n=50)             # always use original query for BM25
    merged    = _rrf(semantic, lexical, k=60)
    reranked  = _rerank(query, merged, top_n=max(n_results * 3, 20))

    chunks: list[ChunkResult] = []
    for item in reranked[:n_results]:
        meta       = item.get("metadata", {})
        similarity = item.get("similarity", 0.0)
        chunks.append(ChunkResult(
            doc_id         = item["id"],
            source         = meta.get("source", "unknown"),
            window_text    = meta.get("window_text", item.get("document", "")),
            context_prefix = meta.get("context_prefix", ""),
            embed_text     = item.get("document", ""),
            similarity     = similarity,
            rerank_score   = item.get("rerank_score", 0.0),
            page           = int(meta.get("page", 0)),
        ))

    return chunks


async def retrieve_async(
    query:         str,
    n_results:     int = MAX_RESULTS,
    source_filter: str | None = None,
    use_hyde:      bool = False,
) -> list[ChunkResult]:
    """Async wrapper — runs CPU-bound work in executor."""
    loop = asyncio.get_running_loop()

    embed_text: str | None = None
    if use_hyde:
        embed_text = await _hyde_expand(query)

    chunks = await loop.run_in_executor(
        None,
        lambda: retrieve(query, n_results, source_filter, embed_text),
    )
    return chunks


# ── Prompt formatting ─────────────────────────────────────────────────────────

def format_for_prompt(chunks: list[ChunkResult]) -> str:
    """
    Format retrieved chunks into a system-prompt context block.
    Sources are numbered so the LLM can cite them as [1], [2], etc.
    """
    if not chunks:
        return ""

    lines = [f"[Knowledge Base — {len(chunks)} relevant section(s)]\n"]
    for i, chunk in enumerate(chunks, 1):
        prefix_line = (
            f"  Context: {chunk.context_prefix}\n"
            if chunk.context_prefix else ""
        )
        lines.append(
            f"[{i}] Source: {chunk.source} | Page: {chunk.page}\n"
            f"{prefix_line}"
            f"{chunk.window_text}\n"
        )

    return "\n".join(lines)


# ── High-level async helper used by chat.py ───────────────────────────────────

async def retrieve_for_query(
    query:         str,
    n_results:     int = MAX_RESULTS,
    source_filter: str | None = None,
    use_hyde:      bool = False,
) -> tuple[str, list[ChunkResult], float]:
    """
    Run the full pipeline for a chat query.

    Returns:
      (formatted_context_str, chunks, best_similarity_score)

    If best_similarity_score < MIN_SIMILARITY the caller should
    respond with "not in KB" instead of calling the LLM.
    """
    if not has_documents():
        return "", [], 0.0

    chunks = await retrieve_async(query, n_results, source_filter, use_hyde)

    if not chunks:
        return "", [], 0.0

    best_score = max(c.similarity for c in chunks)
    if best_score < MIN_SIMILARITY:
        return "", chunks, best_score

    formatted = format_for_prompt(chunks)
    return formatted, chunks, best_score
