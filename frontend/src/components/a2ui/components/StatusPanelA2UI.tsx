import { useState, useEffect } from 'react';
import { useStore } from '../../../store/useStore';
import axios from 'axios';

interface StatusPanelA2UIProps {
  components?: Array<'capture' | 'llm' | 'rag' | 'modbus' | 'websocket'>;
  refresh?: number;
}

function resolveBaseURL(): string {
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    const port = (window as unknown as { __BACKEND_PORT__?: number }).__BACKEND_PORT__ ?? 8000;
    return `http://127.0.0.1:${port}/api`;
  }
  return "/api";
}

const api = axios.create({ baseURL: resolveBaseURL() });

export function StatusPanelA2UI({
  components = ['capture', 'llm', 'websocket'],
  refresh = 5000
}: StatusPanelA2UIProps) {
  const { isCapturing, llmStatus } = useStore();
  const [captureStatus, setCaptureStatus] = useState<any>(null);
  const [wsStatus, setWsStatus] = useState<'connected' | 'disconnected'>('disconnected');
  
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await api.get('/capture/status');
        setCaptureStatus(res.data);
      } catch {
        setCaptureStatus(null);
      }
    };
    
    fetchStatus();
    const interval = setInterval(fetchStatus, refresh);
    return () => clearInterval(interval);
  }, [refresh]);
  
  const StatusItem = ({ 
    name, 
    status, 
    icon 
  }: { 
    name: string; 
    status: 'ok' | 'error' | 'warning' | 'unknown'; 
    icon: string;
  }) => (
    <div className="flex items-center justify-between p-3 bg-gray-700 rounded">
      <div className="flex items-center gap-3">
        <span className="text-lg">{icon}</span>
        <span className="text-sm font-medium text-white">{name}</span>
      </div>
      <span className={`px-2 py-1 rounded text-xs font-medium ${
        status === 'ok' ? 'bg-green-900 text-green-300' :
        status === 'warning' ? 'bg-yellow-900 text-yellow-300' :
        status === 'error' ? 'bg-red-900 text-red-300' :
        'bg-gray-600 text-gray-300'
      }`}>
        {status === 'ok' ? 'OK' : status === 'warning' ? 'Warning' : status === 'error' ? 'Error' : 'Unknown'}
      </span>
    </div>
  );
  
  return (
    <div className="status-panel-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">System Status</h3>
      
      <div className="space-y-2">
        {components.includes('capture') && (
          <StatusItem 
            name="Capture" 
            status={isCapturing ? 'ok' : captureStatus?.is_capturing ? 'ok' : 'warning'} 
            icon="📡"
          />
        )}
        
        {components.includes('llm') && (
          <StatusItem 
            name={`LLM (${llmStatus?.backend || 'Unknown'})`}
            status={llmStatus?.reachable ? 'ok' : 'error'}
            icon="🤖"
          />
        )}
        
        {components.includes('websocket') && (
          <StatusItem 
            name="WebSocket" 
            status={wsStatus === 'connected' ? 'ok' : 'warning'}
            icon="🔌"
          />
        )}
        
        {components.includes('rag') && (
          <StatusItem 
            name="RAG" 
            status="warning"
            icon="📚"
          />
        )}
        
        {components.includes('modbus') && (
          <StatusItem 
            name="Modbus" 
            status="warning"
            icon="🔧"
          />
        )}
      </div>
      
      <div className="mt-4 text-xs text-gray-500">
        Last updated: {new Date().toLocaleTimeString()}
      </div>
    </div>
  );
}
