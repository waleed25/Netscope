/**
 * Lightweight toast notification system.
 * No external dependencies — pure React + Tailwind.
 *
 * Usage:
 *   import { toast } from "./Toast";
 *   toast.success("Document indexed");
 *   toast.error("Upload failed: " + err.message);
 *   toast.warn("BPF filter syntax may be invalid");
 *   toast.info("Capture started");
 *
 * Mount <ToastContainer /> once near the app root (Dashboard.tsx).
 */

import { useState, useEffect, useCallback, type ReactNode } from "react";
import { CheckCircle, XCircle, AlertTriangle, Info, X } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

type ToastKind = "success" | "error" | "warn" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  duration: number;
}

// ── Global event bus ──────────────────────────────────────────────────────────

type ToastListener = (item: ToastItem) => void;
const _listeners: ToastListener[] = [];
let _nextId = 0;

function _emit(kind: ToastKind, message: string, duration = 4000) {
  const item: ToastItem = { id: _nextId++, kind, message, duration };
  _listeners.forEach((fn) => fn(item));
}

/** Call these anywhere in the app to show a notification. */
export const toast = {
  success: (msg: string, duration?: number) => _emit("success", msg, duration),
  error:   (msg: string, duration?: number) => _emit("error",   msg, duration ?? 6000),
  warn:    (msg: string, duration?: number) => _emit("warn",    msg, duration),
  info:    (msg: string, duration?: number) => _emit("info",    msg, duration),
};

// ── Individual Toast ──────────────────────────────────────────────────────────

const ICONS: Record<ToastKind, ReactNode> = {
  success: <CheckCircle  className="w-4 h-4 text-success shrink-0" />,
  error:   <XCircle      className="w-4 h-4 text-danger  shrink-0" />,
  warn:    <AlertTriangle className="w-4 h-4 text-warning shrink-0" />,
  info:    <Info          className="w-4 h-4 text-accent  shrink-0" />,
};

const BORDER: Record<ToastKind, string> = {
  success: "border-success/40",
  error:   "border-danger/40",
  warn:    "border-warning/40",
  info:    "border-accent/40",
};

function ToastItem({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: (id: number) => void;
}) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Fade in
    const show = requestAnimationFrame(() => setVisible(true));
    // Auto-dismiss
    const timer = setTimeout(() => setVisible(false), item.duration - 300);
    // Remove after fade-out
    const remove = setTimeout(() => onDismiss(item.id), item.duration);
    return () => {
      cancelAnimationFrame(show);
      clearTimeout(timer);
      clearTimeout(remove);
    };
  }, [item, onDismiss]);

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`
        flex items-start gap-3 px-4 py-3 rounded-lg border
        bg-surface/95 backdrop-blur text-foreground text-sm shadow-xl
        transition-all duration-300
        ${BORDER[item.kind]}
        ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}
      `}
    >
      {ICONS[item.kind]}
      <span className="flex-1 leading-snug">{item.message}</span>
      <button
        onClick={() => onDismiss(item.id)}
        className="ml-1 text-muted hover:text-foreground transition-colors"
        aria-label="Dismiss notification"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

// ── Container ─────────────────────────────────────────────────────────────────

/**
 * Mount this once inside your root component (Dashboard.tsx or App.tsx).
 * Toasts stack in the bottom-right corner.
 */
export function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    const handler: ToastListener = (item) => {
      setItems((prev) => [...prev.slice(-4), item]); // keep max 5
    };
    _listeners.push(handler);
    return () => {
      const idx = _listeners.indexOf(handler);
      if (idx !== -1) _listeners.splice(idx, 1);
    };
  }, []);

  return (
    <div
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80 pointer-events-none"
    >
      {items.map((item) => (
        <div key={item.id} className="pointer-events-auto">
          <ToastItem item={item} onDismiss={dismiss} />
        </div>
      ))}
    </div>
  );
}
