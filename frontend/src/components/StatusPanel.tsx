/**
 * StatusPanel
 *
 * Shows a live health dashboard for every backend subsystem plus the
 * running software version. Auto-refreshes every 15 seconds; the user
 * can also force a refresh at any time.
 *
 * Components probed:
 *   backend_api        — FastAPI process itself (always ok if this renders)
 *   packet_capture     — Scapy / pyshark interface enumeration
 *   llm_backend        — active LLM (Ollama or LM Studio) reachability
 *   ollama             — Ollama service on :11434
 *   lmstudio           — LM Studio service on :1234
 *   rag_knowledge_base — ChromaDB vector store
 *   modbus_simulator   — Modbus simulator session manager
 *   modbus_client      — Modbus client session manager
 *   websocket_hub      — WebSocket subscriber counts
 */

import { useEffect, useState, useCallback } from "react";
import {
  CheckCircle,
  XCircle,
  RefreshCw,
  Clock,
  Loader,
  Server,
  Cpu,
  Brain,
  Database,
  Radio,
  Activity,
  Wifi,
  Info,
} from "lucide-react";
import { fetchSystemStatus, SystemStatus, ComponentStatus } from "../lib/api";

// ---------------------------------------------------------------------------
// Component metadata — display name + icon for each probe key
// ---------------------------------------------------------------------------

type IconComponent = React.ComponentType<{ className?: string }>;

interface ComponentMeta {
  label: string;
  description: string;
  Icon: IconComponent;
}

const META: Record<string, ComponentMeta> = {
  backend_api:        { label: "Backend API",         description: "FastAPI REST server",                    Icon: Server   },
  packet_capture:     { label: "Packet Capture",      description: "Scapy / pyshark interface layer",        Icon: Activity },
  llm_backend:        { label: "LLM Backend",         description: "Active inference engine (Ollama / LM Studio)", Icon: Brain },
  ollama:             { label: "Ollama Service",       description: "Ollama daemon on localhost:11434",       Icon: Cpu      },
  lmstudio:           { label: "LM Studio Service",   description: "LM Studio server on localhost:1234",     Icon: Cpu      },
  rag_knowledge_base: { label: "Knowledge Base (RAG)", description: "ChromaDB vector store + BM25 index",   Icon: Database },
  modbus_simulator:   { label: "Modbus Simulator",    description: "Modbus TCP device simulator",            Icon: Radio    },
  modbus_client:      { label: "Modbus Client",       description: "Modbus TCP polling client",              Icon: Radio    },
  websocket_hub:      { label: "WebSocket Hub",       description: "Real-time packet + insight push relay",  Icon: Wifi     },
};

// Display order
const COMPONENT_ORDER = [
  "backend_api",
  "packet_capture",
  "llm_backend",
  "ollama",
  "lmstudio",
  "rag_knowledge_base",
  "modbus_simulator",
  "modbus_client",
  "websocket_hub",
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="flex items-center gap-1 text-success text-xs font-semibold">
      <CheckCircle className="w-3.5 h-3.5" />
      OK
    </span>
  ) : (
    <span className="flex items-center gap-1 text-danger text-xs font-semibold">
      <XCircle className="w-3.5 h-3.5" />
      DOWN
    </span>
  );
}

interface ComponentRowProps {
  id: string;
  status: ComponentStatus;
}

function ComponentRow({ id, status }: ComponentRowProps) {
  const meta = META[id] ?? {
    label: id,
    description: "",
    Icon: Info,
  };
  const { Icon } = meta;

  return (
    <div
      className={`flex items-center gap-4 px-4 py-3 border-b border-border-subtle last:border-0 transition-colors ${
        status.ok ? "hover:bg-surface" : "bg-down-bg hover:bg-down-bg"
      }`}
    >
      {/* Icon */}
      <div
        className={`flex items-center justify-center w-8 h-8 rounded-md shrink-0 ${
          status.ok ? "bg-ok-bg text-success" : "bg-down-bg text-danger"
        }`}
      >
        <Icon className="w-4 h-4" />
      </div>

      {/* Name + description */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-foreground text-sm font-medium">{meta.label}</span>
          <StatusBadge ok={status.ok} />
        </div>
        {meta.description && (
          <div className="text-muted text-xs mt-0.5">{meta.description}</div>
        )}
        {status.detail && (
          <div
            className={`text-xs mt-0.5 font-mono truncate ${
              status.ok ? "text-accent" : "text-danger"
            }`}
            title={status.detail}
          >
            {status.detail}
          </div>
        )}
      </div>

      {/* Latency */}
      {status.latency_ms !== null && (
        <div className="flex items-center gap-1 text-muted text-xs shrink-0">
          <Clock className="w-3 h-3" />
          {status.latency_ms < 1 ? "<1" : status.latency_ms}ms
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 15_000;

export function StatusPanel() {
  const [data, setData]       = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchSystemStatus();
      setData(result);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + polling
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  // ---------------------------------------------------------------------------
  // Derived stats
  // ---------------------------------------------------------------------------

  const components = data?.components ?? {};
  const orderedKeys = [
    ...COMPONENT_ORDER.filter((k) => k in components),
    ...Object.keys(components).filter((k) => !COMPONENT_ORDER.includes(k)),
  ];
  const totalOk   = orderedKeys.filter((k) => components[k]?.ok).length;
  const totalDown = orderedKeys.length - totalOk;
  const allOk     = totalDown === 0 && orderedKeys.length > 0;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-full overflow-y-auto bg-background p-4">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-foreground text-base font-semibold">System Status</h2>
          {lastRefresh && (
            <p className="text-muted text-xs mt-0.5">
              Last updated: {lastRefresh.toLocaleTimeString()}
            </p>
          )}
        </div>

        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-border text-muted text-xs hover:text-foreground hover:border-accent transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* ── Version banner ──────────────────────────────────────────────────── */}
      {data && (
        <div className="flex items-center gap-3 px-4 py-3 mb-4 rounded-lg border border-border bg-surface">
          <Server className="w-4 h-4 text-accent shrink-0" />
          <div className="flex-1">
            <span className="text-foreground text-sm font-medium">NetScope</span>
            <span className="ml-3 text-accent font-mono text-sm">v{data.version}</span>
          </div>
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
              allOk
                ? "bg-ok-bg text-success"
                : "bg-down-bg text-danger"
            }`}
          >
            {loading ? (
              <Loader className="w-3 h-3 animate-spin" />
            ) : allOk ? (
              <CheckCircle className="w-3 h-3" />
            ) : (
              <XCircle className="w-3 h-3" />
            )}
            {loading ? "Checking…" : allOk ? "All systems operational" : `${totalDown} system(s) down`}
          </div>
        </div>
      )}

      {/* ── Summary pills ───────────────────────────────────────────────────── */}
      {data && !loading && (
        <div className="flex gap-3 mb-4">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-ok-bg text-success text-xs font-medium">
            <CheckCircle className="w-3.5 h-3.5" />
            {totalOk} operational
          </div>
          {totalDown > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-down-bg text-danger text-xs font-medium">
              <XCircle className="w-3.5 h-3.5" />
              {totalDown} down
            </div>
          )}
        </div>
      )}

      {/* ── Error state ─────────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-start gap-3 px-4 py-3 mb-4 rounded-lg border border-danger bg-down-bg text-danger text-sm">
          <XCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">Could not reach backend</div>
            <div className="text-xs mt-0.5 text-danger font-mono">{error}</div>
          </div>
        </div>
      )}

      {/* ── Loading skeleton ─────────────────────────────────────────────────── */}
      {loading && !data && (
        <div className="rounded-lg border border-border-subtle bg-surface overflow-hidden">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-3 border-b border-border-subtle last:border-0">
              <div className="w-8 h-8 rounded-md bg-border-subtle animate-pulse shrink-0" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 w-32 bg-border-subtle rounded animate-pulse" />
                <div className="h-2.5 w-48 bg-border-subtle rounded animate-pulse" />
              </div>
              <div className="h-2.5 w-12 bg-border-subtle rounded animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {/* ── Component rows ───────────────────────────────────────────────────── */}
      {data && orderedKeys.length > 0 && (
        <div className="rounded-lg border border-border-subtle bg-surface overflow-hidden">
          {orderedKeys.map((key) => (
            <ComponentRow key={key} id={key} status={components[key]} />
          ))}
        </div>
      )}
    </div>
  );
}
