"""
tshark_expert tool — run tshark's built-in expert analysis on a PCAP.

Uses `tshark -z expert -q -n` to offload mathematical state tracking
(TCP reassembly errors, retransmissions, malformed packets, protocol warnings)
directly to Wireshark's dissection engine, then formats the output as TOON
for token-efficient delivery to the LLM.
"""

from __future__ import annotations
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

from agent.tools.registry import register, ToolDef
from utils import proc
from utils.tshark_utils import find_tshark
from utils.toon import expert_lines_to_toon
from utils.sanitize import sanitize_tshark_output, validate_read_only_command

# Paths blocked for path-traversal protection (mirrors modbus.py pattern)
_BLOCKED_PREFIXES = (
    r"c:\windows", r"c:\program files", r"c:\programdata",
    r"c:\users\default", r"c:\system",
)
_ALLOWED_EXTENSIONS = (".pcap", ".pcapng", ".cap")


def _get_current_pcap() -> Optional[str]:
    """Lazily import the current capture file path from routes to avoid circular import."""
    try:
        from api.routes import _current_capture_file
        return _current_capture_file if _current_capture_file else None
    except Exception:
        return None


def _validate_pcap_path(raw: str) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve and validate a PCAP path.
    Returns (resolved_path, error_message).
    """
    try:
        p = str(Path(raw).resolve())
    except Exception:
        return None, f"[tshark_expert] Invalid path: {raw}"

    p_lower = p.lower()
    if any(p_lower.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        return None, f"[tshark_expert] Path not allowed: {p}"
    if not any(p_lower.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        return None, "[tshark_expert] Only .pcap/.pcapng/.cap files are supported."
    if not os.path.isfile(p):
        return None, f"[tshark_expert] File not found: {p}"
    return p, None


def _run_expert(pcap_path: str) -> str:
    """Blocking call to tshark -z expert -q -n."""
    tshark = find_tshark()
    if not tshark:
        return "[tshark not found] Install Wireshark to enable expert analysis."

    cmd = [tshark, "-r", pcap_path, "-z", "expert", "-q", "-n"]

    # Read-only boundary enforcement
    if not validate_read_only_command(cmd):
        return "[safety] Command rejected: contains write operations."

    try:
        result = proc.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        output = sanitize_tshark_output(result.stdout)
        if not output.strip() and result.returncode != 0:
            return f"[tshark error] {result.stderr[:300]}"
        return output
    except subprocess.TimeoutExpired:
        return "[timeout] Expert analysis exceeded 90 seconds."
    except Exception as e:
        return f"[error] {e}"


async def run_tshark_expert(args: str) -> str:
    """
    Tool runner: run tshark built-in expert analysis on a PCAP.

    args: optional path to .pcap/.pcapng/.cap file.
          If omitted, uses the currently loaded capture file.
    """
    raw_path = args.strip()

    # Resolve PCAP path
    if raw_path:
        pcap, err = _validate_pcap_path(raw_path)
    else:
        current = _get_current_pcap()
        if not current:
            return (
                "[tshark_expert] No capture file is currently loaded. "
                "Load a PCAP first or provide a path: tshark_expert <path>"
            )
        pcap, err = _validate_pcap_path(current)

    if err:
        return err

    # Run in executor to avoid blocking the event loop
    loop = asyncio.get_running_loop()
    raw_output = await loop.run_in_executor(None, _run_expert, pcap)

    if raw_output.startswith("["):
        return raw_output  # error

    if not raw_output.strip():
        return "[tshark_expert] No expert info generated — capture may have no anomalies."

    lines = raw_output.splitlines()
    toon = expert_lines_to_toon(lines)
    summary_line = f"Expert analysis of: {Path(pcap).name}"
    return f"{summary_line}\n\n{toon}"


# ── Registration ──────────────────────────────────────────────────────────────

register(ToolDef(
    name="tshark_expert",
    category="analysis",
    description=(
        "Run tshark built-in expert analysis on a PCAP — surfaces TCP errors, "
        "retransmissions, malformed packets, and protocol warnings pre-calculated "
        "by Wireshark's dissection engine. Returns TOON-formatted anomaly table."
    ),
    args_spec="[pcap_path]",
    runner=run_tshark_expert,
    safety="read",
    always_available=True,
    needs_packets=False,
))
