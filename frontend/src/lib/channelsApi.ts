/**
 * Typed API helpers for the Channels feature.
 * Reuses the shared axios instance from api.ts so that URL resolution
 * (Vite proxy in dev, absolute URL in Electron) is consistent.
 */
import { api } from "./api";

// ── Types ─────────────────────────────────────────────────────────────────

export interface ChannelStatus {
  name: string;
  connected: boolean;
  state: "connected" | "disconnected" | "qr_pending" | "error";
  error: string | null;
  message_count: number;
}

export interface ChannelMessage {
  user_id: string;
  username: string;
  text: string;
  is_bot: boolean;
  timestamp: number;
}

export interface PairingEntry {
  channel: string;
  user_id: string;
  username: string;
  code: string;
  expires_at: number;
}

export interface TelegramConfig {
  token: string;
  dm_policy: "pairing" | "allowlist" | "open";
  allowed_user_ids: string[];
}

export interface WhatsAppConfig {
  dm_policy: "pairing" | "allowlist" | "open";
  allowed_user_ids: string[];
  bridge_port: number;
}

// ── Endpoints ─────────────────────────────────────────────────────────────

export async function fetchChannels(): Promise<ChannelStatus[]> {
  const res = await api.get<ChannelStatus[]>("/channels");
  return res.data;
}

export async function configureTelegram(cfg: TelegramConfig): Promise<ChannelStatus> {
  const res = await api.post<ChannelStatus>("/channels/telegram/configure", cfg);
  return res.data;
}

export async function stopChannel(name: string): Promise<void> {
  await api.delete(`/channels/${name}`);
}

export async function configureWhatsApp(cfg: WhatsAppConfig): Promise<ChannelStatus> {
  const res = await api.post<ChannelStatus>("/channels/whatsapp/configure", cfg);
  return res.data;
}

export async function fetchChannelMessages(
  name: string,
  limit = 50,
): Promise<ChannelMessage[]> {
  const res = await api.get<{ channel: string; messages: ChannelMessage[] }>(
    `/channels/${name}/messages`,
    { params: { limit } },
  );
  return res.data.messages;
}

export async function sendTestMessage(
  name: string,
  user_id: string,
  text: string,
): Promise<void> {
  await api.post(`/channels/${name}/send`, { user_id, text });
}

export async function fetchWhatsAppQR(): Promise<string | null> {
  const res = await api.get<{ qr_b64: string | null }>("/channels/whatsapp/qr");
  return res.data.qr_b64;
}

export async function fetchPairings(): Promise<PairingEntry[]> {
  const res = await api.get<{ pairings: PairingEntry[] }>("/channels/pairings");
  return res.data.pairings;
}

export async function approvePairing(channel: string, code: string): Promise<void> {
  await api.post("/channels/pairings/approve", { channel, code });
}

export async function rejectPairing(channel: string, code: string): Promise<void> {
  await api.post("/channels/pairings/reject", { channel, code });
}
