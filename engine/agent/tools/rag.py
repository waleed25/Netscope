"""
RAG / Knowledge Base tools: rag_status, rag_search.
"""
from __future__ import annotations
from agent.tools.registry import register, ToolDef, MAX_OUTPUT


def _safe_str(value: object, max_len: int = 300) -> str:
    s = str(value) if value is not None else ""
    return "".join(c for c in s if c.isprintable())[:max_len]


async def run_rag_status(args: str = "") -> str:
    import asyncio
    import json
    try:
        from rag.ingest import _collection
        if _collection is None:
            return json.dumps({"status": "not_initialized", "chunks": 0})
        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(None, _collection.count)
        return json.dumps({"status": "ok", "chunks": count})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


async def run_rag_search(args: str = "") -> str:
    import json
    query = args.strip()
    if not query:
        return "[rag_search] Usage: rag_search <query>"
    try:
        from rag.retriever import retrieve_for_query, has_documents
        if not has_documents():
            return json.dumps({"results": [], "message": "Knowledge base is empty. Upload documents first."})
        ctx, chunks, score = await retrieve_for_query(query, n_results=5)
        results = [{
            "source": getattr(c, "source", ""),
            "score": round(getattr(c, "score", 0), 3),
            "text": _safe_str(getattr(c, "text", "")),
        } for c in chunks]
        return json.dumps({"query": query, "best_score": round(score, 3), "results": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ─────────────────────────────────────────────────────────────

register(ToolDef(
    name="rag_status", category="rag",
    description="KB health and chunk count",
    args_spec="", runner=run_rag_status,
    safety="safe",
    keywords={"rag", "knowledge", "document", "kb", "documentation", "manual", "datasheet", "reference"},
))

register(ToolDef(
    name="rag_search", category="rag",
    description="search the knowledge base",
    args_spec="<query>", runner=run_rag_search,
    safety="read",
    keywords={"rag", "knowledge", "document", "kb", "search", "lookup", "documentation", "manual", "datasheet", "reference"},
))
