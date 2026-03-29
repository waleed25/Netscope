import { useStore } from "../store/useStore";
import { useShallow } from "zustand/react/shallow";
import { FilterBar } from "./FilterBar";
import { PacketsAndInsights } from "./PacketsAndInsights";
import { PcapUpload } from "./PcapUpload";
import { CaptureManager } from "./CaptureManager";
import { Radio, Upload, HardDrive } from "lucide-react";

const SUB_TABS = [
  { id: "live"   as const, label: "Live Capture",   icon: Radio      },
  { id: "import" as const, label: "Import PCAP",    icon: Upload     },
  { id: "saved"  as const, label: "Saved Captures", icon: HardDrive  },
];

export function PacketsTab() {
  const { subTab, setSubTab } = useStore(
    useShallow((s) => ({ subTab: s.packetsSubTab, setSubTab: s.setPacketsSubTab }))
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sub-tab bar */}
      <div className="flex shrink-0 border-b border-border bg-surface px-2 gap-1 pt-1">
        {SUB_TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t transition-colors border-b-2 ${
              subTab === id
                ? "border-accent text-accent bg-surface-hover"
                : "border-transparent text-muted hover:text-foreground hover:bg-surface-hover"
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {subTab === "live" && (
          <>
            <div className="shrink-0 border-b border-border">
              <FilterBar />
            </div>
            <div className="flex-1 overflow-hidden">
              <PacketsAndInsights />
            </div>
          </>
        )}
        {subTab === "import" && (
          <div className="flex-1 overflow-y-auto">
            <PcapUpload />
          </div>
        )}
        {subTab === "saved" && (
          <div className="flex-1 overflow-hidden">
            <CaptureManager />
          </div>
        )}
      </div>
    </div>
  );
}
