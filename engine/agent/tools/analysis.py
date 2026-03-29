"""
Analysis tools: query_packets, list_insights, generate_insight, expert_analyze.
"""
from __future__ import annotations
from agent.tools.registry import register, ToolDef, MAX_OUTPUT


def _safe_str(value: object, max_len: int = 120) -> str:
    s = str(value) if value is not None else ""
    return "".join(c for c in s if c.isprintable())[:max_len]


async def run_query_packets(args: str = "") -> str:
    from agent.toon import encode_packets
    from api.routes import _packets

    parts = args.strip().split()
    protocol = ""
    limit = 20
    for p in parts:
        if p.isdigit():
            limit = min(int(p), 50)
        else:
            protocol = p.upper()

    pkts = list(_packets)
    if protocol:
        pkts = [p for p in pkts if p.get("protocol", "").upper() == protocol]

    total = len(pkts)
    sample = pkts[:limit]
    rows = []
    for p in sample:
        rows.append({
            "proto": _safe_str(p.get("protocol")),
            "src": f"{_safe_str(p.get('src_ip'))}:{_safe_str(p.get('src_port'))}",
            "dst": f"{_safe_str(p.get('dst_ip'))}:{_safe_str(p.get('dst_port'))}",
            "len": p.get("length"),
            "info": _safe_str(p.get("info", ""), 80),
        })
    out = encode_packets(rows, total)
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n... [truncated]"
    return out


async def run_list_insights(args: str = "") -> str:
    import json
    from api.routes import _insights

    items = list(_insights)[:10]
    rows = []
    for i in items:
        text = _safe_str(i.get("text", ""), 200)
        rows.append({"source": i.get("source", ""), "text": text})
    return json.dumps({"count": len(_insights), "insights": rows})


async def run_generate_insight(args: str = "") -> str:
    from api.routes import _packets, add_insight
    from agent import analyzer

    if not _packets:
        return "[generate_insight] No packets captured yet."

    mode = args.strip() or "general"
    valid = getattr(analyzer, "INSIGHT_MODES", ["general"])
    if mode not in valid:
        return f"[generate_insight] Unknown mode '{mode}'. Valid: {valid}"

    try:
        result = await analyzer.generate_insights(list(_packets), mode=mode)
        add_insight(result, mode)
        if len(result) > MAX_OUTPUT:
            result = result[:MAX_OUTPUT] + "\n... [truncated]"
        return result
    except Exception as e:
        return f"[generate_insight] Error: {e}"


async def run_expert_analyze(args: str = "") -> str:
    import asyncio
    import json
    from api.routes import _packets
    from agent import expert as expert_agent

    mode = args.strip()
    if not mode:
        return "[expert_analyze] Usage: expert_analyze <mode> (ics_audit|port_scan|flow_analysis|conversations|anomaly_detect)"

    modes = {
        "ics_audit":      expert_agent.ics_audit,
        "port_scan":      expert_agent.port_scan_detection,
        "flow_analysis":  expert_agent.flow_analysis,
        "conversations":  expert_agent.conversations,
        "anomaly_detect": expert_agent.anomaly_detect,
    }
    fn = modes.get(mode)
    if not fn:
        return f"[expert_analyze] Unknown mode '{mode}'. Valid: {list(modes)}"
    if not _packets:
        return "[expert_analyze] No packets captured yet."

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, fn, list(_packets))
    out = json.dumps(result, default=str)
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n... [truncated]"
    return out


# ── Registration ─────────────────────────────────────────────────────────────

_ANALYSIS_KW = {
    "packet", "packets", "analyze", "analysis", "insight", "expert",
    "anomaly", "scan", "flow", "audit", "detect", "capture",
    "traffic", "protocol", "conversation", "port_scan", "ics_audit",
}

register(ToolDef(
    name="query_packets", category="analysis",
    description="query captured packets (e.g. query_packets TCP 20)",
    args_spec="[proto] [n]", runner=run_query_packets,
    safety="read", keywords=_ANALYSIS_KW, needs_packets=True,
))

register(ToolDef(
    name="list_insights", category="analysis",
    description="show generated insights",
    args_spec="", runner=run_list_insights,
    safety="read", keywords=_ANALYSIS_KW,
))

register(ToolDef(
    name="generate_insight", category="analysis",
    description="create insight (general|security|ics|http|dns|tls)",
    args_spec="[mode]", runner=run_generate_insight,
    safety="read", keywords=_ANALYSIS_KW, needs_packets=True,
))

register(ToolDef(
    name="expert_analyze", category="analysis",
    description="expert analysis (ics_audit|port_scan|flow_analysis|conversations|anomaly_detect)",
    args_spec="<mode>", runner=run_expert_analyze,
    safety="read", keywords=_ANALYSIS_KW, needs_packets=True,
))


# ── Quick-mode analysis tools ─────────────────────────────────────────────────
# These call analysis_pipeline functions and return compact text for the LLM.

from agent.tools.analysis_pipeline import (
    tcp_health as tcp_health_fn,
    stream_inventory as stream_inventory_fn,
    latency_breakdown as latency_breakdown_fn,
    io_timeline as io_timeline_fn,
)


async def run_tcp_health_check(args: str = "") -> str:
    from api.routes import _packets, _current_capture_file
    import asyncio
    pkts = list(_packets)
    if not pkts:
        return "[tcp_health_check] No packets captured yet."
    path = _current_capture_file or None
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, tcp_health_fn, pkts, path)
    est = " (estimated)" if result.get("estimated") else ""
    lines = [
        f"TCP Health{est}:",
        f"  Retransmissions: {result['retransmissions']}",
        f"  Zero windows: {result['zero_windows']}",
        f"  Duplicate ACKs: {result['duplicate_acks']}",
        f"  Out-of-order: {result['out_of_order']}",
        f"  RSTs: {result['rsts']}",
        f"  Avg RTT: {result['rtt_avg_ms']:.1f}ms",
    ]
    if result.get("top_offenders"):
        lines.append("  Top offenders:")
        for o in result["top_offenders"][:3]:
            lines.append(f"    {o['src']} -> {o['dst']}: {o['retransmits']} retransmits")
    out = "\n".join(lines)
    return out[:MAX_OUTPUT]


async def run_stream_follow(args: str = "") -> str:
    from api.routes import _current_capture_file
    import asyncio
    import subprocess as _subprocess
    from utils.tshark_utils import find_tshark

    try:
        stream_index = int(args.strip()) if args.strip().isdigit() else 0
    except ValueError:
        stream_index = 0

    pcap_path = _current_capture_file
    if not pcap_path:
        return "Stream follow requires a saved pcap file. Use 'capture to file' mode."

    tshark = find_tshark()
    if not tshark:
        return "[stream_follow] tshark not found."

    cmd = [tshark, "-r", pcap_path, "-q", "-z", f"follow,tcp,ascii,{stream_index}"]
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _subprocess.run(cmd, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30),
        )
        out = result.stdout or result.stderr or "[no output]"
        total_lines = len(out.splitlines())
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + f"\n[output truncated — {total_lines} lines total]"
        return out
    except Exception as e:
        return f"[stream_follow] Error: {e}"


async def run_latency_analysis(args: str = "") -> str:
    from api.routes import _packets, _current_capture_file
    import asyncio
    pkts = list(_packets)
    if not pkts:
        return "[latency_analysis] No packets captured yet."
    path = _current_capture_file or None
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, latency_breakdown_fn, pkts, path)
    agg = result.get("aggregate", {})
    lines = [
        "Latency Breakdown:",
        f"  Network RTT:     {agg.get('network_rtt_ms', 0):.1f}ms",
        f"  Server response: {agg.get('server_ms', 0):.1f}ms",
        f"  Client delay:    {agg.get('client_ms', 0):.1f}ms",
        f"  Bottleneck:      {agg.get('bottleneck', 'unknown')} ({agg.get('server_pct', 0)}% server)",
    ]
    streams = result.get("streams", [])[:5]
    if streams:
        lines.append("  Per-stream RTT:")
        for s in streams:
            lines.append(f"    stream {s['stream_id']}: net {s['network_rtt_ms']:.1f}ms "
                         f"srv {s['server_ms']:.1f}ms ({s['bottleneck']})")
    return "\n".join(lines)[:MAX_OUTPUT]


async def run_io_graph(args: str = "") -> str:
    from api.routes import _packets
    import asyncio
    pkts = list(_packets)
    if not pkts:
        return "[io_graph] No packets captured yet."
    loop = asyncio.get_running_loop()
    bins = await loop.run_in_executor(None, io_timeline_fn, pkts)
    if not bins:
        return "[io_graph] No timeline data."
    lines = ["IO Timeline (packets/sec):"]
    for b in bins:
        burst_marker = " <- BURST" if b["burst"] else ""
        lines.append(f"  t={b['t']:5.1f}s  {b['packets_per_sec']:4d} pkt/s  "
                     f"{b['bytes_per_sec']:7d} B/s{burst_marker}")
    out = "\n".join(lines)
    return out[:MAX_OUTPUT]


register(ToolDef(
    name="tcp_health_check", category="analysis",
    description="TCP health metrics: retransmissions, zero-windows, RSTs, RTT, top offenders",
    args_spec="", runner=run_tcp_health_check,
    safety="read", keywords=_ANALYSIS_KW | {"retransmission", "zero window", "rst", "rtt", "health"},
    needs_packets=True,
))

register(ToolDef(
    name="stream_follow", category="analysis",
    description="Follow a TCP stream by index and show the reconstructed conversation (requires pcap file)",
    args_spec="[stream_index]", runner=run_stream_follow,
    safety="read", keywords=_ANALYSIS_KW | {"stream", "follow", "conversation", "payload"},
    needs_packets=False,
))

register(ToolDef(
    name="latency_analysis", category="analysis",
    description="Per-stream latency breakdown: network RTT, server response time, client delay, bottleneck",
    args_spec="", runner=run_latency_analysis,
    safety="read", keywords=_ANALYSIS_KW | {"latency", "slow", "rtt", "response time", "bottleneck"},
    needs_packets=True,
))

register(ToolDef(
    name="io_graph", category="analysis",
    description="IO timeline: packets and bytes per second, burst detection",
    args_spec="", runner=run_io_graph,
    safety="read", keywords=_ANALYSIS_KW | {"io", "timeline", "burst", "throughput", "bandwidth"},
    needs_packets=True,
))
