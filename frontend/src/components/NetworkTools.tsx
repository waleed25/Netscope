import { useState, useRef, useCallback, useEffect } from "react";
import { Brain, Play, X, Copy, Check, Wifi, Search, Download, Crosshair, ChevronDown, Loader2, Monitor } from "lucide-react";
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

// ── Top-level NetworkTools with tab switcher ──────────────────────────────────

type Tab = "scanner" | "tools";

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
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {tab === "scanner" ? <SubnetScanner /> : <TerminalTools />}
      </div>
    </div>
  );
}
