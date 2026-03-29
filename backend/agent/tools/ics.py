"""
ICS/SCADA tools: dnp3_analyze, dnp3_forensics, tshark_filter.

dnp3_analyze    — extract and LLM-analyse DNP3 packets from a PCAP
dnp3_forensics  — focused field extraction for DNP3 Write/Operate commands (raw TOON)
tshark_filter   — generate the correct tshark display filter for a description
                  by querying the RAG knowledge base first, then falling back
                  to a curated built-in reference table.
"""

from __future__ import annotations
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

from agent.tools.registry import register, ToolDef
from utils import proc

# Blocked paths (mirrors expert_info.py / modbus.py)
_BLOCKED_PREFIXES = (
    r"c:\windows", r"c:\program files", r"c:\programdata",
    r"c:\users\default", r"c:\system",
)
_ALLOWED_EXTENSIONS = (".pcap", ".pcapng", ".cap")


def _get_current_pcap() -> Optional[str]:
    try:
        from api.routes import _current_capture_file
        return _current_capture_file if _current_capture_file else None
    except Exception:
        return None


def _validate_pcap(raw: str) -> tuple[Optional[str], Optional[str]]:
    try:
        p = str(Path(raw).resolve())
    except Exception:
        return None, f"Invalid path: {raw}"
    p_lower = p.lower()
    if any(p_lower.startswith(pfx) for pfx in _BLOCKED_PREFIXES):
        return None, f"Path not allowed: {p}"
    if not any(p_lower.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        return None, "Only .pcap/.pcapng/.cap files are supported."
    if not os.path.isfile(p):
        return None, f"File not found: {p}"
    return p, None


# ── dnp3_analyze ──────────────────────────────────────────────────────────────

async def run_dnp3_analyze(args: str) -> str:
    """Tool runner for dnp3_analyze."""
    from ics.dnp3_analyzer import analyze_dnp3_capture

    parts = args.strip().split()
    raw_path = parts[0] if parts else ""
    max_packets = 2000
    if len(parts) > 1:
        try:
            max_packets = max(100, min(int(parts[1]), 10000))
        except ValueError:
            pass

    if raw_path:
        pcap, err = _validate_pcap(raw_path)
    else:
        current = _get_current_pcap()
        if not current:
            return (
                "[dnp3_analyze] No capture loaded. "
                "Load a PCAP first or provide a path: dnp3_analyze <path> [max_packets]"
            )
        pcap, err = _validate_pcap(current)

    if err:
        return f"[dnp3_analyze] {err}"

    try:
        return await analyze_dnp3_capture(pcap, max_packets=max_packets)
    except Exception as e:
        return f"[dnp3_analyze] Error: {e}"


register(ToolDef(
    name="dnp3_analyze",
    category="analysis",
    description=(
        "Analyze a PCAP for DNP3/SCADA traffic: extracts application layer function "
        "codes and object groups, computes statistics, and provides an LLM security "
        "assessment of Write/Operate commands and unsolicited responses."
    ),
    args_spec="[pcap_path] [max_packets]",
    runner=run_dnp3_analyze,
    safety="read",
    always_available=True,
    needs_packets=False,
    keywords={"dnp3", "scada", "ics", "ot", "substation", "rtu", "dtu", "outstation"},
))


# ── tshark_filter ─────────────────────────────────────────────────────────────

# Built-in display filter reference — used as fallback when RAG score is low
_FILTER_REFERENCE: dict[str, str] = {
    # Modbus
    "modbus":                   "modbus",
    "modbus read":              "modbus.func_code <= 4",
    "modbus write":             "modbus.func_code >= 5 and modbus.func_code <= 6",
    "modbus write multiple":    "modbus.func_code == 15 or modbus.func_code == 16",
    "modbus exception":         "modbus.exception_code > 0",
    "modbus exception error":   "modbus.exception_code >= 1 and modbus.exception_code <= 4",
    "modbus unit id":           "mbtcp.unit_id == <id>",
    # DNP3
    "dnp3":                     "dnp3",
    "dnp3 write":               "dnp3.al.func == 0x02",
    "dnp3 operate":             "dnp3.al.func == 0x04",
    "dnp3 direct operate":      "dnp3.al.func == 0x05",
    "dnp3 unsolicited":         "dnp3.al.func == 0x82",
    "dnp3 binary output":       "dnp3.al.obj == 12.1",
    # TCP anomalies
    "retransmission":           "tcp.analysis.retransmission",
    "tcp reset":                "tcp.flags.reset == 1",
    "tcp syn flood":            "tcp.flags.syn == 1 and tcp.flags.ack == 0",
    "duplicate ack":            "tcp.analysis.duplicate_ack",
    "zero window":              "tcp.analysis.zero_window",
    # DNS
    "dns":                      "dns",
    "dns query":                "dns.flags.response == 0",
    "dns response":             "dns.flags.response == 1",
    "dns failure":              "dns.flags.rcode != 0",
    # HTTP
    "http":                     "http",
    "http error":               "http.response.code >= 400",
    "http post":                "http.request.method == \"POST\"",
    # TLS
    "tls":                      "tls",
    "tls handshake":            "tls.handshake",
    "tls alert":                "tls.alert_message",
    # ARP
    "arp":                      "arp",
    "arp gratuitous":           "arp.isSolicited == 0",
    # ICMP
    "icmp":                     "icmp",
    "icmp unreachable":         "icmp.type == 3",
    # ICS / general
    "ics scada":                "modbus or dnp3 or opcua or enip",
    "broadcast":                "eth.dst == ff:ff:ff:ff:ff:ff",
    "multicast":                "eth.dst[0] & 1",
    "large packets":            "frame.len > 1400",
    "fragmented":               "ip.flags.mf == 1 or ip.frag_offset > 0",
}


def _fuzzy_match(query: str) -> Optional[str]:
    """Return the best-matching filter from _FILTER_REFERENCE."""
    q = query.lower().strip()
    # Exact match
    if q in _FILTER_REFERENCE:
        return _FILTER_REFERENCE[q]
    # Substring match (query contains key or key contains query)
    best_key = None
    best_score = 0
    for key in _FILTER_REFERENCE:
        common = sum(1 for w in q.split() if w in key)
        if common > best_score:
            best_score = common
            best_key = key
    if best_key and best_score > 0:
        return _FILTER_REFERENCE[best_key]
    return None


async def run_tshark_filter(args: str) -> str:
    """
    Tool runner for tshark_filter.

    Queries the RAG knowledge base for the correct tshark display filter.
    Falls back to _FILTER_REFERENCE if RAG score is below threshold.
    """
    query = args.strip()
    if not query:
        return "[tshark_filter] Usage: tshark_filter <description>  e.g. 'modbus exceptions'"

    rag_filter: Optional[str] = None
    rag_context: str = ""

    # 1. Try RAG retrieval
    try:
        from rag.retriever import retrieve_for_query
        ctx, chunks, best_score = await retrieve_for_query(query, n_results=5)
        if best_score >= 0.30 and ctx:
            rag_context = ctx
            rag_filter = _extract_filter_from_context(ctx, query)
    except Exception:
        pass

    if rag_filter:
        return (
            f"FILTER: {rag_filter}\n"
            f"SOURCE: knowledge base (RAG)\n\n"
            f"CONTEXT:\n{rag_context[:600]}"
        )

    # 2. Fallback: built-in reference
    fallback = _fuzzy_match(query)
    if fallback:
        return (
            f"FILTER: {fallback}\n"
            f"SOURCE: built-in reference\n\n"
            f"EXPLANATION: Matched built-in filter reference for '{query}'.\n"
            f"Run: tshark -r <pcap> -Y \"{fallback}\" -n\n"
            f"Tip: Load the tshark manual into the knowledge base for richer results."
        )

    # 3. No match — provide guidance
    return (
        f"[tshark_filter] No built-in filter found for '{query}'.\n\n"
        f"Try one of these common patterns:\n"
        + "\n".join(f"  tshark_filter \"{k}\"" for k in list(_FILTER_REFERENCE.keys())[:8])
        + "\n\nOr load the tshark display filter reference into the knowledge base "
        "via: POST /api/rag/seed-tshark"
    )


def _extract_filter_from_context(context: str, query: str) -> Optional[str]:
    """
    Heuristically extract a display filter expression from RAG context text.
    Looks for lines containing common tshark filter patterns.
    """
    import re
    # Pattern: filter expressions often appear as: "modbus.func_code == X"
    # or quoted in code blocks
    filter_pattern = re.compile(
        r'`([a-z][a-z0-9_.]+\s*(?:==|!=|>=|<=|>|<|contains|matches)\s*[^\`\n]{1,80})`'
        r'|tshark.*-Y\s+"([^"]+)"'
        r'|display\s+filter[:\s]+([a-z][^\n]{1,80})',
        re.IGNORECASE
    )
    for m in filter_pattern.finditer(context):
        candidate = next(g for g in m.groups() if g)
        candidate = candidate.strip().strip('"\'')
        if len(candidate) >= 4:
            return candidate
    return None


register(ToolDef(
    name="tshark_filter",
    category="analysis",
    description=(
        "Generate the correct tshark display filter for a plain-language description. "
        "Queries the knowledge base first; falls back to a built-in ICS/network filter "
        "reference. Example: tshark_filter 'modbus exceptions' → modbus.exception_code > 0"
    ),
    args_spec="<description>",
    runner=run_tshark_filter,
    safety="read",
    always_available=True,
    needs_packets=False,
    keywords={
        "filter", "display", "tshark", "wireshark", "capture", "query",
        "how", "syntax", "expression", "modbus", "dnp3", "tcp", "udp",
    },
))


# ── DNP3 Forensics (raw TOON, no nested LLM call) ───────────────────────────

# Sensitive DNP3 object groups (physical I/O, time, device status)
_SENSITIVE_GROUPS = {12, 30, 40, 41, 50, 80}
_SENSITIVE_GROUP_NAMES = {
    12: "CROB",      # Binary Output Command — controls relays
    30: "AnalogIn",  # Sensor readings
    40: "AnalogOut",  # Setpoint commands
    41: "AnalogCmd",  # Direct output control
    50: "Time",       # Clock synchronization
    80: "Indications",  # Device status flags
}


async def run_dnp3_forensics(args: str) -> str:
    """Extract DNP3 Write/Operate commands (FC 2-6) targeting sensitive objects.

    Returns TOON-formatted table with security annotations.
    No internal LLM call — the agent's outer loop reasons over the data.
    """
    from utils.tshark_utils import find_tshark
    from utils.toon import tshark_fields_to_toon, _val
    from utils.sanitize import sanitize_tshark_output, validate_read_only_command

    parts = args.strip().split()
    raw_path = parts[0] if parts else ""
    max_packets = int(parts[1]) if len(parts) > 1 else 2000

    # Resolve PCAP path
    if raw_path:
        pcap, err = _validate_pcap(raw_path)
    else:
        current = _get_current_pcap()
        if not current:
            return (
                "[dnp3_forensics] No capture file loaded. "
                "Provide a path or load a PCAP first."
            )
        pcap, err = _validate_pcap(current)
    if err:
        return f"[dnp3_forensics] {err}"

    tshark = find_tshark()
    if not tshark:
        return "[tshark not found] Install Wireshark."

    # Filter: Write (0x02), Select (0x03), Operate (0x04),
    #         Direct Operate (0x05), Direct Operate No Ack (0x06)
    cmd = [
        tshark, "-r", pcap, "-n",
        "-Y", "dnp3.al.func >= 2 and dnp3.al.func <= 6",
        "-c", str(max_packets),
        "-T", "fields", "-E", "separator=,",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "dnp3.src",
        "-e", "dnp3.dst",
        "-e", "dnp3.al.func",
        "-e", "dnp3.al.obj",
    ]

    if not validate_read_only_command(cmd):
        return "[safety] Command rejected."

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: proc.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=90,
            ),
        )
    except Exception as e:
        return f"[dnp3_forensics error] {e}"

    if result.returncode != 0 and not result.stdout.strip():
        return f"[tshark error] {result.stderr[:300]}"

    raw = sanitize_tshark_output(result.stdout)
    if not raw.strip():
        return "[dnp3_forensics] No DNP3 Write/Operate commands found in capture."

    # Parse and annotate with security flags
    columns = ["frame", "time", "ip_src", "ip_dst", "dnp3_src", "dnp3_dst", "func", "obj"]
    records: list[dict] = []
    sensitive_count = 0

    for line in raw.strip().splitlines():
        fields = line.split(",")
        if len(fields) < len(columns):
            fields.extend([""] * (len(columns) - len(fields)))

        row: dict = {col: _val(fields[i], 50) for i, col in enumerate(columns)}

        # Check if object group is sensitive
        obj_str = fields[7] if len(fields) > 7 else ""
        security_flag = "-"
        try:
            # dnp3.al.obj may be "group:variation" like "12:1" or just group
            group_num = int(obj_str.split(":")[0]) if obj_str else 0
            if group_num in _SENSITIVE_GROUPS:
                security_flag = f"SENSITIVE({_SENSITIVE_GROUP_NAMES.get(group_num, group_num)})"
                sensitive_count += 1
        except (ValueError, IndexError):
            pass

        row["security"] = security_flag
        records.append(row)

    if not records:
        return "[dnp3_forensics] No DNP3 Write/Operate commands found."

    # Build TOON table
    from utils.toon import to_toon
    toon = to_toon(records, "DNP3_WRITE_OPS")

    # Append summary
    summary = (
        f"\nSummary: {len(records)} Write/Operate commands, "
        f"{sensitive_count} targeting sensitive object groups."
    )

    return toon + summary


register(ToolDef(
    name="dnp3_forensics",
    category="analysis",
    description=(
        "Extract DNP3 Write/Operate commands from PCAP as TOON table with "
        "security annotations. Flags sensitive object groups (CROB, Analog I/O, "
        "Time, Indications). Raw data — no LLM call."
    ),
    args_spec="[pcap_path] [max_packets]",
    runner=run_dnp3_forensics,
    safety="read",
    always_available=True,
    needs_packets=False,
    keywords={
        "dnp3", "scada", "write", "operate", "crob",
        "unauthorized", "forensics", "ics", "control",
    },
))
