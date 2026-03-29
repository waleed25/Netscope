import { create } from "zustand";

export interface Packet {
  id: number;
  timestamp: number;
  layers: string[];
  src_ip: string;
  dst_ip: string;
  src_port: string;
  dst_port: string;
  protocol: string;
  length: number;
  info: string;
  color: string;
  details: Record<string, string>;
}

export interface Insight {
  text: string;
  source: string;
  timestamp: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

export interface Interface {
  index: string;
  name: string;
  device: string;
}

export interface LLMStatus {
  backend: "ollama" | "lmstudio";
  base_url: string;
  model: string;
  reachable: boolean;
  // Ollama-only VRAM fields (absent for LM Studio)
  vram_used_bytes?:  number;
  model_size_bytes?: number;
  context_length?:   number;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  requests: number;
}

export type Theme = "light" | "dark";

// ── New Shell navigation (UI Redesign) ────────────────────────────────────────
export type ActiveView = "capture" | "analysis" | "trafficmap" | "protocols" | "tools";
export type RightPanelTab = "chat" | "quick" | "deep";

// ── Deep Analysis types ───────────────────────────────────────────────────────

interface TcpHealthReport {
  retransmissions: number;
  zero_windows: number;
  duplicate_acks: number;
  out_of_order: number;
  rsts: number;
  rtt_avg_ms: number;
  top_offenders: Array<{ src: string; dst: string; retransmits: number }>;
  estimated: boolean;
}

interface StreamRecord {
  stream_id: number;
  src: string;
  dst: string;
  protocol: string;
  packets: number;
  bytes: number;
  duration_s: number;
}

interface LatencyReport {
  streams: Array<{
    stream_id: number;
    network_rtt_ms: number;
    server_ms: number;
    client_ms: number;
    bottleneck: 'client' | 'network' | 'server';
  }>;
  aggregate: {
    network_rtt_ms: number;
    server_ms: number;
    client_ms: number;
    bottleneck: 'client' | 'network' | 'server' | 'unknown';
    server_pct: number;
  };
}

interface ExpertInfoReport {
  available: boolean;
  reason?: string;
  counts?: { error: number; warning: number; note: number; chat: number };
  top?: Array<{ severity: string; message: string; count: number }>;
}

interface IoTimelineBin {
  t: number;
  packets_per_sec: number;
  bytes_per_sec: number;
  burst: boolean;
}

export interface DeepAnalysisReport {
  tcp_health: TcpHealthReport;
  streams: StreamRecord[];
  latency: LatencyReport;
  expert_info: ExpertInfoReport;
  io_timeline: IoTimelineBin[];
}

// ─────────────────────────────────────────────────────────────────────────────

interface AppState {
  // Theme
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;

  // Packets
  packets: Packet[];
  totalPackets: number;
  setTotalPackets: (n: number) => void;
  addPacket: (pkt: Packet) => void;
  setPackets: (pkts: Packet[]) => void;
  clearPackets: () => void;

  // Capture
  isCapturing: boolean;
  activeInterface: string;
  bpfFilter: string;
  setIsCapturing: (v: boolean) => void;
  setActiveInterface: (v: string) => void;
  setBpfFilter: (v: string) => void;

  // Interfaces
  interfaces: Interface[];
  setInterfaces: (ifaces: Interface[]) => void;

  // Local IPs (machine's own interface addresses for packet highlighting)
  localIPs: string[];
  setLocalIPs: (ips: string[]) => void;

  // Insights
  insights: Insight[];
  currentInsightStream: string;
  addInsight: (insight: Insight) => void;
  clearInsights: () => void;
  appendInsightToken: (token: string) => void;
  clearInsightStream: () => void;

  // Chat
  chatMessages: ChatMessage[];
  isChatLoading: boolean;
  addChatMessage: (msg: ChatMessage) => void;
  setChatLoading: (v: boolean) => void;
  clearChat: () => void;

  // LLM
  llmStatus: LLMStatus | null;
  llmBackend: "ollama" | "lmstudio";
  setLLMStatus: (s: LLMStatus) => void;
  setLLMBackend: (b: "ollama" | "lmstudio") => void;

  // Token usage
  tokenUsage: TokenUsage;
  setTokenUsage: (t: TokenUsage) => void;
  resetTokenUsage: () => void;

  // UI
  selectedProtocol: string;
  setSelectedProtocol: (p: string) => void;
  activeTab: "packets" | "tools" | "expert" | "modbus" | "rag" | "status" | "channels" | "trafficmap" | "scheduler" | "wizards" | "reports";
  setActiveTab: (t: "packets" | "tools" | "expert" | "modbus" | "rag" | "status" | "channels" | "trafficmap" | "scheduler" | "wizards" | "reports") => void;
  packetsSubTab: "live" | "import" | "saved";
  setPacketsSubTab: (v: "live" | "import" | "saved") => void;

  // RAG
  ragEnabled: boolean;
  setRagEnabled: (v: boolean) => void;
  useHyde: boolean;
  setUseHyde: (v: boolean) => void;

  // Thinking
  thinkingEnabled: boolean;
  setThinkingEnabled: (v: boolean) => void;

  // Autonomous mode
  autonomousEnabled: boolean;
  setAutonomousEnabled: (v: boolean) => void;

  // Shell mode
  shellEnabled: boolean;
  setShellEnabled: (v: boolean) => void;

  // Deep Analysis
  analysisReport: DeepAnalysisReport | null;
  analysisContext: string;
  setAnalysisReport: (report: DeepAnalysisReport, context: string) => void;
  clearAnalysisReport: () => void;
  analysisReportTs: number;

  // Chat prefill (for "Ask in chat →" buttons)
  chatPrefill: string;
  setChatPrefill: (v: string) => void;
  clearChatPrefill: () => void;

  // ── New Shell navigation (UI Redesign)
  rightPanelTab: RightPanelTab;
  setRightPanelTab: (t: RightPanelTab) => void;
  analysisStripExpanded: boolean;
  setAnalysisStripExpanded: (v: boolean) => void;
}

const getInitialTheme = (): Theme => {
  try {
    const stored = localStorage.getItem("netscope-theme");
    if (stored === "light" || stored === "dark") return stored;
  } catch {}
  return "dark"; // default
};

export const useStore = create<AppState>((set, get) => ({
  // Theme
  theme: getInitialTheme(),
  setTheme: (t) => {
    localStorage.setItem("netscope-theme", t);
    set({ theme: t });
  },
  toggleTheme: () => {
    const next = get().theme === "dark" ? "light" : "dark";
    localStorage.setItem("netscope-theme", next);
    set({ theme: next });
  },

  // Packets
  packets: [],
  totalPackets: 0,
  setTotalPackets: (n) => set({ totalPackets: n }),
  addPacket: (pkt) =>
    set((state) => {
      const packets = [...state.packets, pkt].slice(-5000);
      return { packets, totalPackets: state.totalPackets + 1 };
    }),
  setPackets: (pkts) => set({ packets: pkts, totalPackets: pkts.length }),
  clearPackets: () => set({ packets: [], totalPackets: 0 }),

  // Capture
  isCapturing: false,
  activeInterface: "",
  bpfFilter: "",
  setIsCapturing: (v) => set({ isCapturing: v }),
  setActiveInterface: (v) => set({ activeInterface: v }),
  setBpfFilter: (v) => set({ bpfFilter: v }),

  // Interfaces
  interfaces: [],
  setInterfaces: (ifaces) => set({ interfaces: ifaces }),

  // Local IPs
  localIPs: [],
  setLocalIPs: (ips) => set({ localIPs: ips }),

  // Insights
  insights: [],
  currentInsightStream: "",
  addInsight: (insight) =>
    set((state) => ({ insights: [insight, ...state.insights].slice(0, 50) })),
  clearInsights: () => set({ insights: [] }),
  appendInsightToken: (token) =>
    set((state) => ({ currentInsightStream: state.currentInsightStream + token })),
  clearInsightStream: () => set({ currentInsightStream: "" }),

  // Chat
  chatMessages: [],
  isChatLoading: false,
  addChatMessage: (msg) =>
    set((state) => ({
      chatMessages: [...state.chatMessages, msg].slice(-500),
    })),
  setChatLoading: (v) => set({ isChatLoading: v }),
  clearChat: () => set({ chatMessages: [] }),

  // LLM
  llmStatus: null,
  llmBackend: "ollama",
  setLLMStatus: (s) => set({ llmStatus: s }),
  setLLMBackend: (b) => set({ llmBackend: b }),

  // Token usage
  tokenUsage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, requests: 0 },
  setTokenUsage: (t) => set({ tokenUsage: t }),
  resetTokenUsage: () =>
    set({ tokenUsage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, requests: 0 } }),

  // UI
  selectedProtocol: "",
  setSelectedProtocol: (p) => set({ selectedProtocol: p }),
  activeTab: "packets" as "packets" | "tools" | "expert" | "modbus" | "rag" | "status" | "channels" | "trafficmap" | "scheduler" | "wizards" | "reports",
  setActiveTab: (t) => set({ activeTab: t }),
  packetsSubTab: "live" as "live" | "import" | "saved",
  setPacketsSubTab: (v) => set({ packetsSubTab: v }),

  // RAG
  ragEnabled: false,
  setRagEnabled: (v) => set({ ragEnabled: v }),
  useHyde: false,
  setUseHyde: (v) => set({ useHyde: v }),

  // Thinking
  thinkingEnabled: false,
  setThinkingEnabled: (v) => set({ thinkingEnabled: v }),

  // Autonomous mode
  autonomousEnabled: false,
  setAutonomousEnabled: (v) => set({ autonomousEnabled: v }),

  // Shell mode
  shellEnabled: false,
  setShellEnabled: (v) => set({ shellEnabled: v }),

  // Deep Analysis
  analysisReport: null,
  analysisContext: "",
  analysisReportTs: 0,
  setAnalysisReport: (report, context) => set({ analysisReport: report, analysisContext: context, analysisReportTs: Date.now() / 1000 }),
  clearAnalysisReport: () => set({ analysisReport: null, analysisContext: "", analysisReportTs: 0 }),

  // Chat prefill
  chatPrefill: "",
  setChatPrefill: (v) => set({ chatPrefill: v }),
  clearChatPrefill: () => set({ chatPrefill: "" }),

  // New Shell navigation
  rightPanelTab: "chat",
  setRightPanelTab: (t) => set({ rightPanelTab: t }),
  analysisStripExpanded: false,
  setAnalysisStripExpanded: (v) => set({ analysisStripExpanded: v }),
}));
