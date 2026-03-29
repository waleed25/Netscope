import { useEffect, useRef, useState } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import {
  fetchInsights,
  generateInsightStream,
  fetchCurrentCaptureFile,
  sendChatMessage,
  runDeepAnalysis,
  streamNarrative,
  buildAnalysisContext,
} from "../lib/api";
import type { DeepAnalysisReport } from "../store/useStore";
import { Brain, RefreshCw, Loader2, Clock, HardDrive, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { MarkdownContent } from "./MarkdownContent";
import type { Insight } from "../store/useStore";

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function InsightCard({ insight }: { insight: Insight }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="border border-border rounded-lg overflow-hidden mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface hover:bg-surface-hover text-xs"
      >
        <div className="flex items-center gap-2">
          <Brain className="w-3.5 h-3.5 text-purple" />
          <span className="text-foreground font-medium capitalize">{insight.source} Insight</span>
        </div>
        <div className="flex items-center gap-2 text-muted">
          <Clock className="w-3 h-3" />
          <span>{formatTimestamp(insight.timestamp)}</span>
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </div>
      </button>
      {expanded && (
        <div className="px-4 py-3 bg-background">
          <MarkdownContent>{insight.text}</MarkdownContent>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  title,
  children,
  onAskInChat,
}: {
  title: string;
  children: React.ReactNode;
  onAskInChat?: () => void;
}) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="border border-border rounded-lg overflow-hidden mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface hover:bg-surface-hover text-xs"
      >
        <span className="text-foreground font-medium">{title}</span>
        <div className="flex items-center gap-2">
          {onAskInChat && (
            <span
              className="text-blue-400 hover:text-blue-300 text-[10px] font-medium"
              onClick={(e) => {
                e.stopPropagation();
                onAskInChat();
              }}
            >
              Ask in chat →
            </span>
          )}
          {expanded ? (
            <ChevronDown className="w-3 h-3 text-muted" />
          ) : (
            <ChevronRight className="w-3 h-3 text-muted" />
          )}
        </div>
      </button>
      {expanded && <div className="px-4 py-3 bg-background text-xs">{children}</div>}
    </div>
  );
}

const MODES = [
  { id: "general",  label: "General"  },
  { id: "security", label: "Security" },
  { id: "ics",      label: "ICS"      },
  { id: "http",     label: "HTTP"     },
  { id: "dns",      label: "DNS"      },
  { id: "tls",      label: "TLS"      },
  { id: "quick",    label: "⚡ Quick" },
  { id: "deep",     label: "🔬 Deep"  },
] as const;

export function InsightPanel() {
  const { insights, addInsight, clearInsights, llmStatus, setAnalysisReport, analysisContext, setChatPrefill } = useStore(
    useShallow((s) => ({
      insights: s.insights,
      addInsight: s.addInsight,
      clearInsights: s.clearInsights,
      llmStatus: s.llmStatus,
      setAnalysisReport: s.setAnalysisReport,
      analysisContext: s.analysisContext,
      setChatPrefill: s.setChatPrefill,
    }))
  );
  const packetsLength = useStore((s) => s.totalPackets);
  const modelName = llmStatus?.model?.split(":")[0] || "LLM";

  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState("");
  const [selectedMode, setSelectedMode] = useState<string>("general");
  const [captureFile, setCaptureFile] = useState<{ name: string | null; size_bytes: number }>({
    name: null, size_bytes: 0,
  });
  const abortRef = useRef<AbortController | null>(null);

  // Deep mode state
  const [deepReport, setDeepReport] = useState<DeepAnalysisReport | null>(null);
  const [narrativeText, setNarrativeText] = useState("");
  const [deepLoading, setDeepLoading] = useState(false);
  const narrativeAbortRef = useRef<AbortController | null>(null);

  // Load existing insights from backend on mount
  useEffect(() => {
    fetchInsights()
      .then((ins) => ins.forEach((i) => addInsight(i)))
      .catch(() => {});
  }, []);

  // Poll current capture file info
  useEffect(() => {
    const poll = () =>
      fetchCurrentCaptureFile()
        .then((info) => setCaptureFile({ name: info.name, size_bytes: info.size_bytes }))
        .catch(() => {});
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  const handleDeepAnalysis = async () => {
    setDeepLoading(true);
    setDeepReport(null);
    setNarrativeText("");
    setError("");
    narrativeAbortRef.current?.abort();

    try {
      // captureFile is the existing useState polled above
      const report = await runDeepAnalysis(captureFile.name ?? undefined);
      setDeepReport(report);
      const ctx = buildAnalysisContext(report);
      setAnalysisReport(report, ctx);

      // Stream narrative
      narrativeAbortRef.current = new AbortController();
      await streamNarrative(
        (token) => setNarrativeText((prev) => prev + token),
        narrativeAbortRef.current.signal,
      );
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setError(e?.message || "Deep analysis failed");
      }
    } finally {
      setDeepLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (loading || packetsLength === 0) return;
    setLoading(true);
    setStreamText("");
    setError("");
    abortRef.current = new AbortController();

    // Deep mode is handled separately
    if (selectedMode === "deep") {
      setLoading(false);
      await handleDeepAnalysis();
      return;
    }

    try {
      let full: string;
      if (selectedMode === "quick") {
        // Route through chat/tool loop so Quick mode has access to all analysis tools
        const quickMessage =
          "Run a quick expert analysis of this capture. Use the tcp_health_check, " +
          "stream_follow, latency_analysis, io_graph, and expert_info tools. " +
          "Lead with the most significant finding.";
        full = await sendChatMessage(
          quickMessage,
          (token) => setStreamText((prev) => prev + token),
          undefined,
          false,
          false,
          abortRef.current.signal,
          analysisContext || undefined,
        );
      } else {
        full = await generateInsightStream(
          selectedMode,
          (token) => setStreamText((prev) => prev + token),
          abortRef.current.signal,
        );
      }
      addInsight({ text: full, source: selectedMode, timestamp: Date.now() / 1000 });
      setStreamText("");
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        const msg = e?.message || "Failed to generate insight";
        let displayMsg = msg;
        if (msg.startsWith("{")) {
          try {
            displayMsg = JSON.parse(msg)?.detail || "LLM error — check Ollama/LM Studio is running";
          } catch {
            displayMsg = "LLM error — check Ollama/LM Studio is running";
          }
        }
        setError(displayMsg);
      }
      setStreamText("");
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  const handleCancel = () => {
    abortRef.current?.abort();
    narrativeAbortRef.current?.abort();
  };

  const isRunning = loading || deepLoading;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-surface text-xs shrink-0">
        <div className="flex items-center gap-2 text-purple">
          <Brain className="w-4 h-4" />
          <span className="font-semibold">AI Insights</span>
          <span className="text-muted">· {modelName}</span>
        </div>
        {captureFile.name && (
          <div className="flex items-center gap-1 text-muted" title={captureFile.name}>
            <HardDrive className="w-3 h-3" />
            <span className="max-w-[120px] truncate">{captureFile.name}</span>
            <span>({formatBytes(captureFile.size_bytes)})</span>
          </div>
        )}
      </div>

      {/* Mode selector + Generate button */}
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-border bg-surface shrink-0 flex-wrap">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setSelectedMode(m.id)}
            disabled={isRunning}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors disabled:opacity-50 ${
              selectedMode === m.id
                ? "bg-purple-emphasis text-white"
                : "bg-border text-muted hover:text-foreground"
            }`}
          >
            {m.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1.5">
          {insights.length > 0 && !isRunning && (
            <button
              onClick={clearInsights}
              className="flex items-center gap-1 px-2.5 py-1 bg-surface border border-border hover:bg-surface-hover text-muted hover:text-danger text-xs rounded font-medium transition-colors"
              title="Clear all insights"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          )}
          {isRunning ? (
            <button
              onClick={handleCancel}
              className="flex items-center gap-1 px-2.5 py-1 bg-danger hover:bg-danger/80 text-white text-xs rounded font-medium"
            >
              <Loader2 className="w-3 h-3 animate-spin" /> Cancel
            </button>
          ) : (
            <button
              onClick={handleGenerate}
              disabled={packetsLength === 0}
              className="flex items-center gap-1 px-2.5 py-1 bg-purple-emphasis hover:bg-purple-emphasis-hover disabled:opacity-50 text-white text-xs rounded font-medium transition-colors"
            >
              <RefreshCw className="w-3 h-3" /> Generate
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-3 py-2 text-xs text-danger bg-danger/10 border-b border-danger/20 shrink-0">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-auto p-3">
        {/* Deep mode report cards */}
        {selectedMode === "deep" && deepReport && (
          <div>
            {/* TCP Health */}
            <MetricCard
              title={`🔴 TCP Health${deepReport.tcp_health.estimated ? " (estimated)" : ""}`}
              onAskInChat={() => setChatPrefill("Why are there so many retransmissions?")}
            >
              <div className="grid grid-cols-3 gap-2 mb-2">
                {(
                  [
                    ["Retransmissions", deepReport.tcp_health.retransmissions],
                    ["Zero Windows",    deepReport.tcp_health.zero_windows],
                    ["RSTs",            deepReport.tcp_health.rsts],
                    ["Dup ACKs",        deepReport.tcp_health.duplicate_acks],
                    ["Out of Order",    deepReport.tcp_health.out_of_order],
                    ["RTT avg",         `${deepReport.tcp_health.rtt_avg_ms}ms`],
                  ] as const
                ).map(([label, val]) => (
                  <div key={String(label)} className="bg-surface rounded p-1.5">
                    <div className="text-muted text-[10px]">{label}</div>
                    <div className="text-foreground font-mono font-semibold">{String(val)}</div>
                  </div>
                ))}
              </div>
              {deepReport.tcp_health.top_offenders.length > 0 && (
                <div className="text-muted mt-1">
                  Top: {deepReport.tcp_health.top_offenders[0].src} →{" "}
                  {deepReport.tcp_health.top_offenders[0].dst} (
                  {deepReport.tcp_health.top_offenders[0].retransmits} retransmits)
                </div>
              )}
            </MetricCard>

            {/* Latency Breakdown */}
            <MetricCard
              title="⏱ Latency Breakdown"
              onAskInChat={() =>
                setChatPrefill(
                  `The ${deepReport.latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?`
                )
              }
            >
              {(() => {
                const agg = deepReport.latency.aggregate;
                const total = agg.network_rtt_ms + agg.server_ms + agg.client_ms;
                return (
                  <div>
                    <div className="flex gap-1 h-4 rounded overflow-hidden mb-2">
                      {total > 0 && (
                        <>
                          <div
                            style={{ width: `${(agg.client_ms / total) * 100}%` }}
                            className="bg-blue-500/60 flex items-center justify-center text-[9px]"
                          >
                            C
                          </div>
                          <div
                            style={{ width: `${(agg.network_rtt_ms / total) * 100}%` }}
                            className="bg-yellow-500/60 flex items-center justify-center text-[9px]"
                          >
                            N
                          </div>
                          <div
                            style={{ width: `${(agg.server_ms / total) * 100}%` }}
                            className={`${
                              agg.bottleneck === "server" ? "bg-red-500/80" : "bg-green-500/60"
                            } flex items-center justify-center text-[9px]`}
                          >
                            S
                          </div>
                        </>
                      )}
                    </div>
                    <div className="flex gap-4 text-[10px] text-muted">
                      <span>Client: {agg.client_ms}ms</span>
                      <span>Network: {agg.network_rtt_ms}ms</span>
                      <span
                        className={
                          agg.bottleneck === "server" ? "text-red-400 font-semibold" : ""
                        }
                      >
                        Server: {agg.server_ms}ms {agg.bottleneck === "server" && "⚠"}
                      </span>
                    </div>
                  </div>
                );
              })()}
            </MetricCard>

            {/* Streams */}
            {deepReport.streams.length > 0 && (
              <MetricCard
                title={`🌊 Streams (${deepReport.streams.length})`}
                onAskInChat={() => setChatPrefill("Walk me through stream 0")}
              >
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-muted border-b border-border">
                        <th className="text-left py-1 pr-3">Src → Dst</th>
                        <th className="text-left py-1 pr-3">Proto</th>
                        <th className="text-right py-1 pr-3">Bytes</th>
                        <th className="text-right py-1">Pkts</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deepReport.streams.slice(0, 8).map((s) => (
                        <tr key={s.stream_id} className="border-b border-border/40">
                          <td className="py-1 pr-3 font-mono text-[9px] text-muted">
                            {s.src}
                            <br />→ {s.dst}
                          </td>
                          <td className="py-1 pr-3">{s.protocol}</td>
                          <td className="py-1 pr-3 text-right">{formatBytes(s.bytes)}</td>
                          <td className="py-1 text-right">{s.packets}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </MetricCard>
            )}

            {/* Expert Info */}
            {deepReport.expert_info.available && deepReport.expert_info.counts && (
              <MetricCard
                title="⚠ Expert Info"
                onAskInChat={() => setChatPrefill("What do the TCP warnings mean?")}
              >
                <div className="flex gap-4 text-[10px] mb-2">
                  {deepReport.expert_info.counts.error > 0 && (
                    <span className="text-red-400">
                      ✕ {deepReport.expert_info.counts.error} errors
                    </span>
                  )}
                  {deepReport.expert_info.counts.warning > 0 && (
                    <span className="text-yellow-400">
                      ⚠ {deepReport.expert_info.counts.warning} warnings
                    </span>
                  )}
                  {deepReport.expert_info.counts.note > 0 && (
                    <span className="text-blue-400">
                      ℹ {deepReport.expert_info.counts.note} notes
                    </span>
                  )}
                </div>
                {deepReport.expert_info.top?.slice(0, 5).map((item, i) => (
                  <div key={i} className="text-[10px] text-muted mb-0.5">
                    <span
                      className={
                        item.severity === "error"
                          ? "text-red-400"
                          : item.severity === "warning"
                          ? "text-yellow-400"
                          : "text-blue-400"
                      }
                    >
                      {item.severity}
                    </span>{" "}
                    {item.message} ×{item.count}
                  </div>
                ))}
              </MetricCard>
            )}

            {/* IO Timeline */}
            {deepReport.io_timeline.length > 0 && (
              <MetricCard
                title="📈 IO Timeline"
                onAskInChat={() => {
                  const burst = deepReport.io_timeline.find((b) => b.burst);
                  setChatPrefill(
                    burst
                      ? `What caused the burst at t=${burst.t.toFixed(1)}s?`
                      : "Describe the traffic pattern over time."
                  );
                }}
              >
                <div className="flex items-end gap-px h-12">
                  {deepReport.io_timeline.map((b, i) => {
                    const max = Math.max(
                      ...deepReport.io_timeline.map((x) => x.packets_per_sec)
                    );
                    const height = max > 0 ? Math.max(2, (b.packets_per_sec / max) * 100) : 2;
                    return (
                      <div
                        key={i}
                        title={`t=${b.t.toFixed(0)}s: ${b.packets_per_sec} pkt/s`}
                        style={{ height: `${height}%` }}
                        className={`flex-1 min-w-[2px] rounded-t ${
                          b.burst ? "bg-red-400" : "bg-blue-500/60"
                        }`}
                      />
                    );
                  })}
                </div>
                <div className="text-[10px] text-muted mt-1">
                  {deepReport.io_timeline.filter((b) => b.burst).length} burst(s) detected
                </div>
              </MetricCard>
            )}

            {/* Narrative */}
            <MetricCard title="📝 Analysis Narrative">
              {deepLoading && !narrativeText && (
                <div className="flex items-center gap-2 text-muted">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span>Generating narrative…</span>
                </div>
              )}
              {narrativeText && <MarkdownContent>{narrativeText}</MarkdownContent>}
            </MetricCard>
          </div>
        )}

        {/* Deep mode loading indicator (before report arrives) */}
        {selectedMode === "deep" && deepLoading && !deepReport && (
          <div className="border border-border rounded-lg overflow-hidden mb-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-surface">
              <Loader2 className="w-3.5 h-3.5 text-purple animate-spin" />
              <span className="text-foreground text-xs font-medium">
                Running deep analysis on {packetsLength.toLocaleString()} packets…
              </span>
            </div>
          </div>
        )}

        {/* Streaming live preview (Quick + other modes) */}
        {loading && streamText && selectedMode !== "deep" && (
          <div className="border border-purple/40 rounded-lg overflow-hidden mb-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-surface">
              <Loader2 className="w-3.5 h-3.5 text-purple animate-spin" />
              <span className="text-foreground text-xs font-medium capitalize">
                {selectedMode} analysis streaming…
              </span>
            </div>
            <div className="px-4 py-3 bg-background">
              <MarkdownContent>{streamText}</MarkdownContent>
            </div>
          </div>
        )}

        {/* Waiting for first token */}
        {loading && !streamText && selectedMode !== "deep" && (
          <div className="border border-border rounded-lg overflow-hidden mb-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-surface">
              <Loader2 className="w-3.5 h-3.5 text-purple animate-spin" />
              <span className="text-foreground text-xs font-medium">
                Analyzing {packetsLength.toLocaleString()} packets…
              </span>
            </div>
          </div>
        )}

        {/* Past insights */}
        {insights.map((insight, i) => (
          <InsightCard key={i} insight={insight} />
        ))}

        {/* Empty state */}
        {insights.length === 0 && !isRunning && !(selectedMode === "deep" && deepReport) && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-muted">
            <Brain className="w-10 h-10 opacity-20" />
            <p className="text-sm">No insights yet.</p>
            <p className="text-xs text-center">
              {packetsLength === 0
                ? "Capture traffic or upload a PCAP, then click Generate."
                : `${packetsLength.toLocaleString()} packets ready — select a mode and click Generate.`}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
