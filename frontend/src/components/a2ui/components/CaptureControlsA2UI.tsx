import { useState } from 'react';
import { useStore } from '../../../store/useStore';
import axios from 'axios';

interface CaptureControlsA2UIProps {
  initialInterface?: string;
  initialBpfFilter?: string;
  maxPackets?: number;
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function CaptureControlsA2UI({
  initialInterface,
  initialBpfFilter = '',
  maxPackets = 5000
}: CaptureControlsA2UIProps) {
  const { isCapturing, setIsCapturing, interfaces, activeInterface } = useStore();
  const [selectedInterface, setSelectedInterface] = useState(initialInterface || activeInterface || '');
  const [filter, setFilter] = useState(initialBpfFilter);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const handleStart = async () => {
    if (!selectedInterface) {
      setError('Please select a network interface');
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      await api.post("/capture/start", { interface: selectedInterface, bpf_filter: filter });
      setIsCapturing(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start capture');
    } finally {
      setLoading(false);
    }
  };
  
  const handleStop = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.post("/capture/stop");
      setIsCapturing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop capture');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="capture-controls-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex flex-wrap gap-4 items-end">
        {/* Interface Selector */}
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-gray-400 mb-1">Network Interface</label>
          <select
            value={selectedInterface}
            onChange={(e) => setSelectedInterface(e.target.value)}
            disabled={isCapturing || loading}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          >
            <option value="">Select interface...</option>
            {interfaces.map((iface: any) => (
              <option key={iface.name} value={iface.name}>
                {iface.name} - {iface.description || 'No description'}
              </option>
            ))}
          </select>
        </div>
        
        {/* BPF Filter */}
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-gray-400 mb-1">BPF Filter</label>
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="e.g., tcp port 443"
            disabled={isCapturing || loading}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          />
        </div>
        
        {/* Action Buttons */}
        <div className="flex gap-2">
          {!isCapturing ? (
            <button
              onClick={handleStart}
              disabled={loading || !selectedInterface}
              className="bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors flex items-center gap-2"
            >
              <span className="w-2 h-2 bg-green-400 rounded-full"></span>
              {loading ? 'Starting...' : 'Start Capture'}
            </button>
          ) : (
            <button
              onClick={handleStop}
              disabled={loading}
              className="bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white px-4 py-2 rounded text-sm font-medium transition-colors flex items-center gap-2"
            >
              <span className="w-2 h-2 bg-red-400 rounded-full animate-pulse"></span>
              {loading ? 'Stopping...' : 'Stop Capture'}
            </button>
          )}
        </div>
      </div>
      
      {/* Status Messages */}
      {error && (
        <div className="mt-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      
      {isCapturing && (
        <div className="mt-3 flex items-center gap-2 text-sm text-green-400">
          <span className="animate-pulse">●</span>
          <span>Capturing on <span className="font-mono">{selectedInterface}</span></span>
          <span className="text-gray-500">•</span>
          <span className="text-gray-400">Max {maxPackets} packets</span>
        </div>
      )}
    </div>
  );
}
