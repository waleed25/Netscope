/**
 * NetworkTopologyDiagram
 *
 * Renders a hierarchical network topology diagram from the backend topology API.
 * Shows firewalls, routers, switches, servers, endpoints, and PLCs with their
 * physical/inferred connections and port numbers.
 *
 * Data sources (via backend):
 *   - CDP / LLDP packets  → confirmed adjacency with real port IDs
 *   - ARP / DHCP / STP    → device discovery and gateway identification
 *   - Subnet scan         → active host enumeration
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  MarkerType,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  type EdgeProps,
  Handle,
  Position,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import {
  RefreshCw, Search, CheckCircle, AlertTriangle,
  Info, X, Network,
} from "lucide-react";
import { fetchTopology, scanTopology } from "../lib/api";
import type { NetworkTopology, TopologyNode, DeviceType } from "../lib/api";

/** Read a CSS custom property as an rgb() string. */
function cssColor(varName: string): string {
  const val = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  return val ? `rgb(${val})` : "rgb(139,148,158)";
}

// ── Cisco-style SVG device symbols ───────────────────────────────────────────

/** Firewall — brick wall with flame on top */
function FirewallIcon({ size = 36, color = "rgb(var(--color-danger))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      {/* Flame */}
      <path d="M24 4 C20 10 16 12 18 18 C16 16 15 13 16 10 C12 14 11 20 14 25 C11 23 10 19 11 16 C8 20 8 28 14 32 C10 31 8 27 9 24 C6 27 6 34 10 38 C8 37 7 34 8 31" stroke={color} strokeWidth="1.5" fill="none" opacity="0.7"/>
      <path d="M24 6 C28 11 32 13 30 19 C32 17 33 14 32 11 C36 15 37 21 34 26 C37 24 38 20 37 17 C40 21 40 29 34 33 C38 32 40 28 39 25 C42 28 42 35 38 39 C40 38 41 35 40 32" stroke={color} strokeWidth="1.5" fill="none" opacity="0.7"/>
      {/* Brick wall body */}
      <rect x="6" y="32" width="36" height="5" rx="1" fill={color} opacity="0.9"/>
      <rect x="6" y="38" width="36" height="5" rx="1" fill={color} opacity="0.9"/>
      {/* Mortar lines */}
      <line x1="18" y1="32" x2="18" y2="37" stroke="rgb(var(--color-background))" strokeWidth="1.5"/>
      <line x1="30" y1="32" x2="30" y2="37" stroke="rgb(var(--color-background))" strokeWidth="1.5"/>
      <line x1="12" y1="38" x2="12" y2="43" stroke="rgb(var(--color-background))" strokeWidth="1.5"/>
      <line x1="24" y1="38" x2="24" y2="43" stroke="rgb(var(--color-background))" strokeWidth="1.5"/>
      <line x1="36" y1="38" x2="36" y2="43" stroke="rgb(var(--color-background))" strokeWidth="1.5"/>
    </svg>
  );
}

/** Router — circle with 4 directional arrows (classic Cisco router symbol) */
function RouterIcon({ size = 36, color = "rgb(var(--color-tool))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="14" stroke={color} strokeWidth="2" fill={color} fillOpacity={0.09}/>
      {/* Cross lines */}
      <line x1="24" y1="10" x2="24" y2="38" stroke={color} strokeWidth="1.5"/>
      <line x1="10" y1="24" x2="38" y2="24" stroke={color} strokeWidth="1.5"/>
      {/* Arrow heads */}
      <polygon points="24,6 21,12 27,12" fill={color}/>
      <polygon points="24,42 21,36 27,36" fill={color}/>
      <polygon points="6,24 12,21 12,27" fill={color}/>
      <polygon points="42,24 36,21 36,27" fill={color}/>
      {/* Center dot */}
      <circle cx="24" cy="24" r="3" fill={color}/>
    </svg>
  );
}

/** Switch — rack unit with port grid */
function SwitchIcon({ size = 40, color = "rgb(var(--color-accent))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size * 0.55} viewBox="0 0 56 31" fill="none">
      {/* Chassis body */}
      <rect x="1" y="1" width="54" height="29" rx="3" fill={color} fillOpacity={0.09} stroke={color} strokeWidth="1.5"/>
      {/* Status LED strip */}
      <rect x="4" y="4" width="4" height="4" rx="1" fill="rgb(var(--color-success))"/>
      <rect x="10" y="4" width="4" height="4" rx="1" fill="rgb(var(--color-success))"/>
      <rect x="16" y="4" width="4" height="4" rx="1" fill={color} opacity="0.4"/>
      {/* Port grid — 8 ports × 2 rows */}
      {[0,1,2,3,4,5,6,7].map(i => (
        <g key={i}>
          <rect x={4 + i*6} y={11} width="5" height="4" rx="0.5" fill={color} fillOpacity={0.25} stroke={color} strokeOpacity={0.50} strokeWidth="0.8"/>
          <rect x={4 + i*6} y={17} width="5" height="4" rx="0.5" fill={color} fillOpacity={0.25} stroke={color} strokeOpacity={0.50} strokeWidth="0.8"/>
        </g>
      ))}
      {/* Uplink ports (larger) */}
      <rect x="52" y="11" width="1.5" height="10" fill={color} opacity="0.6"/>
      {/* Vent slots */}
      {[44,47,50].map(x => (
        <line key={x} x1={x} y1="23" x2={x} y2="27" stroke={color} strokeOpacity={0.25} strokeWidth="1"/>
      ))}
    </svg>
  );
}

/** Server — rack unit with drive bays */
function ServerIcon({ size = 36, color = "rgb(var(--color-success))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      {/* Chassis */}
      <rect x="4" y="10" width="40" height="28" rx="2" fill={color} fillOpacity={0.09} stroke={color} strokeWidth="1.5"/>
      {/* Drive bays */}
      {[0,1,2,3].map(i => (
        <rect key={i} x={8 + i*7} y="15" width="5" height="8" rx="1" fill={color} fillOpacity={0.19} stroke={color} strokeOpacity={0.38} strokeWidth="0.8"/>
      ))}
      {/* CD/tape drive */}
      <rect x="8" y="26" width="18" height="5" rx="1" fill={color} fillOpacity={0.13} stroke={color} strokeOpacity={0.31} strokeWidth="0.8"/>
      {/* Status LEDs */}
      <circle cx="34" cy="28" r="1.5" fill="rgb(var(--color-success))"/>
      <circle cx="38" cy="28" r="1.5" fill={color} opacity="0.5"/>
      {/* Power button */}
      <circle cx="40" cy="18" r="3" stroke={color} strokeWidth="1.2" fill="none"/>
      <line x1="40" y1="15.5" x2="40" y2="18" stroke={color} strokeWidth="1.2"/>
    </svg>
  );
}

/** PLC — DIN-rail mounted industrial controller */
function PLCIcon({ size = 36, color = "rgb(var(--color-warning))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      {/* DIN rail */}
      <rect x="2" y="6" width="44" height="4" rx="1" fill={color} fillOpacity={0.31} stroke={color} strokeOpacity={0.50} strokeWidth="1"/>
      {/* Controller body */}
      <rect x="8" y="10" width="32" height="30" rx="2" fill={color} fillOpacity={0.08} stroke={color} strokeWidth="1.5"/>
      {/* Display/HMI area */}
      <rect x="11" y="13" width="14" height="10" rx="1" fill="rgb(var(--color-background))" stroke={color} strokeOpacity={0.38} strokeWidth="0.8"/>
      <line x1="13" y1="16" x2="23" y2="16" stroke={color} strokeOpacity={0.50} strokeWidth="0.7"/>
      <line x1="13" y1="18" x2="21" y2="18" stroke={color} strokeOpacity={0.38} strokeWidth="0.7"/>
      <line x1="13" y1="20" x2="22" y2="20" stroke={color} strokeOpacity={0.38} strokeWidth="0.7"/>
      {/* I/O terminals */}
      {[0,1,2,3,4].map(i => (
        <rect key={i} x={11 + i*4} y="27" width="3" height="5" rx="0.5" fill={color} fillOpacity={0.19} stroke={color} strokeOpacity={0.38} strokeWidth="0.6"/>
      ))}
      {/* Status LEDs */}
      <circle cx="30" cy="15" r="1.5" fill="rgb(var(--color-success))"/>
      <circle cx="34" cy="15" r="1.5" fill={color}/>
      <circle cx="30" cy="19" r="1.5" fill={color} opacity="0.4"/>
      {/* Comms port */}
      <rect x="27" y="25" width="8" height="5" rx="1" fill={color} fillOpacity={0.13} stroke={color} strokeOpacity={0.31} strokeWidth="0.8"/>
    </svg>
  );
}

/** Endpoint — desktop computer */
function EndpointIcon({ size = 32, color = "rgb(var(--color-muted))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      {/* Monitor */}
      <rect x="6" y="6" width="36" height="26" rx="2" fill={color} fillOpacity={0.08} stroke={color} strokeWidth="1.5"/>
      <rect x="9" y="9" width="30" height="20" rx="1" fill="rgb(var(--color-background))"/>
      {/* Screen glow */}
      <rect x="12" y="12" width="24" height="14" rx="1" fill={color} fillOpacity={0.06}/>
      <line x1="14" y1="16" x2="30" y2="16" stroke={color} strokeOpacity={0.31} strokeWidth="1"/>
      <line x1="14" y1="19" x2="28" y2="19" stroke={color} strokeOpacity={0.25} strokeWidth="1"/>
      <line x1="14" y1="22" x2="26" y2="22" stroke={color} strokeOpacity={0.19} strokeWidth="1"/>
      {/* Stand */}
      <line x1="24" y1="32" x2="24" y2="38" stroke={color} strokeWidth="2"/>
      <rect x="16" y="37" width="16" height="3" rx="1" fill={color} fillOpacity={0.38} stroke={color} strokeWidth="1"/>
    </svg>
  );
}

/** Unknown device */
function UnknownIcon({ size = 32, color = "rgb(var(--color-muted-dim))" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      <rect x="8" y="8" width="32" height="32" rx="4" fill={color} fillOpacity={0.13} stroke={color} strokeWidth="1.5" strokeDasharray="4 2"/>
      <text x="24" y="30" textAnchor="middle" fontSize="18" fill={color} fontFamily="monospace">?</text>
    </svg>
  );
}

// ── Device visual config ──────────────────────────────────────────────────────

interface DeviceConfig {
  color: string;
  bg: string;
  Icon: React.FC<{ size?: number; color?: string }>;
  badge: string;
  width: number;
  height: number;
}

function getDeviceConfig(): Record<DeviceType, DeviceConfig> {
  return {
    firewall: { color: cssColor("--color-danger"),     bg: cssColor("--color-danger-subtle"),   Icon: FirewallIcon, badge: "FIREWALL", width: 170, height: 100 },
    router:   { color: cssColor("--color-cat-host"),    bg: cssColor("--color-surface"),         Icon: RouterIcon,   badge: "ROUTER",   width: 160, height: 95  },
    switch:   { color: cssColor("--color-accent"),      bg: cssColor("--color-surface"),         Icon: SwitchIcon,   badge: "SWITCH",   width: 200, height: 105 },
    server:   { color: cssColor("--color-success"),     bg: cssColor("--color-surface"),         Icon: ServerIcon,   badge: "SERVER",   width: 155, height: 88  },
    plc:      { color: cssColor("--color-shell-text"),  bg: cssColor("--color-surface"),         Icon: PLCIcon,      badge: "PLC/RTU",  width: 155, height: 88  },
    endpoint: { color: cssColor("--color-muted"),       bg: cssColor("--color-surface"),         Icon: EndpointIcon, badge: "HOST",     width: 145, height: 80  },
    unknown:  { color: cssColor("--color-muted-dim"),   bg: cssColor("--color-surface"),         Icon: UnknownIcon,  badge: "DEVICE",   width: 145, height: 80  },
  };
}

// ── Custom device node ────────────────────────────────────────────────────────

interface DeviceNodeData extends TopologyNode {
  onSelect: (node: TopologyNode) => void;
}

function DeviceNode({ data }: { data: DeviceNodeData }) {
  const DEVICE_CONFIG = getDeviceConfig();
  const cfg = DEVICE_CONFIG[data.type] ?? DEVICE_CONFIG.unknown;
  const { Icon } = cfg;
  const isSwitch = data.type === "switch";

  return (
    <div
      onClick={() => data.onSelect(data)}
      style={{
        minWidth: cfg.width,
        background: cfg.bg,
        border: `2px solid ${cfg.color}`,
        borderRadius: 8,
        padding: "8px 10px",
        cursor: "pointer",
        userSelect: "none",
        boxShadow: `0 0 10px ${cfg.color}22`,
      }}
      title={`${data.label} · ${data.vendor} · ${data.packets} pkts`}
    >
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />

      {/* Symbol + info row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {/* Cisco-style SVG symbol */}
        <div style={{
          flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: cfg.color + "12",
          border: `1px solid ${cfg.color}30`,
          borderRadius: 6,
          padding: isSwitch ? "4px 6px" : "4px",
        }}>
          <Icon
            size={isSwitch ? 40 : 34}
            color={cfg.color}
          />
        </div>

        {/* Text info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Badge + VLAN */}
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 2 }}>
            <span style={{ fontSize: 7, color: cfg.color, fontWeight: 700, letterSpacing: "0.1em" }}>
              {cfg.badge}
            </span>
            {data.vlan && (
              <span style={{
                fontSize: 7, color: cfg.color,
                background: cfg.color + "20",
                padding: "0 4px", borderRadius: 3,
                border: `1px solid ${cfg.color}40`,
              }}>
                VLAN {data.vlan}
              </span>
            )}
          </div>

          {/* IP / Primary Address */}
          <div style={{
            fontSize: 10, color: cssColor("--color-foreground"),
            fontFamily: "monospace", fontWeight: 600,
            lineHeight: 1.3, wordBreak: "break-all",
          }}>
            {data.ip || data.label}
          </div>

          {/* Hostname underneath IP */}
          {data.hostname && data.hostname !== data.ip && (
            <div style={{ fontSize: 8, color: cssColor("--color-muted"), fontFamily: "monospace", marginTop: 2, wordBreak: "break-all" }}>
              {data.hostname}
            </div>
          )}

          {/* Label (if different from IP and Hostname) */}
          {data.label && data.label !== data.ip && data.label !== data.hostname && (
            <div style={{ fontSize: 8, color: cssColor("--color-muted-dim"), fontFamily: "monospace", marginTop: 1 }}>
              {data.label}
            </div>
          )}

          {/* Vendor / platform */}
          {data.vendor !== "Unknown" && (
            <div style={{ fontSize: 8, color: cssColor("--color-muted-dim"), marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {data.vendor}{data.platform ? ` · ${data.platform}` : ""}
            </div>
          )}
        </div>
      </div>

      {/* Switch: port indicator row */}
      {isSwitch && data.ports.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 2, marginTop: 6 }}>
          {data.ports.slice(0, 16).map((port, i) => (
            <div
              key={i}
              title={port}
              style={{
                width: 14, height: 8,
                background: cfg.color + "35",
                border: `1px solid ${cfg.color}60`,
                borderRadius: 2,
                fontSize: 5, color: cfg.color,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              ▪
            </div>
          ))}
          {data.ports.length > 16 && (
            <span style={{ fontSize: 7, color: cssColor("--color-muted-dim"), alignSelf: "center" }}>
              +{data.ports.length - 16}
            </span>
          )}
        </div>
      )}

      {/* Protocol pills */}
      {data.protocols.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 2, marginTop: 4 }}>
          {data.protocols.slice(0, 3).map((p) => (
            <span key={p} style={{
              fontSize: 7, color: cssColor("--color-muted"),
              background: cssColor("--color-surface-hover"), padding: "0 3px", borderRadius: 2,
            }}>
              {p}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Custom port-labeled edge ──────────────────────────────────────────────────

function PortEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition, data, markerEnd, animated, style,
}: EdgeProps) {
  const [edgePath] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY,
    sourcePosition, targetPosition, borderRadius: 12,
  });

  const srcPort = (data as Record<string, unknown>)?.source_port as string | undefined;
  const dstPort = (data as Record<string, unknown>)?.target_port as string | undefined;
  const edgeType = (data as Record<string, unknown>)?.edge_type as string | undefined;
  const isInferred = edgeType === "inferred";

  // Place port labels 15% and 85% along the straight vector
  const sx = sourceX + (targetX - sourceX) * 0.15;
  const sy = sourceY + (targetY - sourceY) * 0.15;
  const dx = sourceX + (targetX - sourceX) * 0.85;
  const dy = sourceY + (targetY - sourceY) * 0.85;

  const labelStyle: React.CSSProperties = {
    position: "absolute",
    pointerEvents: "none",
    fontSize: 8,
    fontFamily: "monospace",
    color: cssColor("--color-muted"),
    background: cssColor("--color-background"),
    padding: "0 3px",
    borderRadius: 2,
    border: `1px solid ${cssColor("--color-surface-hover")}`,
    whiteSpace: "nowrap",
  };

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        className={animated ? "ns-flow-animated" : ""}
        style={{
          stroke: isInferred ? cssColor("--color-border") : cssColor("--color-border-hover"),
          strokeWidth: isInferred ? 1 : 1.5,
          strokeDasharray: isInferred && !animated ? "5 3" : undefined,
          ...style,
        }}
      />
      {animated && (
        <circle r="3" fill={cssColor("--color-accent")} style={{ filter: "drop-shadow(0 0 3px rgb(var(--color-accent)))" }}>
          <animateMotion dur={isInferred ? "3s" : "1.5s"} repeatCount="indefinite" path={edgePath} />
        </circle>
      )}
      <EdgeLabelRenderer>
        {srcPort && (
          <div
            className="nodrag nopan"
            style={{ ...labelStyle, transform: `translate(-50%,-50%) translate(${sx}px,${sy}px)` }}
          >
            {srcPort}
          </div>
        )}
        {dstPort && (
          <div
            className="nodrag nopan"
            style={{ ...labelStyle, transform: `translate(-50%,-50%) translate(${dx}px,${dy}px)` }}
          >
            {dstPort}
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes: NodeTypes = { device: DeviceNode };
const edgeTypes: EdgeTypes = { port: PortEdge };

// ── Dagre layout ──────────────────────────────────────────────────────────────

function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR",
): Node[] {
  const DEVICE_CONFIG = getDeviceConfig();
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    ranksep: direction === "TB" ? 100 : 80,
    nodesep: direction === "TB" ? 55 : 40,
    marginx: 40,
    marginy: 40,
  });

  for (const n of nodes) {
    const cfg = DEVICE_CONFIG[(n.data as unknown as TopologyNode).type ?? "unknown"] ?? DEVICE_CONFIG.unknown;
    g.setNode(n.id, { width: cfg.width + 20, height: cfg.height + 20 });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    const cfg = DEVICE_CONFIG[(n.data as unknown as TopologyNode).type ?? "unknown"] ?? DEVICE_CONFIG.unknown;
    return {
      ...n,
      position: { x: pos.x - cfg.width / 2, y: pos.y - cfg.height / 2 },
    };
  });
}

// ── Confidence badge ──────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence }: { confidence: NetworkTopology["confidence"] }) {
  if (confidence === "high")
    return (
      <span className="flex items-center gap-1 text-[10px] text-success">
        <CheckCircle className="w-3 h-3" /> CDP/LLDP confirmed
      </span>
    );
  if (confidence === "medium")
    return (
      <span className="flex items-center gap-1 text-[10px] text-warning">
        <AlertTriangle className="w-3 h-3" /> Gateway inferred
      </span>
    );
  return (
    <span className="flex items-center gap-1 text-[10px] text-muted">
      <Info className="w-3 h-3" /> Topology estimated
    </span>
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ node, onClose }: { node: TopologyNode; onClose: () => void }) {
  const DEVICE_CONFIG = getDeviceConfig();
  const cfg = DEVICE_CONFIG[node.type] ?? DEVICE_CONFIG.unknown;
  const { Icon } = cfg;

  return (
    <div
      className="absolute top-3 right-3 z-10 w-64 bg-surface border border-border rounded-lg shadow-xl text-xs"
      style={{ maxHeight: "calc(100% - 24px)", overflowY: "auto" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <Icon size={12} color={cfg.color} />
          <span className="font-semibold text-foreground">{node.label}</span>
        </div>
        <button onClick={onClose} className="text-muted hover:text-foreground">
          <X className="w-3 h-3" />
        </button>
      </div>

      <div className="p-3 space-y-2">
        {/* Identity */}
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <span className="text-muted">Type</span>
          <span style={{ color: cfg.color }} className="font-semibold">{cfg.badge}</span>

          {node.ip && <><span className="text-muted">IP</span><span className="font-mono text-foreground">{node.ip}</span></>}
          {node.mac && <><span className="text-muted">MAC</span><span className="font-mono text-foreground">{node.mac}</span></>}
          {node.vendor !== "Unknown" && <><span className="text-muted">Vendor</span><span className="text-foreground">{node.vendor}</span></>}
          {node.platform && <><span className="text-muted">OS / Model</span><span className="text-foreground">{node.platform}</span></>}
          {node.hostname && <><span className="text-muted">Hostname</span><span className="text-foreground">{node.hostname}</span></>}
          {node.netbios && <><span className="text-muted">NetBIOS</span><span className="text-foreground">{node.netbios}</span></>}
          {node.vlan && <><span className="text-muted">VLAN</span><span className="text-foreground">{node.vlan}</span></>}
          {node.packets > 0 && <><span className="text-muted">Packets</span><span className="text-foreground">{node.packets.toLocaleString()}</span></>}
          {node.is_gateway && <><span className="text-muted">Role</span><span className="text-success">Gateway</span></>}
        </div>

        {/* Ports */}
        {node.ports.length > 0 && (
          <div>
            <div className="text-muted mb-1">Ports ({node.ports.length})</div>
            <div className="space-y-0.5 max-h-28 overflow-y-auto">
              {node.ports.map((p, i) => (
                <div key={i} className="font-mono text-foreground bg-background px-2 py-0.5 rounded text-[10px]">
                  {p}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Protocols */}
        {node.protocols.length > 0 && (
          <div>
            <div className="text-muted mb-1">Protocols</div>
            <div className="flex flex-wrap gap-1">
              {node.protocols.map((p) => (
                <span key={p} className="bg-background border border-border px-1.5 py-0.5 rounded text-foreground text-[10px]">
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="absolute bottom-14 left-3 z-10 bg-surface border border-border rounded-lg p-2 text-[9px] space-y-1">
      {(["firewall", "router", "switch", "server", "plc", "endpoint"] as DeviceType[]).map((t) => {
        const DEVICE_CONFIG = getDeviceConfig();
        const cfg = DEVICE_CONFIG[t];
        const { Icon } = cfg;
        return (
          <div key={t} className="flex items-center gap-1.5">
            <Icon size={16} color={cfg.color} />
            <span className="text-muted">{cfg.badge}</span>
          </div>
        );
      })}
      <div className="border-t border-border pt-1 mt-1 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <div style={{ width: 16, height: 1.5, background: cssColor("--color-border-hover") }} />
          <span className="text-muted">Confirmed link</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div style={{ width: 16, height: 1, background: cssColor("--color-border"), border: "none", borderTop: `1px dashed ${cssColor("--color-border")}` }} />
          <span className="text-muted">Inferred link</span>
        </div>
      </div>
    </div>
  );
}

// ── Inner component (must live inside ReactFlowProvider) ──────────────────────

function TopologyInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [topo, setTopo]     = useState<NetworkTopology | null>(null);
  const [loading, setLoading]   = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanInput, setScanInput] = useState("");
  const [showScanInput, setShowScanInput] = useState(false);
  const [error, setError]   = useState("");
  const [selected, setSelected] = useState<TopologyNode | null>(null);
  const [filterText, setFilterText] = useState("");
  const [filterProto, setFilterProto] = useState("");
  const [layoutDir, setLayoutDir] = useState<"TB" | "LR">("TB");
  const containerRef = useRef<HTMLDivElement>(null);
  const { fitView } = useReactFlow();

  // Contextual "Blast Radius" Highlighting
  useEffect(() => {
    if (!topo) return;

    if (!selected) {
      setNodes((nds) => nds.map((n) => ({ ...n, style: { ...n.style, opacity: 1, filter: "none", transition: "opacity 0.3s, filter 0.3s" } })));
      setEdges((eds) => eds.map((e) => ({ ...e, animated: true, style: { ...e.style, opacity: 1, strokeWidth: undefined, transition: "opacity 0.3s, stroke-width 0.3s" } })));
      return;
    }

    const connectedIds = new Set<string>([selected.id]);
    for (const e of topo.edges) {
      if (e.source === selected.id) connectedIds.add(e.target);
      if (e.target === selected.id) connectedIds.add(e.source);
    }

    setNodes((nds) =>
      nds.map((n) => {
        const d = n.data as unknown as TopologyNode;
        const isFocus = selected ? connectedIds.has(n.id) : true;
        
        let isMatch = true;
        if (filterProto && !d.protocols?.includes(filterProto)) isMatch = false;
        if (filterText) {
          const term = filterText.toLowerCase();
          if (
            !d.ip?.toLowerCase().includes(term) &&
            !d.mac?.toLowerCase().includes(term) &&
            !d.label?.toLowerCase().includes(term) &&
            !d.hostname?.toLowerCase().includes(term) &&
            !d.platform?.toLowerCase().includes(term) &&
            !d.type?.toLowerCase().includes(term)
          ) {
            isMatch = false;
          }
        }

        const visible = isFocus && isMatch;
        return {
          ...n,
          style: {
            ...n.style,
            opacity: visible ? 1 : 0.1,
            filter: visible ? "none" : "grayscale(100%)",
            transition: "opacity 0.3s, filter 0.3s",
          },
        };
      })
    );

    setEdges((eds) =>
      eds.map((e) => {
        const isFocus = selected ? (e.source === selected.id || e.target === selected.id) : true;

        // An edge is considered a match if BOTH source and target match the text filter (if active),
        // or if the edge itself carries the protocol (we approximate by checking the connected nodes for now, or just leave it visible if endpoints are visible)
        // A simpler approach: edge is visible if its source or target is visible
        
        let isMatch = true;
        if (filterProto) {
          const sNode = topo.nodes.find(n => n.id === e.source);
          const tNode = topo.nodes.find(n => n.id === e.target);
          if (!sNode?.protocols.includes(filterProto) && !tNode?.protocols.includes(filterProto)) isMatch = false;
        }

        const visible = isFocus && isMatch;

        return {
          ...e,
          animated: isFocus,
          style: {
            ...e.style,
            opacity: visible ? 1 : 0.05,
            strokeWidth: selected && isFocus ? 2 : undefined,
            transition: "opacity 0.3s, stroke-width 0.3s",
          },
        };
      })
    );
  }, [selected, topo, setNodes, setEdges, filterText, filterProto]);

  const buildFlow = useCallback(
    (data: NetworkTopology, dir: "TB" | "LR") => {
      const rfNodes: Node[] = data.nodes.map((n) => ({
        id: n.id,
        type: "device",
        position: { x: 0, y: 0 },
        data: {
          ...n,
          onSelect: setSelected,
        },
      }));

      const rfEdges: Edge[] = data.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "port",
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 10, color: cssColor("--color-border-hover") },
        data: {
          source_port: e.source_port,
          target_port: e.target_port,
          edge_type: e.edge_type,
          vlan: e.vlan,
        },
      }));

      const laid = applyDagreLayout(rfNodes, rfEdges, dir);
      setNodes(laid);
      setEdges(rfEdges);
      setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 80);
    },
    [setNodes, setEdges, fitView],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchTopology();
      setTopo(data);
      buildFlow(data, layoutDir);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to load topology.");
    } finally {
      setLoading(false);
    }
  }, [layoutDir, buildFlow]);

  const scan = useCallback(async () => {
    setScanning(true);
    setError("");
    try {
      const data = await scanTopology(scanInput.trim() || undefined);
      setTopo(data);
      buildFlow(data, layoutDir);
      setShowScanInput(false);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Scan failed.");
    } finally {
      setScanning(false);
    }
  }, [scanInput, layoutDir, buildFlow]);

  // Reload with new layout direction
  useEffect(() => {
    if (topo) buildFlow(topo, layoutDir);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutDir]);

  // Auto-load on mount
  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col h-full relative">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border bg-surface shrink-0 flex-wrap">
        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-foreground border border-border rounded transition-colors disabled:opacity-40"
          title="Analyze current capture"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Analyzing…" : "Analyze Capture"}
        </button>

        {/* Scan trigger */}
        {showScanInput ? (
          <div className="flex items-center gap-1">
            <input
              value={scanInput}
              onChange={(e) => setScanInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") scan(); if (e.key === "Escape") setShowScanInput(false); }}
              placeholder="192.168.1.0/24 (auto-detect if blank)"
              className="text-xs bg-background border border-border rounded px-2 py-1 w-52 focus:outline-none focus:border-accent text-foreground placeholder-muted"
              autoFocus
            />
            <button
              onClick={scan}
              disabled={scanning}
              className="px-2 py-1 text-xs bg-accent text-white rounded disabled:opacity-40"
            >
              {scanning ? "Scanning…" : "Scan"}
            </button>
            <button onClick={() => setShowScanInput(false)} className="text-muted hover:text-foreground">
              <X className="w-3 h-3" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowScanInput(true)}
            disabled={scanning}
            className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-foreground border border-border rounded transition-colors disabled:opacity-40"
            title="Run active network scan to discover devices"
          >
            <Search className="w-3 h-3" />
            Scan Network
          </button>
        )}

        <span className="text-border mx-1">|</span>

        {/* Filters */}
        <input
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          placeholder="Filter (IP, OS, MAC…)"
          className="text-xs bg-background border border-border rounded px-2 py-1 w-36 focus:outline-none focus:border-accent text-foreground placeholder-muted"
        />
        <select
          value={filterProto}
          onChange={(e) => setFilterProto(e.target.value)}
          className="text-xs bg-background border border-border rounded px-2 py-1 focus:outline-none focus:border-accent text-foreground"
        >
          <option value="">All Protocols</option>
          {Array.from(new Set(topo?.nodes.flatMap(n => n.protocols) || [])).sort().map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <span className="text-border mx-1">|</span>

        {/* Layout toggle */}
        <button
          onClick={() => setLayoutDir((d) => (d === "TB" ? "LR" : "TB"))}
          className="px-2 py-1 text-xs text-muted hover:text-foreground border border-border rounded transition-colors"
          title="Toggle layout direction"
        >
          {layoutDir === "TB" ? "↕ TB" : "↔ LR"}
        </button>

        {/* Stats + confidence */}
        {topo && (
          <div className="flex items-center gap-3 ml-auto text-xs text-muted">
            <span>{topo.total_devices} devices</span>
            {topo.vlans.length > 0 && <span>{topo.vlans.length} VLANs</span>}
            {topo.scan_hosts_found !== undefined && (
              <span className="text-success">{topo.scan_hosts_found} alive</span>
            )}
            <ConfidenceBadge confidence={topo.confidence} />
          </div>
        )}
      </div>

      {/* Error bar */}
      {error && (
        <div className="px-3 py-1 text-xs text-danger border-b border-border bg-surface shrink-0">
          {error}
        </div>
      )}

      {/* ReactFlow canvas */}
      <div ref={containerRef} className="flex-1 relative min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background color={cssColor("--color-surface-hover")} gap={20} />
          <Controls />
          <MiniMap
            nodeColor={(n) => {
              const t = (n.data as unknown as TopologyNode)?.type ?? "unknown";
              return getDeviceConfig()[t]?.color ?? cssColor("--color-muted-dim");
            }}
            style={{ background: cssColor("--color-background"), border: `1px solid ${cssColor("--color-surface-hover")}` }}
          />
        </ReactFlow>

        {/* Device detail panel */}
        {selected && (
          <DetailPanel node={selected} onClose={() => setSelected(null)} />
        )}

        {/* Legend */}
        <Legend />

        {/* Empty state */}
        {!loading && nodes.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted pointer-events-none">
            <Network className="w-10 h-10 mb-3 opacity-20" />
            <p className="text-sm">No topology data yet</p>
            <p className="text-xs mt-1 opacity-70">
              Analyze a capture or run a network scan to discover devices
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Public export (self-contained with own ReactFlowProvider) ─────────────────

export function NetworkTopologyDiagram() {
  return (
    <ReactFlowProvider>
      <TopologyInner />
    </ReactFlowProvider>
  );
}
