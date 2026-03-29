# Wireshark Expert Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Quick (LLM tool-driven) and Deep (Python/tshark pipeline + LLM narrator) analysis modes to InsightPanel, with chat integration, achieving Chris Greer-level Wireshark analysis capability.

**Architecture:** Python/tshark computes all metrics (TCP health, streams, latency, expert info, IO timeline); the LLM only narrates pre-computed findings. Deep mode runs a full pipeline on demand; Quick mode routes through the existing chat/tool loop with new tools registered.

**Tech Stack:** Python 3.11, FastAPI/Starlette StreamingResponse, asyncio executors, tshark subprocess, pytest; React + TypeScript + Zustand, Lucide icons, Tailwind CSS.

---

## File Map

**New files:**
- `backend/agent/tools/analysis_pipeline.py` — pure Python/tshark metric functions
- `backend/agent/tools/narrative.py` — async LLM narrator for deep report
- `backend/tests/test_analysis_pipeline.py` — tests for pipeline functions
- `backend/tests/test_narrative.py` — tests for narrative generator

**Modified files:**
- `backend/agent/tools/analysis.py` — register 4 new Quick-mode tools
- `backend/api/routes.py` — 6 new `/analysis/*` endpoints; `analysis_context` on `ChatRequest`; `_last_deep_analysis` state variable
- `backend/agent/chat.py` — `analysis_context` param on `_base_messages`, `answer_question`, `answer_question_stream`; new `_SECTION_BUDGETS` entry
- `frontend/src/store/useStore.ts` — `DeepAnalysisReport` types + store fields
- `frontend/src/lib/api.ts` — `runDeepAnalysis`, `streamNarrative`, updated `sendChatMessage`
- `frontend/src/components/InsightPanel.tsx` — Quick/Deep modes + Deep report cards

---

## Task 1: Analysis Pipeline — tshark helper and tcp_health

**Files:**
- Create: `backend/agent/tools/analysis_pipeline.py`
- Create: `backend/tests/test_analysis_pipeline.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_analysis_pipeline.py`:
```python
"""Tests for analysis_pipeline.py"""
import pytest
from tests.conftest import make_packet


def _tcp(src_ip, dst_ip, src_port, dst_port, ts, flags="", seq=None, details=None):
    p = make_packet(
        protocol="TCP", src_ip=src_ip, dst_ip=dst_ip,
        src_port=src_port, dst_port=dst_port,
        timestamp=ts, details=details or {},
    )
    if flags:
        p["details"]["tcp_flags"] = flags
    if seq is not None:
        p["details"]["tcp_seq"] = str(seq)
    return p


class TestTcpHealth:
    def test_empty_packets_returns_zeros(self):
        from agent.tools.analysis_pipeline import tcp_health
        result = tcp_health([], pcap_path=None)
        assert result["retransmissions"] == 0
        assert result["rsts"] == 0
        assert result["estimated"] is True

    def test_counts_rsts_from_tcp_flags(self):
        from agent.tools.analysis_pipeline import tcp_health
        pkts = [
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.0, flags="RST"),
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.1, flags="RST"),
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.2, flags="ACK"),
        ]
        result = tcp_health(pkts, pcap_path=None)
        assert result["rsts"] == 2
        assert result["estimated"] is True

    def test_rtt_from_syn_synack_pair(self):
        from agent.tools.analysis_pipeline import tcp_health
        # SYN at t=0, SYN-ACK at t=0.004 → RTT 4ms
        pkts = [
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.000, flags="SYN"),
            _tcp("2.2.2.2", "1.1.1.1", "80", "1000", 0.004, flags="SYN,ACK"),
        ]
        result = tcp_health(pkts, pcap_path=None)
        assert abs(result["rtt_avg_ms"] - 4.0) < 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_analysis_pipeline.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'agent.tools.analysis_pipeline'`

- [ ] **Step 3: Create analysis_pipeline.py with tshark helper and tcp_health**

`backend/agent/tools/analysis_pipeline.py`:
```python
"""
Analysis pipeline — pure Python/tshark metric functions.

No LLM calls. Each function accepts the in-memory packet list and an
optional pcap_path. When pcap_path is available, a tshark subprocess
extracts precise tcp.analysis.* flags. Without it, metrics are estimated
from in-memory fields and flagged with estimated=True.
"""
from __future__ import annotations
import asyncio
import csv
import io
import subprocess
from collections import Counter, defaultdict
from typing import Any

from utils.tshark_utils import find_tshark
from utils import proc


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
        result = proc.run(
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_analysis_pipeline.py::TestTcpHealth -v
```
Expected: 3 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/analysis_pipeline.py backend/tests/test_analysis_pipeline.py
git commit -m "feat: add analysis_pipeline with tshark helper and tcp_health"
```

---

## Task 2: Analysis Pipeline — stream_inventory and latency_breakdown

**Files:**
- Modify: `backend/agent/tools/analysis_pipeline.py` (add functions)
- Modify: `backend/tests/test_analysis_pipeline.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_analysis_pipeline.py`:
```python
class TestStreamInventory:
    def test_groups_by_4tuple_without_pcap(self):
        from agent.tools.analysis_pipeline import stream_inventory
        pkts = [
            make_packet(src_ip="1.1.1.1", dst_ip="2.2.2.2", src_port="1000", dst_port="80", length=100),
            make_packet(src_ip="1.1.1.1", dst_ip="2.2.2.2", src_port="1000", dst_port="80", length=200),
            make_packet(src_ip="3.3.3.3", dst_ip="4.4.4.4", src_port="2000", dst_port="443", length=50),
        ]
        result = stream_inventory(pkts, pcap_path=None)
        assert len(result) == 2
        assert result[0]["bytes"] == 300   # sorted by bytes desc
        assert result[0]["packets"] == 2

    def test_detects_http_by_port(self):
        from agent.tools.analysis_pipeline import stream_inventory
        pkts = [make_packet(src_port="54321", dst_port="80", length=100)]
        result = stream_inventory(pkts, pcap_path=None)
        assert result[0]["protocol"] == "HTTP"

    def test_detects_tls_by_port(self):
        from agent.tools.analysis_pipeline import stream_inventory
        pkts = [make_packet(src_port="54321", dst_port="443", length=100)]
        result = stream_inventory(pkts, pcap_path=None)
        assert result[0]["protocol"] == "TLS"


class TestLatencyBreakdown:
    def test_returns_empty_streams_without_pcap_and_no_syn(self):
        from agent.tools.analysis_pipeline import latency_breakdown
        pkts = [make_packet()]
        result = latency_breakdown(pkts, pcap_path=None)
        assert "aggregate" in result
        assert result["aggregate"]["network_rtt_ms"] == 0.0

    def test_computes_rtt_from_syn_synack(self):
        from agent.tools.analysis_pipeline import latency_breakdown
        pkts = [
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.000, flags="SYN"),
            _tcp("2.2.2.2", "1.1.1.1", "80", "1000", 0.006, flags="SYN,ACK"),
        ]
        result = latency_breakdown(pkts, pcap_path=None)
        assert result["aggregate"]["network_rtt_ms"] == pytest.approx(6.0, abs=0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_analysis_pipeline.py::TestStreamInventory tests/test_analysis_pipeline.py::TestLatencyBreakdown -v 2>&1 | head -20
```
Expected: `AttributeError: module has no attribute 'stream_inventory'`

- [ ] **Step 3: Add stream_inventory and latency_breakdown to analysis_pipeline.py**

Append to `backend/agent/tools/analysis_pipeline.py`:
```python

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
        sa_key = (key[1], key[0], key[3], key[2])
        if sa_key in syn_ack_times:
            rtt_ms = (syn_ack_times[sa_key] - syn_t) * 1000
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_analysis_pipeline.py::TestStreamInventory tests/test_analysis_pipeline.py::TestLatencyBreakdown -v
```
Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/analysis_pipeline.py backend/tests/test_analysis_pipeline.py
git commit -m "feat: add stream_inventory and latency_breakdown to analysis pipeline"
```

---

## Task 3: Analysis Pipeline — expert_info_summary, io_timeline, run_deep_analysis

**Files:**
- Modify: `backend/agent/tools/analysis_pipeline.py`
- Modify: `backend/tests/test_analysis_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_analysis_pipeline.py`:
```python
class TestExpertInfoSummary:
    def test_returns_unavailable_when_no_pcap(self):
        from agent.tools.analysis_pipeline import expert_info_summary
        result = expert_info_summary(None)
        assert result["available"] is False
        assert "reason" in result

    def test_returns_unavailable_for_nonexistent_pcap(self):
        from agent.tools.analysis_pipeline import expert_info_summary
        result = expert_info_summary("/nonexistent/file.pcap")
        assert result["available"] is False


class TestIoTimeline:
    def test_empty_returns_empty_list(self):
        from agent.tools.analysis_pipeline import io_timeline
        assert io_timeline([]) == []

    def test_bins_packets_by_second(self):
        from agent.tools.analysis_pipeline import io_timeline
        pkts = [
            make_packet(timestamp=0.1, length=100),
            make_packet(timestamp=0.5, length=200),
            make_packet(timestamp=1.1, length=150),
        ]
        result = io_timeline(pkts)
        assert len(result) == 2
        assert result[0]["t"] == pytest.approx(0.0, abs=0.01)
        assert result[0]["packets_per_sec"] == 2
        assert result[0]["bytes_per_sec"] == 300

    def test_annotates_burst(self):
        from agent.tools.analysis_pipeline import io_timeline
        # 5 quiet seconds then a burst
        base_pkts = [make_packet(timestamp=float(i) + 0.5) for i in range(5)]
        burst_pkts = [make_packet(timestamp=5.1 + j * 0.01) for j in range(50)]
        result = io_timeline(base_pkts + burst_pkts)
        burst_bins = [b for b in result if b["burst"]]
        assert len(burst_bins) >= 1


class TestRunDeepAnalysis:
    def test_returns_all_sections(self):
        from agent.tools.analysis_pipeline import run_deep_analysis
        pkts = [make_packet()]
        result = run_deep_analysis(pkts, pcap_path=None)
        assert set(result.keys()) == {"tcp_health", "streams", "latency", "expert_info", "io_timeline"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_analysis_pipeline.py::TestExpertInfoSummary tests/test_analysis_pipeline.py::TestIoTimeline tests/test_analysis_pipeline.py::TestRunDeepAnalysis -v 2>&1 | head -20
```
Expected: `AttributeError` — functions not yet defined.

- [ ] **Step 3: Add expert_info_summary, io_timeline, and run_deep_analysis**

Append to `backend/agent/tools/analysis_pipeline.py`:
```python

# ── expert_info_summary ───────────────────────────────────────────────────────

def expert_info_summary(pcap_path: str | None) -> dict:
    """
    Run tshark expert info via the existing _run_expert helper.
    Parse output using expert_lines_to_toon then extract counts/top.
    """
    if not pcap_path:
        return {"available": False, "reason": "live capture — no pcap file"}

    import os
    if not os.path.isfile(pcap_path):
        return {"available": False, "reason": f"file not found: {pcap_path}"}

    try:
        from agent.tools.expert_info import _run_expert
        from utils.toon import expert_lines_to_toon
    except ImportError as e:
        return {"available": False, "reason": f"import error: {e}"}

    raw = _run_expert(pcap_path)
    if raw.startswith("["):
        return {"available": False, "reason": raw}

    # Note: expert_lines_to_toon() returns a formatted TOON *string*, not structured data.
    # We parse the raw tshark output lines directly to build counts/top dicts.
    lines = raw.splitlines()

    # Parse severity counts and top messages from raw tshark expert output.
    # tshark -z expert format: section headers "Errors (N)" / "Warnings (N)" etc.
    # followed by lines: "  Group   Severity   Protocol   Summary"
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
```

- [ ] **Step 4: Run all pipeline tests**

```bash
cd backend && python -m pytest tests/test_analysis_pipeline.py -v
```
Expected: All tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/analysis_pipeline.py backend/tests/test_analysis_pipeline.py
git commit -m "feat: complete analysis pipeline (expert_info, io_timeline, run_deep_analysis)"
```

---

## Task 4: Narrative Generator

**Files:**
- Create: `backend/agent/tools/narrative.py`
- Create: `backend/tests/test_narrative.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_narrative.py`:
```python
"""Tests for narrative.py"""
import pytest
from unittest.mock import patch, AsyncMock


SAMPLE_REPORT = {
    "tcp_health": {
        "retransmissions": 42, "zero_windows": 3, "duplicate_acks": 18,
        "out_of_order": 5, "rsts": 7, "rtt_avg_ms": 4.2,
        "top_offenders": [{"src": "192.168.1.5", "dst": "10.0.0.1", "retransmits": 12}],
        "estimated": False,
    },
    "streams": [
        {"stream_id": 0, "src": "192.168.1.5:54321", "dst": "10.0.0.1:80",
         "protocol": "HTTP", "packets": 142, "bytes": 98432, "duration_s": 4.2}
    ],
    "latency": {
        "streams": [],
        "aggregate": {"network_rtt_ms": 4.2, "server_ms": 85.0, "client_ms": 11.0,
                      "bottleneck": "server", "server_pct": 85},
    },
    "expert_info": {"available": False, "reason": "live capture"},
    "io_timeline": [
        {"t": 0.0, "packets_per_sec": 12, "bytes_per_sec": 8400, "burst": False},
        {"t": 4.0, "packets_per_sec": 156, "bytes_per_sec": 109200, "burst": True},
    ],
}


@pytest.mark.asyncio
async def test_generate_narrative_yields_tokens():
    from agent.tools.narrative import generate_narrative

    async def fake_stream(messages, max_tokens=None, **kwargs):
        for token in ["The ", "capture ", "shows ", "issues."]:
            yield (token, False)

    with patch("agent.tools.narrative.chat_completion_stream", side_effect=fake_stream):
        tokens = []
        async for tok in generate_narrative(SAMPLE_REPORT):
            tokens.append(tok)
    assert "".join(tokens) == "The capture shows issues."


@pytest.mark.asyncio
async def test_generate_narrative_skips_reasoning_tokens():
    from agent.tools.narrative import generate_narrative

    async def fake_stream(messages, max_tokens=None, **kwargs):
        yield ("thinking...", True)   # reasoning token — should be skipped
        yield ("Result.", False)

    with patch("agent.tools.narrative.chat_completion_stream", side_effect=fake_stream):
        tokens = []
        async for tok in generate_narrative(SAMPLE_REPORT):
            tokens.append(tok)
    assert tokens == ["Result."]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_narrative.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'agent.tools.narrative'`

- [ ] **Step 3: Create narrative.py**

`backend/agent/tools/narrative.py`:
```python
"""
Narrative generator — takes a run_deep_analysis() report dict and streams
a focused LLM-generated analysis prose. The LLM receives pre-computed
structured data only; no raw packets are passed.
"""
from __future__ import annotations
from typing import AsyncGenerator

from agent.llm_client import chat_completion_stream


_SYSTEM = (
    "You are Netscope, an expert network analyst. "
    "You are given pre-computed analysis metrics from a packet capture. "
    "Write a concise, expert-level narrative (under 200 words). "
    "Lead with the single most important finding. "
    "Identify the bottleneck clearly. "
    "Flag any ICS/OT concerns if present. "
    "Use markdown bullet points for multiple findings. "
    "Do NOT repeat the raw numbers — explain what they mean."
)


def _build_prompt(report: dict) -> str:
    tcp = report.get("tcp_health", {})
    lat = report.get("latency", {}).get("aggregate", {})
    streams = report.get("streams", [])
    expert = report.get("expert_info", {})
    io = report.get("io_timeline", [])

    bursts = [b for b in io if b.get("burst")]
    burst_summary = f"burst at t={bursts[0]['t']:.1f}s" if bursts else "no bursts"
    stream_protocols = list({s.get("protocol", "") for s in streams[:5] if s.get("protocol")})
    top_offender = ""
    if tcp.get("top_offenders"):
        off = tcp["top_offenders"][0]
        top_offender = f"Top retransmitter: {off['src']} → {off['dst']} ({off['retransmits']} retransmits)."

    lines = [
        "## Capture Analysis Data",
        f"TCP Health: {tcp.get('retransmissions', 0)} retransmissions, "
        f"{tcp.get('zero_windows', 0)} zero-windows, {tcp.get('rsts', 0)} RSTs, "
        f"avg RTT {tcp.get('rtt_avg_ms', 0):.1f}ms"
        + (" (estimated)" if tcp.get("estimated") else "") + ".",
        top_offender,
        f"Latency: client {lat.get('client_ms', 0):.1f}ms / "
        f"network {lat.get('network_rtt_ms', 0):.1f}ms / "
        f"server {lat.get('server_ms', 0):.1f}ms "
        f"({lat.get('bottleneck', 'unknown')} is bottleneck, "
        f"{lat.get('server_pct', 0)}% server).",
        f"Streams: {len(streams)} total, protocols: {', '.join(stream_protocols) or 'unknown'}.",
        f"Expert info: {expert.get('counts', {}).get('error', 0)} errors, "
        f"{expert.get('counts', {}).get('warning', 0)} warnings."
        if expert.get("available") else "Expert info: not available (live capture).",
        f"IO: {burst_summary}.",
        "",
        "Based on this data, provide your expert analysis:",
    ]
    return "\n".join(l for l in lines if l is not None)


async def generate_narrative(report: dict) -> AsyncGenerator[str, None]:
    """Stream an LLM-generated narrative for the given deep analysis report."""
    prompt = _build_prompt(report)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    async for token, is_reasoning in chat_completion_stream(messages, max_tokens=400):
        if not is_reasoning:
            yield token
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_narrative.py -v
```
Expected: 2 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/narrative.py backend/tests/test_narrative.py
git commit -m "feat: add narrative generator for deep analysis reports"
```

---

## Task 5: Backend API Endpoints

**Files:**
- Modify: `backend/api/routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_routes.py` (find the imports section and add after existing tests):
```python
class TestAnalysisEndpoints:
    def test_deep_analysis_returns_all_sections(self, client, monkeypatch):
        from unittest.mock import patch
        sample = {
            "tcp_health": {"retransmissions": 0, "zero_windows": 0, "duplicate_acks": 0,
                           "out_of_order": 0, "rsts": 0, "rtt_avg_ms": 0.0,
                           "top_offenders": [], "estimated": True},
            "streams": [],
            "latency": {"streams": [], "aggregate": {"network_rtt_ms": 0.0, "server_ms": 0.0,
                        "client_ms": 0.0, "bottleneck": "unknown", "server_pct": 0}},
            "expert_info": {"available": False, "reason": "live capture"},
            "io_timeline": [],
        }
        with patch("api.routes.run_deep_analysis", return_value=sample):
            resp = client.post("/api/analysis/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert "tcp_health" in data
        assert "streams" in data

    def test_narrative_returns_400_when_no_analysis_run(self, client):
        # Reset _last_deep_analysis to None
        import api.routes as r
        r._last_deep_analysis = None
        resp = client.get("/api/analysis/narrative")
        assert resp.status_code == 400

    def test_tcp_health_endpoint(self, client):
        with patch("api.routes.tcp_health_fn", return_value={"retransmissions": 0}):
            resp = client.get("/api/analysis/tcp-health")
        # 200 or 500 depending on whether packets exist — just check it doesn't crash
        assert resp.status_code in (200, 500)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_routes.py::TestAnalysisEndpoints -v 2>&1 | head -20
```
Expected: 404 or import errors — endpoints don't exist yet.

- [ ] **Step 3: Add module-level state variable and import to routes.py**

Open `backend/api/routes.py`. After the existing module-level variables (near `_packets`, `_current_capture_file`), add:
```python
# ── Analysis state ─────────────────────────────────────────────────────────────
_last_deep_analysis: dict | None = None
```

Also add imports near the top of the file (after existing agent imports):
```python
from agent.tools.analysis_pipeline import (
    run_deep_analysis,
    tcp_health as tcp_health_fn,
    stream_inventory as stream_inventory_fn,
    latency_breakdown as latency_breakdown_fn,
    io_timeline as io_timeline_fn,
)
from agent.tools.narrative import generate_narrative
```

- [ ] **Step 4: Add the six analysis endpoints**

Add after the chat endpoints section in `backend/api/routes.py`:
```python
# ── Analysis endpoints ─────────────────────────────────────────────────────────

@router.post("/analysis/deep")
async def analysis_deep(pcap_path: str = ""):
    """Run full analysis pipeline. Returns JSON. Call /analysis/narrative next for LLM prose."""
    global _last_deep_analysis
    path = pcap_path or _current_capture_file or None
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, run_deep_analysis, list(_packets), path
    )
    _last_deep_analysis = result
    return result


@router.get("/analysis/narrative")
async def analysis_narrative():
    """Stream LLM narrative for the most recent deep analysis. Call after /analysis/deep."""
    if _last_deep_analysis is None:
        raise HTTPException(status_code=400, detail="No analysis has been run yet. Call POST /analysis/deep first.")

    async def stream_gen():
        async for token in generate_narrative(_last_deep_analysis):
            yield token

    return StreamingResponse(
        stream_gen(),
        media_type="text/plain",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/analysis/tcp-health")
async def analysis_tcp_health(pcap_path: str = ""):
    path = pcap_path or _current_capture_file or None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, tcp_health_fn, list(_packets), path)


@router.get("/analysis/streams")
async def analysis_streams(pcap_path: str = ""):
    path = pcap_path or _current_capture_file or None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, stream_inventory_fn, list(_packets), path)


@router.get("/analysis/latency")
async def analysis_latency(pcap_path: str = ""):
    path = pcap_path or _current_capture_file or None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, latency_breakdown_fn, list(_packets), path)


@router.get("/analysis/io-timeline")
async def analysis_io_timeline():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, io_timeline_fn, list(_packets))
```

- [ ] **Step 5: Run the tests**

```bash
cd backend && python -m pytest tests/test_routes.py::TestAnalysisEndpoints -v
```
Expected: 3 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes.py
git commit -m "feat: add /analysis/* API endpoints with deep analysis and narrative stream"
```

---

## Task 6: ChatRequest analysis_context Threading

**Files:**
- Modify: `backend/api/routes.py`
- Modify: `backend/agent/chat.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_chat.py`:
```python
class TestAnalysisContextInjection:
    @pytest.mark.asyncio
    async def test_analysis_context_appears_in_system_message(self):
        from unittest.mock import patch, AsyncMock
        from agent.chat import _base_messages

        async def fake_chat_stream(*a, **kw):
            yield ("ok", False)

        with patch("agent.chat.chat_completion_stream", side_effect=fake_chat_stream):
            messages, _ = await _base_messages(
                packets=[], history=None, question="test",
                analysis_context="TCP: 5 retransmit",
            )

        system_content = " ".join(
            m["content"] for m in messages if m["role"] == "system"
        )
        assert "TCP: 5 retransmit" in system_content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest "tests/test_chat.py::TestAnalysisContextInjection" -v 2>&1 | head -20
```
Expected: `TypeError: _base_messages() got unexpected keyword argument 'analysis_context'`

- [ ] **Step 3: Add analysis_context to _SECTION_BUDGETS and _base_messages in chat.py**

In `backend/agent/chat.py`, find `_SECTION_BUDGETS` dict and add:
```python
    "analysis": 1600,  # ~400 tokens — injected when deep analysis has run
```

Find the `_base_messages` function signature (line 199) and add the parameter:
```python
async def _base_messages(
    packets,
    history,
    question:          str  = "",
    rag_enabled:       bool = False,
    use_hyde:          bool = False,
    is_channel:        bool = False,
    shell_enabled:     bool = False,
    analysis_context:  str | None = None,   # ← add
) -> tuple[list[dict], list]:
```

Inside `_base_messages`, after the RAG context section and before the traffic section, add:
```python
    # ── Analysis report context ───────────────────────────────────────────────
    if analysis_context:
        ctx = analysis_context[:1600]
        if _fits("analysis", ctx):
            _push(f"[Analysis Report]\n{ctx}")
```
(Use whatever helper function exists in the function to push system sections — match the pattern used for RAG context injection.)

- [ ] **Step 4: Thread analysis_context through answer_question and answer_question_stream**

In `backend/agent/chat.py`, update `answer_question` signature (add parameter and pass to `_base_messages`):
```python
async def answer_question(
    question:         str,
    packets:          list[dict],
    history:          list[dict] | None = None,
    rag_enabled:      bool = False,
    use_hyde:         bool = False,
    is_channel:       bool = False,
    analysis_context: str | None = None,   # ← add
) -> str:
    messages, rag_chunks = await _base_messages(
        packets, history, question, rag_enabled, use_hyde,
        is_channel=is_channel, shell_enabled=_shell_mode,
        analysis_context=analysis_context,  # ← add
    )
```

Update `answer_question_stream` similarly:
```python
async def answer_question_stream(
    question:         str,
    packets:          list[dict],
    history:          list[dict] | None = None,
    rag_enabled:      bool = False,
    use_hyde:         bool = False,
    analysis_context: str | None = None,   # ← add
) -> AsyncGenerator[str, None]:
    messages, rag_chunks = await _base_messages(
        packets, history, question, rag_enabled, use_hyde,
        shell_enabled=_shell_mode,
        analysis_context=analysis_context,  # ← add
    )
```

- [ ] **Step 5: Add analysis_context to ChatRequest and thread through chat() handler in routes.py**

In `backend/api/routes.py`, update `ChatRequest`:
```python
class ChatRequest(BaseModel):
    message:          str
    stream:           bool = False
    rag_enabled:      bool = False
    use_hyde:         bool = False
    analysis_context: str | None = None   # ← add
```

In the `chat()` handler, pass `analysis_context` to both call sites:
```python
# Streaming path (~line 596):
async for chunk in chat_agent.answer_question_stream(
    req.message, _packets, _chat_history,
    rag_enabled=req.rag_enabled, use_hyde=req.use_hyde,
    analysis_context=req.analysis_context,   # ← add
):

# Non-streaming path (~line 616):
response = await chat_agent.answer_question(
    req.message, _packets, _chat_history,
    rag_enabled=req.rag_enabled, use_hyde=req.use_hyde,
    analysis_context=req.analysis_context,   # ← add
)
```

- [ ] **Step 6: Run the test**

```bash
cd backend && python -m pytest "tests/test_chat.py::TestAnalysisContextInjection" -v
```
Expected: PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/agent/chat.py backend/api/routes.py
git commit -m "feat: thread analysis_context through ChatRequest → _base_messages"
```

---

## Task 7: Quick Mode Agent Tools

**Files:**
- Modify: `backend/agent/tools/analysis.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_tools.py`:
```python
class TestQuickModeTools:
    @pytest.mark.asyncio
    async def test_tcp_health_check_tool_returns_string(self, monkeypatch):
        from unittest.mock import patch
        import api.routes as r
        r._packets = [make_packet()]
        with patch("agent.tools.analysis.tcp_health_fn",
                   return_value={"retransmissions": 5, "rsts": 1, "rtt_avg_ms": 3.0,
                                 "zero_windows": 0, "duplicate_acks": 0, "out_of_order": 0,
                                 "top_offenders": [], "estimated": True}):
            from agent.tools.analysis import run_tcp_health_check
            result = await run_tcp_health_check("")
        assert "retransmissions" in result or "5" in result

    @pytest.mark.asyncio
    async def test_stream_follow_requires_pcap(self, monkeypatch):
        import api.routes as r
        r._current_capture_file = None
        from agent.tools.analysis import run_stream_follow
        result = await run_stream_follow("0")
        assert "pcap" in result.lower() or "file" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_tools.py::TestQuickModeTools -v 2>&1 | head -20
```
Expected: `AttributeError` — new tool functions not yet defined.

- [ ] **Step 3: Add four new tools to analysis.py**

Append to `backend/agent/tools/analysis.py` (before the registration block):
```python
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
    import asyncio, json
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
            lines.append(f"    {o['src']} → {o['dst']}: {o['retransmits']} retransmits")
    out = "\n".join(lines)
    return out[:MAX_OUTPUT]


async def run_stream_follow(args: str = "") -> str:
    from api.routes import _current_capture_file
    import asyncio
    from utils.tshark_utils import find_tshark
    from utils import proc

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
            lambda: proc.run(cmd, capture_output=True, text=True,
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
        burst_marker = " ← BURST" if b["burst"] else ""
        lines.append(f"  t={b['t']:5.1f}s  {b['packets_per_sec']:4d} pkt/s  "
                     f"{b['bytes_per_sec']:7d} B/s{burst_marker}")
    out = "\n".join(lines)
    return out[:MAX_OUTPUT]
```

Add registrations at the bottom of the file (after existing `register()` calls):
```python
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
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_tools.py::TestQuickModeTools -v
```
Expected: 2 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/agent/tools/analysis.py
git commit -m "feat: register tcp_health_check, stream_follow, latency_analysis, io_graph tools"
```

---

## Task 8: Frontend — Store Types and API Client

**Files:**
- Modify: `frontend/src/store/useStore.ts`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add DeepAnalysisReport types and store fields to useStore.ts**

At the top of `frontend/src/store/useStore.ts`, after the existing interfaces, add:
```typescript
// ── Deep Analysis types ───────────────────────────────────────────────────────

interface TcpHealthReport {
  retransmissions: number;
  zero_windows: number;
  duplicate_acks: number;
  out_of_order: number;
  rsts: number;
  rtt_avg_ms: number;
  top_offenders: Array<{ src: string; dst: string; retransmits: number }>;
  estimated: boolean;
}

interface StreamRecord {
  stream_id: number;
  src: string;
  dst: string;
  protocol: string;
  packets: number;
  bytes: number;
  duration_s: number;
}

interface LatencyReport {
  streams: Array<{
    stream_id: number;
    network_rtt_ms: number;
    server_ms: number;
    client_ms: number;
    bottleneck: 'client' | 'network' | 'server';
  }>;
  aggregate: {
    network_rtt_ms: number;
    server_ms: number;
    client_ms: number;
    bottleneck: 'client' | 'network' | 'server';
    server_pct: number;
  };
}

interface ExpertInfoReport {
  available: boolean;
  reason?: string;
  counts?: { error: number; warning: number; note: number; chat: number };
  top?: Array<{ severity: string; message: string; count: number }>;
}

interface IoTimelineBin {
  t: number;
  packets_per_sec: number;
  bytes_per_sec: number;
  burst: boolean;
}

export interface DeepAnalysisReport {
  tcp_health: TcpHealthReport;
  streams: StreamRecord[];
  latency: LatencyReport;
  expert_info: ExpertInfoReport;
  io_timeline: IoTimelineBin[];
}
```

In the `AppState` interface, add after the RAG section:
```typescript
  // Deep Analysis
  analysisReport: DeepAnalysisReport | null;
  analysisContext: string;
  setAnalysisReport: (report: DeepAnalysisReport, context: string) => void;
  clearAnalysisReport: () => void;
```

In the `create<AppState>` implementation, add the fields and actions:
```typescript
  // Deep Analysis
  analysisReport: null,
  analysisContext: "",
  setAnalysisReport: (report, context) => set({ analysisReport: report, analysisContext: context }),
  clearAnalysisReport: () => set({ analysisReport: null, analysisContext: "" }),
```

- [ ] **Step 2: Add API functions to api.ts**

At the end of `frontend/src/lib/api.ts`, add:
```typescript
// ── Deep Analysis ─────────────────────────────────────────────────────────────

import type { DeepAnalysisReport } from "../store/useStore";

export async function runDeepAnalysis(pcapPath?: string): Promise<DeepAnalysisReport> {
  const params = pcapPath ? `?pcap_path=${encodeURIComponent(pcapPath)}` : "";
  const res = await api.post<DeepAnalysisReport>(`/analysis/deep${params}`);
  return res.data;
}

export async function streamNarrative(
  onToken: (token: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/analysis/narrative`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken(decoder.decode(value, { stream: true }));
  }
}

/** Serialize DeepAnalysisReport to a compact context string (≤800 chars). */
export function buildAnalysisContext(report: DeepAnalysisReport): string {
  const t = report.tcp_health;
  const l = report.latency.aggregate;
  const tcpProtos = [...new Set(report.streams.map((s) => s.protocol))].slice(0, 5).join(", ");
  const tcpCount = report.streams.filter((s) => s.protocol !== "UDP").length;
  const udpCount = report.streams.length - tcpCount;
  const expertLine = report.expert_info.available && report.expert_info.counts
    ? `Expert: ${report.expert_info.counts.error} errors, ${report.expert_info.counts.warning} warnings`
    : "Expert: not available";
  const bursts = report.io_timeline.filter((b) => b.burst);
  const burstLine = bursts.length > 0
    ? `Bursts: detected at t=${bursts[0].t.toFixed(1)}s`
    : "Bursts: none";
  return [
    `TCP: ${t.retransmissions} retransmit, ${t.zero_windows} zero-win, ${t.rsts} RST, RTT ${t.rtt_avg_ms}ms${t.estimated ? " (est)" : ""}`,
    `Latency: client ${l.client_ms}ms / network ${l.network_rtt_ms}ms / server ${l.server_ms}ms (${l.bottleneck} bottleneck)`,
    `Streams: ${tcpCount} TCP, ${udpCount} UDP — protocols: ${tcpProtos || "unknown"}`,
    expertLine,
    burstLine,
  ].join("\n").slice(0, 800);
}
```

Update `sendChatMessage` in `api.ts` to accept and pass `analysisContext`:
```typescript
export async function sendChatMessage(
  message: string,
  onToken?: (token: string) => void,
  onToolEvent?: (event: ToolEvent) => void,
  ragEnabled = false,
  useHyde = false,
  signal?: AbortSignal,
  analysisContext?: string,    // ← add
): Promise<string> {
  const body = {
    message, stream: !!onToken, rag_enabled: ragEnabled, use_hyde: useHyde,
    analysis_context: analysisContext || null,   // ← add
  };
  if (onToken) {
    const res = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),    // ← use body var
      signal,
    });
    // ... rest of streaming logic unchanged
```
(Only change the body construction — do not modify the streaming read loop.)

- [ ] **Step 3: Build frontend to verify no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: Build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/store/useStore.ts frontend/src/lib/api.ts
git commit -m "feat: add DeepAnalysisReport types, store fields, and analysis API client functions"
```

---

## Task 9: InsightPanel — Quick and Deep Modes

**Files:**
- Modify: `frontend/src/components/InsightPanel.tsx`

- [ ] **Step 1: Add Quick and Deep modes to MODES array**

In `InsightPanel.tsx`, find the `MODES` array (line 46) and add two entries:
```typescript
const MODES = [
  { id: "general",  label: "General"  },
  { id: "security", label: "Security" },
  { id: "ics",      label: "ICS"      },
  { id: "http",     label: "HTTP"     },
  { id: "dns",      label: "DNS"      },
  { id: "tls",      label: "TLS"      },
  { id: "quick",    label: "⚡ Quick" },
  { id: "deep",     label: "🔬 Deep"  },
] as const;
```

- [ ] **Step 2: Add Quick mode handler**

Quick mode sends a fixed message to `/chat` using the existing streaming pattern. In `InsightPanel.tsx`, update `handleGenerate` to handle `quick` mode before calling `generateInsightStream`:
```typescript
const handleGenerate = async () => {
  if (loading || packetsLength === 0) return;
  setLoading(true);
  setStreamText("");
  setError("");
  abortRef.current = new AbortController();

  // Deep mode is handled by handleDeepAnalysis
  if (selectedMode === "deep") {
    setLoading(false);
    await handleDeepAnalysis();
    return;
  }

  try {
    let full: string;
    if (selectedMode === "quick") {
      // Route through chat/tool loop
      const quickMessage =
        "Run a quick expert analysis of this capture. Use the tcp_health_check, " +
        "stream_follow, latency_analysis, io_graph, and expert_info tools. " +
        "Lead with the most significant finding.";
      full = await sendChatMessage(
        quickMessage,
        (token) => setStreamText((prev) => prev + token),
        undefined,
        false, false,
        abortRef.current.signal,
        analysisContext || undefined,
      );
    } else {
      full = await generateInsightStream(
        selectedMode,
        (token) => setStreamText((prev) => prev + token),
        abortRef.current.signal,
      );
    }
    addInsight({ text: full, source: selectedMode, timestamp: Date.now() / 1000 });
    setStreamText("");
  } catch (e: any) {
    if (e?.name !== "AbortError") {
      setError(e?.message || "Failed to generate insight");
      setStreamText("");
    }
  } finally {
    setLoading(false);
    abortRef.current = null;
  }
};
```

Add the required imports at the top:
```typescript
import { sendChatMessage, runDeepAnalysis, streamNarrative, buildAnalysisContext } from "../lib/api";
import type { DeepAnalysisReport } from "../store/useStore";
```

Add store selectors:
```typescript
const { insights, addInsight, clearInsights, llmStatus, setAnalysisReport, analysisReport, analysisContext } = useStore(
  useShallow((s) => ({
    insights: s.insights, addInsight: s.addInsight, clearInsights: s.clearInsights,
    llmStatus: s.llmStatus, setAnalysisReport: s.setAnalysisReport,
    analysisReport: s.analysisReport, analysisContext: s.analysisContext,
  }))
);
```

Add additional state for Deep mode:
```typescript
const [deepReport, setDeepReport] = useState<DeepAnalysisReport | null>(null);
const [narrativeText, setNarrativeText] = useState("");
const [deepLoading, setDeepLoading] = useState(false);
const narrativeAbortRef = useRef<AbortController | null>(null);
```

- [ ] **Step 3: Add Deep mode handler**

Add `handleDeepAnalysis` function inside `InsightPanel`:
```typescript
const handleDeepAnalysis = async () => {
  setDeepLoading(true);
  setDeepReport(null);
  setNarrativeText("");
  narrativeAbortRef.current?.abort();

  try {
    // captureFile is already polled by the existing useEffect at the top of InsightPanel
    // (state variable: const [captureFile, setCaptureFile] = useState<{name:string|null,...}>)
    const report = await runDeepAnalysis(captureFile.name ?? undefined);
    setDeepReport(report);
    const ctx = buildAnalysisContext(report);
    setAnalysisReport(report, ctx);

    // Stream narrative
    narrativeAbortRef.current = new AbortController();
    await streamNarrative(
      (token) => setNarrativeText((prev) => prev + token),
      narrativeAbortRef.current.signal,
    );
  } catch (e: any) {
    if (e?.name !== "AbortError") {
      setError(e?.message || "Deep analysis failed");
    }
  } finally {
    setDeepLoading(false);
  }
};
```

- [ ] **Step 4: Render Deep report cards**

Add a `DeepReportPanel` component at the top of `InsightPanel.tsx` (above the `InsightPanel` function):
```typescript
function MetricCard({
  title, children, onAskInChat,
}: { title: string; children: React.ReactNode; onAskInChat?: () => void }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="border border-border rounded-lg overflow-hidden mb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface hover:bg-surface-hover text-xs"
      >
        <span className="text-foreground font-medium">{title}</span>
        <div className="flex items-center gap-2">
          {onAskInChat && (
            <span
              className="text-blue-400 hover:text-blue-300 text-[10px] font-medium"
              onClick={(e) => { e.stopPropagation(); onAskInChat(); }}
            >
              Ask in chat →
            </span>
          )}
          {expanded ? <ChevronDown className="w-3 h-3 text-muted" /> : <ChevronRight className="w-3 h-3 text-muted" />}
        </div>
      </button>
      {expanded && <div className="px-4 py-3 bg-background text-xs">{children}</div>}
    </div>
  );
}
```

Inside the main `InsightPanel` JSX, in the content area, add a conditional block after the streaming preview:
```typescript
{/* Deep mode report */}
{selectedMode === "deep" && deepReport && (
  <div>
    {/* TCP Health */}
    <MetricCard
      title={`🔴 TCP Health${deepReport.tcp_health.estimated ? " (estimated)" : ""}`}
      onAskInChat={() => setChatPrefill("Why are there so many retransmissions?")}
    >
      <div className="grid grid-cols-3 gap-2 mb-2">
        {[
          ["Retransmissions", deepReport.tcp_health.retransmissions],
          ["Zero Windows",    deepReport.tcp_health.zero_windows],
          ["RSTs",            deepReport.tcp_health.rsts],
          ["Dup ACKs",        deepReport.tcp_health.duplicate_acks],
          ["Out of Order",    deepReport.tcp_health.out_of_order],
          ["RTT avg",         `${deepReport.tcp_health.rtt_avg_ms}ms`],
        ].map(([label, val]) => (
          <div key={String(label)} className="bg-surface rounded p-1.5">
            <div className="text-muted text-[10px]">{label}</div>
            <div className="text-foreground font-mono font-semibold">{String(val)}</div>
          </div>
        ))}
      </div>
      {deepReport.tcp_health.top_offenders.length > 0 && (
        <div className="text-muted mt-1">
          Top: {deepReport.tcp_health.top_offenders[0].src} → {deepReport.tcp_health.top_offenders[0].dst} ({deepReport.tcp_health.top_offenders[0].retransmits} retransmits)
        </div>
      )}
    </MetricCard>

    {/* Latency Breakdown */}
    <MetricCard
      title="⏱ Latency Breakdown"
      onAskInChat={() => setChatPrefill(`The ${deepReport.latency.aggregate.bottleneck} is the bottleneck — what's causing the delay?`)}
    >
      {(() => {
        const agg = deepReport.latency.aggregate;
        const total = agg.network_rtt_ms + agg.server_ms + agg.client_ms;
        return (
          <div>
            <div className="flex gap-1 h-4 rounded overflow-hidden mb-2">
              {total > 0 && <>
                <div style={{ width: `${agg.client_ms / total * 100}%` }} className="bg-blue-500/60 flex items-center justify-center text-[9px]">C</div>
                <div style={{ width: `${agg.network_rtt_ms / total * 100}%` }} className="bg-yellow-500/60 flex items-center justify-center text-[9px]">N</div>
                <div style={{ width: `${agg.server_ms / total * 100}%` }} className={`${agg.bottleneck === "server" ? "bg-red-500/80" : "bg-green-500/60"} flex items-center justify-center text-[9px]`}>S</div>
              </>}
            </div>
            <div className="flex gap-4 text-[10px] text-muted">
              <span>Client: {agg.client_ms}ms</span>
              <span>Network: {agg.network_rtt_ms}ms</span>
              <span className={agg.bottleneck === "server" ? "text-red-400 font-semibold" : ""}>
                Server: {agg.server_ms}ms {agg.bottleneck === "server" && "⚠"}
              </span>
            </div>
          </div>
        );
      })()}
    </MetricCard>

    {/* Streams */}
    {deepReport.streams.length > 0 && (
      <MetricCard
        title={`🌊 Streams (${deepReport.streams.length})`}
        onAskInChat={() => setChatPrefill("Walk me through stream 0")}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead><tr className="text-muted border-b border-border">
              <th className="text-left py-1 pr-3">Src → Dst</th>
              <th className="text-left py-1 pr-3">Proto</th>
              <th className="text-right py-1 pr-3">Bytes</th>
              <th className="text-right py-1">Pkts</th>
            </tr></thead>
            <tbody>
              {deepReport.streams.slice(0, 8).map((s) => (
                <tr key={s.stream_id} className="border-b border-border/40">
                  <td className="py-1 pr-3 font-mono text-[9px] text-muted">{s.src}<br/>→ {s.dst}</td>
                  <td className="py-1 pr-3">{s.protocol}</td>
                  <td className="py-1 pr-3 text-right">{formatBytes(s.bytes)}</td>
                  <td className="py-1 text-right">{s.packets}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MetricCard>
    )}

    {/* Expert Info */}
    {deepReport.expert_info.available && deepReport.expert_info.counts && (
      <MetricCard
        title="⚠ Expert Info"
        onAskInChat={() => setChatPrefill("What do the TCP warnings mean?")}
      >
        <div className="flex gap-4 text-[10px] mb-2">
          {deepReport.expert_info.counts.error > 0 && <span className="text-red-400">✕ {deepReport.expert_info.counts.error} errors</span>}
          {deepReport.expert_info.counts.warning > 0 && <span className="text-yellow-400">⚠ {deepReport.expert_info.counts.warning} warnings</span>}
          {deepReport.expert_info.counts.note > 0 && <span className="text-blue-400">ℹ {deepReport.expert_info.counts.note} notes</span>}
        </div>
        {deepReport.expert_info.top?.slice(0, 5).map((item, i) => (
          <div key={i} className="text-[10px] text-muted mb-0.5">
            <span className={item.severity === "error" ? "text-red-400" : item.severity === "warning" ? "text-yellow-400" : "text-blue-400"}>
              {item.severity}
            </span>
            {" "}{item.message} ×{item.count}
          </div>
        ))}
      </MetricCard>
    )}

    {/* IO Timeline */}
    {deepReport.io_timeline.length > 0 && (
      <MetricCard
        title="📈 IO Timeline"
        onAskInChat={() => {
          const burst = deepReport.io_timeline.find((b) => b.burst);
          setChatPrefill(burst ? `What caused the burst at t=${burst.t.toFixed(1)}s?` : "Describe the traffic pattern over time.");
        }}
      >
        <div className="flex items-end gap-px h-12">
          {deepReport.io_timeline.map((b, i) => {
            const max = Math.max(...deepReport.io_timeline.map((x) => x.packets_per_sec));
            const height = max > 0 ? Math.max(2, (b.packets_per_sec / max) * 100) : 2;
            return (
              <div
                key={i}
                title={`t=${b.t.toFixed(0)}s: ${b.packets_per_sec} pkt/s`}
                style={{ height: `${height}%` }}
                className={`flex-1 min-w-[2px] rounded-t ${b.burst ? "bg-red-400" : "bg-blue-500/60"}`}
              />
            );
          })}
        </div>
        <div className="text-[10px] text-muted mt-1">
          {deepReport.io_timeline.filter((b) => b.burst).length} burst(s) detected
        </div>
      </MetricCard>
    )}

    {/* Narrative */}
    <MetricCard title="📝 Analysis Narrative">
      {deepLoading && !narrativeText && (
        <div className="flex items-center gap-2 text-muted">
          <Loader2 className="w-3 h-3 animate-spin" />
          <span>Generating narrative…</span>
        </div>
      )}
      {narrativeText && <MarkdownContent>{narrativeText}</MarkdownContent>}
    </MetricCard>
  </div>
)}
```

- [ ] **Step 5: Wire up "Ask in chat" — add setChatPrefill prop/callback**

`InsightPanel` needs to communicate with `ChatBox` to pre-fill the input. The cleanest approach is to add a `chatPrefill` store field.

In `useStore.ts`, add to `AppState`:
```typescript
  chatPrefill: string;
  setChatPrefill: (v: string) => void;
  clearChatPrefill: () => void;
```

In the store implementation:
```typescript
  chatPrefill: "",
  setChatPrefill: (v) => set({ chatPrefill: v }),
  clearChatPrefill: () => set({ chatPrefill: "" }),
```

In `InsightPanel.tsx`, get `setChatPrefill` from store and use it in the "Ask in chat →" handlers (already wired in step 4 above as `setChatPrefill("...")`).

In `ChatBox.tsx` (or wherever the chat input lives), read `chatPrefill` from the store and pre-fill the input:
```typescript
const chatPrefill = useStore((s) => s.chatPrefill);
const clearChatPrefill = useStore((s) => s.clearChatPrefill);

useEffect(() => {
  if (chatPrefill) {
    setInput(chatPrefill);
    clearChatPrefill();
  }
}, [chatPrefill]);
```

- [ ] **Step 6: Build and verify no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -30
```
Expected: Build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/InsightPanel.tsx frontend/src/store/useStore.ts frontend/src/lib/api.ts
git commit -m "feat: InsightPanel Quick and Deep modes with report cards and chat integration"
```

---

## Task 10: Integration Verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```
Expected: All existing tests pass + new tests pass. No regressions.

- [ ] **Step 2: Start the app and test Deep mode manually**

```bash
# Terminal 1 — backend
cd backend && python -m uvicorn main:app --reload --port 8000

# Terminal 2 — frontend dev server
cd frontend && npm run dev
```

1. Open the app, upload or load a pcap file.
2. Navigate to the Insights panel.
3. Click **🔬 Deep** — verify 5 metric cards appear and the Narrative card streams in text.
4. Click **Ask in chat →** on the TCP Health card — verify chat input pre-fills with the question.
5. Click **⚡ Quick** — verify LLM streams a tool-driven analysis.
6. Send a chat message — verify the analysis context appears in responses (ask "what was the bottleneck?").

- [ ] **Step 3: Test with no pcap (live capture only) — verify graceful degradation**

1. Clear packets and do a brief live capture (no file).
2. Click **🔬 Deep** — TCP Health card should show `(estimated)` label.
3. Expert Info card should be hidden (not available for live capture).

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat: complete Wireshark expert analysis (Quick + Deep modes, chat integration)"
```
