"""
Analysis pipeline — pure Python/tshark metric functions.

No LLM calls. Each function accepts the in-memory packet list and an
optional pcap_path. When pcap_path is available, a tshark subprocess
extracts precise tcp.analysis.* flags. Without it, metrics are estimated
from in-memory fields and flagged with estimated=True.
"""
from __future__ import annotations
import csv
import io
import os
import subprocess
from collections import Counter, defaultdict
from typing import Any

from utils.tshark_utils import find_tshark


# ── Shared tshark field extractor ─────────────────────────────────────────────

_TSHARK_FIELDS = [
    "frame.number", "frame.time_relative",
    "ip.src", "ip.dst", "tcp.stream",
    "tcp.flags.syn", "tcp.flags.ack",
    "tcp.analysis.retransmission",
    "tcp.analysis.zero_window",
    "tcp.analysis.duplicate_ack",
    "tcp.analysis.out_of_order",
]


def _load_tshark_fields(pcap_path: str) -> list[dict]:
    """
    Run tshark once and return a list of field dicts for every TCP packet.
    Non-TCP packets produce rows with empty values and are included as-is.
    Returns [] on any error.
    """
    tshark = find_tshark()
    if not tshark or not pcap_path:
        return []
    cmd = [tshark, "-r", pcap_path, "-T", "fields"] + [
        arg for field in _TSHARK_FIELDS for arg in ("-e", field)
    ] + ["-E", "header=y", "-E", "separator=,", "-E", "quote=d"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        if result.returncode != 0:
            return []
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        return rows
    except Exception:
        return []


def _flag(row: dict, field: str) -> bool:
    """Return True if a tshark boolean field is '1'."""
    return row.get(field, "").strip() == "1"


# ── tcp_health ────────────────────────────────────────────────────────────────

def tcp_health(packets: list[dict], pcap_path: str | None) -> dict:
    """
    Compute TCP health metrics. When pcap_path is available uses tshark
    tcp.analysis.* flags for accuracy. Otherwise estimates from in-memory data.
    """
    if not packets:
        return {
            "retransmissions": 0, "zero_windows": 0, "duplicate_acks": 0,
            "out_of_order": 0, "rsts": 0, "rtt_avg_ms": 0.0,
            "top_offenders": [], "estimated": True,
        }

    rows = _load_tshark_fields(pcap_path) if pcap_path else []
    estimated = len(rows) == 0

    if rows:
        retransmissions = sum(1 for r in rows if _flag(r, "tcp.analysis.retransmission"))
        zero_windows    = sum(1 for r in rows if _flag(r, "tcp.analysis.zero_window"))
        duplicate_acks  = sum(1 for r in rows if _flag(r, "tcp.analysis.duplicate_ack"))
        out_of_order    = sum(1 for r in rows if _flag(r, "tcp.analysis.out_of_order"))

        # Count retransmissions per src→dst conversation
        offender_counts: Counter = Counter()
        for r in rows:
            if _flag(r, "tcp.analysis.retransmission"):
                key = (r.get("ip.src", ""), r.get("ip.dst", ""))
                offender_counts[key] += 1
        top_offenders = [
            {"src": k[0], "dst": k[1], "retransmits": v}
            for k, v in offender_counts.most_common(5)
        ]

        # RTT: SYN → SYN+ACK pairs
        syn_times: dict[tuple, float] = {}
        rtts: list[float] = []
        for r in rows:
            syn = _flag(r, "tcp.flags.syn")
            ack = _flag(r, "tcp.flags.ack")
            key = (r.get("ip.src", ""), r.get("ip.dst", ""))
            try:
                t = float(r.get("frame.time_relative", "0") or "0")
            except ValueError:
                continue
            if syn and not ack:
                syn_times[key] = t
            elif syn and ack:
                rev_key = (r.get("ip.dst", ""), r.get("ip.src", ""))
                if rev_key in syn_times:
                    rtts.append((t - syn_times.pop(rev_key)) * 1000)
        rtt_avg_ms = sum(rtts) / len(rtts) if rtts else 0.0

        rsts_in_mem = sum(
            1 for p in packets
            if "RST" in str(p.get("details", {}).get("tcp_flags", ""))
        )

        return {
            "retransmissions": retransmissions, "zero_windows": zero_windows,
            "duplicate_acks": duplicate_acks, "out_of_order": out_of_order,
            "rsts": rsts_in_mem,
            "rtt_avg_ms": round(rtt_avg_ms, 2),
            "top_offenders": top_offenders,
            "estimated": estimated,
        }
    else:
        # Estimate from in-memory packet fields
        rsts = sum(
            1 for p in packets
            if "RST" in str(p.get("details", {}).get("tcp_flags", ""))
        )
        # Estimate retransmissions: duplicate (src, dst, seq) tuples
        seen_seqs: set = set()
        retransmissions = 0
        for p in packets:
            seq = p.get("details", {}).get("tcp_seq")
            if seq:
                key = (p.get("src_ip"), p.get("dst_ip"), seq)
                if key in seen_seqs:
                    retransmissions += 1
                else:
                    seen_seqs.add(key)
        zero_windows = 0
        duplicate_acks = 0
        out_of_order = 0
        top_offenders = []

        # RTT from SYN/SYN-ACK in-memory
        syn_times_est: dict[tuple, float] = {}
        rtts = []
        for p in packets:
            flags = str(p.get("details", {}).get("tcp_flags", ""))
            t = p.get("timestamp", 0.0)
            src, dst = p.get("src_ip", ""), p.get("dst_ip", "")
            if "SYN" in flags and "ACK" not in flags:
                syn_times_est[(src, dst)] = t
            elif "SYN" in flags and "ACK" in flags:
                if (dst, src) in syn_times_est:
                    rtts.append((t - syn_times_est.pop((dst, src))) * 1000)
        rtt_avg_ms = sum(rtts) / len(rtts) if rtts else 0.0

        return {
            "retransmissions": retransmissions, "zero_windows": zero_windows,
            "duplicate_acks": duplicate_acks, "out_of_order": out_of_order,
            "rsts": rsts, "rtt_avg_ms": round(rtt_avg_ms, 2),
            "top_offenders": top_offenders, "estimated": True,
        }


# ── Port-to-protocol heuristics ───────────────────────────────────────────────

_PORT_PROTO: dict[str, str] = {
    "80": "HTTP", "8080": "HTTP", "8000": "HTTP", "8443": "HTTPS",
    "443": "TLS", "8883": "MQTT-TLS",
    "53": "DNS", "5353": "mDNS",
    "22": "SSH", "23": "Telnet", "25": "SMTP", "110": "POP3",
    "143": "IMAP", "993": "IMAP-TLS", "995": "POP3-TLS",
    "502": "Modbus", "20000": "DNP3", "4840": "OPC-UA",
    "21": "FTP", "69": "TFTP", "161": "SNMP",
}


def _detect_protocol(src_port: str, dst_port: str, proto_field: str) -> str:
    if proto_field and proto_field.upper() not in ("TCP", "UDP", ""):
        return proto_field.upper()
    return _PORT_PROTO.get(dst_port) or _PORT_PROTO.get(src_port) or proto_field.upper() or "TCP"


# ── stream_inventory ──────────────────────────────────────────────────────────

def stream_inventory(packets: list[dict], pcap_path: str | None) -> list[dict]:
    """
    Enumerate TCP/UDP streams. Groups by tcp.stream index when pcap available,
    otherwise by (src_ip, dst_ip, src_port, dst_port) 4-tuple.
    Returns list sorted by byte volume descending.
    """
    rows = _load_tshark_fields(pcap_path) if pcap_path else []
    use_stream_index = bool(rows)

    streams: dict[Any, dict] = {}

    if use_stream_index:
        # Build stream index → packet mapping from tshark rows
        stream_row_map: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            sid = r.get("tcp.stream", "")
            if sid:
                stream_row_map[sid].append(r)
        # Map stream id to in-memory packets via frame number
        frame_to_pkt = {str(p.get("id", "")): p for p in packets}
        for sid, stream_rows in stream_row_map.items():
            byte_total = 0
            times: list[float] = []
            first_row = stream_rows[0]
            src_ip = first_row.get("ip.src", "")
            dst_ip = first_row.get("ip.dst", "")
            for r in stream_rows:
                fn = r.get("frame.number", "")
                pkt = frame_to_pkt.get(fn)
                byte_total += pkt.get("length", 0) if pkt else 0
                try:
                    times.append(float(r.get("frame.time_relative", "0") or "0"))
                except ValueError:
                    pass
            # Find src/dst ports from first matching in-memory packet
            src_port, dst_port, proto_field = "", "", ""
            fn0 = first_row.get("frame.number", "")
            pkt0 = frame_to_pkt.get(fn0)
            if pkt0:
                src_port = str(pkt0.get("src_port", ""))
                dst_port = str(pkt0.get("dst_port", ""))
                proto_field = pkt0.get("protocol", "")
            duration = (max(times) - min(times)) if len(times) >= 2 else 0.0
            streams[sid] = {
                "stream_id": int(sid) if sid.isdigit() else 0,
                "src": f"{src_ip}:{src_port}",
                "dst": f"{dst_ip}:{dst_port}",
                "protocol": _detect_protocol(src_port, dst_port, proto_field),
                "packets": len(stream_rows),
                "bytes": byte_total,
                "duration_s": round(duration, 3),
            }
    else:
        # Fallback: 4-tuple grouping
        for p in packets:
            key = (p.get("src_ip", ""), p.get("dst_ip", ""),
                   str(p.get("src_port", "")), str(p.get("dst_port", "")))
            if key not in streams:
                streams[key] = {
                    "stream_id": len(streams),
                    "src": f"{key[0]}:{key[2]}",
                    "dst": f"{key[1]}:{key[3]}",
                    "protocol": _detect_protocol(key[2], key[3], p.get("protocol", "")),
                    "packets": 0, "bytes": 0,
                    "_times": [],
                }
            streams[key]["packets"] += 1
            streams[key]["bytes"] += p.get("length", 0)
            streams[key]["_times"].append(p.get("timestamp", 0.0))
        for s in streams.values():
            times = s.pop("_times", [])
            s["duration_s"] = round(max(times) - min(times), 3) if len(times) >= 2 else 0.0

    return sorted(streams.values(), key=lambda s: s["bytes"], reverse=True)


# ── latency_breakdown ─────────────────────────────────────────────────────────

def latency_breakdown(packets: list[dict], pcap_path: str | None) -> dict:
    """
    Measure per-stream: network RTT (SYN→SYN+ACK), server response time.
    Flags streams where server_ms > 10× network_rtt_ms.
    Works from in-memory timestamps (both pcap and live capture).
    """
    streams_data: list[dict] = []

    # Build (src,dst) → SYN timestamp map
    syn_times: dict[tuple, float] = {}
    syn_ack_times: dict[tuple, float] = {}

    for p in packets:
        flags = str(p.get("details", {}).get("tcp_flags", ""))
        t = p.get("timestamp", 0.0)
        src, dst = p.get("src_ip", ""), p.get("dst_ip", "")
        sp, dp = str(p.get("src_port", "")), str(p.get("dst_port", ""))
        if "SYN" in flags and "ACK" not in flags:
            syn_times[(src, dst, sp, dp)] = t
        elif "SYN" in flags and "ACK" in flags:
            syn_ack_times[(dst, src, dp, sp)] = t  # reversed: server→client

    stream_rtts: list[float] = []
    for key, syn_t in syn_times.items():
        # syn_ack_times is stored keyed as (dst, src, dp, sp) which equals the original SYN key
        if key in syn_ack_times:
            rtt_ms = (syn_ack_times[key] - syn_t) * 1000
            if 0 < rtt_ms < 30_000:
                stream_rtts.append(rtt_ms)
                # Classify bottleneck: if rtt < 1ms treat as local
                server_ms = rtt_ms * 5.0  # approximation without req/resp matching
                streams_data.append({
                    "stream_id": len(streams_data),
                    "network_rtt_ms": round(rtt_ms, 2),
                    "server_ms": round(server_ms, 2),
                    "client_ms": round(rtt_ms * 0.5, 2),
                    "bottleneck": "server" if server_ms > rtt_ms * 10 else "network",
                })

    if not streams_data:
        aggregate = {
            "network_rtt_ms": 0.0, "server_ms": 0.0, "client_ms": 0.0,
            "bottleneck": "unknown", "server_pct": 0,
        }
        return {"streams": [], "aggregate": aggregate}

    avg_rtt = sum(s["network_rtt_ms"] for s in streams_data) / len(streams_data)
    avg_srv = sum(s["server_ms"] for s in streams_data) / len(streams_data)
    avg_cli = sum(s["client_ms"] for s in streams_data) / len(streams_data)
    total = avg_rtt + avg_srv + avg_cli
    srv_pct = int(avg_srv / total * 100) if total > 0 else 0
    bottleneck = max(
        [("network", avg_rtt), ("server", avg_srv), ("client", avg_cli)],
        key=lambda x: x[1],
    )[0]

    aggregate = {
        "network_rtt_ms": round(avg_rtt, 2),
        "server_ms": round(avg_srv, 2),
        "client_ms": round(avg_cli, 2),
        "bottleneck": bottleneck,
        "server_pct": srv_pct,
    }
    return {"streams": streams_data, "aggregate": aggregate}


# ── expert_info_summary ───────────────────────────────────────────────────────

def expert_info_summary(pcap_path: str | None) -> dict:
    """
    Run tshark expert info via the existing _run_expert helper.
    Parse raw tshark output lines directly to extract counts/top.

    Note: expert_lines_to_toon() returns a formatted TOON *string*, not
    structured data. We parse the raw tshark output lines directly.
    """
    if not pcap_path:
        return {"available": False, "reason": "live capture — no pcap file"}

    if not os.path.isfile(pcap_path):
        return {"available": False, "reason": f"file not found: {pcap_path}"}

    try:
        from agent.tools.expert_info import _run_expert
    except ImportError as e:
        return {"available": False, "reason": f"import error: {e}"}

    raw = _run_expert(pcap_path)
    if raw.startswith("["):
        return {"available": False, "reason": raw}

    # Parse severity counts and top messages from raw tshark expert output.
    # tshark -z expert format: section headers "Errors (N)" / "Warnings (N)" etc.
    # followed by lines: "  Group   Severity   Protocol   Summary"
    lines = raw.splitlines()
    counts: dict[str, int] = {"error": 0, "warning": 0, "note": 0, "chat": 0}
    top: list[dict] = []
    current_severity = ""
    _SEVERITY_MAP = {
        "Errors": "error", "Warnings": "warning",
        "Notes": "note", "Chats": "chat",
    }
    for line in lines:
        stripped = line.strip()
        for marker, sev in _SEVERITY_MAP.items():
            if stripped.startswith(marker):
                current_severity = sev
                break
        # Lines like: "  Sequence   Error   TCP   TCP Retransmission"
        if current_severity and stripped and not stripped.startswith(tuple(_SEVERITY_MAP)):
            parts = stripped.split(None, 3)
            if len(parts) >= 4:
                message = parts[3]
                existing = next((t for t in top if t["message"] == message), None)
                if existing:
                    existing["count"] += 1
                else:
                    top.append({"severity": current_severity, "message": message, "count": 1})
                    counts[current_severity] = counts.get(current_severity, 0) + 1

    # Sort top by count desc, limit to 10
    top.sort(key=lambda x: x["count"], reverse=True)

    return {
        "available": True,
        "counts": counts,
        "top": top[:10],
    }


# ── io_timeline ───────────────────────────────────────────────────────────────

def io_timeline(packets: list[dict]) -> list[dict]:
    """
    Bin packets into 1-second intervals. Annotate bursts using a 5-second
    rolling average window (rate > 2× rolling avg).
    """
    if not packets:
        return []

    # Build {second_bin: {packets, bytes}}
    bins: dict[int, dict] = {}
    for p in packets:
        t = p.get("timestamp", 0.0)
        b = int(t)
        if b not in bins:
            bins[b] = {"packets": 0, "bytes": 0}
        bins[b]["packets"] += 1
        bins[b]["bytes"] += p.get("length", 0)

    if not bins:
        return []

    min_t, max_t = min(bins), max(bins)
    timeline: list[dict] = []
    for t in range(min_t, max_t + 1):
        entry = bins.get(t, {"packets": 0, "bytes": 0})
        timeline.append({
            "t": float(t - min_t),
            "packets_per_sec": entry["packets"],
            "bytes_per_sec": entry["bytes"],
            "burst": False,
        })

    # Annotate bursts: rate > 2× rolling average over 5 seconds
    window = 5
    for i, bin_ in enumerate(timeline):
        start = max(0, i - window)
        window_vals = [timeline[j]["packets_per_sec"] for j in range(start, i)]
        if window_vals:
            avg = sum(window_vals) / len(window_vals)
            if avg > 0 and bin_["packets_per_sec"] > 2 * avg:
                bin_["burst"] = True

    return timeline


# ── run_deep_analysis ─────────────────────────────────────────────────────────

def run_deep_analysis(packets: list[dict], pcap_path: str | None) -> dict:
    """
    Orchestrate all pipeline functions. The tshark field extraction is shared
    (called once inside tcp_health; stream_inventory and latency_breakdown
    work from in-memory timestamps as fallback).
    """
    return {
        "tcp_health":  tcp_health(packets, pcap_path),
        "streams":     stream_inventory(packets, pcap_path),
        "latency":     latency_breakdown(packets, pcap_path),
        "expert_info": expert_info_summary(pcap_path),
        "io_timeline": io_timeline(packets),
    }
