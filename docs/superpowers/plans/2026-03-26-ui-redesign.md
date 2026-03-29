# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 12-tab sidebar with a three-column shell (52px icon rail + packet table center + 320px persistent right chat/analysis panel) per the approved spec.

**Architecture:** The new shell is rendered when `useNewShell: true` in the Zustand store (default true); the old sidebar layout stays in Dashboard.tsx behind `useNewShell: false` for rollback. Three new components (IconRail, RightPanel, AnalysisStrip) are created; existing components (Dashboard, PacketsAndInsights, PacketTable) are modified minimally.

**Tech Stack:** React 18, Zustand, Tailwind CSS, Lucide React, existing api.ts helpers (`sendChatMessage`, `runDeepAnalysis`, `streamNarrative`, `generateInsightStream`, `fetchCurrentCaptureFile`, `buildAnalysisContext`).

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/store/useStore.ts` | Add 4 fields: `activeView`, `rightPanelTab`, `analysisStripExpanded`, `useNewShell` |
| `frontend/src/index.css` | Add 9 Wireshark-style packet row color utility classes |
| `frontend/src/components/IconRail.tsx` | New — 52px left icon rail (5 icons + tooltips) |
| `frontend/src/components/AnalysisStrip.tsx` | New — collapsible deep-analysis summary above chat |
| `frontend/src/components/RightPanel.tsx` | New — 320px right panel: Chat / Quick / Deep sub-tabs + auto-insight trigger |
| `frontend/src/components/PacketTable.tsx` | Add `getRowClass()` applied to each virtual row |
| `frontend/src/components/PacketsAndInsights.tsx` | Strip InsightPanel sidebar; remove auto-insight trigger (moved to RightPanel) |
| `frontend/src/components/Dashboard.tsx` | Add three-column shell conditional on `useNewShell`; wire IconRail + RightPanel |

---

## Task 1: Store additions

**Files:**
- Modify: `frontend/src/store/useStore.ts`

- [ ] **Step 1: Add types + fields to the AppState interface** (after the existing `chatPrefill` group)

```typescript
// ── New Shell navigation (UI Redesign)
type ActiveView = "capture" | "analysis" | "trafficmap" | "protocols";
type RightPanelTab = "chat" | "quick" | "deep";

// In AppState interface:
activeView: ActiveView;
setActiveView: (v: ActiveView) => void;
rightPanelTab: RightPanelTab;
setRightPanelTab: (t: RightPanelTab) => void;
analysisStripExpanded: boolean;
setAnalysisStripExpanded: (v: boolean) => void;
useNewShell: boolean;
setUseNewShell: (v: boolean) => void;
```

Export `ActiveView` and `RightPanelTab` from the file (add to existing exports).

- [ ] **Step 2: Add implementations to the `create()` call** (after `clearChatPrefill`)

```typescript
// New Shell navigation
activeView: "capture",
setActiveView: (v) => set({ activeView: v }),
rightPanelTab: "chat",
setRightPanelTab: (t) => set({ rightPanelTab: t }),
analysisStripExpanded: false,
setAnalysisStripExpanded: (v) => set({ analysisStripExpanded: v }),
useNewShell: true,
setUseNewShell: (v) => set({ useNewShell: v }),
```

- [ ] **Step 3: Verify TypeScript** — run `cd frontend && npx tsc --noEmit`. Expected: 0 errors.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/store/useStore.ts
git commit -m "feat(store): add activeView, rightPanelTab, analysisStripExpanded, useNewShell"
```

---

## Task 2: Packet row color CSS classes

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add row color utility classes** at the end of the `@layer base` block (before closing `}`)

```css
/* ── Wireshark-style packet row colors (dark theme) ─────────────────── */
.row-tcp   { background-color: #1a2535; color: #c8d8f0; }
.row-tls   { background-color: #1e1835; color: #d0c8f0; }
.row-dns   { background-color: #0f2018; color: #c0e8d0; }
.row-http  { background-color: #162030; color: #b8d8e8; }
.row-udp   { background-color: #1a2035; color: #c8c8f0; }
.row-arp   { background-color: #1a1a0f; color: #e8e8b8; }
.row-icmp  { background-color: #1a2020; color: #b8e0e0; }
.row-error { background-color: #2d1515; color: #f4b8b8; }
.row-warn  { background-color: #2a1e10; color: #f4d8b8; }
.row-selected { outline: 2px solid rgb(var(--color-accent)); outline-offset: -2px; }
```

- [ ] **Step 2: Commit**
```bash
git add frontend/src/index.css
git commit -m "feat(styles): add Wireshark-style packet row color classes"
```

---

## Task 3: IconRail component

**Files:**
- Create: `frontend/src/components/IconRail.tsx`

- [ ] **Step 1: Create `IconRail.tsx`**

```tsx
import { Activity, Shield, GitFork, Cpu, Settings } from "lucide-react";
import type { ActiveView } from "../store/useStore";

interface IconRailProps {
  activeView: ActiveView;
  onViewChange: (v: ActiveView) => void;
  onSettingsClick: () => void;
}

interface RailIcon {
  id: ActiveView | "settings";
  icon: typeof Activity;
  label: string;
}

const ICONS: RailIcon[] = [
  { id: "capture",    icon: Activity, label: "Capture"    },
  { id: "analysis",   icon: Shield,   label: "Analysis"   },
  { id: "trafficmap", icon: GitFork,  label: "Traffic Map"},
  { id: "protocols",  icon: Cpu,      label: "Protocols"  },
];

export function IconRail({ activeView, onViewChange, onSettingsClick }: IconRailProps) {
  return (
    <div className="flex flex-col w-[52px] shrink-0 bg-surface border-r border-border h-full">
      {/* Logo mark */}
      <div className="flex items-center justify-center h-10 border-b border-border shrink-0">
        <span className="text-accent font-bold text-xs">NS</span>
      </div>

      {/* View icons */}
      <nav className="flex-1 flex flex-col py-2 gap-1">
        {ICONS.map(({ id, icon: Icon, label }) => {
          const isActive = activeView === id;
          return (
            <button
              key={id}
              title={label}
              aria-label={label}
              onClick={() => onViewChange(id as ActiveView)}
              className={`relative flex items-center justify-center w-full h-10 transition-colors ${
                isActive
                  ? "text-accent bg-surface-hover"
                  : "text-muted hover:text-foreground hover:bg-surface-hover"
              }`}
            >
              {isActive && (
                <span className="absolute left-0 top-1 bottom-1 w-0.5 bg-accent rounded-r" />
              )}
              <Icon className="w-4 h-4" />
            </button>
          );
        })}
      </nav>

      {/* Settings at bottom */}
      <button
        title="Settings"
        aria-label="Settings"
        onClick={onSettingsClick}
        className="flex items-center justify-center h-10 border-t border-border text-muted hover:text-foreground hover:bg-surface-hover transition-colors shrink-0"
      >
        <Settings className="w-4 h-4" />
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript** — `npx tsc --noEmit`. Expected: 0 errors.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/IconRail.tsx
git commit -m "feat(ui): add IconRail component with 4 view icons + settings"
```

---

## Task 4: PacketTable row coloring

**Files:**
- Modify: `frontend/src/components/PacketTable.tsx`

- [ ] **Step 1: Add `getRowClass` function** immediately before the `PacketTable` component (after the `PROTOCOL_BG` constant block)

```typescript
function getRowClass(pkt: Packet): string {
  const d = pkt.details ?? {};
  if (
    d["tcp.analysis.retransmission"] === "1" ||
    d["tcp.analysis.out_of_order"] === "1" ||
    (pkt.protocol === "TCP" && pkt.info?.includes("[RST]"))
  ) return "row-error";
  if (
    d["tcp.analysis.zero_window"] === "1" ||
    d["tcp.analysis.duplicate_ack"] === "1"
  ) return "row-warn";
  switch (pkt.protocol) {
    case "TLSv1.2": case "TLSv1.3": case "SSL": return "row-tls";
    case "DNS": case "MDNS": case "LLMNR": return "row-dns";
    case "HTTP": case "HTTP2": return "row-http";
    case "UDP": return "row-udp";
    case "ARP": return "row-arp";
    case "ICMP": case "ICMPv6": return "row-icmp";
    default: return "row-tcp";
  }
}
```

- [ ] **Step 2: Apply `getRowClass` to the virtual row container**

Find the virtual row `<div>` that currently sets its className to something like:
```tsx
className={`flex text-xs border-b border-border/50 cursor-pointer ... ${PROTOCOL_BG[proto] || ""} ...`}
```
Add `getRowClass(pkt)` to the className, and add `row-selected` when the row is selected:
```tsx
className={`flex text-xs border-b border-border/50 cursor-pointer transition-colors ${getRowClass(pkt)} ${isSelected ? "row-selected" : ""}`}
```
Remove the `PROTOCOL_BG` lookup from this className (it's superseded by the new row classes).

- [ ] **Step 3: Verify TypeScript** — `npx tsc --noEmit`. Expected: 0 errors.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/components/PacketTable.tsx
git commit -m "feat(packets): add Wireshark-style row coloring via getRowClass()"
```

---

## Task 5: Simplify PacketsAndInsights

**Files:**
- Modify: `frontend/src/components/PacketsAndInsights.tsx`

The auto-insight trigger moves to `RightPanel.tsx` (Task 7). This component becomes a thin wrapper.

- [ ] **Step 1: Replace the entire file content**

```tsx
import { PacketTable } from "./PacketTable";

export function PacketsAndInsights() {
  return (
    <div className="flex-1 h-full overflow-hidden">
      <PacketTable />
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript** — `npx tsc --noEmit`. Expected: 0 errors.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/PacketsAndInsights.tsx
git commit -m "refactor(packets): strip InsightPanel sidebar from PacketsAndInsights"
```

---

## Task 6: AnalysisStrip component

**Files:**
- Create: `frontend/src/components/AnalysisStrip.tsx`

Shown above the chat thread when `rightPanelTab === "chat"` and `analysisReport !== null`. Collapses to a header + metric pills row; expands to full MetricCards.

- [ ] **Step 1: Create `AnalysisStrip.tsx`**

```tsx
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { ChevronDown, ChevronRight, CheckCircle } from "lucide-react";

function formatAge(ts: number): string {
  const secs = Math.floor((Date.now() / 1000) - ts);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

interface PillProps {
  label: string;
  color: string;
  onClick: () => void;
}
function Pill({ label, color, onClick }: PillProps) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-0.5 rounded text-[10px] font-medium transition-opacity hover:opacity-80 ${color}`}
    >
      {label}
    </button>
  );
}

export function AnalysisStrip() {
  const { analysisReport, analysisStripExpanded, setAnalysisStripExpanded, setChatPrefill } =
    useStore(useShallow((s) => ({
      analysisReport: s.analysisReport,
      analysisStripExpanded: s.analysisStripExpanded,
      setAnalysisStripExpanded: s.setAnalysisStripExpanded,
      setChatPrefill: s.setChatPrefill,
    })));

  if (!analysisReport) return null;

  const { tcp_health, latency } = analysisReport;
  const ageTs = (analysisReport as any)._ts ?? Date.now() / 1000;

  const pills = [
    { label: `${tcp_health.retransmissions} retransmit`, color: "bg-red-900/60 text-red-300",    q: "Why are there so many retransmissions?" },
    { label: `${tcp_health.zero_windows} zero-win`,     color: "bg-amber-900/60 text-amber-300", q: "What is causing zero window events?" },
    { label: `${latency.aggregate.bottleneck} bottleneck`, color: "bg-purple-900/60 text-purple-300", q: `The ${latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?` },
    { label: `RTT ${tcp_health.rtt_avg_ms}ms`,          color: "bg-green-900/60 text-green-300", q: "What is the round-trip time telling us?" },
    { label: `${tcp_health.rsts} RSTs`,                 color: "bg-blue-900/60 text-blue-300",   q: "Why are there TCP RST packets?" },
  ];

  return (
    <div className="border-b border-border bg-surface shrink-0">
      {/* Header row */}
      <button
        onClick={() => setAnalysisStripExpanded(!analysisStripExpanded)}
        className="flex items-center gap-2 w-full px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors"
      >
        <CheckCircle className="w-3.5 h-3.5 text-success shrink-0" />
        <span className="text-foreground font-medium">Deep Analysis</span>
        <span className="text-muted">· {formatAge(ageTs)}</span>
        <span className="ml-auto text-muted">
          {analysisStripExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </span>
      </button>

      {/* Collapsed: pills */}
      {!analysisStripExpanded && (
        <div className="flex flex-wrap gap-1 px-3 pb-2">
          {pills.map((p) => (
            <Pill key={p.label} label={p.label} color={p.color} onClick={() => setChatPrefill(p.q)} />
          ))}
        </div>
      )}

      {/* Expanded: redirect to Deep tab (MetricCards live there to avoid duplication).
          The spec calls for full MetricCards here, but since DeepTab already contains
          all MetricCards JSX, we avoid duplicating it. A future follow-up can extract
          <MetricCards> into a shared component and render it in both places. */}
      {analysisStripExpanded && (
        <div className="px-3 pb-3 text-xs text-muted">
          Full report available in the{" "}
          <button
            onClick={() => { setAnalysisStripExpanded(false); useStore.getState().setRightPanelTab("deep"); }}
            className="text-accent hover:underline"
          >
            Deep tab
          </button>.{" "}
          <button
            onClick={() => setAnalysisStripExpanded(false)}
            className="text-muted hover:underline"
          >
            Collapse
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript** — `npx tsc --noEmit`. Expected: 0 errors.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/AnalysisStrip.tsx
git commit -m "feat(ui): add AnalysisStrip component with metric pills"
```

---

## Task 7: RightPanel component

**Files:**
- Create: `frontend/src/components/RightPanel.tsx`

This is the main new component. It contains: sub-tab header (Chat/Quick/Deep), AnalysisStrip (chat tab only), chat thread + input (chat tab), Quick analysis runner, Deep analysis runner, auto-insight trigger (moved from PacketsAndInsights), suggested prompt chips.

- [ ] **Step 1: Create `RightPanel.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import {
  sendChatMessage,
  generateInsight,
  generateInsightStream,
  fetchCurrentCaptureFile,
  runDeepAnalysis,
  streamNarrative,
  buildAnalysisContext,
} from "../lib/api";
import { MarkdownContent } from "./MarkdownContent";
import { AnalysisStrip } from "./AnalysisStrip";
import { Zap, Microscope, MessageSquare, Send, Loader2, Paperclip } from "lucide-react";
import type { DeepAnalysisReport } from "../store/useStore";

// ── Suggested prompt chips ────────────────────────────────────────────────────

const STATIC_CHIPS = ["Follow stream 0", "Top talkers?", "Show retransmissions"];

function getChipsFromReport(report: DeepAnalysisReport | null): string[] {
  if (!report) return STATIC_CHIPS;
  const { tcp_health, latency, io_timeline } = report;
  const burst = io_timeline.find((b) => b.burst);
  return [
    "Why are there so many retransmissions?",
    `The ${latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?`,
    "Walk me through stream 0",
    burst
      ? `What caused the burst at t=${burst.t}s?`
      : "Describe the traffic pattern over time.",
  ];
}

// ── Chat thread ───────────────────────────────────────────────────────────────

function ChatThread() {
  const { chatMessages, isChatLoading, analysisReport, analysisContext, chatPrefill, clearChatPrefill,
          addChatMessage, setChatLoading, clearChat, setChatPrefill } =
    useStore(useShallow((s) => ({
      chatMessages: s.chatMessages,
      isChatLoading: s.isChatLoading,
      analysisReport: s.analysisReport,
      analysisContext: s.analysisContext,
      chatPrefill: s.chatPrefill,
      clearChatPrefill: s.clearChatPrefill,
      addChatMessage: s.addChatMessage,
      setChatLoading: s.setChatLoading,
      clearChat: s.clearChat,
      setChatPrefill: s.setChatPrefill,
    })));

  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Consume chatPrefill (set by "Ask in chat →" buttons elsewhere)
  useEffect(() => {
    if (chatPrefill) {
      setInput(chatPrefill);
      clearChatPrefill();
      textareaRef.current?.focus();
    }
  }, [chatPrefill, clearChatPrefill]);

  const send = async (text: string) => {
    const msg = text.trim();
    if (!msg || isChatLoading) return;
    setInput("");
    addChatMessage({ id: crypto.randomUUID(), role: "user", content: msg, timestamp: Date.now() / 1000 });
    setChatLoading(true);
    try {
      const context = analysisContext || undefined;
      const reply = await sendChatMessage(msg, context);
      addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: reply, timestamp: Date.now() / 1000 });
    } catch (e: any) {
      addChatMessage({ id: crypto.randomUUID(), role: "assistant", content: `Error: ${e?.message ?? "Failed to get response"}`, timestamp: Date.now() / 1000 });
    } finally {
      setChatLoading(false);
    }
  };

  const chips = getChipsFromReport(analysisReport);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* AnalysisStrip — only when analysisReport is set */}
      <AnalysisStrip />

      {/* Message thread */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {chatMessages.length === 0 && (
          <div className="text-center text-muted text-xs py-8">
            Ask anything about the captured traffic.
          </div>
        )}
        {chatMessages.map((msg) => (
          <div key={msg.id} className={`text-xs ${msg.role === "user" ? "flex justify-end" : ""}`}>
            {msg.role === "assistant" ? (
              <div className="bg-[#111827] border-l-2 border-accent rounded px-3 py-2">
                <div className="text-[10px] text-muted font-mono mb-1">⬡ NETSCOPE</div>
                <MarkdownContent>{msg.content}</MarkdownContent>
              </div>
            ) : (
              <div className="bg-accent/20 text-foreground rounded px-3 py-2 max-w-[85%]">
                {msg.content}
              </div>
            )}
          </div>
        ))}
        {isChatLoading && (
          <div className="flex items-center gap-1.5 text-muted text-xs">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Prompt chips */}
      <div className="px-3 py-1 flex flex-wrap gap-1 border-t border-border shrink-0">
        {chips.map((chip) => (
          <button
            key={chip}
            onClick={() => setChatPrefill(chip)}
            className="px-2 py-0.5 bg-surface border border-border rounded text-[10px] text-muted hover:text-foreground hover:border-accent transition-colors"
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Input area */}
      <div className="px-3 py-2 border-t border-border shrink-0">
        <div className="flex items-end gap-1.5">
          <button
            title="Upload PCAP"
            aria-label="Upload PCAP"
            onClick={() => fileInputRef.current?.click()}
            className="text-muted hover:text-foreground transition-colors shrink-0 pb-1"
          >
            <Paperclip className="w-3.5 h-3.5" />
          </button>
          <input ref={fileInputRef} type="file" accept=".pcap,.pcapng" className="hidden" />
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
            }}
            placeholder="Ask about the traffic…"
            rows={1}
            className="flex-1 bg-surface border border-border rounded px-2 py-1.5 text-xs text-foreground placeholder-muted resize-none focus:outline-none focus:border-accent"
            style={{ maxHeight: "5rem", overflowY: "auto" }}
          />
          <button
            onClick={() => send(input)}
            disabled={isChatLoading || !input.trim()}
            aria-label="Send"
            className="text-accent hover:text-accent-muted disabled:opacity-30 transition-colors shrink-0 pb-1"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Quick tab ─────────────────────────────────────────────────────────────────

function QuickTab() {
  const [result, setResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { analysisContext, addChatMessage, setRightPanelTab } = useStore(
    useShallow((s) => ({
      analysisContext: s.analysisContext,
      addChatMessage: s.addChatMessage,
      setRightPanelTab: s.setRightPanelTab,
    }))
  );

  const run = async () => {
    setLoading(true);
    setResult("");
    try {
      let full = "";
      await generateInsightStream("quick", analysisContext || undefined, (token) => {
        full += token;
        setResult(full);
      });
    } catch (e: any) {
      setResult(`Error: ${e?.message ?? "Failed"}`);
    } finally {
      setLoading(false);
    }
  };

  if (!result && !loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <button
          onClick={run}
          className="flex items-center gap-2 px-4 py-2 bg-accent text-white rounded text-sm font-medium hover:bg-accent-emphasis transition-colors"
        >
          <Zap className="w-4 h-4" /> Run Quick Analysis
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border shrink-0">
        <span className="text-xs text-muted">Quick Analysis</span>
        <button onClick={run} disabled={loading} className="text-xs text-accent hover:underline disabled:opacity-50">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Re-run"}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs">
        {result && <MarkdownContent>{result}</MarkdownContent>}
        {loading && !result && <Loader2 className="w-4 h-4 animate-spin text-muted mt-4 mx-auto" />}
      </div>
    </div>
  );
}

// ── Deep tab ──────────────────────────────────────────────────────────────────

function DeepTab() {
  const [loading, setLoading] = useState(false);
  const [narrative, setNarrative] = useState<string | null>(null);
  const { analysisReport, setAnalysisReport, setChatPrefill } = useStore(
    useShallow((s) => ({
      analysisReport: s.analysisReport,
      setAnalysisReport: s.setAnalysisReport,
      setChatPrefill: s.setChatPrefill,
    }))
  );

  const run = async () => {
    setLoading(true);
    setNarrative(null);
    try {
      const captureFile = await fetchCurrentCaptureFile();
      const report: DeepAnalysisReport = await runDeepAnalysis(captureFile);
      const ctx = buildAnalysisContext(report);
      setAnalysisReport(report, ctx);
      let full = "";
      await streamNarrative(captureFile, (token) => {
        full += token;
        setNarrative(full);
      });
    } catch (e: any) {
      setNarrative(`Error: ${e?.message ?? "Deep analysis failed"}`);
    } finally {
      setLoading(false);
    }
  };

  if (!analysisReport && !loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <button
          onClick={run}
          className="flex items-center gap-2 px-4 py-2 bg-purple/20 text-purple border border-purple/30 rounded text-sm font-medium hover:bg-purple/30 transition-colors"
        >
          <Microscope className="w-4 h-4" /> Run Deep Analysis
        </button>
      </div>
    );
  }

  if (loading && !analysisReport) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-muted text-sm">
        <Loader2 className="w-4 h-4 animate-spin" /> Running deep analysis…
      </div>
    );
  }

  const r = analysisReport!;
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border shrink-0">
        <span className="text-xs text-muted">Deep Analysis</span>
        <button onClick={run} disabled={loading} className="text-xs text-accent hover:underline disabled:opacity-50">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Re-run"}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs space-y-3">
        {/* TCP Health */}
        <div className="border border-border rounded p-2">
          <div className="font-medium text-foreground mb-1">TCP Health</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-muted">
            <span>Retransmissions: <b className="text-foreground">{r.tcp_health.retransmissions}</b></span>
            <span>Zero windows: <b className="text-foreground">{r.tcp_health.zero_windows}</b></span>
            <span>Out-of-order: <b className="text-foreground">{r.tcp_health.out_of_order}</b></span>
            <span>RSTs: <b className="text-foreground">{r.tcp_health.rsts}</b></span>
            <span>RTT avg: <b className="text-foreground">{r.tcp_health.rtt_avg_ms}ms</b></span>
          </div>
          <button onClick={() => setChatPrefill("Why are there so many retransmissions?")}
            className="mt-1 text-[10px] text-blue-400 hover:underline">Ask in chat →</button>
        </div>
        {/* Latency */}
        <div className="border border-border rounded p-2">
          <div className="font-medium text-foreground mb-1">Latency</div>
          <div className="text-muted">
            Bottleneck: <b className="text-foreground">{r.latency.aggregate.bottleneck}</b> ·
            Network RTT: <b className="text-foreground">{r.latency.aggregate.network_rtt_ms}ms</b> ·
            Server: <b className="text-foreground">{r.latency.aggregate.server_ms}ms</b>
          </div>
          <button onClick={() => setChatPrefill(`The ${r.latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?`)}
            className="mt-1 text-[10px] text-blue-400 hover:underline">Ask in chat →</button>
        </div>
        {/* Streams */}
        <div className="border border-border rounded p-2">
          <div className="font-medium text-foreground mb-1">Streams ({r.streams.length})</div>
          {r.streams.slice(0, 5).map((s) => (
            <div key={s.stream_id} className="text-muted text-[10px]">
              [{s.stream_id}] {s.src} → {s.dst} · {s.protocol} · {s.packets}pkts
            </div>
          ))}
          <button onClick={() => setChatPrefill("Walk me through stream 0")}
            className="mt-1 text-[10px] text-blue-400 hover:underline">Ask in chat →</button>
        </div>
        {/* Expert Info */}
        {r.expert_info.available && r.expert_info.counts && (
          <div className="border border-border rounded p-2">
            <div className="font-medium text-foreground mb-1">Expert Info</div>
            <div className="text-muted">
              Errors: {r.expert_info.counts.error} · Warnings: {r.expert_info.counts.warning} · Notes: {r.expert_info.counts.note}
            </div>
            <button onClick={() => setChatPrefill("What do the TCP warnings mean?")}
              className="mt-1 text-[10px] text-blue-400 hover:underline">Ask in chat →</button>
          </div>
        )}
        {/* Narrative */}
        {narrative && (
          <div className="border border-border rounded p-2">
            <div className="font-medium text-foreground mb-1">Narrative</div>
            <MarkdownContent>{narrative}</MarkdownContent>
          </div>
        )}
        {loading && (
          <div className="flex items-center gap-1.5 text-muted text-xs">
            <Loader2 className="w-3 h-3 animate-spin" /> Generating narrative…
          </div>
        )}
      </div>
    </div>
  );
}

// ── RightPanel ────────────────────────────────────────────────────────────────

export function RightPanel() {
  const { rightPanelTab, setRightPanelTab, isCapturing, packets, addChatMessage } =
    useStore(useShallow((s) => ({
      rightPanelTab: s.rightPanelTab,
      setRightPanelTab: s.setRightPanelTab,
      isCapturing: s.isCapturing,
      packets: s.packets,
      addChatMessage: s.addChatMessage,
    })));

  // Auto-insight trigger: fires when capture ends and packets exist
  const wasCapturingRef = useRef(isCapturing);
  useEffect(() => {
    const wasCap = wasCapturingRef.current;
    wasCapturingRef.current = isCapturing;
    if (wasCap && !isCapturing && packets.length > 0) {
      generateInsight("general")
          .then((text) => {
            addChatMessage({
              id: crypto.randomUUID(),
              role: "assistant",
              content: text,
              timestamp: Date.now() / 1000,
            });
          })
          .catch(() => {});
    }
  }, [isCapturing]);

  const tabs = [
    { id: "chat" as const,  icon: MessageSquare, label: "Chat"  },
    { id: "quick" as const, icon: Zap,           label: "Quick" },
    { id: "deep"  as const, icon: Microscope,    label: "Deep"  },
  ];

  return (
    <div className="flex flex-col w-[320px] shrink-0 border-l border-border bg-background h-full overflow-hidden">
      {/* Sub-tab header */}
      <div className="flex border-b border-border shrink-0">
        {tabs.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => setRightPanelTab(id)}
            className={`flex items-center gap-1.5 flex-1 justify-center py-2 text-xs font-medium transition-colors ${
              rightPanelTab === id
                ? "text-accent border-b-2 border-accent"
                : "text-muted hover:text-foreground"
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {rightPanelTab === "chat"  && <ChatThread />}
        {rightPanelTab === "quick" && <QuickTab />}
        {rightPanelTab === "deep"  && <DeepTab />}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript** — `npx tsc --noEmit`. Expected: 0 errors (fix any that arise).

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/RightPanel.tsx
git commit -m "feat(ui): add RightPanel with Chat/Quick/Deep tabs and auto-insight trigger"
```

---

## Task 8: Dashboard three-column shell

**Files:**
- Modify: `frontend/src/components/Dashboard.tsx`

The new shell is rendered when `useNewShell === true`. The old sidebar layout renders when `useNewShell === false`.

- [ ] **Step 1: Add imports** at the top of `Dashboard.tsx`

Add to existing imports:
```tsx
import { IconRail } from "./IconRail";
import { RightPanel } from "./RightPanel";
import type { ActiveView } from "../store/useStore";
```

- [ ] **Step 2: Pull new store fields** in the `useStore(useShallow(...))` call

Add to the destructured fields:
```tsx
activeView, setActiveView, useNewShell,
```

- [ ] **Step 3: Add Settings flyout state** inside the component:
```tsx
const [settingsOpen, setSettingsOpen] = useState(false);
```

- [ ] **Step 4: Add the new shell JSX** — wrap the `return` statement with a conditional

Before the existing `return (`, add:

```tsx
if (useNewShell) {
  const CENTER_VIEWS: Record<ActiveView, React.ReactNode> = {
    capture:    <PacketsAndInsights />,
    analysis:   <ExpertTools />,
    trafficmap: <TrafficMap />,
    protocols:  <ModbusPanel />,
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <ToastContainer />

      {/* Settings flyout stub */}
      {settingsOpen && (
        <div className="absolute inset-0 z-50 flex">
          <div className="w-64 bg-surface border-r border-border flex flex-col p-4">
            <div className="text-foreground font-semibold mb-2">Settings</div>
            <div className="text-muted text-sm flex-1">Settings coming soon.</div>
            <button onClick={() => setSettingsOpen(false)} className="text-accent text-sm hover:underline">Close</button>
          </div>
          <div className="flex-1 bg-black/40" onClick={() => setSettingsOpen(false)} />
        </div>
      )}

      {/* Icon rail */}
      <IconRail
        activeView={activeView}
        onViewChange={setActiveView}
        onSettingsClick={() => setSettingsOpen(true)}
      />

      {/* Center column */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar.
            NOTE: The spec (§2.3) describes a full capture toolbar
            (Start/Stop/Interface/Import/Captures/LLM/Settings). Building that toolbar is
            deferred to a follow-up plan (capture controls aren't yet extracted from
            PacketTable). For this iteration we keep the existing header widgets. */}
        <header className="flex flex-wrap items-center gap-2 px-3 py-1.5 bg-surface border-b border-border shrink-0">
          <ContextPie />
          <TokenCounter />
          <div className="ml-auto flex items-center gap-2">
            <UpdateChecker onUpdateFailed={onUpdateFailed} />
            <LLMConfig />
          </div>
        </header>

        {/* Filter bar — only on capture view */}
        {activeView === "capture" && (
          <div className="shrink-0 border-b border-border">
            <FilterBar />
          </div>
        )}

        {/* Center view */}
        <main className="flex-1 overflow-hidden">
          {CENTER_VIEWS[activeView]}
        </main>
      </div>

      {/* Right panel — always visible */}
      <RightPanel />
    </div>
  );
}
```

The existing `return (` block below this remains unchanged (it renders the old sidebar layout when `useNewShell === false`).

- [ ] **Step 5: Verify TypeScript** — `npx tsc --noEmit`. Expected: 0 errors.

- [ ] **Step 6: Verify dev build starts** — `cd frontend && npm run dev`. Open the app. Should see three-column layout.

- [ ] **Step 7: Commit**
```bash
git add frontend/src/components/Dashboard.tsx
git commit -m "feat(ui): three-column shell with icon rail and persistent right panel"
```

---

## Task 9: Final verification

- [ ] **Step 1: Full TypeScript check** — `cd frontend && npx tsc --noEmit`. Must be 0 errors.

- [ ] **Step 2: Build check** — `npm run build`. Must succeed with no errors.

- [ ] **Step 3: Smoke test (manual)** — Run the app and verify:
  1. Three-column layout renders by default
  2. Icon rail switches views (capture → packets table, analysis → ExpertTools, trafficmap → TrafficMap, protocols → ModbusPanel)
  3. Right panel always visible; Chat/Quick/Deep sub-tabs switch correctly
  4. PacketTable rows show color coding (requires a loaded pcap)
  5. AnalysisStrip appears above chat after a Deep analysis run
  6. Prompt chips populate the input when clicked
  7. Old sidebar still works with `useNewShell: false` (set in browser console: `window.__store?.setUseNewShell(false)`)

- [ ] **Step 4: Commit verification result**
```bash
git add frontend/src/components/Dashboard.tsx frontend/src/components/RightPanel.tsx \
        frontend/src/components/AnalysisStrip.tsx frontend/src/components/IconRail.tsx \
        frontend/src/components/PacketTable.tsx frontend/src/components/PacketsAndInsights.tsx \
        frontend/src/store/useStore.ts frontend/src/index.css
git commit -m "feat: complete UI redesign — three-column shell, icon rail, RightPanel"
```
