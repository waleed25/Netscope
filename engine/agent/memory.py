"""
Persistent conversation memory — OpenClaw MEMORY.md equivalent.

Stores network observations (facts), user preferences, and session summaries
in a local JSON file. Loaded at startup, persisted on every write.
Provides context to the agent across sessions.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from threading import Lock


_DEFAULT_FILE = "agent_memory.json"
_MAX_FACTS = 50
_MAX_SUMMARIES = 10


class MemoryStore:
    def __init__(self, data_dir: str = "data", filename: str = _DEFAULT_FILE) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / filename
        self._lock = Lock()
        self._data: dict = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"facts": [], "preferences": {}, "session_summaries": []}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[memory] Failed to save: {e}")

    # ── Facts (network observations) ──────────────────────────────────────────

    def add_fact(self, text: str) -> None:
        """Add a network observation fact. Deduplicates by exact match."""
        with self._lock:
            facts = self._data.setdefault("facts", [])
            # Deduplicate
            if any(f.get("text") == text for f in facts):
                return
            facts.append({"text": text, "added": time.time()})
            # Cap at max
            if len(facts) > _MAX_FACTS:
                self._data["facts"] = facts[-_MAX_FACTS:]
            self._save()

    def get_facts(self) -> list[str]:
        with self._lock:
            return [f["text"] for f in self._data.get("facts", [])]

    def remove_fact(self, text: str) -> bool:
        with self._lock:
            facts = self._data.get("facts", [])
            before = len(facts)
            self._data["facts"] = [f for f in facts if f.get("text") != text]
            if len(self._data["facts"]) < before:
                self._save()
                return True
            return False

    # ── Session summaries ────────────────────────────────────────────────────

    def add_session_summary(self, summary: str) -> None:
        with self._lock:
            summaries = self._data.setdefault("session_summaries", [])
            summaries.append({"text": summary, "timestamp": time.time()})
            if len(summaries) > _MAX_SUMMARIES:
                self._data["session_summaries"] = summaries[-_MAX_SUMMARIES:]
            self._save()

    def get_last_summary(self) -> str | None:
        with self._lock:
            summaries = self._data.get("session_summaries", [])
            return summaries[-1]["text"] if summaries else None

    # ── Preferences ──────────────────────────────────────────────────────────

    def set_preference(self, key: str, value: str) -> None:
        with self._lock:
            self._data.setdefault("preferences", {})[key] = value
            self._save()

    def get_preferences(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data.get("preferences", {}))

    # ── Context builder for system prompt ────────────────────────────────────

    def build_context(self, max_chars: int = 600) -> str:
        """
        Build a memory context string for inclusion in the system prompt.
        Returns empty string if no memory is stored.
        """
        parts = []

        facts = self.get_facts()
        if facts:
            parts.append("Known network facts:")
            for f in facts[-10:]:  # last 10 facts
                parts.append(f"- {f}")

        summary = self.get_last_summary()
        if summary:
            parts.append(f"\nLast session: {summary}")

        if not parts:
            return ""

        ctx = "\n".join(parts)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars] + "\n...(memory truncated)"
        return f"\n[AGENT MEMORY — persistent context]\n{ctx}\n"

    # ── Raw access for API ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        with self._lock:
            return dict(self._data)


# ── Singleton ────────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        from config import settings
        _store = MemoryStore(data_dir=settings.rag_data_dir)
    return _store
