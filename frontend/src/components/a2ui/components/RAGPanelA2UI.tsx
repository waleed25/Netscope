import { useState } from 'react';
import axios from 'axios';

interface RAGPanelA2UIProps {
  mode?: 'search' | 'ingest' | 'manage';
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function RAGPanelA2UI({
  initialMode = 'search'
}: RAGPanelA2UIProps & { initialMode?: string }) {
  const [mode, setMode] = useState(initialMode);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const search = async () => {
    if (!query.trim()) {
      setError('Please enter a search query');
      return;
    }
    
    setLoading(true);
    setError(null);
    setResults([]);
    
    try {
      // Using existing insights endpoint as a proxy for RAG search
      const response = await api.post('/insights/generate', {
        mode: 'general',
        query: query
      });
      
      setResults([response.data.insight || 'No results found']);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="rag-panel-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">Knowledge Base</h3>
      
      {/* Mode Selection */}
      <div className="mb-4">
        <div className="flex gap-2">
          {[
            { id: 'search', name: 'Search', icon: '🔍' },
            { id: 'ingest', name: 'Ingest', icon: '📥' },
            { id: 'manage', name: 'Manage', icon: '⚙️' },
          ].map(m => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={`flex-1 p-2 rounded text-center transition-colors ${
                mode === m.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              <span className="text-lg mr-1">{m.icon}</span>
              <span className="text-sm">{m.name}</span>
            </button>
          ))}
        </div>
      </div>
      
      {/* Search Input */}
      {mode === 'search' && (
        <>
          <div className="mb-4">
            <label className="block text-xs text-gray-400 mb-2">Query</label>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the knowledge base..."
              disabled={loading}
              onKeyDown={(e) => e.key === 'Enter' && search()}
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            />
          </div>
          
          <button
            onClick={search}
            disabled={loading || !query.trim()}
            className="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors mb-4"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </>
      )}
      
      {/* Ingest Mode */}
      {mode === 'ingest' && (
        <div className="text-center py-8 text-gray-400">
          <div className="text-4xl mb-2">📄</div>
          <div className="text-sm">Drag & drop files here to ingest</div>
          <div className="text-xs mt-2">Supports PDF, TXT, MD files</div>
        </div>
      )}
      
      {/* Manage Mode */}
      {mode === 'manage' && (
        <div className="text-center py-8 text-gray-400">
          <div className="text-4xl mb-2">📚</div>
          <div className="text-sm">Knowledge base management</div>
          <button className="mt-4 bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded text-sm">
            View Indexed Documents
          </button>
        </div>
      )}
      
      {/* Error Display */}
      {error && (
        <div className="mb-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      
      {/* Results Display */}
      {results.length > 0 && (
        <div className="bg-gray-900 rounded border border-gray-700 p-3 max-h-64 overflow-auto">
          {results.map((result, idx) => (
            <div key={idx} className="text-sm text-gray-300 whitespace-pre-wrap">
              {result}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
