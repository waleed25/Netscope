"""
Sentence-window chunker for RAG ingestion.

Strategy:
  - Split text into individual sentences (the embedding unit — small + focused)
  - Build overlapping windows of WINDOW_SENTENCES around each sentence
    (the retrieval unit — wide context passed to the LLM)
  - Handle CLI-style lines (commands) as atomic units — never split mid-command

ChunkRecord fields:
  embed_text   : what gets embedded into ChromaDB (sentence + neighbours)
  window_text  : what gets passed to the LLM on retrieval (wider context)
  char_offset  : byte offset in original text (for provenance)
  sentence_idx : 0-based index of the anchor sentence
"""

from __future__ import annotations
import re
from dataclasses import dataclass


# ── Config ─────────────────────────────────────────────────────────────────────

EMBED_WINDOW   = 1   # sentences each side included in the embedding unit
CONTEXT_WINDOW = 3   # sentences each side included in the retrieved window
MAX_CHUNK_CHARS = 1000  # hard cap on window_text length


@dataclass
class ChunkRecord:
    embed_text:   str
    window_text:  str
    char_offset:  int
    sentence_idx: int


# ── Sentence splitter ─────────────────────────────────────────────────────────

# CLI command lines (start with alphabetic word + optional flags, or start with
# special chars like show/set/get) — treat whole line as one sentence.
_CLI_LINE_RE = re.compile(
    r'^[ \t]*(show|set|get|delete|clear|request|debug|test|commit|'
    r'configure|exit|quit|ping|traceroute|less|find|grep|tail|cat)\b',
    re.IGNORECASE,
)

# Standard sentence-ending punctuation, not followed by a digit (avoids
# splitting "10.0.0.1" or "v11.1").
_SENT_END_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')


def split_sentences(text: str) -> list[str]:
    """
    Split *text* into a list of sentence strings.

    Lines that look like CLI commands are kept intact.
    Empty lines / pure whitespace are dropped.
    """
    sentences: list[str] = []
    # First split on hard newlines to preserve line structure
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # CLI commands — keep whole line as one unit
        if _CLI_LINE_RE.match(line) or line.startswith(('>', '#', '$', '%')):
            sentences.append(line)
            continue

        # Markdown headings — keep as one unit
        if line.startswith('#'):
            sentences.append(line)
            continue

        # Code fences / table rows — keep as one unit
        if line.startswith(('```', '|', '    ')):
            sentences.append(line)
            continue

        # Otherwise split on sentence-ending punctuation
        parts = _SENT_END_RE.split(line)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)

    return sentences


# ── Window builder ────────────────────────────────────────────────────────────

def build_windows(
    sentences: list[str],
    embed_window: int = EMBED_WINDOW,
    context_window: int = CONTEXT_WINDOW,
) -> list[ChunkRecord]:
    """
    Build ChunkRecord list from a sentence list.

    For sentence i:
      embed_text  = sentences[i-embed_window : i+embed_window+1]   joined
      window_text = sentences[i-context_window : i+context_window+1] joined
    """
    records: list[ChunkRecord] = []

    # Pre-compute cumulative char offsets for each sentence
    offsets = []
    running = 0
    for s in sentences:
        offsets.append(running)
        running += len(s) + 1  # +1 for the separator

    for i in range(0, len(sentences), embed_window + 1):
        # Embedding unit: narrow window
        e_start = max(0, i - embed_window)
        e_end   = min(len(sentences), i + embed_window + 1)
        embed_text = " ".join(sentences[e_start:e_end]).strip()

        # Context window: wider window
        c_start = max(0, i - context_window)
        c_end   = min(len(sentences), i + context_window + 1)
        window_text = " ".join(sentences[c_start:c_end]).strip()

        # Hard cap
        if len(window_text) > MAX_CHUNK_CHARS:
            window_text = window_text[:MAX_CHUNK_CHARS] + "…"

        records.append(ChunkRecord(
            embed_text=embed_text,
            window_text=window_text,
            char_offset=offsets[i],
            sentence_idx=i,
        ))

    return records


def chunk_text(
    text: str,
    embed_window: int = EMBED_WINDOW,
    context_window: int = CONTEXT_WINDOW,
) -> list[ChunkRecord]:
    """Convenience: split text into sentences then build windows."""
    sentences = split_sentences(text)
    if not sentences:
        return []
    return build_windows(sentences, embed_window, context_window)
