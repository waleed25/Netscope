import { Activity, Shield, GitFork, Cpu, Terminal, Settings } from "lucide-react";
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
  { id: "capture",    icon: Activity,  label: "Capture"    },
  { id: "analysis",   icon: Shield,    label: "Analysis"   },
  { id: "trafficmap", icon: GitFork,   label: "Traffic Map"},
  { id: "protocols",  icon: Cpu,       label: "Protocols"  },
  { id: "tools",      icon: Terminal,  label: "Net Tools"  },
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
