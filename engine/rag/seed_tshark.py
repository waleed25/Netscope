"""
Seed the RAG knowledge base with tshark documentation.

Strategy (runs at startup, idempotent):
  1. Always try to ingest the bundled tshark-filters.md first (offline-safe).
  2. Then attempt to crawl live Wireshark docs URLs for deeper coverage.
     Each URL is tried independently; network failures are logged but do not
     abort the seeding process.
  3. Ingest all skills/*.md files so the agent knows its own capabilities.

All operations are idempotent — sources already in ChromaDB are skipped.
"""

from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
_BACKEND_ROOT = _HERE.parent
_FILTER_REF = _BACKEND_ROOT / "data" / "tshark-filters.md"
_SKILLS_DIR = _BACKEND_ROOT.parent / "skills"

# ── Live crawl URLs (attempted after bundled file) ────────────────────────────

TSHARK_DOCS_URLS: list[tuple[str, str]] = [
    # (url, source_name)
    ("https://www.wireshark.org/docs/man-pages/tshark.html",       "tshark-man-page"),
    ("https://wiki.wireshark.org/DisplayFilters",                   "wireshark-display-filters"),
    ("https://wiki.wireshark.org/Modbus",                           "wireshark-modbus"),
    ("https://wiki.wireshark.org/DNP3",                             "wireshark-dnp3"),
    ("https://wiki.wireshark.org/SampleCaptures",                   "wireshark-sample-captures"),
    ("https://www.wireshark.org/docs/wsug_html_chunked/ChWorkBuildDisplayFilterSection.html",
     "wireshark-filter-reference"),
    ("https://wiki.wireshark.org/OPC-UA",                           "wireshark-opcua"),
    ("https://wiki.wireshark.org/Modbus_TCP",                       "wireshark-modbus-tcp"),
]


# ── Source-presence check ─────────────────────────────────────────────────────

def _source_exists(source_name: str) -> bool:
    """Return True if any chunk with this source_name is already in ChromaDB."""
    try:
        from rag.ingest import get_collection
        col = get_collection()
        results = col.get(where={"source": source_name}, limit=1)
        return bool(results and results.get("ids"))
    except Exception:
        return False


# ── Ingest helpers ────────────────────────────────────────────────────────────

async def _ingest_file_safe(path: Path, source_name: str) -> int:
    """Ingest a local file. Returns chunk count added (0 on skip/error)."""
    if _source_exists(source_name):
        log.debug("RAG seed: skip %s (already present)", source_name)
        return 0
    if not path.exists():
        log.warning("RAG seed: file not found: %s", path)
        return 0
    try:
        from rag.ingest import ingest_file
        result = await ingest_file(str(path), source_name=source_name)
        added = getattr(result, "chunks_added", 0)
        log.info("RAG seed: ingested %s → %d chunks", source_name, added)
        return added
    except Exception as exc:
        log.warning("RAG seed: failed to ingest %s: %s", source_name, exc)
        return 0


async def _ingest_url_safe(url: str, source_name: str) -> int:
    """Attempt to ingest a URL. Silently skips on network/crawl errors."""
    if _source_exists(source_name):
        log.debug("RAG seed: skip %s (already present)", source_name)
        return 0
    try:
        from rag.ingest import ingest_url
        result = await ingest_url(url, source_name=source_name)
        added = getattr(result, "chunks_added", 0)
        log.info("RAG seed: crawled %s → %d chunks", source_name, added)
        return added
    except Exception as exc:
        log.warning("RAG seed: failed to crawl %s: %s", url, exc)
        return 0


# ── Main entry point ──────────────────────────────────────────────────────────

async def seed_if_needed() -> bool:
    """
    Seed the knowledge base with tshark docs and skill files.

    Returns True if any new content was ingested.
    """
    total_added = 0

    # 1. Bundled tshark filter reference (always first — offline-safe)
    total_added += await _ingest_file_safe(_FILTER_REF, "tshark-filters.md")

    # 2. Live Wireshark docs (best-effort, per-URL error isolation)
    for url, name in TSHARK_DOCS_URLS:
        total_added += await _ingest_url_safe(url, name)
        # Yield control between crawls to avoid starving the event loop
        await asyncio.sleep(0.1)

    # 3. OpenClaw SKILL.md files
    if _SKILLS_DIR.exists():
        for skill_file in sorted(_SKILLS_DIR.glob("*.md")):
            source_name = f"skills/{skill_file.name}"
            total_added += await _ingest_file_safe(skill_file, source_name)
    else:
        log.debug("RAG seed: skills/ directory not found at %s", _SKILLS_DIR)

    if total_added:
        log.info("RAG seed complete: %d new chunks added.", total_added)
    else:
        log.debug("RAG seed: nothing new to ingest.")

    return total_added > 0


async def seed_background() -> None:
    """
    Background wrapper for seed_if_needed() — catches all exceptions so
    a seeding failure never crashes the server startup.
    """
    try:
        await seed_if_needed()
    except Exception as exc:
        log.warning("RAG seed background task failed: %s", exc)
