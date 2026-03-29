/**
 * InlineChatMap — compact ReactFlow traffic map rendered inside a chat bubble.
 * Takes the JSON output of traffic_map_summary and renders it as a node graph.
 */
import { useMemo } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MarkerType,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import type { TrafficMapSummary } from "../lib/api";

// ── Protocol colours (mirrors TrafficMap.tsx) ────────────────────────────────

const PROTO_COLORS: Record<string, string> = {
  TCP:    "rgb(var(--color-accent))",
  UDP:    "rgb(var(--color-success))",
  ICMP:   "rgb(var(--color-severe))",
  ARP:    "rgb(var(--color-warning))",
  DNS:    "rgb(var(--color-purple))",
  HTTP:   "rgb(var(--color-protocol-http))",
  HTTPS:  "rgb(var(--color-success))",
  TLS:    "rgb(var(--color-success))",
  Modbus: "rgb(var(--color-danger))",
  DNP3:   "rgb(var(--color-tool))",
};

function edgeColor(protocols: string[]): string {
  for (const p of protocols) {
    if (PROTO_COLORS[p]) return PROTO_COLORS[p];
  }
  return "rgb(var(--color-muted-extra))";
}

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
}

// ── Custom host node (compact version) ───────────────────────────────────────

interface HostNodeData extends Record<string, unknown> {
  label: string;
  packets: number;
  bytes: number;
  protocols: string[];
  isExternal: boolean;
}

function HostNode({ data }: { data: HostNodeData }) {
  const size = Math.max(36, Math.min(64, 26 + Math.log2(data.packets + 1) * 5));
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
        alignItems: "center",
        justifyContent: "center",
        fontSize: 7,
        color: "rgb(var(--color-foreground))",
        textAlign: "center",
        padding: 2,
        cursor: "default",
        position: "relative",
      }}
      title={`${data.label}\n${data.packets} pkts · ${formatBytes(data.bytes)}\n${data.protocols.join(", ")}`}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div
        style={{
          fontFamily: "monospace",
          fontSize: 7,
          wordBreak: "break-all",
          lineHeight: 1.1,
        }}
      >
        {data.label}
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = { host: HostNode };

// ── Dagre layout ──────────────────────────────────────────────────────────────

function applyDagre(
  nodes: Node[],
  edges: Edge[]
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 80 });

  for (const n of nodes) {
    const size = Math.max(
      36,
      Math.min(
        64,
        26 + Math.log2(((n.data as HostNodeData).packets ?? 1) + 1) * 5
      )
    );
    g.setNode(n.id, { width: size, height: size });
  }
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const pos = g.node(n.id);
      return {
        ...n,
        position: { x: pos.x - pos.width / 2, y: pos.y - pos.height / 2 },
      };
    }),
    edges,
  };
}

// ── Inner map (needs to be inside ReactFlowProvider) ─────────────────────────

function InnerMap({ data }: { data: TrafficMapSummary }) {
  const { initialNodes, initialEdges } = useMemo(() => {
    const rawNodes: Node[] = data.top_hosts.map((h) => ({
      id: h.ip,
      type: "host",
      position: { x: 0, y: 0 },
      data: {
        label: h.ip,
        packets: h.packets,
        bytes: h.bytes,
        protocols: h.protocols,
        isExternal: h.is_external,
      } satisfies HostNodeData,
    }));

    const rawEdges: Edge[] = data.top_flows
      .filter(
        (f) =>
          data.top_hosts.some((h) => h.ip === f.src) &&
          data.top_hosts.some((h) => h.ip === f.dst)
      )
      .map((f, i) => ({
        id: `e${i}`,
        source: f.src,
        target: f.dst,
        label: f.protocols[0] ?? "",
        animated: false,
        style: {
          stroke: edgeColor(f.protocols),
          strokeWidth: Math.max(1, Math.min(3, Math.log2(f.packets + 1))),
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: edgeColor(f.protocols),
        },
        labelStyle: {
          fill: "rgb(var(--color-muted))",
          fontSize: 7,
          fontFamily: "monospace",
        },
        labelBgStyle: { fill: "transparent" },
      }));

    const { nodes, edges } = applyDagre(rawNodes, rawEdges);
    return { initialNodes: nodes, initialEdges: edges };
  }, [data]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.3}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="rgb(var(--color-border))" gap={20} size={0.5} />
      <Controls
        showInteractive={false}
        style={{ bottom: 8, right: 8, left: "auto", top: "auto" }}
      />
    </ReactFlow>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

export function InlineChatMap({ data }: { data: TrafficMapSummary }) {
  if (!data.top_hosts || data.top_hosts.length === 0) return null;

  return (
    <div
      className="w-full rounded-lg border border-border bg-background overflow-hidden my-2"
      style={{ height: 280 }}
    >
      {/* Stats bar */}
      <div className="flex gap-4 px-3 py-1.5 bg-surface border-b border-border text-[10px] text-muted font-mono">
        <span>
          <span className="text-accent">{data.total_hosts}</span> hosts
        </span>
        <span>
          <span className="text-success">{data.total_flows}</span> flows
        </span>
        <span>
          <span className="text-foreground">
            {data.total_packets.toLocaleString()}
          </span>{" "}
          packets
        </span>
        {Object.entries(data.protocol_distribution)
          .slice(0, 4)
          .map(([proto, count]) => (
            <span key={proto} style={{ color: PROTO_COLORS[proto] ?? "rgb(var(--color-muted))" }}>
              {proto} {count}
            </span>
          ))}
      </div>
      {/* Graph */}
      <div style={{ height: "calc(100% - 29px)" }}>
        <ReactFlowProvider>
          <InnerMap data={data} />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
