import { useState } from 'react';
import axios from 'axios';

interface ModbusPanelA2UIProps {
  action?: 'scan' | 'read' | 'write' | 'simulate';
  target?: string;
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function ModbusPanelA2UI({
  initialAction = 'scan',
  initialTarget = ''
}: ModbusPanelA2UIProps & { initialAction?: string; initialTarget?: string }) {
  const [action, setAction] = useState(initialAction);
  const [target, setTarget] = useState(initialTarget);
  const [register, setRegister] = useState('');
  const [value, setValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const executeAction = async () => {
    if (!target && action !== 'scan') {
      setError('Please enter a target IP');
      return;
    }
    
    setLoading(true);
    setError(null);
    setResult(null);
    
    try {
      const payload: any = { action };
      
      if (target) payload.target = target;
      if (register) payload.register = parseInt(register);
      if (value) payload.value = parseInt(value);
      
      const response = await api.post('/expert/analyze', {
        mode: 'ics_audit',
        action: action,
        ...payload
      });
      
      setResult(JSON.stringify(response.data, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Modbus operation failed');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="modbus-panel-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">Modbus Device Control</h3>
      
      {/* Action Selection */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Action</label>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { id: 'scan', name: 'Scan', icon: '🔍' },
            { id: 'read', name: 'Read', icon: '📖' },
            { id: 'write', name: 'Write', icon: '✏️' },
            { id: 'simulate', name: 'Simulate', icon: '🎭' },
          ].map(act => (
            <button
              key={act.id}
              onClick={() => setAction(act.id)}
              disabled={loading}
              className={`p-2 rounded text-center transition-colors ${
                action === act.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50'
              }`}
            >
              <div className="text-lg mb-1">{act.icon}</div>
              <div className="text-xs">{act.name}</div>
            </button>
          ))}
        </div>
      </div>
      
      {/* Target IP */}
      {action !== 'scan' && (
        <div className="mb-4">
          <label className="block text-xs text-gray-400 mb-2">Target IP</label>
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="e.g., 192.168.1.100"
            disabled={loading}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          />
        </div>
      )}
      
      {/* Register Address */}
      {(action === 'read' || action === 'write') && (
        <div className="mb-4">
          <label className="block text-xs text-gray-400 mb-2">Register Address</label>
          <input
            type="number"
            value={register}
            onChange={(e) => setRegister(e.target.value)}
            placeholder="e.g., 0"
            disabled={loading}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          />
        </div>
      )}
      
      {/* Value */}
      {action === 'write' && (
        <div className="mb-4">
          <label className="block text-xs text-gray-400 mb-2">Value</label>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="e.g., 1"
            disabled={loading}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          />
        </div>
      )}
      
      {/* Execute Button */}
      <button
        onClick={executeAction}
        disabled={loading}
        className="w-full bg-orange-600 hover:bg-orange-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors mb-4"
      >
        {loading ? 'Executing...' : `Execute ${action.charAt(0).toUpperCase() + action.slice(1)}`}
      </button>
      
      {/* Error Display */}
      {error && (
        <div className="mb-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      
      {/* Result Display */}
      {result && (
        <div className="bg-gray-900 rounded border border-gray-700 p-3 max-h-64 overflow-auto">
          <pre className="text-xs font-mono text-green-400 whitespace-pre-wrap">
            {result}
          </pre>
        </div>
      )}
    </div>
  );
}
