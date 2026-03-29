"""
Modbus Wireshark Capture Analyzer using Qwen LLM.

Analyzes PCAP files for Modbus protocol issues and provides AI-powered insights.
"""

from __future__ import annotations
import subprocess
import os
import re
import asyncio
from typing import Optional
from dataclasses import dataclass

from utils import proc
from agent.llm_client import chat_completion
from utils.sanitize import sanitize_tshark_output, validate_read_only_command


@dataclass
class ModbusPacket:
    frame_num: int
    time_rel: float
    func_code: str
    unit_id: str
    src_ip: str
    dst_ip: str
    src_port: str
    dst_port: str
    exception_code: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class AnalysisResult:
    total_packets: int
    exception_count: int
    error_count: int
    unique_devices: int
    func_codes: dict
    exceptions: dict
    llm_analysis: str


def find_tshark() -> Optional[str]:
    """Find tshark executable."""
    from utils.tshark_utils import find_tshark as _find
    return _find()


def export_modbus_packets(pcap_path: str, filter_str: str = "modbus || modbus.tcp", max_packets: int = 5000) -> str:
    """Export Modbus packets from PCAP using tshark."""
    tshark = find_tshark()
    if not tshark:
        return "[tshark not found] Install Wireshark to enable packet analysis."

    if not os.path.exists(pcap_path):
        return f"[file not found] {pcap_path}"

    fields = [
        "frame.number", "frame.time_relative",
        "modbus.func_code", "modbus.unit_id",
        "ip.src", "ip.dst", "tcp.srcport", "tcp.dstport",
        "modbus.exception_code", "modbus.error_code"
    ]

    cmd = [
        tshark, "-r", pcap_path,
        "-Y", filter_str,
        "-c", str(max_packets),
        "-T", "fields",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "modbus.func_code",
        "-e", "modbus.unit_id",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "tcp.srcport",
        "-e", "tcp.dstport",
        "-e", "modbus.exception_code",
        "-e", "modbus.error_code"
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
            timeout=60
        )
        raw = result.stdout if result.returncode == 0 else f"[tshark error] {result.stderr}"
        return sanitize_tshark_output(raw)
    except subprocess.TimeoutExpired:
        return "[timeout] Capture analysis took too long."
    except Exception as e:
        return f"[error] {str(e)}"


def parse_packets(raw: str) -> list[ModbusPacket]:
    """Parse tshark output into ModbusPacket objects."""
    packets = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        try:
            pkt = ModbusPacket(
                frame_num=int(parts[0]) if parts[0] else 0,
                time_rel=float(parts[1]) if parts[1] else 0.0,
                func_code=parts[2] or "unknown",
                unit_id=parts[3] or "0",
                src_ip=parts[4] or "",
                dst_ip=parts[5] or "",
                src_port=parts[6] or "",
                dst_port=parts[7] or "",
                exception_code=parts[8] if len(parts) > 8 and parts[8] else None,
                error_code=parts[9] if len(parts) > 9 and parts[9] else None,
            )
            packets.append(pkt)
        except (ValueError, IndexError):
            continue
    return packets


def compute_stats(packets: list[ModbusPacket]) -> dict:
    """Compute basic statistics from parsed packets."""
    func_codes: dict[str, int] = {}
    exceptions: dict[str, int] = {}
    devices = set()

    for p in packets:
        # Count function codes
        func_codes[p.func_code] = func_codes.get(p.func_code, 0) + 1
        # Count exceptions
        if p.exception_code:
            exceptions[p.exception_code] = exceptions.get(p.exception_code, 0) + 1
        # Track unique devices
        if p.src_ip:
            devices.add(p.src_ip)
        if p.dst_ip:
            devices.add(p.dst_ip)

    return {
        "total": len(packets),
        "exception_count": sum(exceptions.values()),
        "error_count": sum(1 for p in packets if p.error_code),
        "unique_devices": len(devices),
        "func_codes": func_codes,
        "exceptions": exceptions,
    }


def build_llm_prompt(packets: list[ModbusPacket], stats: dict) -> list[dict]:
    """Build messages for Qwen LLM analysis using TOON format."""
    from utils.toon import to_toon, stats_to_toon

    # Convert sample packets to TOON table (limit to 50 for prompt size)
    sample = packets[:50]
    packet_dicts = [
        {
            "frame": p.frame_num,
            "fc": p.func_code,
            "unit": p.unit_id,
            "src": f"{p.src_ip}:{p.src_port}",
            "dst": f"{p.dst_ip}:{p.dst_port}",
            "exc": p.exception_code or "-",
            "err": p.error_code or "-",
        }
        for p in sample
    ]
    toon_packets = to_toon(packet_dicts, "MODBUS_SAMPLE")

    # Convert stats to TOON key-value block
    toon_stats = stats_to_toon({
        "total_packets": stats["total"],
        "exception_count": stats["exception_count"],
        "error_count": stats["error_count"],
        "unique_devices": stats["unique_devices"],
        "func_codes": stats["func_codes"],
        "exceptions": stats["exceptions"],
    }, "MODBUS_STATS")

    prompt = f"""You are a network protocol expert analyzing Modbus/TCP traffic from a Wireshark capture.

{toon_stats}

{toon_packets}

## Your Task
Analyze this Modbus traffic and provide:
1. **Issues Found** - Specific problems with cause and affected devices
2. **Patterns** - Any suspicious or repeated behavior
3. **Recommendations** - Actionable fixes

Focus on:
- Exception codes (1-4 indicate errors)
- Unusual function codes
- High error rates
- Timing issues
- Device-specific problems

Respond in markdown format with clear sections."""

    return [{"role": "user", "content": prompt}]


async def analyze_capture(pcap_path: str, filter_str: str = "modbus || modbus.tcp", max_packets: int = 5000) -> str:
    """
    Main entry point: Analyze a Modbus PCAP file.
    
    Returns formatted analysis results.
    """
    # Export packets — run in executor to avoid blocking the async event loop
    # (export_modbus_packets calls subprocess.run with a 60s timeout)
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None, export_modbus_packets, pcap_path, filter_str, max_packets
    )

    if raw.startswith("["):
        return raw  # Error message

    if not raw.strip():
        return "[no traffic] No Modbus packets found matching filter."

    # Parse and compute stats
    packets = parse_packets(raw)
    if not packets:
        return "[parse error] Could not extract Modbus packets from capture."

    stats = compute_stats(packets)

    # Get LLM analysis
    try:
        messages = build_llm_prompt(packets, stats)
        llm_result = await chat_completion(messages, temperature=0.3, max_tokens=400)
    except Exception as e:
        llm_result = f"[LLM error] {str(e)}\n\nFallback: See statistics above."

    # Format final output
    return f"""## Modbus Capture Analysis

### Summary
- Total packets: {stats['total']}
- Exceptions: {stats['exception_count']}
- Errors: {stats['error_count']}
- Unique devices: {stats['unique_devices']}

{llm_result}
"""


# Sync wrapper for tool integration
def analyze_capture_sync(pcap_path: str, filter_str: str = "modbus || modbus.tcp", max_packets: int = 5000) -> str:
    """Synchronous wrapper for analyze_capture."""
    try:
        return asyncio.run(analyze_capture(pcap_path, filter_str, max_packets))
    except Exception as e:
        return f"[error] {str(e)}"


if __name__ == "__main__":
    # Quick test
    import sys
    if len(sys.argv) > 1:
        print(asyncio.run(analyze_capture(sys.argv[1])))
    else:
        print("Usage: python -m modbus.analyzer_skill <pcap_file>")
