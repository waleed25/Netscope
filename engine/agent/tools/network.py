"""
Network tools: ping, tracert, arp, netstat, ipconfig, capture.
"""
from __future__ import annotations
import asyncio
import os
import re
import shutil
import subprocess

from agent.tools.registry import register, ToolDef, MAX_OUTPUT
from utils import proc

# ── Target validation ────────────────────────────────────────────────────────

_TARGET_RE = re.compile(
    r"^(?:"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"  # FQDN
    r"|(?:\d{1,3}\.){3}\d{1,3}"                                              # IPv4
    r"|[0-9a-fA-F:]{2,39}"                                                   # IPv6 (simplified)
    r")$"
)


def _validate_host(raw: str, default: str = "8.8.8.8") -> tuple[str, str | None]:
    """Return (host, error_msg). error_msg is None when host is valid."""
    t = raw.strip()
    if not t:
        return default, None
    if len(t) > 255:
        return "", f"[tool error] Target too long."
    if not _TARGET_RE.match(t):
        return "", f"[tool error] Invalid target '{t}': must be a hostname or IP address."
    return t, None


# ── Executable paths ─────────────────────────────────────────────────────────

_EXECUTABLES = {
    "ping":     shutil.which("ping")     or r"C:\Windows\System32\PING.EXE",
    "tracert":  shutil.which("tracert")  or r"C:\Windows\System32\TRACERT.EXE",
    "arp":      shutil.which("arp")      or r"C:\Windows\System32\ARP.EXE",
    "netstat":  shutil.which("netstat")  or r"C:\Windows\System32\NETSTAT.EXE",
    "ipconfig": shutil.which("ipconfig") or r"C:\Windows\System32\ipconfig.exe",
}

# ── Allowlists ───────────────────────────────────────────────────────────────

_NETSTAT_OK = {"-a", "-n", "-o", "-ano", "-an", "-ao", "-no", "-b", "-e", "-s", "-p"}
_IPCONFIG_OK = {"/all", "/release", "/renew", "/flushdns", "/displaydns",
                "/registerdns", "/showclassid", "/setclassid"}


# ── Sync subprocess runner ───────────────────────────────────────────────────

def _run_subprocess(argv: list[str]) -> str:
    """Run a subprocess synchronously, return output string."""
    try:
        result = proc.run(
            argv, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return f"[tool error] Command timed out after 30 seconds."
    except Exception as exc:
        return f"[tool error] Failed to run command: {exc}"

    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n...[truncated — {len(output)} chars total]"
    return output or "[tool] Command produced no output."


async def _run_sync(fn, *args):
    """Wrap a sync function in run_in_executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


# ── Tool implementations ────────────────────────────────────────────────────

async def run_ping(args: str) -> str:
    host, err = _validate_host(args.strip(), default="8.8.8.8")
    if err:
        return err
    return await _run_sync(_run_subprocess, [_EXECUTABLES["ping"], "-n", "4", host])


async def run_tracert(args: str) -> str:
    host, err = _validate_host(args.strip(), default="8.8.8.8")
    if err:
        return err
    return await _run_sync(_run_subprocess, [_EXECUTABLES["tracert"], "-d", host])


async def run_arp(args: str) -> str:
    argv = [_EXECUTABLES["arp"], "-a"]
    if args.strip():
        host, err = _validate_host(args.strip())
        if err:
            return err
        argv.append(host)
    return await _run_sync(_run_subprocess, argv)


async def run_netstat(args: str) -> str:
    raw_flags = args.strip().split() if args.strip() else ["-ano"]
    bad = [f for f in raw_flags if f.lower() not in _NETSTAT_OK]
    if bad:
        return f"[tool error] netstat: disallowed flag(s): {bad}. Allowed: {sorted(_NETSTAT_OK)}"
    return await _run_sync(_run_subprocess, [_EXECUTABLES["netstat"]] + raw_flags)


async def run_ipconfig(args: str) -> str:
    raw_flags = args.strip().split() if args.strip() else ["/all"]
    bad = [f for f in raw_flags if f.lower() not in _IPCONFIG_OK]
    if bad:
        return f"[tool error] ipconfig: disallowed flag(s): {bad}. Allowed: {sorted(_IPCONFIG_OK)}"
    return await _run_sync(_run_subprocess, [_EXECUTABLES["ipconfig"]] + raw_flags)


async def run_capture(args: str) -> tuple[str, list[dict]]:
    """
    Async capture — starts live capture, waits, stops, returns (summary_json, packets).
    This tool is special: it returns a tuple, not a plain string.
    Handled separately in chat.py dispatch.
    """
    import json
    from collections import Counter
    from capture import live_capture
    from api.routes import clear_packets, add_packets, get_packets, _drain_loop

    # Parse duration — strip non-digit chars the LLM may include (e.g. "[50]")
    try:
        digits = re.sub(r"[^\d]", "", args.strip())
        seconds = max(1, min(int(digits), 120)) if digits else 10
    except (ValueError, TypeError):
        seconds = 10

    # Find interface
    interface = live_capture.get_active_interface()
    if not interface:
        try:
            ifaces = await live_capture.get_interfaces()
            preferred = fallback = None
            for iface in ifaces:
                name_lower = iface["name"].lower()
                if "loopback" in name_lower or "etw" in name_lower:
                    continue
                if preferred is None and ("wi-fi" in name_lower or "ethernet" in name_lower):
                    preferred = iface["index"]
                if fallback is None:
                    fallback = iface["index"]
            interface = preferred or fallback or ""
        except Exception:
            interface = ""

    if not interface:
        return "[capture error] No network interface available.", []

    if live_capture.is_capturing():
        await live_capture.stop_capture()
        await asyncio.sleep(0.5)

    clear_packets()
    await live_capture.start_capture(interface, "")
    await asyncio.sleep(0.3)

    drain_task = asyncio.create_task(_drain_loop())
    await asyncio.sleep(seconds)
    await live_capture.stop_capture()

    for _ in range(20):
        q = await live_capture.get_packet_queue()
        if q.empty():
            break
        await asyncio.sleep(0.1)

    drain_task.cancel()
    try:
        await drain_task
    except asyncio.CancelledError:
        pass

    packets = get_packets()
    count = len(packets)

    if count == 0:
        return f"[capture] No packets captured in {seconds}s on {interface}.", []

    def _safe(v, mx=120):
        s = str(v) if v is not None else ""
        return "".join(c for c in s if c.isprintable())[:mx]

    proto_counts = Counter(p.get("protocol", "?") for p in packets)
    src_ips = Counter(p.get("src_ip", "") for p in packets if p.get("src_ip"))
    dst_ips = Counter(p.get("dst_ip", "") for p in packets if p.get("dst_ip"))
    ports = Counter(p.get("dst_port", "") for p in packets if p.get("dst_port"))
    dns = list({p["details"]["dns_query"] for p in packets if p.get("details", {}).get("dns_query")})[:15]
    tls = list({p["details"]["tls_sni"] for p in packets if p.get("details", {}).get("tls_sni")})[:15]
    http = [
        f"{p['details'].get('http_method')} {p['details'].get('http_host','')}{p['details'].get('http_uri','')}"
        for p in packets if p.get("details", {}).get("http_method")
    ][:10]

    summary = json.dumps({
        "interface": interface, "duration_s": seconds, "packet_count": count,
        "protocols": dict(proto_counts.most_common(8)),
        "top_src_ips": dict(src_ips.most_common(5)),
        "top_dst_ips": dict(dst_ips.most_common(5)),
        "top_dst_ports": dict(ports.most_common(8)),
        "dns_queries": dns, "tls_sni": tls, "http_requests": http,
    })

    return summary, packets


# ── Registration ─────────────────────────────────────────────────────────────

register(ToolDef(
    name="ping", category="network",
    description="ICMP ping (e.g. ping 8.8.8.8)",
    args_spec="<host>", runner=run_ping,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="tracert", category="network",
    description="trace route",
    args_spec="<host>", runner=run_tracert,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="arp", category="network",
    description="ARP cache",
    args_spec="", runner=run_arp,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="netstat", category="network",
    description="connections (e.g. netstat -ano)",
    args_spec="[flags]", runner=run_netstat,
    safety="safe", always_available=True,
))

register(ToolDef(
    name="ipconfig", category="network",
    description="network config (e.g. ipconfig /all)",
    args_spec="[flag]", runner=run_ipconfig,
    safety="safe", always_available=True,
))

# Capture registration — runner is a placeholder since capture is dispatched specially
register(ToolDef(
    name="capture", category="network",
    description="capture live traffic (default 10s)",
    args_spec="[seconds]", runner=run_capture,  # type: ignore[arg-type]
    safety="dangerous", always_available=True,
))
