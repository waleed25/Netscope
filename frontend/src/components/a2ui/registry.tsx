import { ComponentType } from 'react';

import { PacketTableA2UI } from './components/PacketTableA2UI';
import { CaptureControlsA2UI } from './components/CaptureControlsA2UI';
import { InsightCardA2UI } from './components/InsightCardA2UI';
import { FilterBarA2UI } from './components/FilterBarA2UI';
import { NetworkToolsA2UI } from './components/NetworkToolsA2UI';
import { StatusPanelA2UI } from './components/StatusPanelA2UI';
import { ExpertToolsA2UI } from './components/ExpertToolsA2UI';
import { ModbusPanelA2UI } from './components/ModbusPanelA2UI';
import { RAGPanelA2UI } from './components/RAGPanelA2UI';
import { LLMConfigA2UI } from './components/LLMConfigA2UI';

interface A2UIComponentProp {
  type: 'string' | 'number' | 'boolean' | 'array' | 'object';
  description?: string;
  enum?: string[];
  default?: any;
  items?: { type: string };
}

export interface A2UIComponentDefinition {
  name: string;
  description: string;
  propsSchema: Record<string, A2UIComponentProp>;
  defaultProps: Record<string, any>;
  examples: string[];
  component: ComponentType<any>;
}

export const A2UI_COMPONENTS = {
  'packet-table': {
    name: 'PacketTable',
    description: 'Display network packets in a sortable, filterable table',
    propsSchema: {
      filter: { type: 'string', description: 'BPF filter expression' },
      protocol: { type: 'string', enum: ['TCP', 'UDP', 'ICMP', 'DNS', 'HTTP'] },
      limit: { type: 'number', default: 100 },
      columns: { type: 'array', items: { type: 'string' } },
      showHex: { type: 'boolean', default: false },
    },
    defaultProps: { limit: 100, showHex: false },
    examples: ['show TCP packets', 'filter by port 80', 'display DNS queries only'],
    component: PacketTableA2UI,
  },
  'capture-controls': {
    name: 'CaptureControls',
    description: 'Start/stop/configure packet capture',
    propsSchema: {
      interface: { type: 'string', description: 'Network interface' },
      bpfFilter: { type: 'string', description: 'BPF filter' },
      maxPackets: { type: 'number', default: 5000 },
      mode: { type: 'string', enum: ['live', 'preview'] },
    },
    defaultProps: { maxPackets: 5000, mode: 'live' },
    examples: ['start capture on eth0', 'stop capture', 'capture with filter "tcp"'],
    component: CaptureControlsA2UI,
  },
  'insight-card': {
    name: 'InsightCard',
    description: 'Display AI-generated network insights',
    propsSchema: {
      mode: { type: 'string', enum: ['general', 'security', 'performance', 'ics'] },
      streaming: { type: 'boolean', default: true },
      showSource: { type: 'boolean', default: true },
    },
    defaultProps: { mode: 'general', streaming: true, showSource: true },
    examples: ['generate security insight', 'analyze performance', 'show ICS audit results'],
    component: InsightCardA2UI,
  },
  'filter-bar': {
    name: 'FilterBar',
    description: 'Interactive packet filtering controls',
    propsSchema: {
      protocols: { type: 'array', items: { type: 'string' } },
      ports: { type: 'array', items: { type: 'number' } },
      presets: { type: 'array', items: { type: 'string' } },
    },
    defaultProps: {},
    examples: ['show filter for HTTP', 'filter by source IP', 'quick filters'],
    component: FilterBarA2UI,
  },
  'network-tools': {
    name: 'NetworkTools',
    description: 'Run network diagnostic tools',
    propsSchema: {
      tool: { type: 'string', enum: ['ping', 'tracert', 'arp', 'netstat', 'subnet-scan'] },
      target: { type: 'string', description: 'Target IP or hostname' },
      args: { type: 'string', description: 'Additional arguments' },
    },
    defaultProps: {},
    examples: ['ping 8.8.8.8', 'tracert google.com', 'run subnet scan'],
    component: NetworkToolsA2UI,
  },
  'status-panel': {
    name: 'StatusPanel',
    description: 'System status and health metrics',
    propsSchema: {
      components: { type: 'array', items: { type: 'string', enum: ['capture', 'llm', 'rag', 'modbus', 'websocket'] } },
      refresh: { type: 'number', description: 'Auto-refresh interval (ms)' },
    },
    defaultProps: { refresh: 5000 },
    examples: ['show system status', 'check LLM connection', 'show component health'],
    component: StatusPanelA2UI,
  },
  'expert-tools': {
    name: 'ExpertTools',
    description: 'Run expert network analysis modes',
    propsSchema: {
      mode: { type: 'string', enum: ['ics_audit', 'port_scan', 'flow_analysis', 'conversations', 'anomaly_detect'] },
      with_llm: { type: 'boolean', default: true },
    },
    defaultProps: { with_llm: true },
    examples: ['run ICS audit', 'detect port scans', 'show network conversations'],
    component: ExpertToolsA2UI,
  },
  'modbus-panel': {
    name: 'ModbusPanel',
    description: 'Modbus device scanning and interaction',
    propsSchema: {
      action: { type: 'string', enum: ['scan', 'read', 'write', 'simulate'] },
      target: { type: 'string', description: 'Target IP' },
      register: { type: 'number', description: 'Register address' },
      value: { type: 'number', description: 'Value to write' },
    },
    defaultProps: {},
    examples: ['scan for Modbus devices', 'read holding registers', 'write to coil'],
    component: ModbusPanelA2UI,
  },
  'rag-panel': {
    name: 'RAGPanel',
    description: 'Knowledge base search and management',
    propsSchema: {
      mode: { type: 'string', enum: ['search', 'ingest', 'manage'] },
    },
    defaultProps: { mode: 'search' },
    examples: ['search documentation', 'ingest new document', 'show indexed documents'],
    component: RAGPanelA2UI,
  },
  'llm-config': {
    name: 'LLMConfig',
    description: 'LLM backend and model configuration',
    propsSchema: {
      backend: { type: 'string', enum: ['ollama', 'lmstudio'] },
      model: { type: 'string', description: 'Model name' },
      temperature: { type: 'number', min: 0, max: 2 },
    },
    defaultProps: { backend: 'ollama', temperature: 0.7 },
    examples: ['switch to ollama', 'change model to llama3', 'configure LLM'],
    component: LLMConfigA2UI,
  },
} as const;

export const A2UI_COMPONENT_REGISTRY = A2UI_COMPONENTS;

export type A2UIComponentName = keyof typeof A2UI_COMPONENTS;
