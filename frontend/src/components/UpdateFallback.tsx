/**
 * UpdateFallback
 *
 * Full-screen fallback UI rendered by App.tsx when an update has broken the
 * backend (i.e. the post-update health check failed).
 *
 * Provides:
 *   - Clear error messaging
 *   - A "Retry" button that re-runs the health-check and clears the fallback
 *     state if the backend comes back healthy
 *   - A countdown auto-retry so the user doesn't have to click anything
 *   - Rollback instructions for manual recovery
 */

import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, RefreshCw, Terminal, CheckCircle, Loader } from "lucide-react";
import { api } from "../lib/api";

// ---------------------------------------------------------------------------
// Health-check (duplicated locally so this component has zero external deps
// that could themselves be broken during a bad update)
// ---------------------------------------------------------------------------

async function localHealthCheck(): Promise<{ ok: boolean; detail?: string }> {
  try {
    const res = await api.get("/health", { timeout: 6000 });
    if (res.status === 200 && res.data?.status === "ok") return { ok: true };
    return { ok: false, detail: `Status ${res.status}: ${JSON.stringify(res.data)}` };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, detail: msg };
  }
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface UpdateFallbackProps {
  /** Reason the fallback was triggered (from UpdateChecker). */
  reason: string;
  /** Called when the health-check confirms the backend is healthy again. */
  onRecovered: () => void;
  /**
   * Seconds between auto-retry attempts. Set to 0 to disable auto-retry.
   * Default: 15.
   */
  autoRetrySeconds?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UpdateFallback({
  reason,
  onRecovered,
  autoRetrySeconds = 15,
}: UpdateFallbackProps) {
  const [retrying, setRetrying]     = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retryOk, setRetryOk]       = useState(false);
  const [countdown, setCountdown]   = useState(autoRetrySeconds);

  // ---------------------------------------------------------------------------
  // Retry logic
  // ---------------------------------------------------------------------------

  const doRetry = useCallback(async () => {
    if (retrying) return;
    setRetrying(true);
    setRetryError(null);

    const result = await localHealthCheck();

    setRetrying(false);
    if (result.ok) {
      setRetryOk(true);
      // Short delay so the user sees the green tick before the fallback unmounts
      setTimeout(() => onRecovered(), 800);
    } else {
      setRetryError(result.detail ?? "Backend still unreachable.");
      setCountdown(autoRetrySeconds); // reset countdown
    }
  }, [retrying, onRecovered, autoRetrySeconds]);

  // ---------------------------------------------------------------------------
  // Auto-retry countdown
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (autoRetrySeconds <= 0) return;

    const tick = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          doRetry();
          return autoRetrySeconds;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(tick);
  }, [autoRetrySeconds, doRetry]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      data-testid="update-fallback"
      className="flex flex-col items-center justify-center h-screen bg-background text-foreground p-8 gap-6"
    >
      {/* Icon */}
      <div className="flex items-center justify-center w-16 h-16 rounded-full bg-danger-subtle border border-danger">
        {retryOk ? (
          <CheckCircle className="w-8 h-8 text-success" />
        ) : retrying ? (
          <Loader className="w-8 h-8 text-accent animate-spin" />
        ) : (
          <AlertTriangle className="w-8 h-8 text-danger" />
        )}
      </div>

      {/* Headline */}
      <div className="text-center max-w-lg">
        {retryOk ? (
          <h1 className="text-xl font-semibold text-success">Backend recovered</h1>
        ) : (
          <>
            <h1 className="text-xl font-semibold text-danger">
              Update broke the backend
            </h1>
            <p className="mt-2 text-sm text-muted">
              The post-update health check failed. The application has fallen
              back to safe mode to prevent data loss.
            </p>
          </>
        )}
      </div>

      {/* Error detail */}
      {!retryOk && (
        <div className="w-full max-w-lg rounded border border-border bg-surface p-4 text-xs font-mono text-danger break-words">
          {reason}
          {retryError && (
            <div className="mt-2 text-muted">Last retry: {retryError}</div>
          )}
        </div>
      )}

      {/* Retry button */}
      {!retryOk && (
        <button
          data-testid="retry-btn"
          onClick={doRetry}
          disabled={retrying}
          className="flex items-center gap-2 px-5 py-2 rounded border border-accent text-accent text-sm font-medium hover:bg-accent/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {retrying ? (
            <Loader className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {retrying
            ? "Checking…"
            : autoRetrySeconds > 0
              ? `Retry now (auto in ${countdown}s)`
              : "Retry"}
        </button>
      )}

      {/* Manual rollback instructions */}
      {!retryOk && (
        <details className="w-full max-w-lg text-xs text-muted cursor-pointer">
          <summary className="flex items-center gap-2 text-foreground font-medium select-none hover:text-accent transition-colors">
            <Terminal className="w-3.5 h-3.5 shrink-0" />
            Manual rollback instructions
          </summary>
          <div className="mt-3 space-y-2 pl-5 border-l border-border">
            <p>
              1. Stop the running backend process (Ctrl+C or kill the uvicorn
              process).
            </p>
            <p>
              2. Restore the previous version from your backup or run:{" "}
              <code className="bg-surface px-1 rounded">
                git checkout HEAD~1
              </code>
            </p>
            <p>
              3. Reinstall dependencies:{" "}
              <code className="bg-surface px-1 rounded">
                pip install -r requirements.txt
              </code>
            </p>
            <p>
              4. Restart the backend:{" "}
              <code className="bg-surface px-1 rounded">
                python -m uvicorn main:app --host 0.0.0.0 --port 8000
              </code>
            </p>
            <p>
              5. Click{" "}
              <span className="text-accent">Retry</span> above once the
              backend is running again.
            </p>
          </div>
        </details>
      )}
    </div>
  );
}
