/**
 * Netscope WhatsApp Bridge — powered by @whiskeysockets/baileys
 *
 * Exposes a local HTTP API for the Python backend to:
 *   GET  /status   → { state: "qr"|"open"|"closed", qr_b64: "..." }
 *   GET  /qr       → { qr_b64: "..." }
 *   POST /send     → { to: "+E164orJID", text: "..." }
 *   GET  /messages → { messages: [{from, text, timestamp}] }  (drains queue)
 *
 * Usage: node index.js [--port 3500]
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");
const express = require("express");
const QRCode = require("qrcode");
const path = require("path");
const pino = require("pino");

// ── CLI args ───────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const portIdx = args.indexOf("--port");
const PORT = portIdx !== -1 ? parseInt(args[portIdx + 1], 10) : 3500;

// ── State ──────────────────────────────────────────────────────────────────
let state = "disconnected"; // "qr_pending" | "open" | "closed" | "disconnected"
let qrB64 = null;
const inboundQueue = [];    // Drained by GET /messages
let sock = null;

// Auth credentials stored next to this script
const AUTH_DIR = path.join(__dirname, "auth_state");

// ── Express app ────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get("/status", (_req, res) => {
  res.json({ state, qr_b64: qrB64 });
});

app.get("/qr", (_req, res) => {
  res.json({ qr_b64: qrB64 });
});

app.post("/send", async (req, res) => {
  const { to, text } = req.body;
  if (!to || !text) {
    return res.status(400).json({ error: "Missing 'to' or 'text'" });
  }
  if (!sock || state !== "open") {
    return res.status(503).json({ error: "WhatsApp not connected" });
  }
  try {
    // Normalise: if it looks like a phone number, convert to JID
    const jid = to.includes("@") ? to : `${to.replace(/\D/g, "")}@s.whatsapp.net`;
    await sock.sendMessage(jid, { text });
    res.json({ status: "sent" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get("/messages", (_req, res) => {
  // Drain the inbound queue and return all pending messages
  const msgs = inboundQueue.splice(0);
  res.json({ messages: msgs });
});

// ── Baileys connection ─────────────────────────────────────────────────────
const logger = pino({ level: "warn" }); // Show warnings from Baileys

async function connect() {
  const { state: authState, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    logger,
    auth: authState,
    printQRInTerminal: false,
    browser: ["Netscope", "Chrome", "1.0"],
    // Skip history sync so message events flush immediately
    shouldSyncHistoryMessage: () => false,
    fireInitQueries: true,
    markOnlineOnConnect: true,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      state = "qr_pending";
      try {
        qrB64 = await QRCode.toDataURL(qr);
      } catch (_) {
        qrB64 = null;
      }
      console.log("[bridge] QR code ready — scan with WhatsApp");
    }

    if (connection === "open") {
      state = "open";
      qrB64 = null;
      console.log("[bridge] WhatsApp connected!");
      // Force flush buffered events after connection opens
      setTimeout(() => {
        if (sock.ev.flush) {
          console.log("[bridge] Forcing ev.flush()");
          sock.ev.flush();
        }
      }, 3000);
    }

    if (connection === "close") {
      const shouldReconnect =
        lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;

      console.log("[bridge] Connection closed. Reconnect:", shouldReconnect);
      state = shouldReconnect ? "disconnected" : "closed";

      if (shouldReconnect) {
        // Exponential backoff: wait 3s then retry
        setTimeout(connect, 3000);
      }
    }
  });

  // Debug: log all event names to see what Baileys is emitting
  const origEmit = sock.ev.emit.bind(sock.ev);
  sock.ev.emit = (event, ...args) => {
    console.log(`[bridge] EVENT: ${event}`);
    return origEmit(event, ...args);
  };

  sock.ev.on("messages.upsert", (upsert) => {
    const { messages, type } = upsert;
    console.log(`[bridge] messages.upsert: type=${type}, count=${messages?.length}`);
    if (type !== "notify") return;
    for (const msg of messages) {
      console.log(`[bridge]   msg: fromMe=${msg.key.fromMe}, remoteJid=${msg.key.remoteJid}, hasMessage=${!!msg.message}`);
      if (msg.key.fromMe) continue;       // Ignore our own messages
      if (!msg.message) continue;

      const from = msg.key.remoteJid;
      // Try all known text message fields
      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        msg.message.ephemeralMessage?.message?.extendedTextMessage?.text ||
        msg.message.ephemeralMessage?.message?.conversation ||
        msg.message.viewOnceMessage?.message?.extendedTextMessage?.text ||
        msg.message.viewOnceMessage?.message?.conversation ||
        "";

      console.log(`[bridge]   from=${from}, text="${text.substring(0, 80)}"`);
      if (text.trim()) {
        inboundQueue.push({
          from,
          text,
          timestamp: msg.messageTimestamp,
        });
        console.log(`[bridge]   → queued (queue size: ${inboundQueue.length})`);
      }
    }
  });
}

// ── Start ──────────────────────────────────────────────────────────────────
connect().catch((err) => {
  console.error("[bridge] Fatal connect error:", err);
  process.exit(1);
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[bridge] HTTP API listening on http://127.0.0.1:${PORT}`);
});

// Graceful shutdown
process.on("SIGTERM", () => { sock?.end(); process.exit(0); });
process.on("SIGINT",  () => { sock?.end(); process.exit(0); });
