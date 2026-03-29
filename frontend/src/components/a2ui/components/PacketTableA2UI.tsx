import { useStore } from '../../../store/useStore';
import { useMemo } from 'react';

interface PacketTableA2UIProps {
  filter?: string;
  protocol?: string;
  limit?: number;
  columns?: string[];
  showHex?: boolean;
}

export function PacketTableA2UI({ 
  filter, 
  protocol, 
  limit = 100,
  columns = ['time', 'source', 'destination', 'protocol', 'length', 'info'],
  showHex = false 
}: PacketTableA2UIProps) {
  const { packets } = useStore();
  
  const filteredPackets = useMemo(() => {
    let result = packets;
    
    if (protocol) {
      result = result.filter(p => 
        p.protocol?.toUpperCase() === protocol.toUpperCase()
      );
    }
    
    if (filter) {
      result = result.filter(p => 
        JSON.stringify(p).toLowerCase().includes(filter.toLowerCase())
      );
    }
    
    return result.slice(0, limit);
  }, [packets, protocol, filter, limit]);
  
  return (
    <div className="packet-table-a2ui border border-gray-700 rounded-lg overflow-hidden bg-gray-900">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-700">
          <thead className="bg-gray-800">
            <tr>
              {columns.map(col => (
                <th 
                  key={col} 
                  className="px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-gray-900 divide-y divide-gray-800">
            {filteredPackets.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-500">
                  No packets to display
                </td>
              </tr>
            ) : (
              filteredPackets.map((pkt: any, idx: number) => (
                <tr key={idx} className="hover:bg-gray-800 transition-colors">
                  <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">
                    {pkt.time || '-'}
                  </td>
                  <td className="px-4 py-2 text-xs font-mono text-gray-300 whitespace-nowrap">
                    {pkt.source || '-'}
                  </td>
                  <td className="px-4 py-2 text-xs font-mono text-gray-300 whitespace-nowrap">
                    {pkt.destination || '-'}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                      pkt.protocol === 'TCP' ? 'bg-blue-900 text-blue-300' :
                      pkt.protocol === 'UDP' ? 'bg-green-900 text-green-300' :
                      pkt.protocol === 'ICMP' ? 'bg-yellow-900 text-yellow-300' :
                      'bg-gray-700 text-gray-300'
                    }`}>
                      {pkt.protocol || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-400 whitespace-nowrap">
                    {pkt.length || '-'}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-400 font-mono">
                    {pkt.info || '-'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2 bg-gray-800 text-xs text-gray-500 border-t border-gray-700">
        Showing {filteredPackets.length} of {packets.length} packets
        {filter && ` (filtered by "${filter}")`}
        {protocol && ` (protocol: ${protocol})`}
      </div>
    </div>
  );
}
