import { useState, useEffect, useRef } from "react";
import {
  BookOpen, Upload, Link, Globe, Trash2, Loader2,
  CheckCircle2, AlertTriangle, RefreshCw, Search, ChevronDown, ChevronRight,
  Square,
} from "lucide-react";
import { toast } from "./Toast";
import {
  fetchRAGStatus, fetchRAGSources, deleteRAGSource,
  ingestRAGPdf, ingestRAGUrl, crawlWireshark, crawlPanOS,
  fetchRAGTasks, queryRAG, cancelIngestTask,
  type RAGStatus, type RAGSource, type RAGTask,
} from "../lib/api";
import { Skeleton } from "./Skeleton";

// ── Status bar ────────────────────────────────────────────────────────────────

function StatusBar({ status }: { status: RAGStatus | null }) {
  if (!status) {
    return (
      <div className="flex items-center gap-2 px-4 py-2 bg-surface border-b border-border text-xs text-muted">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading status…
      </div>
    );
  }
  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-surface border-b border-border text-xs">
      <div className="flex items-center gap-1.5">
        <BookOpen className="w-3.5 h-3.5 text-accent" />
        <span className="text-foreground font-semibold">{status.total_chunks.toLocaleString()}</span>
        <span className="text-muted">chunks indexed</span>
      </div>
      <div
        className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] ${
          status.ready
            ? "bg-success-subtle border-success-emphasis text-success"
            : "bg-danger-subtle border-danger text-danger"
        }`}
      >
        {status.ready ? <CheckCircle2 className="w-2.5 h-2.5" /> : <AlertTriangle className="w-2.5 h-2.5" />}
        {status.ready ? "Ready" : "No documents"}
      </div>
      <div
        className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] ${
          status.hhem_available
            ? "bg-success-subtle border-success-emphasis text-success"
            : "bg-warning-subtle border-warning/70 text-warning"
        }`}
      >
        {status.hhem_available ? <CheckCircle2 className="w-2.5 h-2.5" /> : <AlertTriangle className="w-2.5 h-2.5" />}
        HHEM {status.hhem_available ? "loaded" : "unavailable"}
      </div>
    </div>
  );
}

// ── Task progress list ────────────────────────────────────────────────────────

function TaskList({
  tasks,
  onCancel,
}: {
  tasks: RAGTask[];
  onCancel: (task_id: string) => void;
}) {
  const [cancelling, setCancelling] = useState<string | null>(null);

  if (tasks.length === 0) return null;

  const handleCancel = async (task_id: string) => {
    setCancelling(task_id);
    try {
      await onCancel(task_id);
    } finally {
      setCancelling(null);
    }
  };

  return (
    <div className="space-y-1 mt-3">
      {tasks.map((t) => (
        <div
          key={t.task_id}
          className={`flex items-center gap-2 px-3 py-1.5 rounded border text-xs ${
            t.status === "done"
              ? "border-success-emphasis bg-success-subtle text-success"
              : t.status === "error"
              ? "border-danger bg-danger-subtle text-danger"
              : t.status === "cancelled"
              ? "border-warning/70 bg-warning-subtle text-warning"
              : "border-accent-emphasis bg-background text-accent-muted"
          }`}
        >
          {t.status === "running" && <Loader2 className="w-3 h-3 animate-spin shrink-0" />}
          {t.status === "done" && <CheckCircle2 className="w-3 h-3 shrink-0" />}
          {t.status === "error" && <AlertTriangle className="w-3 h-3 shrink-0" />}
          {t.status === "cancelled" && <Square className="w-3 h-3 shrink-0" />}
          <span className="font-mono truncate flex-1">{t.source_name}</span>
          <span className="text-[10px] shrink-0 text-muted">{t.progress}</span>
          {(t.status === "done" || t.status === "cancelled") && (
            <span className="text-[10px] shrink-0">+{t.chunks_added} chunks</span>
          )}
          {t.status === "running" && (
            <button
              onClick={() => handleCancel(t.task_id)}
              disabled={cancelling === t.task_id}
              title="Stop ingestion"
              className="ml-1 flex items-center gap-1 px-1.5 py-0.5 rounded border border-danger text-danger hover:bg-danger-subtle disabled:opacity-50 transition-colors text-[10px] shrink-0"
            >
              {cancelling === t.task_id
                ? <Loader2 className="w-2.5 h-2.5 animate-spin" />
                : <Square className="w-2.5 h-2.5" />}
              Stop
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Sources table ─────────────────────────────────────────────────────────────

function SourcesTable({
  sources,
  onDelete,
}: {
  sources: RAGSource[];
  onDelete: (name: string) => void;
}) {
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleDelete = async (name: string) => {
    setDeleting(name);
    try {
      await onDelete(name);
    } finally {
      setDeleting(null);
    }
  };

  if (sources.length === 0) {
    return (
      <div className="text-center py-8 text-muted text-xs">
        No documents ingested yet. Upload a PDF, paste a URL, or crawl the Wireshark wiki.
      </div>
    );
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-border text-muted">
          <th className="text-left py-1.5 px-2 font-medium">Source</th>
          <th className="text-right py-1.5 px-2 font-medium">Chunks</th>
          <th className="py-1.5 px-2" />
        </tr>
      </thead>
      <tbody>
        {sources.map((s) => (
          <tr key={s.name} className="border-b border-border-subtle hover:bg-surface transition-colors">
            <td className="py-1.5 px-2 text-foreground font-mono truncate max-w-xs">{s.name}</td>
            <td className="py-1.5 px-2 text-right text-muted">{s.chunk_count}</td>
            <td className="py-1.5 px-2 text-right">
              <button
                onClick={() => handleDelete(s.name)}
                disabled={deleting === s.name}
                className="text-muted hover:text-danger disabled:opacity-50 transition-colors"
              >
                {deleting === s.name ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Trash2 className="w-3 h-3" />
                )}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Query test box ────────────────────────────────────────────────────────────

function QueryTestBox() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const handleQuery = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await queryRAG(query.trim(), 3);
      setResult(res.formatted);
      setExpanded(true);
    } catch (e) {
      setResult("Error: " + (e instanceof Error ? e.message : String(e)));
      setExpanded(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-4 border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-surface text-xs text-muted hover:text-foreground transition-colors"
      >
        <Search className="w-3.5 h-3.5 text-accent" />
        <span className="font-semibold text-foreground">Test retrieval</span>
        <span className="text-[10px] ml-1">— check what the KB returns for a query</span>
        <span className="ml-auto">
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </span>
      </button>
      {expanded && (
        <div className="p-3 bg-background border-t border-border">
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleQuery()}
              placeholder="e.g. How do I filter TLS traffic in Wireshark?"
              className="flex-1 bg-surface border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent placeholder-muted-dim"
            />
            <button
              onClick={handleQuery}
              disabled={loading || !query.trim()}
              className="flex items-center gap-1 px-3 py-1.5 bg-success-emphasis hover:bg-success-emphasis-hover disabled:opacity-50 text-white text-xs rounded transition-colors"
            >
              {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
              Search
            </button>
          </div>
          {result && (
            <pre className="mt-3 text-[10px] font-mono text-foreground whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto bg-surface border border-border rounded p-2">
              {result}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main RAGPanel ─────────────────────────────────────────────────────────────

export function RAGPanel() {
  const [status, setStatus] = useState<RAGStatus | null>(null);
  const [sources, setSources] = useState<RAGSource[]>([]);
  const [tasks, setTasks] = useState<RAGTask[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  // Ingest — PDF
  const [pdfDragging, setPdfDragging] = useState(false);
  const [pdfUploading, setPdfUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Ingest — URL
  const [urlInput, setUrlInput] = useState("");
  const [urlName, setUrlName] = useState("");
  const [urlLoading, setUrlLoading] = useState(false);

  // Crawl — PAN-OS
  const [panosUrl, setPanosUrl] = useState("");
  const [panosPages, setPanosPages] = useState(50);
  const [panosLoading, setPanosLoading] = useState(false);

  // Crawl — Wireshark
  const [wsLoading, setWsLoading] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const [s, src, t] = await Promise.all([
        fetchRAGStatus(),
        fetchRAGSources(),
        fetchRAGTasks(),
      ]);
      setStatus(s);
      setSources(src);
      setTasks(t);
    } catch {}
    setRefreshing(false);
  };

  useEffect(() => {
    refresh();
    // Poll every 5s while there are running tasks
    const id = setInterval(async () => {
      const t = await fetchRAGTasks().catch(() => [] as RAGTask[]);
      setTasks(t);
      if (t.some((tk) => tk.status === "running")) {
        const [s, src] = await Promise.all([fetchRAGStatus(), fetchRAGSources()]).catch(() => [null, []]);
        if (s) setStatus(s as RAGStatus);
        if (src) setSources(src as RAGSource[]);
      }
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const handlePdfFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setPdfUploading(true);
    try {
      for (const file of Array.from(files)) {
        await ingestRAGPdf(file);
      }
      await refresh();
    } catch (e) {
      toast.error("Upload failed: " + (e instanceof Error ? e.message : String(e)));
    } finally {
      setPdfUploading(false);
    }
  };

  const handleUrlIngest = async () => {
    if (!urlInput.trim()) return;
    setUrlLoading(true);
    try {
      await ingestRAGUrl(urlInput.trim(), urlName.trim() || urlInput.trim());
      setUrlInput("");
      setUrlName("");
      await refresh();
    } catch (e) {
      toast.error("URL ingest failed: " + (e instanceof Error ? e.message : String(e)));
    } finally {
      setUrlLoading(false);
    }
  };

  const handleWiresharkCrawl = async () => {
    setWsLoading(true);
    try {
      await crawlWireshark();
      await refresh();
    } catch (e) {
      toast.error("Crawl failed: " + (e instanceof Error ? e.message : String(e)));
    } finally {
      setWsLoading(false);
    }
  };

  const handlePanosCrawl = async () => {
    if (!panosUrl.trim()) return;
    setPanosLoading(true);
    try {
      await crawlPanOS(panosUrl.trim(), panosPages);
      await refresh();
    } catch (e) {
      toast.error("Crawl failed: " + (e instanceof Error ? e.message : String(e)));
    } finally {
      setPanosLoading(false);
    }
  };

  const handleDeleteSource = async (name: string) => {
    await deleteRAGSource(name);
    await refresh();
  };

  const handleCancelTask = async (task_id: string) => {
    try {
      await cancelIngestTask(task_id);
      // Optimistically mark as cancelled in local state while we wait for next poll
      setTasks((prev) =>
        prev.map((t) =>
          t.task_id === task_id
            ? { ...t, status: "cancelled", progress: "Cancellation requested…" }
            : t
        )
      );
    } catch (e) {
      toast.error("Cancel failed: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Status bar */}
      <StatusBar status={status} />

      <div className="flex-1 overflow-auto p-4 space-y-6">

        {/* ── Ingest section ── */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Upload className="w-4 h-4 text-accent" />
              Ingest Documents
            </h2>
            <button
              onClick={refresh}
              disabled={refreshing}
              className="flex items-center gap-1 text-muted hover:text-foreground text-xs disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* PDF Upload */}
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-muted uppercase tracking-wider">PDF / Document</h3>
              <div
                onDragOver={(e) => { e.preventDefault(); setPdfDragging(true); }}
                onDragLeave={() => setPdfDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setPdfDragging(false);
                  handlePdfFiles(e.dataTransfer.files);
                }}
                onClick={() => fileInputRef.current?.click()}
                className={`flex flex-col items-center justify-center gap-2 h-28 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
                  pdfDragging
                    ? "border-accent bg-accent-subtle/20"
                    : "border-border hover:border-accent hover:bg-surface"
                }`}
              >
                {pdfUploading ? (
                  <Loader2 className="w-6 h-6 text-accent animate-spin" />
                ) : (
                  <>
                    <Upload className="w-6 h-6 text-muted" />
                    <span className="text-xs text-muted">Drop PDF / DOCX / HTML here</span>
                    <span className="text-[10px] text-muted-dim">or click to browse</span>
                  </>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.html,.htm,.txt,.md"
                className="hidden"
                onChange={(e) => handlePdfFiles(e.target.files)}
              />
            </div>

            {/* URL Ingest */}
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-muted uppercase tracking-wider">URL / Web Page</h3>
              <div className="space-y-2">
                <input
                  type="text"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  placeholder="https://example.com/docs/page"
                  className="w-full bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent placeholder-muted-dim"
                />
                <input
                  type="text"
                  value={urlName}
                  onChange={(e) => setUrlName(e.target.value)}
                  placeholder="Source name (optional)"
                  className="w-full bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent placeholder-muted-dim"
                />
                <button
                  onClick={handleUrlIngest}
                  disabled={urlLoading || !urlInput.trim()}
                  className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-success-emphasis hover:bg-success-emphasis-hover disabled:opacity-50 text-white text-xs rounded transition-colors"
                >
                  {urlLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Link className="w-3 h-3" />}
                  Ingest URL
                </button>
              </div>
            </div>
          </div>

          {/* Crawler section */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Wireshark wiki crawler */}
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-muted uppercase tracking-wider">Wireshark Wiki Crawler</h3>
              <p className="text-[10px] text-muted">
                Crawls ~13 key Wireshark wiki pages: display filters, capture, protocols, TLS, Lua scripting, etc.
              </p>
              <button
                onClick={handleWiresharkCrawl}
                disabled={wsLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-accent-emphasis hover:bg-accent-emphasis-hover disabled:opacity-50 text-white text-xs rounded transition-colors"
              >
                {wsLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Globe className="w-3 h-3" />}
                Crawl Wireshark Wiki
              </button>
            </div>

            {/* PAN-OS crawler */}
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-muted uppercase tracking-wider">PAN-OS TechDocs Crawler</h3>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={panosUrl}
                  onChange={(e) => setPanosUrl(e.target.value)}
                  placeholder="https://docs.paloaltonetworks.com/pan-os/..."
                  className="flex-1 bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent placeholder-muted-dim"
                />
                <input
                  type="number"
                  value={panosPages}
                  onChange={(e) => setPanosPages(parseInt(e.target.value) || 50)}
                  min={1}
                  max={500}
                  className="w-16 bg-background border border-border text-foreground text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent text-center"
                  title="Max pages"
                />
              </div>
              <button
                onClick={handlePanosCrawl}
                disabled={panosLoading || !panosUrl.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-emphasis hover:bg-purple-emphasis-hover disabled:opacity-50 text-white text-xs rounded transition-colors"
              >
                {panosLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Globe className="w-3 h-3" />}
                Crawl PAN-OS Docs
              </button>
            </div>
          </div>

          {/* Task progress */}
          <TaskList tasks={tasks} onCancel={handleCancelTask} />
        </section>

        {/* ── Sources section ── */}
        <section>
          <h2 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-3">
            <BookOpen className="w-4 h-4 text-accent" />
            Indexed Sources
            <span className="text-muted font-normal text-xs">({sources.length})</span>
          </h2>
          <div className="bg-background border border-border rounded-lg overflow-hidden">
            <SourcesTable sources={sources} onDelete={handleDeleteSource} />
          </div>
        </section>

        {/* ── Query test box ── */}
        <section>
          <QueryTestBox />
        </section>

      </div>
    </div>
  );
}
