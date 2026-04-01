/**
 * PacketTable — Wireshark-style three-pane packet inspector.
 *
 * Pane 1 (top):   Packet list — virtualised, compact 20px rows, Wireshark
 *                 column layout (No. · Time · Source · Destination · Protocol
 *                 · Length · Info), row-background colour coding per protocol.
 *
 * Pane 2 (bottom-left):  Protocol detail tree — layers + decoded fields,
 *                         collapsible per layer, Wireshark field-name style.
 *
 * Pane 3 (bottom-right): Packet bytes — reconstructed hex dump from known
 *                         header fields (Ethernet / IP / TCP / UDP), with a
 *                         banner noting raw capture bytes aren't streamed.
 *
 * Both splits are drag-resizable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useStore } from "../store/useStore";
import { fetchPackets, fetchLocalIPs } from "../lib/api";
import { compileFilter } from "../lib/displayFilter";
import { ChevronDown, ChevronRight, X, ChevronUp, BarChart2 } from "lucide-react";
import type { Packet } from "../store/useStore";
import { PacketContextMenu } from "./PacketContextMenu";
import type { ContextMenuState } from "./PacketContextMenu";
import { StatisticsModal } from "./StatisticsModal";
import type { StatView } from "./StatisticsModal";

// ── Protocol layer labels (Wireshark naming) ──────────────────────────────────

const LAYER_LABELS: Record<string, string> = {
  ETH:    "Ethernet II",
  IP:     "Internet Protocol Version 4",
  IPV6:   "Internet Protocol Version 6",
  TCP:    "Transmission Control Protocol",
  UDP:    "User Datagram Protocol",
  DNS:    "Domain Name System",
  MDNS:   "Multicast Domain Name System",
  LLMNR:  "Link-Local Multicast Name Resolution",
  HTTP:   "Hypertext Transfer Protocol",
  HTTP2:  "HyperText Transfer Protocol 2",
  TLS:    "Transport Layer Security",
  TLSV1: "Transport Layer Security",
  TLSV1_2: "Transport Layer Security",
  TLSV1_3: "Transport Layer Security",
  SSL:    "Secure Sockets Layer",
  ICMP:   "Internet Control Message Protocol",
  ICMPV6: "Internet Control Message Protocol v6",
  ARP:    "Address Resolution Protocol",
  DHCP:   "Dynamic Host Configuration Protocol",
  DATA:   "Data",
};

const LAYER_PREFIXES: Record<string, string> = {
  ETH: "eth", IP: "ip", IPV6: "ipv6",
  TCP: "tcp", UDP: "udp",
  DNS: "dns", MDNS: "dns", LLMNR: "dns",
  HTTP: "http", HTTP2: "http2",
  TLS: "tls", SSL: "ssl",
  ICMP: "icmp", ICMPV6: "icmpv6",
  ARP: "arp", DHCP: "dhcp",
};

// ── Row colour system (dark Wireshark tints + left accent bar) ────────────────

interface RowStyle { bg: string; accent: string }

const ROW_STYLES: Record<string, RowStyle> = {
  error: { bg: "#2a0808", accent: "#da3633" },
  warn:  { bg: "#1e1600", accent: "#d29922" },
  tls:   { bg: "#0b1526", accent: "#388bfd" },
  http:  { bg: "#091d0e", accent: "#3fb950" },
  dns:   { bg: "#10093a", accent: "#a371f7" },
  udp:   { bg: "#0a1522", accent: "#58a6ff" },
  arp:   { bg: "#181400", accent: "#e3b341" },
  icmp:  { bg: "#041515", accent: "#39d353" },
  tcp:   { bg: "#0d1117", accent: "#30363d" },
  other: { bg: "#0d1117", accent: "#30363d" },
};
const SELECTED_BG = "#0c2d6b";
const SELECTED_FG = "#e6edf3";

function getRowStyle(pkt: Packet): RowStyle {
  const d = pkt.details ?? {};
  if (
    d["tcp.analysis.retransmission"] === "1" ||
    d["tcp.analysis.out_of_order"] === "1" ||
    (pkt.protocol === "TCP" && pkt.info?.includes("[RST]"))
  ) return ROW_STYLES.error;
  if (
    d["tcp.analysis.zero_window"] === "1" ||
    d["tcp.analysis.duplicate_ack"] === "1"
  ) return ROW_STYLES.warn;

  const p = (pkt.protocol ?? "").toUpperCase();
  if (p === "TLSV1.2" || p === "TLSV1.3" || p === "SSL" || p === "TLS") return ROW_STYLES.tls;
  if (p === "HTTP" || p === "HTTP2") return ROW_STYLES.http;
  if (p === "DNS" || p === "MDNS" || p === "LLMNR") return ROW_STYLES.dns;
  if (p === "UDP") return ROW_STYLES.udp;
  if (p === "ARP") return ROW_STYLES.arp;
  if (p === "ICMP" || p === "ICMPV6") return ROW_STYLES.icmp;
  if (p === "TCP") return ROW_STYLES.tcp;
  return ROW_STYLES.other;
}

// ── Time formatter ────────────────────────────────────────────────────────────

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

function fmtAddr(ip: string, port: string): string {
  if (!ip) return "—";
  if (port && port !== "0" && port !== "-") return `${ip}:${port}`;
  return ip;
}

// ── Protocol detail tree ──────────────────────────────────────────────────────

interface TreeLayer {
  id: string;
  label: string;
  summary: string;
  fields: [string, string][];
}

function buildTree(pkt: Packet): TreeLayer[] {
  const layers: TreeLayer[] = [];

  // Frame layer (always first)
  layers.push({
    id: "frame",
    label: "Frame",
    summary: `${pkt.id}: ${pkt.length} bytes on wire`,
    fields: [
      ["Frame Number",      String(pkt.id)],
      ["Arrival Time",      fmtTime(pkt.timestamp)],
      ["Frame Length",      `${pkt.length} bytes (${pkt.length * 8} bits)`],
      ["Protocols in frame",(pkt.layers ?? []).join(" : ")],
    ],
  });

  for (const rawLayer of (pkt.layers ?? [])) {
    const key    = rawLayer.toUpperCase().replace(/\./g, "_");
    const prefix = LAYER_PREFIXES[key] ?? rawLayer.toLowerCase();
    const label  = LAYER_LABELS[key] ?? rawLayer;

    // Collect matching detail fields
    const fields: [string, string][] = [];
    for (const [k, v] of Object.entries(pkt.details ?? {})) {
      if (!v) continue;
      if (k.startsWith(prefix + ".")) {
        const shortKey = k
          .slice(prefix.length + 1)
          .replace(/_/g, " ")
          .replace(/\b\w/g, (c) => c.toUpperCase());
        fields.push([shortKey, v]);
      }
    }

    // Per-layer summary
    let summary = "";
    const lu = key;
    if (lu === "IP" || lu === "IPV6") {
      summary = `${pkt.src_ip}  →  ${pkt.dst_ip}`;
    } else if (lu === "TCP" || lu === "UDP") {
      summary = `${pkt.src_port} → ${pkt.dst_port}`;
    } else if (lu === "ETH") {
      const src = pkt.details?.["eth.src"] ?? "";
      const dst = pkt.details?.["eth.dst"] ?? "";
      if (src || dst) summary = [src && `Src: ${src}`, dst && `Dst: ${dst}`].filter(Boolean).join("  ");
    }

    // Fallback fields from top-level packet properties
    if (fields.length === 0) {
      if (lu === "IP" || lu === "IPV6") {
        fields.push(["Source", pkt.src_ip], ["Destination", pkt.dst_ip]);
      } else if (lu === "TCP" || lu === "UDP") {
        fields.push(["Source Port", pkt.src_port], ["Destination Port", pkt.dst_port]);
      }
    }

    layers.push({ id: rawLayer.toLowerCase(), label, summary, fields });
  }

  return layers;
}

// ── Protocol tree pane ────────────────────────────────────────────────────────

function ProtocolTree({ pkt }: { pkt: Packet | null }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["frame"]));

  useEffect(() => {
    if (!pkt) return;
    setExpanded(new Set(["frame", ...(pkt.layers ?? []).map((l) => l.toLowerCase())]));
  }, [pkt?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!pkt) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#6e7681] text-xs font-mono"
           style={{ background: "#0d1117" }}>
        Select a packet to inspect protocol details
      </div>
    );
  }

  const tree = buildTree(pkt);
  const toggle = (id: string) =>
    setExpanded((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <div className="flex-1 overflow-y-auto text-xs font-mono select-text"
         style={{ background: "#0d1117" }}>
      {tree.map((layer) => {
        const open = expanded.has(layer.id);
        return (
          <div key={layer.id}>
            <button
              onClick={() => toggle(layer.id)}
              className="w-full flex items-start gap-1 px-1.5 py-px text-left hover:bg-[#161b22]"
            >
              {open
                ? <ChevronDown  className="w-3 h-3 mt-0.5 shrink-0 text-[#8b949e]" />
                : <ChevronRight className="w-3 h-3 mt-0.5 shrink-0 text-[#8b949e]" />}
              <span className="text-[#58a6ff] font-semibold shrink-0">{layer.label}</span>
              {!open && layer.summary && (
                <span className="text-[#8b949e] ml-1 truncate">, {layer.summary}</span>
              )}
            </button>
            {open && (
              <div className="pl-5 border-l border-[#21262d] ml-3">
                {layer.summary && (
                  <div className="text-[#8b949e] px-1 py-px">{layer.summary}</div>
                )}
                {layer.fields.map(([k, v]) => (
                  <div key={k} className="flex gap-2 px-1 py-px hover:bg-[#161b22]">
                    <span className="text-[#8b949e] shrink-0 min-w-[120px]">{k}:</span>
                    <span className="text-[#e6edf3] break-all">{v}</span>
                  </div>
                ))}
                {layer.fields.length === 0 && (
                  <div className="text-[#8b949e] px-1 py-px italic">No decoded fields</div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Hex dump pane ─────────────────────────────────────────────────────────────

function parseIPv4(ip: string): number[] {
  const p = ip.split(".").map(Number);
  return p.length === 4 && p.every((n) => !isNaN(n)) ? p : [0, 0, 0, 0];
}
function parsePort(s: string): number[] {
  const n = parseInt(s, 10);
  return isNaN(n) ? [0, 0] : [(n >> 8) & 0xff, n & 0xff];
}

function buildHexBytes(pkt: Packet): number[] {
  const b: number[] = [];
  const proto = (pkt.protocol ?? "").toUpperCase();

  // Ethernet header (14 bytes) — MACs unknown → 00 placeholders
  b.push(0xff,0xff,0xff,0xff,0xff,0xff);  // dst MAC
  b.push(0x00,0x00,0x00,0x00,0x00,0x00);  // src MAC
  if (proto === "ARP") {
    b.push(0x08, 0x06);                    // EtherType ARP
  } else {
    b.push(0x08, 0x00);                    // EtherType IPv4
  }

  if (proto === "ARP") {
    b.push(0x00,0x01);                     // HW type: Ethernet
    b.push(0x08,0x00);                     // Proto: IPv4
    b.push(0x06, 0x04);                    // HW size / Proto size
    b.push(0x00,0x01);                     // Opcode: request
    b.push(0x00,0x00,0x00,0x00,0x00,0x00); // Sender MAC
    b.push(...parseIPv4(pkt.src_ip));
    b.push(0x00,0x00,0x00,0x00,0x00,0x00); // Target MAC
    b.push(...parseIPv4(pkt.dst_ip));
    return b;
  }

  // IPv4 header (20 bytes)
  const totalLen = pkt.length;
  const protoNum = proto === "TCP" ? 6 : proto === "UDP" ? 17 : proto === "ICMP" ? 1 : 0;
  b.push(0x45);                            // Version 4 + IHL 5
  b.push(0x00);                            // DSCP / ECN
  b.push((totalLen >> 8) & 0xff, totalLen & 0xff);
  b.push(0x00,0x00);                       // ID
  b.push(0x40,0x00);                       // Flags DF + Fragment offset 0
  b.push(0x40);                            // TTL 64
  b.push(protoNum);
  b.push(0x00,0x00);                       // Checksum (unknown)
  b.push(...parseIPv4(pkt.src_ip));
  b.push(...parseIPv4(pkt.dst_ip));

  if (proto === "TCP") {
    b.push(...parsePort(pkt.src_port));
    b.push(...parsePort(pkt.dst_port));
    b.push(0x00,0x00,0x00,0x00);           // Seq
    b.push(0x00,0x00,0x00,0x00);           // Ack
    b.push(0x50,0x18);                     // Data offset 5, PSH+ACK
    b.push(0xff,0xff);                     // Window
    b.push(0x00,0x00,0x00,0x00);           // Checksum + Urgent ptr
  } else if (proto === "UDP") {
    b.push(...parsePort(pkt.src_port));
    b.push(...parsePort(pkt.dst_port));
    const udpLen = Math.max(8, pkt.length - 28);
    b.push((udpLen >> 8) & 0xff, udpLen & 0xff);
    b.push(0x00,0x00);                     // Checksum
  } else if (proto === "ICMP") {
    b.push(0x08,0x00,0x00,0x00);           // Type 8 (echo req), checksum
    b.push(0x00,0x00,0x00,0x01);           // ID + Seq
  }

  return b;
}

function PacketBytes({ pkt }: { pkt: Packet | null }) {
  if (!pkt) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#6e7681] text-xs font-mono"
           style={{ background: "#0a0e14", borderLeft: "1px solid #21262d" }}>
        No packet selected
      </div>
    );
  }

  const bytes  = buildHexBytes(pkt);
  const rows: { off: string; hex: string; asc: string }[] = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const chunk = bytes.slice(i, i + 16);
    const hexParts = chunk.map((b) => b.toString(16).padStart(2, "0"));
    const hex = [hexParts.slice(0, 8).join(" "), hexParts.slice(8).join(" ")].filter(Boolean).join("  ");
    const asc = chunk.map((b) => (b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : ".")).join("");
    rows.push({ off: i.toString(16).padStart(4, "0"), hex, asc });
  }

  return (
    <div className="flex-1 overflow-y-auto p-2 text-[11px] font-mono select-text"
         style={{ background: "#0a0e14", borderLeft: "1px solid #21262d" }}>
      <div className="text-[#6e7681] text-[10px] mb-1.5 leading-tight">
        Reconstructed from decoded fields — raw capture bytes not streamed
      </div>
      {rows.map((r) => (
        <div key={r.off} className="flex gap-3 leading-[1.55] hover:bg-[#161b22] px-0.5">
          <span className="text-[#6e7681] w-8 shrink-0">{r.off}</span>
          <span className="text-[#79c0ff] tracking-wide w-[17ch] shrink-0"
                style={{ minWidth: "calc(8*1ch + 1ch + 8*1ch)" }}>{r.hex}</span>
          <span className="text-[#e6edf3] tracking-widest">{r.asc}</span>
        </div>
      ))}
    </div>
  );
}

// ── Drag resize hook ──────────────────────────────────────────────────────────

function useDragResize(
  initial: number,
  min: number,
  max: number,
  axis: "vertical" | "horizontal",
  invert = false,
) {
  const [size, setSize] = useState(initial);
  const dragging = useRef(false);
  const startPos = useRef(0);
  const startSize = useRef(initial);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startPos.current  = axis === "vertical" ? e.clientY : e.clientX;
    startSize.current = size;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = (axis === "vertical" ? ev.clientY : ev.clientX) - startPos.current;
      const next  = invert ? startSize.current - delta : startSize.current + delta;
      setSize(Math.max(min, Math.min(max, next)));
    };
    const onUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [axis, invert, max, min, size]);

  return [size, onMouseDown] as const;
}

// ── Row height ────────────────────────────────────────────────────────────────

const ROW_HEIGHT = 20;

// ── Main PacketTable ──────────────────────────────────────────────────────────

export function PacketTable() {
  const { isCapturing, selectedProtocol, setTotalPackets, localIPs, setLocalIPs } = useStore();

  const localIPSet = new Set(localIPs);

  useEffect(() => {
    fetchLocalIPs().then(setLocalIPs).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const [packets, setPackets]       = useState<Packet[]>([]);
  const [total, _setTotal]          = useState(0);
  const setTotal = useCallback((n: number) => { _setTotal(n); setTotalPackets(n); }, [setTotalPackets]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [search, setSearch]         = useState("");
  const [filterError, setFilterError] = useState("");
  const [ctxMenu, setCtxMenu]       = useState<ContextMenuState | null>(null);
  const [markedIds, setMarkedIds]   = useState<Set<number>>(new Set());
  const [ignoredIds, setIgnoredIds] = useState<Set<number>>(new Set());
  const [statsView, setStatsView]   = useState<StatView | null>(null);
  const [statsMenuOpen, setStatsMenuOpen] = useState(false);

  const scrollRef     = useRef<HTMLDivElement>(null);
  const pollRef       = useRef<ReturnType<typeof setInterval> | null>(null);
  const initDoneRef   = useRef(false);
  const pktLenRef     = useRef(0);
  const searchRef     = useRef(search);
  const protoRef      = useRef(selectedProtocol);
  const prevCapRef    = useRef(isCapturing);

  searchRef.current = search;
  protoRef.current  = selectedProtocol;
  pktLenRef.current = packets.length;

  // ── Resize state ────────────────────────────────────────────────────────────
  // detailH = height of the bottom detail pane in px
  // treeW   = width of the protocol tree within the bottom pane in px
  const [detailH, onDetailDivider] = useDragResize(220, 80, 520, "vertical", true);
  const [treeW,   onTreeDivider  ] = useDragResize(360, 160, 800, "horizontal");

  // ── Data fetching ────────────────────────────────────────────────────────────
  // Filtering is done entirely client-side via compileFilter — we never send
  // the display-filter string to the backend (tshark requires a pcap file).
  // FETCH_ALL is a large sentinel; the backend returns however many it has stored.
  const FETCH_ALL = 2_000_000;

  useEffect(() => {
    initDoneRef.current = false;
    setPackets([]);
    setTotal(0);
    setFilterError("");
    pktLenRef.current = 0;

    const timer = setTimeout(async () => {
      try {
        const res = await fetchPackets(0, FETCH_ALL, selectedProtocol);
        setTotal(res.total);
        setPackets(res.packets);
        pktLenRef.current = res.packets.length;
        initDoneRef.current = true;
      } catch (e: any) {
        const msg = e?.response?.data?.detail ?? "";
        if (msg) setFilterError(msg);
      }
    }, 0);

    return () => {
      clearTimeout(timer);
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [selectedProtocol]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }

    if (prevCapRef.current && !isCapturing) {
      (async () => {
        try {
          const res = await fetchPackets(0, FETCH_ALL, protoRef.current);
          setTotal(res.total); setPackets(res.packets); pktLenRef.current = res.packets.length;
        } catch {}
      })();
    }
    prevCapRef.current = isCapturing;
    if (!isCapturing) return;

    if (!initDoneRef.current) {
      (async () => {
        try {
          const res = await fetchPackets(0, FETCH_ALL, protoRef.current);
          setTotal(res.total); setPackets(res.packets); pktLenRef.current = res.packets.length;
          initDoneRef.current = true;
        } catch {}
      })();
    }

    const poll = async () => {
      const curProto = protoRef.current;
      try {
        const res = await fetchPackets(pktLenRef.current, 500, curProto);
        setTotal(res.total);
        if (res.packets.length > 0) {
          setPackets((prev) => {
            const updated = [...prev, ...res.packets];
            pktLenRef.current = updated.length;
            return updated;
          });
        }
      } catch {}
    };
    pollRef.current = setInterval(poll, 500);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [isCapturing, selectedProtocol]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Derived packet list: client-side display filter + ignore list ───────────
  const filterResult = compileFilter(search);
  const filterFn     = filterResult.ok ? filterResult.fn! : null;
  const visiblePackets = packets.filter((p) => {
    if (ignoredIds.has(p.id)) return false;
    if (filterFn) return filterFn(p);
    return true;
  });

  // ── Virtualizer ─────────────────────────────────────────────────────────────

  const virt = useVirtualizer({
    count: visiblePackets.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: useCallback(() => ROW_HEIGHT, []),
    overscan: 15,
  });

  useEffect(() => {
    if (autoScroll && visiblePackets.length > 0)
      virt.scrollToIndex(visiblePackets.length - 1, { align: "end" });
  }, [visiblePackets.length, autoScroll, virt]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 60);
  };

  // ── Context menu handlers ────────────────────────────────────────────────
  const toggleMark   = useCallback((id: number) =>
    setMarkedIds((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }), []);
  const toggleIgnore = useCallback((id: number) =>
    setIgnoredIds((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }), []);

  const handleFollowStream = useCallback((pkt: Packet, proto: "tcp" | "udp") => {
    if (!pkt.src_ip || !pkt.dst_ip || !pkt.src_port || !pkt.dst_port) return;
    const f = `(ip.addr == ${pkt.src_ip} && ip.addr == ${pkt.dst_ip} && ${proto}.port == ${pkt.src_port} && ${proto}.port == ${pkt.dst_port})`;
    setSearch(f);
    setFilterError("");
  }, []);

  const selectedPkt = selectedId != null
    ? (packets.find((p) => p.id === selectedId) ?? null)
    : null;

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: "#0d1117" }}>

      {/* ── Display filter bar ───────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center gap-0 border-b"
           style={{ background: "#161b22", borderColor: "#30363d" }}>
        {/* Validity indicator strip — green=valid, red=parse error, dim=empty */}
        <div
          className="self-stretch w-1 shrink-0"
          style={{
            background: !search        ? "#238636"
                      : filterResult.ok ? "#238636"
                      : "#da3633",
            opacity: search ? 1 : 0.35,
          }}
        />
        <div className="flex items-center gap-1.5 flex-1 px-2 py-1.5">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Apply a display filter … (e.g.  tcp  ·  ip.src == 1.2.3.4  ·  dns)"
            className="flex-1 bg-transparent text-[#e6edf3] text-xs focus:outline-none placeholder-[#6e7681] font-mono"
          />
          {search && (
            <button onClick={() => setSearch("")} title="Clear filter"
                    className="text-[#6e7681] hover:text-[#e6edf3] transition-colors">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        {search && !filterResult.ok && (
          <div className="px-3 text-xs text-[#f85149] shrink-0 font-mono truncate max-w-[300px]">
            {filterResult.error}
          </div>
        )}

        {/* ── Statistics dropdown button ─────────────────────────────────── */}
        <div className="relative shrink-0 border-l" style={{ borderColor: "#30363d" }}>
          <button
            onClick={() => setStatsMenuOpen(o => !o)}
            className="flex items-center gap-1.5 px-3 h-full text-[11px] font-mono transition-colors hover:bg-[#1c2128]"
            style={{ color: "#8b949e" }}
            title="Statistics"
          >
            <BarChart2 className="w-3.5 h-3.5" />
            Statistics
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>

          {statsMenuOpen && (
            <>
              {/* Backdrop */}
              <div className="fixed inset-0 z-[90]" onClick={() => setStatsMenuOpen(false)} />
              {/* Dropdown */}
              <div
                className="absolute right-0 top-full z-[100] rounded shadow-2xl overflow-hidden"
                style={{ minWidth: 220, background: "#1c2128", border: "1px solid #444c56", marginTop: 2 }}
              >
                {([
                  ["summary",       "Capture File Properties"],
                  ["hierarchy",     "Protocol Hierarchy"],
                  ["conversations", "Conversations"],
                  ["endpoints",     "Endpoints"],
                  ["lengths",       "Packet Lengths"],
                  ["iograph",       "I/O Graph"],
                ] as [StatView, string][]).map(([id, label]) => (
                  <button
                    key={id}
                    onClick={() => { setStatsView(id); setStatsMenuOpen(false); }}
                    className="w-full text-left px-3 py-1.5 text-[12px] font-mono transition-colors hover:bg-[#2d333b]"
                    style={{ color: "#cdd9e5" }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Packet list ──────────────────────────────────────────────────────── */}
      <div className="shrink-0 flex flex-col overflow-hidden"
           style={{ flex: "1 1 0", minHeight: 0 }}>

        {/* Column header */}
        <div className="flex shrink-0 text-[#8b949e] text-[11px] font-semibold select-none border-b"
             style={{ background: "#161b22", borderColor: "#30363d", height: 24 }}>
          <div className="px-2 flex items-center w-14 shrink-0 border-r"
               style={{ borderColor: "#21262d" }}>No.</div>
          <div className="px-2 flex items-center w-28 shrink-0 border-r"
               style={{ borderColor: "#21262d" }}>Time</div>
          <div className="px-2 flex items-center flex-1 min-w-0 border-r"
               style={{ borderColor: "#21262d" }}>Source</div>
          <div className="px-2 flex items-center flex-1 min-w-0 border-r"
               style={{ borderColor: "#21262d" }}>Destination</div>
          <div className="px-2 flex items-center w-20 shrink-0 border-r"
               style={{ borderColor: "#21262d" }}>Protocol</div>
          <div className="px-2 flex items-center w-14 shrink-0 border-r"
               style={{ borderColor: "#21262d" }}>Length</div>
          <div className="px-2 flex items-center flex-[2] min-w-0">Info</div>
        </div>

        {/* Virtualised rows */}
        <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-auto"
             style={{ background: "#0d1117" }}>
          {visiblePackets.length === 0 ? (
            <div className="text-center text-[#6e7681] py-16 text-xs font-mono">
              {search
                ? "No packets match the display filter."
                : isCapturing
                ? "Waiting for packets…"
                : "No packets captured yet."}
            </div>
          ) : (
            <div style={{ height: virt.getTotalSize(), width: "100%", position: "relative" }}>
              {virt.getVirtualItems().map((vi) => {
                const pkt = visiblePackets[vi.index];
                if (!pkt) return null;
                const rs       = getRowStyle(pkt);
                const sel      = selectedId === pkt.id;
                const marked   = markedIds.has(pkt.id);
                const srcLocal = localIPSet.has(pkt.src_ip);
                const dstLocal = localIPSet.has(pkt.dst_ip);

                // Marked packets get Wireshark's black-on-yellow treatment
                const rowBg = sel     ? SELECTED_BG
                            : marked  ? "#3a2e00"
                            : rs.bg;
                const rowFg = sel    ? SELECTED_FG
                            : marked ? "#e3b341"
                            : undefined;

                return (
                  <div
                    key={vi.key}
                    data-index={vi.index}
                    ref={virt.measureElement}
                    style={{
                      position: "absolute", top: 0, left: 0, width: "100%",
                      transform: `translateY(${vi.start}px)`,
                      height: ROW_HEIGHT,
                    }}
                  >
                    <div
                      role="row"
                      tabIndex={0}
                      aria-selected={sel}
                      onClick={() => setSelectedId(sel ? null : pkt.id)}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        setSelectedId(pkt.id);
                        setCtxMenu({ x: e.clientX, y: e.clientY, pkt });
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedId(sel ? null : pkt.id);
                        }
                      }}
                      aria-label={`Packet ${pkt.id}: ${pkt.protocol} from ${pkt.src_ip} to ${pkt.dst_ip}`}
                      className="flex items-center text-[11px] cursor-default border-b transition-none select-none"
                      style={{
                        height: ROW_HEIGHT,
                        background: rowBg,
                        color: rowFg,
                        borderColor: "#21262d",
                        borderLeft: `3px solid ${marked ? "#e3b341" : rs.accent}`,
                      }}
                    >
                      <div className="px-2 font-mono text-[#6e7681] w-14 shrink-0 truncate flex items-center gap-1"
                           style={{ color: rowFg ?? undefined }}>
                        {marked && <span style={{ color: "#e3b341", fontSize: 8 }}>◆</span>}
                        {pkt.id}
                      </div>
                      <div className="px-2 font-mono text-[#8b949e] w-28 shrink-0 whitespace-nowrap"
                           style={{ color: rowFg ?? undefined }}>{fmtTime(pkt.timestamp)}</div>
                      <div className={`px-2 font-mono flex-1 min-w-0 truncate ${srcLocal ? "font-bold" : ""}`}
                           style={{ color: rowFg ?? (srcLocal ? "#e3b341" : "#e6edf3") }}>
                        {fmtAddr(pkt.src_ip, pkt.src_port)}
                      </div>
                      <div className={`px-2 font-mono flex-1 min-w-0 truncate ${dstLocal ? "font-bold" : ""}`}
                           style={{ color: rowFg ?? (dstLocal ? "#e3b341" : "#e6edf3") }}>
                        {fmtAddr(pkt.dst_ip, pkt.dst_port)}
                      </div>
                      <div className="px-2 font-semibold w-20 shrink-0 truncate"
                           style={{ color: rowFg ?? rs.accent }}>{pkt.protocol}</div>
                      <div className="px-2 text-[#8b949e] w-14 shrink-0"
                           style={{ color: rowFg ?? undefined }}>{pkt.length}</div>
                      <div className="px-2 flex-[2] min-w-0 truncate text-[#c9d1d9]"
                           style={{ color: rowFg ?? undefined }}>{pkt.info}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Resize handle ────────────────────────────────────────────────────── */}
      <div
        onMouseDown={onDetailDivider}
        className="shrink-0 flex items-center justify-center cursor-row-resize select-none group"
        style={{ height: 6, background: "#161b22", borderTop: "1px solid #30363d", borderBottom: "1px solid #30363d" }}
        title="Drag to resize"
      >
        <div className="w-12 h-0.5 rounded-full opacity-40 group-hover:opacity-80 transition-opacity"
             style={{ background: "#8b949e" }} />
      </div>

      {/* ── Bottom pane (protocol tree + hex dump) ────────────────────────────── */}
      <div className="shrink-0 flex overflow-hidden"
           style={{ height: detailH }}>

        {/* Protocol tree */}
        <div className="flex flex-col overflow-hidden"
             style={{ width: treeW, minWidth: 160 }}>
          {/* Pane header */}
          <div className="flex items-center gap-2 px-2 shrink-0 border-b text-[10px] font-semibold text-[#8b949e] uppercase tracking-widest"
               style={{ height: 22, background: "#161b22", borderColor: "#30363d" }}>
            Packet Details
          </div>
          <ProtocolTree pkt={selectedPkt} />
        </div>

        {/* Vertical resize handle */}
        <div
          onMouseDown={onTreeDivider}
          className="shrink-0 cursor-col-resize select-none group flex items-center justify-center"
          style={{ width: 6, background: "#161b22", borderLeft: "1px solid #30363d", borderRight: "1px solid #30363d" }}
        >
          <div className="h-12 w-0.5 rounded-full opacity-40 group-hover:opacity-80 transition-opacity"
               style={{ background: "#8b949e" }} />
        </div>

        {/* Hex dump */}
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          <div className="flex items-center gap-2 px-2 shrink-0 border-b text-[10px] font-semibold text-[#8b949e] uppercase tracking-widest"
               style={{ height: 22, background: "#161b22", borderColor: "#30363d" }}>
            Packet Bytes
          </div>
          <PacketBytes pkt={selectedPkt} />
        </div>
      </div>

      {/* ── Wireshark-style status bar ────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center justify-between px-3 text-[10px] font-mono border-t"
           style={{ height: 20, background: "#161b22", borderColor: "#30363d", color: "#8b949e" }}>
        <div className="flex items-center gap-4">
          <span>Packets: <span className="text-[#e6edf3]">{total.toLocaleString()}</span></span>
          <span>Displayed: <span className="text-[#e6edf3]">{visiblePackets.length.toLocaleString()}</span></span>
          {ignoredIds.size > 0 && (
            <span>Ignored: <span style={{ color: "#e5534b" }}>{ignoredIds.size}</span></span>
          )}
          {markedIds.size > 0 && (
            <span>Marked: <span style={{ color: "#e3b341" }}>{markedIds.size}</span></span>
          )}
          {selectedPkt && (
            <span>Selected: <span className="text-[#e6edf3]">#{selectedPkt.id} · {selectedPkt.length} bytes</span></span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isCapturing && (
            <span className="flex items-center gap-1 text-[#3fb950]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#3fb950] animate-pulse inline-block" />
              Capturing
            </span>
          )}
          {!autoScroll && visiblePackets.length > 0 && (
            <button
              onClick={() => { setAutoScroll(true); virt.scrollToIndex(visiblePackets.length - 1, { align: "end" }); }}
              className="flex items-center gap-1 text-[#58a6ff] hover:underline"
            >
              <ChevronUp className="w-3 h-3" /> Jump to latest
            </button>
          )}
        </div>
      </div>

      {/* ── Right-click context menu ─────────────────────────────────────────── */}
      {ctxMenu && (
        <PacketContextMenu
          state={ctxMenu}
          markedIds={markedIds}
          ignoredIds={ignoredIds}
          onClose={() => setCtxMenu(null)}
          onApplyFilter={(f) => { setSearch(f); setFilterError(""); }}
          onMarkToggle={toggleMark}
          onIgnoreToggle={toggleIgnore}
          onFollowStream={handleFollowStream}
        />
      )}

      {/* ── Statistics modal ─────────────────────────────────────────────────── */}
      {statsView && (
        <StatisticsModal
          packets={packets}
          initialView={statsView}
          onClose={() => setStatsView(null)}
        />
      )}
    </div>
  );
}
