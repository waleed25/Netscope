"""
subnet_scanner.py — Async ping-sweep with NetBIOS name resolution and MAC/vendor lookup.

Public API
----------
async def scan_subnet(
    cidr: str,
    *,
    max_concurrent: int = 100,
    timeout: float = 1.0,
    on_result: Callable[[HostResult], None] | None = None,
) -> list[HostResult]

HostResult fields
-----------------
ip          str   — dotted-decimal IPv4 address
alive       bool  — responded to ICMP ping
hostname    str   — DNS PTR name (or "" if not resolved)
netbios     str   — NetBIOS/NBNS machine name (or "")
mac         str   — MAC address from ARP cache (or "")
vendor      str   — OUI vendor from mac-vendor-lookup (or "Unknown")
latency_ms  float — round-trip time in ms (or -1 if unreachable)
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import struct
import time
from dataclasses import dataclass, field, asdict
from typing import AsyncIterator, Callable

from utils import proc

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class HostResult:
    ip:         str
    alive:      bool  = False
    hostname:   str   = ""
    netbios:    str   = ""
    mac:        str   = ""
    vendor:     str   = ""
    latency_ms: float = -1.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── ICMP ping ─────────────────────────────────────────────────────────────────

def _icmp_checksum(data: bytes) -> int:
    s = 0
    for i in range(0, len(data) - 1, 2):
        s += (data[i] << 8) + data[i + 1]
    if len(data) % 2:
        s += data[-1] << 8
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def _build_icmp_echo(seq: int = 1) -> bytes:
    pid   = 0xBEEF & 0xFFFF
    hdr   = struct.pack(">BBHHH", 8, 0, 0, pid, seq)
    cksum = _icmp_checksum(hdr + b"\x00" * 8)
    return struct.pack(">BBHHH", 8, 0, cksum, pid, seq) + b"\x00" * 8


async def _ping_host(ip: str, timeout: float = 1.0) -> float:
    """
    Send one raw ICMP echo request.  Returns latency in ms, or -1 on failure.

    Falls back to subprocess ping when raw sockets are not available
    (e.g. no admin rights on Windows).
    """
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _ping_raw, ip, timeout)
    except (PermissionError, OSError):
        return await loop.run_in_executor(None, _ping_subprocess, ip, timeout)


def _ping_raw(ip: str, timeout: float) -> float:
    """Raw ICMP ping — requires elevated privileges."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    sock.settimeout(timeout)
    pkt  = _build_icmp_echo(1)
    try:
        t0 = time.perf_counter()
        sock.sendto(pkt, (ip, 0))
        while True:
            data, addr = sock.recvfrom(1024)
            if addr[0] == ip:
                icmp_type = data[20]
                if icmp_type == 0:  # echo reply
                    return (time.perf_counter() - t0) * 1000
    except (socket.timeout, OSError):
        return -1.0
    finally:
        sock.close()


def _ping_subprocess(ip: str, timeout: float) -> float:
    """Subprocess ping fallback for non-admin environments."""
    import platform
    timeout_ms = max(1, int(timeout * 1000))
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        cmd = ["ping", "-c", "1", f"-W{max(1, int(timeout))}", ip]
    try:
        t0  = time.perf_counter()
        out = proc.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
        elapsed = (time.perf_counter() - t0) * 1000
        if out.returncode == 0:
            # Try to extract RTT from output
            m = re.search(r"(?:time[=<]|TTL=)\s*(\d+(?:\.\d+)?)", out.stdout, re.I)
            if m:
                return float(m.group(1))
            return elapsed
        return -1.0
    except Exception:
        return -1.0


# ── DNS reverse lookup ────────────────────────────────────────────────────────

async def _resolve_hostname(ip: str) -> str:
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: socket.gethostbyaddr(ip)
        )
        return result[0]
    except Exception:
        return ""


# ── NetBIOS name query ────────────────────────────────────────────────────────

def _netbios_query(ip: str, timeout: float = 1.0) -> str:
    """
    Send a NetBIOS Name Service (NBNS) node status request (UDP 137).
    Returns the machine name if the host responds, else "".

    Packet layout: RFC 1002, section 4.2.18
    """
    # NBNS query packet: TXN_ID + flags + qdcount + ... + NBSTAT query
    # This is a "node status" request for * (wildcard)
    TXN_ID = b"\xab\xcd"
    HEADER = TXN_ID + b"\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    # Encoded wildcard name: 32 'C's + 'A' + null terminator
    NAME   = b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + b"\x00"
    QTYPE  = b"\x00\x21"   # NBSTAT
    QCLASS = b"\x00\x01"   # IN
    pkt    = HEADER + NAME + QTYPE + QCLASS

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(pkt, (ip, 137))
        data, _ = sock.recvfrom(1024)
        # Parse response: skip 56 bytes of header, then read name table
        if len(data) < 57:
            return ""
        num_names = data[56]
        offset = 57
        names: list[str] = []
        for _ in range(num_names):
            if offset + 18 > len(data):
                break
            raw_name = data[offset:offset + 15].rstrip(b"\x00 ").decode("ascii", errors="replace")
            name_type = data[offset + 15]
            flags     = struct.unpack_from(">H", data, offset + 16)[0]
            # Type 0x00 = workstation name (not group), type 0x03 = messenger
            if name_type == 0x00 and not (flags & 0x8000):
                names.append(raw_name.strip())
            offset += 18
        return names[0] if names else ""
    except Exception:
        return ""
    finally:
        sock.close()


# ── ARP cache MAC lookup ──────────────────────────────────────────────────────

_ARP_CACHE: dict[str, str] = {}
_ARP_CACHE_LOADED = False


def _load_arp_cache() -> None:
    """Populate _ARP_CACHE from the OS ARP table."""
    global _ARP_CACHE_LOADED
    import platform
    try:
        if platform.system() == "Windows":
            out = proc.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        else:
            out = proc.run(["arp", "-n"], capture_output=True, text=True, timeout=5)

        for line in out.stdout.splitlines():
            # Windows: "  192.168.1.1          aa-bb-cc-dd-ee-ff     dynamic"
            # Linux:   "192.168.1.1 ether  aa:bb:cc:dd:ee:ff  C  eth0"
            m = re.search(
                r"(\d{1,3}(?:\.\d{1,3}){3})\s+[^\s]*\s+([0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2})",
                line
            )
            if m:
                ip_addr  = m.group(1)
                mac_addr = m.group(2).upper().replace("-", ":")
                _ARP_CACHE[ip_addr] = mac_addr
        _ARP_CACHE_LOADED = True
    except Exception:
        _ARP_CACHE_LOADED = True  # mark as loaded even on failure


def _get_mac(ip: str) -> str:
    """Look up a MAC from the OS ARP cache after pinging the host."""
    global _ARP_CACHE_LOADED
    # Reload on first call or when a new host might have been added
    _load_arp_cache()
    return _ARP_CACHE.get(ip, "")


# ── MAC vendor lookup (OUI database) ─────────────────────────────────────────

# Inline OUI prefix table — top ~250 most common vendors.
# Format: first 3 octets uppercase colon-separated → vendor name.
# This avoids any network call; for unknown OUIs we fall back to "Unknown".
_OUI: dict[str, str] = {
    "00:00:0C": "Cisco",
    "00:01:42": "Cisco",
    "00:04:9A": "Cisco",
    "00:07:50": "Cisco",
    "00:08:E3": "Cisco",
    "00:0A:41": "Cisco",
    "00:0B:45": "Cisco",
    "00:0D:28": "Cisco",
    "00:0D:BC": "Cisco",
    "00:0E:08": "Cisco",
    "00:0F:8F": "Cisco",
    "00:11:5C": "Cisco",
    "00:12:00": "Cisco",
    "00:13:1A": "Cisco",
    "00:14:69": "Cisco",
    "00:16:C7": "Cisco",
    "00:17:94": "Cisco",
    "00:18:18": "Cisco",
    "00:19:06": "Cisco",
    "00:1A:2F": "Cisco",
    "00:1B:53": "Cisco",
    "00:1C:57": "Cisco",
    "00:1D:70": "Cisco",
    "00:1E:7A": "Cisco",
    "00:1F:9D": "Cisco",
    "00:21:A0": "Cisco",
    "00:22:55": "Cisco",
    "00:23:04": "Cisco",
    "00:24:13": "Cisco",
    "00:25:83": "Cisco",
    "00:26:0A": "Cisco",
    "00:26:CB": "Cisco",
    "00:50:56": "VMware",
    "00:0C:29": "VMware",
    "00:05:69": "VMware",
    "00:1C:14": "VMware",
    "08:00:27": "VirtualBox",
    "52:54:00": "QEMU/KVM",
    "00:15:5D": "Microsoft Hyper-V",
    "00:1A:92": "ASRock",
    "00:1B:21": "Intel",
    "00:1D:E0": "Intel",
    "00:1E:65": "Intel",
    "00:21:6A": "Intel",
    "00:22:FA": "Intel",
    "00:23:14": "Intel",
    "00:24:D7": "Intel",
    "00:26:B9": "Intel",
    "00:27:10": "Intel",
    "8C:EC:4B": "Intel",
    "A4:C3:F0": "Intel",
    "AC:FD:CE": "Intel",
    "B4:B6:86": "Intel",
    "D8:FC:93": "Intel",
    "F8:16:54": "Intel",
    "00:1B:63": "Apple",
    "00:25:BC": "Apple",
    "04:54:53": "Apple",
    "18:65:90": "Apple",
    "28:CF:E9": "Apple",
    "34:08:BC": "Apple",
    "3C:15:C2": "Apple",
    "60:FB:42": "Apple",
    "74:E1:B6": "Apple",
    "78:CA:39": "Apple",
    "8C:7B:9D": "Apple",
    "A4:5E:60": "Apple",
    "AC:BC:32": "Apple",
    "B8:63:4D": "Apple",
    "C8:2A:14": "Apple",
    "D0:23:DB": "Apple",
    "E0:F8:47": "Apple",
    "F4:5C:89": "Apple",
    "FC:E9:98": "Apple",
    "00:15:00": "Dell",
    "00:21:9B": "Dell",
    "14:18:77": "Dell",
    "18:03:73": "Dell",
    "24:B6:FD": "Dell",
    "34:17:EB": "Dell",
    "5C:F9:DD": "Dell",
    "78:45:C4": "Dell",
    "B8:CA:3A": "Dell",
    "F0:4D:A2": "Dell",
    "F8:DB:88": "Dell",
    "00:1A:4B": "Hewlett Packard",
    "00:1E:0B": "Hewlett Packard",
    "00:23:7D": "Hewlett Packard",
    "00:25:B3": "Hewlett Packard",
    "18:A9:05": "Hewlett Packard",
    "3C:D9:2B": "Hewlett Packard",
    "94:57:A5": "Hewlett Packard",
    "B4:99:BA": "Hewlett Packard",
    "D8:D3:85": "Hewlett Packard",
    "FC:15:B4": "Hewlett Packard",
    "00:0F:1F": "Dell",
    "00:1A:4B": "HP",
    "00:00:5E": "IANA (VRRP)",
    "01:00:5E": "IPv4 Multicast",
    "33:33:00": "IPv6 Multicast",
    "FF:FF:FF": "Broadcast",
    "00:00:0E": "Fujitsu",
    "00:00:48": "Seagate",
    "00:00:4C": "NEC",
    "00:00:74": "Ricoh",
    "00:00:AA": "Xerox",
    "00:00:F0": "Samsung",
    "00:01:29": "Advantech",
    "00:06:29": "Advantech",
    "00:D0:C9": "Advantech",
    "00:02:B3": "Intel",
    "00:03:47": "Intel",
    "00:03:BA": "Sun Microsystems",
    "00:04:75": "3Com",
    "00:04:AC": "IBM",
    "00:08:74": "Dell",
    "00:09:6B": "IBM",
    "00:0A:E6": "General Dynamics",
    "00:0B:AB": "Rockwell Automation",
    "00:1D:9C": "Rockwell Automation",
    "00:00:BC": "Allen-Bradley",
    "00:80:F4": "Schweitzer Engineering",
    "00:90:FA": "GE Energy",
    "00:04:B0": "Emerson/Rosemount",
    "00:60:35": "Schneider Electric",
    "00:80:A3": "Lantronix",
    "00:20:4A": "Network Computing Devices",
    "00:50:C2": "IEEE OUI (generic)",
    "00:0C:EF": "Beckhoff Automation",
    "00:01:05": "Motorola",
    "00:04:56": "Moxa Technologies",
    "00:90:E8": "Moxa Technologies",
    "00:10:BC": "Moxa Technologies",
    "00:60:97": "Siemens",
    "00:80:63": "Siemens",
    "00:E0:4B": "Siemens",
    "00:0E:8C": "Siemens",
    "00:13:A7": "Siemens",
    "00:1B:1B": "Siemens",
    "00:1C:06": "Siemens",
    "08:00:06": "Siemens",
    "A4:D0:E3": "Siemens",
    "00:00:AB": "Phoenix Contact",
    "00:A0:45": "Phoenix Contact",
    "00:60:34": "Phoenix Contact",
    "A4:97:B1": "ABB",
    "00:0A:DC": "ABB",
    "00:30:DE": "ABB",
    "00:20:85": "Honeywell",
    "00:40:2B": "Honeywell",
    "FC:AA:14": "Honeywell",
    "00:02:34": "Yokogawa",
    "00:0E:1E": "Yokogawa",
    "00:16:C0": "Yokogawa",
    "00:1E:61": "Endress+Hauser",
    "00:17:89": "Pepperl+Fuchs",
    "54:A0:50": "Hirschmann",
    "00:03:C1": "Hirschmann",
    "00:06:24": "Hirschmann",
    "00:09:E5": "Hirschmann",
    "00:80:63": "Hirschmann",
    "00:1A:87": "GE Fanuc",
    "00:60:52": "GE Fanuc",
    "00:40:BF": "GE Fanuc",
    "FC:CD:2F": "WAGO",
    "00:30:DE": "WAGO",
    "00:60:35": "WAGO",
    "00:1B:08": "Harting",
    "D8:80:39": "Mitsubishi",
    "00:00:E0": "Mitsubishi",
    "00:20:D2": "Mitsubishi",
    "00:11:B1": "Weintek",
    "74:FE:48": "Weintek",
    "00:E0:9C": "Omron",
    "00:00:73": "Omron",
    "00:A0:4B": "Omron",
    "00:00:A7": "Networks & Communications",
    "CC:F9:54": "Texas Instruments",
    "00:17:EC": "Texas Instruments",
    "D4:BE:D9": "Texas Instruments",
    "00:1A:E8": "Broadcom",
    "00:10:18": "Broadcom",
    "00:90:4C": "Broadcom",
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "D8:3A:DD": "Raspberry Pi",
    "28:CD:C1": "Raspberry Pi",
    "2C:CF:67": "TP-Link",
    "50:C7:BF": "TP-Link",
    "54:C8:0F": "TP-Link",
    "74:DA:38": "TP-Link",
    "B0:48:7A": "TP-Link",
    "F0:9F:C2": "TP-Link",
    "18:A6:F7": "Ubiquiti",
    "24:A4:3C": "Ubiquiti",
    "44:D9:E7": "Ubiquiti",
    "68:72:51": "Ubiquiti",
    "78:8A:20": "Ubiquiti",
    "80:2A:A8": "Ubiquiti",
    "DC:9F:DB": "Ubiquiti",
    "F0:9F:C2": "Ubiquiti",
    "00:18:0A": "Juniper Networks",
    "00:19:E2": "Juniper Networks",
    "00:23:9C": "Juniper Networks",
    "2C:6B:F5": "Juniper Networks",
    "28:8A:1C": "Juniper Networks",
    "00:1F:12": "Fortinet",
    "00:09:0F": "Fortinet",
    "90:6C:AC": "Fortinet",
    "00:0C:E6": "Palo Alto Networks",
    "7C:69:F6": "Palo Alto Networks",
    "18:9C:5D": "Palo Alto Networks",
}


def _lookup_vendor(mac: str) -> str:
    """Return OUI vendor name for a MAC address."""
    if not mac or len(mac) < 8:
        return "Unknown"
    oui = mac.upper()[:8]  # "AA:BB:CC"
    return _OUI.get(oui, "Unknown")


# ── Per-host scan ─────────────────────────────────────────────────────────────

async def _scan_host(ip: str, timeout: float) -> HostResult:
    result = HostResult(ip=ip)

    # 1. Ping
    latency = await _ping_host(ip, timeout)
    result.alive      = latency >= 0
    result.latency_ms = round(latency, 2) if latency >= 0 else -1.0

    if not result.alive:
        return result

    # 2. DNS + NetBIOS + ARP in parallel
    loop = asyncio.get_event_loop()

    hostname_task  = asyncio.create_task(_resolve_hostname(ip))
    netbios_future = loop.run_in_executor(None, _netbios_query, ip, timeout)

    result.hostname = await hostname_task

    # Re-read ARP cache (updated after successful ping)
    _load_arp_cache()
    _ARP_CACHE_LOADED  # already set
    # Re-trigger ARP if MAC not in cache yet by pinging again via subprocess
    mac = _ARP_CACHE.get(ip, "")
    if not mac:
        # Force ARP entry by sending another ping to populate the OS cache
        import platform
        try:
            if platform.system() == "Windows":
                proc.run(["ping", "-n", "1", "-w", "200", ip],
                         capture_output=True, timeout=1)
            else:
                proc.run(["ping", "-c", "1", "-W", "1", ip],
                         capture_output=True, timeout=1)
        except Exception:
            pass
        _load_arp_cache()
        mac = _ARP_CACHE.get(ip, "")

    result.mac    = mac
    result.vendor = _lookup_vendor(mac) if mac else ""
    result.netbios = await asyncio.wrap_future(netbios_future)

    return result


# ── Subnet scan ──────────────────────────────────────────────────────────────

async def scan_subnet(
    cidr: str,
    *,
    max_concurrent: int = 128,
    timeout: float = 1.0,
    on_result: Callable[[HostResult], None] | None = None,
) -> list[HostResult]:
    """
    Ping-sweep every host in *cidr* concurrently.

    Parameters
    ----------
    cidr          e.g. "192.168.1.0/24"  or a single IP "192.168.1.5"
    max_concurrent  max parallel probes (default 128)
    timeout         per-host timeout in seconds
    on_result       optional callback invoked for every completed host (alive or not)

    Returns a list of HostResult sorted by IP.
    """
    # Normalise input: accept bare IPs, CIDR, or range strings
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid subnet/IP: {cidr!r}") from exc

    if network.num_addresses > 65536:
        raise ValueError("Subnet too large (max /16). Please narrow the range.")

    hosts = list(network.hosts()) if network.num_addresses > 1 else [network.network_address]
    results: list[HostResult] = []
    sem = asyncio.Semaphore(max_concurrent)

    async def _probe(ip_obj: ipaddress.IPv4Address) -> None:
        async with sem:
            r = await _scan_host(str(ip_obj), timeout)
            results.append(r)
            if on_result:
                on_result(r)

    await asyncio.gather(*[_probe(h) for h in hosts])

    # Sort by IP numerically
    results.sort(key=lambda r: ipaddress.ip_address(r.ip))
    return results


async def scan_subnet_stream(
    cidr: str,
    *,
    max_concurrent: int = 128,
    timeout: float = 1.0,
) -> AsyncIterator[HostResult]:
    """
    Async generator that yields HostResult objects as each host is probed.
    Results arrive in completion order (not IP order).
    """
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid subnet/IP: {cidr!r}") from exc

    if network.num_addresses > 65536:
        raise ValueError("Subnet too large (max /16).")

    hosts = list(network.hosts()) if network.num_addresses > 1 else [network.network_address]
    sem   = asyncio.Semaphore(max_concurrent)
    queue: asyncio.Queue[HostResult | None] = asyncio.Queue()
    pending = len(hosts)

    async def _probe(ip_obj: ipaddress.IPv4Address) -> None:
        nonlocal pending
        async with sem:
            r = await _scan_host(str(ip_obj), timeout)
            await queue.put(r)

    tasks = [asyncio.create_task(_probe(h)) for h in hosts]

    received = 0
    while received < len(hosts):
        result = await queue.get()
        received += 1
        yield result

    await asyncio.gather(*tasks, return_exceptions=True)
