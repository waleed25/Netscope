"""
Tool audit log — append-only JSON Lines file of all tool executions.
OpenClaw-inspired audit trail for transparency and debugging.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from threading import Lock


class ToolAuditLog:
    def __init__(self, path: str = "data/tool_audit.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, result, args: str) -> None:
        """Append an execution record. `result` is a ToolResult."""
        entry = {
            "ts": time.time(),
            "tool": result.tool,
            "args": args[:200],
            "status": result.status,
            "safety": result.safety,
            "duration_ms": round(result.duration_ms, 1),
            "output_len": len(result.output),
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass  # non-fatal

    def recent(self, n: int = 50) -> list[dict]:
        """Return last N entries."""
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            entries = []
            for line in lines[-n:]:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return entries
        except OSError:
            return []


# ── Singleton ────────────────────────────────────────────────────────────────

_log: ToolAuditLog | None = None


def get_audit_log() -> ToolAuditLog:
    global _log
    if _log is None:
        from config import settings
        _log = ToolAuditLog(path=os.path.join(settings.rag_data_dir, "tool_audit.jsonl"))
    return _log
