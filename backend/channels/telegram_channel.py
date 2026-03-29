"""
Telegram channel — python-telegram-bot v21 (fully async).

Integration with FastAPI's event loop:
  Uses app.initialize() / app.start() / app.updater.start_polling()
  directly — never run_polling() which creates its own loop.

Features:
  - Partial streaming via editMessageText (single-message updates)
  - DM pairing code flow
  - /start /help /status /capture /new /history /approve commands
  - PCAP file upload handling
  - OpenClaw-style message queue
"""
from __future__ import annotations
import asyncio
import re
import traceback

from channels.base_channel import BaseChannel, ChannelStatus
from channels.message_queue import QueueMode

# python-telegram-bot imports — only resolved when a TelegramChannel is instantiated
try:
    from telegram import Update, Bot
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters as tg_filters,
    )
    from telegram.error import TelegramError
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False


_TOKEN_RE = re.compile(r"^\d{8,12}:[A-Za-z0-9_-]{35,}$")

# How many chars to accumulate before editing the in-progress Telegram message
_EDIT_CHUNK = 30


def validate_token(token: str) -> bool:
    return bool(_TOKEN_RE.match(token.strip()))


class TelegramChannel(BaseChannel):
    name = "telegram"

    def __init__(
        self,
        token: str,
        dm_policy: str = "pairing",
        allowed_user_ids: list[str] | None = None,
        rate_seconds: float = 3.0,
        on_pairing_request=None,  # callback(user_id, username, code) → None
        on_pairing_approved=None, # callback(user_id) → None
    ) -> None:
        super().__init__(
            dm_policy=dm_policy,
            allowed_user_ids=allowed_user_ids,
            rate_seconds=rate_seconds,
            queue_mode=QueueMode.COLLECT,
        )
        if not _TG_AVAILABLE:
            raise RuntimeError(
                "python-telegram-bot is not installed. "
                "Run: pip install 'python-telegram-bot>=21.0.0'"
            )
        self._token = token.strip()
        self._app: Application | None = None
        self._connected = False
        self._error: str | None = None

        # Callbacks so the manager can react to pairing events
        self._on_pairing_request = on_pairing_request
        self._on_pairing_approved = on_pairing_approved

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        try:
            self._app = (
                Application.builder()
                .token(self._token)
                .build()
            )
            self._register_handlers()
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._connected = True
            self._error = None
            print("[telegram] Bot started (polling).")
        except Exception as exc:
            self._connected = False
            self._error = str(exc)
            print(f"[telegram] Start failed: {exc}")
            raise

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        except Exception as exc:
            print(f"[telegram] Stop error (non-fatal): {exc}")
        finally:
            self._connected = False
            self._app = None
            print("[telegram] Bot stopped.")

    def status(self) -> ChannelStatus:
        return ChannelStatus(
            name="telegram",
            connected=self._connected,
            state="connected" if self._connected else ("error" if self._error else "disconnected"),
            error=self._error,
            message_count=len(self._message_log),
        )

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message to a Telegram chat_id. Chunks > 4096 chars."""
        if not self._app or not self._connected:
            return
        try:
            chunks = _chunk(text, 4096)
            for chunk in chunks:
                await self._app.bot.send_message(chat_id=int(user_id), text=chunk)
        except TelegramError as exc:
            print(f"[telegram] send_message error: {exc}")

    async def _send_fn(self, user_key: str, text: str) -> None:
        """Adapter: extract chat_id from user_key and send."""
        chat_id = user_key.split(":")[-1]
        await self.send_message(chat_id, text)

    # ── Handler registration ──────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        app = self._app
        app.add_handler(CommandHandler("start",   self._cmd_start))
        app.add_handler(CommandHandler("help",    self._cmd_help))
        app.add_handler(CommandHandler("status",  self._cmd_status))
        app.add_handler(CommandHandler("capture", self._cmd_capture))
        app.add_handler(CommandHandler("new",     self._cmd_new))
        app.add_handler(CommandHandler("history", self._cmd_history))
        app.add_handler(CommandHandler("approve", self._cmd_approve))
        # PCAP uploads
        app.add_handler(MessageHandler(
            tg_filters.Document.FileExtension("pcap")
            | tg_filters.Document.FileExtension("pcapng"),
            self._handle_pcap,
        ))
        # Plain text messages
        app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, self._handle_message))

    # ── Access gate (shared by all handlers) ──────────────────────────────────

    async def _gate(self, update: Update) -> tuple[str, str] | None:
        """
        Check DM policy. Returns (user_key, username) if allowed, else None.
        For pairing mode, unknown users receive a code and the handler returns None.
        """
        user = update.effective_user
        if user is None:
            return None
        uid = str(user.id)
        username = user.username or user.first_name or uid
        user_key = f"telegram:{uid}"

        if self._dm_policy == "open":
            return user_key, username

        if self._dm_policy == "allowlist" or self._dm_policy == "pairing":
            if uid in self._allowed_ids:
                return user_key, username
            if self._dm_policy == "allowlist":
                await update.message.reply_text(
                    "🔒 You are not on the allowed list for this bot."
                )
                return None
            # Pairing mode — generate code
            if self._on_pairing_request:
                code = self._on_pairing_request(uid, username)
                await update.message.reply_text(
                    f"🔒 *Access requires approval.*\n\n"
                    f"Your code: `{code}`\n\n"
                    f"Ask the admin to approve it in the Netscope Channels panel. "
                    f"_(Code expires in 1 hour)_",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("🔒 Access requires admin approval.")
            return None

        return user_key, username

    # ── Commands ──────────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "👋 *Welcome to Netscope!*\n\n"
            "I'm your local network analysis assistant. You can:\n"
            "• Ask questions about your captured traffic\n"
            "• Run network commands (`ping 8.8.8.8`, `netstat -ano`)\n"
            "• `/capture 30` — capture 30 seconds of traffic\n"
            "• Send a `.pcap` file for analysis\n\n"
            "Type /help for all commands.",
            parse_mode="Markdown",
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "*Netscope Commands*\n\n"
            "/status — packet count, LLM status\n"
            "/capture [N] — capture N seconds of traffic (default 10)\n"
            "/new — clear your conversation history\n"
            "/history — show last 5 messages\n"
            "📎 Send a `.pcap` file — analyze it\n\n"
            "_Or just type anything to chat with the AI agent!_",
            parse_mode="Markdown",
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        gate = await self._gate(update)
        if gate is None:
            return
        user_key, username = gate
        try:
            from api.routes import _packets
            from agent.tools.system import run_llm_status
            pkt_count = len(_packets)
            llm_info = await run_llm_status("")
            await update.message.reply_text(
                f"📊 *Netscope Status*\n\n"
                f"📦 Packets in memory: `{pkt_count}`\n"
                f"🤖 LLM: `{llm_info[:200]}`",
                parse_mode="Markdown",
            )
        except Exception as exc:
            await update.message.reply_text(f"⚠️ Status error: {exc}")

    async def _cmd_capture(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        gate = await self._gate(update)
        if gate is None:
            return
        user_key, username = gate

        seconds = 10
        if ctx.args:
            try:
                seconds = max(1, min(120, int(ctx.args[0])))
            except ValueError:
                pass

        await update.message.reply_text(
            f"🔴 Capture started for *{seconds}s*. I'll message you when done.",
            parse_mode="Markdown",
        )

        async def do_capture():
            try:
                from agent.tools.network import run_capture
                summary, new_packets = await run_capture(str(seconds))
                count = len(new_packets)
                await self.send_message(
                    user_key.split(":")[-1],
                    f"✅ *Capture complete* — {count} packets captured.\n\n{summary[:800]}",
                )
            except Exception as exc:
                await self.send_message(
                    user_key.split(":")[-1],
                    f"❌ Capture failed: {exc}",
                )

        asyncio.create_task(do_capture())

    async def _cmd_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        gate = await self._gate(update)
        if gate is None:
            return
        user_key, _ = gate
        self.clear_history(user_key)
        await update.message.reply_text("🗑️ Conversation history cleared.")

    async def _cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        gate = await self._gate(update)
        if gate is None:
            return
        user_key, _ = gate
        hist = list(self._get_history(user_key))
        if not hist:
            await update.message.reply_text("📭 No conversation history yet.")
            return
        lines = []
        for entry in hist[-10:]:  # last 5 turns (10 messages)
            role = "You" if entry["role"] == "user" else "Bot"
            content = entry["content"][:100].replace("\n", " ")
            lines.append(f"*{role}:* {content}…")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_approve(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin command: /approve <code>"""
        gate = await self._gate(update)
        if gate is None:
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /approve <6-digit code>")
            return
        code = ctx.args[0]
        if self._on_pairing_approved:
            result = self._on_pairing_approved(code)
            if result:
                entry = result
                await update.message.reply_text(
                    f"✅ Approved `{entry.get('username', '?')}` (ID: `{entry.get('user_id', '?')}`).",
                    parse_mode="Markdown",
                )
                # Notify the newly approved user
                try:
                    await self.send_message(
                        entry["user_id"],
                        "✅ *Access granted!* You can now chat with Netscope.",
                    )
                except Exception:
                    pass
            else:
                await update.message.reply_text("❌ Code not found or expired.")
        else:
            await update.message.reply_text("❌ Pairing not configured.")

    # ── Message handlers ──────────────────────────────────────────────────────

    async def _handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        gate = await self._gate(update)
        if gate is None:
            return
        user_key, username = gate
        text = (update.message.text or "").strip()
        if not text:
            return

        # Show typing indicator while we work
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Route through the queue/agent pipeline
        await self.route_to_agent(user_key, text, self._send_fn, username=username)

    async def _handle_pcap(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        gate = await self._gate(update)
        if gate is None:
            return
        user_key, username = gate

        doc = update.message.document
        if doc.file_size and doc.file_size > 200 * 1024 * 1024:
            await update.message.reply_text("❌ File too large (max 200 MB).")
            return

        try:
            tg_file = await ctx.bot.get_file(doc.file_id)
            file_bytes = await tg_file.download_as_bytearray()
            await self.handle_pcap_upload(
                user_key,
                bytes(file_bytes),
                doc.file_name or "upload.pcap",
                self._send_fn,
                username=username,
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ Upload error: {exc}")


# ── Utilities ─────────────────────────────────────────────────────────────────

def _chunk(text: str, size: int) -> list[str]:
    """Split text into chunks of at most `size` characters."""
    return [text[i:i + size] for i in range(0, max(len(text), 1), size)]
