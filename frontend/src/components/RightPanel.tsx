import { useCallback, useEffect, useRef, useState } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import {
  sendChatMessage,
  generateInsight,
  generateInsightStream,
  fetchCurrentCaptureFile,
  runDeepAnalysis,
  streamNarrative,
  buildAnalysisContext,
} from "../lib/api";
import { MarkdownContent } from "./MarkdownContent";
import { AnalysisStrip } from "./AnalysisStrip";
import { TokenCounter } from "./TokenCounter";
import {
  Zap, Microscope, MessageSquare, Send, Loader2,
  Paperclip, Image, X, StopCircle,
} from "lucide-react";
import type { DeepAnalysisReport } from "../store/useStore";

// ── Suggested prompt chips ────────────────────────────────────────────────────

const STATIC_CHIPS = ["Follow stream 0", "Top talkers?", "Show retransmissions"];

function getChipsFromReport(report: DeepAnalysisReport | null): string[] {
  if (!report) return STATIC_CHIPS;
  const { latency, io_timeline } = report;
  const burst = io_timeline.find((b) => b.burst);
  return [
    "Why are there so many retransmissions?",
    `The ${latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?`,
    "Walk me through stream 0",
    burst
      ? `What caused the burst at t=${burst.t}s?`
      : "Describe the traffic pattern over time.",
  ];
}

// ── Image helpers ─────────────────────────────────────────────────────────────

/** Convert a File to a base64 data-URL */
function fileToDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const MAX_IMAGES = 4;

// ── Image thumbnail strip ─────────────────────────────────────────────────────

function ImageStrip({
  images,
  onRemove,
}: {
  images: string[];
  onRemove: (index: number) => void;
}) {
  if (!images.length) return null;
  return (
    <div className="flex gap-1.5 flex-wrap px-3 pt-2">
      {images.map((src, i) => (
        <div key={i} className="relative group shrink-0">
          <img
            src={src}
            alt={`attachment ${i + 1}`}
            className="w-14 h-14 object-cover rounded border border-border"
          />
          <button
            onClick={() => onRemove(i)}
            className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-surface-active
                       border border-border flex items-center justify-center
                       opacity-0 group-hover:opacity-100 transition-opacity"
            aria-label="Remove image"
          >
            <X className="w-2.5 h-2.5 text-foreground" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ── Chat thread ───────────────────────────────────────────────────────────────

function ChatThread() {
  const {
    chatMessages, isChatLoading, analysisReport, analysisContext, chatPrefill,
    clearChatPrefill, addChatMessage, setChatLoading, setChatPrefill,
  } = useStore(useShallow((s) => ({
    chatMessages: s.chatMessages,
    isChatLoading: s.isChatLoading,
    analysisReport: s.analysisReport,
    analysisContext: s.analysisContext,
    chatPrefill: s.chatPrefill,
    clearChatPrefill: s.clearChatPrefill,
    addChatMessage: s.addChatMessage,
    setChatLoading: s.setChatLoading,
    setChatPrefill: s.setChatPrefill,
  })));

  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pcapInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const streamingContentRef = useRef<string>("");

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Prefill from chips / deep analysis
  useEffect(() => {
    if (chatPrefill) {
      setInput(chatPrefill);
      clearChatPrefill();
      textareaRef.current?.focus();
    }
  }, [chatPrefill, clearChatPrefill]);

  // ── Image add helpers ─────────────────────────────────────────────────────

  const addImages = useCallback(async (files: FileList | File[]) => {
    const arr = Array.from(files).filter((f) => ACCEPTED_IMAGE_TYPES.includes(f.type));
    if (!arr.length) return;
    const remaining = MAX_IMAGES - pendingImages.length;
    const toAdd = arr.slice(0, remaining);
    const dataURLs = await Promise.all(toAdd.map(fileToDataURL));
    setPendingImages((prev) => [...prev, ...dataURLs].slice(0, MAX_IMAGES));
  }, [pendingImages.length]);

  const removeImage = useCallback((index: number) => {
    setPendingImages((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // ── Paste handler (Ctrl+V image) ──────────────────────────────────────────

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const imageItems = items.filter((item) => ACCEPTED_IMAGE_TYPES.includes(item.type));
    if (!imageItems.length) return;
    e.preventDefault();
    const files = imageItems
      .map((item) => item.getAsFile())
      .filter((f): f is File => f !== null);
    await addImages(files);
  }, [addImages]);

  // ── Drag-and-drop handlers ────────────────────────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => setIsDragging(false), []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length) await addImages(files);
  }, [addImages]);

  // ── Send ──────────────────────────────────────────────────────────────────

  const send = async (text: string, images: string[]) => {
    const msg = text.trim();
    if ((!msg && !images.length) || isChatLoading) return;
    setInput("");
    setPendingImages([]);

    // Add user message immediately
    const userMsgId = crypto.randomUUID();
    addChatMessage({
      id: userMsgId,
      role: "user",
      content: msg,
      images: images.length ? images : undefined,
      timestamp: Date.now() / 1000,
    });

    // Create assistant placeholder for streaming
    const assistantId = crypto.randomUUID();
    addChatMessage({ id: assistantId, role: "assistant", content: "", timestamp: Date.now() / 1000 });
    setStreamingId(assistantId);
    streamingContentRef.current = "";
    setChatLoading(true);

    abortRef.current = new AbortController();

    try {
      const context = analysisContext || undefined;
      await sendChatMessage(
        msg,
        // onToken — stream tokens into the assistant bubble
        (token) => {
          streamingContentRef.current += token;
          useStore.setState((s) => ({
            chatMessages: s.chatMessages.map((m) =>
              m.id === assistantId
                ? { ...m, content: streamingContentRef.current }
                : m
            ),
          }));
        },
        undefined,
        false,
        false,
        abortRef.current.signal,
        context,
        images.length ? images : undefined,
      );
    } catch (e: unknown) {
      const errMsg = e instanceof Error ? e.message : "Failed to get response";
      const isAbort = errMsg.includes("abort") || errMsg.includes("AbortError");
      if (!isAbort) {
        useStore.setState((s) => ({
          chatMessages: s.chatMessages.map((m) =>
            m.id === assistantId
              ? { ...m, content: streamingContentRef.current || `Error: ${errMsg}` }
              : m
          ),
        }));
      }
    } finally {
      setStreamingId(null);
      setChatLoading(false);
      abortRef.current = null;
    }
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  const chips = getChipsFromReport(analysisReport);

  return (
    <div
      className={`flex flex-col h-full overflow-hidden transition-colors ${
        isDragging ? "bg-accent/5" : ""
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <AnalysisStrip />

      {/* Token counter */}
      <div className="flex items-center justify-center px-2 py-1.5 border-b border-border shrink-0">
        <TokenCounter />
      </div>

      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
          <div className="bg-accent/10 border-2 border-dashed border-accent rounded-lg px-6 py-3">
            <span className="text-accent text-sm font-medium">Drop image here</span>
          </div>
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2 relative">
        {chatMessages.length === 0 && (
          <div className="text-center py-8 space-y-1">
            <p className="text-muted text-xs">Ask anything about the captured traffic.</p>
            <p className="text-muted-dim text-[10px]">
              Paste or drag images — Gemma4 can see them.
            </p>
          </div>
        )}

        {chatMessages.map((msg) => (
          <div key={msg.id} className={`text-xs ${msg.role === "user" ? "flex justify-end" : ""}`}>
            {msg.role === "assistant" ? (
              <div className="bg-surface border-l-2 border-accent rounded px-3 py-2">
                <div className="text-[10px] text-muted font-mono mb-1">⬡ NETSCOPE</div>
                {msg.content ? (
                  <MarkdownContent>{msg.content}</MarkdownContent>
                ) : (
                  // Empty placeholder while first tokens arrive
                  <span className="inline-block w-1.5 h-3.5 bg-accent/70 animate-pulse rounded-sm" />
                )}
                {streamingId === msg.id && (
                  <span className="inline-block w-1.5 h-3.5 bg-accent/70 animate-pulse rounded-sm ml-0.5 align-middle" />
                )}
              </div>
            ) : (
              <div className="bg-accent/20 text-foreground rounded px-3 py-2 max-w-[85%] space-y-1.5">
                {/* Attached images in user bubble */}
                {msg.images && msg.images.length > 0 && (
                  <div className="flex gap-1 flex-wrap">
                    {msg.images.map((src, i) => (
                      <img
                        key={i}
                        src={src}
                        alt={`image ${i + 1}`}
                        className="w-20 h-20 object-cover rounded border border-accent/30"
                      />
                    ))}
                  </div>
                )}
                {msg.content && <div>{msg.content}</div>}
              </div>
            )}
          </div>
        ))}

        {isChatLoading && !streamingId && (
          <div className="flex items-center gap-1.5 text-muted text-xs">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Prompt chips */}
      <div className="px-3 py-1 flex flex-wrap gap-1 border-t border-border shrink-0">
        {chips.map((chip) => (
          <button
            key={chip}
            onClick={() => setChatPrefill(chip)}
            className="px-2 py-0.5 bg-surface border border-border rounded text-[10px] text-muted hover:text-foreground hover:border-accent transition-colors"
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Image previews */}
      <ImageStrip images={pendingImages} onRemove={removeImage} />

      {/* Input row */}
      <div className="px-3 py-2 border-t border-border shrink-0">
        <div className="flex items-end gap-1.5">

          {/* Hidden file inputs */}
          <input
            ref={pcapInputRef}
            type="file"
            accept=".pcap,.pcapng"
            className="hidden"
            onChange={(e) => { e.target.value = ""; }}
          />
          <input
            ref={imageInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            className="hidden"
            onChange={async (e) => {
              if (e.target.files) await addImages(e.target.files);
              e.target.value = "";
            }}
          />

          {/* PCAP attach */}
          <button
            title="Attach PCAP"
            aria-label="Attach PCAP"
            onClick={() => pcapInputRef.current?.click()}
            className="text-muted hover:text-foreground transition-colors shrink-0 pb-1"
          >
            <Paperclip className="w-3.5 h-3.5" />
          </button>

          {/* Image attach (vision) */}
          <button
            title={`Attach image (max ${MAX_IMAGES})`}
            aria-label="Attach image"
            onClick={() => imageInputRef.current?.click()}
            disabled={pendingImages.length >= MAX_IMAGES}
            className={`transition-colors shrink-0 pb-1 ${
              pendingImages.length >= MAX_IMAGES
                ? "text-muted-dim cursor-not-allowed"
                : "text-muted hover:text-accent"
            }`}
          >
            <Image className="w-3.5 h-3.5" />
          </button>

          {/* Message textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                send(input, pendingImages);
              }
            }}
            onPaste={handlePaste}
            placeholder={pendingImages.length ? "Describe the image… (optional)" : "Ask about the traffic… (Ctrl+Enter to send)"}
            rows={1}
            className="flex-1 bg-surface border border-border rounded px-2 py-1.5 text-xs text-foreground placeholder-muted resize-none focus:outline-none focus:border-accent"
            style={{ maxHeight: "5rem", overflowY: "auto" }}
          />

          {/* Stop / Send */}
          {isChatLoading ? (
            <button
              onClick={stop}
              aria-label="Stop generation"
              title="Stop"
              className="text-danger hover:text-danger/80 transition-colors shrink-0 pb-1"
            >
              <StopCircle className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              onClick={() => send(input, pendingImages)}
              disabled={!input.trim() && !pendingImages.length}
              aria-label="Send"
              className="text-accent hover:text-accent-muted disabled:opacity-30 transition-colors shrink-0 pb-1"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Image count hint */}
        {pendingImages.length > 0 && (
          <p className="text-[10px] text-muted mt-1 ml-8">
            {pendingImages.length}/{MAX_IMAGES} image{pendingImages.length > 1 ? "s" : ""} attached
            · Ctrl+Enter to send
          </p>
        )}
      </div>
    </div>
  );
}

// ── Quick tab ─────────────────────────────────────────────────────────────────

function QuickTab() {
  const [result, setResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    setResult("");
    try {
      let full = "";
      await generateInsightStream("quick", (token) => {
        full += token;
        setResult(full);
      });
    } catch (e: unknown) {
      setResult(`Error: ${e instanceof Error ? e.message : "Failed"}`);
    } finally {
      setLoading(false);
    }
  };

  if (!result && !loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <button
          onClick={run}
          className="flex items-center gap-2 px-4 py-2 bg-accent text-white rounded text-sm font-medium hover:bg-accent-emphasis transition-colors"
        >
          <Zap className="w-4 h-4" /> Run Quick Analysis
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border shrink-0">
        <span className="text-xs text-muted">Quick Analysis</span>
        <button onClick={run} disabled={loading} className="text-xs text-accent hover:underline disabled:opacity-50">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Re-run"}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs">
        {result && <MarkdownContent>{result}</MarkdownContent>}
        {loading && !result && (
          <div className="space-y-3 animate-pulse mt-2">
            <div className="flex items-center gap-2 text-muted mb-4">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Analyzing traffic...</span>
            </div>
            <div className="h-4 w-3/4 bg-border/50 rounded" />
            <div className="h-4 w-full bg-border/30 rounded" />
            <div className="h-4 w-5/6 bg-border/30 rounded" />
            <div className="h-4 w-1/2 bg-border/30 rounded" />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Deep tab ──────────────────────────────────────────────────────────────────

function DeepTab() {
  const [loading, setLoading] = useState(false);
  const [narrative, setNarrative] = useState<string | null>(null);
  const { analysisReport, setAnalysisReport, setChatPrefill } = useStore(
    useShallow((s) => ({
      analysisReport: s.analysisReport,
      setAnalysisReport: s.setAnalysisReport,
      setChatPrefill: s.setChatPrefill,
    }))
  );

  const run = async () => {
    setLoading(true);
    setNarrative(null);
    try {
      const captureFileInfo = await fetchCurrentCaptureFile();
      const report: DeepAnalysisReport = await runDeepAnalysis(captureFileInfo.file ?? undefined);
      const ctx = buildAnalysisContext(report);
      setAnalysisReport(report, ctx);
      let full = "";
      await streamNarrative((token) => {
        full += token;
        setNarrative(full);
      });
    } catch (e: unknown) {
      setNarrative(`Error: ${e instanceof Error ? e.message : "Deep analysis failed"}`);
    } finally {
      setLoading(false);
    }
  };

  if (!analysisReport && !loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <button
          onClick={run}
          className="flex items-center gap-2 px-4 py-2 bg-purple/20 text-purple border border-purple/30 rounded text-sm font-medium hover:bg-purple/30 transition-colors"
        >
          <Microscope className="w-4 h-4" /> Run Deep Analysis
        </button>
      </div>
    );
  }

  if (loading && !analysisReport) {
    return (
      <div className="flex flex-col h-full overflow-hidden p-3 space-y-3">
        <div className="animate-pulse flex gap-2 items-center text-muted text-xs mb-2">
          <Loader2 className="w-3 h-3 animate-spin" /> Running deep analysis…
        </div>
        <div className="border border-border rounded p-2 space-y-2">
          <div className="h-4 w-24 bg-border/50 rounded animate-pulse" />
          <div className="grid grid-cols-2 gap-2">
            <div className="h-3 w-full bg-border/30 rounded animate-pulse" />
            <div className="h-3 w-full bg-border/30 rounded animate-pulse" />
            <div className="h-3 w-full bg-border/30 rounded animate-pulse" />
            <div className="h-3 w-full bg-border/30 rounded animate-pulse" />
          </div>
        </div>
        <div className="border border-border rounded p-2 space-y-2">
          <div className="h-4 w-20 bg-border/50 rounded animate-pulse" />
          <div className="h-3 w-full bg-border/30 rounded animate-pulse" />
        </div>
        <div className="border border-border rounded p-2 space-y-2">
          <div className="h-4 w-28 bg-border/50 rounded animate-pulse" />
          <div className="h-3 w-full bg-border/30 rounded animate-pulse" />
          <div className="h-3 w-3/4 bg-border/30 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  const r = analysisReport!;
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border shrink-0">
        <span className="text-xs text-muted">Deep Analysis</span>
        <button onClick={run} disabled={loading} className="text-xs text-accent hover:underline disabled:opacity-50">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Re-run"}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs space-y-3">
        <div className="border border-border rounded p-2">
          <div className="font-medium text-foreground mb-1">TCP Health</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-muted">
            <span>Retransmissions: <b className="text-foreground">{r.tcp_health.retransmissions}</b></span>
            <span>Zero windows: <b className="text-foreground">{r.tcp_health.zero_windows}</b></span>
            <span>Out-of-order: <b className="text-foreground">{r.tcp_health.out_of_order}</b></span>
            <span>RSTs: <b className="text-foreground">{r.tcp_health.rsts}</b></span>
            <span>RTT avg: <b className="text-foreground">{r.tcp_health.rtt_avg_ms}ms</b></span>
          </div>
          <button onClick={() => setChatPrefill("Why are there so many retransmissions?")}
            className="mt-1 text-[10px] text-accent hover:underline">Ask in chat →</button>
        </div>
        <div className="border border-border rounded p-2">
          <div className="font-medium text-foreground mb-1">Latency</div>
          <div className="text-muted">
            Bottleneck: <b className="text-foreground">{r.latency.aggregate.bottleneck}</b> ·
            Network RTT: <b className="text-foreground">{r.latency.aggregate.network_rtt_ms}ms</b> ·
            Server: <b className="text-foreground">{r.latency.aggregate.server_ms}ms</b>
          </div>
          <button onClick={() => setChatPrefill(`The ${r.latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?`)}
            className="mt-1 text-[10px] text-accent hover:underline">Ask in chat →</button>
        </div>
        <div className="border border-border rounded p-2">
          <div className="font-medium text-foreground mb-1">Streams ({r.streams.length})</div>
          {r.streams.slice(0, 5).map((s) => (
            <div key={s.stream_id} className="text-muted text-[10px]">
              [{s.stream_id}] {s.src} → {s.dst} · {s.protocol} · {s.packets}pkts
            </div>
          ))}
          <button onClick={() => setChatPrefill("Walk me through stream 0")}
            className="mt-1 text-[10px] text-accent hover:underline">Ask in chat →</button>
        </div>
        {r.expert_info.available && r.expert_info.counts && (
          <div className="border border-border rounded p-2">
            <div className="font-medium text-foreground mb-1">Expert Info</div>
            <div className="text-muted">
              Errors: {r.expert_info.counts.error} · Warnings: {r.expert_info.counts.warning} · Notes: {r.expert_info.counts.note}
            </div>
            <button onClick={() => setChatPrefill("What do the TCP warnings mean?")}
              className="mt-1 text-[10px] text-accent hover:underline">Ask in chat →</button>
          </div>
        )}
        {narrative && (
          <div className="border border-border rounded p-2">
            <div className="font-medium text-foreground mb-1">Narrative</div>
            <MarkdownContent>{narrative}</MarkdownContent>
          </div>
        )}
        {loading && (
          <div className="flex items-center gap-1.5 text-muted text-xs">
            <Loader2 className="w-3 h-3 animate-spin" /> Generating narrative…
          </div>
        )}
      </div>
    </div>
  );
}

// ── RightPanel ────────────────────────────────────────────────────────────────

export function RightPanel() {
  const { rightPanelTab, setRightPanelTab, isCapturing, packets, addChatMessage } =
    useStore(useShallow((s) => ({
      rightPanelTab: s.rightPanelTab,
      setRightPanelTab: s.setRightPanelTab,
      isCapturing: s.isCapturing,
      packets: s.packets,
      addChatMessage: s.addChatMessage,
    })));

  const wasCapturingRef = useRef(isCapturing);
  useEffect(() => {
    const wasCap = wasCapturingRef.current;
    wasCapturingRef.current = isCapturing;
    if (wasCap && !isCapturing && packets.length > 0) {
      generateInsight("general")
        .then((text) => {
          addChatMessage({
            id: crypto.randomUUID(),
            role: "assistant",
            content: text,
            timestamp: Date.now() / 1000,
          });
        })
        .catch(() => {});
    }
  }, [isCapturing, packets, addChatMessage]);

  const tabs = [
    { id: "chat"  as const, icon: MessageSquare, label: "Chat"  },
    { id: "quick" as const, icon: Zap,           label: "Quick" },
    { id: "deep"  as const, icon: Microscope,    label: "Deep"  },
  ];

  return (
    <div className="flex flex-col w-full border-l border-border bg-background h-full overflow-hidden">
      {/* Token counter bar */}
      <div className="flex items-center justify-center px-2 py-1.5 border-b border-border shrink-0">
        <TokenCounter />
      </div>

      <div className="flex border-b border-border shrink-0">
        {tabs.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => setRightPanelTab(id)}
            className={`flex items-center gap-1.5 flex-1 justify-center py-2 text-xs font-medium transition-colors ${
              rightPanelTab === id
                ? "text-accent border-b-2 border-accent"
                : "text-muted hover:text-foreground"
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden">
        {rightPanelTab === "chat"  && <ChatThread />}
        {rightPanelTab === "quick" && <QuickTab />}
        {rightPanelTab === "deep"  && <DeepTab />}
      </div>
    </div>
  );
}
