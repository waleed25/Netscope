import { useState } from 'react';
import { useStore } from '../../../store/useStore';
import axios from 'axios';

interface InsightCardA2UIProps {
  mode?: 'general' | 'security' | 'performance' | 'ics';
  streaming?: boolean;
  showSource?: boolean;
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function InsightCardA2UI({
  mode = 'general',
  streaming = true,
  showSource = true
}: InsightCardA2UIProps) {
  const { insights, appendInsightToken, currentInsightStream, clearInsightStream } = useStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const generateInsight = async () => {
    setLoading(true);
    setError(null);
    clearInsightStream();
    
    try {
      if (streaming) {
        const response = await fetch(`${resolveBaseURL()}/insights/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode }),
        });
        
        if (!response.ok) throw new Error('Failed to generate insight');
        
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        
        if (!reader) throw new Error('No response stream');
        
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          appendInsightToken(chunk);
        }
      } else {
        const response = await api.post('/insights/generate', { mode });
        appendInsightToken(response.data.insight);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate insight');
    } finally {
      setLoading(false);
    }
  };
  
  const latestInsight = insights[0];
  const displayText = currentInsightStream || latestInsight?.text || '';
  
  return (
    <div className="insight-card-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-white capitalize">
          {mode} Insight
        </h3>
        <button
          onClick={generateInsight}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-3 py-1 rounded text-sm font-medium transition-colors"
        >
          {loading ? 'Generating...' : 'Generate'}
        </button>
      </div>
      
      {error && (
        <div className="mb-3 p-2 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      
      <div className="prose prose-invert max-w-none">
        {displayText ? (
          <p className="text-gray-300 whitespace-pre-wrap text-sm leading-relaxed">
            {displayText}
          </p>
        ) : (
          <p className="text-gray-500 italic">
            Click Generate to create an insight...
          </p>
        )}
      </div>
      
      {showSource && latestInsight?.source && (
        <div className="mt-3 text-xs text-gray-500">
          Source: {latestInsight.source}
        </div>
      )}
    </div>
  );
}
