import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { ChevronDown, ChevronRight, CheckCircle } from "lucide-react";

function formatAge(ts: number): string {
  const secs = Math.floor((Date.now() / 1000) - ts);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

interface PillProps {
  label: string;
  color: string;
  onClick: () => void;
}
function Pill({ label, color, onClick }: PillProps) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-0.5 rounded text-[10px] font-medium transition-opacity hover:opacity-80 ${color}`}
    >
      {label}
    </button>
  );
}

export function AnalysisStrip() {
  const { analysisReport, analysisReportTs, analysisStripExpanded, setAnalysisStripExpanded, setChatPrefill, setRightPanelTab } =
    useStore(useShallow((s) => ({
      analysisReport: s.analysisReport,
      analysisReportTs: s.analysisReportTs,
      analysisStripExpanded: s.analysisStripExpanded,
      setAnalysisStripExpanded: s.setAnalysisStripExpanded,
      setChatPrefill: s.setChatPrefill,
      setRightPanelTab: s.setRightPanelTab,
    })));

  if (!analysisReport) return null;

  const { tcp_health, latency } = analysisReport;
  const ageTs = analysisReportTs > 0 ? analysisReportTs : Date.now() / 1000;

  const pills = [
    { label: `${tcp_health.retransmissions} retransmit`, color: "bg-red-900/60 text-red-300",    q: "Why are there so many retransmissions?" },
    { label: `${tcp_health.zero_windows} zero-win`,     color: "bg-amber-900/60 text-amber-300", q: "What is causing zero window events?" },
    { label: `${latency.aggregate.bottleneck} bottleneck`, color: "bg-purple-900/60 text-purple-300", q: `The ${latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?` },
    { label: `RTT ${tcp_health.rtt_avg_ms}ms`,          color: "bg-green-900/60 text-green-300", q: "What is the round-trip time telling us?" },
    { label: `${tcp_health.rsts} RSTs`,                 color: "bg-blue-900/60 text-blue-300",   q: "Why are there TCP RST packets?" },
  ];

  return (
    <div className="border-b border-border bg-surface shrink-0">
      {/* Header row */}
      <button
        onClick={() => setAnalysisStripExpanded(!analysisStripExpanded)}
        className="flex items-center gap-2 w-full px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors"
      >
        <CheckCircle className="w-3.5 h-3.5 text-success shrink-0" />
        <span className="text-foreground font-medium">Deep Analysis</span>
        <span className="text-muted">· {formatAge(ageTs)}</span>
        <span className="ml-auto text-muted">
          {analysisStripExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </span>
      </button>

      {/* Collapsed: pills */}
      {!analysisStripExpanded && (
        <div className="flex flex-wrap gap-1 px-3 pb-2">
          {pills.map((p) => (
            <Pill key={p.label} label={p.label} color={p.color} onClick={() => setChatPrefill(p.q)} />
          ))}
        </div>
      )}

      {/* Expanded: redirect to Deep tab (MetricCards live there to avoid duplication).
          The spec calls for full MetricCards here, but since DeepTab already contains
          all MetricCards JSX, we avoid duplicating it. A future follow-up can extract
          <MetricCards> into a shared component and render it in both places. */}
      {analysisStripExpanded && (
        <div className="px-3 pb-3 text-xs text-muted">
          Full report available in the{" "}
          <button
            onClick={() => { setAnalysisStripExpanded(false); setRightPanelTab("deep"); }}
            className="text-accent hover:underline"
          >
            Deep tab
          </button>.{" "}
          <button
            onClick={() => setAnalysisStripExpanded(false)}
            className="text-muted hover:underline"
          >
            Collapse
          </button>
        </div>
      )}
    </div>
  );
}
