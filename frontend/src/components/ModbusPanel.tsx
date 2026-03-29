/**
 * ModbusPanel — five sub-tabs:
 *   Simulator   : start/stop simulated Modbus devices, view live registers
 *   Client      : connect to real/simulated devices, view polled registers
 *   Scanner     : scan network for Modbus TCP devices
 *   Device Maps : browse predefined maps, upload CSV/Excel device list
 *   Diagnostics : God's View — live register grid, KPI bar, RTT timeline
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchSimSessions, createSimSession, stopSimSession, fetchSimRegisters, writeSimRegister,
  fetchClientSessions, createClientSession, stopClientSession,
  fetchClientRegisters, clientReadNow, writeClientRegister,
  updateClientSession, getModbusRegisters, writeModbusRegister,
  runModbusScan, fetchModbusDeviceTypes, uploadModbusDeviceList,
  createSimFromDevices, createClientFromDevices,
  createModbusLiveWebSocket,
  type ModbusSession, type ModbusRegisterValue, type ScanResult, type DeviceTypeInfo,
  type RegisterEntry, type ModbusWsData,
} from "../lib/api";
import { ModbusDiagnostics } from "./ModbusDiagnostics";

// ── tiny shared components ──────────────────────────────────────────────────

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${color}`}>
      {text}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    running:    "bg-success-subtle text-success",
    polling:    "bg-success-subtle text-success",
    connecting: "bg-warning-subtle text-attention",
    error:      "bg-danger-subtle text-danger",
    stopped:    "bg-surface-hover text-muted",
  };
  return <Badge text={status} color={map[status] ?? "bg-surface-hover text-muted"} />;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">
      {children}
    </h3>
  );
}

function Input({
  label, value, onChange, placeholder, type = "text", className = "",
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 text-xs text-muted ${className}`}>
      {label}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-background border border-border rounded px-2 py-1.5 text-foreground text-xs placeholder-muted-dim focus:outline-none focus:border-accent"
      />
    </label>
  );
}

function Select({
  label, value, onChange, options,
}: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-background border border-border rounded px-2 py-1.5 text-foreground text-xs focus:outline-none focus:border-accent"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

function Btn({
  children, onClick, variant = "primary", disabled = false, className = "",
}: {
  children: React.ReactNode; onClick?: () => void;
  variant?: "primary" | "danger" | "ghost"; disabled?: boolean; className?: string;
}) {
  const cls = {
    primary: "bg-accent-emphasis hover:bg-accent-emphasis-hover text-white",
    danger:  "bg-danger-subtle hover:bg-danger-subtle text-danger",
    ghost:   "bg-transparent hover:bg-border-subtle text-muted border border-border",
  }[variant];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${cls} ${className}`}
    >
      {children}
    </button>
  );
}

// ── Register table ─────────────────────────────────────────────────────────

function RegisterTable({
  registers, onWrite,
}: {
  registers: ModbusRegisterValue[];
  onWrite?: (address: number, value: number) => void;
}) {
  const [writeAddr, setWriteAddr] = useState("");
  const [writeVal,  setWriteVal]  = useState("");

  if (!registers.length) {
    return <p className="text-xs text-muted-dim py-4 text-center">No register data yet.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="overflow-auto max-h-64 border border-border-subtle rounded">
        <table className="w-full text-xs font-mono">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-muted">
              <th className="px-2 py-1 text-left w-16">Addr</th>
              <th className="px-2 py-1 text-left">Name</th>
              <th className="px-2 py-1 text-right w-20">Value</th>
              <th className="px-2 py-1 text-left w-12">Unit</th>
              <th className="px-2 py-1 text-left w-10">Acc</th>
            </tr>
          </thead>
          <tbody>
            {registers.map((r) => (
              <tr key={r.address} className="border-t border-border-subtle hover:bg-surface">
                <td className="px-2 py-1 text-accent">{r.address}</td>
                <td className="px-2 py-1 text-foreground truncate max-w-[150px]" title={r.description || r.name}>
                  {r.name}
                </td>
                <td className="px-2 py-1 text-right">
                  {r.error ? (
                    <span className="text-danger">ERR</span>
                  ) : (
                    <span className="text-success">{r.value}</span>
                  )}
                </td>
                <td className="px-2 py-1 text-muted">{r.unit || "—"}</td>
                <td className="px-2 py-1 text-muted-extra">{r.access || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {onWrite && (
        <div className="flex gap-2 items-end">
          <Input label="Address" value={writeAddr} onChange={setWriteAddr} placeholder="40009" className="w-24" />
          <Input label="Value (raw)" value={writeVal} onChange={setWriteVal} placeholder="25000" className="w-28" />
          <Btn
            onClick={() => {
              const a = parseInt(writeAddr, 10);
              const v = parseInt(writeVal, 10);
              if (!isNaN(a) && !isNaN(v)) {
                onWrite(a, v);
                setWriteAddr(""); setWriteVal("");
              }
            }}
            className="mb-0.5"
          >
            Write
          </Btn>
        </div>
      )}
    </div>
  );
}

// ── SessionCard (shared by Simulator + Client) ─────────────────────────────

function SessionCard({
  session, registers, onStop, onRefresh, onWrite, isRefreshing,
}: {
  session: ModbusSession;
  registers: ModbusRegisterValue[];
  onStop: () => void;
  onRefresh: () => void;
  onWrite?: (address: number, value: number) => void;
  isRefreshing: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border rounded bg-background text-xs">
      <div className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-surface"
        onClick={() => setExpanded((x) => !x)}>
        <span className="text-foreground font-mono flex-1 truncate">
          {session.label}
        </span>
        <span className="text-muted-extra">{session.host}:{session.port}</span>
        <Badge text={`uid ${session.unit_id}`} color="bg-surface-hover text-muted-extra" />
        <Badge text={session.device_type || "generic"} color="bg-surface-hover text-muted" />
        <StatusBadge status={session.status} />
        <span onClick={(e) => e.stopPropagation()}>
          <Btn variant="ghost" onClick={() => onRefresh()} disabled={isRefreshing}>
            {isRefreshing ? "…" : "↻"}
          </Btn>
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <Btn variant="danger" onClick={() => onStop()}>
            Stop
          </Btn>
        </span>
        <span className="text-muted-dim">{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && (
        <div className="px-3 pb-3 border-t border-border-subtle">
          <div className="text-muted-extra mb-2 mt-2">
            {session.register_count} registers
            {session.poll_count !== undefined && ` · ${session.poll_count} polls`}
            {session.error_count !== undefined && session.error_count > 0 && (
              <span className="text-danger ml-2">{session.error_count} errors</span>
            )}
            {session.last_error && (
              <span className="text-danger ml-2 truncate">— {session.last_error}</span>
            )}
          </div>
          <RegisterTable registers={registers} onWrite={onWrite} />
        </div>
      )}
    </div>
  );
}

// ── ClientSessionCard — ModScan-style scan + settings edit ──────────────────

const FC_OPTIONS = [
  { value: "3",  label: "FC03 — Holding Registers" },
  { value: "4",  label: "FC04 — Input Registers" },
  { value: "1",  label: "FC01 — Coils" },
  { value: "2",  label: "FC02 — Discrete Inputs" },
];

const FC_DEFAULT_START: Record<string, number> = {
  "3": 40001, "4": 30001, "1": 1, "2": 10001,
};

const ALL_FCS: [number, string][] = [
  [1, "Coils"], [2, "Discrete In"], [3, "Holding Regs"], [4, "Input Regs"],
  [5, "Write Coil"], [6, "Write Reg"], [15, "Write Coils"], [16, "Write Regs"],
];

// ── Display format helpers ────────────────────────────────────────────────────

function formatRaw(raw: number, fmt: "dec" | "hex" | "bin"): string {
  if (fmt === "hex") return "0x" + raw.toString(16).toUpperCase().padStart(4, "0");
  if (fmt === "bin") return raw.toString(2).padStart(16, "0");
  return String(raw);
}

function decodeFloat32(hi: number, lo: number, byteOrder: string): string {
  const buf = new ArrayBuffer(4);
  const v   = new DataView(buf);
  const [a, b, c, d] = [(hi >> 8) & 0xFF, hi & 0xFF, (lo >> 8) & 0xFF, lo & 0xFF];
  const map: Record<string, [number, number, number, number]> = {
    ABCD: [a,b,c,d], BADC: [b,a,d,c], CDAB: [c,d,a,b], DCBA: [d,c,b,a],
  };
  (map[byteOrder] ?? map.ABCD).forEach((byte, i) => v.setUint8(i, byte));
  const f = v.getFloat32(0, false);
  return isFinite(f) ? f.toPrecision(6) : "NaN";
}

// ── QualityDot (inline — ModbusDiagnostics owns the canonical version) ───────

const QUALITY_COLORS_MP: Record<string, string> = {
  good:      "bg-green-500",
  bad:       "bg-red-500",
  uncertain: "bg-yellow-500",
  stale:     "bg-gray-500",
};

function QualityDot({ quality }: { quality?: string }) {
  const q = quality ?? "uncertain";
  return (
    <span
      title={q}
      className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${QUALITY_COLORS_MP[q] ?? "bg-gray-500"}`}
    />
  );
}

function ClientSessionCard({
  session, onStop, onSessionUpdated,
}: {
  session: ModbusSession;
  onStop: () => void;
  onSessionUpdated: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [innerTab, setInnerTab] = useState<"scan" | "settings">("scan");

  // ── Live register stream (WebSocket) ─────────────────────────────────────
  const [liveRegs, setLiveRegs] = useState<RegisterEntry[]>([]);

  useEffect(() => {
    if (!expanded) { setLiveRegs([]); return; }
    const dispose = createModbusLiveWebSocket(
      session.session_id,
      (msg: ModbusWsData) => {
        if (msg.type === "data" && msg.registers) {
          setLiveRegs(msg.registers as RegisterEntry[]);
        }
      },
      1.0,
    );
    return dispose;
  }, [expanded, session.session_id]);

  // ── Scan panel state ──────────────────────────────────────────────────────
  const [fc, setFc]             = useState("3");
  const [startAddr, setStartAddr] = useState("40001");
  const [count, setCount]       = useState("20");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [scanRegs, setScanRegs] = useState<any[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanErr, setScanErr]   = useState("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Write / display state ──────────────────────────────────────────────────
  type DisplayFmt = "dec" | "hex" | "bin" | "float";
  const [displayFmt,   setDisplayFmt]   = useState<DisplayFmt>("dec");
  const [scanView,     setScanView]     = useState<"scan" | "live">("scan");
  const [writeRowAddr, setWriteRowAddr] = useState<number | null>(null);
  const [writeRowVal,  setWriteRowVal]  = useState("");
  const [blockOpen,    setBlockOpen]    = useState(false);
  const [blockAddr,    setBlockAddr]    = useState("");
  const [blockVals,    setBlockVals]    = useState("");
  const [writeMsg,     setWriteMsg]     = useState<{ ok: boolean; text: string } | null>(null);
  const writeMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Update start addr default when FC changes
  const handleFcChange = (v: string) => {
    setFc(v);
    setStartAddr(String(FC_DEFAULT_START[v] ?? 1));
  };

  const doScan = useCallback(async () => {
    const start = parseInt(startAddr, 10);
    const n     = Math.min(Math.max(parseInt(count, 10) || 20, 1), 125);
    if (isNaN(start)) { setScanErr("Invalid start address"); return; }
    setScanErr(""); setScanning(true);
    try {
      const res = await getModbusRegisters("client", session.session_id, parseInt(fc), start, n);
      setScanRegs(res.registers ?? []);
    } catch (e: any) {
      setScanErr(e?.response?.data?.detail ?? String(e));
    }
    setScanning(false);
  }, [session.session_id, fc, startAddr, count]);

  const showWriteMsg = (ok: boolean, text: string) => {
    if (writeMsgTimer.current) clearTimeout(writeMsgTimer.current);
    setWriteMsg({ ok, text });
    writeMsgTimer.current = setTimeout(() => setWriteMsg(null), 2500);
  };

  const doWrite = useCallback(async (writeFC: number, addr: number, values: number[]) => {
    try {
      const res = await writeModbusRegister("client", session.session_id, { fc: writeFC, addr, values });
      if (res.ok) {
        showWriteMsg(true, `FC${writeFC} @ ${addr} ✓`);
        await doScan();
      } else {
        showWriteMsg(false, res.error ?? "Write failed");
      }
    } catch (e: any) {
      showWriteMsg(false, e?.response?.data?.detail ?? String(e));
    }
    setWriteRowAddr(null);
    setWriteRowVal("");
  }, [session.session_id, doScan]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-refresh control
  useEffect(() => {
    if (autoRefresh && expanded && innerTab === "scan") {
      doScan();
      intervalRef.current = setInterval(doScan, 1000);
    } else {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [autoRefresh, expanded, innerTab, doScan]);

  // ── Settings panel state ──────────────────────────────────────────────────
  const [pollInterval, setPollInterval] = useState(String(session.poll_interval ?? 10));
  const [byteOrder,    setByteOrder]    = useState<string>(session.byte_order ?? "ABCD");
  const [enabledFCs,   setEnabledFCs]   = useState<Set<number>>(
    new Set(session.enabled_fcs ?? [1, 2, 3, 4, 5, 6, 15, 16]),
  );
  const [saving, setSaving]   = useState(false);
  const [saveOk, setSaveOk]   = useState(false);
  const [saveErr, setSaveErr] = useState("");

  const toggleFC = (f: number) => setEnabledFCs(prev => {
    const next = new Set(prev);
    next.has(f) ? next.delete(f) : next.add(f);
    return next;
  });

  const handleSave = async () => {
    setSaving(true); setSaveOk(false); setSaveErr("");
    try {
      await updateClientSession(session.session_id, {
        poll_interval: parseFloat(pollInterval) || 10,
        byte_order: byteOrder,
        enabled_fcs: [...enabledFCs],
      });
      setSaveOk(true);
      onSessionUpdated();
      setTimeout(() => setSaveOk(false), 2000);
    } catch (e: any) {
      setSaveErr(e?.response?.data?.detail ?? String(e));
    }
    setSaving(false);
  };

  return (
    <div className="border border-border rounded bg-background text-xs">
      {/* Header row */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-surface"
        onClick={() => setExpanded(x => !x)}
      >
        <span className="text-foreground font-mono flex-1 truncate">{session.label || `${session.host}:${session.port}`}</span>
        <span className="text-muted-extra">{session.host}:{session.port}</span>
        <Badge text={`uid ${session.unit_id}`} color="bg-surface-hover text-muted-extra" />
        {session.device_type && <Badge text={session.device_type} color="bg-surface-hover text-muted" />}
        <StatusBadge status={session.status} />
        {session.last_error && (
          <span className="text-danger truncate max-w-[160px]" title={session.last_error}>
            {session.last_error}
          </span>
        )}
        <span onClick={e => e.stopPropagation()}>
          <Btn variant="danger" onClick={onStop}>Stop</Btn>
        </span>
        <span className="text-muted-dim">{expanded ? "▲" : "▼"}</span>
      </div>

      {expanded && (
        <div className="border-t border-border-subtle">
          {/* Inner tab bar */}
          <div className="flex border-b border-border-subtle">
            {(["scan", "settings"] as const).map(t => (
              <button
                key={t}
                onClick={() => setInnerTab(t)}
                className={`px-4 py-1.5 text-[10px] font-medium uppercase tracking-wider border-b-2 transition-colors ${
                  innerTab === t
                    ? "border-accent text-accent"
                    : "border-transparent text-muted hover:text-foreground"
                }`}
              >
                {t === "scan" ? "Live Scan" : "Settings"}
              </button>
            ))}
          </div>

          {/* ── SCAN TAB ── */}
          {innerTab === "scan" && (() => {
            const isCoilFC   = fc === "1" || fc === "2";
            const isFloatMode = displayFmt === "float" && (fc === "3" || fc === "4");
            return (
            <div className="p-3 space-y-3">
              {/* Controls */}
              <div className="flex flex-wrap gap-2 items-end">
                <label className="flex flex-col gap-1 text-[10px] text-[rgb(var(--color-muted))]">
                  Register Type
                  <select
                    value={fc}
                    onChange={e => handleFcChange(e.target.value)}
                    className="bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-2 py-1.5 text-[rgb(var(--color-foreground))] text-xs focus:outline-none focus:border-[rgb(var(--color-accent))]"
                  >
                    {FC_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-[10px] text-[rgb(var(--color-muted))]">
                  Start Address
                  <input
                    type="number"
                    value={startAddr}
                    onChange={e => setStartAddr(e.target.value)}
                    className="w-24 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-2 py-1.5 text-[rgb(var(--color-foreground))] text-xs font-mono focus:outline-none focus:border-[rgb(var(--color-accent))]"
                  />
                </label>
                <label className="flex flex-col gap-1 text-[10px] text-[rgb(var(--color-muted))]">
                  Count (max 125)
                  <input
                    type="number"
                    value={count}
                    onChange={e => setCount(e.target.value)}
                    min={1} max={125}
                    className="w-20 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-2 py-1.5 text-[rgb(var(--color-foreground))] text-xs font-mono focus:outline-none focus:border-[rgb(var(--color-accent))]"
                  />
                </label>
                {/* Display format */}
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-[rgb(var(--color-muted))]">Format</span>
                  <div className="flex rounded border border-[rgb(var(--color-border))] overflow-hidden">
                    {(["dec","hex","bin","float"] as const).map(f => (
                      <button
                        key={f}
                        onClick={() => setDisplayFmt(f)}
                        className={`px-2 py-1.5 text-[10px] font-mono transition-colors ${
                          displayFmt === f
                            ? "bg-[rgb(var(--color-accent-emphasis))] text-white"
                            : "bg-[rgb(var(--color-background))] text-[rgb(var(--color-muted))] hover:bg-[rgb(var(--color-surface))]"
                        }`}
                      >{f.toUpperCase()}</button>
                    ))}
                  </div>
                </div>
                <div className="flex gap-2 items-end pb-0.5">
                  <Btn onClick={doScan} disabled={scanning}>
                    {scanning ? "Reading…" : "Read"}
                  </Btn>
                  <label className="flex items-center gap-1.5 text-[10px] text-[rgb(var(--color-muted))] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={autoRefresh}
                      onChange={e => setAutoRefresh(e.target.checked)}
                      className="w-3 h-3"
                    />
                    Auto (1 s)
                  </label>
                </div>
              </div>

              {/* Error banner */}
              {scanErr && (
                <div className="bg-[rgb(var(--color-danger-subtle))] border border-[rgb(var(--color-danger))] rounded px-3 py-2">
                  <p className="text-[rgb(var(--color-danger))] text-[10px] font-mono break-all">{scanErr}</p>
                </div>
              )}

              {/* Scan/Live toggle + write feedback */}
              <div className="flex items-center justify-between">
                <div className="flex rounded border border-[rgb(var(--color-border-subtle))] overflow-hidden">
                  {(["scan","live"] as const).map(sv => (
                    <button
                      key={sv}
                      onClick={() => setScanView(sv)}
                      className={`px-3 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors ${
                        scanView === sv
                          ? "bg-[rgb(var(--color-accent-emphasis))] text-white"
                          : "bg-[rgb(var(--color-background))] text-[rgb(var(--color-muted))] hover:bg-[rgb(var(--color-surface))]"
                      }`}
                    >
                      {sv === "scan" ? `Scan (${scanRegs.length})` : `Live (${liveRegs.length})`}
                    </button>
                  ))}
                </div>
                {writeMsg && (
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${
                    writeMsg.ok
                      ? "text-[rgb(var(--color-success))] bg-[rgb(var(--color-success-subtle))]"
                      : "text-[rgb(var(--color-danger))] bg-[rgb(var(--color-danger-subtle))]"
                  }`}>{writeMsg.ok ? "✓" : "✗"} {writeMsg.text}</span>
                )}
              </div>

              {/* ── SCAN RESULTS view ── */}
              {scanView === "scan" && (
                <>
                  {scanRegs.length > 0 && (
                    <div className="overflow-auto max-h-96 border border-[rgb(var(--color-border-subtle))] rounded">
                      <table className="w-full text-[10px] font-mono">
                        <thead className="sticky top-0 bg-[rgb(var(--color-surface))]">
                          <tr className="text-[rgb(var(--color-muted))]">
                            <th className="px-2 py-1 text-left w-16">Addr</th>
                            {isCoilFC ? (
                              <th className="px-2 py-1 text-center w-16">State</th>
                            ) : isFloatMode ? (
                              <th className="px-2 py-1 text-right w-28">Float32</th>
                            ) : (
                              <>
                                <th className="px-2 py-1 text-right w-28">Value</th>
                                {(r => r)(fc === "3") && <th className="px-2 py-1 w-24"></th>}
                              </>
                            )}
                            <th className="px-2 py-1 text-left w-10">Unit</th>
                            <th className="px-2 py-1 text-left">Name</th>
                          </tr>
                        </thead>
                        <tbody>
                          {isFloatMode
                            ? (() => {
                                const rows = [];
                                for (let i = 0; i < scanRegs.length; i += 2) {
                                  const hi = scanRegs[i];
                                  const lo = scanRegs[i + 1];
                                  const floatStr = lo
                                    ? decodeFloat32(hi.raw ?? 0, lo.raw ?? 0, session.byte_order ?? "ABCD")
                                    : String(hi.raw ?? 0);
                                  rows.push(
                                    <tr key={hi.address} className="border-t border-[rgb(var(--color-border-subtle))] hover:bg-[rgb(var(--color-surface))]">
                                      <td className="px-2 py-0.5 text-[rgb(var(--color-accent))]">{hi.address}{lo ? `–${lo.address}` : ""}</td>
                                      <td className="px-2 py-0.5 text-right text-[rgb(var(--color-success))]">{floatStr}</td>
                                      <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">{hi.unit || "—"}</td>
                                      <td className="px-2 py-0.5 text-[rgb(var(--color-foreground))] truncate max-w-[120px]" title={hi.name}>{hi.name || "—"}</td>
                                    </tr>
                                  );
                                }
                                return rows;
                              })()
                            : scanRegs.map((r: any) => {
                                const isOn = r.raw !== 0;
                                return (
                                  <tr key={r.address} className="border-t border-[rgb(var(--color-border-subtle))] hover:bg-[rgb(var(--color-surface))]">
                                    <td className="px-2 py-0.5 text-[rgb(var(--color-accent))]">{r.address}</td>

                                    {isCoilFC ? (
                                      <td className="px-2 py-0.5 text-center">
                                        <span
                                          onClick={fc === "1" ? () => doWrite(5, r.address, [isOn ? 0x0000 : 0xFF00]) : undefined}
                                          className={`px-2 py-0.5 rounded text-[10px] font-bold select-none ${
                                            isOn ? "bg-green-700 text-green-100" : "bg-[rgb(var(--color-surface-hover))] text-[rgb(var(--color-muted))]"
                                          } ${fc === "1" ? "cursor-pointer hover:opacity-80" : ""}`}
                                          title={fc === "1" ? (isOn ? "Click to turn OFF" : "Click to turn ON") : undefined}
                                        >{isOn ? "ON" : "OFF"}</span>
                                      </td>
                                    ) : (
                                      <td className="px-2 py-0.5 text-right text-[rgb(var(--color-success))]">
                                        {formatRaw(r.raw ?? 0, displayFmt as "dec" | "hex" | "bin")}
                                      </td>
                                    )}

                                    <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">{r.unit || "—"}</td>
                                    <td className="px-2 py-0.5 text-[rgb(var(--color-foreground))] truncate max-w-[120px]" title={r.name}>{r.name || "—"}</td>

                                    {/* Write cell — only FC3 holding registers are writable */}
                                    {fc === "3" && (
                                      <td className="px-2 py-0.5">
                                        {writeRowAddr === r.address ? (
                                          <div className="flex gap-1 items-center">
                                            <input
                                              autoFocus
                                              type="number"
                                              value={writeRowVal}
                                              onChange={e => setWriteRowVal(e.target.value)}
                                              onKeyDown={e => {
                                                if (e.key === "Enter") {
                                                  const v = parseInt(writeRowVal, 10);
                                                  if (!isNaN(v)) doWrite(6, r.address, [v]);
                                                }
                                                if (e.key === "Escape") { setWriteRowAddr(null); setWriteRowVal(""); }
                                              }}
                                              className="w-20 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-accent))] rounded px-1 py-0.5 text-[rgb(var(--color-foreground))] text-[10px] font-mono focus:outline-none"
                                              placeholder={String(r.raw ?? 0)}
                                            />
                                            <button
                                              onClick={() => { const v = parseInt(writeRowVal, 10); if (!isNaN(v)) doWrite(6, r.address, [v]); }}
                                              className="text-[9px] px-1.5 py-0.5 rounded bg-[rgb(var(--color-accent-emphasis))] text-white"
                                            >W</button>
                                            <button
                                              onClick={() => { setWriteRowAddr(null); setWriteRowVal(""); }}
                                              className="text-[9px] px-1.5 py-0.5 rounded bg-[rgb(var(--color-surface-hover))] text-[rgb(var(--color-muted))] border border-[rgb(var(--color-border))]"
                                            >✕</button>
                                          </div>
                                        ) : (
                                          <button
                                            onClick={() => { setWriteRowAddr(r.address); setWriteRowVal(String(r.raw ?? 0)); }}
                                            className="text-[9px] px-1.5 py-0.5 rounded bg-[rgb(var(--color-surface-hover))] text-[rgb(var(--color-muted))] border border-[rgb(var(--color-border))] hover:text-[rgb(var(--color-foreground))] hover:border-[rgb(var(--color-accent))]"
                                          >Write</button>
                                        )}
                                      </td>
                                    )}
                                  </tr>
                                );
                              })
                          }
                        </tbody>
                      </table>
                    </div>
                  )}
                  {scanRegs.length === 0 && !scanErr && (
                    <div className="text-center py-3">
                      {session.status === "connecting" && (
                        <p className="text-[rgb(var(--color-warning))] text-[10px] animate-pulse">Session connecting to {session.host}:{session.port}…</p>
                      )}
                      {session.status === "error" && session.last_error && (
                        <p className="text-[rgb(var(--color-danger))] text-[10px]">Session error: {session.last_error}</p>
                      )}
                      {(session.status === "polling" || session.status === "idle") && (
                        <p className="text-[rgb(var(--color-muted))] text-[10px]">Press <strong>Read</strong> to fetch registers.</p>
                      )}
                      {!["connecting","error","polling","idle"].includes(session.status) && (
                        <p className="text-[rgb(var(--color-muted))] text-[10px]">Session status: {session.status} — press Read to try.</p>
                      )}
                    </div>
                  )}

                  {/* FC16 Write Block — holding registers only */}
                  {fc === "3" && (
                    <div className="border border-[rgb(var(--color-border-subtle))] rounded">
                      <button
                        onClick={() => setBlockOpen(x => !x)}
                        className="w-full flex items-center justify-between px-3 py-1.5 text-[10px] text-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-foreground))] hover:bg-[rgb(var(--color-surface))]"
                      >
                        <span className="font-medium uppercase tracking-wider">Write Block (FC16)</span>
                        <span>{blockOpen ? "▲" : "▼"}</span>
                      </button>
                      {blockOpen && (
                        <div className="px-3 pb-3 pt-1 flex flex-wrap gap-2 items-end border-t border-[rgb(var(--color-border-subtle))]">
                          <label className="flex flex-col gap-1 text-[10px] text-[rgb(var(--color-muted))]">
                            Start Addr
                            <input
                              type="number"
                              value={blockAddr}
                              onChange={e => setBlockAddr(e.target.value)}
                              placeholder="40001"
                              className="w-24 bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-2 py-1.5 text-[rgb(var(--color-foreground))] text-[10px] font-mono focus:outline-none focus:border-[rgb(var(--color-accent))]"
                            />
                          </label>
                          <label className="flex flex-col gap-1 text-[10px] text-[rgb(var(--color-muted))] flex-1 min-w-[8rem]">
                            Values (space-separated)
                            <input
                              type="text"
                              value={blockVals}
                              onChange={e => setBlockVals(e.target.value)}
                              placeholder="100 200 300"
                              className="bg-[rgb(var(--color-background))] border border-[rgb(var(--color-border))] rounded px-2 py-1.5 text-[rgb(var(--color-foreground))] text-[10px] font-mono focus:outline-none focus:border-[rgb(var(--color-accent))]"
                            />
                          </label>
                          <Btn
                            onClick={() => {
                              const addr = parseInt(blockAddr, 10);
                              const vals = blockVals.trim().split(/\s+/).map(Number).filter(n => !isNaN(n));
                              if (!isNaN(addr) && vals.length > 0) doWrite(16, addr, vals);
                            }}
                          >Write FC16</Btn>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* ── LIVE POLLED view ── */}
              {scanView === "live" && (
                liveRegs.length > 0 ? (
                  <div className="overflow-auto max-h-96 border border-[rgb(var(--color-border))] rounded text-xs font-mono">
                    <table className="w-full">
                      <thead className="sticky top-0 bg-[rgb(var(--color-surface))]">
                        <tr className="text-[rgb(var(--color-muted))] border-b border-[rgb(var(--color-border))]">
                          <th className="text-left px-2 py-1">Addr</th>
                          <th className="text-left px-2 py-1">Name</th>
                          <th className="text-right px-2 py-1">Value</th>
                          <th className="text-left px-2 py-1">Unit</th>
                          <th className="px-2 py-1">Q</th>
                        </tr>
                      </thead>
                      <tbody>
                        {liveRegs.map((r: RegisterEntry) => (
                          <tr key={r.address} className="border-b border-[rgb(var(--color-border-subtle))] hover:bg-[rgb(var(--color-surface))]">
                            <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">{r.address}</td>
                            <td className="px-2 py-0.5 text-[rgb(var(--color-foreground))] truncate max-w-[120px]" title={r.name}>{r.name}</td>
                            <td className="px-2 py-0.5 text-right text-[rgb(var(--color-accent))]">
                              {"error" in r ? <span className="text-[rgb(var(--color-danger))]">ERR</span> : r.value}
                            </td>
                            <td className="px-2 py-0.5 text-[rgb(var(--color-muted))]">{r.unit}</td>
                            <td className="px-2 py-0.5 text-center">
                              <QualityDot quality={r.quality} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-center text-[10px] text-[rgb(var(--color-muted))] py-4">
                    No live polled data yet — waiting for background poll.
                  </p>
                )
              )}
            </div>
            );
          })()}

          {/* ── SETTINGS TAB ── */}
          {innerTab === "settings" && (
            <div className="p-3 space-y-3">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <label className="flex flex-col gap-1 text-[10px] text-muted">
                  Poll Interval (s)
                  <input
                    type="number"
                    value={pollInterval}
                    onChange={e => setPollInterval(e.target.value)}
                    className="bg-background border border-border rounded px-2 py-1.5 text-foreground text-xs focus:outline-none focus:border-accent"
                  />
                </label>
                <label className="flex flex-col gap-1 text-[10px] text-muted">
                  Byte Order
                  <select
                    value={byteOrder}
                    onChange={e => setByteOrder(e.target.value)}
                    className="bg-background border border-border rounded px-2 py-1.5 text-foreground text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="ABCD">ABCD — Big/Big (default)</option>
                    <option value="BADC">BADC — Byte-swap</option>
                    <option value="CDAB">CDAB — Word-swap (Schneider)</option>
                    <option value="DCBA">DCBA — Little/Little</option>
                  </select>
                </label>
              </div>
              <div>
                <p className="text-[10px] text-muted uppercase tracking-wider mb-1.5">Enabled Function Codes</p>
                <div className="flex flex-wrap gap-3">
                  {ALL_FCS.map(([f, lbl]) => (
                    <label key={f} className="flex items-center gap-1.5 text-[10px] text-foreground cursor-pointer">
                      <input
                        type="checkbox"
                        checked={enabledFCs.has(f)}
                        onChange={() => toggleFC(f)}
                        className="w-3 h-3"
                      />
                      <span className="text-accent font-mono">FC{f}</span>
                      <span className="text-muted">{lbl}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex gap-2 items-center">
                <Btn onClick={handleSave} disabled={saving}>{saving ? "Saving…" : "Save Settings"}</Btn>
                {saveOk && <span className="text-success text-[10px]">✓ Saved</span>}
                {saveErr && <span className="text-danger text-[10px]">{saveErr}</span>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── SIMULATOR TAB ──────────────────────────────────────────────────────────

function SimulatorTab({ onSessionsChange }: { onSessionsChange?: (ids: string[]) => void }) {
  const [sessions, setSessions]       = useState<ModbusSession[]>([]);
  const [registers, setRegisters]     = useState<Record<string, ModbusRegisterValue[]>>({});
  const [refreshing, setRefreshing]   = useState<Record<string, boolean>>({});
  const [deviceTypes, setDeviceTypes] = useState<DeviceTypeInfo[]>([]);
  const safeSetDeviceTypes = (v: unknown) => setDeviceTypes(Array.isArray(v) ? v : []);

  // Create form
  const [dtKey,      setDtKey]      = useState("sma");
  const [port,       setPort]       = useState("5020");
  const [unitId,     setUnitId]     = useState("1");
  const [label,      setLabel]      = useState("");
  const [creating,   setCreating]   = useState(false);
  const [error,      setError]      = useState("");

  const refresh = useCallback(async () => {
    try { setSessions(await fetchSimSessions()); } catch {}
  }, []);

  useEffect(() => {
    refresh();
    fetchModbusDeviceTypes().then(safeSetDeviceTypes).catch(() => {});
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    onSessionsChange?.(sessions.map((s) => s.session_id));
  }, [sessions, onSessionsChange]);

  const refreshRegs = async (sid: string) => {
    setRefreshing((p) => ({ ...p, [sid]: true }));
    try {
      const regs = await fetchSimRegisters(sid);
      setRegisters((p) => ({ ...p, [sid]: regs }));
    } catch {}
    setRefreshing((p) => ({ ...p, [sid]: false }));
  };

  const handleCreate = async () => {
    setError(""); setCreating(true);
    try {
      await createSimSession({
        device_type: dtKey, label, port: parseInt(port, 10) || 5020,
        unit_id: parseInt(unitId, 10) || 1,
      });
      setLabel("");
      await refresh();
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    }
    setCreating(false);
  };

  const handleStop = async (sid: string) => {
    await stopSimSession(sid).catch(() => {});
    setRegisters((p) => { const c = {...p}; delete c[sid]; return c; });
    await refresh();
  };

  const handleWrite = async (sid: string, addr: number, val: number) => {
    await writeSimRegister(sid, addr, val).catch(() => {});
    await refreshRegs(sid);
  };

  const dtOptions = deviceTypes.map((d) => ({ value: d.key, label: `${d.key} (${d.register_count} regs)` }));

  return (
    <div className="flex flex-col gap-4">
      {/* Create form */}
      <div className="border border-border rounded p-3 bg-background">
        <SectionTitle>Start Simulator</SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {dtOptions.length > 0 ? (
            <Select label="Device Type" value={dtKey} onChange={setDtKey} options={dtOptions} />
          ) : (
            <Input label="Device Type" value={dtKey} onChange={setDtKey} placeholder="sma" />
          )}
          <Input label="Port" value={port} onChange={setPort} placeholder="5020" type="number" />
          <Input label="Unit ID" value={unitId} onChange={setUnitId} placeholder="1" type="number" />
          <Input label="Label (optional)" value={label} onChange={setLabel} placeholder="e.g. SMA Roof" />
        </div>
        {error && <p className="text-danger text-xs mt-2">{error}</p>}
        <Btn onClick={handleCreate} disabled={creating} className="mt-3">
          {creating ? "Starting…" : "Start Simulator"}
        </Btn>
      </div>

      {/* Session list */}
      <div>
        <SectionTitle>Running Simulator Sessions ({sessions.length})</SectionTitle>
        {sessions.length === 0 && (
          <p className="text-xs text-muted-dim py-2">No active simulator sessions.</p>
        )}
        <div className="space-y-2">
          {sessions.map((s) => (
            <SessionCard
              key={s.session_id}
              session={s}
              registers={registers[s.session_id] ?? []}
              onStop={() => handleStop(s.session_id)}
              onRefresh={() => refreshRegs(s.session_id)}
              onWrite={(a, v) => handleWrite(s.session_id, a, v)}
              isRefreshing={!!refreshing[s.session_id]}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── CLIENT TAB ─────────────────────────────────────────────────────────────

function ClientTab({ onSessionsChange }: { onSessionsChange?: (ids: string[]) => void }) {
  const [sessions,  setSessions]  = useState<ModbusSession[]>([]);
  const [registers, setRegisters] = useState<Record<string, ModbusRegisterValue[]>>({});
  const [refreshing,setRefreshing]= useState<Record<string, boolean>>({});
  const [deviceTypes, setDeviceTypes] = useState<DeviceTypeInfo[]>([]);
  const safeSetDeviceTypes = (v: unknown) => setDeviceTypes(Array.isArray(v) ? v : []);

  // Form — basic
  const [host,    setHost]    = useState("127.0.0.1");
  const [port,    setPort]    = useState("502");
  const [unitId,  setUnitId]  = useState("1");
  const [dtKey,   setDtKey]   = useState("");
  const [label,   setLabel]   = useState("");
  const [poll,    setPoll]    = useState("10");
  const [creating,setCreating]= useState(false);
  const [error,   setError]   = useState("");

  // Form — transport / serial
  const [transport,   setTransport]   = useState<"tcp" | "rtu" | "ascii">("tcp");
  const [serialPort,  setSerialPort]  = useState("");
  const [baudrate,    setBaudrate]    = useState("9600");
  const [bytesize,    setBytesize]    = useState("8");
  const [parity,      setParity]      = useState<"N" | "E" | "O">("N");
  const [stopbits,    setStopbits]    = useState("1");
  const [maxConn,     setMaxConn]     = useState("1");

  // Form — advanced
  const [byteOrder,   setByteOrder]   = useState<"ABCD" | "BADC" | "CDAB" | "DCBA">("ABCD");
  const [zeroBased,   setZeroBased]   = useState(true);
  const [blockGap,    setBlockGap]    = useState("1");
  const [blockMaxSize,setBlockMaxSize]= useState("0");
  const [connTimeout, setConnTimeout] = useState("5");
  const [enabledFCs,  setEnabledFCs]  = useState<Set<number>>(new Set([1, 2, 3, 4, 5, 6, 15, 16]));
  const [showAdvanced,setShowAdvanced]= useState(false);

  const toggleFC = (fc: number) => {
    setEnabledFCs(prev => {
      const next = new Set(prev);
      if (next.has(fc)) next.delete(fc);
      else next.add(fc);
      return next;
    });
  };

  const refresh = useCallback(async () => {
    try { setSessions(await fetchClientSessions()); } catch {}
  }, []);

  useEffect(() => {
    refresh();
    fetchModbusDeviceTypes().then(safeSetDeviceTypes).catch(() => {});
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    onSessionsChange?.(sessions.map((s) => s.session_id));
  }, [sessions, onSessionsChange]);

  const refreshRegs = async (sid: string, force = false) => {
    setRefreshing((p) => ({ ...p, [sid]: true }));
    try {
      const regs = force ? await clientReadNow(sid) : await fetchClientRegisters(sid);
      setRegisters((p) => ({ ...p, [sid]: regs }));
    } catch {}
    setRefreshing((p) => ({ ...p, [sid]: false }));
  };

  const handleCreate = async () => {
    setError(""); setCreating(true);
    try {
      await createClientSession({
        host, port: parseInt(port, 10) || 502,
        unit_id: parseInt(unitId, 10) || 1,
        device_type: dtKey || undefined, label,
        poll_interval: parseFloat(poll) || 10,
        transport,
        serial_port: serialPort || undefined,
        baudrate: transport !== "tcp" ? (parseInt(baudrate) || undefined) : undefined,
        bytesize: transport !== "tcp" ? (parseInt(bytesize) || undefined) : undefined,
        parity: transport !== "tcp" ? parity : undefined,
        stopbits: transport !== "tcp" ? (parseInt(stopbits) || undefined) : undefined,
        timeout: parseInt(connTimeout) || undefined,
        byte_order: byteOrder,
        zero_based_addressing: zeroBased,
        block_read_max_gap: parseInt(blockGap),
        block_read_max_size: parseInt(blockMaxSize) || 0,
        enabled_fcs: [...enabledFCs],
        max_connections: transport === "tcp" ? parseInt(maxConn) : undefined,
      });
      setLabel("");
      await refresh();
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    }
    setCreating(false);
  };

  const handleStop = async (sid: string) => {
    await stopClientSession(sid).catch(() => {});
    setRegisters((p) => { const c = {...p}; delete c[sid]; return c; });
    await refresh();
  };

  const handleWrite = async (sid: string, addr: number, val: number) => {
    await writeClientRegister(sid, addr, val).catch(() => {});
    await refreshRegs(sid);
  };

  const dtOptions = deviceTypes.map((d) => ({ value: d.key, label: `${d.key} (${d.register_count} regs)` }));

  return (
    <div className="flex flex-col gap-4">
      <div className="border border-border rounded p-3 bg-background">
        <SectionTitle>Connect to Modbus Device</SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Input label="Host / IP" value={host} onChange={setHost} placeholder="192.168.1.10" />
          <Input label="Port" value={port} onChange={setPort} placeholder="502" type="number" />
          <Input label="Unit ID" value={unitId} onChange={setUnitId} placeholder="1" type="number" />
          {dtOptions.length > 0 ? (
            <Select
              label="Device Type (optional)"
              value={dtKey}
              onChange={setDtKey}
              options={[
                { value: "", label: "\u2014 none (on-demand reads) \u2014" },
                ...dtOptions,
              ]}
            />
          ) : (
            <Input label="Device Type (optional)" value={dtKey} onChange={setDtKey} placeholder="sma, plc, meter\u2026" />
          )}
          <Input label="Label (optional)" value={label} onChange={setLabel} placeholder="e.g. Inverter 1" />
          <Input label="Poll interval (s)" value={poll} onChange={setPoll} placeholder="10" type="number" />
        </div>

        {/* Transport section */}
        <div className="mt-3 border-t border-border-subtle pt-3">
          <p className="text-[10px] text-muted uppercase tracking-wider mb-2">Transport</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Select
              label="Transport"
              value={transport}
              onChange={(v) => setTransport(v as "tcp" | "rtu" | "ascii")}
              options={[
                { value: "tcp",   label: "TCP" },
                { value: "rtu",   label: "RTU" },
                { value: "ascii", label: "ASCII" },
              ]}
            />
            {transport === "tcp" && (
              <Select
                label="Max Connections"
                value={maxConn}
                onChange={setMaxConn}
                options={Array.from({ length: 10 }, (_, i) => ({
                  value: String(i + 1), label: String(i + 1),
                }))}
              />
            )}
            {(transport === "rtu" || transport === "ascii") && (
              <>
                <Input
                  label="Serial Port"
                  value={serialPort}
                  onChange={setSerialPort}
                  placeholder="COM3 or /dev/ttyUSB0"
                />
                <Select
                  label="Baudrate"
                  value={baudrate}
                  onChange={setBaudrate}
                  options={[
                    { value: "1200",   label: "1200" },
                    { value: "2400",   label: "2400" },
                    { value: "4800",   label: "4800" },
                    { value: "9600",   label: "9600" },
                    { value: "19200",  label: "19200" },
                    { value: "38400",  label: "38400" },
                    { value: "57600",  label: "57600" },
                    { value: "115200", label: "115200" },
                  ]}
                />
                <Select
                  label="Data Bits"
                  value={bytesize}
                  onChange={setBytesize}
                  options={[
                    { value: "7", label: "7" },
                    { value: "8", label: "8" },
                  ]}
                />
                <Select
                  label="Parity"
                  value={parity}
                  onChange={(v) => setParity(v as "N" | "E" | "O")}
                  options={[
                    { value: "N", label: "None" },
                    { value: "E", label: "Even" },
                    { value: "O", label: "Odd" },
                  ]}
                />
                <Select
                  label="Stop Bits"
                  value={stopbits}
                  onChange={setStopbits}
                  options={[
                    { value: "1", label: "1" },
                    { value: "2", label: "2" },
                  ]}
                />
              </>
            )}
          </div>
        </div>

        {/* Advanced section (collapsible) */}
        <div className="mt-3 border-t border-border-subtle pt-2">
          <button
            type="button"
            onClick={() => setShowAdvanced((x) => !x)}
            className="text-[10px] text-[rgb(var(--color-accent))] hover:text-accent uppercase tracking-wider flex items-center gap-1 focus:outline-none"
          >
            <span>{showAdvanced ? "▾" : "▸"}</span>
            Advanced
          </button>
          {showAdvanced && (
            <div className="mt-2 space-y-3">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Select
                  label="Byte Order"
                  value={byteOrder}
                  onChange={(v) => setByteOrder(v as "ABCD" | "BADC" | "CDAB" | "DCBA")}
                  options={[
                    { value: "ABCD", label: "ABCD — Big/Big (default)" },
                    { value: "BADC", label: "BADC — Byte-swap" },
                    { value: "CDAB", label: "CDAB — Word-swap (Schneider/Carlo Gavazzi)" },
                    { value: "DCBA", label: "DCBA — Little/Little" },
                  ]}
                />
                <Input
                  label="Block Read Max Gap"
                  value={blockGap}
                  onChange={setBlockGap}
                  placeholder="1"
                  type="number"
                />
                <Input
                  label="Block Read Max Size (0=auto)"
                  value={blockMaxSize}
                  onChange={setBlockMaxSize}
                  placeholder="0"
                  type="number"
                />
                <Input
                  label="Connection Timeout (s)"
                  value={connTimeout}
                  onChange={setConnTimeout}
                  placeholder="5"
                  type="number"
                />
                <label className="flex flex-col gap-1 text-xs text-muted">
                  Zero-Based Addressing
                  <div className="flex items-center gap-2 mt-1">
                    <input
                      type="checkbox"
                      checked={zeroBased}
                      onChange={(e) => setZeroBased(e.target.checked)}
                      className="accent-[rgb(var(--color-accent))] w-3.5 h-3.5"
                    />
                    <span className="text-[rgb(var(--color-foreground))] text-[10px]">{zeroBased ? "Enabled" : "Disabled"}</span>
                  </div>
                </label>
              </div>
              {/* FC enable/disable */}
              <div>
                <p className="text-[10px] text-muted uppercase tracking-wider mb-1.5">Enabled Function Codes</p>
                <div className="flex flex-wrap gap-3">
                  {([
                    [1, "Coils"],
                    [2, "Discrete In"],
                    [3, "Holding Regs"],
                    [4, "Input Regs"],
                    [5, "Write Coil"],
                    [6, "Write Reg"],
                    [15, "Write Coils"],
                    [16, "Write Regs"],
                  ] as [number, string][]).map(([fc, fcLabel]) => (
                    <label key={fc} className="flex items-center gap-1.5 text-[10px] text-[rgb(var(--color-foreground))] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={enabledFCs.has(fc)}
                        onChange={() => toggleFC(fc)}
                        className="accent-[rgb(var(--color-accent))] w-3 h-3"
                      />
                      <span className="text-[rgb(var(--color-accent))] font-mono">FC{fc}</span>
                      <span className="text-muted">{fcLabel}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {error && <p className="text-danger text-xs mt-2">{error}</p>}
        <Btn onClick={handleCreate} disabled={creating} className="mt-3">
          {creating ? "Connecting…" : "Connect Client"}
        </Btn>
      </div>

      <div>
        <SectionTitle>Active Client Sessions ({sessions.length})</SectionTitle>
        {sessions.length === 0 && (
          <p className="text-xs text-muted-dim py-2">No active client sessions.</p>
        )}
        <div className="space-y-2">
          {sessions.map((s) => (
            <ClientSessionCard
              key={s.session_id}
              session={s}
              onStop={() => handleStop(s.session_id)}
              onSessionUpdated={refresh}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── SCANNER TAB ────────────────────────────────────────────────────────────

function ScannerTab() {
  const [targets, setTargets]   = useState("192.168.1.0/24");
  const [ports,   setPorts]     = useState("502");
  const [uids,    setUids]      = useState("1,2,3,4");
  const [timeout, setTimeout_]  = useState("2");
  const [scanning, setScanning] = useState(false);
  const [results,  setResults]  = useState<ScanResult[] | null>(null);
  const [error,    setError]    = useState("");

  const handleScan = async () => {
    setError(""); setScanning(true); setResults(null);
    try {
      const portList = ports.split(",").map((p) => parseInt(p.trim(), 10)).filter(Boolean);
      const uidList  = uids.split(",").map((u) => parseInt(u.trim(), 10)).filter(Boolean);
      const res = await runModbusScan({
        targets, ports: portList, unit_ids: uidList,
        timeout: parseFloat(timeout) || 2,
      });
      setResults(res.results);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    }
    setScanning(false);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="border border-border rounded p-3 bg-background">
        <SectionTitle>Scan Parameters</SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Input label="Targets (CIDR or IPs)" value={targets} onChange={setTargets}
            placeholder="192.168.1.0/24" className="col-span-2 sm:col-span-2" />
          <Input label="Ports (comma)" value={ports} onChange={setPorts} placeholder="502,5020" />
          <Input label="Unit IDs (comma)" value={uids} onChange={setUids} placeholder="1,2,3,4" />
          <Input label="Timeout (s)" value={timeout} onChange={setTimeout_} placeholder="2" type="number" />
        </div>
        {error && <p className="text-danger text-xs mt-2">{error}</p>}
        <Btn onClick={handleScan} disabled={scanning} className="mt-3">
          {scanning ? "Scanning…" : "Scan Network"}
        </Btn>
        {scanning && (
          <p className="text-xs text-attention mt-2 animate-pulse">
            Scanning {targets} — this may take a while for large ranges…
          </p>
        )}
      </div>

      {results !== null && (
        <div>
          <SectionTitle>Results — {results.length} device{results.length !== 1 ? "s" : ""} found</SectionTitle>
          {results.length === 0 ? (
            <p className="text-xs text-muted-dim py-2">No Modbus devices found on the scanned range.</p>
          ) : (
            <div className="overflow-auto border border-border-subtle rounded">
              <table className="w-full text-xs font-mono">
                <thead className="bg-surface">
                  <tr className="text-muted">
                    <th className="px-3 py-1.5 text-left">Host</th>
                    <th className="px-3 py-1.5 text-left w-14">Port</th>
                    <th className="px-3 py-1.5 text-left w-14">UID</th>
                    <th className="px-3 py-1.5 text-left">Device Type (guess)</th>
                    <th className="px-3 py-1.5 text-left">Regs @0-3</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={i} className="border-t border-border-subtle hover:bg-surface">
                      <td className="px-3 py-1.5 text-accent">{r.host}</td>
                      <td className="px-3 py-1.5 text-foreground">{r.port}</td>
                      <td className="px-3 py-1.5 text-foreground">{r.unit_id}</td>
                      <td className="px-3 py-1.5 text-success">{r.device_type_guess}</td>
                      <td className="px-3 py-1.5 text-muted">
                        {Object.entries(r.regs).map(([a, v]) => `${a}:${v}`).join(" ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── DEVICE MAPS TAB ────────────────────────────────────────────────────────

function DeviceMapsTab() {
  const [deviceTypes, setDeviceTypes]   = useState<DeviceTypeInfo[]>([]);
  const safeSetDeviceTypes = (v: unknown) => setDeviceTypes(Array.isArray(v) ? v : []);
  const [uploading,   setUploading]     = useState(false);
  const [uploadResult, setUploadResult] = useState<any>(null);
  const [uploadError,  setUploadError]  = useState("");
  const [simPort,    setSimPort]        = useState("5020");
  const [simming,    setSimming]        = useState(false);
  const [simResult,  setSimResult]      = useState<any>(null);
  const [clienting,  setClienting]      = useState(false);
  const [clientResult, setClientResult] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchModbusDeviceTypes().then(safeSetDeviceTypes).catch(() => {});
  }, []);

  const handleUpload = async (file: File) => {
    setUploadError(""); setUploading(true); setUploadResult(null);
    try {
      const res = await uploadModbusDeviceList(file);
      setUploadResult(res);
    } catch (e: any) {
      setUploadError(e?.response?.data?.detail ?? String(e));
    }
    setUploading(false);
  };

  const handleSimFromDevices = async () => {
    if (!uploadResult?.devices) return;
    setSimming(true);
    try {
      const res = await createSimFromDevices(uploadResult.devices, parseInt(simPort, 10) || 5020);
      setSimResult(res);
    } catch (e: any) {
      setUploadError(e?.response?.data?.detail ?? String(e));
    }
    setSimming(false);
  };

  const handleClientFromDevices = async () => {
    if (!uploadResult?.devices) return;
    setClienting(true);
    try {
      const res = await createClientFromDevices(uploadResult.devices, 10);
      setClientResult(res);
    } catch (e: any) {
      setUploadError(e?.response?.data?.detail ?? String(e));
    }
    setClienting(false);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Upload device list */}
      <div className="border border-border rounded p-3 bg-background">
        <SectionTitle>Upload Device List (CSV / Excel)</SectionTitle>
        <p className="text-muted-extra text-xs mb-3">
          Columns: ip, port, unit_id, device_type, device_name, description.{" "}
          <a href="/api/modbus/devices/template" className="text-accent hover:underline" download>
            Download template
          </a>
        </p>
        <div className="flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.xlsm,.xls"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
          />
          <Btn onClick={() => fileRef.current?.click()} disabled={uploading} variant="ghost">
            {uploading ? "Parsing…" : "Choose File"}
          </Btn>
          {uploadResult && (
            <span className="text-success text-xs">
              ✓ {uploadResult.device_count} devices parsed from {uploadResult.filename}
            </span>
          )}
        </div>
        {uploadError && <p className="text-danger text-xs mt-2">{uploadError}</p>}

        {uploadResult?.devices && (
          <div className="mt-3 space-y-2">
            {/* Preview table */}
            <div className="overflow-auto max-h-48 border border-border-subtle rounded">
              <table className="w-full text-xs font-mono">
                <thead className="bg-surface sticky top-0">
                  <tr className="text-muted">
                    <th className="px-2 py-1 text-left">IP</th>
                    <th className="px-2 py-1 text-left w-12">Port</th>
                    <th className="px-2 py-1 text-left w-10">UID</th>
                    <th className="px-2 py-1 text-left">Type</th>
                    <th className="px-2 py-1 text-left">Name</th>
                    <th className="px-2 py-1 text-left">Map</th>
                    <th className="px-2 py-1 text-right w-12">Regs</th>
                  </tr>
                </thead>
                <tbody>
                  {uploadResult.devices.map((d: any, i: number) => (
                    <tr key={i} className="border-t border-border-subtle hover:bg-surface">
                      <td className="px-2 py-1 text-accent">{d.ip}</td>
                      <td className="px-2 py-1 text-foreground">{d.port}</td>
                      <td className="px-2 py-1 text-foreground">{d.unit_id}</td>
                      <td className="px-2 py-1 text-muted">{d.device_type || "—"}</td>
                      <td className="px-2 py-1 text-foreground">{d.device_name || "—"}</td>
                      <td className="px-2 py-1 text-success">{d.map_key}</td>
                      <td className="px-2 py-1 text-right text-foreground">{d.register_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Bulk actions */}
            <div className="flex gap-3 items-center pt-1">
              <Btn onClick={handleSimFromDevices} disabled={simming}>
                {simming ? "Creating…" : "Simulate All"}
              </Btn>
              <Input label="" value={simPort} onChange={setSimPort} placeholder="base port" type="number" className="w-28" />
              <Btn onClick={handleClientFromDevices} disabled={clienting} variant="ghost">
                {clienting ? "Connecting…" : "Connect All as Clients"}
              </Btn>
            </div>
            {simResult && (
              <p className="text-success text-xs">✓ Created {simResult.created} simulator sessions</p>
            )}
            {clientResult && (
              <p className="text-success text-xs">✓ Created {clientResult.created} client sessions</p>
            )}
          </div>
        )}
      </div>

      {/* Predefined maps */}
      <div>
        <SectionTitle>Predefined Register Maps ({deviceTypes.length})</SectionTitle>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {deviceTypes.map((dt) => (
            <div key={dt.key} className="border border-border rounded p-2 bg-background text-xs">
              <div className="font-mono text-accent">{dt.key}</div>
              <div className="text-muted">{(dt as any).label || dt.key}</div>
              <div className="text-muted-extra mt-0.5">{dt.register_count} registers</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main Panel ─────────────────────────────────────────────────────────────

const SUBTABS = [
  { id: "simulator",   label: "Simulator"   },
  { id: "client",      label: "Client"      },
  { id: "scanner",     label: "Scanner"     },
  { id: "maps",        label: "Device Maps" },
  { id: "diagnostics", label: "Diagnostics" },
] as const;

type SubTab = typeof SUBTABS[number]["id"];

export function ModbusPanel() {
  const [activeSubTab, setActiveSubTab] = useState<SubTab>("simulator");
  const [simSessionIds,    setSimSessionIds]    = useState<string[]>([]);
  const [clientSessionIds, setClientSessionIds] = useState<string[]>([]);

  const diagSessions = [...clientSessionIds, ...simSessionIds];
  const diagSource: "client" | "simulator" =
    clientSessionIds.length > 0 ? "client" : "simulator";

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sub-tab nav */}
      <nav className="flex gap-0 border-b border-border bg-surface shrink-0">
        {SUBTABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setActiveSubTab(id)}
            className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeSubTab === id
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeSubTab === "simulator"   && <SimulatorTab onSessionsChange={setSimSessionIds} />}
        {activeSubTab === "client"      && <ClientTab onSessionsChange={setClientSessionIds} />}
        {activeSubTab === "scanner"     && <ScannerTab />}
        {activeSubTab === "maps"        && <DeviceMapsTab />}
        {activeSubTab === "diagnostics" && (
          <ModbusDiagnostics sessions={diagSessions} source={diagSource} />
        )}
      </div>
    </div>
  );
}
