import { useRef, useState, useEffect, useCallback } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { sendChatMessage, clearChatHistory, generateInsight, stopCapture, uploadPcap, getThinking, setThinking, getAutonomous, setAutonomous, getShell, setShell, restartBackend } from "../lib/api";
import type { ToolEvent, TrafficMapSummary } from "../lib/api";
import { InlineChatMap } from "./InlineChatMap";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Send, Trash2, Loader2, MessageSquare, User, Bot,
  ChevronDown, ChevronRight, Radio, CheckCircle2,
  BookOpen, Zap, AlertTriangle, CheckCircle,
  Brain, Shield, ArrowLeftRight, Network, Cpu, Timer, Square,
  Paperclip, FileSearch, X, GitFork, RotateCcw, Terminal,
} from "lucide-react";
import type { ChatMessage } from "../store/useStore";

const EXAMPLE_QUERIES = [
  "What are the top 5 source IPs?",
  "Are there any DNS exfiltration patterns?",
  "Capture 10 seconds of traffic and analyze it",
  "Ping 8.8.8.8 and tell me the latency",
  "Run ipconfig and summarize my network interfaces",
  "Which IPs are communicating on unusual ports?",
  "Show me the traffic map — who is talking to who?",
  "Capture 30 seconds and tell me what hosts I'm talking to",
];

// ── Tool tracking ─────────────────────────────────────────────────────────────

interface ToolCard {
  name: string;
  args: string;
  output?: string; // set once result arrives
}

// ── Capture card ──────────────────────────────────────────────────────────────

interface CaptureCardData {
  seconds: number;         // total capture duration
  elapsed: number;         // seconds elapsed (counts up)
  done: boolean;
  packetCount?: number;
}

function CaptureCard({ data, onStop }: { data: CaptureCardData; onStop?: () => void }) {
  const [stopping, setStopping] = useState(false);
  const pct = data.done ? 100 : Math.min(100, Math.round((data.elapsed / data.seconds) * 100));

  const handleStop = async () => {
    if (stopping || data.done) return;
    setStopping(true);
    try {
      await stopCapture();
    } catch {
      // best-effort; the backend will mark capture done regardless
    } finally {
      setStopping(false);
      onStop?.();
    }
  };

  return (
    <div className="my-2 rounded border border-accent-emphasis bg-background text-xs overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2">
        {data.done ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
        ) : (
          <Radio className="w-3.5 h-3.5 text-accent shrink-0 animate-pulse" />
        )}
        <span className={`font-mono font-semibold ${data.done ? "text-success" : "text-accent"}`}>
          capture
        </span>
        {data.done ? (
          <span className="text-muted font-mono">
            done — {data.packetCount ?? 0} packets in {data.seconds}s
          </span>
        ) : (
          <span className="text-muted font-mono">
            {data.elapsed}s / {data.seconds}s
          </span>
        )}
        <span className="ml-auto text-muted font-mono">{pct}%</span>

        {/* Stop button — only visible while capture is running */}
        {!data.done && (
          <button
            onClick={handleStop}
            disabled={stopping}
            title="Stop capture"
            className="ml-2 flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-danger-emphasis/20 border border-danger-emphasis text-danger hover:bg-danger-emphasis/25 disabled:opacity-50 transition-colors shrink-0"
          >
            {stopping ? (
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
            ) : (
              <Square className="w-2.5 h-2.5" />
            )}
            Stop
          </button>
        )}
      </div>
      {/* Progress bar */}
      <div className="h-1 bg-surface">
        <div
          className={`h-1 transition-all duration-1000 ${data.done ? "bg-success" : "bg-accent-emphasis"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** Gemini-style inline tool chip — compact pill, no expansion */
function ToolChip({ card }: { card: ToolCard }) {
  const done = card.output !== undefined;
  const label = card.args ? `${card.name} ${card.args}` : card.name;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono border transition-colors ${
        done
          ? "bg-success/8 border-success/25 text-success"
          : "bg-accent/8 border-accent/25 text-accent"
      }`}
      title={done && card.output ? card.output.slice(0, 300) : label}
    >
      {done
        ? <CheckCircle2 className="w-3 h-3 shrink-0" />
        : <Loader2 className="w-3 h-3 animate-spin shrink-0" />}
      {label}
    </span>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

/** Parse the compact tool annotation stored at the head of assistant messages. */
function parsePersistedTools(content: string): {
  tools: Array<{ name: string; args: string }>;
  body: string;
} {
  const match = content.match(/^<!-- netscope-tools: (\[[\s\S]*?\]) -->\n\n/);
  if (!match) return { tools: [], body: content };
  try {
    return { tools: JSON.parse(match[1]) as Array<{ name: string; args: string }>, body: content.slice(match[0].length) };
  } catch {
    return { tools: [], body: content };
  }
}

/** Parse the inline map annotation stored at the head of assistant messages. */
function parsePersistedMap(content: string): { mapData: TrafficMapSummary | null; rest: string } {
  const match = content.match(/^<!-- netscope-map: (\{[\s\S]*?\}) -->\n/);
  if (!match) return { mapData: null, rest: content };
  try {
    return { mapData: JSON.parse(match[1]) as TrafficMapSummary, rest: content.slice(match[0].length) };
  } catch {
    return { mapData: null, rest: content };
  }
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  const { tools, body: bodyWithMap } = isUser ? { tools: [], body: msg.content } : parsePersistedTools(msg.content);
  const { mapData, rest: body } = isUser ? { mapData: null, rest: bodyWithMap } : parsePersistedMap(bodyWithMap);

  return (
    <div className={`flex gap-2.5 mb-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
          isUser ? "bg-success-emphasis" : "bg-purple-emphasis"
        }`}
      >
        {isUser ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
      </div>
      <div
        className={`max-w-[80%] rounded-lg px-3 py-2.5 text-xs ${
          isUser
            ? "bg-surface-hover border border-border text-foreground"
            : "bg-surface border border-border text-foreground"
        }`}
      >
        {/* Gemini-style tool chips for persisted messages */}
        {tools.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 mb-2.5 pb-2.5 border-b border-border/60">
            <span className="text-[10px] text-muted">Used</span>
            {tools.map((t, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono border bg-success/8 border-success/25 text-success"
              >
                <CheckCircle2 className="w-3 h-3 shrink-0" />
                {t.args ? `${t.name} ${t.args}` : t.name}
              </span>
            ))}
          </div>
        )}

        {/* Inline traffic map (persisted) */}
        {mapData && <InlineChatMap data={mapData} />}

        {isUser ? (
          <p>{body}</p>
        ) : (
          <div className="prose prose-invert prose-xs max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
          </div>
        )}
        <div className="text-muted text-[10px] mt-1 text-right">
          {new Date(msg.timestamp).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}

// ── Reasoning block (collapsible thinking display) ───────────────────────────

function ReasoningBlock({ text, defaultOpen = true }: { text: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="my-2 rounded border border-purple-emphasis/40 bg-surface text-xs overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-hover transition-colors"
      >
        <Brain className="w-3 h-3 text-purple shrink-0 animate-pulse" />
        <span className="text-purple font-mono text-[10px] font-semibold">Thinking...</span>
        <span className="text-muted font-mono text-[10px]">{text.length} chars</span>
        <span className="ml-auto shrink-0">
          {open ? (
            <ChevronDown className="w-3 h-3 text-muted" />
          ) : (
            <ChevronRight className="w-3 h-3 text-muted" />
          )}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-2 border-t border-purple-emphasis/20 pt-2 max-h-40 overflow-y-auto">
          <p className="text-muted font-mono text-[10px] leading-relaxed whitespace-pre-wrap italic">
            {text}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Streaming bubble (shown while LLM is responding) ─────────────────────────

// A "stream item" is either a tool card or a capture card, ordered by arrival
type StreamItem =
  | { kind: "tool"; card: ToolCard }
  | { kind: "capture"; data: CaptureCardData };

function StreamingBubble({
  text,
  reasoningText,
  streamItems,
  onStopCapture,
  mapData,
}: {
  text: string;
  reasoningText: string;
  streamItems: StreamItem[];
  onStopCapture: (idx: number) => void;
  mapData: TrafficMapSummary | null;
}) {
  const toolItems = streamItems.filter((i) => i.kind === "tool") as { kind: "tool"; card: ToolCard }[];
  const captureItems = streamItems
    .map((item, idx) => ({ item, idx }))
    .filter(({ item }) => item.kind === "capture") as { item: { kind: "capture"; data: CaptureCardData }; idx: number }[];

  return (
    <div className="flex gap-2.5 mb-4">
      <div className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center bg-purple-emphasis">
        <Bot className="w-3.5 h-3.5" />
      </div>
      <div className="max-w-[80%] rounded-lg px-3 py-2.5 text-xs bg-surface border border-border text-foreground">
        {/* Reasoning (thinking) block */}
        {reasoningText && <ReasoningBlock text={reasoningText} />}

        {/* Gemini-style tools row — compact chips */}
        {toolItems.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 mb-2.5 pb-2.5 border-b border-border/60">
            <span className="text-[10px] text-muted">Used</span>
            {toolItems.map((t, i) => (
              <ToolChip key={i} card={t.card} />
            ))}
          </div>
        )}

        {/* Capture progress cards (keep full card — progress bar is useful) */}
        {captureItems.map(({ item, idx }) => (
          <CaptureCard key={idx} data={item.data} onStop={() => onStopCapture(idx)} />
        ))}

        {/* Inline traffic map (streaming) */}
        {mapData && <InlineChatMap data={mapData} />}

        {/* Streaming LLM text */}
        {text && (
          <div className="prose prose-invert prose-xs max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        )}

        {/* Typing indicator */}
        {!text && toolItems.every((t) => t.card.output !== undefined) && captureItems.every((c) => c.item.data.done) && (
          <span className="inline-flex gap-0.5 mt-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1 h-1 rounded-full bg-muted animate-bounce"
                style={{ animationDelay: `${i * 150}ms` }}
              />
            ))}
          </span>
        )}
        {(text || !toolItems.every((t) => t.card.output !== undefined) || captureItems.some((c) => !c.item.data.done)) && (
          <Loader2 className={`w-3 h-3 animate-spin text-muted mt-1 ${text ? "hidden" : ""}`} />
        )}
      </div>
    </div>
  );
}

// ── Main ChatBox ──────────────────────────────────────────────────────────────

export function ChatBox() {
  const {
    chatMessages,
    addChatMessage,
    isChatLoading,
    setChatLoading,
    clearChat,
    ragEnabled,
    setRagEnabled,
    useHyde,
    setUseHyde,
    setActiveTab,
    thinkingEnabled,
    setThinkingEnabled,
    autonomousEnabled,
    setAutonomousEnabled,
    shellEnabled,
    setShellEnabled,
  } = useStore(
    useShallow((s) => ({
      chatMessages: s.chatMessages,
      addChatMessage: s.addChatMessage,
      isChatLoading: s.isChatLoading,
      setChatLoading: s.setChatLoading,
      clearChat: s.clearChat,
      ragEnabled: s.ragEnabled,
      setRagEnabled: s.setRagEnabled,
      useHyde: s.useHyde,
      setUseHyde: s.setUseHyde,
      setActiveTab: s.setActiveTab,
      thinkingEnabled: s.thinkingEnabled,
      setThinkingEnabled: s.setThinkingEnabled,
      autonomousEnabled: s.autonomousEnabled,
      setAutonomousEnabled: s.setAutonomousEnabled,
      shellEnabled: s.shellEnabled,
      setShellEnabled: s.setShellEnabled,
    }))
  );
  const packetsLength = useStore((s) => s.totalPackets);
  const chatPrefill = useStore((s) => s.chatPrefill);
  const clearChatPrefill = useStore((s) => s.clearChatPrefill);
  const analysisContext = useStore((s) => s.analysisContext);

  const [input, setInput] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [reasoningText, setReasoningText] = useState("");
  const [streamItems, setStreamItems] = useState<StreamItem[]>([]);
  const [faithfulness, setFaithfulness] = useState<number | null>(null);
  const [ragSources, setRagSources] = useState<Array<{ source: string; page: number | null }>>([]);
  const [streamingMapData, setStreamingMapData] = useState<TrafficMapSummary | null>(null);
  const mapDataRef = useRef<TrafficMapSummary | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Interval ref for the capture countdown ticker
  const captureTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // PCAP attachment state
  const [loadedPcap, setLoadedPcap] = useState<{ name: string; packets: number } | null>(null);
  const [pcapUploading, setPcapUploading] = useState(false);
  const [pcapError, setPcapError] = useState("");
  const [chatDragOver, setChatDragOver] = useState(false);
  const pcapInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, streamingText, streamItems]);

  // Consume chatPrefill from InsightPanel "Ask in chat →" buttons
  useEffect(() => {
    if (chatPrefill) {
      setInput(chatPrefill);
      clearChatPrefill();
    }
  }, [chatPrefill]);

  // Clean up on unmount: abort any in-flight stream and clear the capture timer.
  // Without aborting, a tab switch during streaming leaves an orphaned fetch with
  // no consumer, and setChatLoading(false) never fires (isChatLoading stays true).
  useEffect(() => () => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (captureTimerRef.current) clearInterval(captureTimerRef.current);
  }, []);

  // Sync thinking/autonomous/shell state from backend on mount
  useEffect(() => {
    getThinking().then((r) => setThinkingEnabled(r.enabled)).catch(() => {});
    getAutonomous().then((r) => setAutonomousEnabled(r.enabled)).catch(() => {});
    getShell().then((r) => setShellEnabled(r.enabled)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── PCAP upload + auto-analysis ───────────────────────────────────────────
  const handlePcapFile = useCallback(async (file: File) => {
    const name = file.name.toLowerCase();
    if (!name.endsWith(".pcap") && !name.endsWith(".pcapng") && !name.endsWith(".cap")) {
      setPcapError("Only .pcap / .pcapng / .cap files are supported.");
      return;
    }
    setPcapError("");
    setPcapUploading(true);
    try {
      const res = await uploadPcap(file);
      const { filename, packet_count } = res.data;
      setLoadedPcap({ name: filename, packets: packet_count });
      // System message confirming load
      addChatMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: `[PCAP loaded: **${filename}** — ${packet_count.toLocaleString()} packets]\n\nRun tshark expert analysis on this capture and summarize the findings.`,
        timestamp: Date.now(),
      });
      // Auto-trigger expert analysis immediately
      await runExpertAnalysis();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Upload failed.";
      setPcapError(msg);
    } finally {
      setPcapUploading(false);
    }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const runExpertAnalysis = async () => {
    setChatLoading(true);
    setStreamingText("");
    setReasoningText("");
    setStreamItems([]);
    setFaithfulness(null);
    setRagSources([]);
    setStreamingMapData(null);
    mapDataRef.current = null;

    const controller = new AbortController();
    abortRef.current = controller;

    let reasoningAccum = "";
    let textAccum = "";

    try {
      const itemsRef: StreamItem[] = [];
      const toolCardsRef: ToolCard[] = [];

      const fullText = await sendChatMessage(
        "Run tshark expert analysis on the loaded PCAP and summarize the findings.",
        (token) => { textAccum += token; setStreamingText((p) => p + token); },
        (ev: ToolEvent) => {
          if (ev.type === "reasoning") { reasoningAccum += ev.token; setReasoningText(reasoningAccum); return; }
          if (ev.type === "faithfulness") { setFaithfulness(ev.score); }
          else if (ev.type === "rag_sources") { setRagSources(ev.sources); }
          else if (ev.type === "traffic_map_data") {
            mapDataRef.current = ev.data;
            setStreamingMapData(ev.data);
          } else if (ev.type === "call") {
            const card: ToolCard = { name: ev.name, args: ev.args };
            toolCardsRef.push(card); itemsRef.push({ kind: "tool", card }); setStreamItems([...itemsRef]);
          } else if (ev.type === "result") {
            for (let i = toolCardsRef.length - 1; i >= 0; i--) {
              if (toolCardsRef[i].output === undefined) { toolCardsRef[i].output = ev.output; break; }
            }
            setStreamItems([...itemsRef]);
          }
        },
        ragEnabled,
        useHyde,
        controller.signal,
        analysisContext || undefined,
      );

      const mapAnnotation = mapDataRef.current
        ? `<!-- netscope-map: ${JSON.stringify(mapDataRef.current)} -->\n`
        : "";
      const toolAnnotation = toolCardsRef.length
        ? `<!-- netscope-tools: ${JSON.stringify(
            toolCardsRef.map((c) => ({ name: c.name, args: c.args }))
          )} -->\n\n`
        : "";
      const reasoningBlock = reasoningAccum
        ? `<details><summary>Reasoning (${reasoningAccum.length} chars)</summary>\n\n${reasoningAccum}\n\n</details>\n\n`
        : "";
      addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: mapAnnotation + toolAnnotation + reasoningBlock + fullText, timestamp: Date.now() });
    } catch (e: unknown) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        const errMsg = e instanceof Error ? e.message : "Analysis failed.";
        addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: `Error: ${errMsg}`, timestamp: Date.now() });
      }
    } finally {
      setStreamingText(""); setReasoningText(""); setStreamItems([]);
      setStreamingMapData(null); mapDataRef.current = null;
      abortRef.current = null; setChatLoading(false);
    }
  };

  const handleChatDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setChatDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handlePcapFile(file);
  };

  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || isChatLoading) return;

    setInput("");
    setChatLoading(true);
    setStreamingText("");
    setReasoningText("");
    setStreamItems([]);
    setFaithfulness(null);
    setRagSources([]);
    setStreamingMapData(null);
    mapDataRef.current = null;

    const controller = new AbortController();
    abortRef.current = controller;

    addChatMessage({ id: crypto.randomUUID(), role: "user", content: msg, timestamp: Date.now() });

    // Mutable accumulators (closures can't see React state updates)
    let reasoningAccum = "";
    let textAccum = "";

    try {
      // Mutable ref arrays for use inside closures
      const itemsRef: StreamItem[] = [];
      const toolCardsRef: ToolCard[] = [];

      const fullText = await sendChatMessage(
        msg,
        // onToken — plain LLM text
        (token) => {
          textAccum += token;
          setStreamingText((prev) => prev + token);
        },
        // onToolEvent — tool call, result, capture, or RAG events
        (ev: ToolEvent) => {
          if (ev.type === "reasoning") {
            reasoningAccum += ev.token;
            setReasoningText(reasoningAccum);
            return;
          }

          if (ev.type === "faithfulness") {
            setFaithfulness(ev.score);
          } else if (ev.type === "rag_sources") {
            setRagSources(ev.sources);
          } else if (ev.type === "open_tab") {
            // Auto-navigate to the requested tab (e.g. after traffic_map_summary)
            setActiveTab(ev.tab as Parameters<typeof setActiveTab>[0]);
          } else if (ev.type === "traffic_map_data") {
            mapDataRef.current = ev.data;
            setStreamingMapData(ev.data);
          } else if (ev.type === "call") {
            const card: ToolCard = { name: ev.name, args: ev.args };
            toolCardsRef.push(card);
            itemsRef.push({ kind: "tool", card });
            setStreamItems([...itemsRef]);
          } else if (ev.type === "result") {
            // Attach result to last tool card without output
            for (let i = toolCardsRef.length - 1; i >= 0; i--) {
              if (toolCardsRef[i].output === undefined) {
                toolCardsRef[i].output = ev.output;
                break;
              }
            }
            setStreamItems([...itemsRef]);
          } else if (ev.type === "capture_start") {
            const captureData: CaptureCardData = {
              seconds: ev.seconds,
              elapsed: 0,
              done: false,
            };
            const itemIdx = itemsRef.length;
            itemsRef.push({ kind: "capture", data: captureData });
            setStreamItems([...itemsRef]);

            // Tick elapsed every second
            if (captureTimerRef.current) clearInterval(captureTimerRef.current);
            captureTimerRef.current = setInterval(() => {
              const item = itemsRef[itemIdx];
              if (item?.kind === "capture" && !item.data.done) {
                item.data = { ...item.data, elapsed: item.data.elapsed + 1 };
                setStreamItems([...itemsRef]);
              }
            }, 1000);
          } else if (ev.type === "capture_done") {
            if (captureTimerRef.current) {
              clearInterval(captureTimerRef.current);
              captureTimerRef.current = null;
            }
            // Mark the last capture item as done
            for (let i = itemsRef.length - 1; i >= 0; i--) {
              const capItem = itemsRef[i].kind === "capture"
                ? (itemsRef[i] as { kind: "capture"; data: CaptureCardData })
                : null;
              if (capItem && !capItem.data.done) {
                capItem.data = {
                  ...capItem.data,
                  done: true,
                  packetCount: ev.count,
                };
                break;
              }
            }
            setStreamItems([...itemsRef]);
          }
        },
        ragEnabled,
        useHyde,
        controller.signal,
        analysisContext || undefined,
      );

      // Inline map annotation (prepended if traffic_map_summary was called)
      const mapAnnotation = mapDataRef.current
        ? `<!-- netscope-map: ${JSON.stringify(mapDataRef.current)} -->\n`
        : "";

      // Compact tool annotation (Gemini-style — chips, not markdown blocks)
      const toolAnnotation = toolCardsRef.length
        ? `<!-- netscope-tools: ${JSON.stringify(
            toolCardsRef.map((c) => ({ name: c.name, args: c.args }))
          )} -->\n\n`
        : "";

      // Build reasoning details block for persisted message
      const reasoningBlock = reasoningAccum
        ? `<details><summary>Reasoning (${reasoningAccum.length} chars)</summary>\n\n${reasoningAccum}\n\n</details>\n\n`
        : "";

      addChatMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: mapAnnotation + toolAnnotation + reasoningBlock + fullText,
        timestamp: Date.now(),
      });
    } catch (e: unknown) {
      // Handle user-initiated abort gracefully
      if (e instanceof DOMException && e.name === "AbortError") {
        const partialText = textAccum || "(stopped by user)";
        const reasoningBlock = reasoningAccum
          ? `<details><summary>Reasoning (${reasoningAccum.length} chars)</summary>\n\n${reasoningAccum}\n\n</details>\n\n`
          : "";
        addChatMessage({
          id: crypto.randomUUID(),
          role: "assistant",
          content: reasoningBlock + partialText + "\n\n*(generation stopped)*",
          timestamp: Date.now(),
        });
      } else {
        const msg2 = e instanceof Error ? e.message : "Failed to get response from LLM.";
        addChatMessage({
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Error: ${msg2}`,
          timestamp: Date.now(),
        });
      }
    } finally {
      setStreamingText("");
      setReasoningText("");
      setStreamItems([]);
      setStreamingMapData(null);
      mapDataRef.current = null;
      abortRef.current = null;
      if (captureTimerRef.current) {
        clearInterval(captureTimerRef.current);
        captureTimerRef.current = null;
      }
      setChatLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && isChatLoading) {
      e.preventDefault();
      handleStop();
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── Insight quick-actions ──────────────────────────────────────────────────
  const INSIGHT_MODES = [
    { id: "general",  label: "General",  icon: Brain },
    { id: "security", label: "Security", icon: Shield },
    { id: "ics",      label: "ICS",      icon: Cpu },
    { id: "http",     label: "HTTP",     icon: Network },
    { id: "dns",      label: "DNS",      icon: ArrowLeftRight },
    { id: "tls",      label: "TLS",      icon: Timer },
  ] as const;

  const [insightLoading, setInsightLoading] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [restartError, setRestartError] = useState("");

  const handleInsight = async (mode: string) => {
    if (isChatLoading || insightLoading || packetsLength === 0) return;
    setInsightLoading(mode);
    const label = INSIGHT_MODES.find((m) => m.id === mode)?.label ?? mode;
    addChatMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: `Generate ${label} insight analysis`,
      timestamp: Date.now(),
    });
    try {
      const text = await generateInsight(mode);
      addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: text, timestamp: Date.now() });
    } catch {
      addChatMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Error: Failed to generate insight.",
        timestamp: Date.now(),
      });
    } finally {
      setInsightLoading(null);
    }
  };

  const handleClear = async () => {
    clearChat();
    await clearChatHistory().catch(() => {});
  };

  const handleRestart = async () => {
    if (restarting) return;
    setRestarting(true);
    setRestartError("");
    try {
      await restartBackend();
      // Re-sync thinking/autonomous/shell state after restart (resets to default false)
      getThinking().then((r) => setThinkingEnabled(r.enabled)).catch(() => {});
      getAutonomous().then((r) => setAutonomousEnabled(r.enabled)).catch(() => {});
      getShell().then((r) => setShellEnabled(r.enabled)).catch(() => {});
    } catch (e: unknown) {
      setRestartError(e instanceof Error ? e.message : "Restart failed.");
    } finally {
      setRestarting(false);
    }
  };

  const isStreaming = isChatLoading && (streamingText.length > 0 || streamItems.length > 0 || reasoningText.length > 0);
  const isWaiting = isChatLoading && !isStreaming;

  // Optimistically mark a capture card as done in the UI when the user
  // clicks Stop — the backend will also stop, and the capture_done event
  // will arrive shortly after to confirm.
  const handleStopCapture = (idx: number) => {
    setStreamItems((prev) => {
      const next = [...prev];
      const item = next[idx];
      if (item?.kind === "capture" && !item.data.done) {
        next[idx] = {
          kind: "capture",
          data: { ...item.data, done: true, packetCount: item.data.elapsed > 0 ? undefined : 0 },
        };
      }
      return next;
    });
    if (captureTimerRef.current) {
      clearInterval(captureTimerRef.current);
      captureTimerRef.current = null;
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface text-xs shrink-0">
        <div className="flex items-center gap-2 text-accent">
          <MessageSquare className="w-4 h-4" />
          <span className="font-semibold">Chat with your traffic</span>
          <span className="text-muted">— {packetsLength} packets in context</span>
          {ragEnabled && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-accent-subtle border border-accent-emphasis rounded text-[10px] text-accent-muted">
              <BookOpen className="w-2.5 h-2.5" />
              KB active
            </span>
          )}
          {faithfulness !== null && (
            <span
              className={`flex items-center gap-1 px-1.5 py-0.5 border rounded text-[10px] ${
                faithfulness >= 0.7
                  ? "bg-success-subtle border-success-emphasis text-success"
                  : faithfulness >= 0.5
                  ? "bg-warning-subtle border-warning text-warning"
                  : "bg-danger-subtle border-danger text-danger"
              }`}
            >
              {faithfulness >= 0.5 ? (
                <CheckCircle className="w-2.5 h-2.5" />
              ) : (
                <AlertTriangle className="w-2.5 h-2.5" />
              )}
              {faithfulness >= 0.7
                ? "High confidence"
                : faithfulness >= 0.5
                ? "Medium confidence"
                : "Low confidence"}
              {" "}({(faithfulness * 100).toFixed(0)}%)
            </span>
          )}
        </div>
        {/* Restart backend button */}
        <button
          onClick={handleRestart}
          disabled={restarting || isChatLoading}
          title="Restart the backend Python process"
          className="flex items-center gap-1 px-2 py-1 text-muted hover:text-foreground border border-border rounded text-xs transition-colors disabled:opacity-40"
        >
          <RotateCcw className={`w-3 h-3 ${restarting ? "animate-spin" : ""}`} />
          {restarting ? "Restarting…" : "Restart"}
        </button>
        <button
          onClick={handleClear}
          className="flex items-center gap-1 px-2 py-1 text-muted hover:text-danger border border-border rounded text-xs transition-colors"
        >
          <Trash2 className="w-3 h-3" />
          Clear
        </button>
      </div>

      {/* Messages — also a PCAP drop target */}
      <div
        className={`flex-1 overflow-auto px-4 py-4 relative transition-colors ${chatDragOver ? "bg-accent/5" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setChatDragOver(true); }}
        onDragLeave={() => setChatDragOver(false)}
        onDrop={handleChatDrop}
      >
        {/* Drop overlay */}
        {chatDragOver && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 border-2 border-dashed border-accent rounded bg-background/80 pointer-events-none">
            <FileSearch className="w-10 h-10 text-accent" />
            <p className="text-accent text-sm font-medium">Drop PCAP to analyze</p>
          </div>
        )}
        {chatMessages.length === 0 && !isChatLoading && (
          <div className="flex flex-col items-center gap-4 pt-8">
            <MessageSquare className="w-10 h-10 text-border" />
            <p className="text-muted text-sm">
              Ask about your traffic — or have the AI run a network tool
            </p>
            <div className="grid grid-cols-2 gap-2 w-full max-w-lg">
              {EXAMPLE_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="text-left px-3 py-2 text-xs text-muted border border-border rounded-lg hover:border-accent hover:text-foreground transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {chatMessages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {/* Active streaming bubble */}
        {isStreaming && (
          <StreamingBubble
            text={streamingText}
            reasoningText={reasoningText}
            streamItems={streamItems}
            onStopCapture={handleStopCapture}
            mapData={streamingMapData}
          />
        )}

        {/* Waiting spinner (before first token or tool event) */}
        {isWaiting && (
          <div className="flex gap-2.5 mb-4">
            <div className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center bg-purple-emphasis">
              <Bot className="w-3.5 h-3.5" />
            </div>
            <div className="px-3 py-2 text-xs bg-surface border border-border rounded-lg">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-purple" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-border p-3 bg-surface">
        {/* Toggle pills */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <button
            onClick={() => setRagEnabled(!ragEnabled)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-colors ${
              ragEnabled
                ? "bg-accent-subtle border-accent-emphasis text-accent-muted"
                : "bg-transparent border-border text-muted hover:border-accent hover:text-foreground"
            }`}
          >
            <BookOpen className="w-2.5 h-2.5" />
            Knowledge Base
          </button>
          {ragEnabled && (
            <button
              onClick={() => setUseHyde(!useHyde)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-colors ${
                useHyde
                  ? "bg-purple-subtle border-purple-emphasis text-purple"
                  : "bg-transparent border-border text-muted hover:border-purple-emphasis hover:text-foreground"
              }`}
            >
              <Zap className="w-2.5 h-2.5" />
              HyDE
            </button>
          )}
          {/* Thinking toggle — passes think:true/false to Ollama-compatible models */}
          <button
            onClick={async () => {
              const next = !thinkingEnabled;
              setThinkingEnabled(next);
              try { await setThinking(next); } catch { setThinkingEnabled(!next); }
            }}
            title={thinkingEnabled ? "Extended reasoning ON — click to disable" : "Enable extended reasoning (requires a thinking-capable model like Qwen3 or DeepSeek-R1)"}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-all ${
              thinkingEnabled
                ? "bg-purple-subtle border-purple-emphasis text-purple"
                : "bg-transparent border-border text-muted hover:border-purple-emphasis hover:text-foreground"
            }`}
          >
            <Brain className="w-2.5 h-2.5" />
            Think
            <span className={`text-[9px] font-bold tracking-wide ${thinkingEnabled ? "text-purple" : "opacity-50"}`}>
              {thinkingEnabled ? "ON" : "OFF"}
            </span>
            {thinkingEnabled && (
              <span className="w-1 h-1 rounded-full bg-purple-emphasis animate-pulse" />
            )}
          </button>
          {/* Autonomous mode toggle */}
          <button
            onClick={async () => {
              const next = !autonomousEnabled;
              setAutonomousEnabled(next);
              try { await setAutonomous(next); } catch { setAutonomousEnabled(!next); }
            }}
            title={autonomousEnabled ? "Autonomous mode ON — agent can chain up to 20 tool calls" : "Enable autonomous mode for multi-step goal pursuit"}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-all ${
              autonomousEnabled
                ? "bg-success-subtle border-success text-success"
                : "bg-transparent border-border text-muted hover:border-success hover:text-foreground"
            }`}
          >
            <Zap className="w-2.5 h-2.5" />
            Auto
            <span className={`text-[9px] font-bold tracking-wide ${autonomousEnabled ? "text-success" : "opacity-50"}`}>
              {autonomousEnabled ? "ON" : "OFF"}
            </span>
            {autonomousEnabled && (
              <span className="w-1 h-1 rounded-full bg-success animate-pulse" />
            )}
          </button>
          {/* Shell mode toggle — enables exec without full autonomous mode */}
          <button
            onClick={async () => {
              const next = !shellEnabled;
              setShellEnabled(next);
              try { await setShell(next); } catch { setShellEnabled(!next); }
            }}
            title={shellEnabled ? "Shell mode ON — exec tool enabled, can run shell commands" : "Enable shell mode to run arbitrary shell commands"}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-all ${
              shellEnabled
                ? "bg-warning-subtle border-warning text-warning"
                : "bg-transparent border-border text-muted hover:border-warning hover:text-foreground"
            }`}
          >
            <Terminal className="w-2.5 h-2.5" />
            Shell
            <span className={`text-[9px] font-bold tracking-wide ${shellEnabled ? "text-warning" : "opacity-50"}`}>
              {shellEnabled ? "ON" : "OFF"}
            </span>
            {shellEnabled && (
              <span className="w-1 h-1 rounded-full bg-warning animate-pulse" />
            )}
          </button>
        </div>
        {/* Expert analysis quick-action when PCAP is loaded */}
        {loadedPcap && !isChatLoading && (
          <div className="flex items-center gap-1.5 mb-2">
            <span className="text-[10px] text-muted">Quick:</span>
            <button
              onClick={runExpertAnalysis}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border border-accent-emphasis bg-accent-subtle/30 text-accent-muted hover:bg-accent-subtle/60 transition-colors"
            >
              <FileSearch className="w-2.5 h-2.5" />
              Expert Analysis (TOON)
            </button>
          </div>
        )}

        {/* Insight quick-actions */}
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <span className="text-[10px] text-muted mr-1">Insights:</span>
          {INSIGHT_MODES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => handleInsight(id)}
              disabled={!!insightLoading || isChatLoading || packetsLength === 0}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-colors ${
                insightLoading === id
                  ? "bg-purple-subtle border-purple text-purple"
                  : "bg-transparent border-border text-muted hover:border-purple hover:text-foreground"
              } disabled:opacity-40`}
            >
              {insightLoading === id ? (
                <Loader2 className="w-2.5 h-2.5 animate-spin" />
              ) : (
                <Icon className="w-2.5 h-2.5" />
              )}
              {label}
            </button>
          ))}
          {/* Traffic Map separator + quick-action */}
          <span className="text-border mx-0.5">|</span>
          <button
            onClick={() => setInput("Show me the traffic map — analyze the hosts and flows")}
            disabled={isChatLoading || packetsLength === 0}
            title="Ask the AI to summarize the traffic topology and open the Traffic Map tab"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border transition-colors bg-transparent border-border text-muted hover:border-accent hover:text-foreground disabled:opacity-40"
          >
            <GitFork className="w-2.5 h-2.5" />
            Traffic Map
          </button>
        </div>
        {/* Loaded PCAP badge */}
        {loadedPcap && (
          <div className="flex items-center gap-2 mb-2 px-2 py-1 rounded bg-accent-subtle/30 border border-accent-emphasis/50 text-[10px] text-accent-muted w-fit">
            <FileSearch className="w-3 h-3 shrink-0" />
            <span className="font-mono">{loadedPcap.name}</span>
            <span className="text-muted-dim">·</span>
            <span>{loadedPcap.packets.toLocaleString()} pkts</span>
            <button
              onClick={() => setLoadedPcap(null)}
              className="ml-1 text-muted-dim hover:text-danger transition-colors"
              title="Clear"
            >
              <X className="w-2.5 h-2.5" />
            </button>
          </div>
        )}
        {pcapError && (
          <p className="text-[10px] text-danger mb-1">{pcapError}</p>
        )}
        {restartError && (
          <p className="text-[10px] text-danger mb-1">{restartError}</p>
        )}

        {/* Hidden PCAP file input */}
        <input
          ref={pcapInputRef}
          type="file"
          accept=".pcap,.pcapng,.cap"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handlePcapFile(f);
            e.target.value = "";
          }}
        />

        <div className="flex gap-2 items-end">
          {/* Paperclip button */}
          <button
            onClick={() => pcapInputRef.current?.click()}
            disabled={pcapUploading || isChatLoading}
            title="Attach PCAP file"
            className="flex items-center justify-center w-8 h-8 border border-border text-muted hover:border-accent hover:text-accent disabled:opacity-40 rounded-lg transition-colors shrink-0"
          >
            {pcapUploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Paperclip className="w-3.5 h-3.5" />}
          </button>

          <textarea
            id="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isChatLoading}
            placeholder={
              loadedPcap
                ? `PCAP loaded — ask about ${loadedPcap.name} or just send to run expert analysis…`
                : ragEnabled
                ? "Ask about Wireshark or PAN-OS — answers grounded in your knowledge base…"
                : "Ask about your traffic, or drop a .pcap here to analyze…"
            }
            rows={2}
            className="flex-1 bg-background border border-border text-foreground text-xs rounded-lg px-3 py-2 resize-none focus:outline-none focus:border-accent disabled:opacity-50 placeholder-muted-dim"
          />
          {isChatLoading ? (
            <button
              onClick={handleStop}
              className="flex items-center justify-center w-8 h-8 bg-danger-emphasis hover:bg-danger text-white rounded-lg transition-colors shrink-0"
              title="Stop generation"
            >
              <Square className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex items-center justify-center w-8 h-8 bg-success-emphasis hover:bg-success-emphasis-hover disabled:opacity-50 text-white rounded-lg transition-colors shrink-0"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        {ragEnabled && ragSources.length > 0 && (
          <div className="mt-2 text-[10px] text-muted">
            <span className="text-purple-emphasis">Sources: </span>
            {ragSources.map((s, i) => (
              <span key={i} className="mr-2">
                [{i + 1}] {s.source}{s.page != null ? ` p.${s.page}` : ""}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
