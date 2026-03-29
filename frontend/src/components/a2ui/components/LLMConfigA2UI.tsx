import { useState, useEffect } from 'react';
import { useStore } from '../../../store/useStore';
import axios from 'axios';

interface LLMConfigA2UIProps {
  backend?: 'ollama' | 'lmstudio';
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function LLMConfigA2UI({
  initialBackend = 'ollama'
}: LLMConfigA2UIProps & { initialBackend?: string }) {
  const { llmStatus, llmBackend, setLLMStatus, setLLMBackend } = useStore();
  const [backend, setBackend] = useState(initialBackend);
  const [model, setModel] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    fetchStatus();
  }, []);
  
  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await api.get('/llm/status');
      setLLMStatus(res.data);
      if (res.data.model) setModel(res.data.model);
    } catch (err) {
      setError('Failed to fetch LLM status');
    } finally {
      setLoading(false);
    }
  };
  
  const saveConfig = async () => {
    setSaving(true);
    setError(null);
    
    try {
      await api.post('/llm/backend', {
        backend,
        base_url: backend === 'ollama' ? 'http://localhost:11434' : 'http://localhost:1234'
      });
      
      if (model) {
        await api.post('/llm/model', { model });
      }
      
      setLLMBackend(backend as 'ollama' | 'lmstudio');
      await fetchStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save config');
    } finally {
      setSaving(false);
    }
  };
  
  return (
    <div className="llm-config-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">LLM Configuration</h3>
      
      {/* Current Status */}
      <div className="mb-4 p-3 bg-gray-900 rounded">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-gray-400">Status</div>
            <div className="text-sm font-medium">
              {llmStatus?.reachable ? (
                <span className="text-green-400">Connected</span>
              ) : (
                <span className="text-red-400">Disconnected</span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-gray-400">Model</div>
            <div className="text-sm font-mono text-gray-300">
              {llmStatus?.model || 'None'}
            </div>
          </div>
        </div>
        
        {llmStatus?.vram_used_bytes && (
          <div className="mt-2 pt-2 border-t border-gray-700">
            <div className="text-xs text-gray-400">VRAM Usage</div>
            <div className="text-sm text-gray-300">
              {Math.round(llmStatus.vram_used_bytes / 1024 / 1024)} MB / {Math.round((llmStatus.model_size_bytes || 0) / 1024 / 1024)} MB
            </div>
          </div>
        )}
      </div>
      
      {/* Backend Selection */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Backend</label>
        <div className="grid grid-cols-2 gap-2">
          {[
            { id: 'ollama', name: 'Ollama', url: 'http://localhost:11434' },
            { id: 'lmstudio', name: 'LM Studio', url: 'http://localhost:1234' },
          ].map(b => (
            <button
              key={b.id}
              onClick={() => setBackend(b.id)}
              disabled={saving}
              className={`p-3 rounded text-center transition-colors ${
                backend === b.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50'
              }`}
            >
              <div className="text-sm font-medium">{b.name}</div>
              <div className="text-xs opacity-75">{b.url}</div>
            </button>
          ))}
        </div>
      </div>
      
      {/* Model Selection */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Model</label>
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="e.g., llama3, codellama, mistral"
          disabled={saving}
          className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        />
      </div>
      
      {/* Temperature */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">
          Temperature: {temperature}
        </label>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          value={temperature}
          onChange={(e) => setTemperature(parseFloat(e.target.value))}
          disabled={saving}
          className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer disabled:opacity-50"
        />
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>Precise</span>
          <span>Balanced</span>
          <span>Creative</span>
        </div>
      </div>
      
      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="flex-1 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-600 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
        <button
          onClick={saveConfig}
          disabled={saving}
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
      
      {/* Error Display */}
      {error && (
        <div className="mt-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
