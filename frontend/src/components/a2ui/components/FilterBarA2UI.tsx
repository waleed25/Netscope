import { useState } from 'react';
import { useStore } from '../../../store/useStore';

interface FilterBarA2UIProps {
  protocols?: string[];
  ports?: number[];
  ips?: string[];
  presets?: string[];
}

const PROTOCOL_OPTIONS = ['TCP', 'UDP', 'ICMP', 'DNS', 'HTTP', 'HTTPS', 'ARP', 'MQTT', 'Modbus'];
const PRESET_FILTERS = [
  { label: 'HTTP/HTTPS', value: 'tcp port 80 or tcp port 443' },
  { label: 'DNS', value: 'udp port 53' },
  { label: 'SSH', value: 'tcp port 22' },
  { label: 'Modbus', value: 'tcp port 502' },
  { label: 'ARP', value: 'arp' },
];

export function FilterBarA2UI({
  protocols = [],
  ports = [],
  ips = [],
  presets = []
}: FilterBarA2UIProps) {
  const { bpfFilter, setBpfFilter } = useStore();
  const [selectedProtocols, setSelectedProtocols] = useState<string[]>(protocols);
  const [customFilter, setCustomFilter] = useState('');
  
  const toggleProtocol = (proto: string) => {
    setSelectedProtocols(prev => 
      prev.includes(proto) 
        ? prev.filter(p => p !== proto)
        : [...prev, proto]
    );
  };
  
  const applyFilter = (filter: string) => {
    setBpfFilter(filter);
  };
  
  return (
    <div className="filter-bar-a2ui bg-gray-800 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-semibold text-white mb-3">Packet Filter</h3>
      
      {/* Protocol Filters */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Protocols</label>
        <div className="flex flex-wrap gap-2">
          {PROTOCOL_OPTIONS.map(proto => (
            <button
              key={proto}
              onClick={() => toggleProtocol(proto)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                selectedProtocols.includes(proto)
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              {proto}
            </button>
          ))}
        </div>
      </div>
      
      {/* Preset Filters */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Quick Filters</label>
        <div className="flex flex-wrap gap-2">
          {PRESET_FILTERS.map(preset => (
            <button
              key={preset.label}
              onClick={() => applyFilter(preset.value)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                bpfFilter === preset.value
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>
      
      {/* Custom Filter */}
      <div className="mb-4">
        <label className="block text-xs text-gray-400 mb-2">Custom BPF Filter</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={customFilter}
            onChange={(e) => setCustomFilter(e.target.value)}
            placeholder="e.g., tcp port 8080 and host 192.168.1.1"
            className="flex-1 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => e.key === 'Enter' && applyFilter(customFilter)}
          />
          <button
            onClick={() => applyFilter(customFilter)}
            disabled={!customFilter.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors"
          >
            Apply
          </button>
        </div>
      </div>
      
      {/* Active Filter Display */}
      {bpfFilter && (
        <div className="flex items-center justify-between bg-gray-900 rounded px-3 py-2">
          <span className="text-sm text-gray-300">
            <span className="text-gray-500">Active: </span>
            <code className="text-green-400 font-mono">{bpfFilter}</code>
          </span>
          <button
            onClick={() => setBpfFilter('')}
            className="text-xs text-red-400 hover:text-red-300"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
