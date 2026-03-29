import { useEffect, useRef, useState, useMemo } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { startCapture, stopCapture, fetchInterfaces, captureStatus, fetchCurrentCaptureFile } from "../lib/api";
import { Play, Square, RefreshCw, Filter, HardDrive } from "lucide-react";

const PROTOCOLS = ["", "TCP", "UDP", "HTTP", "HTTPS", "TLS", "DNS", "ICMP", "ARP", "OTHER"];

// ── BPF / tshark filter suggestion bank ────────────────────────────────────

interface FilterSuggestion {
  filter: string;
  description: string;
  category: string;
}

const FILTER_SUGGESTIONS: FilterSuggestion[] = [
  // ── Protocols ──────────────────────────────────────────────────────────────
  { filter: "tcp",                                  description: "TCP packets only",              category: "Protocol" },
  { filter: "udp",                                  description: "UDP packets only",              category: "Protocol" },
  { filter: "icmp",                                 description: "ICMP (ping / unreachable)",     category: "Protocol" },
  { filter: "arp",                                  description: "ARP packets",                   category: "Protocol" },
  { filter: "ip",                                   description: "IPv4 packets",                  category: "Protocol" },
  { filter: "ip6",                                  description: "IPv6 packets",                  category: "Protocol" },
  { filter: "not arp",                              description: "Exclude ARP",                   category: "Exclude"  },

  // ── Ports ──────────────────────────────────────────────────────────────────
  { filter: "port 80",                              description: "HTTP",                          category: "Port"     },
  { filter: "port 443",                             description: "HTTPS / TLS",                   category: "Port"     },
  { filter: "port 53",                              description: "DNS",                           category: "Port"     },
  { filter: "port 22",                              description: "SSH",                           category: "Port"     },
  { filter: "port 21",                              description: "FTP control",                   category: "Port"     },
  { filter: "port 25",                              description: "SMTP",                          category: "Port"     },
  { filter: "port 3389",                            description: "RDP",                           category: "Port"     },
  { filter: "portrange 1024-65535",                 description: "Ephemeral ports",               category: "Port"     },

  // ── Protocol + Port ────────────────────────────────────────────────────────
  { filter: "tcp port 80",                          description: "TCP HTTP",                      category: "Proto+Port" },
  { filter: "tcp port 443",                         description: "TCP HTTPS",                     category: "Proto+Port" },
  { filter: "tcp port 22",                          description: "TCP SSH",                       category: "Proto+Port" },
  { filter: "udp port 53",                          description: "UDP DNS",                       category: "Proto+Port" },
  { filter: "tcp and (port 80 or port 443)",        description: "Web traffic",                   category: "Proto+Port" },

  // ── Host / Net ─────────────────────────────────────────────────────────────
  { filter: "host 192.168.1.1",                     description: "Traffic to/from host",          category: "Host"     },
  { filter: "src host 192.168.1.1",                 description: "From source host",              category: "Host"     },
  { filter: "dst host 8.8.8.8",                     description: "To destination host",           category: "Host"     },
  { filter: "not host 192.168.1.1",                 description: "Exclude host",                  category: "Host"     },
  { filter: "net 192.168.0.0/24",                   description: "Subnet /24",                    category: "Network"  },
  { filter: "src net 10.0.0.0/8",                   description: "From 10.x.x.x",                category: "Network"  },
  { filter: "dst net 172.16.0.0/12",                description: "To 172.16-31.x.x",             category: "Network"  },

  // ── TCP flags ──────────────────────────────────────────────────────────────
  { filter: "tcp[tcpflags] & tcp-syn != 0",         description: "SYN packets (new connections)", category: "TCP Flags" },
  { filter: "tcp[tcpflags] == tcp-rst",             description: "TCP RST (rejected/reset)",      category: "TCP Flags" },
  { filter: "tcp[tcpflags] & (tcp-syn|tcp-fin) != 0", description: "SYN or FIN",                 category: "TCP Flags" },
  { filter: "tcp[tcpflags] & tcp-push != 0",        description: "PSH flag (data push)",          category: "TCP Flags" },

  // ── Packet size ────────────────────────────────────────────────────────────
  { filter: "greater 1400",                         description: "Jumbo / near-MTU packets",      category: "Size"     },
  { filter: "less 64",                              description: "Tiny packets",                  category: "Size"     },
  { filter: "greater 1000 and tcp",                 description: "Large TCP segments",            category: "Size"     },

  // ── Broadcast / Multicast ──────────────────────────────────────────────────
  { filter: "broadcast",                            description: "Broadcast frames",              category: "Special"  },
  { filter: "multicast",                            description: "Multicast frames",              category: "Special"  },
  { filter: "not broadcast and not multicast",      description: "Unicast only",                  category: "Special"  },

  // ── ICS / OT ───────────────────────────────────────────────────────────────
  { filter: "port 502",                             description: "Modbus TCP",                    category: "ICS"      },
  { filter: "port 20000",                           description: "DNP3",                          category: "ICS"      },
  { filter: "port 102",                             description: "S7comm (Siemens PLC)",          category: "ICS"      },
  { filter: "port 44818",                           description: "EtherNet/IP (Allen-Bradley)",   category: "ICS"      },
  { filter: "port 2404",                            description: "IEC 60870-5-104",               category: "ICS"      },
  { filter: "port 4840",                            description: "OPC-UA",                        category: "ICS"      },
  { filter: "port 502 or port 20000",               description: "Modbus + DNP3",                 category: "ICS"      },

  // ── Security / Anomaly ─────────────────────────────────────────────────────
  { filter: "tcp[13] == 0x02",                      description: "SYN scan detection",            category: "Security" },
  { filter: "tcp port 4444 or port 31337",          description: "Common backdoor ports",         category: "Security" },
  { filter: "icmp[icmptype] == icmp-echo",          description: "ICMP ping requests only",       category: "Security" },
  { filter: "not port 22 and not port 80 and not port 443", description: "Non-standard ports",   category: "Security" },

  // ── Compound / Common combos ───────────────────────────────────────────────
  { filter: "not port 22",                          description: "Exclude SSH",                   category: "Exclude"  },
  { filter: "not port 53",                          description: "Exclude DNS",                   category: "Exclude"  },
  { filter: "tcp and not port 22",                  description: "TCP excluding SSH",             category: "Exclude"  },
  { filter: "src net 192.168.0.0/16 and tcp",       description: "Local TCP traffic",             category: "Network"  },
];

// ── Smart matching ──────────────────────────────────────────────────────────

function matchSuggestions(input: string): FilterSuggestion[] {
  const q = input.trim().toLowerCase();
  if (!q) return FILTER_SUGGESTIONS.slice(0, 10);

  const starts: FilterSuggestion[] = [];
  const contains: FilterSuggestion[] = [];
  const descMatch: FilterSuggestion[] = [];

  for (const s of FILTER_SUGGESTIONS) {
    const f = s.filter.toLowerCase();
    const d = s.description.toLowerCase();
    const cat = s.category.toLowerCase();
    if (f.startsWith(q))        starts.push(s);
    else if (f.includes(q) || cat.includes(q)) contains.push(s);
    else if (d.includes(q))     descMatch.push(s);
  }

  return [...starts, ...contains, ...descMatch].slice(0, 10);
}

// ── Autocomplete input component ────────────────────────────────────────────

interface BpfInputProps {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}

function BpfFilterInput({ value, onChange, disabled }: BpfInputProps) {
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const suggestions = useMemo(() => matchSuggestions(value), [value]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Keep active item scrolled into view
  useEffect(() => {
    if (activeIdx >= 0 && listRef.current) {
      const li = listRef.current.children[activeIdx] as HTMLElement;
      li?.scrollIntoView({ block: "nearest" });
    }
  }, [activeIdx]);

  const select = (filter: string) => {
    onChange(filter);
    setOpen(false);
    setActiveIdx(-1);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      if (e.key === "ArrowDown") { setOpen(true); setActiveIdx(0); e.preventDefault(); }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIdx((i) => Math.min(i + 1, suggestions.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIdx((i) => (i <= 0 ? -1 : i - 1));
        break;
      case "Enter":
        if (activeIdx >= 0) { e.preventDefault(); select(suggestions[activeIdx].filter); }
        break;
      case "Tab":
        if (activeIdx >= 0) { e.preventDefault(); select(suggestions[activeIdx].filter); }
        else setOpen(false);
        break;
      case "Escape":
        setOpen(false);
        setActiveIdx(-1);
        break;
    }
  };

  const CATEGORY_COLORS: Record<string, string> = {
    Protocol:   "rgb(var(--color-accent))",
    Port:       "rgb(var(--color-success))",
    "Proto+Port": "rgb(var(--color-success-emphasis))",
    Host:       "rgb(var(--color-tool))",
    Network:    "rgb(var(--color-warning))",
    "TCP Flags":"rgb(var(--color-purple))",
    Size:       "rgb(var(--color-accent-muted))",
    Special:    "rgb(var(--color-muted))",
    ICS:        "rgb(var(--color-danger))",
    Security:   "rgb(var(--color-severe))",
    Exclude:    "rgb(var(--color-muted-dim))",
  };

  return (
    <div ref={containerRef} className="relative flex-1 min-w-[160px]">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActiveIdx(-1); }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="BPF filter (e.g. tcp port 80)"
        autoComplete="off"
        spellCheck={false}
        className="w-full bg-surface border border-border text-foreground text-xs rounded px-2 py-1 focus:outline-none focus:border-accent disabled:opacity-50 placeholder-muted-dim font-mono"
      />

      {open && !disabled && suggestions.length > 0 && (
        <ul
          ref={listRef}
          className="absolute top-full left-0 right-0 z-50 mt-0.5 rounded border border-border shadow-xl overflow-y-auto bg-surface"
          style={{ maxHeight: 280 }}
        >
          {suggestions.map((s, i) => (
            <li
              key={s.filter}
              onMouseDown={(e) => { e.preventDefault(); select(s.filter); }}
              onMouseEnter={() => setActiveIdx(i)}
              className={`flex items-center gap-2 px-2 py-1.5 cursor-pointer ${i === activeIdx ? "bg-surface-hover" : ""} ${i < suggestions.length - 1 ? "border-b border-border" : ""}`}
            >
              {/* Category dot — dynamic color must stay inline */}
              <span
                className="shrink-0 w-1.5 h-1.5 rounded-full"
                style={{ background: CATEGORY_COLORS[s.category] ?? "rgb(var(--color-muted))" }}
              />
              {/* Filter text */}
              <span className="font-mono text-[11px] text-foreground shrink-0">
                {s.filter}
              </span>
              {/* Description */}
              <span className="text-[10px] text-muted flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
                {s.description}
              </span>
              {/* Category badge — dynamic border/color must stay inline */}
              <span
                className="text-[9px] px-1 py-px rounded font-mono bg-surface-hover shrink-0 opacity-80"
                style={{
                  color: CATEGORY_COLORS[s.category] ?? "rgb(var(--color-muted-dim))",
                  border: `1px solid ${CATEGORY_COLORS[s.category] ?? "transparent"}`,
                }}>
                {s.category}
              </span>
            </li>
          ))}
          <li className="px-2 py-1 bg-background text-[9px] text-muted flex justify-between border-t border-border">
            <span>↑↓ navigate</span>
            <span>↵ / Tab select</span>
            <span>Esc close</span>
          </li>
        </ul>
      )}
    </div>
  );
}

// ── FilterBar ───────────────────────────────────────────────────────────────

export function FilterBar() {
  const {
    interfaces, setInterfaces,
    activeInterface, setActiveInterface,
    bpfFilter, setBpfFilter,
    isCapturing, setIsCapturing,
    selectedProtocol, setSelectedProtocol,
  } = useStore(
    useShallow((s) => ({
      interfaces: s.interfaces, setInterfaces: s.setInterfaces,
      activeInterface: s.activeInterface, setActiveInterface: s.setActiveInterface,
      bpfFilter: s.bpfFilter, setBpfFilter: s.setBpfFilter,
      isCapturing: s.isCapturing, setIsCapturing: s.setIsCapturing,
      selectedProtocol: s.selectedProtocol, setSelectedProtocol: s.setSelectedProtocol,
    }))
  );

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [error, setError] = useState("");
  const [backendCount, setBackendCount] = useState(0);
  const [captureFileName, setCaptureFileName] = useState("");

  useEffect(() => {
    fetchInterfaces().then(setInterfaces).catch(() => {});
  }, []);

  useEffect(() => {
    if (isCapturing) {
      pollRef.current = setInterval(async () => {
        try {
          const r = await captureStatus();
          setBackendCount(r.data.packet_count);
        } catch {}
      }, 2000);
    } else {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [isCapturing]);

  const handleStart = async () => {
    if (!activeInterface) { setError("Select a network interface first."); return; }
    setError("");
    setBackendCount(0);
    try {
      await startCapture(activeInterface, bpfFilter);
      setIsCapturing(true);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to start capture.");
    }
  };

  const handleStop = async () => {
    try { await stopCapture(); } catch {}
    setIsCapturing(false);
    setBackendCount(0);
    fetchCurrentCaptureFile().then((info) => {
      if (info.name) setCaptureFileName(info.name);
    }).catch(() => {});
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-background">
      {/* Interface selector */}
      <div className="flex items-center gap-1.5">
        <label className="text-muted text-xs shrink-0">Interface</label>
        <select
          value={activeInterface}
          onChange={(e) => setActiveInterface(e.target.value)}
          disabled={isCapturing}
          className="bg-surface border border-border text-foreground text-xs rounded px-2 py-1 min-w-[180px] focus:outline-none focus:border-accent disabled:opacity-50"
        >
          <option value="">-- select interface --</option>
          {interfaces.map((iface) => {
            const friendly = iface.name.match(/\(([^)]+)\)$/);
            return (
              <option key={iface.index} value={iface.device} title={iface.name}>
                {iface.index}. {friendly ? friendly[1] : iface.name}
              </option>
            );
          })}
        </select>
        <button
          onClick={() => fetchInterfaces().then(setInterfaces).catch(() => {})}
          disabled={isCapturing}
          className="p-1 text-muted hover:text-foreground disabled:opacity-50"
          title="Refresh interfaces"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* BPF filter with autocomplete */}
      <div className="flex items-center gap-1.5 flex-1 min-w-[160px]">
        <Filter className="w-3.5 h-3.5 text-muted shrink-0" />
        <BpfFilterInput
          value={bpfFilter}
          onChange={setBpfFilter}
          disabled={isCapturing}
        />
      </div>

      {/* Protocol filter */}
      <div className="flex items-center gap-1.5">
        <label className="text-muted text-xs shrink-0">Proto</label>
        <select
          value={selectedProtocol}
          onChange={(e) => setSelectedProtocol(e.target.value)}
          className="bg-surface border border-border text-foreground text-xs rounded px-2 py-1 focus:outline-none focus:border-accent"
        >
          {PROTOCOLS.map((p) => (
            <option key={p} value={p}>{p || "All"}</option>
          ))}
        </select>
      </div>

      {/* Packet count badge */}
      <div className="flex items-center gap-1 px-2 py-1 bg-surface border border-border rounded text-xs font-mono">
        <span className="text-muted">pkts</span>
        <span className={`font-semibold ${isCapturing ? "text-success" : "text-foreground"}`}>
          {backendCount.toLocaleString()}
        </span>
        {isCapturing && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-success animate-pulse ml-1" />
        )}
      </div>

      {/* Start / Stop */}
      {!isCapturing ? (
        <button onClick={handleStart}
          className="flex items-center gap-1.5 px-3 py-1 bg-success hover:bg-success/80 text-white text-xs rounded font-medium transition-colors">
          <Play className="w-3 h-3" /> Start Capture
        </button>
      ) : (
        <button onClick={handleStop}
          className="flex items-center gap-1.5 px-3 py-1 bg-danger hover:bg-danger/80 text-white text-xs rounded font-medium transition-colors">
          <Square className="w-3 h-3" /> Stop
        </button>
      )}

      {error && <span className="text-danger text-xs">{error}</span>}

      {captureFileName && !isCapturing && (
        <div className="flex items-center gap-1 text-xs text-muted ml-auto" title={captureFileName}>
          <HardDrive className="w-3 h-3 shrink-0" />
          <span className="max-w-[200px] truncate font-mono">{captureFileName}</span>
        </div>
      )}
    </div>
  );
}
