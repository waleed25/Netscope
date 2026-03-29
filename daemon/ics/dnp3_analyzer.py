"""
DNP3 PCAP Analyzer.

Extracts DNP3 Application Layer packets from a PCAP using tshark CSV output,
computes statistics, converts to TOON format, and runs an LLM analysis pass
(same pattern as modbus/wireshark_analyzer.py).
"""

from __future__ import annotations
import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from utils import proc
from utils.tshark_utils import find_tshark
from utils.toon import to_toon, stats_to_toon, _val
from utils.sanitize import sanitize_tshark_output, validate_read_only_command

# ── DNP3 Application Layer function code reference ────────────────────────────

DNP3_AL_FUNCS: dict[str, str] = {
    "0x00": "Confirm",
    "0x01": "Read",
    "0x02": "Write",
    "0x03": "Select",
    "0x04": "Operate",
    "0x05": "Direct Operate",
    "0x06": "Direct Operate No Ack",
    "0x07": "Immediate Freeze",
    "0x08": "Immediate Freeze No Ack",
    "0x09": "Freeze and Clear",
    "0x0a": "Freeze and Clear No Ack",
    "0x0b": "Freeze with Time",
    "0x0c": "Freeze with Time No Ack",
    "0x0d": "Cold Restart",
    "0x0e": "Warm Restart",
    "0x0f": "Initialize Data",
    "0x10": "Initialize Application",
    "0x11": "Start Application",
    "0x12": "Stop Application",
    "0x13": "Save Configuration",
    "0x14": "Enable Unsolicited",
    "0x15": "Disable Unsolicited",
    "0x16": "Assign Class",
    "0x17": "Delay Measure",
    "0x18": "Record Current Time",
    "0x19": "Open File",
    "0x1a": "Close File",
    "0x1b": "Delete File",
    "0x1c": "Get File Info",
    "0x1d": "Authenticate File",
    "0x1e": "Abort File",
    "0x1f": "Activate Config",
    "0x20": "Authentication Request",
    "0x21": "Authentication Error",
    "0x81": "Response",
    "0x82": "Unsolicited Response",
    "0x83": "Authentication Response",
}

# DNP3 object groups of interest for security analysis
_SENSITIVE_GROUPS = {
    "12": "Binary Output Command (CROB)",
    "30": "Analog Input",
    "40": "Analog Output",
    "41": "Analog Output Command",
    "50": "Time and Date",
    "80": "Internal Indications",
    "110": "Octet String",
}

_WRITE_FUNCS = {"0x02", "0x03", "0x04", "0x05", "0x06", "0x07", "0x08", "0x09"}
_UNSOLICITED_FUNC = "0x82"


# ── tshark extraction ─────────────────────────────────────────────────────────

def _run_tshark_dnp3(pcap_path: Path, max_packets: int) -> str:
    tshark = find_tshark()
    if not tshark:
        return "[tshark not found] Install Wireshark to enable DNP3 analysis."

    cmd = [
        tshark,
        "-r", str(pcap_path),
        "-n",
        "-Y", "dnp3",
        "-c", str(max_packets),
        "-T", "fields",
        "-E", "separator=,",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "dnp3.src",
        "-e", "dnp3.dst",
        "-e", "dnp3.al.func",
        "-e", "dnp3.al.obj",
        "-e", "dnp3.ctl",
    ]

    if not validate_read_only_command(cmd):
        return "[safety] Command rejected: contains write operations."

    try:
        result = proc.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        raw = result.stdout if result.returncode == 0 else f"[tshark error] {result.stderr[:300]}"
        return sanitize_tshark_output(raw)
    except subprocess.TimeoutExpired:
        return "[timeout] DNP3 analysis took too long."
    except Exception as e:
        return f"[error] {e}"


# ── CSV parser ────────────────────────────────────────────────────────────────

def parse_dnp3_csv(raw: str) -> list[dict]:
    packets = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        # Pad to expected length
        while len(parts) < 9:
            parts.append("")
        packets.append({
            "frame":    parts[0] or "?",
            "time":     parts[1] or "?",
            "ip_src":   parts[2] or "?",
            "ip_dst":   parts[3] or "?",
            "dnp3_src": parts[4] or "?",
            "dnp3_dst": parts[5] or "?",
            "func":     parts[6] or "?",
            "obj":      parts[7] or "?",
            "ctl":      parts[8] or "?",
        })
    return packets


# ── Statistics ────────────────────────────────────────────────────────────────

def compute_dnp3_stats(packets: list[dict]) -> dict:
    func_counts: dict[str, int] = {}
    obj_counts:  dict[str, int] = {}
    src_set:  set[str] = set()
    dst_set:  set[str] = set()
    write_count = 0
    unsolicited_count = 0
    sensitive_obj_count = 0

    for p in packets:
        func = p["func"].lower().strip()
        obj  = p["obj"].strip()

        func_counts[func] = func_counts.get(func, 0) + 1
        if obj and obj != "?":
            obj_counts[obj] = obj_counts.get(obj, 0) + 1

        if p["ip_src"] not in ("?", ""):
            src_set.add(p["ip_src"])
        if p["ip_dst"] not in ("?", ""):
            dst_set.add(p["ip_dst"])

        if func in _WRITE_FUNCS:
            write_count += 1
        if func == _UNSOLICITED_FUNC:
            unsolicited_count += 1

        # Check if object group is sensitive
        obj_group = obj.split(".")[0] if obj else ""
        if obj_group in _SENSITIVE_GROUPS:
            sensitive_obj_count += 1

    return {
        "total_packets":     len(packets),
        "unique_sources":    len(src_set),
        "unique_destinations": len(dst_set),
        "write_count":       write_count,
        "unsolicited_count": unsolicited_count,
        "sensitive_obj_count": sensitive_obj_count,
        "func_code_counts":  func_counts,
        "object_counts":     obj_counts,
    }


# ── LLM analysis ─────────────────────────────────────────────────────────────

def _build_llm_prompt(packets: list[dict], stats: dict) -> list[dict]:
    sample = packets[:60]
    toon_table = to_toon(sample, "DNP3_PACKETS")
    toon_stats = stats_to_toon(
        {k: v for k, v in stats.items() if not isinstance(v, dict)},
        "DNP3_STATS"
    )

    # Human-readable function code summary
    func_lines = []
    for fc, cnt in sorted(stats["func_code_counts"].items(), key=lambda x: -x[1])[:10]:
        name = DNP3_AL_FUNCS.get(fc.lower(), DNP3_AL_FUNCS.get(fc, "Unknown"))
        func_lines.append(f"  {fc} ({name}): {cnt}")
    func_summary = "\n".join(func_lines) or "  (none)"

    # Sensitive object summary
    obj_lines = []
    for obj_key, cnt in sorted(stats["object_counts"].items(), key=lambda x: -x[1])[:10]:
        group = obj_key.split(".")[0]
        label = _SENSITIVE_GROUPS.get(group, "")
        obj_lines.append(f"  {obj_key}{' [' + label + ']' if label else ''}: {cnt}")
    obj_summary = "\n".join(obj_lines) or "  (none)"

    prompt = f"""You are a SCADA/ICS security expert analyzing DNP3 traffic from a Wireshark capture.

## Capture Statistics (TOON)
{toon_stats}

## Function Code Distribution
{func_summary}

## Object Group Distribution (top 10)
{obj_summary}

## Sample Packets (TOON, first 60)
{toon_table}

## Your Task
Analyze this DNP3 traffic and provide:
1. **Security Findings** — unauthorized writes, unexpected unsolicited responses, unusual function codes
2. **Operational Patterns** — normal vs anomalous SCADA behavior
3. **Affected Endpoints** — source/destination DNP3 addresses of concern
4. **Recommendations** — concrete mitigations

Focus on:
- Write/Operate/Select commands (FC 0x02–0x06) — should only come from master
- Unsolicited Responses (FC 0x82) — verify they are expected
- Binary Output Commands (Group 12) — direct physical control
- Replay or spoofing indicators (duplicate sequences, out-of-order frames)

Respond in markdown with clear sections."""

    return [{"role": "user", "content": prompt}]


# ── Main entry point ──────────────────────────────────────────────────────────

async def analyze_dnp3_capture(pcap_path: str, max_packets: int = 2000) -> str:
    """
    Analyze a PCAP file for DNP3 traffic.

    Returns a formatted analysis string (TOON + LLM narrative).
    """
    path = Path(pcap_path)

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, _run_tshark_dnp3, path, max_packets)

    if raw.startswith("["):
        return raw  # error message

    if not raw.strip():
        return "[no traffic] No DNP3 packets found in capture."

    packets = parse_dnp3_csv(raw)
    if not packets:
        return "[parse error] Could not extract DNP3 packets from capture."

    stats = compute_dnp3_stats(packets)

    toon_stats = stats_to_toon(
        {k: v for k, v in stats.items() if not isinstance(v, dict)},
        "DNP3_STATS"
    )
    toon_table = to_toon(packets[:100], "DNP3_PACKETS")

    try:
        from agent.llm_client import chat_completion
        messages = _build_llm_prompt(packets, stats)
        llm_result = await chat_completion(messages, temperature=0.3, max_tokens=500)
    except Exception as e:
        llm_result = f"[LLM error] {e}\n\nSee statistics above."

    return (
        f"## DNP3 Capture Analysis\n\n"
        f"### Statistics\n```\n{toon_stats}\n```\n\n"
        f"### Packet Sample (first 100)\n```\n{toon_table}\n```\n\n"
        f"{llm_result}\n"
    )
