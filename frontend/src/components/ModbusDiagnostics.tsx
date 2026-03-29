/**
 * ModbusDiagnostics — Desktop-style tool layout.
 *
 * Toolbar (h-9): session selector, FC segment buttons, Live toggle, Read, Config popover
 * Middle row: RegPane (register table + write toolbar) | StatsSidebar (KPIs, timeline, jitter, exceptions)
 * Log panel (resizable height): Transactions | Traffic tabs
 * Status bar (h-6): polling state, RTT, polls, rate, exceptions
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getModbusDiagnostics,
  getModbusRegisters,
  writeModbusRegister,
  updateClientSession,
  fetchClientSessions,
  createModbusLiveWebSocket,
  createModbusTrafficWebSocket,
  setModbusTrafficLog,
  type DiagnosticsStats,
  type JitterStats,
  type ModbusWsData,
  type RegisterEntry,
  type ModbusSession,
  type ParsedFrame,
} from "../lib/api";
import { TrendChart } from "./TrendChart";

// ── Props ──────────────────────────────────────────────────────────────────────

export interface ModbusDiagnosticsProps {
  sessions: string[];
  source: "simulator" | "client";
}

// ── FC tab definitions ─────────────────────────────────────────────────────────

const FC_TABS = [
  { label: "HR",    fc: 3, start: 40001, count: 50 },
  { label: "IR",    fc: 4, start: 30001, count: 50 },
  { label: "Coils", fc: 1, start: 1,     count: 50 },
  { label: "DI",    fc: 2, start: 10001, count: 50 },
] as const;

type FcTabId = typeof FC_TABS[number]["label"]; // "HR" | "IR" | "Coils" | "DI"

// ── Helper functions ───────────────────────────────────────────────────────────

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

function fmtRtt(ms: number): string {
  return `${ms.toFixed(0)}ms`;
}

function fmtMicros(ts_us: number): string {
  const d = new Date(ts_us / 1000);
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function qualityRowBg(quality?: string, isFlashing?: boolean): string {
  if (isFlashing) return "bg-[rgb(var(--color-warning-subtle))]";
  switch (quality) {
    case "good":  return "bg-[rgb(var(--color-success-subtle))]/30";
    case "bad":   return "bg-[rgb(var(--color-danger-subtle))]/40";
    case "stale": return "bg-[rgb(var(--color-border-subtle))]";
    default:      return "";
  }
}

// ── ALL_FCS_DIAG ───────────────────────────────────────────────────────────────

const ALL_FCS_DIAG: [number, string][] = [
  [1, "Coils"], [2, "Discrete In"], [3, "Holding Regs"], [4, "Input Regs"],
  [5, "Write Coil"], [6, "Write Reg"], [15, "Write Coils"], [16, "Write Regs"],
];

// ── SessionConfigPanel ─────────────────────────────────────────────────────────

function SessionConfigPanel({
  sessionId,
  session,
  onUpdated,
}: {
  sessionId: string;
  session: ModbusSession | undefined;
  onUpdated: () => void;
}) {
  const [editByteOrder, setEditByteOrder] = useState(session?.byte_order ?? "ABCD");
  const [editPollInterval, setEditPollInterval] = useState(String(session?.poll_interval ?? 10));
  const [editEnabledFCs, setEditEnabledFCs] = useState<Set<number>>(
    new Set(session?.enabled_fcs ?? [1, 2, 3, 4, 5, 6, 15, 16]),
  );
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const [saveOk, setSaveOk] = useState(false);

  // Sync state when session prop changes (e.g. after save or session switch)
  useEffect(() => {
    setEditByteOrder(session?.byte_order ?? "ABCD");
    setEditPollInterval(String(session?.poll_interval ?? 10));
    setEditEnabledFCs(new Set(session?.enabled_fcs ?? [1, 2, 3, 4, 5, 6, 15, 16]));
  }, [session]);

  const toggleFC = (fc: number) => setEditEnabledFCs(prev => {
    const next = new Set(prev);
    next.has(fc) ? next.delete(fc) : next.add(fc);
    return next;
  });

  const handleSave = async () => {
    setSaving(true); setSaveErr(""); setSaveOk(false);
    try {
      await updateClientSession(sessionId, {
        byte_order: editByteOrder,
        poll_interval: parseFloat(editPollInterval) || 10,
        enabled_fcs: [...editEnabledFCs],
      });
      setSaveOk(true);
      onUpdated();
      setTimeout(() => setSaveOk(false), 2000);
    } catch (e: unknown) {
      setSaveErr(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center gap-2 text-[10px] text-[rgb(var(--color-muted))] flex-wrap">
        <span className="px-1.5 py-0.5 bg-[rgb(var(--color-background))] rounded text-[rgb(var(--color-accent))] font-mono border border-[rgb(var(--color-border))]">
          {(session?.transport ?? "tcp").toUpperCase()}
        </span>
        <span>Order: {session?.byte_order ?? "ABCD"}</span>
        <span>{(session?.enabled_fcs ?? []).length} FCs</span>
        {saveOk && <span className="text-[rgb(var(--color-success))]">✓ Saved</span>}
      </div>

      <div className="space-y-2">
        <label className="flex flex-col gap-0.5 text-[10px] text-[rgb(var(--color-muted))]">
          Byte Order
          <select
            value={editByteOrder}
            onChange={(e) => setEditByteOrder(e.target.value)}
            className="bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-1.5 py-0.5 text-[rgb(var(--color-foreground))] text-[10px] focus:outline-none focus:border-[rgb(var(--color-accent))]"
          >
            <option value="ABCD">ABCD — Big/Big</option>
            <option value="BADC">BADC — Byte-swap</option>
            <option value="CDAB">CDAB — Word-swap (Schneider)</option>
            <option value="DCBA">DCBA — Little/Little</option>
          </select>
        </label>
        <label className="flex flex-col gap-0.5 text-[10px] text-[rgb(var(--color-muted))]">
          Poll Interval (s)
          <input
            type="number"
            value={editPollInterval}
            onChange={(e) => setEditPollInterval(e.target.value)}
            className="bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-1.5 py-0.5 text-[rgb(var(--color-foreground))] text-[10px] font-mono focus:outline-none focus:border-[rgb(var(--color-accent))] w-20"
          />
        </label>
        <div>
          <p className="text-[10px] text-[rgb(var(--color-muted))] uppercase tracking-wider mb-1">Function Codes</p>
          <div className="flex flex-wrap gap-2">
            {ALL_FCS_DIAG.map(([fc, lbl]) => (
              <label key={fc} className="flex items-center gap-1 text-[10px] text-[rgb(var(--color-foreground))] cursor-pointer">
                <input
                  type="checkbox"
                  checked={editEnabledFCs.has(fc)}
                  onChange={() => toggleFC(fc)}
                  className="accent-[rgb(var(--color-accent))] w-3 h-3"
                />
                <span className="text-[rgb(var(--color-accent))] font-mono">FC{fc}</span>
                <span className="text-[rgb(var(--color-muted))]">{lbl}</span>
              </label>
            ))}
          </div>
        </div>
        {saveErr && <p className="text-[10px] text-[rgb(var(--color-danger))]">{saveErr}</p>}
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-2 py-0.5 rounded text-[10px] font-medium bg-[rgb(var(--color-accent-emphasis))] text-white hover:bg-[rgb(var(--color-accent-emphasis-hover))] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}

// ── WriteToolbar ───────────────────────────────────────────────────────────────

interface WriteToolbarProps {
  source: "simulator" | "client";
  sessionId: string;
  onWriteComplete: () => void;
}

function WriteToolbar({ source, sessionId, onWriteComplete }: WriteToolbarProps) {
  const [writeAddr, setWriteAddr] = useState("");
  const [writeVal,  setWriteVal]  = useState("");
  const [writeFc,   setWriteFc]   = useState<6 | 16>(6);
  const [writing,   setWriting]   = useState(false);
  const [writeErr,  setWriteErr]  = useState("");

  const handleWrite = async () => {
    const addr = parseInt(writeAddr, 10);
    const val  = parseInt(writeVal,  10);
    if (isNaN(addr) || isNaN(val)) { setWriteErr("Bad addr/val"); return; }
    setWriting(true); setWriteErr("");
    try {
      const res = await writeModbusRegister(source, sessionId, { fc: writeFc, addr, values: [val] });
      if ((res as { error?: string }).error) setWriteErr((res as { error?: string }).error!);
      else { setWriteAddr(""); setWriteVal(""); onWriteComplete(); }
    } catch (e: unknown) {
      setWriteErr(e instanceof Error ? e.message : String(e));
    }
    setWriting(false);
  };

  return (
    <div className="shrink-0 h-8 flex items-center gap-1.5 px-2 border-t border-[rgb(var(--color-border))] bg-[rgb(var(--color-surface))]">
      <select
        value={writeFc}
        onChange={e => setWriteFc(Number(e.target.value) as 6 | 16)}
        className="h-6 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-1 text-[11px] font-mono text-[rgb(var(--color-foreground))] focus:outline-none focus:border-[rgb(var(--color-accent))]"
      >
        <option value={6}>FC06</option>
        <option value={16}>FC16</option>
      </select>
      <input
        className="w-16 h-6 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-1.5 text-[11px] font-mono text-[rgb(var(--color-foreground))] focus:outline-none focus:border-[rgb(var(--color-accent))]"
        value={writeAddr} onChange={e => setWriteAddr(e.target.value)} placeholder="40001"
      />
      <input
        className="w-16 h-6 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-1.5 text-[11px] font-mono text-[rgb(var(--color-foreground))] focus:outline-none focus:border-[rgb(var(--color-accent))]"
        value={writeVal} onChange={e => setWriteVal(e.target.value)} placeholder="0"
      />
      <button
        onClick={handleWrite}
        disabled={writing}
        className="h-6 px-2 rounded text-[11px] font-medium bg-[rgb(var(--color-accent-emphasis))] text-white hover:bg-[rgb(var(--color-accent-emphasis-hover))] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {writing ? "…" : "Write"}
      </button>
      {writeErr && <span className="text-[10px] text-[rgb(var(--color-danger))] truncate">{writeErr}</span>}
    </div>
  );
}

// ── RegPane ────────────────────────────────────────────────────────────────────

interface RegPaneProps {
  sessionId: string;
  source: "simulator" | "client";
  fcTab: FcTabId;
}

function RegPane({ sessionId, source, fcTab }: RegPaneProps) {
  const [registers, setRegisters] = useState<RegisterEntry[]>([]);
  const [flashing, setFlashing]   = useState<Set<number>>(new Set());
  const [editAddr, setEditAddr]   = useState<number | null>(null);
  const [editVal,  setEditVal]    = useState("");
  const prevRegsRef = useRef<Map<number, number>>(new Map());

  const fcDef = FC_TABS.find(t => t.label === fcTab) ?? FC_TABS[0];

  const fetchRegs = useCallback(async () => {
    try {
      const resp = await getModbusRegisters(source, sessionId, fcDef.fc, fcDef.start, fcDef.count);
      const regs = resp.registers ?? [];
      const changed = new Set<number>();
      for (const r of regs) {
        const prev = prevRegsRef.current.get(r.address);
        if (prev !== undefined && prev !== r.raw) changed.add(r.address);
      }
      const newMap = new Map<number, number>();
      for (const r of regs) newMap.set(r.address, r.raw);
      prevRegsRef.current = newMap;
      if (changed.size > 0) {
        setFlashing(prev => { const n = new Set(prev); for (const a of changed) n.add(a); return n; });
        setTimeout(() => setFlashing(prev => { const n = new Set(prev); for (const a of changed) n.delete(a); return n; }), 1000);
      }
      setRegisters(regs);
    } catch { /* silently ignore */ }
  }, [source, sessionId, fcDef.fc, fcDef.start, fcDef.count]);

  // Client mode: live WebSocket — does NOT depend on fcTab
  useEffect(() => {
    if (!sessionId || source !== "client") return;
    setRegisters([]);
    prevRegsRef.current = new Map();
    const dispose = createModbusLiveWebSocket(sessionId, (msg: ModbusWsData) => {
      if (msg.type === "data" && msg.registers) setRegisters(msg.registers as RegisterEntry[]);
    }, 1.0);
    return dispose;
  }, [sessionId, source]);

  // Simulator mode: REST polling, re-runs on FC tab change
  useEffect(() => {
    if (!sessionId || source !== "simulator") return;
    setRegisters([]);
    prevRegsRef.current = new Map();
    fetchRegs();
    const t = setInterval(fetchRegs, 1000);
    return () => clearInterval(t);
  }, [sessionId, source, fcTab, fetchRegs]);

  const commitInlineWrite = useCallback(async (addr: number, rawVal: string) => {
    const v = parseInt(rawVal, 10);
    if (isNaN(v)) { setEditAddr(null); return; }
    try { await writeModbusRegister(source, sessionId, { fc: 6, addr, values: [v] }); } catch { /* ignore */ }
    setEditAddr(null); setEditVal("");
    fetchRegs();
  }, [source, sessionId, fetchRegs]);

  return (
    <div className="flex-1 flex flex-col border-r border-[rgb(var(--color-border))] overflow-hidden min-w-0">
      {/* Register table */}
      <div className="flex-1 overflow-y-auto">
        {registers.length === 0 ? (
          <p className="text-[11px] text-[rgb(var(--color-muted))] py-8 text-center">
            {sessionId ? "No data yet" : "Select a session"}
          </p>
        ) : (
          <table className="w-full text-[11px] font-mono border-collapse">
            <thead className="sticky top-0 bg-[rgb(var(--color-surface))] z-10">
              <tr className="text-[rgb(var(--color-muted))] text-[10px] uppercase tracking-wide border-b border-[rgb(var(--color-border))]">
                <th className="px-2 py-1 text-left w-14 font-medium">Addr</th>
                <th className="px-2 py-1 text-left w-16 font-medium">Hex</th>
                <th className="px-2 py-1 text-right w-14 font-medium">Raw</th>
                <th className="px-2 py-1 text-right w-16 font-medium">Value</th>
                <th className="px-2 py-1 text-left w-10 font-medium">Unit</th>
                <th className="px-2 py-1 text-left font-medium">Name</th>
                <th className="px-2 py-1 text-center w-6 font-medium">Δ</th>
              </tr>
            </thead>
            <tbody>
              {registers.map(r => {
                const isFlashing = flashing.has(r.address);
                const isEditing  = editAddr === r.address;
                return (
                  <tr
                    key={r.address}
                    className={`border-t border-[rgb(var(--color-border-subtle))] transition-colors duration-300 hover:bg-[rgb(var(--color-surface))] ${qualityRowBg(r.quality, isFlashing)}`}
                  >
                    <td className="px-2 py-0.5 text-[rgb(var(--color-accent))] font-medium">{r.address}</td>
                    <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">
                      0x{r.raw.toString(16).padStart(4, "0").toUpperCase()}
                    </td>
                    <td
                      className={`px-2 py-0.5 text-right cursor-pointer select-none ${isFlashing ? "text-[rgb(var(--color-warning))]" : "text-[rgb(var(--color-foreground))]"}`}
                      onClick={() => { setEditAddr(r.address); setEditVal(String(r.raw)); }}
                      title="Click to edit"
                    >
                      {isEditing ? (
                        <input
                          autoFocus
                          className="w-14 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-accent))] rounded px-1 text-[11px] text-[rgb(var(--color-foreground))] font-mono focus:outline-none"
                          value={editVal}
                          onChange={e => setEditVal(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === "Enter")  commitInlineWrite(r.address, editVal);
                            if (e.key === "Escape") { setEditAddr(null); setEditVal(""); }
                          }}
                          onBlur={() => { setEditAddr(null); setEditVal(""); }}
                        />
                      ) : r.raw}
                    </td>
                    <td className={`px-2 py-0.5 text-right ${isFlashing ? "text-[rgb(var(--color-warning))]" : "text-[rgb(var(--color-success))]"}`}>
                      {r.value}
                    </td>
                    <td className="px-2 py-0.5 text-[rgb(var(--color-muted))] truncate">{r.unit || "—"}</td>
                    <td className="px-2 py-0.5 text-[rgb(var(--color-foreground))] truncate max-w-[120px]" title={r.name}>{r.name || "—"}</td>
                    <td className="px-2 py-0.5 text-center text-[10px]">
                      {r.delta > 0 ? <span className="text-[rgb(var(--color-success))]">▲</span>
                        : r.delta < 0 ? <span className="text-[rgb(var(--color-danger))]">▼</span>
                        : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {/* Write toolbar */}
      <WriteToolbar source={source} sessionId={sessionId} onWriteComplete={fetchRegs} />
    </div>
  );
}

// ── KpiCard ────────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color, compact = false }: {
  label: string; value: string; sub?: string; color: string; compact?: boolean;
}) {
  return (
    <div className={`flex flex-col gap-0.5 bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded ${compact ? "px-2 py-1.5" : "px-3 py-2 flex-1 min-w-0"}`}>
      <span className={`${compact ? "text-[9px]" : "text-[10px]"} text-[rgb(var(--color-muted))] uppercase tracking-wide truncate`}>{label}</span>
      <span className={`${compact ? "text-[12px]" : "text-sm"} font-mono font-semibold ${color}`}>{value}</span>
      {sub && <span className="text-[10px] text-[rgb(var(--color-muted))] font-mono">{sub}</span>}
    </div>
  );
}

// ── RttTimeline ────────────────────────────────────────────────────────────────

interface TimelinePoint {
  ts: number;
  avg_rtt: number;
  count: number;
  exceptions: number;
}

function RttTimeline({ data }: { data: TimelinePoint[] }) {
  const MAX_BARS = 60;
  const visible = data.slice(-MAX_BARS);
  const maxRtt  = Math.max(...visible.map((d) => d.avg_rtt), 1);

  if (visible.length === 0) {
    return (
      <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2 h-24 flex items-center justify-center">
        <span className="text-[10px] text-[rgb(var(--color-muted))]">No timeline data</span>
      </div>
    );
  }

  return (
    <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2">
      <p className="text-[10px] text-[rgb(var(--color-muted))] mb-1 uppercase tracking-wide">RTT Timeline (last 2 min)</p>
      <div className="flex items-end gap-px h-16 overflow-hidden">
        {visible.map((d, i) => {
          const heightPct = (d.avg_rtt / maxRtt) * 100;
          const isExc = d.exceptions > 0;
          return (
            <div
              key={i}
              title={`${fmtTime(d.ts)}: ${fmtRtt(d.avg_rtt)}${isExc ? ` (${d.exceptions} exc)` : ""}`}
              className={`flex-1 min-w-[2px] rounded-sm transition-all ${isExc ? "bg-[rgb(var(--color-danger))]" : "bg-[rgb(var(--color-accent))]"}`}
              style={{ height: `${Math.max(heightPct, 2)}%` }}
            />
          );
        })}
      </div>
      <div className="flex justify-between mt-0.5 text-[9px] text-[rgb(var(--color-muted))] font-mono">
        {visible.length > 0 && <span>{fmtTime(visible[0].ts)}</span>}
        {visible.length > 1 && <span>{fmtTime(visible[visible.length - 1].ts)}</span>}
      </div>
    </div>
  );
}

// ── JitterPanel ────────────────────────────────────────────────────────────────

function JitterPanel({ data }: { data: JitterStats | undefined }) {
  if (!data || data.samples === 0) {
    return (
      <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2 h-24 flex items-center justify-center">
        <span className="text-[10px] text-[rgb(var(--color-muted))]">No jitter data yet</span>
      </div>
    );
  }

  const timeline = data.timeline_ms ?? [];
  const maxVal   = Math.max(...timeline, data.target_ms * 1.2, 1);

  return (
    <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2">
      <p className="text-[10px] text-[rgb(var(--color-muted))] mb-1 uppercase tracking-wide">
        Jitter Monitor — target {data.target_ms.toFixed(0)} ms
      </p>

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-1 mb-2">
        {[
          { label: "Mean",       value: data.mean_ms,        unit: "ms" },
          { label: "Std Dev",    value: data.std_dev_ms,     unit: "ms" },
          { label: "p50 jitter", value: data.p50_jitter_ms,  unit: "ms" },
          { label: "p95 jitter", value: data.p95_jitter_ms,  unit: "ms" },
        ].map(({ label, value, unit }) => (
          <div key={label} className="text-center">
            <p className="text-[9px] text-[rgb(var(--color-muted))] uppercase">{label}</p>
            <p className="text-[11px] font-mono font-semibold text-[rgb(var(--color-foreground))]">
              {value != null ? `${value.toFixed(1)}${unit}` : "—"}
            </p>
          </div>
        ))}
      </div>

      {/* Sparkline — actual intervals vs target line */}
      {timeline.length > 0 && (
        <svg className="w-full h-10" viewBox={`0 0 ${timeline.length} 40`} preserveAspectRatio="none">
          {/* target line */}
          <line
            x1={0} y1={40 - (data.target_ms / maxVal) * 40}
            x2={timeline.length} y2={40 - (data.target_ms / maxVal) * 40}
            stroke="rgb(var(--color-muted))" strokeWidth="0.5" strokeDasharray="2,2"
          />
          {/* actual interval polyline */}
          <polyline
            points={timeline.map((v, i) =>
              `${i},${(40 - (v / maxVal) * 38).toFixed(1)}`
            ).join(" ")}
            fill="none"
            stroke="rgb(var(--color-accent))"
            strokeWidth="1"
          />
        </svg>
      )}
    </div>
  );
}

// ── ExceptionFrequency ─────────────────────────────────────────────────────────

interface ExcEntry {
  fc: number;
  addr: number;
  code: number;
  count: number;
}

function ExceptionFrequency({ data }: { data: ExcEntry[] }) {
  const sorted = [...data].sort((a, b) => b.count - a.count).slice(0, 5);
  const maxCount = Math.max(...sorted.map((d) => d.count), 1);

  if (sorted.length === 0) {
    return (
      <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2">
        <p className="text-[10px] text-[rgb(var(--color-muted))] uppercase tracking-wide mb-1">Exception Frequency</p>
        <p className="text-[10px] text-[rgb(var(--color-muted))] py-2 text-center">No exceptions recorded</p>
      </div>
    );
  }

  return (
    <div className="bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded p-2">
      <p className="text-[10px] text-[rgb(var(--color-muted))] uppercase tracking-wide mb-2">Exception Frequency</p>
      <div className="space-y-1">
        {sorted.map((d, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-[rgb(var(--color-muted))] w-28 shrink-0 truncate">
              FC{d.fc} @{d.addr} e{d.code}
            </span>
            <div className="flex-1 bg-[rgb(var(--color-border-subtle))] rounded-sm h-2 overflow-hidden">
              <div
                className="h-full bg-[rgb(var(--color-danger))] rounded-sm"
                style={{ width: `${(d.count / maxCount) * 100}%` }}
              />
            </div>
            <span className="text-[10px] font-mono text-[rgb(var(--color-danger))] w-8 text-right shrink-0">
              {d.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── TransactionLog ─────────────────────────────────────────────────────────────

interface TxEntry {
  seq: number;
  ts: number;
  session_id: string;
  fc: number;
  addr: number;
  rtt_ms: number;
  status: string;
  exception_code: number | null;
  response_summary: string;
}

function txRowBg(tx: TxEntry): string {
  if (tx.status === "exception" || tx.exception_code !== null) return "bg-[rgb(var(--color-danger-subtle))]";
  if (tx.fc === 6 || tx.fc === 16) return "bg-[rgb(var(--color-purple-subtle))]";
  return "";
}

function TransactionLog({ transactions, paused }: {
  transactions: TxEntry[];
  paused: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transactions, paused]);

  return (
    <div ref={scrollRef} className="h-full overflow-auto">
      <table className="w-full text-[11px] font-mono">
        <thead className="sticky top-0 bg-[rgb(var(--color-surface))]">
          <tr className="text-[rgb(var(--color-muted))] border-b border-[rgb(var(--color-border))]">
            <th className="px-2 py-1 text-left w-10">#</th>
            <th className="px-2 py-1 text-left w-20">Time</th>
            <th className="px-2 py-1 text-left w-10">FC</th>
            <th className="px-2 py-1 text-left">Request / Response</th>
            <th className="px-2 py-1 text-left w-20">Status</th>
            <th className="px-2 py-1 text-right w-16">RTT</th>
          </tr>
        </thead>
        <tbody>
          {transactions.length === 0 ? (
            <tr><td colSpan={6} className="px-2 py-4 text-center text-[rgb(var(--color-muted))]">No transactions yet</td></tr>
          ) : (
            transactions.map(tx => (
              <tr key={tx.seq} className={`border-t border-[rgb(var(--color-border-subtle))] ${txRowBg(tx)}`}>
                <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">{tx.seq}</td>
                <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">{fmtTime(tx.ts)}</td>
                <td className="px-2 py-0.5 text-[rgb(var(--color-accent))]">FC{tx.fc}</td>
                <td className="px-2 py-0.5 text-[rgb(var(--color-foreground))] truncate max-w-[200px]">@{tx.addr} {tx.response_summary}</td>
                <td className={`px-2 py-0.5 ${tx.status === "ok" ? "text-[rgb(var(--color-success))]" : "text-[rgb(var(--color-danger))]"}`}>
                  {tx.status}{tx.exception_code !== null ? ` e${tx.exception_code}` : ""}
                </td>
                <td className="px-2 py-0.5 text-right text-[rgb(var(--color-foreground))]">{fmtRtt(tx.rtt_ms)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── TrafficTab ─────────────────────────────────────────────────────────────────

function TrafficTab({
  sessionId,
  source,
}: {
  sessionId: string;
  source: "simulator" | "client";
}) {
  const [frames, setFrames]         = useState<ParsedFrame[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [logging, setLogging]       = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (source !== "client" || !sessionId) return;
    const dispose = createModbusTrafficWebSocket(sessionId, (frame) => {
      setFrames((prev) => {
        const next = [...prev, frame];
        return next.length > 500 ? next.slice(next.length - 500) : next;
      });
    });
    return dispose;
  }, [sessionId, source]);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [frames, autoScroll]);

  async function toggleLog() {
    const next = !logging;
    setLogging(next);
    const path = next
      ? `${import.meta.env.VITE_DATA_DIR ?? "."}/modbus_traffic_${sessionId}.jsonl`
      : undefined;
    try {
      await setModbusTrafficLog(sessionId, next, path);
    } catch {
      setLogging(logging); // revert on error
    }
  }

  if (source === "simulator") {
    return (
      <div className="flex items-center justify-center h-32">
        <span className="text-[10px] text-[rgb(var(--color-muted))]">
          Traffic capture only available for client sessions
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* toolbar */}
      <div className="flex items-center gap-2 px-1 py-1 border-b border-[rgb(var(--color-border))]">
        <span className="text-[10px] text-[rgb(var(--color-muted))] font-mono">
          {frames.length} frames
        </span>
        <button
          onClick={() => setAutoScroll((v) => !v)}
          className={`text-[10px] px-1.5 py-0.5 rounded border ${
            autoScroll
              ? "border-[rgb(var(--color-accent))] text-[rgb(var(--color-accent))]"
              : "border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))]"
          }`}
        >
          Auto-scroll
        </button>
        <button
          onClick={toggleLog}
          title={logging ? "Stop file logging" : "Start file logging (JSONL)"}
          className={`text-[10px] px-1.5 py-0.5 rounded border ${
            logging
              ? "border-[rgb(var(--color-danger))] text-[rgb(var(--color-danger))]"
              : "border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))]"
          }`}
        >
          {logging ? "● Log" : "Log"}
        </button>
        <button
          onClick={() => setFrames([])}
          className="text-[10px] px-1.5 py-0.5 rounded border border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))] ml-auto"
        >
          Clear
        </button>
      </div>

      {/* frame table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-[10px] font-mono">
          <thead className="sticky top-0 bg-[rgb(var(--color-surface))]">
            <tr className="text-[rgb(var(--color-muted))] uppercase text-[9px]">
              <th className="px-1 py-0.5 text-left w-28">Time</th>
              <th className="px-1 py-0.5 text-left w-6">Dir</th>
              <th className="px-1 py-0.5 text-left w-6">FC</th>
              <th className="px-1 py-0.5 text-left w-20">Addr / Count</th>
              <th className="px-1 py-0.5 text-left">Exception</th>
              <th className="px-1 py-0.5 text-left">Raw hex</th>
            </tr>
          </thead>
          <tbody>
            {frames.map((f, i) => (
              <tr
                key={i}
                className={
                  f.is_exception
                    ? "bg-[rgb(var(--color-danger-subtle))] text-[rgb(var(--color-danger))]"
                    : f.direction === "tx"
                    ? "text-[rgb(var(--color-foreground))]"
                    : "text-[rgb(var(--color-muted))]"
                }
              >
                <td className="px-1 py-px">{fmtMicros(f.ts_us)}</td>
                <td className="px-1 py-px">{f.direction.toUpperCase()}</td>
                <td className="px-1 py-px">{f.function_code.toString(16).padStart(2, "0").toUpperCase()}</td>
                <td className="px-1 py-px">
                  {f.start_address != null
                    ? `${f.start_address}×${f.quantity ?? "?"}`
                    : f.byte_count != null
                    ? `${f.byte_count}B`
                    : "—"}
                </td>
                <td className="px-1 py-px">
                  {f.exception_name ?? (f.parse_error ? `⚠ ${f.parse_error}` : "—")}
                </td>
                <td className="px-1 py-px truncate max-w-[120px]">
                  {f.raw_hex.slice(0, 24)}{f.raw_hex.length > 24 ? "…" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ── DiagToolbar ────────────────────────────────────────────────────────────────

interface DiagToolbarProps {
  sessions: string[];
  selectedSession: string;
  onSessionChange: (id: string) => void;
  source: "simulator" | "client";
  sessionObj: ModbusSession | undefined;
  fcTab: FcTabId;
  onFcTabChange: (tab: FcTabId) => void;
  paused: boolean;
  onTogglePause: () => void;
  onReadNow: () => void;
  showConfig: boolean;
  onToggleConfig: () => void;
  onConfigUpdated: () => void;
  configRef: React.RefObject<HTMLDivElement>;
}

function DiagToolbar({
  sessions, selectedSession, onSessionChange, source, sessionObj,
  fcTab, onFcTabChange, paused, onTogglePause, onReadNow,
  showConfig, onToggleConfig, onConfigUpdated, configRef,
}: DiagToolbarProps) {
  const statusColor =
    sessionObj?.status === "polling" || sessionObj?.status === "running"
      ? "text-[rgb(var(--color-success))]"
      : sessionObj?.status === "error"
      ? "text-[rgb(var(--color-danger))]"
      : "text-[rgb(var(--color-muted))]";

  return (
    <div className="shrink-0 h-9 flex items-center gap-1.5 px-2 border-b border-[rgb(var(--color-border))] bg-[rgb(var(--color-surface))]">
      {/* Session selector */}
      <select
        value={selectedSession}
        onChange={e => onSessionChange(e.target.value)}
        className="h-6 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-1.5 text-[11px] font-mono text-[rgb(var(--color-foreground))] focus:outline-none focus:border-[rgb(var(--color-accent))] max-w-[140px]"
      >
        {sessions.length === 0
          ? <option value="">— no sessions —</option>
          : sessions.map(s => <option key={s} value={s}>{s}</option>)
        }
      </select>

      {/* Status dot */}
      <span className={`text-[14px] leading-none select-none ${statusColor}`} title={sessionObj?.status ?? "unknown"}>●</span>

      {/* Divider */}
      <div className="w-px h-5 bg-[rgb(var(--color-border))] mx-0.5 shrink-0" />

      {/* FC segment buttons */}
      {FC_TABS.map(t => (
        <button
          key={t.label}
          onClick={() => onFcTabChange(t.label)}
          className={`h-6 px-2 rounded text-[11px] font-mono font-medium transition-colors ${
            fcTab === t.label
              ? "bg-[rgb(var(--color-accent-subtle))] text-[rgb(var(--color-accent))] border border-[rgb(var(--color-accent))]/40"
              : "text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))] border border-transparent"
          }`}
        >
          {t.label}
        </button>
      ))}

      {/* Divider */}
      <div className="w-px h-5 bg-[rgb(var(--color-border))] mx-0.5 shrink-0" />

      {/* Live toggle */}
      <button
        onClick={onTogglePause}
        className={`h-6 px-2 rounded text-[11px] font-medium transition-colors flex items-center gap-1 border ${
          paused
            ? "border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))]"
            : "border-[rgb(var(--color-success))]/50 text-[rgb(var(--color-success))]"
        }`}
        title={paused ? "Resume live polling" : "Pause polling"}
      >
        <span className="text-[10px]">{paused ? "○" : "●"}</span>
        Live
      </button>

      {/* Read Now */}
      <button
        onClick={onReadNow}
        className="h-6 px-2 rounded text-[11px] font-medium bg-[rgb(var(--color-accent-emphasis))] text-white hover:bg-[rgb(var(--color-accent-emphasis-hover))] transition-colors"
      >
        Read
      </button>

      {/* Config popover — pushed right */}
      {source === "client" && selectedSession && (
        <div className="relative ml-auto" ref={configRef}>
          <button
            onClick={onToggleConfig}
            className={`h-6 px-2 rounded text-[11px] font-medium transition-colors border ${
              showConfig
                ? "border-[rgb(var(--color-accent))]/60 text-[rgb(var(--color-accent))] bg-[rgb(var(--color-accent-subtle))]"
                : "border-[rgb(var(--color-border))] text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))]"
            }`}
            title="Session configuration"
          >
            ⚙ Config
          </button>
          {showConfig && (
            <div className="absolute right-0 top-full mt-1 z-50 w-80 bg-[rgb(var(--color-surface))] border border-[rgb(var(--color-border))] rounded-md shadow-xl overflow-y-auto max-h-[80vh]">
              <SessionConfigPanel
                sessionId={selectedSession}
                session={sessionObj}
                onUpdated={() => { onConfigUpdated(); onToggleConfig(); }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── StatsSidebar ───────────────────────────────────────────────────────────────

interface StatsSidebarProps {
  stats: DiagnosticsStats | null;
}

function StatsSidebar({ stats }: StatsSidebarProps) {
  const rtt    = stats?.rtt ?? { avg: 0, p50: 0, p95: 0, p99: 0 };
  const excTot = stats?.exceptions.reduce((s, e) => s + e.count, 0) ?? 0;

  return (
    <div className="w-80 shrink-0 flex flex-col gap-2 overflow-y-auto p-2 bg-[rgb(var(--color-background))] border-l border-[rgb(var(--color-border))]">
      {/* 2×3 KPI grid */}
      <div className="grid grid-cols-2 gap-1.5">
        <KpiCard label="Avg RTT"     value={fmtRtt(rtt.avg)} color="text-[rgb(var(--color-accent))]"   compact />
        <KpiCard label="p95 RTT"     value={fmtRtt(rtt.p95)} color="text-[rgb(var(--color-accent))]"   compact />
        <KpiCard label="p50 RTT"     value={fmtRtt(rtt.p50)} color="text-[rgb(var(--color-accent))]"   compact />
        <KpiCard label="p99 RTT"     value={fmtRtt(rtt.p99)} color="text-[rgb(var(--color-muted))]"    compact />
        <KpiCard label="Total Polls" value={String(stats?.total_polls ?? 0)} color="text-[rgb(var(--color-success))]" compact />
        <KpiCard label="Exceptions"  value={String(excTot)} color={excTot > 0 ? "text-[rgb(var(--color-danger))]" : "text-[rgb(var(--color-muted))]"} compact />
      </div>

      <div className="shrink-0"><RttTimeline data={stats?.timeline ?? []} /></div>
      <div className="shrink-0"><JitterPanel data={stats?.jitter} /></div>
      <div className="shrink-0"><ExceptionFrequency data={stats?.exceptions ?? []} /></div>
    </div>
  );
}

// ── StatusBar ──────────────────────────────────────────────────────────────────

interface StatusBarProps {
  stats: DiagnosticsStats | null;
  selectedSession: string;
}

function StatusBar({ stats, selectedSession }: StatusBarProps) {
  const polling = Boolean(stats && (stats.total_polls ?? 0) > 0);
  const rtt     = stats?.rtt;
  const jitter  = stats?.jitter;
  const excTot  = stats?.exceptions.reduce((s, e) => s + e.count, 0) ?? 0;

  return (
    <div className="shrink-0 h-6 flex items-center gap-3 px-3 border-t border-[rgb(var(--color-border))] bg-[rgb(var(--color-surface))] font-mono text-[10px] text-[rgb(var(--color-muted))] overflow-hidden">
      <span className={polling ? "text-[rgb(var(--color-success))]" : ""}>
        {polling ? "●" : "○"} {polling ? "polling" : "idle"}
      </span>
      {selectedSession && (
        <span>Session: <span className="text-[rgb(var(--color-foreground))]">{selectedSession}</span></span>
      )}
      {rtt && rtt.avg > 0 && (
        <>
          <span>Avg: <span className="text-[rgb(var(--color-foreground))]">{fmtRtt(rtt.avg)}</span></span>
          <span>p95: <span className="text-[rgb(var(--color-foreground))]">{fmtRtt(rtt.p95)}</span></span>
        </>
      )}
      {(stats?.total_polls ?? 0) > 0 && (
        <span>Polls: <span className="text-[rgb(var(--color-foreground))]">{stats!.total_polls}</span></span>
      )}
      {(stats?.req_rate ?? 0) > 0 && (
        <span>Rate: <span className="text-[rgb(var(--color-foreground))]">{stats!.req_rate.toFixed(1)}/s</span></span>
      )}
      {excTot > 0 && (
        <span className="text-[rgb(var(--color-danger))]">Exc: {excTot}</span>
      )}
      {jitter?.p95_jitter_ms != null && (
        <span>Jitter p95: <span className="text-[rgb(var(--color-foreground))]">{jitter.p95_jitter_ms.toFixed(1)}ms</span></span>
      )}
    </div>
  );
}

// ── Main ModbusDiagnostics export ──────────────────────────────────────────────

const LOG_HEIGHTS = [120, 180, 300, 400] as const;
type LogHeight = typeof LOG_HEIGHTS[number];

export function ModbusDiagnostics({ sessions, source }: ModbusDiagnosticsProps) {
  // Session state
  const [selectedSession, setSelectedSession] = useState<string>(sessions[0] ?? "");
  const [sessionObjects,  setSessionObjects]  = useState<ModbusSession[]>([]);

  // Diagnostics state
  const [stats,  setStats]  = useState<DiagnosticsStats | null>(null);
  const [error,  setError]  = useState("");
  const [paused, setPaused] = useState(false);

  // Toolbar state
  const [fcTab,      setFcTab]      = useState<FcTabId>("HR");
  const [showConfig, setShowConfig] = useState(false);
  const configRef = useRef<HTMLDivElement>(null);

  // Log panel state
  const [logHeight, setLogHeight] = useState<LogHeight>(180);
  const [logTab,    setLogTab]    = useState<"transactions" | "traffic" | "trend">("transactions");

  const cycleLogHeight = () => {
    setLogHeight(prev => {
      const idx = LOG_HEIGHTS.indexOf(prev);
      return LOG_HEIGHTS[(idx + 1) % LOG_HEIGHTS.length];
    });
  };

  // Session objects (client only)
  const refreshSessionObjects = useCallback(async () => {
    if (source !== "client") return;
    try { setSessionObjects(await fetchClientSessions()); } catch { /* ignore */ }
  }, [source]);

  useEffect(() => { refreshSessionObjects(); }, [refreshSessionObjects, sessions]);

  // Keep selectedSession in sync
  useEffect(() => {
    if (sessions.length > 0 && !sessions.includes(selectedSession)) setSelectedSession(sessions[0]);
  }, [sessions, selectedSession]);

  const selectedSessionObj = sessionObjects.find(s => s.session_id === selectedSession);

  // Diagnostics polling — inner fetch (no pause check, used by both poller and Read Now)
  const doFetchDiag = useCallback(async () => {
    if (!selectedSession) return;
    try {
      setStats(await getModbusDiagnostics(selectedSession));
      setError("");
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status && status >= 500) setError("Backend error fetching diagnostics.");
    }
  }, [selectedSession]);

  // Poller wrapper — respects paused flag
  const fetchDiag = useCallback(async () => {
    if (paused) return;
    return doFetchDiag();
  }, [paused, doFetchDiag]);

  useEffect(() => {
    setStats(null); setError("");
    if (!selectedSession) return;
    fetchDiag();
    const t = setInterval(fetchDiag, 1000);
    return () => clearInterval(t);
  }, [fetchDiag, selectedSession]);

  // Close config popover on outside click
  useEffect(() => {
    if (!showConfig) return;
    const handler = (e: MouseEvent) => {
      if (configRef.current && !configRef.current.contains(e.target as Node)) setShowConfig(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showConfig]);

  // CSV export
  const handleExportCsv = useCallback(() => {
    if (!stats) return;
    const headers = ["seq","ts","session_id","fc","addr","rtt_ms","status","exception_code","response_summary"];
    const rows = stats.transactions.map(tx =>
      [tx.seq, tx.ts, tx.session_id, tx.fc, tx.addr, tx.rtt_ms, tx.status,
       tx.exception_code ?? "", `"${(tx.response_summary ?? "").replace(/"/g, '""')}"`].join(",")
    );
    const csv  = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement("a"), { href: url, download: `modbus_transactions_${selectedSession}_${Date.now()}.csv` });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [stats, selectedSession]);

  const logHeightIcon = logHeight === 300 ? "▼" : logHeight === 120 ? "▲" : "↕";

  return (
    <div className="flex flex-col h-full overflow-hidden bg-[rgb(var(--color-background))] text-[rgb(var(--color-foreground))]">

      {/* Toolbar */}
      <DiagToolbar
        sessions={sessions}
        selectedSession={selectedSession}
        onSessionChange={setSelectedSession}
        source={source}
        sessionObj={selectedSessionObj}
        fcTab={fcTab}
        onFcTabChange={setFcTab}
        paused={paused}
        onTogglePause={() => setPaused(p => !p)}
        onReadNow={doFetchDiag}
        showConfig={showConfig}
        onToggleConfig={() => setShowConfig(s => !s)}
        onConfigUpdated={refreshSessionObjects}
        configRef={configRef}
      />

      {/* Error banner */}
      {error && (
        <div className="shrink-0 bg-[rgb(var(--color-danger-subtle))] border-b border-[rgb(var(--color-danger))]/30 px-3 py-1">
          <p className="text-xs text-[rgb(var(--color-danger))]">{error}</p>
        </div>
      )}

      {/* Middle: register pane + stats sidebar */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        <RegPane sessionId={selectedSession} source={source} fcTab={fcTab} />
        <StatsSidebar stats={stats} />
      </div>

      {/* Log panel */}
      <div
        className="shrink-0 flex flex-col border-t border-[rgb(var(--color-border))] overflow-hidden"
        style={{ height: logHeight }}
      >
        {/* Log tab bar */}
        <div className="flex items-center h-8 shrink-0 border-b border-[rgb(var(--color-border))] bg-[rgb(var(--color-surface))] px-1 gap-1">
          {(["transactions", "traffic", "trend"] as const).map(tab => (
            <button
              key={tab}
              onClick={() => { setLogTab(tab); if (tab === "trend") setLogHeight(400); }}
              className={`h-6 px-2.5 text-[11px] font-medium rounded-sm transition-colors ${
                logTab === tab
                  ? "bg-[rgb(var(--color-accent-subtle))] text-[rgb(var(--color-accent))]"
                  : "text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))]"
              }`}
            >
              {tab === "transactions" ? "Transactions" : tab === "traffic" ? "Traffic" : "Trend"}
            </button>
          ))}

          <div className="ml-auto flex items-center gap-1">
            {logTab === "transactions" && (
              <>
                <button
                  onClick={() => setPaused(p => !p)}
                  className={`h-6 px-2 rounded text-[11px] font-medium transition-colors ${
                    paused
                      ? "bg-[rgb(var(--color-accent-emphasis))] text-white"
                      : "text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))]"
                  }`}
                >
                  {paused ? "Resume" : "Pause"}
                </button>
                <button
                  onClick={handleExportCsv}
                  className="h-6 px-2 rounded text-[11px] text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))] transition-colors"
                >
                  CSV
                </button>
                <button
                  onClick={() => setStats(prev => prev ? { ...prev, transactions: [] } : prev)}
                  className="h-6 px-2 rounded text-[11px] text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-danger))] transition-colors"
                  title="Clear log"
                >
                  ✕
                </button>
              </>
            )}
            <button
              onClick={cycleLogHeight}
              className="h-6 px-2 rounded text-[11px] font-mono text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))] transition-colors"
              title={`Log height: ${logHeight}px — click to cycle`}
            >
              {logHeightIcon}
            </button>
          </div>
        </div>

        {/* Log content */}
        <div className="flex-1 overflow-hidden min-h-0">
          {logTab === "transactions" ? (
            <TransactionLog transactions={stats?.transactions ?? []} paused={paused} />
          ) : logTab === "traffic" ? (
            <TrafficTab sessionId={selectedSession} source={source} />
          ) : (
            <TrendChart sessionId={selectedSession ?? ""} source={source} />
          )}
        </div>
      </div>

      {/* Status bar */}
      <StatusBar stats={stats} selectedSession={selectedSession} />
    </div>
  );
}
