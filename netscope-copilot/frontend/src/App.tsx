import React from 'react';
import { 
  CopilotKit,
  useCopilotReadable,
} from "@copilotkit/react-core";
import { 
  CopilotSidebar 
} from "@copilotkit/react-ui";
import { 
  Shield, 
  Activity, 
  Terminal, 
  Settings, 
  LayoutDashboard,
  Zap
} from 'lucide-react';
import "@copilotkit/react-ui/styles.css";
import { useNetScopeActions } from './lib/useCopilotActions';

const SidebarItem = ({ icon: Icon, label, active = false }: { icon: any, label: string, active?: boolean }) => (
  <div className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
    active ? 'bg-primary-500/20 text-primary-400 border border-primary-500/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 cursor-not-allowed'
  }`}>
    <Icon className="w-5 h-5" />
    <span className="font-medium">{label}</span>
  </div>
);

const NetScopeUI: React.FC = () => {
  useNetScopeActions();

  const [systemState, setSystemState] = React.useState({
    isCapturing: false,
    interface: "N/A",
    packetCount: 0,
    threats: 0
  });

  useCopilotReadable({
    description: "Current status of the network monitoring system",
    value: JSON.stringify(systemState),
  });

  React.useEffect(() => {
    const pollStatus = async () => {
      try {
        const response = await fetch("http://localhost:8001/api/capture/status");
        if (response.ok) {
          const data = await response.json();
          setSystemState(prev => ({
            ...prev,
            isCapturing: data.is_capturing,
            interface: data.interface || "N/A",
            packetCount: data.packet_count
          }));
        }
      } catch (e) {
        console.error("Status poll failed", e);
      }
    };
    const interval = setInterval(pollStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen w-full bg-[#020617] text-slate-200 overflow-hidden font-sans">
      {/* Left Navigation Sidebar */}
      <aside className="w-64 glass border-r border-white/5 flex flex-col p-4 relative z-10">
        <div className="flex items-center gap-2 mb-8 px-2">
          <div className="w-10 h-10 bg-gradient-to-br from-primary-400 to-primary-600 rounded-xl flex items-center justify-center shadow-lg shadow-primary-500/20">
            <Shield className="text-white w-6 h-6" />
          </div>
          <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
            NetScope
          </h1>
        </div>

        <nav className="flex-1 space-y-2">
          <SidebarItem icon={LayoutDashboard} label="Dashboard" active />
          <SidebarItem icon={Activity} label="Live Capture" />
          <SidebarItem icon={Terminal} label="Packet Analysis" />
          <SidebarItem icon={Zap} label="Expert Tools" />
        </nav>

        <div className="pt-4 border-t border-white/5">
          <SidebarItem icon={Settings} label="Settings" />
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 relative overflow-auto flex flex-col">
        {/* Top Header */}
        <header className="h-16 glass-card border-b border-white/5 flex items-center justify-between px-8 shrink-0">
          <div className="flex items-center gap-4 text-sm font-medium text-slate-400">
            <span>Home</span>
            <span>/</span>
            <span className="text-primary-400">Dashboard</span>
          </div>
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
              systemState.isCapturing 
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
              : 'bg-slate-500/10 border-slate-500/20 text-slate-400'
            }`}>
              <div className={`w-2 h-2 rounded-full ${systemState.isCapturing ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`} />
              <span className="text-xs font-bold uppercase tracking-wider">
                {systemState.isCapturing ? `Capturing on ${systemState.interface}` : 'System Standby'}
              </span>
            </div>
          </div>
        </header>

        {/* Activity Cards */}
        <div className="p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
           <div className="glass-card p-6 rounded-2xl h-48 flex flex-col justify-between">
              <div>
                 <h3 className="text-slate-400 text-sm font-medium mb-1 uppercase tracking-widest text-[10px]">Packet Count</h3>
                 <div className="text-3xl font-bold">{systemState.packetCount.toLocaleString()}</div>
              </div>
              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                 <div 
                   className={`h-full bg-primary-500 transition-all duration-1000 ${systemState.isCapturing ? 'w-full opacity-100' : 'w-0 opacity-0'}`} 
                 />
              </div>
           </div>

           <div className="glass-card p-6 rounded-2xl h-48 flex flex-col justify-between">
              <div>
                 <h3 className="text-slate-400 text-sm font-medium mb-1 uppercase tracking-widest text-[10px]">Threat Level</h3>
                 <div className={`text-3xl font-bold ${systemState.threats > 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                   {systemState.threats > 0 ? 'HIGH' : 'SAFE'}
                 </div>
              </div>
              <div className="flex gap-2">
                 {systemState.threats > 0 ? (
                   <>
                     <span className="px-2 py-1 rounded-md bg-rose-500/10 text-rose-400 text-[10px] font-bold uppercase tracking-tighter border border-rose-500/20">Critical</span>
                     <span className="px-2 py-1 rounded-md bg-orange-500/10 text-orange-400 text-[10px] font-bold uppercase tracking-tighter border border-orange-500/20">Warning</span>
                   </>
                 ) : (
                   <span className="px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-400 text-[10px] font-bold uppercase tracking-tighter border border-emerald-500/20">No Threats Detected</span>
                 )}
              </div>
           </div>

           <div className="glass-card p-6 rounded-2xl h-48 flex flex-col justify-between border-l-4 border-l-primary-500">
              <div>
                 <h3 className="text-slate-400 text-sm font-medium mb-1 uppercase tracking-widest text-[10px]">Live Insights</h3>
                 <div className="text-lg font-medium text-slate-300 leading-tight">
                   {systemState.isCapturing 
                     ? "Monitoring traffic patterns. Analyzing SCADA function codes for anomalies..."
                     : "Ready for analysis. Talk to the Copilot to initiate expert tools or start a capture."}
                 </div>
              </div>
           </div>
        </div>

        {/* Background Decoration */}
        <div className="fixed top-[-10%] left-[-10%] w-[40%] h-[40%] bg-primary-500/10 blur-[120px] rounded-full -z-10" />
        <div className="fixed bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-indigo-500/10 blur-[120px] rounded-full -z-10" />
      </main>

      {/* Copilot Sidebar */}
      <CopilotSidebar
        instructions="You are the NetScope AI assistant. You help users analyze network traffic, configure Modbus simulations, and understand security threats in SCADA architectures."
        labels={{
          title: "NetScope Copilot",
          initial: "Hello! I'm your AI network assistant. How can I help you today?",
        }}
        defaultOpen={true}
        clickOutsideToClose={false}
      />
    </div>
  );
};

const App: React.FC = () => {
  return (
    <CopilotKit runtimeUrl="http://localhost:8001/api/copilot/runtime">
      <NetScopeUI />
    </CopilotKit>
  );
};

export default App;
