import { useState } from 'react';
import axios from 'axios';

interface NetworkToolsA2UIProps {
  tool?: 'ping' | 'tracert' | 'arp' | 'netstat' | 'subnet-scan';
  target?: string;
  streaming?: boolean;
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function NetworkToolsA2UI({
  initialTool = 'ping',
  initialTarget = '',
  streaming = true
}: NetworkToolsA2UIProps & { initialTool?: string; initialTarget?: string }) {
  const [selectedTool, setSelectedTool] = useState(initialTool);
  const [target, setTarget] = useState(initialTarget);
  const [args, setArgs] = useState('');
  const [loading, setLoading] = useState(false);
  const [output, setOutput] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  
  const TOOLS = [
    { id: 'ping', name: 'Ping', description: 'Test connectivity to a host' },
    { id: 'tracert', name: 'Traceroute', description: 'Trace network path' },
    { id: 'arp', name: 'ARP Table', description: 'View ARP cache' },
    { id: 'netstat', name: 'Netstat', description: 'View network connections' },
    { id: 'subnet-scan', name: 'Subnet Scan', description: 'Scan local network' },
  ];
  
  const runTool = async () => {
    if (!target && selectedTool !== 'arp' && selectedTool !== 'netstat') {
      setError('Please enter a target');
      return;
    }
    
    setLoading(true);
    setError(null);
    setOutput([]);
    
    try {
      const endpoint = selectedTool === 'subnet-scan' 
        ? `/tools/subnet-scan?target=${encodeURIComponent(target || '192.168.1.0/24')}`
        : `/tools/run?tool=${selectedTool}&target=${encodeURIComponent(target)}&args=${encodeURIComponent(args)}`;
      
      if (streaming) {
        const response = await fetch(`${resolveBaseURL()}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`, {
          method: 'GET',
        });
        
        if (!response.ok) throw new Error('Tool execution failed');
        
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        
        if (!reader) throw new Error('No response stream');
        
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          setOutput(prev => [...prev, chunk]);
        }
      } else {
        const response = await api.get(endpoint);
        setOutput([response.data.output || 'Command executed successfully']);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to execute tool');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="network-tools-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">Network Tools</h3>
      
      {/* Tool Selection */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Select Tool</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {TOOLS.map(tool => (
            <button
              key={tool.id}
              onClick={() => setSelectedTool(tool.id)}
              className={`px-3 py-2 rounded text-xs font-medium transition-colors text-left ${
                selectedTool === tool.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              <div className="font-medium">{tool.name}</div>
              <div className="text-gray-400 text-xs">{tool.description}</div>
            </button>
          ))}
        </div>
      </div>
      
      {/* Target Input */}
      {selectedTool !== 'arp' && selectedTool !== 'netstat' && (
        <div className="mb-4">
          <label className="block text-xs text-gray-400 mb-2">Target</label>
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="e.g., 8.8.8.8 or google.com"
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}
      
      {/* Additional Args */}
      {selectedTool === 'ping' && (
        <div className="mb-4">
          <label className="block text-xs text-gray-400 mb-2">Additional Args</label>
          <input
            type="text"
            value={args}
            onChange={(e) => setArgs(e.target.value)}
            placeholder="e.g., -n 4 or -c 4"
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}
      
      {/* Run Button */}
      <button
        onClick={runTool}
        disabled={loading || (!target && selectedTool !== 'arp' && selectedTool !== 'netstat')}
        className="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors mb-4"
      >
        {loading ? 'Running...' : `Run ${TOOLS.find(t => t.id === selectedTool)?.name}`}
      </button>
      
      {/* Error Display */}
      {error && (
        <div className="mb-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      
      {/* Output Display */}
      {output.length > 0 && (
        <div className="bg-gray-900 rounded border border-gray-700 p-3 max-h-64 overflow-auto">
          <pre className="text-xs font-mono text-green-400 whitespace-pre-wrap">
            {output.join('')}
          </pre>
        </div>
      )}
    </div>
  );
}
