import { useState, useEffect, useCallback } from "react";
import {
  Clock, Plus, Trash2, Play, ChevronRight, ChevronDown,
  X, Loader2, CheckCircle2, XCircle, Minus,
} from "lucide-react";
import { toast } from "./Toast";
import {
  fetchSchedulerJobs,
  createSchedulerJob,
  deleteSchedulerJob,
  runJobNow,
  fetchJobHistory,
  type SchedulerJob,
  type JobRunRecord,
  type CreateJobPayload,
} from "../lib/api";
import { Skeleton } from "./Skeleton";

// ── Constants ─────────────────────────────────────────────────────────────────

const JOB_TYPES = [
  { value: "health_check",   label: "Health Check",    description: "Check system health every N minutes" },
  { value: "packet_capture", label: "Packet Capture",  description: "Capture live traffic for N seconds on a schedule" },
  { value: "auto_insight",   label: "Auto Insight",    description: "Auto-generate traffic insights" },
  { value: "anomaly_scan",   label: "Anomaly Scan",    description: "Detect network anomalies automatically" },
  { value: "modbus_poll",    label: "Modbus Poll",     description: "Poll active Modbus sessions" },
] as const;

type JobTypeValue = typeof JOB_TYPES[number]["value"];

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(isoString: string | null): string {
  if (!isoString) return "Never";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "Never";
  const diffMs = Date.now() - date.getTime();
  const absDiff = Math.abs(diffMs);
  const isFuture = diffMs < 0;

  const seconds = Math.floor(absDiff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours   = Math.floor(minutes / 60);
  const days    = Math.floor(hours / 24);

  let label: string;
  if (seconds < 60)       label = `${seconds}s`;
  else if (minutes < 60)  label = `${minutes} min`;
  else if (hours < 24)    label = `${hours}h`;
  else                    label = `${days}d`;

  return isFuture ? `in ${label}` : `${label} ago`;
}

function formatTimestamp(isoString: string): string {
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return isoString;
  return date.toLocaleString();
}

// ── Status Badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: 'ok' | 'error' | null }) {
  if (status === null) {
    return (
      <span className="flex items-center gap-1 text-muted text-xs">
        <Minus className="w-3 h-3" />
        <span>—</span>
      </span>
    );
  }
  if (status === 'ok') {
    return (
      <span className="flex items-center gap-1 text-success text-xs">
        <CheckCircle2 className="w-3.5 h-3.5" />
        <span>OK</span>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-danger text-xs">
      <XCircle className="w-3.5 h-3.5" />
      <span>Error</span>
    </span>
  );
}

// ── Job History Panel ─────────────────────────────────────────────────────────

interface HistoryPanelProps {
  job: SchedulerJob;
  onClose: () => void;
}

function HistoryPanel({ job, onClose }: HistoryPanelProps) {
  const [records, setRecords] = useState<JobRunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedOutputs, setExpandedOutputs] = useState<Set<number>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchJobHistory(job.id)
      .then((data) => {
        if (!cancelled) {
          setRecords(data.slice(0, 20));
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          toast.error(`Failed to load history: ${err.message}`);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [job.id]);

  const toggleOutput = (idx: number) => {
    setExpandedOutputs((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className="border-l border-border bg-surface w-80 shrink-0 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="min-w-0">
          <div className="text-foreground text-sm font-semibold truncate">{job.name}</div>
          <div className="text-muted text-xs mt-0.5">Last 20 runs</div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close history panel"
          className="ml-2 shrink-0 text-muted hover:text-foreground transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Records */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 space-y-6">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="space-y-2">
                <div className="flex justify-between">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-3 w-8" />
                </div>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-10 w-full" />
              </div>
            ))}
          </div>
        ) : records.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-muted text-sm">
            <Clock className="w-8 h-8 mb-2 opacity-40" />
            No run records yet
          </div>
        ) : (
          <div className="divide-y divide-border">
            {records.map((record, idx) => {
              const isExpanded = expandedOutputs.has(idx);
              const truncated = record.output.length > 200;
              const displayOutput = isExpanded
                ? record.output
                : record.output.slice(0, 200);

              return (
                <div key={idx} className="px-4 py-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <StatusBadge status={record.status} />
                    <span className="text-muted text-xs">{record.duration_ms}ms</span>
                  </div>
                  <div className="text-muted text-xs">
                    {formatTimestamp(record.started_at)}
                  </div>
                  {record.output && (
                    <div>
                      <pre className="text-foreground text-[11px] font-mono bg-background rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap break-words leading-relaxed">
                        {displayOutput}
                        {truncated && !isExpanded && "…"}
                      </pre>
                      {truncated && (
                        <button
                          onClick={() => toggleOutput(idx)}
                          className="text-accent text-xs mt-1 hover:underline"
                        >
                          {isExpanded ? "show less" : "show more"}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Add Job Modal ─────────────────────────────────────────────────────────────

interface AddJobModalProps {
  onClose: () => void;
  onCreated: (job: SchedulerJob) => void;
}

function AddJobModal({ onClose, onCreated }: AddJobModalProps) {
  const [jobType, setJobType] = useState<JobTypeValue>("health_check");
  const [schedule, setSchedule] = useState("");
  const [name, setName] = useState("");
  const [captureSeconds, setCaptureSeconds] = useState(10);
  const [submitting, setSubmitting] = useState(false);

  const selectedType = JOB_TYPES.find((t) => t.value === jobType)!;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!schedule.trim()) {
      toast.warn("Schedule is required");
      return;
    }

    const params: Record<string, unknown> = {};
    if (jobType === "packet_capture") {
      params.seconds = captureSeconds;
    }

    const payload: CreateJobPayload = {
      type: jobType,
      schedule: schedule.trim(),
      params,
    };
    if (name.trim()) payload.name = name.trim();

    setSubmitting(true);
    try {
      const created = await createSchedulerJob(payload);
      toast.success("Job created");
      onCreated(created);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to create job: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Add scheduled job"
    >
      <div className="bg-surface border border-border rounded-lg w-full max-w-md mx-4 shadow-2xl">
        {/* Modal header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2 text-foreground">
            <Clock className="w-4 h-4 text-accent" />
            <span className="font-semibold text-sm">Add Scheduled Job</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close modal"
            className="text-muted hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
          {/* Job Type */}
          <div>
            <label className="block text-muted text-xs font-medium mb-1.5" htmlFor="job-type">
              Job Type
            </label>
            <select
              id="job-type"
              value={jobType}
              onChange={(e) => setJobType(e.target.value as JobTypeValue)}
              className="w-full bg-background border border-border rounded px-3 py-2 text-foreground text-sm focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40"
            >
              {JOB_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            <p className="mt-1 text-muted text-xs">{selectedType.description}</p>
          </div>

          {/* Schedule */}
          <div>
            <label className="block text-muted text-xs font-medium mb-1.5" htmlFor="job-schedule">
              Schedule
            </label>
            <input
              id="job-schedule"
              type="text"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="*/5 * * * * or 5m or 1h"
              required
              className="w-full bg-background border border-border rounded px-3 py-2 text-foreground text-sm placeholder-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40"
            />
          </div>

          {/* Name (optional) */}
          <div>
            <label className="block text-muted text-xs font-medium mb-1.5" htmlFor="job-name">
              Name <span className="text-muted font-normal">(optional)</span>
            </label>
            <input
              id="job-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My scheduled job"
              className="w-full bg-background border border-border rounded px-3 py-2 text-foreground text-sm placeholder-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40"
            />
          </div>

          {/* Capture-specific: seconds */}
          {jobType === "packet_capture" && (
            <div>
              <label className="block text-muted text-xs font-medium mb-1.5" htmlFor="capture-seconds">
                Capture Duration (seconds)
              </label>
              <input
                id="capture-seconds"
                type="number"
                min={1}
                max={3600}
                value={captureSeconds}
                onChange={(e) => setCaptureSeconds(Math.max(1, parseInt(e.target.value, 10) || 10))}
                className="w-full bg-background border border-border rounded px-3 py-2 text-foreground text-sm focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/40"
              />
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-muted hover:text-foreground transition-colors rounded border border-border hover:border-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-accent-emphasis hover:bg-accent text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Create Job
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Job Row ───────────────────────────────────────────────────────────────────

interface JobRowProps {
  job: SchedulerJob;
  isSelected: boolean;
  onSelect: () => void;
  onRunNow: (id: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

function JobRow({ job, isSelected, onSelect, onRunNow, onDelete }: JobRowProps) {
  const [runningNow, setRunningNow] = useState(false);
  const [deletingNow, setDeletingNow] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleRunNow = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setRunningNow(true);
    try {
      await onRunNow(job.id);
    } finally {
      setRunningNow(false);
    }
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmDelete(true);
  };

  const handleConfirmDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setDeletingNow(true);
    try {
      await onDelete(job.id);
    } finally {
      setDeletingNow(false);
      setConfirmDelete(false);
    }
  };

  const handleCancelDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmDelete(false);
  };

  const typeDef = JOB_TYPES.find((t) => t.value === job.type);
  const typeLabel = typeDef?.label ?? job.type;

  return (
    <tr
      onClick={onSelect}
      className={`border-b border-border cursor-pointer transition-colors ${
        isSelected
          ? "bg-accent-subtle hover:bg-accent-subtle"
          : "hover:bg-surface-hover"
      }`}
    >
      {/* Name + type badge */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {isSelected
            ? <ChevronDown className="w-3.5 h-3.5 text-accent shrink-0" />
            : <ChevronRight className="w-3.5 h-3.5 text-muted shrink-0" />
          }
          <div className="min-w-0">
            <div className="text-foreground text-sm font-medium truncate">{job.name}</div>
            <span className="inline-block mt-0.5 px-1.5 py-0.5 text-[10px] rounded bg-surface-hover text-muted border border-border">
              {typeLabel}
            </span>
          </div>
        </div>
      </td>

      {/* Schedule */}
      <td className="px-4 py-3">
        <code className="text-muted text-xs font-mono">{job.schedule}</code>
      </td>

      {/* Last run */}
      <td className="px-4 py-3 text-muted text-xs">
        {relativeTime(job.last_run)}
      </td>

      {/* Status */}
      <td className="px-4 py-3">
        <StatusBadge status={job.last_status} />
      </td>

      {/* Next run */}
      <td className="px-4 py-3 text-muted text-xs">
        {job.next_run ? relativeTime(job.next_run) : "—"}
      </td>

      {/* Actions */}
      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
        {confirmDelete ? (
          <div className="flex items-center gap-1.5">
            <span className="text-danger text-xs">Delete?</span>
            <button
              onClick={handleConfirmDelete}
              disabled={deletingNow}
              aria-label="Confirm delete"
              className="px-2 py-1 text-xs bg-danger-emphasis hover:bg-danger text-white rounded transition-colors disabled:opacity-50"
            >
              {deletingNow ? <Loader2 className="w-3 h-3 animate-spin" /> : "Yes"}
            </button>
            <button
              onClick={handleCancelDelete}
              aria-label="Cancel delete"
              className="px-2 py-1 text-xs border border-border text-muted hover:text-foreground rounded transition-colors"
            >
              No
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <button
              onClick={handleRunNow}
              disabled={runningNow}
              aria-label={`Run ${job.name} now`}
              title="Run now"
              className="flex items-center gap-1 px-2 py-1 text-xs border border-border text-muted hover:text-success hover:border-success/50 rounded transition-colors disabled:opacity-50"
            >
              {runningNow
                ? <Loader2 className="w-3 h-3 animate-spin" />
                : <Play className="w-3 h-3" />
              }
              Run
            </button>
            <button
              onClick={handleDeleteClick}
              aria-label={`Delete ${job.name}`}
              title="Delete job"
              className="flex items-center gap-1 px-2 py-1 text-xs border border-border text-muted hover:text-danger hover:border-danger/50 rounded transition-colors"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export function SchedulerPanel() {
  const [jobs, setJobs] = useState<SchedulerJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    try {
      const data = await fetchSchedulerJobs();
      setJobs(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to load jobs: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadJobs();
    const interval = setInterval(loadJobs, 30_000);
    return () => clearInterval(interval);
  }, [loadJobs]);

  const handleJobCreated = (job: SchedulerJob) => {
    setJobs((prev) => [...prev, job]);
    setShowAddModal(false);
  };

  const handleRunNow = async (id: string) => {
    try {
      await runJobNow(id);
      toast.success("Job triggered");
      // Refresh after a short delay so last_run may update
      setTimeout(loadJobs, 1500);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to trigger job: ${msg}`);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteSchedulerJob(id);
      setJobs((prev) => prev.filter((j) => j.id !== id));
      if (selectedJobId === id) setSelectedJobId(null);
      toast.success("Job deleted");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to delete job: ${msg}`);
    }
  };

  const handleSelectRow = (id: string) => {
    setSelectedJobId((prev) => (prev === id ? null : id));
  };

  const selectedJob = jobs.find((j) => j.id === selectedJobId) ?? null;

  return (
    <div className="flex h-full bg-background">
      {/* Main area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border bg-surface shrink-0">
          <div className="flex items-center gap-3">
            <Clock className="w-5 h-5 text-accent" />
            <div>
              <h2 className="text-foreground font-semibold text-sm">Autonomous Scheduler</h2>
              <p className="text-muted text-xs mt-0.5">Schedule recurring network monitoring jobs</p>
            </div>
          </div>
          <button
            onClick={() => setShowAddModal(true)}
            aria-label="Add new scheduled job"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-accent-emphasis hover:bg-accent text-white rounded transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Job
          </button>
        </div>

        {/* Job list */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-4 space-y-4">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 border border-border rounded-lg bg-surface">
                  <div className="flex-1 space-y-2">
                    <div className="flex items-center gap-2">
                      <Skeleton className="h-5 w-32" />
                      <Skeleton className="h-4 w-12" />
                    </div>
                    <Skeleton className="h-4 w-48" />
                  </div>
                  <div className="flex gap-2">
                    <Skeleton className="h-8 w-16" />
                    <Skeleton className="h-8 w-16" />
                    <Skeleton className="h-8 w-8" />
                  </div>
                </div>
              ))}
            </div>
          ) : jobs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted">
              <Clock className="w-12 h-12 mb-3 opacity-25" />
              <p className="text-sm font-medium text-foreground">No scheduled jobs</p>
              <p className="text-xs mt-1">Click 'Add Job' to create one.</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="px-4 py-2.5 text-muted text-xs font-semibold uppercase tracking-wider">Name</th>
                  <th className="px-4 py-2.5 text-muted text-xs font-semibold uppercase tracking-wider">Schedule</th>
                  <th className="px-4 py-2.5 text-muted text-xs font-semibold uppercase tracking-wider">Last Run</th>
                  <th className="px-4 py-2.5 text-muted text-xs font-semibold uppercase tracking-wider">Status</th>
                  <th className="px-4 py-2.5 text-muted text-xs font-semibold uppercase tracking-wider">Next Run</th>
                  <th className="px-4 py-2.5 text-muted text-xs font-semibold uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    isSelected={selectedJobId === job.id}
                    onSelect={() => handleSelectRow(job.id)}
                    onRunNow={handleRunNow}
                    onDelete={handleDelete}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* History drawer */}
      {selectedJob && (
        <HistoryPanel
          job={selectedJob}
          onClose={() => setSelectedJobId(null)}
        />
      )}

      {/* Add job modal */}
      {showAddModal && (
        <AddJobModal
          onClose={() => setShowAddModal(false)}
          onCreated={handleJobCreated}
        />
      )}
    </div>
  );
}
