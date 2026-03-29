import "./trend-chart.css";
import { useState, useEffect, useRef, useCallback } from "react";
import {
  createModbusLiveWebSocket,
  type ModbusWsData,
  type RegisterEntry,
} from "../lib/api";

// ── Constants ────────────────────────────────────────────────────────────────

const MAX_SERIES = 8;
const MAX_BUFFER = 1800; // 30 min at 1 s poll

// SVG layout
const VW = 600, VH = 160;
const ML = 52, MR = 8, MT = 8, MB = 20;
const CW = VW - ML - MR;
const CH = VH - MT - MB;

// ── Types ────────────────────────────────────────────────────────────────────

interface TrendPoint { ts: number; v: number; }
interface AvailAddr  { addr: number; name: string; }

interface Props {
  sessionId: string;
  source: "simulator" | "client";
}

// ── Component ────────────────────────────────────────────────────────────────

export function TrendChart({ sessionId, source }: Props) {
  const bufferRef  = useRef<Map<number, TrendPoint[]>>(new Map());
  const svgRef     = useRef<SVGSVGElement>(null);

  const [availAddrs,  setAvailAddrs]  = useState<AvailAddr[]>([]);
  const [selected,    setSelected]    = useState<number[]>([]);
  const [windowSecs,  setWindowSecs]  = useState<30 | 300 | 1800>(30);
  const [tick,        setTick]        = useState(0);
  const [hovered,     setHovered]     = useState<{
    x: number; y: number;
    items: { addr: number; name: string; v: number }[];
    tsStr: string;
  } | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // ── WebSocket ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!sessionId) return;
    bufferRef.current.clear();
    setAvailAddrs([]);
    setSelected([]);

    const dispose = createModbusLiveWebSocket(sessionId, (msg: ModbusWsData) => {
      if (msg.type !== "data" || !msg.registers) return;
      const now = Date.now() / 1000;
      const ts  = now;

      setAvailAddrs(prev => {
        const seen = new Set(prev.map(a => a.addr));
        const next = (msg.registers as RegisterEntry[])
          .filter(r => !seen.has(r.address))
          .map(r => ({ addr: r.address, name: r.name || String(r.address) }));
        return next.length ? [...prev, ...next] : prev;
      });

      for (const r of msg.registers as RegisterEntry[]) {
        const v = typeof r.value === "number" ? r.value : parseFloat(String(r.value ?? r.raw));
        if (!isFinite(v)) continue;
        const buf = bufferRef.current.get(r.address) ?? [];
        buf.push({ ts, v });
        if (buf.length > MAX_BUFFER) buf.shift();
        bufferRef.current.set(r.address, buf);
      }
      setTick(n => n + 1);
    }, 1.0);

    return dispose;
  }, [sessionId, source]);

  // ── Derived chart values ───────────────────────────────────────────────────

  const now  = Date.now() / 1000;
  const xMin = now - windowSecs;
  const xMax = now;

  const seriesData = selected.map(addr => ({
    addr,
    name: availAddrs.find(a => a.addr === addr)?.name ?? String(addr),
    pts:  (bufferRef.current.get(addr) ?? []).filter(p => p.ts >= xMin),
  }));

  const allVals = seriesData.flatMap(s => s.pts.map(p => p.v));
  const yMinRaw = allVals.length ? Math.min(...allVals) : 0;
  const yMaxRaw = allVals.length ? Math.max(...allVals) : 1;
  const pad     = (yMaxRaw - yMinRaw) * 0.1 || Math.abs(yMaxRaw) * 0.1 || 1;
  const yMin    = yMinRaw - pad;
  const yMax    = yMaxRaw + pad;

  const toX = (ts: number) => ML + ((ts - xMin) / (xMax - xMin)) * CW;
  const toY = (v:  number) => MT + (1 - (v - yMin) / (yMax - yMin)) * CH;
  const ptsStr = (data: TrendPoint[]) =>
    data.map(p => `${toX(p.ts).toFixed(1)},${toY(p.v).toFixed(1)}`).join(" ");

  // ── Hover handler ──────────────────────────────────────────────────────────

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || seriesData.every(s => s.pts.length === 0)) { setHovered(null); return; }
    const pxFrac = (e.clientX - rect.left) / rect.width;
    const svgX   = pxFrac * VW;
    if (svgX < ML || svgX > VW - MR) { setHovered(null); return; }
    const ts    = xMin + ((svgX - ML) / CW) * (xMax - xMin);
    const items = seriesData
      .map(s => {
        if (!s.pts.length) return null;
        const pt = s.pts.reduce((b, p) => Math.abs(p.ts - ts) < Math.abs(b.ts - ts) ? p : b);
        return { addr: s.addr, name: s.name, v: pt.v };
      })
      .filter(Boolean) as { addr: number; name: string; v: number }[];
    const tsStr = new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
    setHovered({ x: e.clientX - rect.left, y: e.clientY - rect.top, items, tsStr });
  }, [seriesData, xMin, xMax]);

  // suppress lint warning — tick drives re-render intentionally
  void tick;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full overflow-hidden bg-background">

      {/* Controls row */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-border bg-surface flex-wrap">

        {/* Window selector */}
        <div className="flex rounded border border-border overflow-hidden">
          {([30, 300, 1800] as const).map(w => (
            <button key={w} onClick={() => setWindowSecs(w)}
              className={`px-2 py-0.5 text-[10px] font-mono transition-colors ${
                windowSecs === w
                  ? "bg-accent-emphasis text-white"
                  : "bg-background text-muted hover:bg-surface"
              }`}>
              {w === 30 ? "30s" : w === 300 ? "5m" : "30m"}
            </button>
          ))}
        </div>

        {/* Series chips */}
        {selected.map((addr, i) => (
          <span key={addr}
            className={`chart-series-${i} chart-chip-${i} flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono`}>
            {availAddrs.find(a => a.addr === addr)?.name ?? addr}
            <button
              onClick={() => setSelected(s => s.filter(a => a !== addr))}
              className="opacity-60 hover:opacity-100 ml-0.5">×</button>
          </span>
        ))}

        {/* + Add dropdown */}
        {selected.length < MAX_SERIES && (
          <div className="relative">
            <button
              onClick={() => setShowAdd(s => !s)}
              className="h-5 px-2 rounded text-[10px] border border-border text-muted hover:text-foreground hover:border-accent">
              + Add
            </button>
            {showAdd && (
              <div className="absolute left-0 top-6 z-10 bg-surface border border-border rounded shadow-lg min-w-[8rem] max-h-48 overflow-auto">
                {availAddrs.filter(a => !selected.includes(a.addr)).length === 0
                  ? <p className="text-[10px] text-muted px-3 py-2">No data yet</p>
                  : availAddrs.filter(a => !selected.includes(a.addr)).map(a => (
                      <button key={a.addr}
                        onClick={() => { setSelected(s => [...s, a.addr]); setShowAdd(false); }}
                        className="w-full text-left px-3 py-1.5 text-[10px] font-mono text-foreground hover:bg-background">
                        {a.name} <span className="text-muted">({a.addr})</span>
                      </button>
                    ))
                }
              </div>
            )}
          </div>
        )}

        {selected.length === 0 && (
          <span className="text-[10px] text-muted">
            {availAddrs.length > 0 ? "Click + Add to plot a register" : "Waiting for register data…"}
          </span>
        )}
      </div>

      {/* SVG chart */}
      <div className="flex-1 relative overflow-hidden" onMouseLeave={() => setHovered(null)}>
        <svg ref={svgRef} className="w-full h-full"
          viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="none"
          onMouseMove={onMouseMove}>

          {/* Y grid + labels */}
          {Array.from({ length: 5 }, (_, i) => {
            const v  = yMin + (i / 4) * (yMax - yMin);
            const cy = toY(v);
            return (
              <g key={i}>
                <line x1={ML} y1={cy} x2={VW - MR} y2={cy}
                  className="stroke-border" strokeWidth="0.5" />
                <text x={ML - 4} y={cy + 3} textAnchor="end"
                  fontSize="8" className="fill-muted font-mono">
                  {Math.abs(v) >= 1000 ? v.toFixed(0) : v.toPrecision(3)}
                </text>
              </g>
            );
          })}

          {/* X axis labels */}
          {Array.from({ length: 5 }, (_, i) => {
            const ts = xMin + (i / 4) * (xMax - xMin);
            return (
              <text key={i} x={toX(ts)} y={VH - 4} textAnchor="middle"
                fontSize="7" className="fill-muted font-mono">
                {new Date(ts * 1000).toLocaleTimeString([], { hour12: false, minute: "2-digit", second: "2-digit" })}
              </text>
            );
          })}

          {/* Series polylines */}
          {seriesData.map((s, i) => s.pts.length < 2 ? null : (
            <polyline key={s.addr}
              className={`chart-series-${i}`}
              points={ptsStr(s.pts)}
              fill="none" strokeWidth="1.5"
              strokeLinejoin="round" strokeLinecap="round" />
          ))}

          {/* Hover crosshair */}
          {hovered && (() => {
            const svgX = (hovered.x / (svgRef.current?.clientWidth ?? 1)) * VW;
            return (
              <line x1={svgX} y1={MT} x2={svgX} y2={VH - MB}
                className="stroke-accent" strokeWidth="0.5" strokeDasharray="3 2" />
            );
          })()}
        </svg>

        {/* Tooltip */}
        {hovered && hovered.items.length > 0 && (
          <div
            className="absolute pointer-events-none z-10 bg-surface border border-border rounded shadow-lg px-2 py-1.5"
            style={{
              left: Math.min(hovered.x + 12, (svgRef.current?.clientWidth ?? 200) - 130),
              top:  Math.max(hovered.y - 10, 4),
            }}>
            <p className="text-[9px] text-muted mb-1 font-mono">{hovered.tsStr}</p>
            {hovered.items.map((it, i) => (
              <p key={it.addr} className={`chart-series-${i} text-[10px] font-mono flex gap-1.5`}>
                <span>{it.name}:</span>
                <span className="font-semibold">{it.v.toPrecision(5)}</span>
              </p>
            ))}
          </div>
        )}

        {/* Empty state */}
        {selected.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <p className="text-[11px] text-muted">
              {availAddrs.length > 0
                ? `${availAddrs.length} register${availAddrs.length > 1 ? "s" : ""} available — click + Add above`
                : "No live data — select a session and ensure polling is active"}
            </p>
          </div>
        )}
      </div>

      {/* Legend row */}
      {selected.length > 0 && (
        <div className="shrink-0 flex items-center gap-3 px-3 py-1 border-t border-border bg-surface flex-wrap">
          {seriesData.map((s, i) => {
            const latest = s.pts[s.pts.length - 1];
            return (
              <span key={s.addr} className={`chart-series-${i} flex items-center gap-1.5 text-[10px] font-mono`}>
                <span className={`chart-series-${i} w-4 h-0.5 inline-block rounded`} />
                {s.name}
                {latest != null && (
                  <span className="text-foreground ml-0.5">= {latest.v.toPrecision(5)}</span>
                )}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
