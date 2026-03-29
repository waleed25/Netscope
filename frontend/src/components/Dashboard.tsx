import { useState, useEffect, useRef, lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { useFeature } from "../features";
import { RightPanel } from "./RightPanel";
import { PacketsTab } from "./PacketsTab";
import { FilterBar } from "./FilterBar";
import { LLMConfig } from "./LLMConfig";
import { TokenCounter } from "./TokenCounter";
import { NetworkTools } from "./NetworkTools";
import { ContextPie } from "./ContextPie";
import { UpdateChecker } from "./UpdateChecker";
import {
  Activity,
  Terminal, Shield, Cpu, BookOpen, HeartPulse, Network,
  PanelLeftClose, PanelLeftOpen, Radio,
  Sun, Moon, GitFork, Clock, Wand2, FileText
} from "lucide-react";
import { ExpertTools } from "./ExpertTools";
import { StatusPanel } from "./StatusPanel";
import { ToastContainer } from "./Toast";

// Optional module panels — lazy-loaded so they don't bloat the initial bundle
const TrafficMap    = lazy(() => import("./TrafficMap").then(m => ({ default: m.TrafficMap })));
const ModbusPanel   = lazy(() => import("./ModbusPanel").then(m => ({ default: m.ModbusPanel })));
const RAGPanel      = lazy(() => import("./RAGPanel").then(m => ({ default: m.RAGPanel })));
const ChannelsPanel = lazy(() => import("./ChannelsPanel").then(m => ({ default: m.ChannelsPanel })));
const SchedulerPanel = lazy(() => import("./SchedulerPanel").then(m => ({ default: m.SchedulerPanel })));
const WizardPanel    = lazy(() => import("./WizardPanel"));
const ReportViewer   = lazy(() => import("./ReportViewer"));

const LazyFallback = () => <div className="p-4 text-muted">Loading...</div>;

interface DashboardProps {
  onUpdateFailed?: (reason: string) => void;
}

type TabId = "packets" | "tools" | "expert" | "modbus" | "rag" | "status" | "channels" | "trafficmap" | "scheduler" | "wizards" | "reports";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof Activity;
}

/** Build nav sections, filtering out tabs whose feature module is disabled. */
function useNavSections(): { heading: string; tabs: TabDef[] }[] {
  const hasModbus    = useFeature('modbus');
  const hasRAG       = useFeature('rag');
  const hasTopology  = useFeature('topology');
  const hasScheduler = useFeature('scheduler');
  const hasExpert    = useFeature('expert-analysis');
  const hasChannels  = useFeature('channels');

  return [
    {
      heading: "Capture",
      tabs: [
        { id: "packets", label: "Packets", icon: Activity },
      ],
    },
    {
      heading: "Tools",
      tabs: [
        { id: "tools",      label: "Net Tools",   icon: Terminal },
        ...(hasExpert   ? [{ id: "expert"     as TabId, label: "Analysis",    icon: Shield  }] : []),
        ...(hasTopology ? [{ id: "trafficmap"  as TabId, label: "Traffic Map", icon: GitFork }] : []),
        ...(hasModbus   ? [{ id: "modbus"      as TabId, label: "Modbus",      icon: Cpu     }] : []),
      ],
    },
    {
      heading: "System",
      tabs: [
        ...(hasRAG       ? [{ id: "rag"       as TabId, label: "Knowledge Base", icon: BookOpen   }] : []),
        ...(hasChannels  ? [{ id: "channels"  as TabId, label: "Channels",       icon: Radio      }] : []),
        { id: "status",   label: "Status",      icon: HeartPulse },
        ...(hasScheduler ? [{ id: "scheduler" as TabId, label: "Scheduler",      icon: Clock      }] : []),
        { id: "wizards",  label: "Wizards",     icon: Wand2      },
        { id: "reports",  label: "Reports",     icon: FileText   },
      ],
    },
  ];
}

/** Tabs that use capture controls (FilterBar is now inside PacketsTab for "packets") */
const FILTER_TABS = new Set<TabId>(["expert"]);

/**
 * Tab content — all panels stay mounted to preserve WebSocket connections and
 * in-progress captures across tab switches. Inactive panels are hidden via CSS.
 * Lazy panels are only initialised on first visit (Suspense loads once, then
 * the component stays alive in the hidden div).
 */
function TabContent({ activeTab }: { activeTab: TabId }): ReactNode {
  // Track which lazy tabs have been visited so we don't mount them until needed
  const [visited, setVisited] = useState<Set<TabId>>(() => new Set([activeTab]));
  useEffect(() => {
    setVisited((prev) => {
      if (prev.has(activeTab)) return prev;
      const next = new Set(prev);
      next.add(activeTab);
      return next;
    });
  }, [activeTab]);

  const show = (id: TabId) => ({ style: { display: activeTab === id ? undefined : "none" } as React.CSSProperties });

  return (
    <>
      {/* Core panels — always mounted */}
      <div {...show("packets")}  className="h-full"><PacketsTab /></div>
      <div {...show("tools")}    className="h-full"><NetworkTools /></div>
      <div {...show("expert")}   className="h-full"><ExpertTools /></div>
      <div {...show("status")}   className="h-full"><StatusPanel /></div>

      {/* Lazy panels — mounted on first visit, hidden thereafter */}
      <div {...show("trafficmap")} className="h-full">
        {visited.has("trafficmap") && <Suspense fallback={<LazyFallback />}><TrafficMap /></Suspense>}
      </div>
      <div {...show("modbus")} className="h-full">
        {visited.has("modbus") && <Suspense fallback={<LazyFallback />}><ModbusPanel /></Suspense>}
      </div>
      <div {...show("rag")} className="h-full">
        {visited.has("rag") && <Suspense fallback={<LazyFallback />}><RAGPanel /></Suspense>}
      </div>
      <div {...show("channels")} className="h-full">
        {visited.has("channels") && <Suspense fallback={<LazyFallback />}><ChannelsPanel /></Suspense>}
      </div>
      <div {...show("scheduler")} className="h-full">
        {visited.has("scheduler") && <Suspense fallback={<LazyFallback />}><SchedulerPanel /></Suspense>}
      </div>
      <div {...show("wizards")} className="h-full">
        {visited.has("wizards") && <Suspense fallback={<LazyFallback />}><WizardPanel /></Suspense>}
      </div>
      <div {...show("reports")} className="h-full">
        {visited.has("reports") && <Suspense fallback={<LazyFallback />}><ReportViewer /></Suspense>}
      </div>
    </>
  );
}

export function Dashboard({ onUpdateFailed }: DashboardProps) {
  const { activeTab, setActiveTab, isCapturing, theme, toggleTheme } = useStore(
    useShallow((s) => ({
      activeTab: s.activeTab,
      setActiveTab: s.setActiveTab,
      isCapturing: s.isCapturing,
      theme: s.theme,
      toggleTheme: s.toggleTheme,
    }))
  );
  const [collapsed, setCollapsed] = useState(false);
  const navSections = useNavSections();

  // Right panel resize
  const [panelWidth, setPanelWidth] = useState(320);
  const isResizing = useRef(false);

  const onResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    const startX = e.clientX;
    const startWidth = panelWidth;

    const onMove = (ev: MouseEvent) => {
      if (!isResizing.current) return;
      const delta = startX - ev.clientX;
      setPanelWidth(Math.min(640, Math.max(240, startWidth + delta)));
    };
    const onUp = () => {
      isResizing.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        // Focus chat box (Ctrl+K)
        if (e.key.toLowerCase() === "k") {
          e.preventDefault();
          document.getElementById("chat-input")?.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <ToastContainer />

      {/* ── Left Sidebar ── */}
      <aside className={`flex flex-col shrink-0 bg-surface border-r border-border transition-[width] duration-200 ${collapsed ? "w-12" : "w-48"}`}>
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-3 py-3 border-b border-border">
          <Network className="w-5 h-5 text-accent shrink-0" />
          {!collapsed && (
            <div className="leading-tight min-w-0">
              <div className="text-foreground font-semibold text-sm tracking-wide">NetScope</div>
              <div className="text-muted text-[10px] tracking-widest uppercase">Network Analyzer</div>
            </div>
          )}
        </div>

        {/* Nav items */}
        <nav role="tablist" aria-label="Main navigation" className="flex-1 overflow-y-auto py-1">
          {navSections.map(({ heading, tabs }) => (
            <div key={heading}>
              {!collapsed && (
                <div className="px-4 pt-3 pb-1 text-[10px] font-semibold text-muted uppercase tracking-wider">
                  {heading}
                </div>
              )}
              {collapsed && <div className="my-1 mx-2 border-t border-border" />}
              {tabs.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={activeTab === id}
                  aria-label={label}
                  onClick={() => setActiveTab(id)}
                  title={collapsed ? label : undefined}
                  className={`flex items-center gap-2.5 w-full text-sm transition-colors ${
                    collapsed ? "justify-center px-0 py-2.5" : "px-4 py-2"
                  } ${
                    activeTab === id
                      ? "bg-surface-hover text-accent border-r-2 border-accent"
                      : "text-muted hover:bg-surface-hover hover:text-foreground"
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {!collapsed && label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Live indicator */}
        {isCapturing && (
          <div className="shrink-0 px-3 py-2 border-t border-border flex items-center gap-1.5 text-success text-xs font-medium" role="status" aria-live="polite">
            <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
            {!collapsed && "CAPTURING"}
          </div>
        )}

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className="shrink-0 flex items-center justify-center py-2 border-t border-border text-muted hover:text-foreground transition-colors"
        >
          {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="shrink-0 flex items-center justify-center py-2 border-t border-border text-muted hover:text-foreground transition-colors"
        >
          {collapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
      </aside>

      {/* ── Center: header + filter + content ── */}
      <div className="flex flex-col flex-1 min-w-0">

        {/* Top bar: LLM status, token stats, misc controls */}
        <header className="flex flex-wrap items-center gap-2 px-3 py-1.5 bg-surface border-b border-border shrink-0">
          <ContextPie />
          <TokenCounter />
          <div className="ml-auto flex items-center gap-2">
            <UpdateChecker onUpdateFailed={onUpdateFailed} />
            <LLMConfig />
          </div>
        </header>

        {/* Filter bar — only on capture-related tabs */}
        {FILTER_TABS.has(activeTab) && (
          <div className="shrink-0 border-b border-border">
            <FilterBar />
          </div>
        )}

        {/* Main content */}
        <main className="flex-1 overflow-hidden" role="tabpanel">
          <TabContent activeTab={activeTab} />
        </main>
      </div>

      {/* ── Right Panel — always visible, resizable ── */}
      <div
        className="shrink-0 bg-surface border-l border-border flex flex-col overflow-hidden relative"
        style={{ width: panelWidth }}
      >
        {/* Drag handle */}
        <div
          onMouseDown={onResizeMouseDown}
          className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-accent/40 transition-colors z-10"
          title="Drag to resize"
        />
        <RightPanel />
      </div>
    </div>
  );
}
