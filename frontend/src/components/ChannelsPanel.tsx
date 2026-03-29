import { useEffect, useRef, useState, useCallback } from "react";
import {
  Radio, Wifi, WifiOff, CheckCircle2, AlertTriangle,
  Loader2, Send, Trash2, QrCode, ChevronDown, ChevronRight,
  MessageCircle, User, Bot, Clock, Shield, ShieldOff, Globe,
} from "lucide-react";
import {
  fetchChannels,
  configureTelegram,
  configureWhatsApp,
  stopChannel,
  fetchChannelMessages,
  fetchWhatsAppQR,
  fetchPairings,
  approvePairing,
  rejectPairing,
  sendTestMessage,
  type ChannelStatus,
  type ChannelMessage,
  type PairingEntry,
} from "../lib/channelsApi";

// ── Status badge ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ChannelStatus | null }) {
  if (!status) {
    return (
      <span className="flex items-center gap-1 text-[10px] text-muted">
        <WifiOff className="w-3 h-3" /> Disconnected
      </span>
    );
  }
  const { state, error } = status;
  if (state === "connected") {
    return (
      <span className="flex items-center gap-1 text-[10px] text-success">
        <CheckCircle2 className="w-3 h-3" /> Connected
      </span>
    );
  }
  if (state === "qr_pending") {
    return (
      <span className="flex items-center gap-1 text-[10px] text-warning">
        <QrCode className="w-3 h-3 animate-pulse" /> Scan QR Code
      </span>
    );
  }
  if (state === "error") {
    return (
      <span className="flex items-center gap-1 text-[10px] text-danger" title={error ?? ""}>
        <AlertTriangle className="w-3 h-3" /> Error
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[10px] text-muted">
      <WifiOff className="w-3 h-3" /> Disconnected
    </span>
  );
}

// ── Policy icon ───────────────────────────────────────────────────────────

function PolicyIcon({ policy }: { policy: string }) {
  if (policy === "open")      return <Globe className="w-3 h-3 text-warning" />;
  if (policy === "allowlist") return <Shield className="w-3 h-3 text-accent" />;
  return <ShieldOff className="w-3 h-3 text-muted" />;
}

// ── Recent messages list ──────────────────────────────────────────────────

function RecentMessages({
  messages,
  platform,
}: {
  messages: ChannelMessage[];
  platform: "telegram" | "whatsapp";
}) {
  const [open, setOpen] = useState(false);
  if (messages.length === 0) return null;

  const isTelegram = platform === "telegram";

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] text-muted hover:text-foreground transition-colors w-full text-left"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Recent messages ({messages.length})
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 max-h-48 overflow-y-auto pr-1">
          {messages.slice(-15).reverse().map((m, i) => (
            <div key={i} className="flex gap-2 text-[10px]">
              <div
                className={`shrink-0 w-4 h-4 rounded-full flex items-center justify-center mt-0.5 ${
                  m.is_bot
                    ? "bg-purple-emphasis/20"
                    : isTelegram ? "bg-brand-telegram/20" : "bg-brand-whatsapp/20"
                }`}
              >
                {m.is_bot
                  ? <Bot className="w-2.5 h-2.5 text-purple" />
                  : <User className={`w-2.5 h-2.5 ${isTelegram ? "text-brand-telegram" : "text-brand-whatsapp"}`} />
                }
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-1.5">
                  <span className="font-medium text-foreground truncate max-w-[100px]">
                    {m.is_bot ? "Netscope" : (m.username || m.user_id)}
                  </span>
                  <span className="text-muted-dim shrink-0">
                    {new Date(m.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
                <p className="text-muted truncate">{m.text}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Pending pairings card ─────────────────────────────────────────────────

function PairingsCard({
  pairings,
  onApprove,
  onReject,
}: {
  pairings: PairingEntry[];
  onApprove: (channel: string, code: string) => void;
  onReject: (channel: string, code: string) => void;
}) {
  if (pairings.length === 0) return null;

  return (
    <div className="mb-4 rounded-lg border border-warning bg-warning-subtle p-3">
      <div className="flex items-center gap-2 text-warning text-xs font-semibold mb-2">
        <Clock className="w-3.5 h-3.5" />
        Pending Access Requests ({pairings.length})
      </div>
      <div className="space-y-2">
        {pairings.map((p) => {
          const expiresIn = Math.max(0, Math.round((p.expires_at - Date.now() / 1000) / 60));
          return (
            <div key={p.code} className="flex items-center gap-2 bg-surface rounded px-2 py-1.5">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <Radio className="w-3 h-3 text-muted" />
                  <span className="text-[10px] text-muted capitalize">{p.channel}</span>
                </div>
                <div className="text-xs text-foreground font-medium truncate">{p.username || p.user_id}</div>
                <div className="flex items-center gap-2 text-[10px] text-muted">
                  <span>Code: <code className="text-accent">{p.code}</code></span>
                  <span>· {expiresIn}m left</span>
                </div>
              </div>
              <div className="flex gap-1 shrink-0">
                <button
                  onClick={() => onApprove(p.channel, p.code)}
                  className="px-2 py-0.5 text-[10px] bg-success-emphasis hover:bg-success-emphasis-hover text-white rounded transition-colors"
                >
                  Approve
                </button>
                <button
                  onClick={() => onReject(p.channel, p.code)}
                  className="px-2 py-0.5 text-[10px] bg-danger-emphasis/20 hover:bg-danger-emphasis/25 text-danger border border-danger-emphasis rounded transition-colors"
                >
                  Reject
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Telegram card ─────────────────────────────────────────────────────────

function TelegramCard({
  status,
  messages,
  onRefreshMessages,
}: {
  status: ChannelStatus | null;
  messages: ChannelMessage[];
  onRefreshMessages: () => void;
}) {
  const [token, setToken] = useState("");
  const [policy, setPolicy] = useState<"pairing" | "allowlist" | "open">("pairing");
  const [allowedIds, setAllowedIds] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConnected = status?.state === "connected";

  const handleStart = async () => {
    if (!token.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await configureTelegram({
        token: token.trim(),
        dm_policy: policy,
        allowed_user_ids: allowedIds
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setToken(""); // Clear token from UI after submission
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to start Telegram bot");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopChannel("telegram");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full flex items-center justify-center bg-brand-telegram/13">
            <MessageCircle className="w-4 h-4 text-brand-telegram" />
          </div>
          <div>
            <div className="text-sm font-semibold text-foreground">Telegram</div>
            <StatusBadge status={status} />
          </div>
        </div>
        {isConnected && (
          <button
            onClick={handleStop}
            disabled={loading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] text-danger border border-danger-emphasis rounded hover:bg-danger-emphasis/20 transition-colors disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <WifiOff className="w-2.5 h-2.5" />}
            Disconnect
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-3 px-2 py-1.5 rounded bg-danger-subtle border border-danger text-danger text-[11px]">
          {error}
        </div>
      )}

      {/* Config form (shown when not connected) */}
      {!isConnected && (
        <div className="space-y-2">
          <div>
            <label className="block text-[10px] text-muted mb-1">Bot Token</label>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="1234567890:ABC..."
              className="w-full bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-brand-telegram placeholder-muted-dim"
            />
            <p className="text-[10px] text-muted-dim mt-1">
              Get a token from <span className="text-accent">@BotFather</span> on Telegram.
            </p>
          </div>

          <div>
            <label className="block text-[10px] text-muted mb-1">Access Policy</label>
            <div className="flex gap-1.5">
              {(["pairing", "allowlist", "open"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPolicy(p)}
                  className={`flex items-center gap-1 px-2 py-1 text-[10px] rounded border transition-colors ${
                    policy === p
                      ? "bg-accent-emphasis border-accent text-foreground"
                      : "bg-transparent border-border text-muted hover:border-accent"
                  }`}
                >
                  <PolicyIcon policy={p} />
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-muted-dim mt-1">
              {policy === "pairing" && "New users get a 6-digit code that you approve here."}
              {policy === "allowlist" && "Only listed user IDs can chat with the bot."}
              {policy === "open" && "Anyone who finds the bot can use it."}
            </p>
          </div>

          {policy === "allowlist" && (
            <div>
              <label className="block text-[10px] text-muted mb-1">
                Allowed Telegram User IDs (one per line)
              </label>
              <textarea
                value={allowedIds}
                onChange={(e) => setAllowedIds(e.target.value)}
                placeholder={"123456789\n987654321"}
                rows={3}
                className="w-full bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent resize-none placeholder-muted-dim font-mono"
              />
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={!token.trim() || loading}
            className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs font-medium bg-success-emphasis hover:bg-success-emphasis-hover disabled:opacity-50 text-white rounded transition-colors"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wifi className="w-3.5 h-3.5" />}
            {loading ? "Connecting…" : "Start Bot"}
          </button>
        </div>
      )}

      {/* Connected state info */}
      {isConnected && (
        <div className="text-[10px] text-muted space-y-1 mt-1">
          <div className="flex items-center gap-1">
            <PolicyIcon policy={status?.state ?? "pairing"} />
            <span>{messages.length} messages in log</span>
          </div>
          <p className="text-muted-dim">
            Commands available: /help /status /capture [N] /new /history
          </p>
        </div>
      )}

      <RecentMessages messages={messages} platform="telegram" />
    </div>
  );
}

// ── WhatsApp card ─────────────────────────────────────────────────────────

function WhatsAppCard({
  status,
  messages,
  qrB64,
  onRefreshMessages,
}: {
  status: ChannelStatus | null;
  messages: ChannelMessage[];
  qrB64: string | null;
  onRefreshMessages: () => void;
}) {
  const [policy, setPolicy] = useState<"pairing" | "allowlist" | "open">("pairing");
  const [allowedNums, setAllowedNums] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConnected = status?.state === "connected";
  const isQrPending = status?.state === "qr_pending";
  const bridgeError = status?.error;

  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      await configureWhatsApp({
        dm_policy: policy,
        allowed_user_ids: allowedNums
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        bridge_port: 3500,
      });
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to start WhatsApp bridge");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopChannel("whatsapp");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full flex items-center justify-center bg-brand-whatsapp/13">
            <MessageCircle className="w-4 h-4 text-brand-whatsapp" />
          </div>
          <div>
            <div className="text-sm font-semibold text-foreground">WhatsApp</div>
            <StatusBadge status={status} />
          </div>
        </div>
        {(isConnected || isQrPending) && (
          <button
            onClick={handleStop}
            disabled={loading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] text-danger border border-danger-emphasis rounded hover:bg-danger-emphasis/20 transition-colors disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <WifiOff className="w-2.5 h-2.5" />}
            Disconnect
          </button>
        )}
      </div>

      {/* Error */}
      {(error || bridgeError) && (
        <div className="mb-3 px-2 py-1.5 rounded bg-danger-subtle border border-danger text-danger text-[11px]">
          {error || bridgeError}
        </div>
      )}

      {/* QR Code */}
      {isQrPending && qrB64 && (
        <div className="mb-3 flex flex-col items-center gap-2 p-3 bg-white rounded-lg">
          <img src={qrB64} alt="WhatsApp QR Code" className="w-48 h-48" />
          <p className="text-[11px] text-background font-medium">
            Scan with WhatsApp on your phone
          </p>
          <p className="text-[10px] text-muted-dim">
            WhatsApp → ⋮ → Linked Devices → Link a Device
          </p>
        </div>
      )}

      {isQrPending && !qrB64 && (
        <div className="mb-3 flex items-center justify-center gap-2 p-4 bg-background rounded border border-border">
          <Loader2 className="w-4 h-4 animate-spin text-brand-whatsapp" />
          <span className="text-[11px] text-muted">Loading QR code…</span>
        </div>
      )}

      {/* Config form */}
      {!isConnected && !isQrPending && (
        <div className="space-y-2">
          <div>
            <label className="block text-[10px] text-muted mb-1">Access Policy</label>
            <div className="flex gap-1.5">
              {(["pairing", "allowlist", "open"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPolicy(p)}
                  className={`flex items-center gap-1 px-2 py-1 text-[10px] rounded border transition-colors ${
                    policy === p
                      ? "bg-accent-emphasis border-accent text-foreground"
                      : "bg-transparent border-border text-muted hover:border-accent"
                  }`}
                >
                  <PolicyIcon policy={p} />
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {policy === "allowlist" && (
            <div>
              <label className="block text-[10px] text-muted mb-1">
                Allowed Numbers (E.164 format, one per line)
              </label>
              <textarea
                value={allowedNums}
                onChange={(e) => setAllowedNums(e.target.value)}
                placeholder={"+1234567890\n+9876543210"}
                rows={3}
                className="w-full bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent resize-none placeholder-muted-dim font-mono"
              />
            </div>
          )}

          <div className="px-2 py-1.5 rounded bg-background border border-border text-[10px] text-muted">
            <p className="font-medium text-foreground mb-1">Requirements</p>
            <ul className="space-y-0.5 list-disc list-inside">
              <li>Node.js must be installed</li>
              <li>Run <code className="text-accent">npm install</code> in <code className="text-accent">backend/channels/baileys_bridge/</code></li>
              <li>Scan the QR code with your phone</li>
            </ul>
          </div>

          <button
            onClick={handleConnect}
            disabled={loading}
            className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs font-medium bg-success-emphasis hover:bg-success-emphasis-hover disabled:opacity-50 text-white rounded transition-colors"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <QrCode className="w-3.5 h-3.5" />}
            {loading ? "Starting…" : "Connect via QR Code"}
          </button>
        </div>
      )}

      {/* Connected state */}
      {isConnected && (
        <div className="text-[10px] text-muted">
          <div className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-success" />
            <span>{messages.length} messages in log</span>
          </div>
        </div>
      )}

      <RecentMessages messages={messages} platform="whatsapp" />
    </div>
  );
}

// ── Main ChannelsPanel ────────────────────────────────────────────────────

export function ChannelsPanel() {
  const [statuses, setStatuses] = useState<ChannelStatus[]>([]);
  const [tgMessages, setTgMessages] = useState<ChannelMessage[]>([]);
  const [waMessages, setWaMessages] = useState<ChannelMessage[]>([]);
  const [qrB64, setQrB64] = useState<string | null>(null);
  const [pairings, setPairings] = useState<PairingEntry[]>([]);

  const tgStatus = statuses.find((s) => s.name === "telegram") ?? null;
  const waStatus = statuses.find((s) => s.name === "whatsapp") ?? null;

  const refresh = useCallback(async () => {
    try {
      const [ch, p] = await Promise.all([fetchChannels(), fetchPairings()]);
      setStatuses(ch);
      setPairings(p);

      const tg = ch.find((s) => s.name === "telegram");
      const wa = ch.find((s) => s.name === "whatsapp");

      if (tg?.connected) {
        fetchChannelMessages("telegram", 20).then(setTgMessages).catch(() => {});
      }
      if (wa?.connected) {
        fetchChannelMessages("whatsapp", 20).then(setWaMessages).catch(() => {});
      }
      if (wa?.state === "qr_pending") {
        fetchWhatsAppQR().then(setQrB64).catch(() => {});
      } else {
        setQrB64(null);
      }
    } catch {
      // Network not ready yet — silently ignore
    }
  }, []);

  // Poll every 5s; every 2s when WhatsApp is in QR mode
  const waQrPending = waStatus?.state === "qr_pending";
  const intervalMs = waQrPending ? 2000 : 5000;

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  const handleApprove = async (channel: string, code: string) => {
    try {
      await approvePairing(channel, code);
      refresh();
    } catch (e: any) {
      alert(e?.response?.data?.detail || "Failed to approve.");
    }
  };

  const handleReject = async (channel: string, code: string) => {
    try {
      await rejectPairing(channel, code);
      refresh();
    } catch {}
  };

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-surface shrink-0">
        <Radio className="w-4 h-4 text-accent" />
        <span className="text-xs font-semibold text-accent">Channels</span>
        <span className="text-muted text-xs">— Connect your phone via Telegram or WhatsApp</span>
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Pending pairing requests */}
        <PairingsCard
          pairings={pairings}
          onApprove={handleApprove}
          onReject={handleReject}
        />

        {/* Channel cards side-by-side on wide screens */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <TelegramCard
            status={tgStatus}
            messages={tgMessages}
            onRefreshMessages={refresh}
          />
          <WhatsAppCard
            status={waStatus}
            messages={waMessages}
            qrB64={qrB64}
            onRefreshMessages={refresh}
          />
        </div>

        {/* How it works */}
        <div className="rounded-lg border border-border bg-surface p-4 text-[11px] text-muted">
          <div className="font-semibold text-foreground mb-2 flex items-center gap-1.5">
            <Radio className="w-3 h-3 text-accent" />
            How Channels Work
          </div>
          <ul className="space-y-1 list-disc list-inside">
            <li>Messages sent from your phone are routed to the Netscope AI agent</li>
            <li>The agent has full access to packet data, tools (ping, netstat, tracert), and the knowledge base</li>
            <li>Use <code className="text-accent">/capture 30</code> to start a 30s capture — you'll get a message when done</li>
            <li>Send a <code className="text-accent">.pcap</code> file to the bot for instant analysis</li>
            <li>Reply <code className="text-accent">more</code> if a response was truncated</li>
            <li>No internet exposure required — Telegram uses polling, WhatsApp connects outward like WhatsApp Web</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
