import { useState, useRef, useCallback, useEffect } from "react";
import { Brain, Play, X, Copy, Check, Wifi, Search, Download, Crosshair, ChevronDown, Loader2, Monitor, Clock, Radio, ShieldCheck } from "lucide-react";
import axios from "axios";
import { BASE } from "../lib/api";

// ── Tool definitions ──────────────────────────────────────────────────────────

interface ToolDef {
  id: string;
  label: string;
  description: string;
  hasTarget: boolean;
  targetPlaceholder?: string;
  hasExtra: boolean;
  extraPlaceholder?: string;
  extraDefault?: string;
}

const TOOLS: ToolDef[] = [
  {
    id: "ping",
    label: "ping",
    description: "Send ICMP echo requests to a host (-n 4)",
    hasTarget: true,
    targetPlaceholder: "Host / IP (e.g. 8.8.8.8)",
    hasExtra: false,
  },
  {
    id: "tracert",
    label: "tracert",
    description: "Trace the route to a host (no DNS lookup)",
    hasTarget: true,
    targetPlaceholder: "Host / IP (e.g. 8.8.8.8)",
    hasExtra: false,
  },
  {
    id: "arp",
    label: "arp",
    description: "Display the ARP cache (-a)",
    hasTarget: false,
    hasExtra: false,
  },
  {
    id: "netstat",
    label: "netstat",
    description: "Active connections and listening ports",
    hasTarget: false,
    hasExtra: true,
    extraPlaceholder: "Flags (e.g. -ano)",
    extraDefault: "-ano",
  },
  {
    id: "ipconfig",
    label: "ipconfig",
    description: "Network interface configuration",
    hasTarget: false,
    hasExtra: true,
    extraPlaceholder: "Flag (e.g. /all)",
    extraDefault: "/all",
  },
];

// ── Subnet scanner types ──────────────────────────────────────────────────────

interface HostResult {
  ip:          string;
  alive:       boolean;
  hostname:    string;
  netbios:     string;
  mac:         string;
  vendor:      string;
  latency_ms:  number;
}

type SortKey = keyof HostResult;

interface DetectedInterface {
  adapter: string;
  ip:      string;
  mask:    string;
  cidr:    string;
  prefix:  number;
  hosts:   number;
}

// ── SubnetScanner component ───────────────────────────────────────────────────

function SubnetScanner() {
  const [cidr, setCidr]               = useState("192.168.1.0/24");
  const [timeout, setTimeout_]        = useState("1.0");
  const [concurrency, setConcurrency] = useState("128");
  const [scanning, setScanning]       = useState(false);
  const [results, setResults]         = useState<HostResult[]>([]);
  const [progress, setProgress]       = useState({ scanned: 0, total: 0 });
  const [error, setError]             = useState("");
  const [sortKey, setSortKey]         = useState<SortKey>("ip");
  const [sortAsc, setSortAsc]         = useState(true);
  const [filter, setFilter]           = useState("");
  const [showAll, setShowAll]         = useState(false);
  const [detectedIfaces, setDetectedIfaces] = useState<DetectedInterface[]>([]);
  const [detecting, setDetecting]     = useState(false);
  const [showIfaceMenu, setShowIfaceMenu] = useState(false);
  const detectRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Close dropdown on outside click
  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (detectRef.current && !detectRef.current.contains(e.target as Node)) {
      setShowIfaceMenu(false);
    }
  }, []);

  // Register/unregister outside-click listener
  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [handleClickOutside]);

  const detectSubnet = useCallback(async () => {
    setDetecting(true);
    try {
      const resp = await fetch(`${BASE}/tools/my-subnet`);
      if (!resp.ok) throw new Error("Failed to detect subnet");
      const data = await resp.json();
      const ifaces: DetectedInterface[] = data.interfaces ?? [];
      setDetectedIfaces(ifaces);
      if (ifaces.length === 1) {
        // Auto-fill if only one interface
        setCidr(ifaces[0].cidr);
        setShowIfaceMenu(false);
      } else if (ifaces.length > 1) {
        setShowIfaceMenu(true);
      }
    } catch {
      setDetectedIfaces([]);
    } finally {
      setDetecting(false);
    }
  }, []);

  const selectInterface = (iface: DetectedInterface) => {
    setCidr(iface.cidr);
    setShowIfaceMenu(false);
  };

  const startScan = useCallback(async () => {
    if (scanning) {
      abortRef.current?.abort();
      setScanning(false);
      return;
    }

    setResults([]);
    setError("");
    setProgress({ scanned: 0, total: 0 });
    setScanning(true);

    const params = new URLSearchParams({
      cidr:        cidr.trim(),
      timeout:     timeout,
      concurrency: concurrency,
    });

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const resp = await fetch(`${BASE}/tools/subnet-scan?${params}`, {
        signal: ctrl.signal,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setError(err.detail ?? resp.statusText);
        return;
      }

      const reader  = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buffer    = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";

        for (const ev of events) {
          const dataLine = ev.split("\n").find((l) => l.startsWith("data: "));
          if (!dataLine) continue;
          try {
            const msg = JSON.parse(dataLine.slice(6));
            if (msg.type === "result") {
              setResults((prev) => [...prev, msg.data as HostResult]);
            } else if (msg.type === "progress") {
              setProgress(msg.data);
            } else if (msg.type === "error") {
              setError(msg.data.message);
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setError(err.message);
      }
    } finally {
      setScanning(false);
    }
  }, [scanning, cidr, timeout, concurrency]);

  // ── Sort & filter ─────────────────────────────────────────────────────────

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(true); }
  };

  const ipNum = (ip: string) =>
    ip.split(".").reduce((acc, o) => (acc << 8) + parseInt(o, 10), 0) >>> 0;

  const displayed = results
    .filter((r) => showAll || r.alive)
    .filter((r) => {
      if (!filter) return true;
      const f = filter.toLowerCase();
      return (
        r.ip.includes(f) ||
        r.hostname.toLowerCase().includes(f) ||
        r.netbios.toLowerCase().includes(f) ||
        r.mac.toLowerCase().includes(f) ||
        r.vendor.toLowerCase().includes(f)
      );
    })
    .sort((a, b) => {
      let va: string | number = a[sortKey] as string | number;
      let vb: string | number = b[sortKey] as string | number;
      if (sortKey === "ip") { va = ipNum(a.ip); vb = ipNum(b.ip); }
      if (sortKey === "latency_ms") { va = a.latency_ms; vb = b.latency_ms; }
      if (va < vb) return sortAsc ? -1 : 1;
      if (va > vb) return sortAsc ? 1 : -1;
      return 0;
    });

  // ── CSV export ────────────────────────────────────────────────────────────

  const exportCsv = () => {
    const header = "IP,Alive,Hostname,NetBIOS,MAC,Vendor,Latency(ms)";
    const rows = displayed.map((r) =>
      [r.ip, r.alive, r.hostname, r.netbios, r.mac, r.vendor, r.latency_ms].join(",")
    );
    const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = "subnet-scan.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  // ── Column header helper ──────────────────────────────────────────────────

  const ColHeader = ({ k, label }: { k: SortKey; label: string }) => (
    <th
      className="px-3 py-2 text-left cursor-pointer select-none whitespace-nowrap hover:text-foreground transition-colors"
      onClick={() => toggleSort(k)}
    >
      {label}
      {sortKey === k && (
        <span className="ml-1 text-accent">{sortAsc ? "▲" : "▼"}</span>
      )}
    </th>
  );

  const pct = progress.total > 0
    ? Math.round((progress.scanned / progress.total) * 100)
    : 0;

  const aliveCount = results.filter((r) => r.alive).length;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Controls ── */}
      <div className="shrink-0 border-b border-border bg-surface px-4 py-3 flex flex-wrap items-center gap-3">
        <Wifi className="w-4 h-4 text-accent shrink-0" />
        <input
          type="text"
          value={cidr}
          onChange={(e) => setCidr(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && startScan()}
          placeholder="Subnet (e.g. 192.168.1.0/24)"
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-48"
        />
        {/* Detect Subnet button */}
        <div ref={detectRef} className="relative">
          <button
            onClick={detectSubnet}
            disabled={detecting}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium border border-border text-muted hover:text-accent hover:border-accent transition-colors disabled:opacity-50"
            title="Detect my subnet"
          >
            {detecting
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Crosshair className="w-3.5 h-3.5" />}
            Detect
            {detectedIfaces.length > 1 && <ChevronDown className="w-3 h-3" />}
          </button>
          {/* Interface dropdown */}
          {showIfaceMenu && detectedIfaces.length > 0 && (
            <div className="absolute top-full left-0 mt-1 z-20 bg-surface border border-border rounded-md shadow-lg min-w-[320px] overflow-hidden">
              <div className="px-3 py-2 border-b border-border text-[10px] text-muted uppercase tracking-wider font-semibold">
                Select Network Interface
              </div>
              {detectedIfaces.map((iface, idx) => (
                <button
                  key={idx}
                  onClick={() => selectInterface(iface)}
                  className="w-full text-left px-3 py-2.5 hover:bg-accent-emphasis/15 transition-colors border-b border-border-subtle last:border-b-0 group"
                >
                  <div className="flex items-center gap-2">
                    <Monitor className="w-3.5 h-3.5 text-accent shrink-0" />
                    <span className="text-xs text-foreground font-medium">{iface.adapter}</span>
                  </div>
                  <div className="ml-[22px] mt-1 flex items-center gap-3 text-[10px]">
                    <span className="text-success font-mono">{iface.ip}</span>
                    <span className="text-muted">/</span>
                    <span className="text-purple font-mono">{iface.mask}</span>
                    <span className="text-muted">-</span>
                    <span className="text-severe font-mono">{iface.cidr}</span>
                    <span className="text-muted-dim">({iface.hosts} hosts)</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        <label className="text-muted text-xs shrink-0">Timeout</label>
        <input
          type="number"
          value={timeout}
          onChange={(e) => setTimeout_(e.target.value)}
          min="0.1" max="10" step="0.1"
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground w-16 focus:outline-none focus:border-accent"
        />
        <label className="text-muted text-xs shrink-0">Threads</label>
        <input
          type="number"
          value={concurrency}
          onChange={(e) => setConcurrency(e.target.value)}
          min="1" max="512"
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground w-16 focus:outline-none focus:border-accent"
        />

        <button
          onClick={startScan}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            scanning
              ? "bg-danger-emphasis hover:bg-danger-emphasis text-white"
              : "bg-success-emphasis hover:bg-success-emphasis-hover text-white"
          }`}
        >
          {scanning ? <><X className="w-3 h-3" /> Stop</> : <><Search className="w-3 h-3" /> Scan</>}
        </button>

        {results.length > 0 && !scanning && (
          <button
            onClick={exportCsv}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border border-border text-muted hover:text-foreground transition-colors"
          >
            <Download className="w-3 h-3" /> Export CSV
          </button>
        )}

        <label className="flex items-center gap-1.5 text-xs text-muted cursor-pointer ml-auto">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
            className="accent-accent"
          />
          Show offline
        </label>
      </div>

      {/* ── Progress bar ── */}
      {(scanning || progress.scanned > 0) && (
        <div className="shrink-0 px-4 py-2 bg-surface border-b border-border flex items-center gap-3">
          <div className="flex-1 bg-border rounded h-1.5 overflow-hidden">
            <div
              className="h-full bg-accent transition-all duration-300 rounded"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-muted shrink-0 tabular-nums">
            {progress.scanned}/{progress.total} — {aliveCount} alive
          </span>
        </div>
      )}

      {/* ── Filter bar (only when results exist) ── */}
      {results.length > 0 && (
        <div className="shrink-0 px-4 py-2 bg-background border-b border-border flex items-center gap-2">
          <Search className="w-3 h-3 text-muted shrink-0" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by IP, hostname, NetBIOS, MAC, vendor…"
            className="flex-1 bg-transparent text-xs text-foreground placeholder-muted-dim focus:outline-none"
          />
          {filter && (
            <button onClick={() => setFilter("")} className="text-muted hover:text-foreground">
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
      )}

      {/* ── Error ── */}
      {error && (
        <div className="shrink-0 px-4 py-2 bg-danger-emphasis/20 border-b border-danger-emphasis text-danger text-xs">
          {error}
        </div>
      )}

      {/* ── Results table ── */}
      <div className="flex-1 overflow-auto">
        {displayed.length === 0 && !scanning ? (
          <div className="flex items-center justify-center h-full text-muted-dim text-xs">
            {results.length === 0
              ? "Enter a subnet (e.g. 192.168.1.0/24) and click Scan."
              : "No hosts match the current filter."}
          </div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-surface text-muted border-b border-border z-10">
              <tr>
                <ColHeader k="ip"         label="IP Address"   />
                <ColHeader k="alive"      label="Status"       />
                <ColHeader k="latency_ms" label="Latency"      />
                <ColHeader k="hostname"   label="Hostname"     />
                <ColHeader k="netbios"    label="NetBIOS"      />
                <ColHeader k="mac"        label="MAC Address"  />
                <ColHeader k="vendor"     label="Vendor"       />
              </tr>
            </thead>
            <tbody>
              {displayed.map((r) => (
                <tr
                  key={r.ip}
                  className="border-b border-border-subtle hover:bg-surface transition-colors"
                >
                  <td className="px-3 py-1.5 font-mono text-foreground">{r.ip}</td>
                  <td className="px-3 py-1.5">
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      r.alive
                        ? "bg-success-emphasis/20 text-success"
                        : "bg-border text-muted"
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${r.alive ? "bg-success" : "bg-muted"}`} />
                      {r.alive ? "Online" : "Offline"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 font-mono text-muted tabular-nums">
                    {r.alive && r.latency_ms >= 0 ? `${r.latency_ms.toFixed(1)} ms` : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-foreground max-w-[180px] truncate" title={r.hostname}>
                    {r.hostname || <span className="text-muted-dim">—</span>}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-purple max-w-[140px] truncate" title={r.netbios}>
                    {r.netbios || <span className="text-muted-dim">—</span>}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-severe uppercase tracking-wide">
                    {r.mac || <span className="text-muted-dim normal-case tracking-normal">—</span>}
                  </td>
                  <td className="px-3 py-1.5 text-muted max-w-[160px] truncate" title={r.vendor}>
                    {r.vendor && r.vendor !== "Unknown"
                      ? <span className="text-foreground">{r.vendor}</span>
                      : <span className="text-muted-dim">{r.vendor || "—"}</span>}
                  </td>
                </tr>
              ))}
              {/* Skeleton rows while scanning */}
              {scanning && displayed.length === 0 && (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={`skel-${i}`} className="border-b border-border-subtle">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-3 py-1.5">
                        <div className="h-3 bg-border-subtle rounded animate-pulse w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── TerminalTools component (original ping/tracert/etc.) ──────────────────────

function TerminalTools() {
  const [selectedTool, setSelectedTool] = useState<ToolDef>(TOOLS[0]);
  const [target, setTarget]   = useState("");
  const [extra, setExtra]     = useState(TOOLS[0].extraDefault ?? "");
  const [lines, setLines]     = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [analysis, setAnalysis]   = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [copied, setCopied]       = useState(false);
  const abortRef  = useRef<AbortController | null>(null);
  const outputRef = useRef<HTMLDivElement>(null);

  const selectTool = (tool: ToolDef) => {
    setSelectedTool(tool);
    setTarget("");
    setExtra(tool.extraDefault ?? "");
    setLines([]);
    setAnalysis("");
    abortRef.current?.abort();
  };

  const runTool = useCallback(async () => {
    if (running) { abortRef.current?.abort(); return; }
    setLines([]);
    setAnalysis("");
    setRunning(true);

    const params = new URLSearchParams({ tool: selectedTool.id });
    if (target.trim()) params.set("target", target.trim());
    if (extra.trim())  params.set("extra",  extra.trim());

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const resp = await fetch(`${BASE}/tools/run?${params}`, { signal: ctrl.signal });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setLines([`[error] ${err.detail ?? resp.statusText}`]);
        return;
      }
      const reader  = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buffer    = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const ev of events) {
          const dataLine = ev.split("\n").find((l) => l.startsWith("data: "));
          if (!dataLine) continue;
          const text = dataLine.slice(6);
          if (text === "[DONE]") break;
          setLines((prev) => {
            const next = [...prev, text];
            setTimeout(() => {
              outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: "smooth" });
            }, 0);
            return next;
          });
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError")
        setLines((prev) => [...prev, `[error] ${err.message}`]);
    } finally {
      setRunning(false);
    }
  }, [running, selectedTool, target, extra]);

  const analyze = async () => {
    if (!lines.length || analyzing) return;
    setAnalyzing(true); setAnalysis("");
    try {
      const resp = await axios.post("/api/tools/analyze", { tool: selectedTool.id, output: lines.join("\n") });
      setAnalysis(resp.data.analysis ?? "");
    } catch (err: unknown) {
      const msg = axios.isAxiosError(err) ? err.response?.data?.detail ?? err.message : String(err);
      setAnalysis(`[error] ${msg}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const copyOutput = () => {
    navigator.clipboard.writeText(lines.join("\n")).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar */}
      <aside className="w-44 shrink-0 border-r border-border bg-surface flex flex-col py-2 gap-0.5">
        {TOOLS.map((tool) => (
          <button
            key={tool.id}
            onClick={() => selectTool(tool)}
            className={`text-left px-4 py-2.5 text-xs font-mono transition-colors ${
              selectedTool.id === tool.id
                ? "bg-accent-emphasis/20 text-accent border-l-2 border-accent"
                : "text-muted hover:text-foreground hover:bg-border-subtle border-l-2 border-transparent"
            }`}
          >
            <div className="font-semibold">{tool.label}</div>
            <div className="text-[10px] mt-0.5 opacity-70 leading-tight">{tool.description}</div>
          </button>
        ))}
      </aside>

      {/* Main panel */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Controls */}
        <div className="shrink-0 border-b border-border bg-surface px-4 py-3 flex items-center gap-3 flex-wrap">
          <span className="text-accent font-mono font-bold text-sm">{selectedTool.label}</span>
          {selectedTool.hasTarget && (
            <input
              type="text" value={target}
              onChange={(e) => setTarget(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTool()}
              placeholder={selectedTool.targetPlaceholder}
              className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-52"
            />
          )}
          {selectedTool.hasExtra && (
            <input
              type="text" value={extra}
              onChange={(e) => setExtra(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTool()}
              placeholder={selectedTool.extraPlaceholder}
              className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-32"
            />
          )}
          <button
            onClick={runTool}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              running ? "bg-danger-emphasis hover:bg-danger-emphasis text-white" : "bg-success-emphasis hover:bg-success-emphasis-hover text-white"
            }`}
          >
            {running ? <><X className="w-3 h-3" /> Stop</> : <><Play className="w-3 h-3" /> Run</>}
          </button>
          {lines.length > 0 && !running && (
            <>
              <button
                onClick={analyze} disabled={analyzing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-accent-emphasis hover:bg-accent-emphasis-hover text-white disabled:opacity-50 transition-colors"
              >
                <Brain className="w-3 h-3" />
                {analyzing ? "Analyzing…" : "Analyze with LLM"}
              </button>
              <button
                onClick={copyOutput}
                className="flex items-center gap-1.5 px-2 py-1.5 rounded text-xs text-muted hover:text-foreground transition-colors"
                title="Copy output"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </>
          )}
          {running && <span className="text-muted text-xs animate-pulse">running…</span>}
        </div>

        {/* Output area */}
        <div className="flex flex-1 overflow-hidden">
          <div
            ref={outputRef}
            className="flex-1 overflow-y-auto p-4 font-mono text-xs text-foreground bg-background leading-relaxed"
          >
            {lines.length === 0 && !running ? (
              <div className="text-muted-dim select-none">Select a tool, fill in options, and click Run.</div>
            ) : (
              lines.map((line, i) => (
                <div key={i} className={line.startsWith("[error]") ? "text-danger" : line === "" ? "h-3" : ""}>
                  {line || "\u00A0"}
                </div>
              ))
            )}
            {running && <div className="text-success animate-pulse mt-1">▌</div>}
          </div>
          {(analysis || analyzing) && (
            <div className="w-80 shrink-0 border-l border-border bg-surface overflow-y-auto p-4">
              <div className="text-accent text-xs font-semibold mb-3 flex items-center gap-1.5">
                <Brain className="w-3.5 h-3.5" /> LLM Analysis
              </div>
              {analyzing
                ? <div className="text-muted text-xs animate-pulse">Thinking…</div>
                : <div className="text-foreground text-xs leading-relaxed whitespace-pre-wrap">{analysis}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── NTP Tester ────────────────────────────────────────────────────────────────

interface NTPSample {
  sample: number;
  offset_ms: number;
  delay_ms: number;
  rx_time: number;
  stratum: number;
  ref_id: string;
  li: number;
  li_text: string;
  version: number;
  root_delay_ms: number;
  root_dispersion_ms: number;
  poll_interval_s: number;
  precision_exp: number;
}

interface NTPSummary {
  server: string;
  samples_ok: number;
  samples_err: number;
  stratum: number;
  ref_id: string;
  li: number;
  li_text: string;
  version: number;
  root_delay_ms: number;
  root_dispersion_ms: number;
  offset_mean_ms: number;
  offset_min_ms: number;
  offset_max_ms: number;
  offset_jitter_ms: number;
  delay_mean_ms: number;
  delay_min_ms: number;
  delay_max_ms: number;
}

function offsetColor(ms: number): string {
  const abs = Math.abs(ms);
  if (abs < 10)  return "text-success";
  if (abs < 100) return "text-warning";
  return "text-danger";
}

function NTPTool() {
  const [server,  setServer]  = useState("pool.ntp.org");
  const [samples, setSamples] = useState("4");
  const [timeout, setTimeout_] = useState("5");
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<NTPSummary | null>(null);
  const [rows,    setRows]    = useState<NTPSample[]>([]);
  const [errors,  setErrors]  = useState<{ sample: number; error: string }[]>([]);
  const [error,   setError]   = useState("");
  const [analysis, setAnalysis]   = useState("");
  const [analyzing, setAnalyzing] = useState(false);

  const run = async () => {
    if (running) return;
    setRunning(true); setSummary(null); setRows([]); setErrors([]); setError(""); setAnalysis("");
    try {
      const params = new URLSearchParams({
        server,
        samples: String(Math.min(Math.max(parseInt(samples) || 4, 1), 10)),
        timeout: String(Math.min(Math.max(parseFloat(timeout) || 5, 1), 15)),
      });
      const res = await fetch(`${BASE}/tools/ntp?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setError(err.detail ?? res.statusText);
        return;
      }
      const data = await res.json();
      setSummary(data.summary);
      setRows(data.samples ?? []);
      setErrors(data.errors ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const analyze = async () => {
    if (!summary || analyzing) return;
    setAnalyzing(true); setAnalysis("");
    try {
      const desc = [
        `NTP server: ${summary.server}`,
        `Stratum: ${summary.stratum}, Ref: ${summary.ref_id}`,
        `Offset: mean ${summary.offset_mean_ms} ms, jitter ${summary.offset_jitter_ms} ms`,
        `Round-trip delay: mean ${summary.delay_mean_ms} ms`,
        `Root delay: ${summary.root_delay_ms} ms, Root dispersion: ${summary.root_dispersion_ms} ms`,
        `LI: ${summary.li_text}`,
        `Samples OK: ${summary.samples_ok}, Errors: ${summary.samples_err}`,
      ].join("\n");
      const resp = await axios.post("/api/tools/analyze", { tool: "ntp", output: desc });
      setAnalysis(resp.data.analysis ?? "");
    } catch (e: unknown) {
      setAnalysis(`[error] ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const liColor = summary
    ? summary.li === 3 ? "text-danger" : summary.li > 0 ? "text-warning" : "text-success"
    : "text-muted";

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Controls */}
      <div className="shrink-0 border-b border-border bg-surface px-4 py-3 flex flex-wrap items-center gap-3">
        <Clock className="w-4 h-4 text-accent shrink-0" />
        <input
          type="text" value={server} onChange={e => setServer(e.target.value)}
          onKeyDown={e => e.key === "Enter" && run()}
          placeholder="NTP server (e.g. pool.ntp.org)"
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-52"
        />
        <label className="text-muted text-xs shrink-0">Samples</label>
        <input
          type="number" value={samples} onChange={e => setSamples(e.target.value)}
          min={1} max={10}
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground w-14 focus:outline-none focus:border-accent"
        />
        <label className="text-muted text-xs shrink-0">Timeout (s)</label>
        <input
          type="number" value={timeout} onChange={e => setTimeout_(e.target.value)}
          min={1} max={15}
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground w-14 focus:outline-none focus:border-accent"
        />
        <button
          onClick={run} disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-success-emphasis hover:bg-success-emphasis-hover text-white disabled:opacity-50 transition-colors"
        >
          {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
          {running ? "Querying…" : "Query"}
        </button>
        {summary && !running && (
          <button
            onClick={analyze} disabled={analyzing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-accent-emphasis hover:bg-accent-emphasis-hover text-white disabled:opacity-50 transition-colors"
          >
            <Brain className="w-3 h-3" />
            {analyzing ? "Analyzing…" : "Analyze with LLM"}
          </button>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="shrink-0 px-4 py-2 bg-danger-emphasis/20 border-b border-danger text-danger text-xs">{error}</div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {!summary && !running && !error && (
          <div className="flex items-center justify-center h-full text-muted-dim text-xs">
            Enter an NTP server and click Query.
          </div>
        )}

        {/* Summary cards */}
        {summary && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {/* Offset */}
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Mean Offset</div>
              <div className={`text-xl font-mono font-bold ${offsetColor(summary.offset_mean_ms)}`}>
                {summary.offset_mean_ms > 0 ? "+" : ""}{summary.offset_mean_ms} ms
              </div>
              <div className="text-[10px] text-muted mt-1">
                jitter {summary.offset_jitter_ms} ms &nbsp;·&nbsp;
                [{summary.offset_min_ms}, {summary.offset_max_ms}]
              </div>
            </div>
            {/* Delay */}
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Round-Trip Delay</div>
              <div className="text-xl font-mono font-bold text-foreground">{summary.delay_mean_ms} ms</div>
              <div className="text-[10px] text-muted mt-1">
                min {summary.delay_min_ms} ms · max {summary.delay_max_ms} ms
              </div>
            </div>
            {/* Stratum */}
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Stratum</div>
              <div className="text-xl font-mono font-bold text-accent">{summary.stratum}</div>
              <div className="text-[10px] text-muted mt-1 truncate" title={summary.ref_id}>
                Ref: {summary.ref_id || "—"}
              </div>
            </div>
            {/* LI / Status */}
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Leap Indicator</div>
              <div className={`text-sm font-semibold ${liColor}`}>{summary.li_text}</div>
              <div className="text-[10px] text-muted mt-1">
                Root delay {summary.root_delay_ms} ms · dispersion {summary.root_dispersion_ms} ms
              </div>
            </div>
          </div>
        )}

        {/* Per-sample table */}
        {rows.length > 0 && (
          <div className="border border-border rounded overflow-hidden">
            <div className="px-3 py-2 bg-surface border-b border-border text-[10px] text-muted uppercase tracking-wider font-semibold">
              Per-sample measurements
            </div>
            <table className="w-full text-xs border-collapse">
              <thead className="bg-surface text-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">#</th>
                  <th className="px-3 py-2 text-right font-medium">Offset (ms)</th>
                  <th className="px-3 py-2 text-right font-medium">Delay (ms)</th>
                  <th className="px-3 py-2 text-left font-medium">Stratum</th>
                  <th className="px-3 py-2 text-left font-medium">Ref ID</th>
                  <th className="px-3 py-2 text-left font-medium">LI</th>
                  <th className="px-3 py-2 text-right font-medium">Root Delay</th>
                  <th className="px-3 py-2 text-right font-medium">Root Disp.</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.sample} className="border-t border-border-subtle hover:bg-surface transition-colors">
                    <td className="px-3 py-1.5 text-muted">{r.sample}</td>
                    <td className={`px-3 py-1.5 text-right font-mono font-semibold ${offsetColor(r.offset_ms)}`}>
                      {r.offset_ms > 0 ? "+" : ""}{r.offset_ms}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-foreground">{r.delay_ms}</td>
                    <td className="px-3 py-1.5 font-mono text-accent">{r.stratum}</td>
                    <td className="px-3 py-1.5 font-mono text-foreground">{r.ref_id}</td>
                    <td className={`px-3 py-1.5 text-[10px] ${r.li === 3 ? "text-danger" : r.li > 0 ? "text-warning" : "text-success"}`}>
                      {r.li_text}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-muted">{r.root_delay_ms} ms</td>
                    <td className="px-3 py-1.5 text-right font-mono text-muted">{r.root_dispersion_ms} ms</td>
                  </tr>
                ))}
                {errors.map(e => (
                  <tr key={e.sample} className="border-t border-border-subtle">
                    <td className="px-3 py-1.5 text-muted">{e.sample}</td>
                    <td colSpan={7} className="px-3 py-1.5 text-danger text-[10px]">{e.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* LLM analysis */}
        {(analysis || analyzing) && (
          <div className="border border-border rounded p-4 bg-surface">
            <div className="text-accent text-xs font-semibold mb-2 flex items-center gap-1.5">
              <Brain className="w-3.5 h-3.5" /> LLM Analysis
            </div>
            {analyzing
              ? <div className="text-muted text-xs animate-pulse">Thinking…</div>
              : <div className="text-foreground text-xs leading-relaxed whitespace-pre-wrap">{analysis}</div>}
          </div>
        )}
      </div>
    </div>
  );
}


// ── PTP Probe ─────────────────────────────────────────────────────────────────

interface PTPClock {
  src_ip: string;
  ptp_version: number;
  domain: number;
  clock_id: string;
  port: number;
  log_announce_interval: number;
  utc_offset_s: number;
  gm_priority1: number;
  gm_priority2: number;
  gm_clock_class: number;
  gm_clock_accuracy: string;
  gm_offset_scaled_log_variance: number;
  gm_identity: string;
  steps_removed: number;
  time_source: string;
  two_step: boolean;
  utc_reasonable: boolean;
  leap_61: boolean;
  leap_59: boolean;
}

interface PTPResult {
  clocks: PTPClock[];
  count: number;
  all_msg_counts: Record<string, number>;
  warnings: string[];
  duration_s: number;
  multicast_group: string;
  port: number;
}

function gmPriorityColor(p: number): string {
  if (p <= 64)  return "text-success";
  if (p <= 128) return "text-warning";
  return "text-muted";
}

function PTPTool() {
  const [timeout, setTimeout_] = useState("5");
  const [iface,   setIface]   = useState("");
  const [running, setRunning] = useState(false);
  const [result,  setResult]  = useState<PTPResult | null>(null);
  const [error,   setError]   = useState("");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const run = async () => {
    if (running) return;
    setRunning(true); setResult(null); setError(""); setElapsed(0);
    const started = Date.now();
    timerRef.current = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    try {
      const params = new URLSearchParams({
        timeout: String(Math.min(Math.max(parseFloat(timeout) || 5, 1), 30)),
      });
      if (iface.trim()) params.set("iface", iface.trim());
      const res = await fetch(`${BASE}/tools/ptp?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setError(err.detail ?? res.statusText);
        return;
      }
      const data: PTPResult = await res.json();
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      clearInterval(timerRef.current!);
      setRunning(false);
    }
  };

  const totalMsgs = result
    ? Object.values(result.all_msg_counts).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Controls */}
      <div className="shrink-0 border-b border-border bg-surface px-4 py-3 flex flex-wrap items-center gap-3">
        <Radio className="w-4 h-4 text-accent shrink-0" />
        <label className="text-muted text-xs shrink-0">Listen (s)</label>
        <input
          type="number" value={timeout} onChange={e => setTimeout_(e.target.value)}
          min={1} max={30}
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground w-14 focus:outline-none focus:border-accent"
        />
        <input
          type="text" value={iface} onChange={e => setIface(e.target.value)}
          placeholder="Local IP (optional)"
          className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-36"
        />
        <button
          onClick={run} disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-success-emphasis hover:bg-success-emphasis-hover text-white disabled:opacity-50 transition-colors"
        >
          {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
          {running ? `Listening… ${elapsed}s` : "Listen"}
        </button>
        <span className="text-[10px] text-muted ml-auto">
          Multicast 224.0.1.129:320 · IEEE 1588-2008
        </span>
      </div>

      {/* Error banner */}
      {error && (
        <div className="shrink-0 px-4 py-2 bg-danger-emphasis/20 border-b border-danger text-danger text-xs whitespace-pre-wrap">{error}</div>
      )}

      {/* Warnings */}
      {result?.warnings?.map((w, i) => (
        <div key={i} className="shrink-0 px-4 py-1.5 bg-warning-subtle border-b border-attention text-attention text-[10px]">{w}</div>
      ))}

      {/* Body */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {!result && !running && !error && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <Radio className="w-8 h-8 text-muted-dim" />
            <p className="text-muted-dim text-xs max-w-xs">
              Listens on UDP port 320 for PTP Announce messages from IEEE 1588 grandmaster clocks.
              <br /><br />
              Requires UDP port 320 to be available. Run as administrator if binding fails.
            </p>
          </div>
        )}

        {running && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="relative w-16 h-16">
              <div className="absolute inset-0 rounded-full border-2 border-accent/20 animate-ping" />
              <div className="absolute inset-2 rounded-full border-2 border-accent/40 animate-ping" style={{ animationDelay: "0.5s" }} />
              <Radio className="absolute inset-0 m-auto w-6 h-6 text-accent" />
            </div>
            <p className="text-muted text-xs">Listening on 224.0.1.129:320 — {elapsed}s / {timeout}s</p>
          </div>
        )}

        {/* Stats row */}
        {result && (
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Clocks Found</div>
              <div className={`text-2xl font-mono font-bold ${result.count > 0 ? "text-success" : "text-muted"}`}>{result.count}</div>
            </div>
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">PTP Frames</div>
              <div className="text-2xl font-mono font-bold text-foreground">{totalMsgs}</div>
            </div>
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Listen Time</div>
              <div className="text-2xl font-mono font-bold text-foreground">{result.duration_s}s</div>
            </div>
            {Object.keys(result.all_msg_counts).length > 0 && (
              <div className="bg-surface border border-border rounded p-3 col-span-1 sm:col-span-1">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Message Types</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {Object.entries(result.all_msg_counts).map(([k, v]) => (
                    <span key={k} className="text-[9px] font-mono bg-border px-1.5 py-0.5 rounded text-muted">
                      {k} ×{v}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* No clocks found */}
        {result && result.count === 0 && (
          <div className="border border-border rounded p-6 text-center text-muted text-xs">
            No PTP Announce messages received in {result.duration_s}s.<br />
            <span className="text-muted-dim">Ensure a PTP grandmaster is active on the network segment and multicast routing is enabled.</span>
          </div>
        )}

        {/* Clock cards */}
        {result?.clocks.map(clock => (
          <div key={clock.clock_id} className="border border-border rounded overflow-hidden">
            {/* Card header */}
            <div className="px-4 py-2.5 bg-surface border-b border-border flex items-center gap-3 flex-wrap">
              <span className="font-mono text-xs text-accent font-bold">{clock.clock_id}</span>
              <span className="text-[10px] text-muted">from {clock.src_ip}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-border text-foreground font-mono">PTPv{clock.ptp_version}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-border text-foreground font-mono">Domain {clock.domain}</span>
              {clock.two_step && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-emphasis/20 text-accent">Two-step</span>
              )}
              {clock.utc_reasonable && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-success-emphasis/20 text-success">UTC reasonable</span>
              )}
              {clock.leap_61 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning-subtle text-attention">Leap +61</span>
              )}
              {clock.leap_59 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning-subtle text-attention">Leap +59</span>
              )}
            </div>
            {/* Two-column detail grid */}
            <div className="grid grid-cols-2 gap-0 sm:grid-cols-4 text-xs">
              {[
                ["GM Identity",   clock.gm_identity],
                ["GM Priority 1", <span className={gmPriorityColor(clock.gm_priority1)}>{clock.gm_priority1}</span>],
                ["GM Priority 2", <span className={gmPriorityColor(clock.gm_priority2)}>{clock.gm_priority2}</span>],
                ["Clock Class",   clock.gm_clock_class],
                ["Accuracy",      clock.gm_clock_accuracy],
                ["Time Source",   clock.time_source],
                ["Steps Removed", clock.steps_removed],
                ["UTC Offset",    `${clock.utc_offset_s} s`],
                ["Port",          clock.port],
                ["Ann. Interval", `${Math.pow(2, clock.log_announce_interval).toFixed(1)} s`],
              ].map(([label, value], i) => (
                <div key={i} className="border-r border-b border-border-subtle px-3 py-2">
                  <div className="text-[9px] text-muted uppercase tracking-wider mb-0.5">{label}</div>
                  <div className="font-mono text-foreground truncate">{value}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


// ── Top-level NetworkTools with tab switcher ──────────────────────────────────

type Tab = "scanner" | "tools" | "time";

export function NetworkTools() {
  const [tab, setTab] = useState<Tab>("scanner");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="shrink-0 flex border-b border-border bg-background px-2 pt-1 gap-1">
        <button
          onClick={() => setTab("scanner")}
          className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-t transition-colors ${
            tab === "scanner"
              ? "bg-surface text-foreground border border-b-surface border-border"
              : "text-muted hover:text-foreground"
          }`}
        >
          <Wifi className="w-3.5 h-3.5" /> Subnet Scanner
        </button>
        <button
          onClick={() => setTab("tools")}
          className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-t transition-colors ${
            tab === "tools"
              ? "bg-surface text-foreground border border-b-surface border-border"
              : "text-muted hover:text-foreground"
          }`}
        >
          <Play className="w-3.5 h-3.5" /> Network Tools
        </button>
        <button
          onClick={() => setTab("time")}
          className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-t transition-colors ${
            tab === "time"
              ? "bg-surface text-foreground border border-b-surface border-border"
              : "text-muted hover:text-foreground"
          }`}
        >
          <Clock className="w-3.5 h-3.5" /> Time Protocols
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {tab === "scanner" ? <SubnetScanner /> : tab === "tools" ? <TerminalTools /> : <TimeProtocolsTab />}
      </div>
    </div>
  );
}

// ── Time Protocols sub-tab ────────────────────────────────────────────────────

// ── NTP Sync Check ─────────────────────────────────────────────────────────────

interface NTPHostResult {
  host: string; reachable: boolean; offset_ms: number; stratum: number;
  ref_id: string; li_text: string; delay_ms: number; jitter_ms: number;
  samples_ok: number; samples_err: number;
}
interface NTPCompareResult {
  reference: NTPHostResult; target: NTPHostResult;
  skew_ms: number | null; threshold_ms: number;
  in_sync: boolean; status: string;
  ref_error: string | null; target_error: string | null;
}

function syncStatusColor(status: string): string {
  if (status === "excellent") return "text-success";
  if (status === "good")      return "text-success";
  if (status === "marginal")  return "text-warning";
  if (status === "out_of_sync") return "text-danger";
  return "text-muted";
}
function syncStatusLabel(status: string): string {
  if (status === "excellent")   return "✓ Excellent sync";
  if (status === "good")        return "✓ Good sync";
  if (status === "marginal")    return "⚠ Marginal";
  if (status === "out_of_sync") return "✗ Out of sync";
  if (status === "unreachable") return "✗ Target unreachable";
  return "— Error";
}

function HostCard({ result, label, error }: { result: NTPHostResult; label: string; error: string | null }) {
  return (
    <div className="bg-surface border border-border rounded p-3 flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">{label}</span>
        {result.reachable
          ? <span className="text-[10px] text-success font-mono">● reachable</span>
          : <span className="text-[10px] text-danger font-mono">● unreachable</span>}
      </div>
      <div className="text-xs font-mono text-accent truncate">{result.host}</div>
      {result.reachable ? (
        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
          <div><span className="text-muted">offset </span><span className={offsetColor(result.offset_ms)}>{result.offset_ms > 0 ? "+" : ""}{result.offset_ms} ms</span></div>
          <div><span className="text-muted">delay </span><span className="text-foreground">{result.delay_ms} ms</span></div>
          <div><span className="text-muted">stratum </span><span className="text-foreground">{result.stratum}</span></div>
          <div><span className="text-muted">ref </span><span className="text-foreground">{result.ref_id}</span></div>
          <div><span className="text-muted">jitter </span><span className="text-foreground">{result.jitter_ms} ms</span></div>
          <div><span className="text-muted">samples </span><span className="text-foreground">{result.samples_ok}/{result.samples_ok + result.samples_err}</span></div>
        </div>
      ) : (
        <div className="text-[11px] text-danger">{error ?? "No response to NTP query"}</div>
      )}
    </div>
  );
}

function NTPSyncCheck() {
  const [reference, setReference] = useState("pool.ntp.org");
  const [target,    setTarget]    = useState("");
  const [threshold, setThreshold] = useState("500");
  const [running,   setRunning]   = useState(false);
  const [result,    setResult]    = useState<NTPCompareResult | null>(null);
  const [error,     setError]     = useState("");

  const run = async () => {
    if (running || !target.trim()) return;
    setRunning(true); setResult(null); setError("");
    try {
      const params = new URLSearchParams({
        reference, target: target.trim(),
        threshold_ms: String(parseFloat(threshold) || 500),
        samples: "3",
      });
      const res = await fetch(`${BASE}/tools/ntp/compare?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setError(err.detail ?? res.statusText); return;
      }
      setResult(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Controls */}
      <div className="shrink-0 border-b border-border bg-surface px-4 py-3 flex flex-wrap items-center gap-3">
        <ShieldCheck className="w-4 h-4 text-accent shrink-0" />
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-muted">Reference NTP Server</label>
          <input
            type="text" value={reference} onChange={e => setReference(e.target.value)}
            placeholder="pool.ntp.org"
            className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-44"
          />
        </div>
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-muted">Target Device (IP / hostname)</label>
          <input
            type="text" value={target} onChange={e => setTarget(e.target.value)}
            onKeyDown={e => e.key === "Enter" && run()}
            placeholder="192.168.1.100"
            className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-44"
          />
        </div>
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-muted">Max skew (ms)</label>
          <input
            type="number" value={threshold} onChange={e => setThreshold(e.target.value)}
            min={1} placeholder="500"
            className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground w-20 focus:outline-none focus:border-accent"
          />
        </div>
        <button
          onClick={run} disabled={running || !target.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-success-emphasis hover:bg-success-emphasis-hover text-white disabled:opacity-50 transition-colors mt-4"
        >
          {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
          {running ? "Checking…" : "Check Sync"}
        </button>
      </div>

      {error && (
        <div className="shrink-0 px-4 py-2 bg-danger-emphasis/20 border-b border-danger text-danger text-xs">{error}</div>
      )}

      <div className="flex-1 overflow-auto p-4 space-y-4">
        {!result && !running && !error && (
          <div className="flex flex-col items-center justify-center h-full text-muted-dim text-xs gap-2">
            <ShieldCheck className="w-8 h-8 opacity-20" />
            <span>Enter a reference NTP server and target device, then click Check Sync.</span>
            <span className="text-[10px] text-muted">The target must respond to NTP queries (UDP 123). Most NTP servers and many ICS devices do.</span>
          </div>
        )}

        {result && (
          <>
            {/* Verdict banner */}
            <div className={`flex items-center gap-3 p-3 rounded border ${
              result.status === "excellent" || result.status === "good"
                ? "bg-success/10 border-success/30"
                : result.status === "marginal"
                ? "bg-warning/10 border-warning/30"
                : "bg-danger/10 border-danger/30"
            }`}>
              <span className={`text-lg font-bold ${syncStatusColor(result.status)}`}>
                {syncStatusLabel(result.status)}
              </span>
              {result.skew_ms !== null && (
                <span className="text-xs text-muted ml-auto font-mono">
                  skew: <span className={`font-semibold ${Math.abs(result.skew_ms) < result.threshold_ms ? "text-success" : "text-danger"}`}>
                    {result.skew_ms > 0 ? "+" : ""}{result.skew_ms} ms
                  </span>
                  {" "}/ threshold: ±{result.threshold_ms} ms
                </span>
              )}
            </div>

            {/* Host cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <HostCard result={result.reference} label="Reference Server" error={result.ref_error} />
              <HostCard result={result.target}    label="Target Device"   error={result.target_error} />
            </div>

            {/* Explanation */}
            <div className="bg-surface border border-border rounded p-3 text-[11px] text-muted space-y-1">
              <div className="font-semibold text-foreground text-xs mb-1">How to read this</div>
              <div>• <span className="text-foreground">Skew</span> = target clock − reference clock. Positive means target is ahead.</div>
              <div>• <span className="text-foreground">Threshold ±{result.threshold_ms} ms</span>: your acceptable sync window.</div>
              <div>• If the target is <span className="text-danger">unreachable</span>, it does not respond to NTP queries on UDP 123. It may be an NTP client only, or a firewall is blocking the port.</div>
              <div>• High <span className="text-foreground">delay</span> on the target reduces accuracy — offset error ≈ ±(delay/2).</div>
              <div>• ICS recommendation: keep skew under <span className="text-success">100 ms</span> for reliable event correlation.</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

type TimeTab = "ntp" | "ptp" | "sync";

function TimeProtocolsTab() {
  const [tab, setTab] = useState<TimeTab>("ntp");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="shrink-0 flex border-b border-border bg-background/50 px-3 pt-1 gap-1">
        <button
          onClick={() => setTab("ntp")}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium rounded-t transition-colors ${
            tab === "ntp"
              ? "bg-surface text-accent border border-b-surface border-border"
              : "text-muted hover:text-foreground"
          }`}
        >
          <Clock className="w-3 h-3" /> NTP Query
        </button>
        <button
          onClick={() => setTab("ptp")}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium rounded-t transition-colors ${
            tab === "ptp"
              ? "bg-surface text-accent border border-b-surface border-border"
              : "text-muted hover:text-foreground"
          }`}
        >
          <Radio className="w-3 h-3" /> PTP Probe
        </button>
        <button
          onClick={() => setTab("sync")}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium rounded-t transition-colors ${
            tab === "sync"
              ? "bg-surface text-accent border border-b-surface border-border"
              : "text-muted hover:text-foreground"
          }`}
        >
          <ShieldCheck className="w-3 h-3" /> Sync Check
        </button>
      </div>
      <div className="flex-1 overflow-hidden">
        {tab === "ntp"  && <NTPTool />}
        {tab === "ptp"  && <PTPTool />}
        {tab === "sync" && <NTPSyncCheck />}
      </div>
    </div>
  );
}
