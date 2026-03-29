/**
 * UpdateChecker
 *
 * Always-visible header button (↑ arrow icon) that opens a small status
 * popover. From there the user can:
 *   - See the running backend version
 *   - Manually trigger a check for updates
 *   - See the latest available version when one is found
 *   - Run the "Test Update" flow that health-checks before + after applying
 *     an update, and triggers the onUpdateFailed fallback if the backend
 *     breaks.
 *
 * A yellow dot badge on the button indicates an update is available.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import {
  RefreshCw,
  X,
  AlertTriangle,
  CheckCircle,
  Loader,
  ArrowUpCircle,
  ChevronDown,
} from "lucide-react";
import { checkForUpdates, UpdateCheckResult, api } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type UpdatePhase =
  | "idle"
  | "checking"
  | "pre-health"
  | "applying"
  | "post-health"
  | "success"
  | "failed";

export interface UpdateCheckerProps {
  /** How often to re-check for updates (ms). Default: 6 hours. */
  pollIntervalMs?: number;
  /** GitHub repo owner. Default: "anomalyco". */
  repoOwner?: string;
  /** GitHub repo name. Default: "wireshark-agent". */
  repoName?: string;
  /**
   * Optional callback that performs the actual update. If omitted the
   * component runs a 2-second simulated dry-run.
   */
  applyUpdate?: () => Promise<void>;
  /** Called when the post-update health-check fails. */
  onUpdateFailed?: (reason: string) => void;
  /** Called when the post-update health-check passes. */
  onUpdateSucceeded?: () => void;
}

// ---------------------------------------------------------------------------
// Health-check helper
// ---------------------------------------------------------------------------

interface HealthResult {
  ok: boolean;
  detail?: string;
}

async function healthCheck(timeoutMs = 5000): Promise<HealthResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await api.get("/health", {
      signal: controller.signal as AbortSignal,
    });
    clearTimeout(timer);
    if (res.status === 200 && res.data?.status === "ok") return { ok: true };
    return { ok: false, detail: `Unexpected response: ${JSON.stringify(res.data)}` };
  } catch (err: unknown) {
    clearTimeout(timer);
    return { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }
}

function defaultApplyUpdate(): Promise<void> {
  return new Promise((r) => setTimeout(r, 2000));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UpdateChecker({
  pollIntervalMs = 6 * 60 * 60 * 1000,
  repoOwner = "anomalyco",
  repoName  = "wireshark-agent",
  applyUpdate,
  onUpdateFailed,
  onUpdateSucceeded,
}: UpdateCheckerProps) {
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null);
  const [phase, setPhase]             = useState<UpdatePhase>("idle");
  const [phaseDetail, setPhaseDetail] = useState<string>("");
  const [open, setOpen]               = useState(false);
  const pollRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  // ---------------------------------------------------------------------------
  // Close popover when clicking outside
  // ---------------------------------------------------------------------------
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // ---------------------------------------------------------------------------
  // Polling
  // ---------------------------------------------------------------------------

  const runCheck = useCallback(async () => {
    setPhase("checking");
    try {
      const result = await checkForUpdates(repoOwner, repoName);
      setCheckResult(result);
    } finally {
      setPhase("idle");
    }
  }, [repoOwner, repoName]);

  useEffect(() => {
    runCheck();
    pollRef.current = setInterval(runCheck, pollIntervalMs);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runCheck, pollIntervalMs]);

  // ---------------------------------------------------------------------------
  // Test-update flow
  // ---------------------------------------------------------------------------

  const handleTestUpdate = useCallback(async () => {
    if (phase !== "idle") return;

    try {
      // 1. Pre-update health check
      setPhase("pre-health");
      setPhaseDetail("Verifying backend is healthy before update…");
      const pre = await healthCheck();
      if (!pre.ok) {
        setPhase("failed");
        setPhaseDetail(`Backend already unhealthy: ${pre.detail ?? "no detail"}. Aborting.`);
        onUpdateFailed?.(`Pre-update health check failed: ${pre.detail ?? "backend unreachable"}`);
        return;
      }

      // 2. Apply update
      setPhase("applying");
      setPhaseDetail("Applying update…");
      try {
        await (applyUpdate ?? defaultApplyUpdate)();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setPhase("failed");
        setPhaseDetail(`Update failed: ${msg}`);
        onUpdateFailed?.(`Update application threw: ${msg}`);
        return;
      }

      // 3. Post-update health check (3 attempts, 2-second gap)
      setPhase("post-health");
      let postResult: HealthResult = { ok: false, detail: "not run" };
      for (let attempt = 1; attempt <= 3; attempt++) {
        setPhaseDetail(`Post-update health check (${attempt}/3)…`);
        postResult = await healthCheck(6000);
        if (postResult.ok) break;
        if (attempt < 3) await new Promise((r) => setTimeout(r, 2000));
      }

      if (!postResult.ok) {
        setPhase("failed");
        setPhaseDetail(`Health check failed after update: ${postResult.detail ?? "no response"}. Fallback triggered.`);
        onUpdateFailed?.(`Post-update health check failed: ${postResult.detail ?? "backend unreachable"}`);
        return;
      }

      // 4. Success
      setPhase("success");
      setPhaseDetail(`Update to ${checkResult?.latestVersion ?? "latest"} verified successfully.`);
      onUpdateSucceeded?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPhase("failed");
      setPhaseDetail(`Unexpected error: ${msg}`);
      onUpdateFailed?.(`Unexpected error: ${msg}`);
    }
  }, [phase, applyUpdate, checkResult, onUpdateFailed, onUpdateSucceeded]);

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const isRunning   = ["checking", "pre-health", "applying", "post-health"].includes(phase);
  const hasUpdate   = !!checkResult?.updateAvailable;
  const checkError  = checkResult?.error;

  // ---------------------------------------------------------------------------
  // Header button + popover
  // ---------------------------------------------------------------------------

  return (
    <div className="relative" ref={popupRef}>
      {/* Always-visible header icon button */}
      <button
        data-testid="update-checker-trigger"
        onClick={() => setOpen((o) => !o)}
        title="Check for updates"
        className={`relative flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium transition-colors
          ${hasUpdate
            ? "text-attention hover:bg-attention/10"
            : "text-muted hover:text-foreground hover:bg-foreground/5"
          }`}
      >
        {isRunning
          ? <Loader className="w-3.5 h-3.5 animate-spin" />
          : phase === "success"
            ? <CheckCircle className="w-3.5 h-3.5 text-success" />
            : phase === "failed"
              ? <AlertTriangle className="w-3.5 h-3.5 text-danger" />
              : <ArrowUpCircle className="w-3.5 h-3.5" />
        }
        <span className="hidden sm:inline">Updates</span>
        <ChevronDown className="w-3 h-3 opacity-60" />

        {/* Yellow dot badge when update available */}
        {hasUpdate && !isRunning && (
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-attention ring-1 ring-background" />
        )}
      </button>

      {/* Popover panel */}
      {open && (
        <div
          data-testid="update-checker-panel"
          className="absolute right-0 top-full mt-1 w-80 z-50 rounded-lg border border-border bg-surface shadow-xl text-xs"
        >
          {/* Header row */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <span className="font-semibold text-foreground">Software Updates</span>
            <button
              onClick={() => setOpen(false)}
              className="text-muted hover:text-foreground"
              aria-label="Close"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="p-4 space-y-3">
            {/* Version info */}
            <div className="flex items-center justify-between text-muted">
              <span>Running version</span>
              <span className="font-mono text-foreground">
                {checkResult?.currentVersion ?? "—"}
              </span>
            </div>

            {checkResult?.latestVersion && (
              <div className="flex items-center justify-between text-muted">
                <span>Latest release</span>
                <span className={`font-mono ${hasUpdate ? "text-attention" : "text-success"}`}>
                  {checkResult.latestVersion}
                </span>
              </div>
            )}

            {/* Status message */}
            {phase === "idle" && !isRunning && (
              <div className={`flex items-center gap-2 rounded px-3 py-2
                ${phase === "idle" && !checkResult
                  ? "bg-border-subtle text-muted"
                  : hasUpdate
                    ? "bg-warning-subtle text-attention"
                    : checkError
                      ? "bg-danger-subtle text-danger"
                      : "bg-success-subtle text-success"
                }`}
              >
                {hasUpdate ? (
                  <><RefreshCw className="w-3.5 h-3.5 shrink-0" /> Update available</>
                ) : checkError ? (
                  <><AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {checkError}</>
                ) : checkResult ? (
                  <><CheckCircle className="w-3.5 h-3.5 shrink-0" /> Up to date</>
                ) : (
                  "Not checked yet"
                )}
              </div>
            )}

            {/* Running phase detail */}
            {(isRunning || phase === "success" || phase === "failed") && (
              <div className={`flex items-start gap-2 rounded px-3 py-2 text-[0.7rem] leading-relaxed
                ${phase === "failed"   ? "bg-danger-subtle text-danger"
                : phase === "success"  ? "bg-success-subtle text-success"
                : "bg-accent-subtle text-accent"}`}
              >
                {isRunning
                  ? <Loader className="w-3.5 h-3.5 shrink-0 mt-px animate-spin" />
                  : phase === "success"
                    ? <CheckCircle className="w-3.5 h-3.5 shrink-0 mt-px" />
                    : <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
                }
                <span>{phaseDetail}</span>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-2 pt-1">
              {/* Manual re-check */}
              <button
                data-testid="check-now-btn"
                onClick={runCheck}
                disabled={isRunning}
                className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded border border-border
                  text-muted hover:text-foreground hover:border-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <RefreshCw className="w-3 h-3" />
                Check now
              </button>

              {/* Test Update — only when update available */}
              {hasUpdate && phase === "idle" && (
                <button
                  data-testid="test-update-btn"
                  onClick={handleTestUpdate}
                  className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded border border-attention
                    text-attention hover:bg-attention/10 transition-colors font-medium"
                >
                  <ArrowUpCircle className="w-3 h-3" />
                  Test Update
                </button>
              )}

              {/* Reset after success/failure */}
              {(phase === "success" || phase === "failed") && (
                <button
                  onClick={() => { setPhase("idle"); setPhaseDetail(""); }}
                  className="flex-1 py-1.5 rounded border border-border text-muted hover:text-foreground transition-colors"
                >
                  Dismiss
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
