"""
Traffic map tool: build a host/flow topology summary from captured packets.

Returns a JSON summary the LLM can reason about and describe — same graph
data that the frontend Traffic Map tab renders visually.
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict

from agent.tools.registry import register, ToolDef, MAX_OUTPUT


def _safe(value: object, max_len: int = 80) -> str:
    s = str(value) if value is not None else ""
    return "".join(c for c in s if c.isprintable())[:max_len]


def _is_private(ip: str) -> bool:
    return (
        ip.startswith("192.168.")
        or ip.startswith("10.")
        or ip.startswith("172.")
        or ip in ("127.0.0.1", "::1", "", "N/A")
    )


async def run_traffic_map_summary(args: str = "") -> str:
    """
    Build a topology summary from the current packet store.

    Optional arg: an integer limit for top-N hosts/flows (default 10).
    """
    from api.routes import _packets

    pkts = list(_packets)
    if not pkts:
        return json.dumps({"error": "No packets captured yet."})

    # Parse optional limit arg
    limit = 10
    try:
        v = int(args.strip())
        if 1 <= v <= 50:
            limit = v
    except (ValueError, TypeError):
        pass

    host_packets: Counter[str] = Counter()
    host_bytes: Counter[str] = Counter()
    host_protos: dict[str, set[str]] = defaultdict(set)

    flow_packets: Counter[tuple[str, str]] = Counter()
    flow_bytes: Counter[tuple[str, str]] = Counter()
    flow_protos: dict[tuple[str, str], set[str]] = defaultdict(set)

    proto_dist: Counter[str] = Counter()

    for p in pkts:
        src = _safe(p.get("src_ip", ""))
        dst = _safe(p.get("dst_ip", ""))
        proto = _safe(p.get("protocol", "?"))
        length = p.get("length") or 0

        proto_dist[proto] += 1

        for ip in (src, dst):
            if not ip:
                continue
            host_packets[ip] += 1
            host_bytes[ip] += length
            if proto:
                host_protos[ip].add(proto)

        if src and dst and src != dst:
            key = (src, dst)
            flow_packets[key] += 1
            flow_bytes[key] += length
            if proto:
                flow_protos[key].add(proto)

    top_hosts = [
        {
            "ip": ip,
            "packets": host_packets[ip],
            "bytes": host_bytes[ip],
            "protocols": sorted(host_protos[ip]),
            "is_external": not _is_private(ip),
        }
        for ip, _ in host_packets.most_common(limit)
    ]

    top_flows = [
        {
            "src": k[0],
            "dst": k[1],
            "packets": flow_packets[k],
            "bytes": flow_bytes[k],
            "protocols": sorted(flow_protos[k]),
        }
        for k, _ in flow_packets.most_common(limit)
    ]

    external_hosts = sorted(
        ip for ip in host_packets if not _is_private(ip)
    )

    result = {
        "total_hosts": len(host_packets),
        "total_flows": len(flow_packets),
        "total_packets": len(pkts),
        "top_hosts": top_hosts,
        "top_flows": top_flows,
        "external_hosts": external_hosts[:20],
        "protocol_distribution": dict(proto_dist.most_common(10)),
    }

    out = json.dumps(result, separators=(",", ":"))
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n...[truncated]"
    return out


# ── Registration ──────────────────────────────────────────────────────────────

_TRAFFICMAP_KW = {
    "traffic map", "trafficmap", "topology", "host graph", "network graph",
    "node graph", "visualize traffic", "visualise traffic", "show map",
    "open map", "who is talking", "hosts and flows", "flow map",
    "network topology", "host topology", "ip graph", "communication map",
    "traffic visualization", "open traffic map", "traffic tab",
}

register(ToolDef(
    name="traffic_map_summary",
    category="trafficmap",
    description="build a host/flow topology summary (hosts, flows, external IPs, protocol distribution)",
    args_spec="[limit]",
    runner=run_traffic_map_summary,
    safety="read",
    keywords=_TRAFFICMAP_KW,
    needs_packets=True,
))
