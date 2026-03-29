import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useStore } from "../store/useStore";
import { fetchPackets, fetchLocalIPs } from "../lib/api";
import { ChevronDown, X } from "lucide-react";
import type { Packet } from "../store/useStore";

const PROTOCOL_COLORS: Record<string, string> = {
  HTTP:  "text-accent",
  HTTPS: "text-accent",
  TLS:   "text-accent-muted",
  DNS:   "text-purple",
  TCP:   "text-success",
  UDP:   "text-warning",
  ICMP:  "text-severe",
  ARP:   "text-pink",
  OTHER: "text-muted",
};


function getRowClass(pkt: Packet): string {
  const d = pkt.details ?? {};
  if (
    d["tcp.analysis.retransmission"] === "1" ||
    d["tcp.analysis.out_of_order"] === "1" ||
    (pkt.protocol === "TCP" && pkt.info?.includes("[RST]"))
  ) return "row-error";
  if (
    d["tcp.analysis.zero_window"] === "1" ||
    d["tcp.analysis.duplicate_ack"] === "1"
  ) return "row-warn";
  switch (pkt.protocol) {
    case "TLSv1.2": case "TLSv1.3": case "SSL": return "row-tls";
    case "DNS": case "MDNS": case "LLMNR": return "row-dns";
    case "HTTP": case "HTTP2": return "row-http";
    case "UDP": return "row-udp";
    case "ARP": return "row-arp";
    case "ICMP": case "ICMPv6": return "row-icmp";
    default: return "row-tcp";
  }
}

/** Height constants for the virtualizer */
const ROW_HEIGHT = 34;
const DETAIL_HEIGHT = 160;

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return (
    d.toTimeString().split(" ")[0] +
    "." +
    String(d.getMilliseconds()).padStart(3, "0")
  );
}

function PacketDetail({ pkt }: { pkt: Packet }) {
  return (
    <div className="p-3 bg-background border-t border-border text-xs font-mono">
      <div className="grid grid-cols-2 gap-x-8 gap-y-1 mb-2">
        <div><span className="text-muted">ID:</span> <span className="text-foreground">{pkt.id}</span></div>
        <div><span className="text-muted">Time:</span> <span className="text-foreground">{formatTime(pkt.timestamp)}</span></div>
        <div><span className="text-muted">Protocol:</span> <span className={PROTOCOL_COLORS[pkt.protocol] || "text-muted"}>{pkt.protocol}</span></div>
        <div><span className="text-muted">Length:</span> <span className="text-foreground">{pkt.length} bytes</span></div>
        <div><span className="text-muted">Source:</span> <span className="text-foreground">{pkt.src_ip}:{pkt.src_port}</span></div>
        <div><span className="text-muted">Destination:</span> <span className="text-foreground">{pkt.dst_ip}:{pkt.dst_port}</span></div>
      </div>
      <div className="mb-2">
        <span className="text-muted">Layers: </span>
        {pkt.layers.map((l) => (
          <span key={l} className="mr-1 px-1.5 py-0.5 bg-surface border border-border rounded text-muted text-xs">{l}</span>
        ))}
      </div>
      {Object.entries(pkt.details).filter(([, v]) => v).map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-muted min-w-[160px]">{k}:</span>
          <span className="text-foreground break-all">{v}</span>
        </div>
      ))}
    </div>
  );
}

export function PacketTable() {
  const { isCapturing, selectedProtocol, setTotalPackets, localIPs, setLocalIPs } = useStore();

  // Build a Set for O(1) local-IP lookups
  const localIPSet = useMemo(() => new Set(localIPs), [localIPs]);

  // Fetch local machine IPs once on mount
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchLocalIPs().then(setLocalIPs).catch(() => {});
  }, []); // intentionally mount-only: setLocalIPs is a stable Zustand action

  const [packets, setPackets] = useState<Packet[]>([]);
  const [total, _setTotal] = useState(0);
  const setTotal = useCallback((n: number) => { _setTotal(n); setTotalPackets(n); }, [setTotalPackets]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [search, setSearch] = useState("");
  const [filterError, setFilterError] = useState("");

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Track whether we've done the initial full fetch for the current
  // filter/capture context.  Reset when filter or capture state changes.
  const initialFetchDoneRef = useRef(false);

  // Keep refs so poll closures see current values without stale captures.
  const packetsLenRef = useRef(0);
  packetsLenRef.current = packets.length;
  const searchRef = useRef(search);
  searchRef.current = search;
  const selectedProtocolRef = useRef(selectedProtocol);
  selectedProtocolRef.current = selectedProtocol;

  // Keep a ref to isCapturing for the previous-value check.
  const prevCapturingRef = useRef(isCapturing);

  // ── Data fetching ────────────────────────────────────────────────────────────

  useEffect(() => {
    // When protocol filter or search changes, reset and do a new full fetch.
    // Debounce the fetch when search is non-empty (wait for user to stop typing).
    initialFetchDoneRef.current = false;
    setPackets([]);
    setTotal(0); // also calls setTotalPackets internally
    setFilterError("");
    packetsLenRef.current = 0;

    const delay = search ? 400 : 0;

    const timer = setTimeout(async () => {
      try {
        const res = await fetchPackets(0, 5000, selectedProtocol, search);
        setTotal(res.total);
        setPackets(res.packets);
        packetsLenRef.current = res.packets.length;
        initialFetchDoneRef.current = true;
      } catch (e: any) {
        const msg = e?.response?.data?.detail || "";
        if (msg) setFilterError(msg);
        // Silently retry on next poll cycle for non-filter errors
      }
    }, delay);

    return () => {
      clearTimeout(timer);
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [selectedProtocol, search]);

  // ── Incremental polling during capture ───────────────────────────────────────

  useEffect(() => {
    // Clean up any existing poll
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    // When capture stops, do one final full re-sync to catch stragglers.
    if (prevCapturingRef.current && !isCapturing) {
      (async () => {
        try {
          const res = await fetchPackets(0, 5000, selectedProtocol, searchRef.current);
          setTotal(res.total);
          setPackets(res.packets);
          packetsLenRef.current = res.packets.length;
        } catch {}
      })();
    }
    prevCapturingRef.current = isCapturing;

    if (!isCapturing) return;

    // If we haven't finished the initial fetch yet, do a full fetch first.
    if (!initialFetchDoneRef.current) {
      (async () => {
        try {
          const res = await fetchPackets(0, 5000, selectedProtocol, searchRef.current);
          setTotal(res.total);
          setPackets(res.packets);
          packetsLenRef.current = res.packets.length;
          initialFetchDoneRef.current = true;
        } catch {}
      })();
    }

    // During capture: poll for new packets.
    // When a display filter is active, re-fetch the full filtered set each time
    // (tshark needs to re-scan the growing file). When no filter, use offset for
    // incremental fetching.
    const poll = async () => {
      const currentSearch = searchRef.current;
      const currentProtocol = selectedProtocolRef.current;
      try {
        if (currentSearch) {
          // Filter mode: re-run tshark on the full (growing) capture file
          const res = await fetchPackets(0, 5000, currentProtocol, currentSearch);
          setTotal(res.total);
          setPackets(res.packets);
          packetsLenRef.current = res.packets.length;
        } else {
          // Incremental mode: only fetch new packets
          const currentLen = packetsLenRef.current;
          const res = await fetchPackets(currentLen, 500, currentProtocol);
          setTotal(res.total);
          if (res.packets.length > 0) {
            setPackets((prev) => {
              const updated = [...prev, ...res.packets];
              packetsLenRef.current = updated.length;
              return updated;
            });
          }
        }
      } catch {}
    };

    pollRef.current = setInterval(poll, 500);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [isCapturing, selectedProtocol]);

  // ── Packets are already filtered by backend ───────────────────────────────────

  const filtered = packets;

  // ── Virtualizer ──────────────────────────────────────────────────────────────

  const rowVirtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: useCallback(
      (index: number) => {
        const pkt = filtered[index];
        if (pkt && selectedId === pkt.id) {
          return ROW_HEIGHT + DETAIL_HEIGHT;
        }
        return ROW_HEIGHT;
      },
      [filtered, selectedId]
    ),
    overscan: 10,
  });

  // When selectedId changes, tell the virtualizer to recalculate sizes.
  useEffect(() => {
    rowVirtualizer.measure();
  }, [selectedId, rowVirtualizer]);

  // ── Auto-scroll to bottom when new packets arrive ────────────────────────────

  useEffect(() => {
    if (autoScroll && filtered.length > 0) {
      rowVirtualizer.scrollToIndex(filtered.length - 1, { align: "end" });
    }
  }, [filtered.length, autoScroll, rowVirtualizer]);

  // ── Scroll tracking for auto-scroll toggle ──────────────────────────────────

  const handleScroll = () => {
    if (!scrollContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 80);
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  const virtualItems = rowVirtualizer.getVirtualItems();

  return (
    <div className="flex flex-col h-full">
      {/* Status bar */}
      <div className="flex items-center justify-between px-3 py-1 bg-surface border-b border-border text-xs text-muted shrink-0">
        <span>
          {filtered.length.toLocaleString()} shown
          {total > filtered.length && ` of ${total.toLocaleString()} total`}
          {selectedProtocol ? ` · ${selectedProtocol}` : ""}
          {isCapturing && (
            <span className="ml-2 text-success">● live</span>
          )}
        </span>
        {!autoScroll && filtered.length > 0 && (
          <button
            onClick={() => {
              setAutoScroll(true);
              rowVirtualizer.scrollToIndex(filtered.length - 1, { align: "end" });
            }}
            className="flex items-center gap-1 text-accent hover:underline"
            aria-label="Jump to latest packets"
          >
            <ChevronDown className="w-3 h-3" /> Jump to latest
          </button>
        )}
      </div>

      {/* tshark display filter bar */}
      <div className="flex flex-col border-b border-border bg-surface shrink-0">
        <div className="flex items-center gap-1.5 px-3 py-1.5">
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setFilterError(""); }}
            placeholder="tshark display filter (e.g. tcp, arp, ip.src == 1.2.3.4)"
            className={`flex-1 bg-background border text-foreground text-xs rounded px-2 py-1 focus:outline-none placeholder-muted ${filterError ? "border-danger focus:border-danger" : "border-border focus:border-accent"}`}
          />
          {search && (
            <button
              onClick={() => { setSearch(""); setFilterError(""); }}
              className="text-muted hover:text-foreground"
              aria-label="Clear filter"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        {filterError && (
          <div className="px-3 pb-1.5 text-xs text-danger">{filterError}</div>
        )}
      </div>

      {/* Table header (sticky, outside scroll container) */}
      <div className="bg-surface border-b border-border shrink-0">
        <div className="flex text-muted text-xs font-medium">
          <div className="px-2 py-1.5 w-12 shrink-0">#</div>
          <div className="px-2 py-1.5 w-28 shrink-0 whitespace-nowrap">Time</div>
          <div className="px-2 py-1.5 w-16 shrink-0">Proto</div>
          <div className="px-2 py-1.5 flex-1 min-w-0">Src IP</div>
          <div className="px-2 py-1.5 w-14 shrink-0">Sport</div>
          <div className="px-2 py-1.5 flex-1 min-w-0">Dst IP</div>
          <div className="px-2 py-1.5 w-14 shrink-0">Dport</div>
          <div className="px-2 py-1.5 w-14 shrink-0">Len</div>
          <div className="px-2 py-1.5 flex-[2] min-w-0">Info</div>
        </div>
      </div>

      {/* Virtualized scrollable body */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto"
      >
        {filtered.length === 0 ? (
          <div className="text-center text-muted py-16 text-sm">
            {search
              ? "No packets match the filter."
              : isCapturing
              ? "Waiting for packets..."
              : "No packets. Start a capture or upload a .pcap file."}
          </div>
        ) : (
          <div
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              width: "100%",
              position: "relative",
            }}
          >
            {virtualItems.map((virtualItem) => {
              const pkt = filtered[virtualItem.index];
              if (!pkt) return null;

              const proto = pkt.protocol || "OTHER";
              const isSelected = selectedId === pkt.id;
              const srcIsLocal = localIPSet.has(pkt.src_ip);
              const dstIsLocal = localIPSet.has(pkt.dst_ip);
              const isLocal = srcIsLocal || dstIsLocal;

              return (
                <div
                  key={virtualItem.key}
                  data-index={virtualItem.index}
                  ref={rowVirtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                >
                  {/* Main row */}
                  <div
                    onClick={() => setSelectedId(isSelected ? null : pkt.id)}
                    className={`flex text-xs border-b border-border/50 cursor-pointer transition-colors ${getRowClass(pkt)} ${isSelected ? "row-selected" : ""}`}
                    role="row"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId(isSelected ? null : pkt.id);
                      }
                    }}
                    aria-expanded={isSelected}
                    aria-label={`Packet ${pkt.id} ${proto} from ${pkt.src_ip || "unknown"} to ${pkt.dst_ip || "unknown"}${isLocal ? " (local interface)" : ""}`}
                    style={{ height: `${ROW_HEIGHT}px` }}
                  >
                    <div className="px-2 py-1 text-muted font-mono w-12 shrink-0 flex items-center">{pkt.id}</div>
                    <div className="px-2 py-1 text-muted font-mono w-28 shrink-0 whitespace-nowrap flex items-center">{formatTime(pkt.timestamp)}</div>
                    <div className={`px-2 py-1 font-semibold w-16 shrink-0 flex items-center ${PROTOCOL_COLORS[proto] || "text-muted"}`}>{proto}</div>
                    <div className={`px-2 py-1 font-mono flex-1 min-w-0 truncate flex items-center ${srcIsLocal ? "text-amber-400 font-bold" : "text-foreground"}`}>{pkt.src_ip || "-"}</div>
                    <div className="px-2 py-1 text-muted w-14 shrink-0 flex items-center">{pkt.src_port || "-"}</div>
                    <div className={`px-2 py-1 font-mono flex-1 min-w-0 truncate flex items-center ${dstIsLocal ? "text-amber-400 font-bold" : "text-foreground"}`}>{pkt.dst_ip || "-"}</div>
                    <div className="px-2 py-1 text-muted w-14 shrink-0 flex items-center">{pkt.dst_port || "-"}</div>
                    <div className="px-2 py-1 text-muted w-14 shrink-0 flex items-center">{pkt.length}</div>
                    <div className="px-2 py-1 text-foreground flex-[2] min-w-0 truncate flex items-center">{pkt.info}</div>
                  </div>

                  {/* Expanded detail panel */}
                  {isSelected && <PacketDetail pkt={pkt} />}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
