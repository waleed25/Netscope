"""
JSON-backed configuration store for channel settings.
Tokens are stored locally and NEVER returned by the API (masked as "***").
"""
from __future__ import annotations
import json
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).parent / "channels_config.json"


@dataclass
class PairingEntry:
    user_id: str
    username: str
    code: str
    expires_at: float  # Unix timestamp


@dataclass
class ChannelConfig:
    name: str
    enabled: bool = False
    token: str = ""
    dm_policy: str = "pairing"          # "pairing" | "allowlist" | "open"
    allowed_user_ids: list[str] = field(default_factory=list)
    pending_pairings: dict[str, dict] = field(default_factory=dict)  # code → PairingEntry dict
    extra: dict[str, Any] = field(default_factory=dict)


class ConfigStore:
    def __init__(self, path: Path = _CONFIG_PATH) -> None:
        self._path = path
        self._configs: dict[str, ChannelConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for name, raw in data.items():
                self._configs[name] = ChannelConfig(**{
                    k: v for k, v in raw.items()
                    if k in ChannelConfig.__dataclass_fields__
                })
        except Exception as exc:
            print(f"[channels] Config load error (non-fatal): {exc}")

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {name: asdict(cfg) for name, cfg in self._configs.items()}
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[channels] Config save error: {exc}")

    def get(self, name: str) -> ChannelConfig | None:
        return self._configs.get(name)

    def put(self, cfg: ChannelConfig) -> None:
        self._configs[cfg.name] = cfg
        self._save()

    def delete(self, name: str) -> None:
        self._configs.pop(name, None)
        self._save()

    def all(self) -> list[ChannelConfig]:
        return list(self._configs.values())

    # ── Pairing code helpers ──────────────────────────────────────────────────

    def generate_pairing_code(self, channel_name: str, user_id: str, username: str) -> str:
        """Generate a 6-digit pairing code for a new user. Returns the code."""
        cfg = self._configs.get(channel_name)
        if cfg is None:
            return ""
        code = str(secrets.randbelow(900000) + 100000)
        cfg.pending_pairings[code] = {
            "user_id": user_id,
            "username": username,
            "code": code,
            "expires_at": time.time() + 3600,  # 1 hour
        }
        self._save()
        return code

    def approve_pairing(self, channel_name: str, code: str) -> dict | None:
        """Approve a pairing code. Returns the entry dict or None if not found/expired."""
        cfg = self._configs.get(channel_name)
        if cfg is None:
            return None
        entry = cfg.pending_pairings.pop(code, None)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            self._save()
            return None  # expired
        # Add to allowlist
        if entry["user_id"] not in cfg.allowed_user_ids:
            cfg.allowed_user_ids.append(entry["user_id"])
        self._save()
        return entry

    def reject_pairing(self, channel_name: str, code: str) -> bool:
        cfg = self._configs.get(channel_name)
        if cfg is None:
            return False
        removed = cfg.pending_pairings.pop(code, None)
        if removed:
            self._save()
        return removed is not None

    def prune_expired_pairings(self, channel_name: str) -> None:
        cfg = self._configs.get(channel_name)
        if cfg is None:
            return
        now = time.time()
        expired = [code for code, e in cfg.pending_pairings.items() if now > e["expires_at"]]
        for code in expired:
            cfg.pending_pairings.pop(code)
        if expired:
            self._save()

    def get_all_pairings(self) -> list[dict]:
        """Return all pending (non-expired) pairing entries across all channels."""
        now = time.time()
        result = []
        for cfg in self._configs.values():
            for entry in cfg.pending_pairings.values():
                if now <= entry["expires_at"]:
                    result.append({"channel": cfg.name, **entry})
        return result
