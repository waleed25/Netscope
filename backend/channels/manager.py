"""
ChannelsManager — singleton that manages all active channels.

Responsible for:
  - Loading persisted config at startup and (re-)starting enabled channels
  - Providing configure/stop/status API surface consumed by router.py
  - Bridging pairing callbacks between TelegramChannel and ConfigStore
"""
from __future__ import annotations
import asyncio

from channels.config_store import ConfigStore, ChannelConfig
from channels.base_channel import ChannelStatus, ChannelMessage


class ChannelsManager:
    def __init__(self) -> None:
        self._store = ConfigStore()
        self._channels: dict[str, object] = {}   # name → channel instance

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Load persisted configs and start any enabled channels."""
        for cfg in self._store.all():
            if cfg.enabled:
                try:
                    await self._start_channel(cfg)
                except Exception as exc:
                    print(f"[channels] Auto-start {cfg.name} failed: {exc}")

    async def shutdown(self) -> None:
        """Stop all running channels."""
        for ch in list(self._channels.values()):
            try:
                await ch.stop()
            except Exception as exc:
                print(f"[channels] Shutdown error: {exc}")
        self._channels.clear()

    # ── Telegram ──────────────────────────────────────────────────────────────

    async def configure_telegram(
        self,
        token: str,
        dm_policy: str = "pairing",
        allowed_user_ids: list[str] | None = None,
    ) -> ChannelStatus:
        from channels.telegram_channel import TelegramChannel, validate_token

        if not validate_token(token):
            raise ValueError("Invalid Telegram bot token format.")

        # Stop existing if running
        await self.stop_channel("telegram")

        cfg = ChannelConfig(
            name="telegram",
            enabled=True,
            token=token,
            dm_policy=dm_policy,
            allowed_user_ids=allowed_user_ids or [],
        )
        self._store.put(cfg)

        ch = TelegramChannel(
            token=token,
            dm_policy=dm_policy,
            allowed_user_ids=allowed_user_ids,
            on_pairing_request=self._telegram_pairing_request,
            on_pairing_approved=self._telegram_pairing_approved,
        )
        await ch.start()
        self._channels["telegram"] = ch
        return ch.status()

    def _telegram_pairing_request(self, user_id: str, username: str) -> str:
        """Called by TelegramChannel when a new unknown user messages the bot."""
        code = self._store.generate_pairing_code("telegram", user_id, username)
        print(f"[telegram] Pairing request from {username} ({user_id}): code {code}")
        return code

    def _telegram_pairing_approved(self, code: str) -> dict | None:
        """Called by /approve command handler."""
        entry = self._store.approve_pairing("telegram", code)
        if entry and "telegram" in self._channels:
            ch = self._channels["telegram"]
            uid = entry["user_id"]
            ch._allowed_ids.add(uid)
        return entry

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    async def configure_whatsapp(
        self,
        dm_policy: str = "pairing",
        allowed_user_ids: list[str] | None = None,
        bridge_port: int = 3500,
    ) -> ChannelStatus:
        from channels.whatsapp_channel import WhatsAppChannel

        await self.stop_channel("whatsapp")

        cfg = ChannelConfig(
            name="whatsapp",
            enabled=True,
            token="",
            dm_policy=dm_policy,
            allowed_user_ids=allowed_user_ids or [],
            extra={"bridge_port": bridge_port},
        )
        self._store.put(cfg)

        ch = WhatsAppChannel(
            dm_policy=dm_policy,
            allowed_user_ids=allowed_user_ids,
            bridge_port=bridge_port,
            on_pairing_request=self._whatsapp_pairing_request,
        )
        await ch.start()
        self._channels["whatsapp"] = ch
        return ch.status()

    def _whatsapp_pairing_request(self, user_id: str, username: str) -> str:
        """Called by WhatsAppChannel when an unknown user messages the bot."""
        code = self._store.generate_pairing_code("whatsapp", user_id, username)
        print(f"[whatsapp] Pairing request from {username} ({user_id}): code {code}")
        return code

    # ── Generic ops ───────────────────────────────────────────────────────────

    async def stop_channel(self, name: str) -> None:
        ch = self._channels.pop(name, None)
        if ch:
            await ch.stop()
        cfg = self._store.get(name)
        if cfg:
            cfg.enabled = False
            self._store.put(cfg)

    def get_status(self) -> list[ChannelStatus]:
        statuses = []
        for name in ("telegram", "whatsapp"):
            if name in self._channels:
                statuses.append(self._channels[name].status())
            else:
                cfg = self._store.get(name)
                statuses.append(ChannelStatus(
                    name=name,
                    connected=False,
                    state="disconnected",
                    error=None,
                    message_count=0,
                ))
        return statuses

    def get_messages(self, name: str, limit: int = 50) -> list[ChannelMessage]:
        ch = self._channels.get(name)
        if ch is None:
            return []
        msgs = ch.get_messages()
        return msgs[-limit:]

    async def send_test_message(self, name: str, user_id: str, text: str) -> None:
        ch = self._channels.get(name)
        if ch is None:
            raise ValueError(f"Channel '{name}' is not running.")
        await ch.send_message(user_id, text)

    def get_whatsapp_qr(self) -> str | None:
        ch = self._channels.get("whatsapp")
        if ch is None:
            return None
        return ch.get_qr()

    def get_pending_pairings(self) -> list[dict]:
        return self._store.get_all_pairings()

    def approve_pairing(self, channel_name: str, code: str) -> dict | None:
        entry = self._store.approve_pairing(channel_name, code)
        if entry and channel_name in self._channels:
            ch = self._channels[channel_name]
            ch._allowed_ids.add(entry["user_id"])
        return entry

    def reject_pairing(self, channel_name: str, code: str) -> bool:
        return self._store.reject_pairing(channel_name, code)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _start_channel(self, cfg: ChannelConfig) -> None:
        if cfg.name == "telegram":
            await self.configure_telegram(
                token=cfg.token,
                dm_policy=cfg.dm_policy,
                allowed_user_ids=cfg.allowed_user_ids,
            )
        elif cfg.name == "whatsapp":
            port = cfg.extra.get("bridge_port", 3500)
            await self.configure_whatsapp(
                dm_policy=cfg.dm_policy,
                allowed_user_ids=cfg.allowed_user_ids,
                bridge_port=port,
            )


channels_manager = ChannelsManager()
