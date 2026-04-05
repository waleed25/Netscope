import axios from "axios";
import type { Packet, Interface, Insight, LLMStatus, TokenUsage, DeepAnalysisReport } from "../store/useStore";

/**
 * Resolve the backend base URL.
 *
 * - In a normal browser/dev environment the app is served from the same origin
 *   as the API proxy, so relative "/api" works as usual.
 * - When running inside Electron the page is loaded as file://, so we need an
 *   absolute URL.  The Electron main process injects window.__BACKEND_PORT__
 *   (via executeJavaScript after dom-ready) and the preload exposes it through
 *   window.electronBridge.getBackendPort().
 */
function resolveBaseURL(): string {
  // Running inside Electron (file:// origin)
  if (
    typeof window !== "undefined" &&
    window.location.protocol === "file:"
  ) {
    const bridge = (window as unknown as { electronBridge?: { getBackendPort: () => number } }).electronBridge;
    const port = bridge?.getBackendPort() ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  // Normal browser / dev server with Vite proxy
  return "/api";
}

export const BASE = resolveBaseURL();

export const api = axios.create({ baseURL: BASE });

// --- Interfaces ---
export async function fetchInterfaces(): Promise<Interface[]> {
  const res = await api.get("/interfaces");
  return res.data.interfaces;
}

export async function fetchLocalIPs(): Promise<string[]> {
  try {
    const res = await api.get<{ ips: string[] }>("/interfaces/local-ips");
    return res.data.ips ?? [];
  } catch {
    return [];
  }
}

// --- Capture ---
export async function startCapture(iface: string, bpfFilter: string) {
  return api.post("/capture/start", { interface: iface, bpf_filter: bpfFilter });
}

export async function stopCapture() {
  return api.post("/capture/stop");
}

export async function captureStatus() {
  return api.get("/capture/status");
}

// --- Packets ---
export async function fetchPackets(
  offset = 0,
  limit = 500,
  protocol = "",
  displayFilter = ""
): Promise<{ total: number; packets: Packet[] }> {
  const params: Record<string, string | number> = { offset, limit };
  if (protocol) params.protocol = protocol;
  if (displayFilter) params.display_filter = displayFilter;
  const res = await api.get("/packets", { params });
  return res.data;
}

// --- pcap upload ---
export async function uploadPcap(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api.post("/pcap/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

// --- Chat ---

export type ToolEvent =
  | { type: "call"; name: string; args: string }
  | { type: "result"; output: string }
  | { type: "capture_start"; seconds: number }
  | { type: "capture_done"; count: number }
  | { type: "faithfulness"; score: number }
  | { type: "rag_sources"; sources: Array<{ source: string; page: number | null }> }
  | { type: "reasoning"; token: string }
  | { type: "open_tab"; tab: string }
  | { type: "traffic_map_data"; data: TrafficMapSummary };

export interface TrafficMapSummary {
  total_hosts: number;
  total_flows: number;
  total_packets: number;
  top_hosts: Array<{
    ip: string;
    packets: number;
    bytes: number;
    protocols: string[];
    is_external: boolean;
  }>;
  top_flows: Array<{
    src: string;
    dst: string;
    packets: number;
    bytes: number;
    protocols: string[];
  }>;
  external_hosts: string[];
  protocol_distribution: Record<string, number>;
}

// ── Network Topology types ────────────────────────────────────────────────────

export type DeviceType = "firewall" | "router" | "switch" | "server" | "endpoint" | "plc" | "unknown";

export interface TopologyNode {
  id: string;
  ip: string;
  mac: string;
  label: string;
  hostname: string;
  netbios: string;
  vendor: string;
  type: DeviceType;
  platform: string;
  protocols: string[];
  packets: number;
  vlan: string | null;
  is_gateway: boolean;
  ports: string[];
  level: number;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  source_port: string;
  target_port: string;
  edge_type: "cdp" | "lldp" | "inferred";
  vlan: string | null;
}

export interface NetworkTopology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  vlans: string[];
  gateways: string[];
  has_cdp: boolean;
  has_lldp: boolean;
  has_stp: boolean;
  confidence: "high" | "medium" | "low";
  total_devices: number;
  scan_cidr?: string;
  scan_hosts_found?: number;
}

export async function fetchTopology(): Promise<NetworkTopology> {
  const res = await api.get<NetworkTopology>("/topology");
  return res.data;
}

export async function scanTopology(cidr?: string): Promise<NetworkTopology> {
  const res = await api.post<NetworkTopology>("/topology/scan", { cidr: cidr ?? "" });
  return res.data;
}

/**
 * Parse a raw stream chunk that may contain NUL-delimited sentinel blocks:
 *   \x00TOOL_CALL:<name> <args>\x00
 *   \x00TOOL_RESULT:<output>\x00
 * Returns { text, events } where text is clean LLM tokens and events are
 * structured tool call/result objects.
 */
function parseChunk(
  raw: string,
  buffer: { pending: string }
): { text: string; events: ToolEvent[] } {
  // Prepend any leftover partial sentinel from last chunk
  const input = buffer.pending + raw;
  buffer.pending = "";

  const events: ToolEvent[] = [];
  let text = "";
  let rest = input;

  while (rest.length > 0) {
    const start = rest.indexOf("\x00");
    if (start === -1) {
      // No sentinel start — all plain text, but might be a partial sentinel
      // If the tail could be the beginning of \x00..., hold it back
      text += rest;
      rest = "";
      break;
    }

    // Text before the sentinel
    text += rest.slice(0, start);
    rest = rest.slice(start); // starts with \x00

    const end = rest.indexOf("\x00", 1);
    if (end === -1) {
      // Sentinel is incomplete — buffer it for next chunk
      buffer.pending = rest;
      rest = "";
      break;
    }

    const sentinel = rest.slice(1, end); // content between the two \x00
    rest = rest.slice(end + 1);

    if (sentinel.startsWith("TOOL_CALL:")) {
      const payload = sentinel.slice("TOOL_CALL:".length).trim();
      const spaceIdx = payload.indexOf(" ");
      const name = spaceIdx === -1 ? payload : payload.slice(0, spaceIdx);
      const args = spaceIdx === -1 ? "" : payload.slice(spaceIdx + 1);
      events.push({ type: "call", name, args });
    } else if (sentinel.startsWith("TOOL_RESULT:")) {
      const output = sentinel.slice("TOOL_RESULT:".length);
      events.push({ type: "result", output });
    } else if (sentinel.startsWith("CAPTURE_START:")) {
      const seconds = parseInt(sentinel.slice("CAPTURE_START:".length), 10) || 10;
      events.push({ type: "capture_start", seconds });
    } else if (sentinel.startsWith("CAPTURE_DONE:")) {
      const count = parseInt(sentinel.slice("CAPTURE_DONE:".length), 10) || 0;
      events.push({ type: "capture_done", count });
    } else if (sentinel.startsWith("FAITHFULNESS:")) {
      const score = parseFloat(sentinel.slice("FAITHFULNESS:".length)) || 0;
      events.push({ type: "faithfulness", score });
    } else if (sentinel.startsWith("RAG_SOURCES:")) {
      try {
        const sources = JSON.parse(sentinel.slice("RAG_SOURCES:".length));
        events.push({ type: "rag_sources", sources });
      } catch {}
    } else if (sentinel.startsWith("REASONING:")) {
      const token = sentinel.slice("REASONING:".length);
      events.push({ type: "reasoning", token });
    } else if (sentinel.startsWith("OPEN_TAB:")) {
      const tab = sentinel.slice("OPEN_TAB:".length).trim();
      events.push({ type: "open_tab", tab });
    } else if (sentinel.startsWith("TRAFFIC_MAP_DATA:")) {
      try {
        const data = JSON.parse(sentinel.slice("TRAFFIC_MAP_DATA:".length));
        events.push({ type: "traffic_map_data", data });
      } catch {}
    }
  }

  return { text, events };
}

export async function sendChatMessage(
  message: string,
  onToken?: (token: string) => void,
  onToolEvent?: (event: ToolEvent) => void,
  ragEnabled = false,
  useHyde = false,
  signal?: AbortSignal,
  analysisContext?: string,
  images?: string[],
): Promise<string> {
  const body = {
    message,
    stream: !!onToken,
    rag_enabled: ragEnabled,
    use_hyde: useHyde,
    analysis_context: analysisContext ?? null,
    images: images ?? [],
  };
  if (onToken) {
    // Streaming
    const res = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) {
      const errText = await res.text().catch(() => `HTTP ${res.status}`);
      throw new Error(errText || `HTTP ${res.status}`);
    }
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let fullText = "";
    const buf = { pending: "" };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const raw = decoder.decode(value, { stream: true });
      const { text, events } = parseChunk(raw, buf);
      if (text) {
        fullText += text;
        onToken(text);
      }
      for (const ev of events) {
        onToolEvent?.(ev);
      }
    }
    return fullText;
  } else {
    const res = await api.post("/chat", body);
    return res.data.response;
  }
}

// --- RAG ---

export interface RAGSource {
  name: string;
  chunk_count: number;
}

export interface RAGStatus {
  total_chunks: number;
  ready: boolean;
  hhem_available: boolean;
}

export interface RAGTask {
  task_id: string;
  status: "running" | "done" | "error" | "cancelled";
  progress: string;
  source_name: string;
  chunks_added: number;
  error?: string;
}

export async function fetchRAGStatus(): Promise<RAGStatus> {
  const res = await api.get("/rag/status");
  return res.data;
}

export async function fetchRAGSources(): Promise<RAGSource[]> {
  const res = await api.get("/rag/sources");
  return res.data.sources;
}

export async function deleteRAGSource(name: string) {
  return api.delete(`/rag/sources/${encodeURIComponent(name)}`);
}

export async function ingestRAGUrl(url: string, source_name: string): Promise<{ task_id: string }> {
  const res = await api.post("/rag/ingest/url", { url, source_name });
  return res.data;
}

export async function ingestRAGPdf(file: File): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post("/rag/ingest/pdf", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function crawlWireshark(): Promise<{ task_id: string }> {
  const res = await api.post("/rag/crawl/wireshark");
  return res.data;
}

export async function crawlPanOS(base_url: string, max_pages: number): Promise<{ task_id: string }> {
  const res = await api.post("/rag/crawl/panos", { base_url, max_pages });
  return res.data;
}

export async function fetchRAGTasks(): Promise<RAGTask[]> {
  const res = await api.get("/rag/tasks");
  return res.data.tasks;
}

export async function cancelIngestTask(task_id: string): Promise<void> {
  await api.post(`/rag/tasks/${task_id}/cancel`);
}

export async function queryRAG(q: string, n = 5, hyde = false): Promise<{ chunks: unknown[]; formatted: string }> {
  const res = await api.get("/rag/query", { params: { q, n, hyde } });
  return res.data;
}

export async function clearChatHistory() {
  return api.delete("/chat/history");
}

// --- Insights ---
export async function fetchInsights(): Promise<Insight[]> {
  const res = await api.get("/insights");
  return res.data.insights;
}

export async function generateInsight(mode: string = "general"): Promise<string> {
  const res = await api.post("/insights/generate", { mode });
  return res.data.insight;
}

export async function generateInsightStream(
  mode: string = "general",
  onToken: (token: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${BASE}/insights/generate/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => `HTTP ${res.status}`);
    throw new Error(text || `HTTP ${res.status}`);
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let full = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    full += chunk;
    onToken(chunk);
  }
  return full;
}

export interface CaptureFileInfo {
  file: string | null;
  name: string | null;
  size_bytes: number;
}

export async function fetchCurrentCaptureFile(): Promise<CaptureFileInfo> {
  const res = await api.get("/capture/current-file");
  return res.data;
}

export interface SavedCaptureFile {
  name: string;
  size_bytes: number;
  modified: number;
  is_active: boolean;
}

export async function listCaptureFiles(): Promise<SavedCaptureFile[]> {
  const res = await api.get("/capture/files");
  return res.data.files;
}

export async function deleteCaptureFile(name: string): Promise<void> {
  await api.delete(`/capture/files/${encodeURIComponent(name)}`);
}

export async function loadCaptureFile(name: string): Promise<{ packet_count: number }> {
  const res = await api.post(`/capture/load/${encodeURIComponent(name)}`);
  return res.data;
}

export async function clearCapture(): Promise<void> {
  await api.post("/capture/clear");
}

// --- LLM ---
export async function fetchLLMStatus(): Promise<LLMStatus> {
  const res = await api.get("/llm/status");
  return res.data;
}

export async function setLLMBackend(backend: "ollama" | "lmstudio") {
  return api.post("/llm/backend", { backend });
}

export async function fetchTokenUsage(): Promise<TokenUsage> {
  const res = await api.get("/llm/tokens");
  return res.data;
}

export interface ContextUsage {
  context_length: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  requests: number;
}

export async function fetchContextUsage(): Promise<ContextUsage> {
  const res = await api.get("/llm/context");
  return res.data;
}

export async function resetTokenUsage() {
  return api.post("/llm/tokens/reset");
}

export async function fetchLLMModels(): Promise<{ models: string[]; active: string }> {
  const res = await api.get("/llm/models");
  return res.data;
}

export async function setLLMModel(model: string) {
  return api.post("/llm/model", { model });
}

export async function getThinking(): Promise<{ enabled: boolean }> {
  const res = await api.get("/llm/thinking");
  return res.data;
}

export async function setThinking(enabled: boolean): Promise<void> {
  await api.post("/llm/thinking", { enabled });
}

export async function getAutonomous(): Promise<{ enabled: boolean }> {
  const res = await api.get("/agent/autonomous");
  return res.data;
}

export async function setAutonomous(enabled: boolean): Promise<void> {
  await api.post("/agent/autonomous", { enabled });
}

export async function getShell(): Promise<{ enabled: boolean }> {
  const res = await api.get("/agent/shell");
  return res.data;
}

export async function setShell(enabled: boolean): Promise<void> {
  await api.post("/agent/shell", { enabled });
}

/**
 * Restart the backend process.
 *
 * - In Electron: uses the IPC bridge which stops the process, starts a new
 *   one, waits for /health, and returns the (potentially new) port.
 *   If the port changed the axios baseURL is updated automatically.
 * - In dev/browser: POSTs to /restart (process exits; a process manager or
 *   uvicorn --reload brings it back), then polls until /health responds.
 */
export async function restartBackend(): Promise<void> {
  type Bridge = { restartBackend?: () => Promise<{ port: number }> };
  const bridge = (window as unknown as { electronBridge?: Bridge }).electronBridge;

  if (bridge?.restartBackend) {
    // Electron path: clean IPC-managed restart
    const { port } = await bridge.restartBackend();
    // Update the axios instance's baseURL if the port changed
    const newBase = `http://127.0.0.1:${port}/api`;
    if (api.defaults.baseURL !== newBase) {
      api.defaults.baseURL = newBase;
    }
    return;
  }

  // Browser/dev-server path: ask the backend to exit, then poll
  try { await api.post("/restart"); } catch { /* ignore — backend exits mid-response */ }
  await pollBackendHealth();
}

/** Poll GET /health until the backend responds 200 or the timeout expires. */
export async function pollBackendHealth(timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await api.get("/health", { timeout: 2000 });
      return; // healthy
    } catch {
      await new Promise(r => setTimeout(r, 600));
    }
  }
  throw new Error("Backend did not come back online within 30 seconds.");
}

export interface PullProgress {
  status: string;
  total?: number;
  completed?: number;
  error?: string;
}

export async function pullModel(
  modelName: string,
  onProgress: (p: PullProgress) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${BASE}/llm/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: modelName }),
    signal,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const reader = resp.body?.getReader();
  if (!reader) throw new Error("No response body");
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() || "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;
      // Parse separately from error-check so parse errors don't swallow payload.error
      let payload: PullProgress;
      try {
        payload = JSON.parse(trimmed.slice(6));
      } catch {
        continue; // skip genuinely unparseable lines
      }
      onProgress(payload);
      if (payload.error) throw new Error(payload.error);
    }
  }
}

// --- Modbus ---

export interface ModbusRegisterValue {
  address: number;
  name: string;
  raw?: number;
  value?: number;
  unit?: string;
  description?: string;
  access?: string;
  error?: string;
  timestamp?: number;
}

export interface ModbusSession {
  session_id: string;
  label: string;
  host: string;
  port: number;
  unit_id: number;
  device_type: string;
  device_name: string;
  register_count: number;
  status: string;
  started_at: number;
  error?: string;
  // client-only
  poll_interval?: number;
  poll_count?: number;
  error_count?: number;
  last_poll_at?: number;
  last_error?: string;
  // simulator-only
  update_interval?: number;
  // transport / serial settings
  transport?: string;           // "tcp" | "rtu" | "ascii"
  serial_port?: string;
  baudrate?: number;
  bytesize?: number;
  parity?: string;              // "N" | "E" | "O"
  stopbits?: number;
  timeout?: number;
  byte_order?: string;          // "ABCD" | "BADC" | "CDAB" | "DCBA"
  zero_based_addressing?: boolean;
  block_read_max_gap?: number;
  block_read_max_size?: number;
  enabled_fcs?: number[];
  max_connections?: number;
}

export interface ScanResult {
  host: string;
  port: number;
  unit_id: number;
  regs: Record<string, number>;
  device_type_guess: string;
  scanned_at: number;
  latency_ms: number;
}

export interface DeviceTypeInfo {
  key: string;
  label: string;
  register_count: number;
}

// Device maps
export async function fetchModbusDeviceTypes(): Promise<DeviceTypeInfo[]> {
  const res = await api.get("/modbus/device-types");
  const raw = res.data.device_types;
  if (!raw || typeof raw !== "object") return [];
  // Backend returns { "sma": { count: 13, registers: [...] }, ... }
  // Convert to array of DeviceTypeInfo
  return Object.entries(raw).map(([key, val]: [string, any]) => ({
    key,
    label: val.label ?? key,
    register_count: val.count ?? val.register_count ?? 0,
  }));
}

export async function fetchModbusDeviceType(key: string) {
  const res = await api.get(`/modbus/device-types/${encodeURIComponent(key)}`);
  return res.data;
}

// Device list upload
export async function uploadModbusDeviceList(file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post("/modbus/devices/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

// Simulator
export async function fetchSimSessions(): Promise<ModbusSession[]> {
  const res = await api.get("/modbus/simulator/sessions");
  return res.data.sessions;
}

export async function createSimSession(params: {
  device_type: string;
  device_name?: string;
  host?: string;
  port?: number;
  unit_id?: number;
  label?: string;
  update_interval?: number;
}): Promise<ModbusSession> {
  const res = await api.post("/modbus/simulator/create", params);
  return res.data;
}

export async function createSimFromDevices(devices: object[], base_port = 5020) {
  const res = await api.post("/modbus/simulator/create-from-devices", { devices, base_port });
  return res.data;
}

export async function stopSimSession(session_id: string) {
  return api.delete(`/modbus/simulator/${session_id}`);
}

export async function fetchSimRegisters(session_id: string): Promise<ModbusRegisterValue[]> {
  const res = await api.get(`/modbus/simulator/${session_id}/registers`);
  return res.data.registers;
}

export async function writeSimRegister(session_id: string, address: number, value: number) {
  const res = await api.post(`/modbus/simulator/${session_id}/write`, { address, value });
  return res.data;
}

// Client
export async function fetchClientSessions(): Promise<ModbusSession[]> {
  const res = await api.get("/modbus/client/sessions");
  return res.data.sessions;
}

export async function createClientSession(params: {
  host: string;
  port?: number;
  unit_id?: number;
  device_type?: string;
  device_name?: string;
  label?: string;
  poll_interval?: number;
  transport?: "tcp" | "rtu" | "ascii";
  serial_port?: string;
  baudrate?: number;
  bytesize?: number;
  parity?: "N" | "E" | "O";
  stopbits?: number;
  timeout?: number;
  byte_order?: "ABCD" | "BADC" | "CDAB" | "DCBA";
  zero_based_addressing?: boolean;
  block_read_max_gap?: number;
  block_read_max_size?: number;
  enabled_fcs?: number[];
  max_connections?: number;
}): Promise<ModbusSession> {
  const res = await api.post("/modbus/client/create", params);
  return res.data;
}

export async function updateClientSession(
  sessionId: string,
  params: {
    enabled_fcs?: number[];
    byte_order?: string;
    poll_interval?: number;
  }
): Promise<ModbusSession> {
  const res = await api.patch(`/modbus/client/${sessionId}`, params);
  return res.data;
}

export async function createClientFromDevices(devices: object[], poll_interval = 10) {
  const res = await api.post("/modbus/client/create-from-devices", { devices, poll_interval });
  return res.data;
}

export async function stopClientSession(session_id: string) {
  return api.delete(`/modbus/client/${session_id}`);
}

export async function fetchClientRegisters(session_id: string): Promise<ModbusRegisterValue[]> {
  const res = await api.get(`/modbus/client/${session_id}/registers`);
  return res.data.registers;
}

export async function clientReadNow(session_id: string): Promise<ModbusRegisterValue[]> {
  const res = await api.post(`/modbus/client/${session_id}/read-now`);
  return res.data.registers;
}

export async function writeClientRegister(session_id: string, address: number, value: number) {
  const res = await api.post(`/modbus/client/${session_id}/write`, { address, value });
  return res.data;
}

// Scanner
export async function runModbusScan(params: {
  targets: string;
  ports?: number[];
  unit_ids?: number[];
  timeout?: number;
}): Promise<{ found: number; results: ScanResult[] }> {
  const res = await api.post("/modbus/scan", params);
  return res.data;
}

// --- Modbus Diagnostics (God's View) ---

export interface JitterStats {
  target_ms: number;
  samples: number;
  mean_ms?: number;
  std_dev_ms?: number;
  min_ms?: number;
  max_ms?: number;
  p50_jitter_ms?: number;
  p95_jitter_ms?: number;
  timeline_ms?: number[];
}

export interface TrafficStats {
  total_frames: number;
  tx_frames: number;
  rx_frames: number;
  exception_frames: number;
  parse_errors: number;
  recent: Array<{
    direction: string;
    ts_us: number;
    frame_type: string;
    raw_hex: string;
    function_code: number;
    fc_name: string;
    is_exception: boolean;
  }>;
}

export interface DiagnosticsStats {
  rtt: { avg: number; p50: number; p95: number; p99: number };
  exceptions: Array<{ fc: number; addr: number; code: number; count: number }>;
  heatmap: Record<string, number>;
  timeline: Array<{ ts: number; avg_rtt: number; count: number; exceptions: number }>;
  transactions: Array<{
    seq: number;
    ts: number;
    session_id: string;
    fc: number;
    addr: number;
    rtt_ms: number;
    status: string;
    exception_code: number | null;
    response_summary: string;
  }>;
  req_rate: number;
  total_polls: number;
  jitter?: JitterStats;
  traffic?: TrafficStats;
}

export interface RegisterEntry {
  address: number;
  raw: number;
  value: number;
  unit: string;
  name: string;
  delta: number;
  quality?: "good" | "bad" | "uncertain" | "stale";
  timestamp?: number;
  str_value?: string;
}

export interface RegistersResponse {
  session_id: string;
  source: string;
  fc: number;
  registers: RegisterEntry[];
}

export async function getModbusDiagnostics(sessionId: string): Promise<DiagnosticsStats> {
  const res = await api.get(`/modbus/diagnostics/${encodeURIComponent(sessionId)}`);
  return res.data;
}

export async function getModbusRegisters(
  source: "simulator" | "client",
  sessionId: string,
  fc?: number,
  start?: number,
  count?: number,
): Promise<RegistersResponse> {
  const params: Record<string, string | number> = {};
  if (fc !== undefined) params.fc = fc;
  if (start !== undefined) params.start = start;
  if (count !== undefined) params.count = count;
  const res = await api.get(`/modbus/${source}/${encodeURIComponent(sessionId)}/registers`, { params });
  return res.data;
}

export async function writeModbusRegister(
  source: "simulator" | "client",
  sessionId: string,
  body: { fc: number; addr: number; values: number[] },
): Promise<{ ok: boolean; error?: string }> {
  const res = await api.post(
    `/modbus/${source}/${encodeURIComponent(sessionId)}/write`,
    body,
  );
  return res.data;
}

// --- System Status ---

export interface ComponentStatus {
  ok: boolean;
  detail: string;
  latency_ms: number | null;
}

export interface SystemStatus {
  version: string;
  components: Record<string, ComponentStatus>;
}

export async function fetchSystemStatus(): Promise<SystemStatus> {
  const res = await api.get("/status");
  return res.data;
}

// --- Version & Update Checking ---

export interface VersionInfo {
  version: string;
}

export interface UpdateCheckResult {
  currentVersion: string;
  latestVersion: string | null;
  updateAvailable: boolean;
  /** True when the /api/version endpoint itself failed to respond */
  backendUnreachable: boolean;
  /** Human-readable error if the check failed */
  error?: string;
}

/**
 * Fetch the version string currently running in the backend.
 */
export async function fetchBackendVersion(): Promise<VersionInfo> {
  const res = await api.get("/version");
  return res.data;
}

/**
 * Compare two semver strings. Returns:
 *   1  if b > a  (update available)
 *   0  if equal
 *  -1  if a > b
 */
export function compareSemver(a: string, b: string): number {
  const parse = (v: string) =>
    v
      .replace(/^v/, "")
      .split(".")
      .map((n) => parseInt(n, 10) || 0);

  const [aMaj, aMin, aPat] = parse(a);
  const [bMaj, bMin, bPat] = parse(b);

  if (bMaj !== aMaj) return bMaj > aMaj ? 1 : -1;
  if (bMin !== aMin) return bMin > aMin ? 1 : -1;
  if (bPat !== aPat) return bPat > aPat ? 1 : -1;
  return 0;
}

/**
 * Full update check:
 *   1. Fetches the running backend version via GET /api/version
 *   2. Fetches the latest published version from GitHub Releases API
 *   3. Returns a structured result describing whether an update is available
 *
 * On any failure the result contains a human-readable `error` field and
 * `updateAvailable` is false — so the caller can fall back gracefully.
 */
export async function checkForUpdates(
  repoOwner = "anomalyco",
  repoName  = "wireshark-agent"
): Promise<UpdateCheckResult> {
  // --- 1. Fetch current backend version ---
  let currentVersion = "unknown";
  try {
    const info = await fetchBackendVersion();
    currentVersion = info.version;
  } catch {
    return {
      currentVersion: "unknown",
      latestVersion:  null,
      updateAvailable: false,
      backendUnreachable: true,
      error: "Backend unreachable — cannot determine current version.",
    };
  }

  // --- 2. Fetch latest release from GitHub ---
  let latestVersion: string | null = null;
  try {
    const ghRes = await fetch(
      `https://api.github.com/repos/${repoOwner}/${repoName}/releases/latest`,
      {
        headers: { Accept: "application/vnd.github+json" },
        signal: AbortSignal.timeout(8000),
      }
    );
    if (!ghRes.ok) {
      throw new Error(`GitHub API returned ${ghRes.status}`);
    }
    const ghData = await ghRes.json();
    latestVersion = (ghData.tag_name as string | undefined) ?? null;
  } catch (err) {
    return {
      currentVersion,
      latestVersion: null,
      updateAvailable: false,
      backendUnreachable: false,
      error: `Could not reach GitHub to check for updates: ${err}`,
    };
  }

  // --- 3. Compare ---
  const updateAvailable =
    latestVersion !== null && compareSemver(currentVersion, latestVersion) === 1;

  return {
    currentVersion,
    latestVersion,
    updateAvailable,
    backendUnreachable: false,
  };
}

// --- WebSocket helpers ---

/**
 * Resolve the WebSocket host:port to use.
 * Under Electron the page is loaded as file://, so window.location.hostname
 * is empty — we must use 127.0.0.1 and the injected backend port instead.
 */
function resolveWSBase(): string {
  if (
    typeof window !== "undefined" &&
    window.location.protocol === "file:"
  ) {
    const port =
      (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ??
      ((window as unknown as { electronBridge?: { getBackendPort: () => number } })
        .electronBridge?.getBackendPort() ?? 8000);
    return `ws://127.0.0.1:${port}`;
  }
  return `ws://${window.location.hostname}:8000`;
}

// ── WebSocket reconnection helper ─────────────────────────────────────────────

const WS_MAX_RETRIES = 5;
const WS_BASE_DELAY_MS = 1000;   // 1s → 2s → 4s → 8s → 16s

/**
 * Returns a disposer function — call it to permanently stop reconnecting and
 * close any open connection. Safe to call multiple times.
 */
function createReconnectingWebSocket(
  url: string,
  onOpen:    (ws: WebSocket) => void,
  onMessage: (ev: MessageEvent) => void,
  onGiveUp?: () => void,
): () => void {
  let ws: WebSocket | null = null;
  let attempt = 0;
  let stopped = false;
  let pingInterval: ReturnType<typeof setInterval> | null = null;

  function cleanup() {
    if (pingInterval !== null) {
      clearInterval(pingInterval);
      pingInterval = null;
    }
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.onopen  = null;
      ws.onmessage = null;
      if (ws.readyState < WebSocket.CLOSING) ws.close();
      ws = null;
    }
  }

  function connect() {
    if (stopped) return;
    cleanup();

    ws = new WebSocket(url);

    ws.onopen = () => {
      attempt = 0;
      onOpen(ws!);
      // Keepalive ping every 20s
      pingInterval = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 20_000);
    };

    ws.onmessage = onMessage;

    ws.onclose = ws.onerror = () => {
      cleanup();
      if (stopped) return;
      attempt++;
      if (attempt > WS_MAX_RETRIES) {
        console.warn(`[WebSocket] ${url} gave up after ${WS_MAX_RETRIES} retries.`);
        onGiveUp?.();
        return;
      }
      const delay = WS_BASE_DELAY_MS * 2 ** (attempt - 1);
      console.info(`[WebSocket] reconnect attempt ${attempt} in ${delay}ms`);
      setTimeout(connect, delay);
    };
  }

  connect();

  return () => {
    stopped = true;
    cleanup();
  };
}

export function createPacketWebSocket(
  onPacket: (pkt: Packet) => void,
  onConnected?: () => void,
  onGiveUp?: () => void,
): () => void {
  return createReconnectingWebSocket(
    `${resolveWSBase()}/ws/packets`,
    () => onConnected?.(),
    (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "packet") onPacket(msg.data);
      } catch {}
    },
    onGiveUp,
  );
}

export function createInsightWebSocket(
  onToken: (token: string) => void,
  onEnd: (full: string) => void,
  onConnected?: () => void,
  onGiveUp?: () => void,
): () => void {
  return createReconnectingWebSocket(
    `${resolveWSBase()}/ws/insights`,
    () => onConnected?.(),
    (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "insight_token") onToken(msg.data);
        if (msg.type === "insight_end") onEnd(msg.data);
      } catch {}
    },
    onGiveUp,
  );
}

// --- Modbus Live WebSocket ---

export interface ModbusWsData {
  type: "init" | "data" | "status" | "write_result" | "error";
  registers?: RegisterEntry[];
  session?: ModbusSession;
  status?: string;
  poll_count?: number;
  error_count?: number;
  error?: string;
  ok?: boolean;
  addr?: number;
  value?: number;
  message?: string;
  ts?: number;
}

export function createModbusLiveWebSocket(
  sessionId: string,
  onMessage: (msg: ModbusWsData) => void,
  interval: number = 1.0,
  onGiveUp?: () => void,
): () => void {
  return createReconnectingWebSocket(
    `${resolveWSBase()}/api/modbus/client/${encodeURIComponent(sessionId)}/ws`,
    (socket: WebSocket) => {
      socket.send(JSON.stringify({ cmd: "live", interval }));
    },
    (ev: MessageEvent) => {
      try {
        const msg: ModbusWsData = JSON.parse(ev.data);
        onMessage(msg);
      } catch {}
    },
    onGiveUp,
  );
}

// ── Modbus Traffic WebSocket ──────────────────────────────────────────────────

export interface ParsedFrame {
  direction: "tx" | "rx"
  ts_us: number
  frame_type: "tcp" | "rtu"
  raw_hex: string
  mbap?: {
    transaction_id: number
    protocol_id: number
    length: number
    unit_id: number
  }
  function_code: number
  fc_name: string
  is_exception: boolean
  exception_code?: number
  exception_name?: string
  start_address?: number
  quantity?: number
  byte_count?: number
  data_hex?: string
  crc_valid?: boolean
  parse_error?: string
}

export function createModbusTrafficWebSocket(
  sessionId: string,
  onFrame: (frame: ParsedFrame) => void,
  onGiveUp?: () => void,
): () => void {
  return createReconnectingWebSocket(
    `${resolveWSBase()}/api/modbus/client/${encodeURIComponent(sessionId)}/traffic/ws`,
    (_socket: WebSocket) => {
      // no handshake needed — server pushes frames immediately
    },
    (ev: MessageEvent) => {
      try {
        const frame = JSON.parse(ev.data) as ParsedFrame;
        onFrame(frame);
      } catch {}
    },
    onGiveUp,
  );
}

export async function setModbusTrafficLog(
  sessionId: string,
  enabled: boolean,
  path?: string,
): Promise<void> {
  await api.post(
    `/modbus/client/${encodeURIComponent(sessionId)}/traffic/log`,
    { enabled, path: path ?? null },
  );
}

// ===================== Scheduler =====================

export interface SchedulerJob {
  id: string
  name: string
  type: string
  schedule: string
  params: Record<string, unknown>
  created_at: string
  last_run: string | null
  last_status: 'ok' | 'error' | null
  next_run: string | null
}

export interface JobRunRecord {
  started_at: string
  finished_at: string
  status: 'ok' | 'error'
  output: string
  duration_ms: number
}

export interface CreateJobPayload {
  type: string
  schedule: string
  params?: Record<string, unknown>
  name?: string
}

export const fetchSchedulerJobs = (): Promise<SchedulerJob[]> =>
  api.get('/scheduler/jobs').then(r => r.data)

export const createSchedulerJob = (payload: CreateJobPayload): Promise<SchedulerJob> =>
  api.post('/scheduler/jobs', payload).then(r => r.data)

export const deleteSchedulerJob = (id: string): Promise<void> =>
  api.delete(`/scheduler/jobs/${id}`)

export const runJobNow = (id: string): Promise<{ status: string; job_id: string }> =>
  api.post(`/scheduler/jobs/${id}/run`).then(r => r.data)

export const fetchJobHistory = (id: string): Promise<JobRunRecord[]> =>
  api.get(`/scheduler/jobs/${id}/history`).then(r => r.data)


// ── Deep Analysis ─────────────────────────────────────────────────────────────

export async function runDeepAnalysis(pcapPath?: string): Promise<DeepAnalysisReport> {
  const params = pcapPath ? `?pcap_path=${encodeURIComponent(pcapPath)}` : "";
  const res = await api.post<DeepAnalysisReport>(`/analysis/deep${params}`);
  return res.data;
}

export async function streamNarrative(
  onToken: (token: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/analysis/narrative`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken(decoder.decode(value, { stream: true }));
  }
}

/** Serialize DeepAnalysisReport to a compact context string (≤800 chars). */
export function buildAnalysisContext(report: DeepAnalysisReport): string {
  const t = report.tcp_health;
  const l = report.latency.aggregate;
  const tcpProtos = [...new Set(report.streams.map((s) => s.protocol))].slice(0, 5).join(", ");
  const tcpCount = report.streams.filter((s) => s.protocol !== "UDP").length;
  const udpCount = report.streams.length - tcpCount;
  const expertLine =
    report.expert_info.available && report.expert_info.counts
      ? `Expert: ${report.expert_info.counts.error} errors, ${report.expert_info.counts.warning} warnings`
      : "Expert: not available";
  const bursts = report.io_timeline.filter((b) => b.burst);
  const burstLine =
    bursts.length > 0
      ? `Bursts: detected at t=${bursts[0].t.toFixed(1)}s`
      : "Bursts: none";
  return [
    `TCP: ${t.retransmissions} retransmit, ${t.zero_windows} zero-win, ${t.rsts} RST, RTT ${t.rtt_avg_ms}ms${t.estimated ? " (est)" : ""}`,
    `Latency: client ${l.client_ms}ms / network ${l.network_rtt_ms}ms / server ${l.server_ms}ms (${l.bottleneck} bottleneck)`,
    `Streams: ${tcpCount} TCP, ${udpCount} UDP — protocols: ${tcpProtos || "unknown"}`,
    expertLine,
    burstLine,
  ]
    .join("\n")
    .slice(0, 800);
}
