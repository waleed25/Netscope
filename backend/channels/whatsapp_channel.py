"""
WhatsApp channel — Baileys Node.js bridge.

The Baileys bridge (backend/channels/baileys_bridge/index.js) is a small
Express HTTP server that:
  - Connects to WhatsApp Web via QR scan (no public URL needed)
  - Exposes GET /status, GET /qr, POST /send, GET /messages
  - Polls Netscope's incoming-message endpoint when messages arrive

Python spawns the bridge as a child process and communicates via HTTP.
"""
from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from utils import proc

from channels.base_channel import BaseChannel, ChannelStatus
from channels.message_queue import QueueMode

from typing import Callable

_BRIDGE_DIR = Path(__file__).parent / "baileys_bridge"
_DEFAULT_PORT = 3500
_POLL_INTERVAL = 1.5   # seconds between polling bridge for new messages


class WhatsAppChannel(BaseChannel):
    name = "whatsapp"

    def __init__(
        self,
        dm_policy: str = "pairing",
        allowed_user_ids: list[str] | None = None,
        rate_seconds: float = 3.0,
        bridge_port: int = _DEFAULT_PORT,
        on_pairing_request: Callable[[str, str], str] | None = None,
    ) -> None:
        super().__init__(
            dm_policy=dm_policy,
            allowed_user_ids=allowed_user_ids,
            rate_seconds=rate_seconds,
            queue_mode=QueueMode.COLLECT,
        )
        self._port = bridge_port
        self._proc: subprocess.Popen | None = None
        self._state = "disconnected"   # "disconnected"|"qr_pending"|"connected"|"error"
        self._error: str | None = None
        self._qr_b64: str | None = None
        self._poll_task: asyncio.Task | None = None
        self._on_pairing_request = on_pairing_request

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._bridge_installed():
            self._state = "error"
            self._error = (
                "Baileys bridge not installed. "
                f"Run: cd {_BRIDGE_DIR} && npm install"
            )
            raise RuntimeError(self._error)

        node = self._find_node()
        if not node:
            self._state = "error"
            self._error = "Node.js not found in PATH. Please install Node.js."
            raise RuntimeError(self._error)

        bridge_script = _BRIDGE_DIR / "index.js"
        self._proc = proc.Popen(
            [node, str(bridge_script), "--port", str(self._port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(_BRIDGE_DIR),
        )
        self._state = "qr_pending"
        print(f"[whatsapp] Baileys bridge started (PID {self._proc.pid}) on port {self._port}.")

        # Forward bridge stdout to Python stdout in a background thread
        import threading
        def _drain_stdout():
            try:
                for line in self._proc.stdout:
                    print(f"[bridge] {line.decode('utf-8', errors='replace').rstrip()}")
            except Exception:
                pass
        threading.Thread(target=_drain_stdout, daemon=True).start()

        # Start polling task
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.sleep(1)
                if self._proc.poll() is None:
                    self._proc.kill()
            except Exception as exc:
                print(f"[whatsapp] Stop error (non-fatal): {exc}")
            self._proc = None

        self._state = "disconnected"
        self._qr_b64 = None
        print("[whatsapp] Bridge stopped.")

    def status(self) -> ChannelStatus:
        return ChannelStatus(
            name="whatsapp",
            connected=(self._state == "connected"),
            state=self._state,
            error=self._error,
            message_count=len(self._message_log),
        )

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message via the Baileys bridge. Chunks > 1600 chars."""
        chunks = _chunk(text, 1600)
        async with httpx.AsyncClient(timeout=10) as client:
            for chunk in chunks:
                try:
                    await client.post(
                        f"http://127.0.0.1:{self._port}/send",
                        json={"to": user_id, "text": chunk},
                    )
                except Exception as exc:
                    print(f"[whatsapp] send_message error: {exc}")

    async def _send_fn(self, user_key: str, text: str) -> None:
        jid = user_key.split(":")[-1]
        await self.send_message(jid, text)

    # ── QR code ───────────────────────────────────────────────────────────────

    def get_qr(self) -> str | None:
        return self._qr_b64

    # ── Polling loop ──────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Periodically poll the Baileys bridge for status and new messages."""
        # Wait for bridge to boot
        await asyncio.sleep(3)

        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    await self._poll_status(client)
                    if self._state == "connected":
                        await self._poll_messages(client)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                await asyncio.sleep(_POLL_INTERVAL)

    async def _poll_status(self, client: httpx.AsyncClient) -> None:
        try:
            r = await client.get(f"http://127.0.0.1:{self._port}/status")
            data = r.json()
            state = data.get("state", "disconnected")
            self._qr_b64 = data.get("qr_b64")
            old_state = self._state
            if state == "open":
                self._state = "connected"
                self._error = None
            elif state in ("qr", "qr_pending"):
                self._state = "qr_pending"
            elif state == "closed":
                self._state = "disconnected"
            else:
                self._state = state
            if old_state != self._state:
                print(f"[whatsapp] State changed: {old_state} → {self._state}")
        except Exception:
            pass  # Bridge still booting

    @staticmethod
    def _normalize_phone(value: str) -> str:
        """Strip +, spaces, dashes and @s.whatsapp.net to get raw digits."""
        import re
        return re.sub(r"\D", "", value.split("@")[0])

    def _is_allowed(self, jid: str) -> bool:
        """Check if a JID matches any entry in allowed_ids (normalised)."""
        norm_jid = self._normalize_phone(jid)
        for aid in self._allowed_ids:
            if self._normalize_phone(aid) == norm_jid:
                return True
        return False

    async def _poll_messages(self, client: httpx.AsyncClient) -> None:
        try:
            r = await client.get(f"http://127.0.0.1:{self._port}/messages")
            messages = r.json().get("messages", [])
            for msg in messages:
                jid = msg.get("from", "")
                text = msg.get("text", "").strip()
                if not jid or not text:
                    continue
                user_key = f"whatsapp:{jid}"

                # Log all incoming messages (even if rejected)
                self._log(self.name, jid, jid, text, is_bot=False)
                print(f"[whatsapp] Message from {jid}: {text[:80]}")

                # Access control
                if self._dm_policy == "allowlist":
                    if not self._is_allowed(jid):
                        await self.send_message(
                            jid,
                            "🔒 You are not on the allowed list. "
                            "Ask the admin to add your WhatsApp number.",
                        )
                        continue
                elif self._dm_policy == "pairing":
                    if not self._is_allowed(jid):
                        if self._on_pairing_request:
                            code = self._on_pairing_request(jid, jid)
                            await self.send_message(
                                jid,
                                f"🔒 Access requires approval.\n"
                                f"Your code: *{code}* (expires in 1 hour).\n"
                                f"Ask the admin to approve it in Netscope.",
                            )
                        else:
                            await self.send_message(
                                jid,
                                "🔒 You are not authorised. "
                                "Ask the admin to add your WhatsApp number.",
                            )
                        continue
                # dm_policy == "open" → allow all

                asyncio.create_task(
                    self.route_to_agent(user_key, text, self._send_fn, username=jid)
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[whatsapp] _poll_messages error: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _bridge_installed(self) -> bool:
        nm = _BRIDGE_DIR / "node_modules"
        return nm.exists()

    @staticmethod
    def _find_node() -> str | None:
        import shutil
        return shutil.which("node")


def _chunk(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, max(len(text), 1), size)]
