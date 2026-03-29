import { useEffect, useState, useCallback } from "react";
import {
  listCaptureFiles, deleteCaptureFile, loadCaptureFile, clearCapture,
  type SavedCaptureFile,
} from "../lib/api";
import { useStore } from "../store/useStore";
import { HardDrive, Trash2, FolderOpen, RefreshCw, X, Loader2, CheckCircle2 } from "lucide-react";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

export function CaptureManager() {
  const [files, setFiles] = useState<SavedCaptureFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionFile, setActionFile] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const isCapturing = useStore((s) => s.isCapturing);
  const setPackets = useStore((s) => s.setPackets);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const f = await listCaptureFiles();
      setFiles(f);
    } catch {
      setError("Failed to load capture files.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleLoad = async (name: string) => {
    if (isCapturing) { setError("Stop the live capture first."); return; }
    setActionFile(name);
    setError(""); setSuccess("");
    try {
      const r = await loadCaptureFile(name);
      setSuccess(`Loaded "${name}" — ${r.packet_count.toLocaleString()} packets.`);
      await refresh();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load file.");
    } finally {
      setActionFile(null);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete "${name}"?`)) return;
    setActionFile(name);
    setError(""); setSuccess("");
    try {
      await deleteCaptureFile(name);
      setSuccess(`Deleted "${name}".`);
      await refresh();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to delete file.");
    } finally {
      setActionFile(null);
    }
  };

  const handleClear = async () => {
    if (isCapturing) { setError("Stop the live capture first."); return; }
    if (!confirm("Clear all packets from memory? This does not delete files.")) return;
    setError(""); setSuccess("");
    try {
      await clearCapture();
      setPackets([]);
      setSuccess("Cleared — no packets in memory.");
      await refresh();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to clear.");
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-surface text-xs shrink-0">
        <div className="flex items-center gap-2 text-foreground">
          <HardDrive className="w-4 h-4 text-accent" />
          <span className="font-semibold">Capture Files</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleClear}
            disabled={isCapturing}
            className="flex items-center gap-1 px-2 py-1 bg-surface border border-border rounded text-muted hover:text-danger hover:border-danger disabled:opacity-40 transition-colors"
            title="Clear packets from memory"
          >
            <X className="w-3 h-3" /> Clear memory
          </button>
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1 px-2 py-1 bg-surface border border-border rounded text-muted hover:text-foreground disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      {/* Status messages */}
      {error && (
        <div className="px-3 py-2 text-xs text-danger bg-danger/10 border-b border-danger/20 shrink-0">
          {error}
        </div>
      )}
      {success && (
        <div className="px-3 py-2 text-xs text-success bg-success/10 border-b border-success/20 shrink-0 flex items-center gap-1.5">
          <CheckCircle2 className="w-3 h-3 shrink-0" /> {success}
        </div>
      )}

      {/* File list */}
      <div className="flex-1 overflow-auto">
        {files.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-muted">
            <HardDrive className="w-10 h-10 opacity-20" />
            <p className="text-sm">No capture files yet.</p>
            <p className="text-xs text-center">Start a live capture or import a PCAP file.</p>
          </div>
        )}

        {files.length > 0 && (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface border-b border-border text-muted">
              <tr>
                <th className="text-left px-3 py-1.5 font-medium">File</th>
                <th className="text-right px-3 py-1.5 font-medium">Size</th>
                <th className="text-left px-3 py-1.5 font-medium">Modified</th>
                <th className="px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {files.map((f) => {
                const busy = actionFile === f.name;
                return (
                  <tr
                    key={f.name}
                    className={`border-b border-border/50 ${f.is_active ? "bg-accent/5" : "hover:bg-surface"}`}
                  >
                    <td className="px-3 py-2 font-mono max-w-[280px]">
                      <div className="flex items-center gap-1.5">
                        {f.is_active && (
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-success shrink-0" title="Active capture" />
                        )}
                        <span className="truncate" title={f.name}>{f.name}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right text-muted tabular-nums whitespace-nowrap">
                      {formatBytes(f.size_bytes)}
                    </td>
                    <td className="px-3 py-2 text-muted whitespace-nowrap">
                      {formatDate(f.modified)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1.5">
                        {busy ? (
                          <Loader2 className="w-3.5 h-3.5 text-muted animate-spin" />
                        ) : (
                          <>
                            <button
                              onClick={() => handleLoad(f.name)}
                              disabled={isCapturing}
                              className="flex items-center gap-1 px-2 py-0.5 rounded bg-accent/10 hover:bg-accent/20 text-accent disabled:opacity-40 transition-colors"
                              title="Load this file as active capture"
                            >
                              <FolderOpen className="w-3 h-3" /> Load
                            </button>
                            <button
                              onClick={() => handleDelete(f.name)}
                              className="flex items-center gap-1 px-2 py-0.5 rounded hover:bg-danger/10 text-muted hover:text-danger transition-colors"
                              title="Delete this file"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
