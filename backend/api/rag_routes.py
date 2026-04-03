"""
REST API for the RAG (Knowledge Base) subsystem.

Endpoints:
  POST /api/rag/ingest/pdf           — upload PDF/DOCX/PPTX → background ingest
  POST /api/rag/ingest/url           — {url, source_name} → background ingest
  GET  /api/rag/sources              — list sources with chunk counts
  DELETE /api/rag/sources/{name}     — delete source from vector + BM25
  GET  /api/rag/query                — ?q=...&n=5&hyde=false — test retrieval
  POST /api/rag/crawl/wireshark      — trigger Wireshark wiki crawl (background)
  POST /api/rag/crawl/panos          — {base_url, max_pages} PAN-OS crawl (background)
  GET  /api/rag/tasks                — list background task statuses
  GET  /api/rag/status               — {total_chunks, embedding_model, ready}
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from rag.crawler import _is_safe_url

router = APIRouter(prefix="/rag", tags=["rag"])

# ── In-memory task registry ───────────────────────────────────────────────────
# task_id → {status, progress, message, started_at, finished_at, result}
_tasks: dict[str, dict[str, Any]] = {}

# task_id → asyncio.Event  (set = cancellation requested)
_cancel_flags: dict[str, asyncio.Event] = {}


def _cancel_event(task_id: str) -> asyncio.Event:
    """Return (creating if needed) the cancellation Event for a task."""
    if task_id not in _cancel_flags:
        _cancel_flags[task_id] = asyncio.Event()
    return _cancel_flags[task_id]


def _new_task(label: str) -> str:
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {
        "task_id":     task_id,
        "source_name": label,        # frontend expects source_name
        "status":      "running",    # running | done | error
        "progress":    "",
        "chunks_added": 0,           # frontend expects chunks_added
        "errors":      0,
        "started_at":  time.time(),
        "finished_at": None,
    }
    return task_id


def _finish_task(task_id: str, chunks: int = 0, errors: int = 0,
                 error_msg: str = "", cancelled: bool = False):
    t = _tasks.get(task_id)
    if not t:
        return
    t["finished_at"]  = time.time()
    t["chunks_added"] = chunks
    t["errors"]       = errors
    if cancelled:
        t["status"]   = "cancelled"
        t["progress"] = f"Cancelled — {chunks} chunks indexed before stop"
    elif error_msg:
        t["status"]   = "error"
        t["progress"] = error_msg
    else:
        t["status"]   = "done"
        t["progress"] = f"Completed: {chunks} chunks indexed"


# ── Pydantic models ───────────────────────────────────────────────────────────

class IngestUrlRequest(BaseModel):
    url:         str
    source_name: str = ""


class CrawlPanosRequest(BaseModel):
    base_url:    str
    max_pages:   int = 100
    source_name: str = "panos-techdocs"


class CrawlWiresharkRequest(BaseModel):
    max_pages: int = 50


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def rag_status():
    from rag.ingest import _collection  # check cached singleton, don't force init
    from rag.faithfulness import _hhem_available  # read cached state, do NOT trigger download

    # Only query chunk count if collection has already been initialised — avoid
    # triggering the 90s sentence-transformer model download on first status poll
    if _collection is not None:
        count = _collection.count()
    else:
        count = 0
    source_count = 0  # not critical for the status badge

    hhem_ok = _hhem_available is True
    return {
        "ready":           count > 0,
        "total_chunks":    count,
        "source_count":    source_count,
        "embedding_model": "Qwen3-Embedding-0.6B",
        "hhem_available":  hhem_ok,
    }


# ── Sources ───────────────────────────────────────────────────────────────────

@router.get("/sources")
async def list_sources():
    from rag.ingest import _collection, list_sources as _ls
    # If collection was never initialised, return empty immediately (avoids model download)
    if _collection is None:
        return {"sources": []}
    loop = asyncio.get_running_loop()
    sources = await loop.run_in_executor(None, _ls)
    # Normalise key 'source' → 'name' so the frontend RAGSource interface matches
    normalised = [
        {"name": s.get("source", s.get("name", "")), "chunk_count": s["chunk_count"]}
        for s in sources
    ]
    return {"sources": normalised}


@router.delete("/sources/{source_name:path}")
async def delete_source(source_name: str):
    from rag.ingest import delete_source as _ds
    loop    = asyncio.get_running_loop()
    deleted = await loop.run_in_executor(None, _ds, source_name)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found.")
    return {"deleted": deleted, "source": source_name}


# ── Manual query (for testing) ────────────────────────────────────────────────

@router.get("/query")
async def query_kb(q: str, n: int = 5, hyde: bool = False, source: str = ""):
    from rag.retriever import retrieve_for_query
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    ctx, chunks, score = await retrieve_for_query(
        q, n_results=n,
        source_filter=source or None,
        use_hyde=hyde,
    )
    return {
        "query":      q,
        "best_score": round(score, 4),
        "in_kb":      score >= 0.30,
        "chunks": [
            {
                "source":         c.source,
                "page":           c.page,
                "context_prefix": c.context_prefix,
                "window_text":    c.window_text[:500],
                "similarity":     round(c.similarity, 4),
                "rerank_score":   round(c.rerank_score, 4),
            }
            for c in chunks
        ],
    }


# ── PDF / file upload ─────────────────────────────────────────────────────────

@router.post("/ingest/pdf")
async def ingest_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_name: str = Form(""),
):
    # Strip path separators to prevent directory traversal via filename
    raw_name    = (file.filename or "upload").replace("\\", "_").replace("/", "_")
    filename    = raw_name[:200]  # cap length
    source_name = source_name.strip() or filename.rsplit(".", 1)[0]
    content     = await file.read()
    task_id     = _new_task(f"Ingest: {filename}")
    cancel_ev   = _cancel_event(task_id)

    async def _run():
        from rag.ingest import ingest_file
        t = _tasks[task_id]
        t["progress"] = f"Converting {filename}…"

        def _progress(msg: str):
            if task_id in _tasks:
                _tasks[task_id]["progress"] = msg

        try:
            result = await ingest_file(content, source_name, filename,
                                       progress_cb=_progress, cancel_event=cancel_ev)
            _finish_task(task_id, result.chunk_count, result.skipped,
                         result.error or "", result.cancelled)
        except Exception as exc:
            _finish_task(task_id, 0, 0, str(exc))

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started", "source_name": source_name}


# ── URL ingest ────────────────────────────────────────────────────────────────

@router.post("/ingest/url")
async def ingest_url(req: IngestUrlRequest, background_tasks: BackgroundTasks):
    url         = req.url.strip()
    source_name = req.source_name.strip() or url.split("/")[-1] or "url-ingest"
    if not url:
        raise HTTPException(status_code=400, detail="'url' is required.")
    safe, reason = _is_safe_url(url)
    if not safe:
        raise HTTPException(status_code=400, detail=f"URL not allowed: {reason}")

    task_id   = _new_task(f"Ingest URL: {url[:60]}")
    cancel_ev = _cancel_event(task_id)

    async def _run():
        from rag.ingest import ingest_url as _iu
        t = _tasks[task_id]
        t["progress"] = f"Fetching {url}…"
        try:
            result = await _iu(url, source_name, cancel_event=cancel_ev)
            _finish_task(task_id, result.chunk_count, result.skipped,
                         result.error or "", result.cancelled)
        except Exception as exc:
            _finish_task(task_id, 0, 0, str(exc))

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started", "source_name": source_name}


# ── Wireshark wiki crawl ──────────────────────────────────────────────────────

@router.post("/crawl/wireshark")
async def crawl_wireshark(
    background_tasks: BackgroundTasks,
    req: Optional[CrawlWiresharkRequest] = None,   # body is fully optional
):
    if req is None:
        req = CrawlWiresharkRequest()
    task_id   = _new_task("Crawl: Wireshark wiki")
    cancel_ev = _cancel_event(task_id)

    async def _run():
        from rag.crawler import crawl_wireshark_wiki

        async def _progress(done: int, total: int, url: str):
            t = _tasks.get(task_id)
            if t:
                t["progress"] = f"[{done}/{total}] {url[:80]}"

        t = _tasks[task_id]
        t["progress"] = "Starting Wireshark wiki crawl…"
        try:
            result = await crawl_wireshark_wiki(
                max_pages=req.max_pages,
                progress_callback=_progress,
                cancel_event=cancel_ev,
            )
            _finish_task(task_id, result.total_chunks, result.errors,
                         cancelled=result.cancelled)
        except Exception as exc:
            _finish_task(task_id, 0, 0, str(exc))

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started"}


# ── PAN-OS TechDocs crawl ─────────────────────────────────────────────────────

@router.post("/crawl/panos")
async def crawl_panos(req: CrawlPanosRequest, background_tasks: BackgroundTasks):
    if not req.base_url.strip():
        raise HTTPException(status_code=400, detail="'base_url' is required.")
    task_id   = _new_task(f"Crawl: PAN-OS — {req.base_url[:60]}")
    cancel_ev = _cancel_event(task_id)

    async def _run():
        from rag.crawler import crawl_panos_techdocs

        async def _progress(done: int, total: int, url: str):
            t = _tasks.get(task_id)
            if t:
                t["progress"] = f"[{done}/{total}] {url[:80]}"

        t = _tasks[task_id]
        t["progress"] = f"Starting PAN-OS crawl from {req.base_url}…"
        try:
            result = await crawl_panos_techdocs(
                base_url          = req.base_url,
                max_pages         = req.max_pages,
                source_name       = req.source_name,
                progress_callback = _progress,
                cancel_event      = cancel_ev,
            )
            _finish_task(task_id, result.total_chunks, result.errors,
                         cancelled=result.cancelled)
        except Exception as exc:
            _finish_task(task_id, 0, 0, str(exc))

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started"}


# ── tshark manual seeding ────────────────────────────────────────────────────

@router.post("/seed-tshark")
async def seed_tshark_manual(background_tasks: BackgroundTasks):
    """
    Seed the knowledge base with tshark documentation.

    Ingests the bundled tshark-filters.md reference (offline-safe), then
    attempts to crawl live Wireshark docs for deeper coverage.
    Also ingests skills/*.md files for agent self-awareness.

    Returns immediately; seeding runs as a background task.
    """
    from rag.seed_tshark import seed_background
    task_id = _new_task("tshark-docs-seed")

    async def _run():
        try:
            from rag.seed_tshark import seed_if_needed
            seeded = await seed_if_needed()
            _finish_task(task_id, chunks=1 if seeded else 0)
        except Exception as exc:
            _finish_task(task_id, error_msg=str(exc))

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started",
            "message": "tshark documentation seeding started in background."}


# ── Task list ─────────────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks():
    # Return most recent 20 tasks, newest first
    tasks = sorted(_tasks.values(), key=lambda t: t["started_at"], reverse=True)
    return {"tasks": tasks[:20]}


# ── Cancel task ───────────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    t = _tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    if t["status"] != "running":
        raise HTTPException(status_code=409,
                            detail=f"Task '{task_id}' is not running (status: {t['status']}).")
    # Signal the ingest coroutine to stop after the current batch
    _cancel_event(task_id).set()
    t["progress"] = "Cancellation requested…"
    return {"task_id": task_id, "status": "cancelling"}
