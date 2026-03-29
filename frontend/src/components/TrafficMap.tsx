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
  MarkerType,
  type Node,
  type Edge,
  type NodeTypes,
  Handle,
  Position,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import { toPng } from "html-to-image";
import { fetchPackets } from "../lib/api";
import type { Packet } from "../store/useStore";
import { RefreshCw, Maximize2, Image, FileText, Workflow, Network, GitBranch } from "lucide-react";
import { NetworkTopologyDiagram } from "./NetworkTopologyDiagram";

// ─── Custom host node ─────────────────────────────────────────────────────────

interface HostNodeData {
  label: string;
  hostname?: string;
  packets: number;
  bytes: number;
  protocols: string[];
  isExternal: boolean;
}

function HostNode({ data }: { data: HostNodeData }) {
  const size = Math.max(40, Math.min(80, 30 + Math.log2(data.packets + 1) * 6));
  const borderColor = data.isExternal ? "rgb(var(--color-danger))" : "rgb(var(--color-accent))";
  const bg = data.isExternal ? "rgb(var(--color-danger-subtle))" : "rgb(var(--color-surface))";

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        border: `2px solid ${borderColor}`,
        background: bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 9,
        color: "rgb(var(--color-foreground))",
        textAlign: "center",
        padding: 4,
        cursor: "default",
        position: "relative",
      }}
      title={`${data.label}\n${data.packets} pkts · ${formatBytes(data.bytes)}\nProtocols: ${data.protocols.join(", ")}`}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div style={{ fontFamily: "monospace", fontSize: 8, wordBreak: "break-all", lineHeight: 1.2 }}>
        <div style={{ fontWeight: 600 }}>{data.label}</div>
        {data.hostname && (
          <div style={{ fontSize: 7, color: "rgb(var(--color-muted))", marginTop: 1 }}>{data.hostname}</div>
        )}
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = { host: HostNode };

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

/** Detect likely private/loopback addresses */
function isPrivate(ip: string): boolean {
  return (
    ip.startsWith("192.168.") ||
    ip.startsWith("10.") ||
    ip.startsWith("172.") ||
    ip === "127.0.0.1" ||
    ip === "::1" ||
    ip === "" ||
    ip === "N/A"
  );
}

interface FlowEdge {
  src: string;
  dst: string;
  packets: number;
  bytes: number;
  protocols: Set<string>;
}

function buildGraph(packets: Packet[]) {
  const hostPackets: Record<string, number> = {};
  const hostBytes: Record<string, number> = {};
  const hostProtocols: Record<string, Set<string>> = {};
  const flows: Record<string, FlowEdge> = {};

  for (const p of packets) {
    const src = p.src_ip || "";
    const dst = p.dst_ip || "";
    if (!src && !dst) continue;

    for (const ip of [src, dst].filter(Boolean)) {
      hostPackets[ip] = (hostPackets[ip] ?? 0) + 1;
      hostBytes[ip] = (hostBytes[ip] ?? 0) + (p.length ?? 0);
      if (!hostProtocols[ip]) hostProtocols[ip] = new Set();
      if (p.protocol) hostProtocols[ip].add(p.protocol);
    }

    if (src && dst && src !== dst) {
      const key = `${src}→${dst}`;
      if (!flows[key]) {
        flows[key] = { src, dst, packets: 0, bytes: 0, protocols: new Set() };
      }
      flows[key].packets += 1;
      flows[key].bytes += p.length ?? 0;
      if (p.protocol) flows[key].protocols.add(p.protocol);
    }
  }

  return { hostPackets, hostBytes, hostProtocols, flows };
}

/** Arrange nodes in a force-inspired circular layout with inner/outer rings */
function layoutNodes(ips: string[]): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};
  if (ips.length === 0) return positions;
  if (ips.length === 1) {
    positions[ips[0]] = { x: 300, y: 300 };
    return positions;
  }

  const cx = 400, cy = 320;
  const inner = ips.slice(0, Math.min(8, ips.length));
  const outer = ips.slice(8);

  for (let i = 0; i < inner.length; i++) {
    const angle = (2 * Math.PI * i) / inner.length - Math.PI / 2;
    positions[inner[i]] = {
      x: cx + 180 * Math.cos(angle),
      y: cy + 180 * Math.sin(angle),
    };
  }
  for (let i = 0; i < outer.length; i++) {
    const angle = (2 * Math.PI * i) / outer.length - Math.PI / 2;
    positions[outer[i]] = {
      x: cx + 300 * Math.cos(angle),
      y: cy + 300 * Math.sin(angle),
    };
  }
  return positions;
}

// ─── Protocol colour palette ──────────────────────────────────────────────────

const PROTO_COLORS: Record<string, string> = {
  TCP: "rgb(var(--color-accent))",
  UDP: "rgb(var(--color-success))",
  ICMP: "rgb(var(--color-tool))",
  ARP: "rgb(var(--color-warning))",
  DNS: "rgb(var(--color-purple))",
  HTTP: "rgb(var(--color-accent-muted))",
  HTTPS: "rgb(var(--color-success-emphasis))",
  TLS: "rgb(var(--color-success-emphasis))",
  Modbus: "rgb(var(--color-danger))",
  DNP3: "rgb(var(--color-severe))",
};

function edgeColor(protocols: Set<string>): string {
  for (const p of protocols) {
    if (PROTO_COLORS[p]) return PROTO_COLORS[p];
  }
  return "rgb(var(--color-muted-dim))";
}

// ─── Dagre auto-layout ────────────────────────────────────────────────────────

type LayoutDirection = "TB" | "LR";

function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  direction: LayoutDirection = "LR",
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 100 });

  for (const n of nodes) {
    // Estimate node size from the data (same formula as HostNode)
    const pkts = (n.data as unknown as HostNodeData)?.packets ?? 0;
    const size = Math.max(40, Math.min(80, 30 + Math.log2(pkts + 1) * 6));
    g.setNode(n.id, { width: size, height: size });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const pos = g.node(n.id);
      const pkts = (n.data as unknown as HostNodeData)?.packets ?? 0;
      const size = Math.max(40, Math.min(80, 30 + Math.log2(pkts + 1) * 6));
      return { ...n, position: { x: pos.x - size / 2, y: pos.y - size / 2 } };
    }),
    edges,
  };
}

// ─── Main component ───────────────────────────────────────────────────────────

const MAX_EDGES = 80; // cap for readability
const MAX_NODES = 40;

/** Inner component — must live inside ReactFlowProvider to use useReactFlow() */
function TrafficMapInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [stats, setStats] = useState({ hosts: 0, flows: 0, packets: 0 });
  const [selected, setSelected] = useState<{ id: string; data: HostNodeData } | null>(null);
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});
  const flowContainerRef = useRef<HTMLDivElement>(null);
  const [layoutDir, setLayoutDir] = useState<LayoutDirection>("LR");
  const { fitView, getEdges } = useReactFlow();
  const [filterText, setFilterText] = useState("");
  const [filterProto, setFilterProto] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch enough packets to build a meaningful map (up to 5000)
      const res = await fetchPackets(0, 5000, "", "");
      const pkts = res.packets;

      const { hostPackets, hostBytes, hostProtocols, flows } = buildGraph(pkts);

      // Sort hosts by packet count, cap to MAX_NODES
      const sortedHosts = Object.keys(hostPackets)
        .sort((a, b) => hostPackets[b] - hostPackets[a])
        .slice(0, MAX_NODES);

      const hostSet = new Set(sortedHosts);

      // Build new positions: keep existing for known nodes, add new
      const known = positionsRef.current;
      const newIPs = sortedHosts.filter((ip) => !known[ip]);
      const freshPositions = layoutNodes(newIPs);
      const allPositions: Record<string, { x: number; y: number }> = {
        ...known,
        ...freshPositions,
      };
      positionsRef.current = allPositions;

      const newNodes: Node[] = sortedHosts.map((ip) => ({
        id: ip,
        type: "host",
        position: allPositions[ip] ?? { x: 400, y: 320 },
        data: {
          label: ip,
          packets: hostPackets[ip] ?? 0,
          bytes: hostBytes[ip] ?? 0,
          protocols: Array.from(hostProtocols[ip] ?? []),
          isExternal: !isPrivate(ip),
        } as unknown as Record<string, unknown>,
      }));

      // Filter flows to only hosts we're showing, sort by packet count, cap
      const sortedFlows = Object.values(flows)
        .filter((f) => hostSet.has(f.src) && hostSet.has(f.dst))
        .sort((a, b) => b.packets - a.packets)
        .slice(0, MAX_EDGES);

      const maxPkts = sortedFlows[0]?.packets ?? 1;

      const newEdges: Edge[] = sortedFlows.map((f) => {
        const thickness = 1 + (f.packets / maxPkts) * 5;
        const color = edgeColor(f.protocols);
        const protos = Array.from(f.protocols).join("/");
        return {
          id: `${f.src}→${f.dst}`,
          source: f.src,
          target: f.dst,
          label: `${protos} · ${f.packets}`,
          labelStyle: { fontSize: 8, fill: "rgb(var(--color-muted))" },
          labelBgStyle: { fill: "rgb(var(--color-surface))", fillOpacity: 0.85 },
          style: { stroke: color, strokeWidth: thickness, opacity: 0.85 },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color,
            width: 10,
            height: 10,
          },
          animated: f.packets > maxPkts * 0.3,
        };
      });

      setNodes(newNodes);
      setEdges(newEdges);
      setStats({
        hosts: sortedHosts.length,
        flows: sortedFlows.length,
        packets: pkts.length,
      });
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges]);

  // Auto-load on mount
  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelected({ id: node.id, data: node.data as unknown as HostNodeData });
    },
    []
  );

  const handlePaneClick = useCallback(() => setSelected(null), []);

  useEffect(() => {
    const currentEdges = getEdges();
    const connectedIds = new Set<string>();
    if (selected) {
      connectedIds.add(selected.id);
      for (const e of currentEdges) {
        if (e.source === selected.id) connectedIds.add(e.target);
        if (e.target === selected.id) connectedIds.add(e.source);
      }
    }

    setNodes((nds) => nds.map((n) => {
      const d = n.data as unknown as HostNodeData;
      const isConnectedFocus = selected ? connectedIds.has(n.id) : true;
      
      let isMatch = true;
      if (filterProto && !d.protocols?.includes(filterProto)) isMatch = false;
      if (filterText) {
        const term = filterText.toLowerCase();
        if (!n.id.toLowerCase().includes(term)) isMatch = false;
      }

      const visible = isConnectedFocus && isMatch;
      return {
        ...n,
        style: {
          ...n.style,
          opacity: visible ? 1 : 0.1,
          filter: visible ? "none" : "grayscale(100%)",
          transition: "opacity 0.3s, filter 0.3s",
        }
      };
    }));

    setEdges((eds) => eds.map((e) => {
      const isFocus = selected ? (e.source === selected.id || e.target === selected.id) : true;
      let isMatch = true;
      if (filterProto) {
         if (!e.label?.toString().includes(filterProto)) isMatch = false;
      }
      const visible = isFocus && isMatch;
      return {
        ...e,
        style: {
           ...e.style,
           opacity: visible ? 0.85 : 0.05,
           transition: "opacity 0.3s"
        }
      };
    }));
  }, [selected, filterText, filterProto, setNodes, setEdges, getEdges]);

  const autoLayout = useCallback((dir?: LayoutDirection) => {
    const direction = dir ?? layoutDir;
    setLayoutDir(direction);
    const { nodes: laid, edges: laidEdges } = getLayoutedElements(nodes, edges, direction);
    // Persist positions so refresh doesn't reset them
    for (const n of laid) {
      positionsRef.current[n.id] = n.position;
    }
    setNodes(laid);
    setEdges(laidEdges);
    requestAnimationFrame(() => fitView({ padding: 0.2, duration: 400 }));
  }, [nodes, edges, layoutDir, setNodes, setEdges, fitView]);

  const exportPng = useCallback(async () => {
    const el = flowContainerRef.current?.querySelector<HTMLElement>(".react-flow__viewport");
    if (!el) return;
    setExporting(true);
    try {
      const dataUrl = await toPng(el, {
        backgroundColor: "rgb(var(--color-background))",
        pixelRatio: 2,
        style: { transform: el.style.transform },
      });
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = `traffic-map-${Date.now()}.png`;
      a.click();
    } finally {
      setExporting(false);
    }
  }, []);

  const exportPdf = useCallback(async () => {
    const el = flowContainerRef.current?.querySelector<HTMLElement>(".react-flow__viewport");
    if (!el) return;
    setExporting(true);
    try {
      const dataUrl = await toPng(el, {
        backgroundColor: "rgb(var(--color-background))",
        pixelRatio: 2,
        style: { transform: el.style.transform },
      });
      const win = window.open("", "_blank");
      if (!win) return;
      const ts = new Date().toLocaleString();
      win.document.write(`
        <!DOCTYPE html><html>
        <head>
          <title>Traffic Map — ${ts}</title>
          <style>
            body { margin: 0; background: rgb(var(--color-background)); display: flex; flex-direction: column;
                   align-items: center; justify-content: center; min-height: 100vh; font-family: monospace; }
            h2 { color: rgb(var(--color-accent)); font-size: 14px; margin: 12px 0 8px; }
            p  { color: rgb(var(--color-muted)); font-size: 11px; margin: 0 0 12px; }
            img { max-width: 100%; border: 1px solid rgb(var(--color-border)); border-radius: 4px; }
            @media print { button { display: none !important; } }
          </style>
        </head>
        <body>
          <h2>NetScope — Traffic Map</h2>
          <p>Generated ${ts} · ${stats.hosts} hosts · ${stats.flows} flows · ${stats.packets.toLocaleString()} packets</p>
          <img src="${dataUrl}" />
          <br/>
          <button onclick="window.print()" style="margin-top:12px;padding:8px 20px;background:rgb(var(--color-accent));color:rgb(var(--color-background));border:none;border-radius:4px;cursor:pointer;font-size:12px;">
            Print / Save as PDF
          </button>
        </body></html>
      `);
      win.document.close();
    } finally {
      setExporting(false);
    }
  }, [stats]);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
        <span className="text-xs font-semibold text-foreground uppercase tracking-wider">Traffic Map</span>
        <div className="flex items-center gap-4 text-[11px] text-muted ml-2">
          <span>{stats.hosts} hosts</span>
          <span>{stats.flows} flows</span>
          <span>{stats.packets.toLocaleString()} packets</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {/* Legend */}
          <div className="flex items-center gap-3 mr-2">
            {Object.entries(PROTO_COLORS).slice(0, 5).map(([proto, color]) => (
              <span key={proto} className="flex items-center gap-1 text-[10px] text-muted">
                <span className="w-2.5 h-0.5 inline-block rounded" style={{ background: color }} />
                {proto}
              </span>
            ))}
            <span className="flex items-center gap-1 text-[10px] text-muted">
              <span className="w-2.5 h-2.5 inline-block rounded-full border border-[rgb(var(--color-danger))]" />
              External
            </span>
            <span className="flex items-center gap-1 text-[10px] text-muted">
              <span className="w-2.5 h-2.5 inline-block rounded-full border border-[rgb(var(--color-accent))]" />
              Internal
            </span>
          </div>

          <span className="text-border mx-1">|</span>

          {/* Filters */}
          <input
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Filter IP..."
            className="text-xs bg-background border border-border rounded px-2 py-1 w-28 focus:outline-none focus:border-accent text-foreground placeholder-muted"
          />
          <select
            value={filterProto}
            onChange={(e) => setFilterProto(e.target.value)}
            className="text-xs bg-background border border-border rounded px-2 py-1 focus:outline-none focus:border-accent text-foreground max-w-[120px]"
          >
            <option value="">All Protocols</option>
            {Object.keys(PROTO_COLORS).sort().map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          <span className="text-border mx-1">|</span>

          <button
            onClick={refresh}
            disabled={loading || exporting}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-accent/10 border border-accent/30 text-accent rounded hover:bg-accent/20 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Loading…" : "Refresh"}
          </button>
          {/* Auto-layout toggle: LR ↔ TB */}
          <div className="flex rounded border border-border overflow-hidden">
            <button
              onClick={() => autoLayout("LR")}
              disabled={nodes.length === 0}
              title="Auto layout: left → right"
              className={`flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors disabled:opacity-40 ${
                layoutDir === "LR"
                  ? "bg-accent/20 text-accent border-r border-border"
                  : "bg-surface text-muted hover:text-foreground border-r border-border"
              }`}
            >
              <Workflow className="w-3 h-3" />
              LR
            </button>
            <button
              onClick={() => autoLayout("TB")}
              disabled={nodes.length === 0}
              title="Auto layout: top → bottom"
              className={`flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors disabled:opacity-40 ${
                layoutDir === "TB"
                  ? "bg-accent/20 text-accent"
                  : "bg-surface text-muted hover:text-foreground"
              }`}
            >
              <Workflow className="w-3 h-3 rotate-90" />
              TB
            </button>
          </div>
          <button
            onClick={exportPng}
            disabled={exporting || nodes.length === 0}
            title="Export as PNG"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface border border-border text-muted rounded hover:text-foreground hover:border-foreground/30 transition-colors disabled:opacity-40"
          >
            <Image className="w-3 h-3" />
            PNG
          </button>
          <button
            onClick={exportPdf}
            disabled={exporting || nodes.length === 0}
            title="Export as PDF (opens print dialog)"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface border border-border text-muted rounded hover:text-foreground hover:border-foreground/30 transition-colors disabled:opacity-40"
          >
            <FileText className="w-3 h-3" />
            PDF
          </button>
        </div>
      </div>

      {/* Map area */}
      <div className="flex-1 relative" ref={flowContainerRef}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={3}
          style={{ background: "rgb(var(--color-background))" }}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="rgb(var(--color-surface-hover))" gap={24} size={1} />
          <Controls
            style={{ background: "rgb(var(--color-surface))", borderColor: "rgb(var(--color-border))" }}
            showInteractive={false}
          />
          <MiniMap
            nodeColor={(n) =>
              (n.data as unknown as HostNodeData)?.isExternal ? "rgb(var(--color-danger))" : "rgb(var(--color-accent))"
            }
            style={{ background: "rgb(var(--color-surface))", border: "1px solid rgb(var(--color-border))" }}
            maskColor="rgba(13,17,23,0.7)"
          />
        </ReactFlow>

        {/* Host detail panel */}
        {selected && (
          <div className="absolute top-3 right-3 w-52 bg-surface border border-border rounded-lg p-3 shadow-xl text-xs z-10">
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-foreground font-mono">{selected.id}</span>
              <button onClick={() => setSelected(null)} className="text-muted hover:text-foreground">×</button>
            </div>
            <div className="space-y-1 text-muted">
              <div className="flex justify-between">
                <span>Packets</span>
                <span className="text-foreground">{selected.data.packets.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span>Bytes</span>
                <span className="text-foreground">{formatBytes(selected.data.bytes)}</span>
              </div>
              <div className="flex justify-between">
                <span>Type</span>
                <span className={selected.data.isExternal ? "text-[rgb(var(--color-danger))]" : "text-accent"}>
                  {selected.data.isExternal ? "External" : "Internal"}
                </span>
              </div>
            </div>
            {selected.data.protocols.length > 0 && (
              <div className="mt-2 pt-2 border-t border-border">
                <div className="text-muted mb-1">Protocols</div>
                <div className="flex flex-wrap gap-1">
                  {selected.data.protocols.map((p) => (
                    <span
                      key={p}
                      className="px-1.5 py-0.5 rounded text-[10px] font-mono"
                      style={{
                        background: (PROTO_COLORS[p] ?? "rgb(var(--color-muted-dim))") + "22",
                        color: PROTO_COLORS[p] ?? "rgb(var(--color-muted))",
                        border: `1px solid ${(PROTO_COLORS[p] ?? "rgb(var(--color-muted-dim))")}44`,
                      }}
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Empty state */}
        {!loading && nodes.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted pointer-events-none">
            <Maximize2 className="w-10 h-10 mb-3 opacity-20" />
            <p className="text-sm">No packet data yet</p>
            <p className="text-xs mt-1 opacity-70">Start a capture or import a PCAP, then refresh</p>
          </div>
        )}
      </div>
    </div>
  );
}

type MapView = "flow" | "topology";

export function TrafficMap() {
  const [view, setView] = useState<MapView>("flow");

  return (
    <div className="flex flex-col h-full bg-background">
      {/* View toggle */}
      <div className="flex items-center gap-0 px-4 py-2 border-b border-border bg-[rgb(var(--color-background))] shrink-0">
        <button
          onClick={() => setView("flow")}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-l border transition-colors ${
            view === "flow"
              ? "bg-accent/20 text-accent border-accent/40"
              : "bg-surface text-muted border-border hover:text-foreground"
          }`}
        >
          <GitBranch className="w-3 h-3" />
          Flow Map
        </button>
        <button
          onClick={() => setView("topology")}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-r border-t border-r border-b transition-colors ${
            view === "topology"
              ? "bg-accent/20 text-accent border-accent/40"
              : "bg-surface text-muted border-border hover:text-foreground"
          }`}
        >
          <Network className="w-3 h-3" />
          Topology
        </button>
        <span className="ml-3 text-[10px] text-muted/60">
          {view === "flow"
            ? "Live host-to-host traffic flows"
            : "Physical / logical network topology from CDP · LLDP · ARP · DHCP"}
        </span>
      </div>

      {/* View content — conditional render so ReactFlow only mounts when visible.
          This ensures fitView() always runs on a properly-sized viewport and
          prevents the topology component from auto-loading while hidden. */}
      <div className="flex-1 min-h-0 flex flex-col">
        {view === "flow" ? (
          <ReactFlowProvider>
            <TrafficMapInner />
          </ReactFlowProvider>
        ) : (
          <NetworkTopologyDiagram />
        )}
      </div>
    </div>
  );
}
