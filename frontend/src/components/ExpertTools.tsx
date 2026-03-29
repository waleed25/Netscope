/**
 * ExpertTools — Expert analysis panel with ICS/SCADA decoders and advanced
 * network analysis modes.
 *
 * Modes:
 *   ics_audit      — Modbus / DNP3 / OPC-UA inventory + anomalies
 *   port_scan      — SYN / horizontal scan detection
 *   flow_analysis  — top flows by packets & bytes, long-lived connections
 *   conversations  — bidirectional IP conversation table
 *   anomaly_detect — statistical anomaly detection
 */

import { useState, useRef, useCallback } from "react";
import { BASE } from "../lib/api";
import {
  Shield, Scan, Activity, ArrowLeftRight, AlertTriangle,
  Play, Loader2, ChevronDown, ChevronRight, Brain,
  AlertCircle, Info, CheckCircle2,
} from "lucide-react";
import { useStore } from "../store/useStore";
import { MarkdownContent } from "./MarkdownContent";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ModeDef {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
}

const MODES: ModeDef[] = [
  {
    id: "ics_audit",
    label: "ICS / SCADA Audit",
    description: "Modbus · DNP3 · OPC-UA inventory and anomalies",
    icon: <Shield className="w-4 h-4" />,
  },
  {
    id: "port_scan",
    label: "Port Scan Detection",
    description: "SYN scan · horizontal scan · RST storm",
    icon: <Scan className="w-4 h-4" />,
  },
  {
    id: "flow_analysis",
    label: "Flow Analysis",
    description: "Top flows by packets & bytes · long-lived sessions",
    icon: <Activity className="w-4 h-4" />,
  },
  {
    id: "conversations",
    label: "Conversations",
    description: "All bidirectional IP pairs with protocol breakdown",
    icon: <ArrowLeftRight className="w-4 h-4" />,
  },
  {
    id: "anomaly_detect",
    label: "Anomaly Detection",
    description: "Statistical outliers · protocol mismatches",
    icon: <AlertTriangle className="w-4 h-4" />,
  },
];

// ── Severity badge ─────────────────────────────────────────────────────────────

function SeverityBadge({ sev }: { sev: string }) {
  const cls: Record<string, string> = {
    HIGH:   "bg-danger-emphasis/20 text-danger border-danger-emphasis/40",
    MEDIUM: "bg-warning/20 text-attention border-warning/40",
    LOW:    "bg-accent-emphasis/20 text-accent border-accent-emphasis/40",
    INFO:   "bg-success-emphasis/20 text-success border-success-emphasis/40",
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border uppercase tracking-wide ${cls[sev] ?? cls.INFO}`}>
      {sev}
    </span>
  );
}

// ── Collapsible section ────────────────────────────────────────────────────────

function Section({
  title, badge, defaultOpen = true, children,
}: {
  title: string; badge?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border rounded-lg overflow-hidden mb-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-surface hover:bg-surface-hover text-left transition-colors"
      >
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-muted shrink-0" />}
        <span className="text-xs font-semibold text-foreground">{title}</span>
        {badge && <span className="ml-1">{badge}</span>}
      </button>
      {open && (
        <div className="px-3 py-2 bg-background text-xs text-foreground">
          {children}
        </div>
      )}
    </div>
  );
}

// ── KV table ──────────────────────────────────────────────────────────────────

function KVTable({ data, keyLabel = "Key", valLabel = "Count" }: {
  data: Record<string, number | string>; keyLabel?: string; valLabel?: string;
}) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="text-muted text-xs italic">—</p>;
  return (
    <table className="w-full text-xs border-collapse">
      <thead>
        <tr className="border-b border-border">
          <th className="text-left text-muted py-1 pr-4 font-medium">{keyLabel}</th>
          <th className="text-right text-muted py-1 font-medium">{valLabel}</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} className="border-b border-border-subtle hover:bg-surface">
            <td className="py-1 pr-4 font-mono text-foreground break-all">{k || "—"}</td>
            <td className="py-1 text-right font-mono text-muted">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Anomaly list ──────────────────────────────────────────────────────────────

function AnomalyList({ anomalies }: { anomalies: Array<{ severity: string; description: string; protocol?: string }> }) {
  if (!anomalies.length) {
    return (
      <div className="flex items-center gap-2 text-success text-xs">
        <CheckCircle2 className="w-3.5 h-3.5" />
        No anomalies detected.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {anomalies.map((a, i) => (
        <div key={i} className="flex items-start gap-2 p-2 rounded bg-surface border border-border">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-danger" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-0.5">
              <SeverityBadge sev={a.severity} />
              {a.protocol && (
                <span className="text-[9px] font-mono text-muted">{a.protocol}</span>
              )}
            </div>
            <p className="text-xs text-foreground leading-snug">{a.description}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Result renderers ──────────────────────────────────────────────────────────

function IcsAuditResult({ result }: { result: any }) {
  const { summary, modbus, dnp3, opcua, anomalies } = result;
  return (
    <div>
      {/* Summary counts */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        {[
          { label: "ICS Total",  value: summary.total_ics },
          { label: "Modbus",     value: summary.modbus_count,  color: "text-danger" },
          { label: "DNP3",       value: summary.dnp3_count,    color: "text-attention" },
          { label: "OPC-UA",     value: summary.opcua_count,   color: "text-purple" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-surface border border-border rounded p-2 text-center">
            <div className={`text-lg font-bold font-mono ${color ?? "text-foreground"}`}>{value}</div>
            <div className="text-[10px] text-muted">{label}</div>
          </div>
        ))}
      </div>

      {/* Anomalies always visible */}
      <Section title="Anomalies" badge={
        anomalies.length > 0
          ? <SeverityBadge sev={anomalies[0].severity} />
          : <CheckCircle2 className="w-3 h-3 text-success" />
      }>
        <AnomalyList anomalies={anomalies} />
      </Section>

      {/* Modbus */}
      {summary.modbus_count > 0 && (
        <Section title={`Modbus  (${summary.modbus_count} packets)`}>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Masters</p>
              <KVTable data={modbus.masters} keyLabel="IP" valLabel="Pkts" />
            </div>
            <div>
              <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Slaves / RTUs</p>
              <KVTable data={modbus.slaves} keyLabel="IP" valLabel="Pkts" />
            </div>
          </div>
          <p className="text-[10px] text-muted mt-2 mb-1 uppercase tracking-wide">Function Codes</p>
          <KVTable data={modbus.function_codes} keyLabel="Function" valLabel="Count" />
          {modbus.exceptions > 0 && (
            <p className="mt-2 text-xs text-attention">
              ⚠ {modbus.exceptions} exception response{modbus.exceptions > 1 ? "s" : ""} detected
            </p>
          )}
          {modbus.dangerous_writes.length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] text-danger mb-1 uppercase tracking-wide">Dangerous Writes</p>
              {modbus.dangerous_writes.map((w: any, i: number) => (
                <span key={i} className="inline-block mr-1 mb-1 px-1.5 py-0.5 bg-danger-emphasis/20 text-danger text-[10px] rounded border border-danger-emphasis/30">
                  {w.label}
                </span>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* DNP3 */}
      {summary.dnp3_count > 0 && (
        <Section title={`DNP3  (${summary.dnp3_count} packets)`}>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Masters</p>
              <KVTable data={dnp3.masters} keyLabel="Address / IP" valLabel="Pkts" />
            </div>
            <div>
              <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Outstations</p>
              <KVTable data={dnp3.outstations} keyLabel="Address / IP" valLabel="Pkts" />
            </div>
          </div>
          <p className="text-[10px] text-muted mt-2 mb-1 uppercase tracking-wide">Application Function Codes</p>
          <KVTable data={dnp3.function_codes} keyLabel="Function" valLabel="Count" />
          {dnp3.dangerous_ops.length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] text-danger mb-1 uppercase tracking-wide">Dangerous Operations</p>
              {dnp3.dangerous_ops.map((op: any, i: number) => (
                <span key={i} className="inline-block mr-1 mb-1 px-1.5 py-0.5 bg-danger-emphasis/20 text-danger text-[10px] rounded border border-danger-emphasis/30">
                  {op.label}
                </span>
              ))}
            </div>
          )}
          {dnp3.unsolicited > 0 && (
            <p className="mt-1 text-xs text-accent">
              ℹ {dnp3.unsolicited} unsolicited response{dnp3.unsolicited > 1 ? "s" : ""} from outstations
            </p>
          )}
        </Section>
      )}

      {/* OPC-UA */}
      {summary.opcua_count > 0 && (
        <Section title={`OPC-UA  (${summary.opcua_count} packets)`}>
          {opcua.insecure_policies.length > 0 && (
            <div className="mb-2 p-2 bg-danger-emphasis/10 border border-danger-emphasis/30 rounded text-xs text-danger">
              ⛔ Insecure sessions detected (SecurityMode=None): {opcua.insecure_policies.join(", ")}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Endpoints</p>
              <KVTable data={opcua.endpoints} keyLabel="URL" valLabel="Pkts" />
            </div>
            <div>
              <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Services</p>
              <KVTable data={opcua.services} keyLabel="Service" valLabel="Count" />
            </div>
          </div>
        </Section>
      )}

      {summary.total_ics === 0 && (
        <div className="flex items-center gap-2 mt-2 text-muted text-xs">
          <Info className="w-3.5 h-3.5" />
          No ICS traffic (Modbus/DNP3/OPC-UA) detected in the current packet buffer.
        </div>
      )}
    </div>
  );
}

function PortScanResult({ result }: { result: any }) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-surface border border-border rounded p-2 text-center">
          <div className="text-lg font-bold font-mono text-foreground">{result.tcp_packets_analyzed}</div>
          <div className="text-[10px] text-muted">TCP Packets</div>
        </div>
        <div className="bg-surface border border-border rounded p-2 text-center">
          <div className={`text-lg font-bold font-mono ${result.scan_suspects.length > 0 ? "text-danger" : "text-success"}`}>
            {result.scan_suspects.length}
          </div>
          <div className="text-[10px] text-muted">Scan Suspects</div>
        </div>
      </div>

      {result.scan_suspects.length > 0 ? (
        <Section title="Scan Suspects" defaultOpen>
          {result.scan_suspects.map((s: any, i: number) => (
            <div key={i} className="mb-2 p-2 bg-surface border border-border rounded">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <SeverityBadge sev={s.severity} />
                <span className="font-mono text-xs text-accent">{s.src_ip}</span>
                <span className="text-[10px] text-muted uppercase">{s.type.replace("_", " ")}</span>
              </div>
              {s.type === "vertical_scan" && (
                <p className="text-xs text-muted">
                  {s.distinct_ports} distinct ports scanned{s.within_60s ? " within 60s" : ""}
                  {s.top_ports && ` — sample: ${s.top_ports.slice(0, 8).join(", ")}…`}
                </p>
              )}
              {s.type === "horizontal_scan" && (
                <p className="text-xs text-muted">
                  Port {s.target_port} probed on {s.distinct_targets} distinct hosts
                </p>
              )}
            </div>
          ))}
        </Section>
      ) : (
        <div className="flex items-center gap-2 text-success text-xs mb-3">
          <CheckCircle2 className="w-3.5 h-3.5" />
          No port scan patterns detected.
        </div>
      )}

      {result.rst_storm.length > 0 && (
        <Section title="RST Storm">
          <KVTable
            data={Object.fromEntries(result.rst_storm.map((r: any) => [r.src_ip, r.rst_count]))}
            keyLabel="Source IP" valLabel="RST Packets"
          />
        </Section>
      )}

      <Section title="Top Port Touchers" defaultOpen={false}>
        <KVTable
          data={Object.fromEntries(result.top_port_touchers.map((r: any) => [r.src_ip, r.distinct_ports]))}
          keyLabel="Source IP" valLabel="Distinct Ports"
        />
      </Section>
    </div>
  );
}

function FlowResult({ result }: { result: any }) {
  const fmt = (b: number) => b > 1_000_000 ? `${(b / 1_000_000).toFixed(1)}MB`
    : b > 1_000 ? `${(b / 1_000).toFixed(1)}KB` : `${b}B`;

  const FlowTable = ({ flows }: { flows: any[] }) => (
    <table className="w-full text-xs border-collapse">
      <thead>
        <tr className="border-b border-border">
          {["Source", "Destination", "Proto", "Pkts", "Bytes", "Duration"].map(h => (
            <th key={h} className="text-left text-muted py-1 pr-3 font-medium">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {flows.map((f: any, i: number) => (
          <tr key={i} className="border-b border-border-subtle hover:bg-surface">
            <td className="py-1 pr-3 font-mono text-foreground break-all">{f.src}</td>
            <td className="py-1 pr-3 font-mono text-foreground break-all">{f.dst}</td>
            <td className="py-1 pr-3">
              <span className={`px-1 py-0.5 rounded text-[9px] font-mono ${
                f.protocol === "MODBUS" ? "bg-danger-emphasis/20 text-danger" :
                f.protocol === "DNP3"   ? "bg-warning/20 text-attention" :
                f.protocol === "OPC-UA" ? "bg-purple-emphasis/20 text-purple" :
                "bg-border-subtle text-muted"
              }`}>{f.protocol}</span>
            </td>
            <td className="py-1 pr-3 font-mono text-muted">{f.packets}</td>
            <td className="py-1 pr-3 font-mono text-muted">{fmt(f.bytes)}</td>
            <td className="py-1 font-mono text-muted">{f.duration_s}s</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-surface border border-border rounded p-2 text-center">
          <div className="text-lg font-bold font-mono text-foreground">{result.total_flows}</div>
          <div className="text-[10px] text-muted">Unique Flows</div>
        </div>
        <div className="bg-surface border border-border rounded p-2 text-center">
          <div className="text-lg font-bold font-mono text-accent">{fmt(result.total_bytes)}</div>
          <div className="text-[10px] text-muted">Total Bytes</div>
        </div>
      </div>
      <Section title="Top Flows by Packets">
        <FlowTable flows={result.top_by_packets} />
      </Section>
      <Section title="Top Flows by Bytes" defaultOpen={false}>
        <FlowTable flows={result.top_by_bytes} />
      </Section>
      {result.long_lived_flows.length > 0 && (
        <Section title={`Long-lived Flows (≥30s) — ${result.long_lived_flows.length}`} defaultOpen={false}>
          <FlowTable flows={result.long_lived_flows} />
        </Section>
      )}
      {result.ics_flows.length > 0 && (
        <Section title={`ICS Flows — ${result.ics_flows.length}`}>
          <FlowTable flows={result.ics_flows} />
        </Section>
      )}
    </div>
  );
}

function ConversationsResult({ result }: { result: any }) {
  return (
    <div>
      <p className="text-xs text-muted mb-3">
        {result.total_conversations} unique conversations
      </p>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-border">
            {["Peer A", "Peer B", "Protocols", "Packets", "Bytes"].map(h => (
              <th key={h} className="text-left text-muted py-1 pr-4 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.conversations.map((c: any, i: number) => (
            <tr key={i} className="border-b border-border-subtle hover:bg-surface">
              <td className="py-1 pr-4 font-mono text-foreground">{c.peer_a}</td>
              <td className="py-1 pr-4 font-mono text-foreground">{c.peer_b}</td>
              <td className="py-1 pr-4 text-muted">
                {Object.keys(c.protocols).join(", ")}
              </td>
              <td className="py-1 pr-4 font-mono text-muted">{c.packets}</td>
              <td className="py-1 font-mono text-muted">{c.bytes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnomalyResult({ result }: { result: any }) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        {[
          { label: "Total Packets", value: result.total_packets },
          { label: "Anomalies",     value: result.anomalies.length,
            color: result.anomalies.length > 0 ? "text-danger" : "text-success" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-surface border border-border rounded p-2 text-center">
            <div className={`text-lg font-bold font-mono ${color ?? "text-foreground"}`}>{value}</div>
            <div className="text-[10px] text-muted">{label}</div>
          </div>
        ))}
      </div>
      <Section title="Anomalies">
        <AnomalyList anomalies={result.anomalies} />
      </Section>
      <Section title="Traffic Statistics" defaultOpen={false}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Protocol Distribution</p>
            <KVTable data={result.stats.protocol_dist} keyLabel="Protocol" valLabel="Pkts" />
          </div>
          <div>
            <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Top Destination Ports</p>
            <KVTable data={result.stats.top_dst_ports} keyLabel="Port" valLabel="Pkts" />
          </div>
          <div>
            <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Top Source IPs</p>
            <KVTable data={result.stats.top_src_ips} keyLabel="IP" valLabel="Pkts" />
          </div>
          <div>
            <p className="text-[10px] text-muted mb-1 uppercase tracking-wide">Top Destination IPs</p>
            <KVTable data={result.stats.top_dst_ips} keyLabel="IP" valLabel="Pkts" />
          </div>
        </div>
      </Section>
    </div>
  );
}

function renderResult(mode: string, result: any) {
  switch (mode) {
    case "ics_audit":      return <IcsAuditResult result={result} />;
    case "port_scan":      return <PortScanResult result={result} />;
    case "flow_analysis":  return <FlowResult result={result} />;
    case "conversations":  return <ConversationsResult result={result} />;
    case "anomaly_detect": return <AnomalyResult result={result} />;
    default:               return <pre className="text-xs">{JSON.stringify(result, null, 2)}</pre>;
  }
}

// ── Main component ────────────────────────────────────────────────────────────

export function ExpertTools() {
  const totalPackets = useStore((s) => s.totalPackets);
  const [selectedMode, setSelectedMode] = useState<ModeDef>(MODES[0]);
  const [running, setRunning]     = useState(false);
  const [result, setResult]       = useState<any>(null);
  const [commentary, setCommentary] = useState("");
  const [showLLM, setShowLLM]     = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    if (running) {
      abortRef.current?.abort();
      return;
    }
    if (!totalPackets) return;

    setRunning(true);
    setResult(null);
    setCommentary("");

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const resp = await fetch(`${BASE}/expert/analyze/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: selectedMode.id, with_llm: showLLM }),
        signal: ctrl.signal,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setCommentary(`[error] ${err.detail ?? resp.statusText}`);
        return;
      }

      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // Scan for EXPERT_RESULT sentinel
        while (buf.includes("\x00")) {
          const start = buf.indexOf("\x00");
          const end   = buf.indexOf("\x00", start + 1);
          if (end === -1) break;

          const sentinel = buf.slice(start + 1, end);
          buf = buf.slice(0, start) + buf.slice(end + 1);

          if (sentinel.startsWith("EXPERT_RESULT:")) {
            try {
              setResult(JSON.parse(sentinel.slice("EXPERT_RESULT:".length)));
            } catch { /* ignore */ }
          }
        }

        // Remaining plain text is LLM commentary
        if (buf && !buf.includes("\x00")) {
          setCommentary((prev) => prev + buf);
          buf = "";
        }
      }
      // Flush any leftover
      if (buf) setCommentary((prev) => prev + buf);

    } catch (e: unknown) {
      if (e instanceof Error && e.name !== "AbortError") {
        setCommentary(`[error] ${e.message}`);
      }
    } finally {
      setRunning(false);
    }
  }, [running, selectedMode, showLLM, totalPackets]);

  const selectMode = (m: ModeDef) => {
    if (running) { abortRef.current?.abort(); }
    setSelectedMode(m);
    setResult(null);
    setCommentary("");
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Horizontal mode tabs */}
      <div className="flex shrink-0 border-b border-border bg-surface px-2 gap-0 pt-1">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => selectMode(m)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t transition-colors border-b-2 whitespace-nowrap ${
              selectedMode.id === m.id
                ? "border-accent text-accent bg-surface-hover"
                : "border-transparent text-muted hover:text-foreground hover:bg-surface-hover"
            }`}
          >
            <span className="w-3.5 h-3.5">{m.icon}</span>
            {m.label}
          </button>
        ))}
      </div>

      {/* Main panel */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Toolbar */}
        <div className="shrink-0 border-b border-border bg-surface px-4 py-2 flex items-center gap-3 flex-wrap">
          <span className="text-muted text-xs">{totalPackets} packets</span>

          <label className="flex items-center gap-1.5 text-xs text-muted cursor-pointer select-none ml-auto">
            <input
              type="checkbox"
              checked={showLLM}
              onChange={(e) => setShowLLM(e.target.checked)}
              className="w-3 h-3 accent-accent"
            />
            LLM commentary
          </label>

          <button
            onClick={run}
            disabled={!totalPackets && !running}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              running
                ? "bg-danger-emphasis hover:bg-danger-emphasis text-white"
                : "bg-success-emphasis hover:bg-success-emphasis-hover text-white disabled:opacity-40"
            }`}
          >
            {running
              ? <><Loader2 className="w-3 h-3 animate-spin" /> Stop</>
              : <><Play className="w-3 h-3" /> Run Analysis</>}
          </button>
        </div>

        {/* Body: result + commentary */}
        <div className="flex flex-1 overflow-hidden">
          {/* Structured result */}
          <div className="flex-1 overflow-y-auto p-4">
            {!result && !running && !commentary && (
              <div className="flex flex-col items-center gap-3 pt-12 text-center">
                <div className="text-border">{selectedMode.icon}</div>
                <p className="text-muted text-sm max-w-xs">{selectedMode.description}</p>
                {!totalPackets && (
                  <p className="text-danger text-xs">
                    No packets — start a capture first.
                  </p>
                )}
              </div>
            )}
            {running && !result && (
              <div className="flex items-center gap-2 text-muted text-xs pt-8">
                <Loader2 className="w-4 h-4 animate-spin" />
                Running analysis…
              </div>
            )}
            {result && renderResult(selectedMode.id, result)}
          </div>

          {/* LLM commentary panel */}
          {(commentary || (running && showLLM && result)) && (
            <div className="w-80 shrink-0 border-l border-border bg-surface overflow-y-auto p-4">
              <div className="flex items-center gap-1.5 text-accent text-xs font-semibold mb-3">
                <Brain className="w-3.5 h-3.5" />
                LLM Security Assessment
              </div>
              {running && !commentary && (
                <div className="text-muted text-xs animate-pulse">Analysing…</div>
              )}
              {commentary && <MarkdownContent>{commentary}</MarkdownContent>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
