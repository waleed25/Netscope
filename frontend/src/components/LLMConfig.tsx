import { useEffect, useState, useRef } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { setLLMBackend, fetchLLMStatus, pullModel } from "../lib/api";
import { api } from "../lib/api";
import { Cpu, Wifi, WifiOff, ChevronDown, MemoryStick, Download } from "lucide-react";

/** Format bytes → "2.4 GB", "512 MB", etc. */
function fmtBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return (bytes / 1_073_741_824).toFixed(1) + " GB";
  if (bytes >= 1_048_576)     return (bytes / 1_048_576).toFixed(0) + " MB";
  return (bytes / 1024).toFixed(0) + " KB";
}

/** Compact VRAM pill shown in the top bar. */
function VramBadge({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const color =
    pct > 90 ? "rgb(var(--color-danger))" :
    pct > 70 ? "rgb(var(--color-warning))" :
               "rgb(var(--color-success))";

  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1 border border-border rounded text-[10px] font-mono text-muted hover:border-muted-dim transition-colors cursor-default"
      title={`VRAM: ${fmtBytes(used)} used of ${fmtBytes(total)}`}
    >
      <MemoryStick className="w-3 h-3" style={{ color }} />
      <span style={{ color }}>{fmtBytes(used)}</span>
      {/* mini bar */}
      <div className="w-12 h-1.5 bg-border-subtle rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

export function LLMConfig() {
  const { llmStatus, llmBackend, setLLMBackend: setBackendStore, setLLMStatus } = useStore(
    useShallow((s) => ({ llmStatus: s.llmStatus, llmBackend: s.llmBackend, setLLMBackend: s.setLLMBackend, setLLMStatus: s.setLLMStatus }))
  );
  const [models, setModels] = useState<string[]>([]);
  const [activeModel, setActiveModel] = useState("");
  const [open, setOpen] = useState(false);
  const [speed, setSpeed] = useState<string | null>(null);
  const [pullOpen, setPullOpen] = useState(false);
  const [pullName, setPullName] = useState("");
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState("");
  const pullInputRef = useRef<HTMLInputElement>(null);

  const isReachable = llmStatus?.reachable ?? false;

  const refreshModels = () => {
    api.get("/llm/models").then((r) => {
      setModels(r.data.models ?? []);
      setActiveModel(r.data.active ?? "");
    }).catch(() => {});
  };

  // Load models on mount and when backend changes
  useEffect(() => { refreshModels(); }, [llmBackend]);

  // Measure speed: time a small completion
  useEffect(() => {
    if (!isReachable) return;
    setSpeed(null);
    const t0 = Date.now();
    api.post("/chat", { message: "1+1=", stream: false })
      .then(() => setSpeed(`~${((Date.now() - t0) / 1000).toFixed(1)}s`))
      .catch(() => setSpeed("slow"));
  }, [activeModel, isReachable]);

  const handlePull = async () => {
    const name = pullName.trim();
    if (!name || pulling) return;
    setPulling(true);
    setPullStatus("Starting download...");
    try {
      await pullModel(name, (p) => {
        if (p.completed && p.total) {
          const pct = Math.round((p.completed / p.total) * 100);
          setPullStatus(`${p.status} ${pct}%`);
        } else {
          setPullStatus(p.status || "downloading...");
        }
      });
      setPullStatus("Done!");
      refreshModels();
      setTimeout(() => { setPullOpen(false); setPullStatus(""); setPullName(""); }, 1500);
    } catch (e: unknown) {
      setPullStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPulling(false);
    }
  };

  const handleToggleBackend = async () => {
    const next = llmBackend === "ollama" ? "lmstudio" : "ollama";
    await setLLMBackend(next).catch(() => {});
    setBackendStore(next);
    fetchLLMStatus().then(setLLMStatus).catch(() => {});
  };

  const handleModelSelect = async (model: string) => {
    await api.post("/llm/model", { model }).catch(() => {});
    setActiveModel(model);
    setOpen(false);
  };

  const shortModel = activeModel.split(":")[0] || "—";

  const vramUsed  = llmStatus?.vram_used_bytes  ?? 0;
  const vramTotal = llmStatus?.model_size_bytes ?? 0;
  const showVram  = llmStatus?.backend === "ollama" && vramUsed > 0;

  return (
    <div className="relative flex items-center gap-2">
      {/* Reachability + speed */}
      <div className={`flex items-center gap-1 text-xs ${isReachable ? "text-success" : "text-danger"}`}>
        {isReachable ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
        {speed && isReachable && (
          <span className={`text-[10px] ${parseFloat(speed) > 5 ? "text-warning" : "text-success"}`}>
            {speed}
          </span>
        )}
      </div>

      {/* VRAM badge (Ollama only) */}
      {showVram && <VramBadge used={vramUsed} total={vramTotal} />}

      {/* Backend toggle */}
      <button
        onClick={handleToggleBackend}
        className="px-2 py-1 border border-border rounded text-xs text-muted hover:text-foreground hover:border-muted-dim transition-colors font-mono"
        title="Click to switch backend"
      >
        {llmBackend === "ollama" ? "Ollama" : "LM Studio"}
      </button>

      {/* Model selector */}
      <div className="relative">
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1 px-2 py-1 border border-border rounded text-xs text-foreground hover:border-muted-dim transition-colors font-mono"
          aria-label="Select LLM model"
          aria-expanded={open}
        >
          <Cpu className="w-3 h-3 text-purple" />
          <span>{shortModel}</span>
          <ChevronDown className="w-3 h-3 text-muted" />
        </button>

        {open && models.length > 0 && (
          <div className="absolute right-0 top-full mt-1 z-50 bg-surface border border-border rounded-lg shadow-xl min-w-[200px] py-1 overflow-hidden">
            <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider border-b border-border">
              Available Models
            </div>
            {models.map((m) => (
              <button
                key={m}
                onClick={() => handleModelSelect(m)}
                className={`w-full text-left px-3 py-2 text-xs font-mono hover:bg-surface-hover transition-colors ${
                  m === activeModel ? "text-accent" : "text-foreground"
                }`}
              >
                <div className="flex items-center justify-between gap-4">
                  <span>{m}</span>
                  {m === activeModel && (
                    <span className="text-[10px] text-success">active</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Pull model (Ollama only) */}
      {llmBackend === "ollama" && (
        <div className="relative">
          <button
            onClick={() => { setPullOpen(!pullOpen); setTimeout(() => pullInputRef.current?.focus(), 50); }}
            className="p-1 border border-border rounded text-muted hover:text-foreground hover:border-muted-dim transition-colors"
            title="Pull / download a model"
            aria-label="Pull model"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          {pullOpen && (
            <div className="absolute right-0 top-full mt-1 z-50 bg-surface border border-border rounded-lg shadow-xl p-3 w-64">
              <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Pull Model</div>
              <div className="flex gap-1.5">
                <input
                  ref={pullInputRef}
                  value={pullName}
                  onChange={(e) => setPullName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handlePull()}
                  placeholder="e.g. qwen3:4b"
                  disabled={pulling}
                  className="flex-1 px-2 py-1 bg-background border border-border rounded text-xs font-mono text-foreground placeholder:text-muted-dim focus:outline-none focus:border-accent"
                />
                <button
                  onClick={handlePull}
                  disabled={pulling || !pullName.trim()}
                  className="px-2 py-1 bg-accent text-background rounded text-xs font-medium hover:bg-accent/80 disabled:opacity-40 transition-colors"
                >
                  {pulling ? "..." : "Pull"}
                </button>
              </div>
              {pullStatus && (
                <div className="mt-2 text-[10px] text-muted font-mono truncate">{pullStatus}</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Close dropdowns on outside click */}
      {(open || pullOpen) && (
        <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setPullOpen(false); }} />
      )}
    </div>
  );
}
