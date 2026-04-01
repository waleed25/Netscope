/**
 * StatisticsModal — Wireshark-accurate Statistics dialogs.
 *
 * Views (matching Wireshark Statistics menu):
 *   Summary             — capture file properties, packet/byte totals
 *   Protocol Hierarchy  — tree of protocols with %, packets, bytes
 *   Conversations       — IPv4 / TCP / UDP conversation tables
 *   Endpoints           — IPv4 / TCP / UDP endpoint tables
 *   Packet Lengths      — histogram of frame sizes
 *   I/O Graph           — packets and bytes over time (SVG)
 *
 * All stats are derived client-side from the Packet[] array passed in.
 */

import { useState, useMemo, useCallback } from "react";
import { X, ChevronRight, ChevronDown } from "lucide-react";
import type { Packet } from "../store/useStore";

// ── Shared style constants ────────────────────────────────────────────────────

const BG       = "#0d1117";
const SURFACE  = "#161b22";
const ELEVATED = "#1c2128";
const BORDER   = "#30363d";
const TEXT     = "#e6edf3";
const MUTED    = "#8b949e";
const ACCENT   = "#58a6ff";
const SUCCESS  = "#3fb950";
const WARNING  = "#e3b341";

// ── Types ─────────────────────────────────────────────────────────────────────

export type StatView =
  | "summary"
  | "hierarchy"
  | "conversations"
  | "endpoints"
  | "lengths"
  | "iograph";

interface Props {
  packets: Packet[];
  initialView?: StatView;
  onClose: () => void;
}

// ── Helper: parse timestamp string to seconds ─────────────────────────────────

function parseTime(t: string | undefined): number {
  if (!t) return 0;
  // "HH:MM:SS.mmm" or plain number string
  const parts = t.split(":");
  if (parts.length === 3) {
    return +parts[0] * 3600 + +parts[1] * 60 + +parts[2];
  }
  return parseFloat(t) || 0;
}

function fmtBytes(b: number): string {
  if (b >= 1_073_741_824) return (b / 1_073_741_824).toFixed(2) + " GB";
  if (b >= 1_048_576)     return (b / 1_048_576).toFixed(2)     + " MB";
  if (b >= 1024)          return (b / 1024).toFixed(2)          + " kB";
  return b + " B";
}

function fmtDuration(secs: number): string {
  if (secs < 0.001) return "< 1 ms";
  if (secs < 1)     return (secs * 1000).toFixed(1) + " ms";
  if (secs < 60)    return secs.toFixed(3) + " s";
  const m = Math.floor(secs / 60);
  const s = (secs % 60).toFixed(1);
  return `${m}m ${s}s`;
}

// ── Sortable table header ─────────────────────────────────────────────────────

type SortDir = "asc" | "desc";

function SortTh({
  label, col, sort, onSort, align = "left",
}: {
  label: string; col: string; sort: [string, SortDir]; onSort: (c: string) => void; align?: string;
}) {
  const active = sort[0] === col;
  return (
    <th
      onClick={() => onSort(col)}
      className="cursor-pointer select-none px-2 py-1 whitespace-nowrap hover:text-[#e6edf3] transition-colors"
      style={{ color: active ? ACCENT : MUTED, textAlign: align as any, fontWeight: 500, fontSize: 11 }}
    >
      {label}
      {active && <span style={{ marginLeft: 3 }}>{sort[1] === "desc" ? "↓" : "↑"}</span>}
    </th>
  );
}

function useSort(initial: string, dir: SortDir = "desc") {
  const [sort, setSort] = useState<[string, SortDir]>([initial, dir]);
  const toggle = useCallback((col: string) => {
    setSort(([c, d]) => col === c ? [c, d === "desc" ? "asc" : "desc"] : [col, "desc"]);
  }, []);
  return [sort, toggle] as const;
}

// ─────────────────────────────────────────────────────────────────────────────
// VIEW: Summary
// ─────────────────────────────────────────────────────────────────────────────

function SummaryView({ packets }: { packets: Packet[] }) {
  const stats = useMemo(() => {
    if (!packets.length) return null;
    const times  = packets.map(p => parseTime(p.time)).filter(Boolean);
    const tFirst = Math.min(...times);
    const tLast  = Math.max(...times);
    const dur    = tLast - tFirst;
    const bytes  = packets.reduce((s, p) => s + (p.length ?? 0), 0);
    const avgPkt = bytes / packets.length;
    const rate   = dur > 0 ? packets.length / dur : 0;
    const bps    = dur > 0 ? (bytes * 8) / dur : 0;

    // Protocol breakdown
    const protoCount: Record<string, number> = {};
    for (const p of packets) {
      const k = p.protocol ?? "Unknown";
      protoCount[k] = (protoCount[k] ?? 0) + 1;
    }
    const topProtos = Object.entries(protoCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);

    return { total: packets.length, bytes, avgPkt, dur, rate, bps, topProtos };
  }, [packets]);

  if (!stats) return <Empty msg="No packets captured yet." />;

  const Row = ({ label, value }: { label: string; value: string }) => (
    <tr>
      <td className="py-1.5 pr-4 font-mono text-[11px]" style={{ color: MUTED }}>{label}</td>
      <td className="py-1.5 font-mono text-[12px]" style={{ color: TEXT }}>{value}</td>
    </tr>
  );

  return (
    <div className="flex flex-col gap-5 p-5 overflow-y-auto h-full">
      <Section title="Capture">
        <table>
          <tbody>
            <Row label="Total packets"    value={stats.total.toLocaleString()} />
            <Row label="Total bytes"      value={fmtBytes(stats.bytes)} />
            <Row label="Duration"         value={fmtDuration(stats.dur)} />
            <Row label="Avg packet size"  value={`${stats.avgPkt.toFixed(1)} bytes`} />
            <Row label="Avg packet rate"  value={`${stats.rate.toFixed(1)} pkts/s`} />
            <Row label="Avg bit rate"     value={`${(stats.bps / 1000).toFixed(1)} kbps`} />
          </tbody>
        </table>
      </Section>

      <Section title="Top Protocols">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-left py-1 pr-4 text-[11px]" style={{ color: MUTED, fontWeight: 500 }}>Protocol</th>
              <th className="text-right py-1 pr-4 text-[11px]" style={{ color: MUTED, fontWeight: 500 }}>Packets</th>
              <th className="text-right py-1 text-[11px]"      style={{ color: MUTED, fontWeight: 500 }}>%</th>
            </tr>
          </thead>
          <tbody>
            {stats.topProtos.map(([proto, count]) => (
              <tr key={proto}>
                <td className="py-0.5 pr-4 font-mono text-[11px]" style={{ color: ACCENT }}>{proto}</td>
                <td className="py-0.5 pr-4 text-right font-mono text-[12px]" style={{ color: TEXT }}>{count.toLocaleString()}</td>
                <td className="py-0.5 text-right font-mono text-[12px]" style={{ color: MUTED }}>
                  {((count / stats.total) * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VIEW: Protocol Hierarchy
// ─────────────────────────────────────────────────────────────────────────────

interface HierNode {
  name: string;
  packets: number;
  bytes: number;
  children: HierNode[];
  expanded: boolean;
}

function HierarchyView({ packets }: { packets: Packet[] }) {
  const tree = useMemo(() => {
    // Build flat protocol → {count, bytes} map first
    const map: Record<string, { packets: number; bytes: number }> = {};
    for (const p of packets) {
      // Use layers array for multi-level; fall back to protocol string
      const layers: string[] = p.layers?.length
        ? p.layers
        : p.protocol ? [p.protocol] : ["Unknown"];

      // Also split protocol strings like "ETH:IP:TCP" if layers not present
      const chain = layers.length > 1 ? layers : (p.protocol ?? "Unknown").split(/[:/]/).filter(Boolean);

      for (const l of chain) {
        const k = l.toUpperCase();
        if (!map[k]) map[k] = { packets: 0, bytes: 0 };
        map[k].packets++;
        map[k].bytes += p.length ?? 0;
      }
    }
    return Object.entries(map)
      .map(([name, v]) => ({ name, ...v }))
      .sort((a, b) => b.packets - a.packets);
  }, [packets]);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const total = packets.length;
  const totalBytes = packets.reduce((s, p) => s + (p.length ?? 0), 0);

  if (!tree.length) return <Empty msg="No packets captured yet." />;

  return (
    <div className="overflow-auto h-full">
      <table className="w-full border-collapse text-[12px] font-mono">
        <thead className="sticky top-0" style={{ background: ELEVATED }}>
          <tr>
            {["Protocol", "% Packets", "Packets", "% Bytes", "Bytes", "Bits/s"].map(h => (
              <th key={h} className="px-3 py-2 text-left text-[11px] border-b"
                  style={{ color: MUTED, fontWeight: 500, borderColor: BORDER }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tree.map((row) => (
            <tr key={row.name}
                className="hover:bg-[#1c2128] transition-colors cursor-pointer"
                onClick={() => setExpanded(s => {
                  const n = new Set(s);
                  n.has(row.name) ? n.delete(row.name) : n.add(row.name);
                  return n;
                })}>
              <td className="px-3 py-1 font-semibold" style={{ color: ACCENT }}>{row.name}</td>
              <td className="px-3 py-1 text-right" style={{ color: TEXT }}>
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block h-1.5 rounded-full" style={{
                    width: Math.max(2, (row.packets / total) * 60),
                    background: ACCENT, opacity: 0.5,
                  }} />
                  {((row.packets / total) * 100).toFixed(2)}%
                </span>
              </td>
              <td className="px-3 py-1 text-right" style={{ color: TEXT }}>{row.packets.toLocaleString()}</td>
              <td className="px-3 py-1 text-right" style={{ color: MUTED }}>
                {totalBytes ? ((row.bytes / totalBytes) * 100).toFixed(2) + "%" : "—"}
              </td>
              <td className="px-3 py-1 text-right" style={{ color: MUTED }}>{fmtBytes(row.bytes)}</td>
              <td className="px-3 py-1 text-right" style={{ color: MUTED }}>—</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VIEW: Conversations
// ─────────────────────────────────────────────────────────────────────────────

type ConvTab = "IPv4" | "TCP" | "UDP";

interface ConvRow {
  addrA: string; addrB: string;
  pktsAB: number; pktsBA: number;
  bytesAB: number; bytesBA: number;
  start: number; duration: number;
}

function buildConversations(packets: Packet[], mode: ConvTab): ConvRow[] {
  const map = new Map<string, ConvRow>();

  for (const p of packets) {
    if (!p.src_ip || !p.dst_ip) continue;
    const proto = (p.protocol ?? "").toLowerCase();
    if (mode === "TCP" && proto !== "tcp") continue;
    if (mode === "UDP" && proto !== "udp") continue;

    const sp = p.src_port ? `:${p.src_port}` : "";
    const dp = p.dst_port ? `:${p.dst_port}` : "";
    const a  = mode === "IPv4" ? p.src_ip : `${p.src_ip}${sp}`;
    const b  = mode === "IPv4" ? p.dst_ip : `${p.dst_ip}${dp}`;

    // Canonical key: sort so A < B
    const [ka, kb] = a < b ? [a, b] : [b, a];
    const key = `${ka}↔${kb}`;
    const dir = a === ka; // true = A→B, false = B→A

    const t = parseTime(p.time);
    if (!map.has(key)) {
      map.set(key, { addrA: ka, addrB: kb, pktsAB: 0, pktsBA: 0, bytesAB: 0, bytesBA: 0, start: t, duration: 0 });
    }
    const row = map.get(key)!;
    const bytes = p.length ?? 0;
    if (dir) { row.pktsAB++; row.bytesAB += bytes; }
    else      { row.pktsBA++; row.bytesBA += bytes; }
    row.duration = Math.max(row.duration, t - row.start);
  }

  return Array.from(map.values());
}

function ConversationsView({ packets }: { packets: Packet[] }) {
  const [tab, setTab] = useState<ConvTab>("IPv4");
  const [sort, toggleSort] = useSort("pktsAB");

  const rows = useMemo(() => {
    const data = buildConversations(packets, tab);
    const [col, dir] = sort;
    return [...data].sort((a: any, b: any) => {
      const v = b[col] - a[col];
      return dir === "desc" ? v : -v;
    });
  }, [packets, tab, sort]);

  const tabs: ConvTab[] = ["IPv4", "TCP", "UDP"];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TabBar tabs={tabs} active={tab} onChange={t => setTab(t as ConvTab)} />
      {rows.length === 0 ? <Empty msg={`No ${tab} conversations found.`} /> : (
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-[11px] font-mono">
            <thead className="sticky top-0" style={{ background: ELEVATED }}>
              <tr>
                <SortTh label="Address A" col="addrA" sort={sort} onSort={toggleSort} />
                <SortTh label="→ Pkts"    col="pktsAB" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="→ Bytes"   col="bytesAB" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="← Pkts"    col="pktsBA" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="← Bytes"   col="bytesBA" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Total Pkts" col="pktsAB" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Duration"  col="duration" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Address B" col="addrB" sort={sort} onSort={toggleSort} />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b hover:bg-[#1c2128] transition-colors"
                    style={{ borderColor: BORDER }}>
                  <td className="px-2 py-0.5" style={{ color: ACCENT }}>{r.addrA}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: TEXT }}>{r.pktsAB.toLocaleString()}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: MUTED }}>{fmtBytes(r.bytesAB)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: TEXT }}>{r.pktsBA.toLocaleString()}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: MUTED }}>{fmtBytes(r.bytesBA)}</td>
                  <td className="px-2 py-0.5 text-right font-semibold" style={{ color: TEXT }}>
                    {(r.pktsAB + r.pktsBA).toLocaleString()}
                  </td>
                  <td className="px-2 py-0.5 text-right" style={{ color: MUTED }}>{fmtDuration(r.duration)}</td>
                  <td className="px-2 py-0.5" style={{ color: WARNING }}>{r.addrB}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <StatusBar count={rows.length} label={`${tab} conversations`} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VIEW: Endpoints
// ─────────────────────────────────────────────────────────────────────────────

type EndpTab = "IPv4" | "TCP" | "UDP";

interface EndpRow {
  addr: string;
  txPkts: number; rxPkts: number;
  txBytes: number; rxBytes: number;
}

function buildEndpoints(packets: Packet[], mode: EndpTab): EndpRow[] {
  const map = new Map<string, EndpRow>();

  const get = (addr: string) => {
    if (!map.has(addr)) map.set(addr, { addr, txPkts: 0, rxPkts: 0, txBytes: 0, rxBytes: 0 });
    return map.get(addr)!;
  };

  for (const p of packets) {
    if (!p.src_ip || !p.dst_ip) continue;
    const proto = (p.protocol ?? "").toLowerCase();
    if (mode === "TCP" && proto !== "tcp") continue;
    if (mode === "UDP" && proto !== "udp") continue;

    const sp  = p.src_port ? `:${p.src_port}` : "";
    const dp  = p.dst_port ? `:${p.dst_port}` : "";
    const src = mode === "IPv4" ? p.src_ip : `${p.src_ip}${sp}`;
    const dst = mode === "IPv4" ? p.dst_ip : `${p.dst_ip}${dp}`;
    const b   = p.length ?? 0;

    get(src).txPkts++;  get(src).txBytes += b;
    get(dst).rxPkts++;  get(dst).rxBytes += b;
  }

  return Array.from(map.values());
}

function EndpointsView({ packets }: { packets: Packet[] }) {
  const [tab, setTab] = useState<EndpTab>("IPv4");
  const [sort, toggleSort] = useSort("txPkts");

  const rows = useMemo(() => {
    const data = buildEndpoints(packets, tab);
    const [col, dir] = sort;
    return [...data].sort((a: any, b: any) => {
      const v = typeof a[col] === "number" ? b[col] - a[col] : a[col].localeCompare(b[col]);
      return dir === "desc" ? v : -v;
    });
  }, [packets, tab, sort]);

  const tabs: EndpTab[] = ["IPv4", "TCP", "UDP"];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TabBar tabs={tabs} active={tab} onChange={t => setTab(t as EndpTab)} />
      {rows.length === 0 ? <Empty msg={`No ${tab} endpoints found.`} /> : (
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-[11px] font-mono">
            <thead className="sticky top-0" style={{ background: ELEVATED }}>
              <tr>
                <SortTh label="Address"  col="addr"    sort={sort} onSort={toggleSort} />
                <SortTh label="Tx Pkts"  col="txPkts"  sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Tx Bytes" col="txBytes" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Rx Pkts"  col="rxPkts"  sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Rx Bytes" col="rxBytes" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Total Pkts" col="txPkts" sort={sort} onSort={toggleSort} align="right" />
                <SortTh label="Total Bytes" col="txBytes" sort={sort} onSort={toggleSort} align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b hover:bg-[#1c2128] transition-colors"
                    style={{ borderColor: BORDER }}>
                  <td className="px-2 py-0.5 font-semibold" style={{ color: ACCENT }}>{r.addr}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: TEXT }}>{r.txPkts.toLocaleString()}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: MUTED }}>{fmtBytes(r.txBytes)}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: TEXT }}>{r.rxPkts.toLocaleString()}</td>
                  <td className="px-2 py-0.5 text-right" style={{ color: MUTED }}>{fmtBytes(r.rxBytes)}</td>
                  <td className="px-2 py-0.5 text-right font-semibold" style={{ color: TEXT }}>
                    {(r.txPkts + r.rxPkts).toLocaleString()}
                  </td>
                  <td className="px-2 py-0.5 text-right" style={{ color: MUTED }}>
                    {fmtBytes(r.txBytes + r.rxBytes)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <StatusBar count={rows.length} label={`${tab} endpoints`} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VIEW: Packet Lengths
// ─────────────────────────────────────────────────────────────────────────────

const LENGTH_BUCKETS = [
  { label: "0–19",     min: 0,    max: 19    },
  { label: "20–39",    min: 20,   max: 39    },
  { label: "40–79",    min: 40,   max: 79    },
  { label: "80–159",   min: 80,   max: 159   },
  { label: "160–319",  min: 160,  max: 319   },
  { label: "320–639",  min: 320,  max: 639   },
  { label: "640–1279", min: 640,  max: 1279  },
  { label: "1280–2559",min: 1280, max: 2559  },
  { label: "2560+",    min: 2560, max: Infinity },
];

function PacketLengthsView({ packets }: { packets: Packet[] }) {
  const buckets = useMemo(() => {
    const counts = LENGTH_BUCKETS.map(b => ({ ...b, count: 0, bytes: 0 }));
    for (const p of packets) {
      const len = p.length ?? 0;
      const b = counts.find(b => len >= b.min && len <= b.max);
      if (b) { b.count++; b.bytes += len; }
    }
    return counts;
  }, [packets]);

  const maxCount = Math.max(...buckets.map(b => b.count), 1);
  const total = packets.length || 1;

  if (!packets.length) return <Empty msg="No packets captured yet." />;

  return (
    <div className="flex flex-col h-full overflow-hidden p-5 gap-5">
      {/* Bar chart */}
      <div className="flex items-end gap-1.5" style={{ height: 160 }}>
        {buckets.map((b) => {
          const h = Math.max(2, (b.count / maxCount) * 140);
          const pct = ((b.count / total) * 100).toFixed(1);
          return (
            <div key={b.label} className="flex flex-col items-center gap-1 flex-1 group relative"
                 title={`${b.label} bytes: ${b.count} pkts (${pct}%)`}>
              {/* Tooltip */}
              <div className="absolute bottom-full mb-2 hidden group-hover:flex flex-col items-center z-10 pointer-events-none">
                <div className="rounded px-2 py-1 text-[10px] font-mono whitespace-nowrap shadow-lg"
                     style={{ background: ELEVATED, border: `1px solid ${BORDER}`, color: TEXT }}>
                  <div>{b.label} bytes</div>
                  <div style={{ color: ACCENT }}>{b.count.toLocaleString()} pkts</div>
                  <div style={{ color: MUTED }}>{pct}%</div>
                </div>
                <div style={{ width: 0, height: 0, borderLeft: "4px solid transparent", borderRight: "4px solid transparent", borderTop: `4px solid ${BORDER}` }} />
              </div>
              <div
                className="w-full rounded-t transition-all"
                style={{
                  height: h,
                  background: b.count > 0 ? ACCENT : BORDER,
                  opacity: b.count > 0 ? 0.85 : 0.2,
                }}
              />
            </div>
          );
        })}
      </div>

      {/* X-axis labels */}
      <div className="flex gap-1.5">
        {buckets.map(b => (
          <div key={b.label} className="flex-1 text-center font-mono" style={{ fontSize: 9, color: MUTED }}>
            {b.label}
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-auto flex-1">
        <table className="w-full border-collapse text-[11px] font-mono">
          <thead style={{ background: ELEVATED }}>
            <tr>
              {["Length range", "Packets", "% of total", "Bytes", "Avg size"].map(h => (
                <th key={h} className="px-3 py-1.5 text-left border-b"
                    style={{ color: MUTED, fontWeight: 500, fontSize: 11, borderColor: BORDER }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {buckets.map((b, i) => (
              <tr key={i} className="border-b hover:bg-[#1c2128]" style={{ borderColor: BORDER }}>
                <td className="px-3 py-0.5" style={{ color: MUTED }}>{b.label}</td>
                <td className="px-3 py-0.5 text-right" style={{ color: TEXT }}>{b.count.toLocaleString()}</td>
                <td className="px-3 py-0.5 text-right" style={{ color: MUTED }}>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-1.5 rounded-full" style={{
                      width: Math.max(1, (b.count / total) * 50),
                      background: ACCENT, opacity: 0.5,
                    }} />
                    {((b.count / total) * 100).toFixed(2)}%
                  </span>
                </td>
                <td className="px-3 py-0.5 text-right" style={{ color: MUTED }}>{fmtBytes(b.bytes)}</td>
                <td className="px-3 py-0.5 text-right" style={{ color: MUTED }}>
                  {b.count ? `${(b.bytes / b.count).toFixed(1)} B` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VIEW: I/O Graph
// ─────────────────────────────────────────────────────────────────────────────

type IOMetric = "packets" | "bytes" | "bits";

function IOGraphView({ packets }: { packets: Packet[] }) {
  const [metric, setMetric] = useState<IOMetric>("packets");
  const [interval, setInterval] = useState<number>(1); // seconds

  const { points, maxVal, labels } = useMemo(() => {
    if (!packets.length) return { points: [], maxVal: 1, labels: [] };
    const times = packets.map(p => parseTime(p.time));
    const tMin  = Math.min(...times);
    const tMax  = Math.max(...times);
    const dur   = tMax - tMin || 1;
    const nBins = Math.min(120, Math.max(10, Math.ceil(dur / interval)));
    const binW  = dur / nBins;

    const counts = Array(nBins).fill(0);
    const bytes  = Array(nBins).fill(0);

    for (let i = 0; i < packets.length; i++) {
      const bin = Math.min(nBins - 1, Math.floor((times[i] - tMin) / binW));
      counts[bin]++;
      bytes[bin] += packets[i].length ?? 0;
    }

    const vals = metric === "packets" ? counts : metric === "bytes" ? bytes : bytes.map(b => b * 8);
    const maxV = Math.max(...vals, 1);

    const lblStep = Math.ceil(nBins / 8);
    const lbls = counts.map((_, i) =>
      i % lblStep === 0 ? fmtDuration(tMin + i * binW) : ""
    );

    return { points: vals, maxVal: maxV, labels: lbls };
  }, [packets, metric, interval]);

  const W = 640, H = 180, PAD_L = 50, PAD_B = 30, PAD_T = 10, PAD_R = 10;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const barW  = Math.max(1, (plotW / Math.max(points.length, 1)) - 1);

  if (!packets.length) return <Empty msg="No packets captured yet." />;

  // Y-axis gridlines
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
    y: PAD_T + plotH * (1 - f),
    label: Math.round(maxVal * f).toLocaleString(),
  }));

  return (
    <div className="flex flex-col h-full overflow-hidden p-5 gap-4">
      {/* Controls */}
      <div className="flex items-center gap-4 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-[11px]" style={{ color: MUTED }}>Y Axis</span>
          {(["packets", "bytes", "bits"] as IOMetric[]).map(m => (
            <button key={m} onClick={() => setMetric(m)}
                    className="px-2 py-0.5 rounded text-[11px] transition-colors"
                    style={{
                      background: metric === m ? ACCENT : "transparent",
                      color:      metric === m ? "#0d1117" : MUTED,
                      border:     `1px solid ${metric === m ? ACCENT : BORDER}`,
                    }}>
              {m}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px]" style={{ color: MUTED }}>Interval</span>
          {[0.1, 0.5, 1, 5, 10].map(s => (
            <button key={s} onClick={() => setInterval(s)}
                    className="px-2 py-0.5 rounded text-[11px] transition-colors"
                    style={{
                      background: interval === s ? ACCENT : "transparent",
                      color:      interval === s ? "#0d1117" : MUTED,
                      border:     `1px solid ${interval === s ? ACCENT : BORDER}`,
                    }}>
              {s < 1 ? `${s * 1000}ms` : `${s}s`}
            </button>
          ))}
        </div>
      </div>

      {/* SVG chart */}
      <div className="overflow-x-auto shrink-0">
        <svg width={W} height={H} style={{ display: "block", fontFamily: "JetBrains Mono, monospace" }}>
          {/* Background */}
          <rect x={PAD_L} y={PAD_T} width={plotW} height={plotH}
                fill={ELEVATED} rx={2} />

          {/* Y gridlines + labels */}
          {yTicks.map(({ y, label }) => (
            <g key={y}>
              <line x1={PAD_L} y1={y} x2={PAD_L + plotW} y2={y}
                    stroke={BORDER} strokeWidth={0.5} />
              <text x={PAD_L - 4} y={y + 3.5} textAnchor="end" fill={MUTED} fontSize={9}>
                {label}
              </text>
            </g>
          ))}

          {/* Bars */}
          {points.map((v, i) => {
            const bh = Math.max(1, (v / maxVal) * plotH);
            const bx = PAD_L + i * (plotW / points.length);
            const by = PAD_T + plotH - bh;
            return (
              <rect key={i} x={bx + 0.5} y={by} width={Math.max(1, barW)} height={bh}
                    fill={ACCENT} opacity={0.75} rx={1} />
            );
          })}

          {/* Border */}
          <rect x={PAD_L} y={PAD_T} width={plotW} height={plotH}
                fill="none" stroke={BORDER} strokeWidth={1} rx={2} />

          {/* X labels */}
          {labels.map((lbl, i) => lbl && (
            <text key={i}
                  x={PAD_L + i * (plotW / points.length)}
                  y={H - 6}
                  fill={MUTED} fontSize={8} textAnchor="middle">
              {lbl}
            </text>
          ))}

          {/* Y axis label */}
          <text x={10} y={H / 2} fill={MUTED} fontSize={9}
                transform={`rotate(-90, 10, ${H / 2})`} textAnchor="middle">
            {metric}
          </text>
        </svg>
      </div>

      {/* Summary stats */}
      <div className="flex gap-6 font-mono text-[11px]">
        {[
          ["Total packets", packets.length.toLocaleString()],
          ["Total bytes",   fmtBytes(packets.reduce((s, p) => s + (p.length ?? 0), 0))],
          ["Buckets",       points.length.toString()],
          ["Interval",      interval < 1 ? `${interval * 1000}ms` : `${interval}s`],
        ].map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <span style={{ color: MUTED }}>{label}</span>
            <span style={{ color: TEXT }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared sub-components
// ─────────────────────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-widest mb-2"
           style={{ color: MUTED, letterSpacing: "0.08em" }}>{title}</div>
      <div className="rounded p-3" style={{ background: ELEVATED, border: `1px solid ${BORDER}` }}>
        {children}
      </div>
    </div>
  );
}

function TabBar({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="flex shrink-0 border-b px-2 gap-0 pt-1" style={{ borderColor: BORDER }}>
      {tabs.map(t => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className="px-3 py-1.5 text-[11px] font-mono transition-colors mr-0.5"
          style={{
            color:       active === t ? ACCENT : MUTED,
            borderBottom: active === t ? `2px solid ${ACCENT}` : "2px solid transparent",
            background: "transparent",
          }}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="flex items-center justify-center h-full text-[13px] font-mono" style={{ color: MUTED }}>
      {msg}
    </div>
  );
}

function StatusBar({ count, label }: { count: number; label: string }) {
  return (
    <div className="shrink-0 flex items-center px-3 border-t text-[10px] font-mono"
         style={{ height: 22, borderColor: BORDER, background: ELEVATED, color: MUTED }}>
      {count.toLocaleString()} {label}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MENU sidebar items
// ─────────────────────────────────────────────────────────────────────────────

const MENU_ITEMS: { id: StatView; label: string; shortDesc: string }[] = [
  { id: "summary",       label: "Capture File Properties", shortDesc: "Overview & totals" },
  { id: "hierarchy",     label: "Protocol Hierarchy",      shortDesc: "Protocol breakdown" },
  { id: "conversations", label: "Conversations",           shortDesc: "IPv4 / TCP / UDP pairs" },
  { id: "endpoints",     label: "Endpoints",               shortDesc: "All unique addresses" },
  { id: "lengths",       label: "Packet Lengths",          shortDesc: "Size histogram" },
  { id: "iograph",       label: "I/O Graph",               shortDesc: "Traffic over time" },
];

// ─────────────────────────────────────────────────────────────────────────────
// ROOT MODAL
// ─────────────────────────────────────────────────────────────────────────────

export function StatisticsModal({ packets, initialView = "summary", onClose }: Props) {
  const [view, setView] = useState<StatView>(initialView);

  const activeItem = MENU_ITEMS.find(m => m.id === view)!;

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.65)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Dialog */}
      <div
        className="flex overflow-hidden rounded-lg shadow-2xl"
        style={{
          width: "min(1100px, 94vw)",
          height: "min(700px, 90vh)",
          background: BG,
          border: `1px solid ${BORDER}`,
        }}
      >
        {/* ── Left sidebar nav ── */}
        <div
          className="flex flex-col shrink-0 overflow-y-auto"
          style={{ width: 210, background: SURFACE, borderRight: `1px solid ${BORDER}` }}
        >
          <div className="flex items-center justify-between px-3 py-2.5 border-b shrink-0"
               style={{ borderColor: BORDER }}>
            <span className="text-[12px] font-semibold tracking-wide uppercase"
                  style={{ color: MUTED, letterSpacing: "0.07em" }}>Statistics</span>
          </div>

          <nav className="flex flex-col py-1">
            {MENU_ITEMS.map(item => (
              <button
                key={item.id}
                onClick={() => setView(item.id)}
                className="flex flex-col px-3 py-2 text-left transition-colors"
                style={{
                  background:   view === item.id ? ELEVATED : "transparent",
                  borderLeft:   `2px solid ${view === item.id ? ACCENT : "transparent"}`,
                }}
              >
                <span className="text-[12px]"
                      style={{ color: view === item.id ? TEXT : MUTED }}>{item.label}</span>
                <span className="text-[10px] mt-0.5" style={{ color: "#4a5568" }}>{item.shortDesc}</span>
              </button>
            ))}
          </nav>

          <div className="mt-auto px-3 py-2 border-t text-[10px] font-mono"
               style={{ borderColor: BORDER, color: "#4a5568" }}>
            {packets.length.toLocaleString()} packets loaded
          </div>
        </div>

        {/* ── Content area ── */}
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          {/* Title bar */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0"
               style={{ background: SURFACE, borderColor: BORDER }}>
            <div>
              <span className="text-[13px] font-semibold" style={{ color: TEXT }}>
                {activeItem.label}
              </span>
              <span className="ml-2 text-[11px]" style={{ color: MUTED }}>
                {activeItem.shortDesc}
              </span>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded transition-colors hover:bg-[#2d333b]"
              style={{ color: MUTED }}
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* View content */}
          <div className="flex-1 overflow-hidden" style={{ background: BG }}>
            {view === "summary"       && <SummaryView       packets={packets} />}
            {view === "hierarchy"     && <HierarchyView     packets={packets} />}
            {view === "conversations" && <ConversationsView packets={packets} />}
            {view === "endpoints"     && <EndpointsView     packets={packets} />}
            {view === "lengths"       && <PacketLengthsView packets={packets} />}
            {view === "iograph"       && <IOGraphView       packets={packets} />}
          </div>
        </div>
      </div>
    </div>
  );
}
