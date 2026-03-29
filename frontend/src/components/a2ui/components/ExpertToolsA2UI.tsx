import { useState } from 'react';
import axios from 'axios';

interface ExpertToolsA2UIProps {
  mode?: 'ics_audit' | 'port_scan' | 'flow_analysis' | 'conversations' | 'anomaly_detect';
  with_llm?: boolean;
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function ExpertToolsA2UI({
  initialMode = 'ics_audit',
  with_llm = true
}: ExpertToolsA2UIProps & { initialMode?: string }) {
  const [selectedMode, setSelectedMode] = useState(initialMode);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const MODES = [
    { 
      id: 'ics_audit', 
      name: 'ICS/SCADA Audit', 
      description: 'Analyze ICS protocols and detect security issues',
      icon: '🏭'
    },
    { 
      id: 'port_scan', 
      name: 'Port Scanner', 
      description: 'Detect open ports and services',
      icon: '🔍'
    },
    { 
      id: 'flow_analysis', 
      name: 'Flow Analysis', 
      description: 'Analyze network conversations and flows',
      icon: '📊'
    },
    { 
      id: 'conversations', 
      name: 'Conversations', 
      description: 'View endpoint conversations',
      icon: '💬'
    },
    { 
      id: 'anomaly_detect', 
      name: 'Anomaly Detection', 
      description: 'Detect unusual network behavior',
      icon: '⚠️'
    },
  ];
  
  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    
    try {
      const response = await api.post('/expert/analyze', {
        mode: selectedMode,
        with_llm: with_llm
      });
      
      setResult(JSON.stringify(response.data, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="expert-tools-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">Expert Analysis Tools</h3>
      
      {/* Mode Selection */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Analysis Mode</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {MODES.map(mode => (
            <button
              key={mode.id}
              onClick={() => setSelectedMode(mode.id)}
              className={`p-3 rounded text-left transition-colors ${
                selectedMode === mode.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="text-lg">{mode.icon}</span>
                <div>
                  <div className="text-sm font-medium">{mode.name}</div>
                  <div className="text-xs opacity-75">{mode.description}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
      
      {/* LLM Toggle */}
      <div className="mb-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={with_llm}
            onChange={(e) => e.target.checked}
            className="w-4 h-4 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-300">Include AI-powered analysis</span>
        </label>
      </div>
      
      {/* Run Button */}
      <button
        onClick={runAnalysis}
        disabled={loading}
        className="w-full bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors mb-4"
      >
        {loading ? 'Analyzing...' : `Run ${MODES.find(m => m.id === selectedMode)?.name}`}
      </button>
      
      {/* Error Display */}
      {error && (
        <div className="mb-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      
      {/* Result Display */}
      {result && (
        <div className="bg-gray-900 rounded border border-gray-700 p-3 max-h-96 overflow-auto">
          <pre className="text-xs font-mono text-green-400 whitespace-pre-wrap">
            {result}
          </pre>
        </div>
      )}
    </div>
  );
}
