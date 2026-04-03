import { useState, useEffect, lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { useFeature } from "../features";
import { RightPanel } from "./RightPanel";
import { PacketsTab } from "./PacketsTab";
import { NetworkTools } from "./NetworkTools";
import { ExpertTools } from "./ExpertTools";
import { StatusPanel } from "./StatusPanel";
import { ToastContainer } from "./Toast";
import {
  Activity,
  Terminal,
  Shield,
  Cpu,
  BookOpen,
  HeartPulse,
  Network,
  Radio,
  GitFork,
  Clock,
  MessageSquare,
  Sun,
  Moon,
  X,
} from "lucide-react";

import { PanelSkeleton } from "./Skeleton";

// Optional module panels — lazy-loaded so they don't bloat the initial bundle
const TrafficMap    = lazy(() => import("./TrafficMap").then(m => ({ default: m.TrafficMap })));
const ModbusPanel   = lazy(() => import("./ModbusPanel").then(m => ({ default: m.ModbusPanel })));
const RAGPanel      = lazy(() => import("./RAGPanel").then(m => ({ default: m.RAGPanel })));
const ChannelsPanel = lazy(() => import("./ChannelsPanel").then(m => ({ default: m.ChannelsPanel })));
const SchedulerPanel = lazy(() => import("./SchedulerPanel").then(m => ({ default: m.SchedulerPanel })));
const WizardPanel    = lazy(() => import("./WizardPanel"));
const ReportViewer   = lazy(() => import("./ReportViewer"));

const LazyFallback = () => <PanelSkeleton />;

interface DashboardProps {
  onUpdateFailed?: (reason: string) => void;
}

type TabId =
  | "packets"
  | "tools"
  | "expert"
  | "modbus"
  | "rag"
  | "status"
  | "channels"
  | "trafficmap"
  | "scheduler"
  | "wizards"
  | "reports";

interface NavItem {
  id: TabId;
  label: string;
  icon: typeof Activity;
}

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

  const show = (id: TabId) => ({
    style: { display: activeTab === id ? undefined : "none" } as React.CSSProperties,
  });

  return (
    <>
      {/* Core panels — always mounted */}
      <div {...show("packets")} className="h-full"><PacketsTab /></div>
      <div {...show("tools")}   className="h-full"><NetworkTools /></div>
      <div {...show("expert")}  className="h-full"><ExpertTools /></div>
      <div {...show("status")}  className="h-full"><StatusPanel /></div>

      {/* Lazy panels — mounted on first visit, hidden thereafter */}
      <div {...show("trafficmap")} className="h-full">
        {visited.has("trafficmap") && (
          <Suspense fallback={<LazyFallback />}><TrafficMap /></Suspense>
        )}
      </div>
      <div {...show("modbus")} className="h-full">
        {visited.has("modbus") && (
          <Suspense fallback={<LazyFallback />}><ModbusPanel /></Suspense>
        )}
      </div>
      <div {...show("rag")} className="h-full">
        {visited.has("rag") && (
          <Suspense fallback={<LazyFallback />}><RAGPanel /></Suspense>
        )}
      </div>
      <div {...show("channels")} className="h-full">
        {visited.has("channels") && (
          <Suspense fallback={<LazyFallback />}><ChannelsPanel /></Suspense>
        )}
      </div>
      <div {...show("scheduler")} className="h-full">
        {visited.has("scheduler") && (
          <Suspense fallback={<LazyFallback />}><SchedulerPanel /></Suspense>
        )}
      </div>
      <div {...show("wizards")} className="h-full">
        {visited.has("wizards") && (
          <Suspense fallback={<LazyFallback />}><WizardPanel /></Suspense>
        )}
      </div>
      <div {...show("reports")} className="h-full">
        {visited.has("reports") && (
          <Suspense fallback={<LazyFallback />}><ReportViewer /></Suspense>
        )}
      </div>
    </>
  );
}

interface SidebarItemProps {
  id: TabId;
  label: string;
  icon: typeof Activity;
  active: boolean;
  onClick: () => void;
}

/** 48px icon button with CSS-only tooltip that appears after 400ms hover delay. */
function SidebarItem({ label, icon: Icon, active, onClick }: SidebarItemProps) {
  return (
    <div className="relative sidebar-item">
      <button
        onClick={onClick}
        aria-label={label}
        role="tab"
        aria-selected={active}
        className={`flex items-center justify-center w-full h-8 mx-auto my-0.5 rounded-md transition-colors ${
          active
            ? "text-accent bg-accent-subtle"
            : "text-muted-dim hover:text-foreground hover:bg-surface-hover"
        }`}
        style={
          active
            ? { boxShadow: "inset -2px 0 0 rgb(var(--color-accent))" }
            : undefined
        }
      >
        <Icon className="w-4 h-4" />
      </button>
      <span className="sidebar-tooltip">{label}</span>
    </div>
  );
}

export function Dashboard({ onUpdateFailed: _onUpdateFailed }: DashboardProps) {
  const { activeTab, setActiveTab, isCapturing, theme, toggleTheme } = useStore(
    useShallow((s) => ({
      activeTab:    s.activeTab,
      setActiveTab: s.setActiveTab,
      isCapturing:  s.isCapturing,
      theme:        s.theme,
      toggleTheme:  s.toggleTheme,
    }))
  );

  const [aiPanelOpen, setAiPanelOpen] = useState(false);

  // Feature flags for conditional nav items
  const hasModbus   = useFeature("modbus");
  const hasRAG      = useFeature("rag");
  const hasTopology = useFeature("topology");
  const hasScheduler = useFeature("scheduler");
  const hasExpert   = useFeature("expert-analysis");
  const hasChannels = useFeature("channels");

  // Build flat nav items (no section headers)
  const navItems: NavItem[] = [
    { id: "packets",    label: "Capture",     icon: Activity   },
    ...(hasExpert    ? [{ id: "expert"      as TabId, label: "Analyze",     icon: Shield    }] : []),
    ...(hasTopology  ? [{ id: "trafficmap"  as TabId, label: "Traffic Map", icon: GitFork   }] : []),
    { id: "tools",      label: "Tools",       icon: Terminal   },
    ...(hasModbus    ? [{ id: "modbus"      as TabId, label: "Modbus",      icon: Cpu       }] : []),
    ...(hasRAG       ? [{ id: "rag"         as TabId, label: "Knowledge",   icon: BookOpen  }] : []),
    ...(hasChannels  ? [{ id: "channels"    as TabId, label: "Channels",    icon: Radio     }] : []),
    { id: "status",     label: "Status",      icon: HeartPulse },
    ...(hasScheduler ? [{ id: "scheduler"   as TabId, label: "Scheduler",   icon: Clock     }] : []),
  ];

  // Ctrl+K toggles AI panel
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setAiPanelOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <ToastContainer />

      {/* ── Sidebar: 48px fixed, no toggle ── */}
      <aside className="flex flex-col shrink-0 w-12 bg-surface border-r border-border">

        {/* Logo */}
        <div className="flex items-center justify-center h-10 border-b border-border shrink-0">
          <Network className="w-5 h-5 text-accent" />
        </div>

        {/* Nav items */}
        <nav
          role="tablist"
          aria-label="Main navigation"
          className="flex-1 overflow-y-auto py-1 px-1"
        >
          {navItems.map(({ id, label, icon }) => (
            <SidebarItem
              key={id}
              id={id}
              label={label}
              icon={icon}
              active={activeTab === id}
              onClick={() => setActiveTab(id)}
            />
          ))}
        </nav>

        {/* Live capture indicator */}
        {isCapturing && (
          <div
            className="shrink-0 flex items-center justify-center py-1.5 border-t border-border"
            role="status"
            aria-live="polite"
          >
            <span
              className="w-2 h-2 rounded-full bg-danger capture-pulse"
              title="Capturing"
            />
          </div>
        )}

        {/* AI assistant toggle */}
        <div className="relative sidebar-item shrink-0 border-t border-border">
          <button
            onClick={() => setAiPanelOpen((prev) => !prev)}
            aria-label="Toggle AI assistant (Ctrl+K)"
            aria-pressed={aiPanelOpen}
            className={`flex items-center justify-center w-full py-2 transition-colors ${
              aiPanelOpen
                ? "text-accent"
                : "text-muted-dim hover:text-foreground"
            }`}
          >
            <MessageSquare className="w-4 h-4" />
          </button>
          <span className="sidebar-tooltip">AI Assistant (Ctrl+K)</span>
        </div>

        {/* Theme toggle */}
        <div className="relative sidebar-item shrink-0 border-t border-border">
          <button
            onClick={toggleTheme}
            aria-label={
              theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
            }
            className="flex items-center justify-center w-full py-2 text-muted-dim hover:text-foreground transition-colors"
          >
            {theme === "dark" ? (
              <Sun className="w-4 h-4" />
            ) : (
              <Moon className="w-4 h-4" />
            )}
          </button>
          <span className="sidebar-tooltip">
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </span>
        </div>
      </aside>

      {/* ── Main content area ── */}
      <div className="flex flex-col flex-1 min-w-0">
        <main className="flex-1 overflow-hidden" role="tabpanel">
          <TabContent activeTab={activeTab} />
        </main>
      </div>

      {/* ── AI Panel: hidden by default, slides in from right ── */}
      <div
        className="shrink-0 bg-surface border-l border-border flex flex-col overflow-hidden transition-[width] duration-[240ms]"
        style={{
          width: aiPanelOpen ? 320 : 0,
          transitionTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
        }}
      >
        {/* Panel header — min-w keeps it from collapsing during animation */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0 min-w-[320px]">
          <span className="text-sm font-medium text-foreground">AI Assistant</span>
          <button
            onClick={() => setAiPanelOpen(false)}
            aria-label="Close AI panel"
            className="text-muted-dim hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* RightPanel always mounted — preserves WebSocket state */}
        <div className="flex-1 overflow-hidden min-w-[320px]">
          <RightPanel />
        </div>
      </div>
    </div>
  );
}
