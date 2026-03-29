import { useEffect, useRef, useState } from "react";
import { fetchContextUsage } from "../lib/api";
import type { ContextUsage } from "../lib/api";

// ── SVG donut helpers ─────────────────────────────────────────────────────────

const CX = 18;
const CY = 18;
const R = 14;       // outer radius
const INNER = 9;    // inner radius (hole)
const CIRC = 2 * Math.PI * R;

function polarToXY(angle: number, r: number): [number, number] {
  // angle 0 = top, clockwise
  const rad = (angle - 90) * (Math.PI / 180);
  return [CX + r * Math.cos(rad), CY + r * Math.sin(rad)];
}

function arcPath(startAngle: number, endAngle: number, outerR: number, innerR: number): string {
  if (Math.abs(endAngle - startAngle) >= 359.9) {
    // Full circle — two half-arcs to avoid degenerate path
    const [ox1, oy1] = polarToXY(startAngle, outerR);
    const [ox2, oy2] = polarToXY(startAngle + 180, outerR);
    const [ix1, iy1] = polarToXY(startAngle, innerR);
    const [ix2, iy2] = polarToXY(startAngle + 180, innerR);
    return [
      `M ${ox1} ${oy1}`,
      `A ${outerR} ${outerR} 0 0 1 ${ox2} ${oy2}`,
      `A ${outerR} ${outerR} 0 0 1 ${ox1} ${oy1}`,
      `M ${ix1} ${iy1}`,
      `A ${innerR} ${innerR} 0 0 0 ${ix2} ${iy2}`,
      `A ${innerR} ${innerR} 0 0 0 ${ix1} ${iy1}`,
      "Z",
    ].join(" ");
  }

  const large = (endAngle - startAngle) > 180 ? 1 : 0;
  const [ox1, oy1] = polarToXY(startAngle, outerR);
  const [ox2, oy2] = polarToXY(endAngle, outerR);
  const [ix1, iy1] = polarToXY(startAngle, innerR);
  const [ix2, iy2] = polarToXY(endAngle, innerR);

  return [
    `M ${ox1} ${oy1}`,
    `A ${outerR} ${outerR} 0 ${large} 1 ${ox2} ${oy2}`,
    `L ${ix2} ${iy2}`,
    `A ${innerR} ${innerR} 0 ${large} 0 ${ix1} ${iy1}`,
    "Z",
  ].join(" ");
}

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(n);
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

interface TooltipProps {
  data: ContextUsage;
}

function Tooltip({ data }: TooltipProps) {
  const { context_length, prompt_tokens, completion_tokens } = data;
  const used = prompt_tokens + completion_tokens;
  const free = Math.max(0, context_length - used);
  const pct = context_length > 0 ? ((used / context_length) * 100).toFixed(1) : "0";

  return (
    <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 z-50 w-52
                    bg-surface border border-border rounded-lg shadow-xl p-3 text-xs">
      <div className="font-semibold text-foreground mb-2">Context Window</div>

      <div className="space-y-1.5">
        {/* Prompt */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-sm bg-accent shrink-0" />
            <span className="text-muted">Prompt</span>
          </div>
          <span className="text-accent font-mono">{fmt(prompt_tokens)}</span>
        </div>

        {/* Completion */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-sm bg-success shrink-0" />
            <span className="text-muted">Completion</span>
          </div>
          <span className="text-success font-mono">{fmt(completion_tokens)}</span>
        </div>

        {/* Free */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-sm bg-border-subtle border border-border shrink-0" />
            <span className="text-muted">Available</span>
          </div>
          <span className="text-muted-dim font-mono">{fmt(free)}</span>
        </div>

        {/* Divider + totals */}
        <div className="border-t border-border pt-1.5 mt-1 flex items-center justify-between">
          <span className="text-muted">Used</span>
          <span className="text-foreground font-mono">
            {fmt(used)} / {fmt(context_length)} ({pct}%)
          </span>
        </div>
      </div>

      {/* Mini progress bar */}
      <div className="mt-2 h-1 bg-border-subtle rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-accent to-success rounded-full transition-all"
          style={{ width: `${Math.min(100, parseFloat(pct))}%` }}
        />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ContextPie() {
  const [data, setData] = useState<ContextUsage | null>(null);
  const [hovered, setHovered] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const poll = () => {
      if (!document.hidden) {
        fetchContextUsage().then(setData).catch(() => {});
      }
    };
    poll();
    intervalRef.current = setInterval(poll, 10_000);

    const onVisChange = () => {
      if (!document.hidden) poll();
    };
    document.addEventListener("visibilitychange", onVisChange);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      document.removeEventListener("visibilitychange", onVisChange);
    };
  }, []);

  if (!data) return null;

  const { context_length, prompt_tokens, completion_tokens } = data;
  const used = prompt_tokens + completion_tokens;
  const free = Math.max(0, context_length - used);
  const total = context_length || 1;

  // Angles (degrees, clockwise from top)
  const promptDeg = (prompt_tokens / total) * 360;
  const completionDeg = (completion_tokens / total) * 360;
  const freeDeg = (free / total) * 360;

  const seg1End = promptDeg;
  const seg2End = seg1End + completionDeg;
  const seg3End = seg2End + freeDeg;

  const usedPct = ((used / total) * 100).toFixed(0);

  return (
    <div
      className="relative flex items-center gap-1.5 cursor-default select-none"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Donut SVG */}
      <svg
        width={36}
        height={36}
        viewBox="0 0 36 36"
        className="shrink-0"
        style={{ filter: hovered ? "drop-shadow(0 0 4px rgb(var(--color-accent) / 0.27))" : undefined }}
      >
        {/* Background ring */}
        <circle
          cx={CX} cy={CY} r={R}
          fill="none"
          stroke="rgb(var(--color-border-subtle))"
          strokeWidth={R - INNER}
        />

        {/* Free slice (drawn first as base) */}
        {freeDeg > 0.5 && (
          <path d={arcPath(seg2End, seg3End, R, INNER)} fill="rgb(var(--color-border-subtle))" />
        )}

        {/* Completion slice */}
        {completionDeg > 0.5 && (
          <path d={arcPath(seg1End, seg2End, R, INNER)} fill="rgb(var(--color-success))" />
        )}

        {/* Prompt slice */}
        {promptDeg > 0.5 && (
          <path d={arcPath(0, seg1End, R, INNER)} fill="rgb(var(--color-accent))" />
        )}

        {/* Centre label — usage % */}
        <text
          x={CX}
          y={CY + 1}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="6"
          fontFamily="monospace"
          fill={used === 0 ? "rgb(var(--color-muted-dim))" : "rgb(var(--color-foreground))"}
        >
          {usedPct}%
        </text>
      </svg>

      {/* Tooltip */}
      {hovered && <Tooltip data={data} />}
    </div>
  );
}
