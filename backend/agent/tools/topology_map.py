"""
Network topology mapper.

Extracts physical/logical topology from pcap data using tshark:
  CDP/LLDP  → exact switch-port adjacency (highest confidence)
  ARP       → IP↔MAC mapping, broadcast domain grouping
  DHCP      → gateway / subnet discovery
  STP       → switch hierarchy (root bridge identification)
  VLAN      → network segmentation (802.1Q tags)

Falls back to subnet-grouping heuristics when discovery protocols are absent.
Can also incorporate live subnet scan results.
"""
from __future__ import annotations
import asyncio
import json
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from agent.tools.registry import ToolDef, register
from utils import proc

# ── MAC OUI → Vendor (network equipment focused) ─────────────────────────────

_OUI: dict[str, str] = {
    # Cisco
    "00:00:0c": "Cisco", "00:1a:a2": "Cisco", "00:14:6c": "Cisco",
    "00:24:13": "Cisco", "6c:41:6a": "Cisco", "00:19:aa": "Cisco",
    "70:ca:9b": "Cisco", "00:50:56": "VMware",
    # Juniper
    "00:10:db": "Juniper", "00:14:fe": "Juniper", "bc:ef:85": "Juniper",
    # Arista
    "fc:59:c0": "Arista", "50:eb:f6": "Arista", "44:4c:a8": "Arista",
    # HP / HPE / Aruba
    "00:0e:0b": "HP", "00:1c:c4": "HP", "94:18:82": "HP",
    "f4:ce:46": "HP", "00:17:a4": "HP", "3c:a8:2a": "HP",
    # Dell
    "00:14:22": "Dell", "6c:2b:59": "Dell", "14:18:77": "Dell",
    # Fortinet
    "00:09:0f": "Fortinet", "90:6c:ac": "Fortinet", "00:09:0e": "Fortinet",
    # Palo Alto Networks
    "00:1b:17": "Palo Alto",
    # Check Point
    "00:1c:7f": "CheckPoint",
    # Ubiquiti
    "24:a4:3c": "Ubiquiti", "68:72:51": "Ubiquiti", "fc:ec:da": "Ubiquiti",
    "dc:9f:db": "Ubiquiti", "80:2a:a8": "Ubiquiti",
    # Netgear
    "00:09:5b": "Netgear", "20:e5:2a": "Netgear", "a0:40:a0": "Netgear",
    # TP-Link
    "f0:9f:c2": "TP-Link", "50:3e:aa": "TP-Link", "c4:6e:1f": "TP-Link",
    # Mikrotik
    "00:0c:42": "Mikrotik", "48:8f:5a": "Mikrotik",
    # Huawei
    "e0:06:30": "Huawei", "d8:da:f1": "Huawei", "54:44:3b": "Huawei",
    # Extreme Networks
    "00:04:96": "Extreme", "00:e0:2b": "Extreme",
    # Brocade / Ruckus
    "00:27:f8": "Brocade", "00:05:33": "Brocade",
    # Siemens (ICS)
    "00:0e:8c": "Siemens", "00:1b:1b": "Siemens",
    # Schneider Electric (ICS)
    "00:80:f4": "Schneider", "00:20:85": "Schneider",
    # General Electric (ICS)
    "00:90:27": "GE",
    # Rockwell / Allen-Bradley (ICS)
    "00:00:bc": "Rockwell",
}

_SWITCH_VENDORS  = {"Cisco", "Juniper", "Arista", "HP", "Ubiquiti",
                    "Netgear", "TP-Link", "Mikrotik", "Huawei",
                    "Extreme", "Brocade"}
_FIREWALL_VENDORS = {"Fortinet", "CheckPoint", "Palo Alto", "Cisco"}
_ICS_VENDORS      = {"Siemens", "Schneider", "GE", "Rockwell"}


def _lookup_vendor(mac: str) -> str:
    if not mac:
        return "Unknown"
    return _OUI.get(mac.lower()[:8], "Unknown")


def _is_private(ip: str) -> bool:
    return (
        ip.startswith("192.168.") or ip.startswith("10.")
        or ip.startswith("172.") or ip == "127.0.0.1"
    )


# ── tshark helper ─────────────────────────────────────────────────────────────

def _find_tshark() -> str:
    found = shutil.which("tshark")
    if found:
        return found
    # Common Windows install locations when Wireshark is not on PATH
    for candidate in [
        r"C:\Program Files\Wireshark\tshark.exe",
        r"C:\Program Files (x86)\Wireshark\tshark.exe",
    ]:
        if Path(candidate).exists():
            return candidate
    return "tshark"


def _run_fields(pcap: str, display_filter: str, fields: list[str],
                max_packets: int = 1000) -> list[dict[str, str]]:
    """Run tshark -T fields on a pcap file; return list of {field: value} dicts."""
    cmd = [
        _find_tshark(), "-r", pcap,
        "-Y", display_filter,
        "-T", "fields",
        "-E", "separator=\t",
        "-E", "occurrence=f",
        "-c", str(max_packets),
    ]
    for f in fields:
        cmd += ["-e", f]
    try:
        result = proc.run(
            cmd, capture_output=True, text=True, timeout=20, check=False
        )
        rows: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == len(fields):
                rows.append(dict(zip(fields, parts)))
        return rows
    except Exception:
        return []


# ── Protocol parsers ──────────────────────────────────────────────────────────

def _parse_arp(pcap: str) -> dict[str, str]:
    """Return {ip: mac} from ARP replies in the capture."""
    rows = _run_fields(
        pcap, "arp.opcode == 2",
        ["arp.src.proto_ipv4", "arp.src.hw_mac"],
    )
    out: dict[str, str] = {}
    for r in rows:
        ip  = r.get("arp.src.proto_ipv4", "").strip()
        mac = r.get("arp.src.hw_mac", "").strip().lower()
        if ip and mac and mac != "00:00:00:00:00:00":
            out[ip] = mac
    return out


def _parse_dhcp(pcap: str) -> tuple[set[str], dict[str, str]]:
    """Return (gateway_ips, {client_mac: offered_ip})."""
    rows = _run_fields(
        pcap, "dhcp",
        ["dhcp.client_hardware_address", "dhcp.ip.your",
         "dhcp.option.router", "dhcp.option.dhcp_server_id"],
    )
    gateways: set[str] = set()
    mac_to_ip: dict[str, str] = {}
    for r in rows:
        gw = r.get("dhcp.option.router", "").strip()
        if gw and gw not in ("0.0.0.0", ""):
            gateways.add(gw)
        srv = r.get("dhcp.option.dhcp_server_id", "").strip()
        if srv and srv not in ("0.0.0.0", ""):
            gateways.add(srv)
        mac = r.get("dhcp.client_hardware_address", "").strip().lower()
        ip  = r.get("dhcp.ip.your", "").strip()
        if mac and ip and ip not in ("0.0.0.0", ""):
            mac_to_ip[mac] = ip
    return gateways, mac_to_ip


def _parse_cdp(pcap: str) -> list[dict]:
    """Return list of CDP adjacency records."""
    rows = _run_fields(
        pcap, "cdp",
        ["cdp.deviceid", "cdp.portid", "cdp.nrgyz.ip_address", "cdp.platform", "cdp.capabilities"],
        max_packets=200,
    )
    seen: set[tuple] = set()
    out: list[dict] = []
    for r in rows:
        key = (r.get("cdp.deviceid", ""), r.get("cdp.portid", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "device_id":    r.get("cdp.deviceid", "").strip(),
            "port_id":      r.get("cdp.portid", "").strip(),
            "ip":           r.get("cdp.nrgyz.ip_address", "").strip().split(",")[0],
            "platform":     r.get("cdp.platform", "").strip(),
            "capabilities": r.get("cdp.capabilities", "").strip(),
        })
    return out


def _parse_lldp(pcap: str) -> list[dict]:
    """Return list of LLDP adjacency records."""
    rows = _run_fields(
        pcap, "lldp",
        ["lldp.chassis.id", "lldp.port.id", "lldp.tlv.system.name",
         "lldp.port.desc", "lldp.mgn.addr.ip4"],
        max_packets=200,
    )
    seen: set[tuple] = set()
    out: list[dict] = []
    for r in rows:
        key = (r.get("lldp.chassis.id", ""), r.get("lldp.port.id", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "chassis_id":  r.get("lldp.chassis.id", "").strip(),
            "port_id":     r.get("lldp.port.id", "").strip(),
            "system_name": r.get("lldp.tlv.system.name", "").strip(),
            "port_desc":   r.get("lldp.port.desc", "").strip(),
            "mgmt_ip":     r.get("lldp.mgn.addr.ip4", "").strip(),
        })
    return out


def _parse_stp(pcap: str) -> dict:
    """Return STP root bridge MAC if found."""
    rows = _run_fields(
        pcap, "stp",
        ["stp.root.hw", "stp.bridge.hw"],
        max_packets=50,
    )
    if not rows:
        return {}
    root_macs = [
        r.get("stp.root.hw", "").strip().lower()
        for r in rows if r.get("stp.root.hw")
    ]
    if not root_macs:
        return {}
    root_mac = Counter(root_macs).most_common(1)[0][0]
    return {"root_bridge_mac": root_mac}


def _parse_vlans(pcap: str) -> dict[str, list[str]]:
    """Return {vlan_id: [src_ips]} from 802.1Q tagged frames.
    Checks both IP and ARP source addresses so VLAN-tagged ARP-only captures
    are handled correctly."""
    rows = _run_fields(
        pcap, "vlan",
        ["vlan.id", "ip.src", "arp.src.proto_ipv4"],
        max_packets=2000,
    )
    vlan_hosts: dict[str, set] = {}
    for r in rows:
        vid = r.get("vlan.id", "").strip()
        ip  = r.get("ip.src", "").strip() or r.get("arp.src.proto_ipv4", "").strip()
        if vid and ip and ip not in ("0.0.0.0", ""):
            vlan_hosts.setdefault(vid, set()).add(ip)
    return {k: list(v) for k, v in vlan_hosts.items()}


# ── Device classification ─────────────────────────────────────────────────────

def _classify_type(
    mac: str, vendor: str,
    is_gateway: bool, is_stp_root: bool, is_cdp_device: bool,
    protocols: list[str],
) -> str:
    if is_gateway:
        return "firewall" if vendor in _FIREWALL_VENDORS else "router"
    if is_stp_root or is_cdp_device:
        return "switch"
    if vendor in _SWITCH_VENDORS:
        return "switch"
    if vendor in _FIREWALL_VENDORS:
        return "firewall"
    if vendor in _ICS_VENDORS:
        return "plc"
    proto_set = {p.upper() for p in protocols}
    if any(p in proto_set for p in {"MODBUS", "DNP3", "OPCUA", "OPC-UA", "EIP"}):
        return "plc"
    if any(p in proto_set for p in {"HTTP", "HTTPS", "TLS", "SSH", "SMB", "RDP"}):
        return "server"
    return "endpoint"


# ── Main topology builder ─────────────────────────────────────────────────────

def build_topology(
    packets: list[dict],
    pcap_file: str | None,
    scan_results: list[dict] | None = None,
) -> dict:
    """
    Build a structured network topology from:
      - in-memory packets (protocol stats, partial ARP)
      - optional pcap file (tshark field extraction for CDP/LLDP/ARP/DHCP/STP/VLAN)
      - optional active scan results (HostResult.to_dict() list)
    """
    # ── 1. Aggregate protocol stats from in-memory packets ─────────────────────
    ip_protocols: dict[str, Counter] = defaultdict(Counter)
    ip_pkt_count: Counter = Counter()

    for pkt in packets:
        proto = pkt.get("protocol", "OTHER")
        for field in ("src_ip", "dst_ip"):
            ip = pkt.get(field, "")
            if ip and _is_private(ip):
                ip_protocols[ip][proto] += 1
                ip_pkt_count[ip] += 1

    # ── 2. Enrich from pcap ────────────────────────────────────────────────────
    ip_to_mac: dict[str, str] = {}
    gateways: set[str] = set()
    cdp_links: list[dict] = []
    lldp_links: list[dict] = []
    stp_info: dict = {}
    vlan_map: dict[str, list[str]] = {}

    has_pcap = pcap_file and Path(pcap_file).exists()
    if has_pcap:
        ip_to_mac.update(_parse_arp(pcap_file))
        dhcp_gw, dhcp_mac_ip = _parse_dhcp(pcap_file)
        gateways.update(dhcp_gw)
        for mac, ip in dhcp_mac_ip.items():
            ip_to_mac.setdefault(ip, mac)
        cdp_links  = _parse_cdp(pcap_file)
        lldp_links = _parse_lldp(pcap_file)
        stp_info   = _parse_stp(pcap_file)
        vlan_map   = _parse_vlans(pcap_file)

    # ── 3. Incorporate scan results ────────────────────────────────────────────
    scan_by_ip: dict[str, dict] = {}
    if scan_results:
        for h in scan_results:
            ip  = h.get("ip", "")
            mac = h.get("mac", "").lower()
            if ip:
                scan_by_ip[ip] = h
                if mac:
                    ip_to_mac.setdefault(ip, mac)
                if ip not in ip_pkt_count:
                    ip_pkt_count[ip] = 0

    # ── 4. Fallback gateway detection (heuristic: .1 / .254 suffix) ───────────
    if not gateways:
        for ip in list(ip_to_mac) + list(ip_pkt_count.keys()):
            last = ip.split(".")[-1] if "." in ip else ""
            if last in ("1", "254"):
                gateways.add(ip)

    # ── 5. Build switch nodes from CDP / LLDP ─────────────────────────────────
    switch_nodes: dict[str, dict] = {}

    for link in cdp_links:
        dev = link["device_id"]
        if not dev:
            continue
        node_id = f"cdp:{dev}"
        if node_id not in switch_nodes:
            switch_nodes[node_id] = {
                "id": node_id, "ip": link["ip"], "mac": "",
                "label": dev, "hostname": dev, "netbios": "",
                "vendor": "Cisco", "type": "switch",
                "platform": link["platform"],
                "protocols": [], "packets": 0,
                "vlan": None, "is_gateway": False,
                "ports": [], "level": 1,
            }
        if link["port_id"] not in switch_nodes[node_id]["ports"]:
            switch_nodes[node_id]["ports"].append(link["port_id"])

    for link in lldp_links:
        sys_name = link["system_name"] or link["chassis_id"]
        if not sys_name:
            continue
        node_id = f"lldp:{sys_name}"
        if node_id not in switch_nodes:
            switch_nodes[node_id] = {
                "id": node_id, "ip": link["mgmt_ip"], "mac": link["chassis_id"],
                "label": sys_name, "hostname": sys_name, "netbios": "",
                "vendor": "Unknown", "type": "switch",
                "platform": "", "protocols": [], "packets": 0,
                "vlan": None, "is_gateway": False,
                "ports": [], "level": 1,
            }
        if link["port_id"] not in switch_nodes[node_id]["ports"]:
            switch_nodes[node_id]["ports"].append(link["port_id"])

    # ── 6. Build host nodes ────────────────────────────────────────────────────
    all_ips = (
        set(ip_to_mac)
        | set(ip_pkt_count)
        | {pkt.get("src_ip", "") for pkt in packets}
        | {pkt.get("dst_ip", "") for pkt in packets}
    )
    all_ips = {
        ip for ip in all_ips
        if ip and _is_private(ip)
        and not ip.endswith(".0")       # skip network addresses
        and not ip.endswith(".255")     # skip broadcast addresses
        and ip != "255.255.255.255"
    }

    stp_root_mac = stp_info.get("root_bridge_mac", "")
    cdp_ips = {link["ip"] for link in cdp_links if link["ip"]}

    host_nodes: list[dict] = []
    for ip in all_ips:
        mac    = ip_to_mac.get(ip, "")
        vendor = _lookup_vendor(mac)
        scan_h = scan_by_ip.get(ip, {})

        is_gw       = ip in gateways
        is_stp_root = bool(stp_root_mac and mac and mac == stp_root_mac)
        is_cdp      = ip in cdp_ips
        protocols   = list(ip_protocols[ip].keys())
        node_type   = _classify_type(mac, vendor, is_gw, is_stp_root, is_cdp, protocols)

        hostname = scan_h.get("hostname", "")
        netbios  = scan_h.get("netbios", "")
        label    = netbios or hostname or ip

        ip_vlan = next(
            (vid for vid, hosts in vlan_map.items() if ip in hosts), None
        )

        type_level = {
            "firewall": 0, "router": 0, "switch": 1,
            "server": 2, "plc": 2, "endpoint": 3, "unknown": 3,
        }

        host_nodes.append({
            "id": ip, "ip": ip, "mac": mac, "label": label,
            "hostname": hostname, "netbios": netbios,
            "vendor": vendor, "type": node_type,
            "platform": "", "protocols": protocols[:8],
            "packets": ip_pkt_count.get(ip, 0),
            "vlan": ip_vlan, "is_gateway": is_gw,
            "ports": [], "level": type_level.get(node_type, 3),
        })

    # ── 7. Build edges ─────────────────────────────────────────────────────────
    edges: list[dict] = []
    # Track which node IDs already have at least one edge so we can fill gaps
    connected_targets: set[str] = set()

    # 7a. CDP confirmed edges
    for link in cdp_links:
        if link["ip"] and link["device_id"]:
            edges.append({
                "id": f"cdp-{link['device_id']}-{link['ip']}",
                "source": f"cdp:{link['device_id']}",
                "target": link["ip"],
                "source_port": link["port_id"],
                "target_port": "",
                "edge_type": "cdp",
                "vlan": None,
            })
            connected_targets.add(link["ip"])
            connected_targets.add(f"cdp:{link['device_id']}")

    # 7b. LLDP confirmed edges
    if lldp_links:
        existing_node_ids = (
            {n["id"] for n in host_nodes}
            | set(switch_nodes.keys())
            | {f"lldp:{(l['system_name'] or l['chassis_id'])}" for l in lldp_links}
        )
        for link in lldp_links:
            mgmt = link["mgmt_ip"]
            sys  = link["system_name"] or link["chassis_id"]
            if not sys:
                continue
            node_id = f"lldp:{sys}"
            target = None
            if mgmt and (mgmt in {n["ip"] for n in host_nodes} or mgmt in existing_node_ids):
                target = mgmt
            elif mgmt:
                parts = mgmt.split(".")
                if len(parts) == 4:
                    target = mgmt
                    switch_ips = {v["ip"] for v in switch_nodes.values()}
                    if not any(n["ip"] == mgmt for n in host_nodes) and mgmt not in switch_ips:
                        host_nodes.append({
                            "id": mgmt, "ip": mgmt, "mac": link["chassis_id"],
                            "label": sys, "hostname": sys, "netbios": "",
                            "vendor": _lookup_vendor(link["chassis_id"]),
                            "type": "switch", "platform": "",
                            "protocols": [], "packets": 0,
                            "vlan": None, "is_gateway": False,
                            "ports": [link["port_id"]], "level": 1,
                        })
            if target:
                edges.append({
                    "id": f"lldp-{sys}-{target}",
                    "source": node_id,
                    "target": target,
                    "source_port": link["port_id"],
                    "target_port": link["port_desc"],
                    "edge_type": "lldp",
                    "vlan": None,
                })
                connected_targets.add(target)
                connected_targets.add(node_id)

    # 7c. Inferred edges — always run for nodes not yet connected via CDP/LLDP
    # Group unconnected non-gateway hosts by /24 subnet and link to their gateway
    gateway_list = [
        n["ip"] for n in host_nodes
        if n["is_gateway"] and n["ip"]
    ]
    subnets: dict[str, list[str]] = defaultdict(list)
    for node in host_nodes:
        if node["is_gateway"] or node["id"] in connected_targets:
            continue
        parts = node["ip"].split(".")
        if len(parts) == 4:
            subnets[".".join(parts[:3])].append(node["ip"])

    for subnet, hosts in subnets.items():
        gw = next(
            (g for g in gateway_list if g.startswith(subnet + ".")),
            gateway_list[0] if gateway_list else None,
        )
        if not gw:
            continue
        for host_ip in hosts:
            vid = next(
                (v for v, ips in vlan_map.items() if host_ip in ips), None
            )
            last_octet = host_ip.split(".")[-1]
            edges.append({
                "id": f"inferred-{gw}-{host_ip}",
                "source": gw,
                "target": host_ip,
                "source_port": f"eth0/{last_octet}",
                "target_port": "eth0",
                "edge_type": "inferred",
                "vlan": vid,
            })

    # ── 8. Assemble result ────────────────────────────────────────────────────
    all_nodes = list(switch_nodes.values()) + host_nodes

    return {
        "nodes": all_nodes,
        "edges": edges,
        "vlans": list(vlan_map),
        "gateways": list(gateways),
        "has_cdp": bool(cdp_links),
        "has_lldp": bool(lldp_links),
        "has_stp": bool(stp_info),
        "confidence": (
            "high" if (cdp_links or lldp_links)
            else "medium" if gateways
            else "low"
        ),
        "total_devices": len(all_nodes),
    }


# ── Tool runners ──────────────────────────────────────────────────────────────

async def run_topology_map(args: str = "") -> str:
    """Build topology from current capture (CDP/LLDP/ARP/DHCP/STP)."""
    from api.routes import get_packets, get_current_capture_file
    packets = get_packets()
    pcap    = get_current_capture_file()
    topo    = build_topology(packets, pcap or None)
    return json.dumps(topo)


async def run_topology_scan(args: str = "") -> str:
    """Active scan + topology build. Args: [CIDR e.g. 192.168.1.0/24]"""
    from api.routes import get_packets, get_current_capture_file
    from capture.subnet_scanner import scan_subnet

    packets = get_packets()
    pcap    = get_current_capture_file()
    cidr    = args.strip()

    if not cidr:
        # Auto-detect subnet from captured traffic
        ip_counter: Counter = Counter()
        for pkt in packets:
            for field in ("src_ip", "dst_ip"):
                ip = pkt.get(field, "")
                if ip and _is_private(ip):
                    parts = ip.split(".")
                    if len(parts) == 4:
                        ip_counter[".".join(parts[:3])] += 1
        if ip_counter:
            top = ip_counter.most_common(1)[0][0]
            cidr = f"{top}.0/24"
        else:
            return json.dumps({"error": "No CIDR specified and no private-IP traffic found."})

    try:
        scan_results_raw = await asyncio.wait_for(
            scan_subnet(cidr, max_concurrent=64, timeout=1.0),
            timeout=30.0,
        )
        scan_dicts = [h.to_dict() for h in scan_results_raw if h.alive]
    except asyncio.TimeoutError:
        scan_dicts = []
    except Exception:
        scan_dicts = []

    topo = build_topology(packets, pcap or None, scan_dicts)
    topo["scan_cidr"] = cidr
    topo["scan_hosts_found"] = len(scan_dicts)
    return json.dumps(topo)


# ── Registration ──────────────────────────────────────────────────────────────

_TOPO_KW = {
    "topology", "topo", "network map", "device map", "diagram",
    "switch port", "firewall port", "physical topology", "layer 2",
    "l2 topology", "switch diagram", "port mapping", "cdp", "lldp",
    "arp map", "network diagram", "draw network", "connected to",
    "plugged into", "which port", "topology scan",
}

register(ToolDef(
    name="topology_map",
    category="topology",
    description=(
        "build network topology (devices, switches, firewalls, port numbers) "
        "from pcap — uses CDP/LLDP/ARP/DHCP/STP for discovery"
    ),
    args_spec="",
    runner=run_topology_map,
    safety="read",
    keywords=_TOPO_KW,
    needs_packets=True,
))

register(ToolDef(
    name="topology_scan",
    category="topology",
    description=(
        "active subnet scan + topology build — discovers all live hosts and "
        "maps them to switches/firewalls with port numbers. Args: [CIDR]"
    ),
    args_spec="[cidr]",
    runner=run_topology_scan,
    safety="read",
    keywords=_TOPO_KW | {"scan", "discover", "alive", "host discovery", "nmap"},
))
