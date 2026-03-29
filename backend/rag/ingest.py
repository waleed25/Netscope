"""
RAG ingestion pipeline.

Flow for each document:
  1. markitdown converts PDF / HTML / URL → Markdown text
  2. chunker splits into sentence-window ChunkRecords
  3. (optional) contextual enrichment: Ollama generates a 1-sentence
     context prefix per chunk, cached by content hash
  4. Enriched embed_text is embedded with all-MiniLM-L6-v2
  5. Vectors stored in ChromaDB (persistent); window_text in metadata
  6. BM25 index rebuilt / updated from ChromaDB corpus

Public API:
  ingest_file(path_or_bytes, source_name, filename) -> IngestResult
  ingest_url(url, source_name)                      -> IngestResult
  list_sources()                                    -> list[dict]
  delete_source(source_name)                        -> int  (chunks deleted)
  get_collection()                                  -> chromadb.Collection
  get_bm25()                                        -> BM25Okapi | None
  total_chunk_count()                               -> int
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

# ── lazy imports (heavy) ─────────────────────────────────────────────────────
# Imported at module level but singletons created on first use to keep
# startup fast and allow the server to boot without GPU/model files.

_chroma_client = None
_collection    = None
_embedder      = None
_bm25          = None          # BM25Okapi | None
_bm25_corpus: list[str] = []  # parallel list to ChromaDB doc order
_bm25_ids:    list[str] = []  # ChromaDB doc IDs matching _bm25_corpus

# Lock serialises the BM25 rebuild + save so concurrent ingests don't race.
_bm25_lock: asyncio.Lock | None = None

def _get_bm25_lock() -> asyncio.Lock:
    global _bm25_lock
    if _bm25_lock is None:
        _bm25_lock = asyncio.Lock()
    return _bm25_lock

# Number of chunks encoded per embedder.encode() call.
EMBED_BATCH_SIZE = 256

# Enrichment cache: content_hash -> context_prefix string
_enrich_cache: dict[str, str] = {}

COLLECTION_NAME = "rag_docs"


# ── Config (read at import time so circular imports avoided) ─────────────────

def _data_dir() -> Path:
    from config import settings
    d = Path(settings.rag_data_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d

def _chroma_path() -> str:
    return str(_data_dir() / "chroma_db")

def _bm25_path() -> Path:
    return _data_dir() / "bm25_corpus.json"

def _enrich_cache_path() -> Path:
    return _data_dir() / "enrich_cache.json"


# ── Singletons ────────────────────────────────────────────────────────────────

def get_collection():
    """Return (or lazily create) the ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    import chromadb
    _chroma_client = chromadb.PersistentClient(path=_chroma_path())
    _collection = _chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"

# Instruction prepended to each passage at ingest time.
# Qwen3-Embedding is instruction-aware: prefixing the passage with the task
# description significantly improves retrieval quality.
INGEST_INSTRUCTION = "Represent this document passage for retrieval: "


def get_embedder():
    """Return (or lazily load) the SentenceTransformer embedder on GPU."""
    global _embedder
    if _embedder is not None:
        return _embedder
    import torch
    from sentence_transformers import SentenceTransformer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    _embedder = SentenceTransformer(MODEL_NAME, device=device)
    return _embedder


def get_bm25():
    """Return the in-memory BM25 index, rebuilt from disk/ChromaDB if needed."""
    global _bm25, _bm25_corpus, _bm25_ids
    if _bm25 is not None:
        return _bm25
    _load_bm25_from_disk()
    return _bm25


def _load_bm25_from_disk():
    """Load BM25 corpus JSON from disk; rebuild from ChromaDB if missing."""
    global _bm25, _bm25_corpus, _bm25_ids
    p = _bm25_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _bm25_corpus = data["corpus"]
            _bm25_ids    = data["ids"]
            _rebuild_bm25_index()
            return
        except Exception:
            pass
    # Fallback: rebuild from ChromaDB
    _rebuild_bm25_from_chroma()


def _rebuild_bm25_index():
    global _bm25, _bm25_corpus
    if not _bm25_corpus:
        _bm25 = None
        return
    from rank_bm25 import BM25Okapi
    tokenized = [doc.lower().split() for doc in _bm25_corpus]
    _bm25 = BM25Okapi(tokenized)


def _rebuild_bm25_from_chroma():
    """Reconstruct BM25 corpus by reading all documents from ChromaDB."""
    global _bm25_corpus, _bm25_ids
    col = get_collection()
    count = col.count()
    if count == 0:
        _bm25_corpus = []
        _bm25_ids    = []
        _bm25        = None
        return
    # Fetch in batches of 1000
    all_docs: list[str] = []
    all_ids:  list[str] = []
    offset = 0
    batch  = 500
    while offset < count:
        res = col.get(limit=batch, offset=offset, include=["documents"])
        all_docs.extend(res["documents"] or [])
        all_ids.extend(res["ids"] or [])
        offset += batch
    _bm25_corpus = all_docs
    _bm25_ids    = all_ids
    _rebuild_bm25_index()
    _save_bm25_to_disk()


def _save_bm25_to_disk():
    try:
        _bm25_path().write_text(
            json.dumps({"corpus": _bm25_corpus, "ids": _bm25_ids}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_enrich_cache():
    global _enrich_cache
    p = _enrich_cache_path()
    if p.exists():
        try:
            _enrich_cache = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _enrich_cache = {}


def _save_enrich_cache():
    try:
        _enrich_cache_path().write_text(
            json.dumps(_enrich_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# Load enrichment cache at import time (small file, fast)
_load_enrich_cache()


# ── IngestResult ──────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    source_name:  str
    chunk_count:  int
    skipped:      int   # chunks skipped (duplicate / too short)
    duration_s:   float
    error:        str   = ""
    cancelled:    bool  = False


# ── Contextual enrichment ─────────────────────────────────────────────────────

async def _enrich_chunk(window_text: str, source_name: str) -> str:
    """
    Generate a 1-sentence context prefix for a chunk via the local LLM.
    Returns cached result if the same content was previously enriched.
    """
    from config import settings
    if not settings.rag_enrichment_enabled:
        return ""

    content_hash = hashlib.sha1(
        (source_name + window_text[:300]).encode()
    ).hexdigest()

    if content_hash in _enrich_cache:
        return _enrich_cache[content_hash]

    prompt = (
        f"Document source: {source_name}\n\n"
        f"Chunk text:\n{window_text[:600]}\n\n"
        "In ONE sentence, describe what section or topic this chunk belongs to "
        "within the document. Be specific (e.g. mention the command name, "
        "protocol, or subsystem). Reply with only that one sentence."
    )
    try:
        from agent.llm_client import chat_completion
        prefix = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=80,
        )
        prefix = prefix.strip().splitlines()[0].strip()
    except Exception:
        prefix = ""

    if prefix:
        _enrich_cache[content_hash] = prefix
        # Persist every 50 new entries
        if len(_enrich_cache) % 50 == 0:
            _save_enrich_cache()

    return prefix


# ── Core ingest function ──────────────────────────────────────────────────────

async def _ingest_markdown(
    text: str,
    source_name: str,
    page_hint: int = 0,
    progress_cb=None,       # Optional[Callable[[str], None]] — called with progress text
    cancel_event=None,      # Optional[asyncio.Event] — set to request early stop
) -> IngestResult:
    """
    Chunk *text*, enrich, embed, and store into ChromaDB + BM25.
    All CPU-bound / blocking calls are offloaded to a thread executor so
    the uvicorn event loop stays responsive during ingest.
    progress_cb(msg: str) is called at key stages so callers can update task state.
    """
    from rag.chunker import chunk_text

    def _report(msg: str):
        if progress_cb:
            progress_cb(msg)

    start = time.monotonic()
    loop  = asyncio.get_running_loop()

    _report(f"Loading models…")
    # Blocking: load models + ChromaDB (runs in thread so event loop is free)
    col      = await loop.run_in_executor(None, get_collection)
    embedder = await loop.run_in_executor(None, get_embedder)

    _report("Chunking text…")
    # Blocking: chunk_text (CPU-bound string ops)
    chunks = await loop.run_in_executor(None, chunk_text, text)
    if not chunks:
        return IngestResult(source_name, 0, 0, time.monotonic() - start)

    _report(f"Enriching and embedding {len(chunks)} chunks…")

    stored  = 0
    skipped = 0

    total_chunks = len(chunks)
    # Process in batches of EMBED_BATCH_SIZE
    for batch_start in range(0, total_chunks, EMBED_BATCH_SIZE):
        # Check for cancellation before starting each batch
        if cancel_event is not None and cancel_event.is_set():
            _report(f"Cancelled — {stored} chunks indexed before stop.")
            async with _get_bm25_lock():
                await loop.run_in_executor(None, _rebuild_bm25_index)
                await loop.run_in_executor(None, _save_bm25_to_disk)
            _save_enrich_cache()
            return IngestResult(
                source_name=source_name,
                chunk_count=stored,
                skipped=skipped,
                duration_s=time.monotonic() - start,
                cancelled=True,
            )

        batch = chunks[batch_start: batch_start + EMBED_BATCH_SIZE]
        _report(f"Embedding chunks {batch_start+1}–{min(batch_start+EMBED_BATCH_SIZE, total_chunks)} / {total_chunks}…")

        # Filter trivially short chunks first
        valid: list[tuple[int, Any]] = []
        for i, chunk in enumerate(batch):
            if len(chunk.embed_text.strip()) < 20:
                skipped += 1
            else:
                valid.append((batch_start + i, chunk))

        if not valid:
            continue

        # --- 1. Parallel enrichment -----------------------------------------
        # All LLM calls in this batch are fired concurrently via asyncio.gather.
        # Cache hits resolve instantly; only uncached chunks hit the LLM.
        prefixes: list[str] = await asyncio.gather(
            *[_enrich_chunk(chunk.window_text, source_name) for _, chunk in valid]
        )

        # --- 2. Build batch tensors ------------------------------------------
        ids        : list[str]  = []
        embed_texts: list[str]  = []
        metadatas  : list[dict] = []

        for (global_idx, chunk), prefix in zip(valid, prefixes):
            enriched = (f"{prefix}\n{chunk.embed_text}" if prefix
                        else chunk.embed_text)
            doc_id = f"{source_name}::{page_hint}::{global_idx}"
            ids.append(doc_id)
            embed_texts.append(enriched)
            metadatas.append({
                "source":         source_name,
                "page":           page_hint,
                "chunk_idx":      global_idx,
                "window_text":    chunk.window_text,
                "context_prefix": prefix,
                "ingested_at":    int(time.time()),
            })

        # --- 3. Embed (GPU inference in thread) ------------------------------
        # Qwen3-Embedding is instruction-aware: prepend the passage instruction
        # to each text before encoding for best retrieval quality.
        instructed = [INGEST_INSTRUCTION + t for t in embed_texts]
        vectors = await loop.run_in_executor(
            None,
            lambda et=instructed: embedder.encode(et, normalize_embeddings=True).tolist()
        )

        # --- 4. Upsert into ChromaDB (I/O + HNSW update in thread) ----------
        def _upsert():
            col.upsert(
                ids=ids,
                documents=embed_texts,
                embeddings=vectors,
                metadatas=metadatas,
            )
        await loop.run_in_executor(None, _upsert)

        # --- 5. Append to in-memory BM25 corpus (fast, stays on event loop) --
        global _bm25_corpus, _bm25_ids
        existing = set(_bm25_ids)
        for doc_id, embed_text in zip(ids, embed_texts):
            if doc_id not in existing:
                _bm25_corpus.append(embed_text)
                _bm25_ids.append(doc_id)
                existing.add(doc_id)

        stored += len(ids)

        # Yield control briefly so other coroutines can run
        await asyncio.sleep(0)

    # --- 6. BM25 rebuild once at the end (not after every batch) -------------
    # Lock ensures concurrent ingests don't rebuild simultaneously.
    async with _get_bm25_lock():
        await loop.run_in_executor(None, _rebuild_bm25_index)
        await loop.run_in_executor(None, _save_bm25_to_disk)
    _save_enrich_cache()

    return IngestResult(
        source_name=source_name,
        chunk_count=stored,
        skipped=skipped,
        duration_s=time.monotonic() - start,
    )


# ── Public ingest functions ───────────────────────────────────────────────────

async def ingest_file(
    path_or_bytes: str | bytes,
    source_name: str,
    filename: str = "",
    progress_cb=None,
    cancel_event=None,  # Optional[asyncio.Event]
) -> IngestResult:
    """
    Convert a file (path string or raw bytes) to Markdown via markitdown,
    then ingest into the RAG store.
    The markitdown conversion is run in a thread executor to avoid blocking
    the event loop (PDF parsing is CPU/I/O-bound).
    progress_cb(msg: str) is forwarded to _ingest_markdown for live progress.
    """
    import tempfile
    from markitdown import MarkItDown

    loop = asyncio.get_running_loop()

    if progress_cb:
        progress_cb(f"Converting {filename or 'file'} to Markdown…")

    def _convert() -> str:
        md_converter = MarkItDown(enable_plugins=False)
        if isinstance(path_or_bytes, bytes):
            suffix = Path(filename).suffix if filename else ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(path_or_bytes)
                tmp_path = tmp.name
            try:
                result = md_converter.convert(tmp_path)
            finally:
                os.unlink(tmp_path)
        else:
            result = md_converter.convert(str(path_or_bytes))
        return result.text_content or ""

    try:
        text = await loop.run_in_executor(None, _convert)
    except Exception as exc:
        return IngestResult(source_name, 0, 0, 0.0, error=str(exc))

    if not text.strip():
        return IngestResult(source_name, 0, 0, 0.0, error="markitdown produced empty output")

    return await _ingest_markdown(text, source_name,
                                   progress_cb=progress_cb, cancel_event=cancel_event)


async def ingest_url(url: str, source_name: str, cancel_event=None) -> IngestResult:
    """
    Fetch a URL, convert to Markdown via markitdown, and ingest.
    The HTTP fetch + HTML parse is offloaded to a thread so the event loop
    stays responsive (mirrors the same pattern used in ingest_file).
    """
    from markitdown import MarkItDown

    loop = asyncio.get_running_loop()

    def _convert() -> str:
        md_converter = MarkItDown(enable_plugins=False)
        result = md_converter.convert(url)
        return result.text_content or ""

    try:
        text = await loop.run_in_executor(None, _convert)
    except Exception as exc:
        return IngestResult(source_name, 0, 0, 0.0, error=str(exc))

    if not text.strip():
        return IngestResult(source_name, 0, 0, 0.0, error="Empty content from URL")

    return await _ingest_markdown(text, source_name, cancel_event=cancel_event)


# ── Source management ─────────────────────────────────────────────────────────

def list_sources() -> list[dict]:
    """Return a list of {source, chunk_count, last_updated} dicts."""
    col = get_collection()
    if col.count() == 0:
        return []

    # Fetch all metadata to aggregate by source
    res = col.get(include=["metadatas"])
    source_info: dict[str, dict] = {}
    for meta in (res.get("metadatas") or []):
        src = meta.get("source", "unknown")
        ts  = meta.get("ingested_at", 0)
        if src not in source_info:
            source_info[src] = {"source": src, "chunk_count": 0, "last_updated": 0}
        source_info[src]["chunk_count"] += 1
        if ts > source_info[src]["last_updated"]:
            source_info[src]["last_updated"] = ts

    return sorted(source_info.values(), key=lambda x: x["source"])


def delete_source(source_name: str) -> int:
    """Delete all chunks for *source_name* from ChromaDB and BM25. Returns count deleted."""
    global _bm25_corpus, _bm25_ids

    col = get_collection()
    # Find all IDs for this source
    res = col.get(where={"source": source_name}, include=[])
    ids_to_delete = res.get("ids") or []
    if not ids_to_delete:
        return 0

    col.delete(ids=ids_to_delete)

    # Remove from BM25 corpus
    id_set = set(ids_to_delete)
    new_corpus = []
    new_ids    = []
    for doc, doc_id in zip(_bm25_corpus, _bm25_ids):
        if doc_id not in id_set:
            new_corpus.append(doc)
            new_ids.append(doc_id)
    _bm25_corpus = new_corpus
    _bm25_ids    = new_ids
    _rebuild_bm25_index()
    _save_bm25_to_disk()

    return len(ids_to_delete)


def total_chunk_count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
