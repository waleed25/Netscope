"""
Normalize raw packets from tshark NDJSON (live), pyshark, and scapy into
a clean, LLM-friendly dict format via a unified parse_packet() entry point.

ICS/SCADA protocols supported:
  - Modbus TCP  (port 502)  — function codes, unit IDs, coil/register addresses
  - DNP3        (port 20000) — application layer control codes, object groups
  - OPC-UA      (port 4840/4843) — service type, security mode, endpoint URL
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import time
from typing import Any, Union


# ── ICS port constants ────────────────────────────────────────────────────────

_MODBUS_PORTS = {"502"}
_DNP3_PORTS = {"20000", "19999", "20001"}
_OPCUA_PORTS = {"4840", "4843", "4841"}

# Modbus function code → human label
_MODBUS_FC: dict[str, str] = {
    "1": "Read Coils",
    "2": "Read Discrete Inputs",
    "3": "Read Holding Registers",
    "4": "Read Input Registers",
    "5": "Write Single Coil",
    "6": "Write Single Register",
    "7": "Read Exception Status",
    "8": "Diagnostics",
    "11": "Get Comm Event Counter",
    "12": "Get Comm Event Log",
    "15": "Write Multiple Coils",
    "16": "Write Multiple Registers",
    "17": "Report Server ID",
    "20": "Read File Record",
    "21": "Write File Record",
    "22": "Mask Write Register",
    "23": "Read/Write Multiple Registers",
    "24": "Read FIFO Queue",
    "43": "Encapsulated Interface Transport",
    "129": "Exception: Read Coils",
    "130": "Exception: Read Discrete Inputs",
    "131": "Exception: Read Holding Registers",
    "132": "Exception: Read Input Registers",
    "133": "Exception: Write Single Coil",
    "134": "Exception: Write Single Register",
    "143": "Exception: Write Multiple Coils",
    "144": "Exception: Write Multiple Registers",
}

_DNP3_FC: dict[str, str] = {
    "0": "Confirm", "1": "Read", "2": "Write", "3": "Select", "4": "Operate",
    "5": "Direct Operate", "6": "Direct Operate No Ack", "7": "Freeze",
    "8": "Freeze No Ack", "9": "Freeze Clear", "10": "Freeze Clear No Ack",
    "11": "Freeze at Time", "12": "Freeze at Time No Ack", "13": "Cold Restart",
    "14": "Warm Restart", "15": "Initialize Data", "16": "Initialize Application",
    "17": "Start Application", "18": "Stop Application", "19": "Save Configuration",
    "20": "Enable Unsolicited Messages", "21": "Disable Unsolicited Messages",
    "22": "Assign Class", "23": "Delay Measurement", "24": "Record Current Time",
    "25": "Open File", "26": "Close File", "27": "Delete File",
    "28": "Get File Info", "29": "Authenticate File", "30": "Abort File",
    "33": "Response", "34": "Unsolicited Response", "35": "Authenticate Request",
    "36": "Authenticate Error",
}

_OPCUA_MSG_TYPE: dict[str, str] = {
    "HEL": "Hello", "ACK": "Acknowledge", "ERR": "Error",
    "MSG": "Message", "OPN": "OpenSecureChannel", "CLO": "CloseSecureChannel",
}

_OPCUA_SERVICE: dict[str, str] = {
    "428": "CreateSession", "431": "ActivateSession", "473": "CloseSession",
    "629": "Browse", "633": "BrowseNext", "677": "Read", "673": "Write",
    "787": "CreateSubscription", "803": "Publish", "841": "CreateMonitoredItems",
    "771": "DeleteSubscription", "845": "DeleteMonitoredItems",
    "751": "ModifySubscription", "855": "ModifyMonitoredItems",
    "813": "Republish", "717": "TranslateBrowsePathsToNodeIds",
    "863": "SetTriggeringRequest",
}

PROTOCOL_COLORS = {
    "HTTP": "blue", "HTTPS": "blue", "TLS": "cyan", "SSL": "cyan",
    "DNS": "purple", "TCP": "green", "UDP": "yellow", "ICMP": "orange",
    "ARP": "pink", "MODBUS": "red", "DNP3": "amber", "OPC-UA": "violet",
    "OTHER": "gray",
}


class ProtocolHandler(ABC):
    """Abstract base class for packet parsing handlers."""

    @abstractmethod
    def parse(self, packet: Any, index: int) -> dict:
        """Parse a packet into a normalized dict."""
        pass

    @abstractmethod
    def can_parse(self, packet: Any) -> bool:
        """Check if this handler can parse the given packet."""
        pass


class TsharkJsonHandler(ProtocolHandler):
    """Handler for tshark NDJSON (tshark -T ek) output."""

    def can_parse(self, packet: Any) -> bool:
        return isinstance(packet, dict) and "layers" in packet

    def parse(self, packet: dict, index: int) -> dict:
        layers_raw = packet.get("layers", {})

        def f(key: str) -> str:
            val = layers_raw.get(key, "")
            if isinstance(val, list):
                return str(val[0]) if val else ""
            return str(val) if val is not None else ""

        protocols_str = f("frame_protocols")
        protocols = [p.upper() for p in protocols_str.split(":")] if protocols_str else []

        src_ip = f("ip_src") or f("ipv6_src")
        dst_ip = f("ip_dst") or f("ipv6_dst")
        src_port = f("tcp_srcport") or f("udp_srcport")
        dst_port = f("tcp_dstport") or f("udp_dstport")

        details: dict = {}

        tcp_flags = f("tcp_flags")
        if tcp_flags:
            details["tcp_flags"] = tcp_flags

        dns_query = f("dns_qry_name")
        dns_resp = f("dns_resp_name")
        if dns_query:
            details["dns_query"] = dns_query
        if dns_resp:
            details["dns_response"] = dns_resp

        http_method = f("http_request_method")
        http_uri = f("http_request_uri")
        http_host = f("http_host")
        http_code = f("http_response_code")
        if http_method:
            details["http_method"] = http_method
        if http_uri:
            details["http_uri"] = http_uri
        if http_host:
            details["http_host"] = http_host
        if http_code:
            details["http_response_code"] = http_code

        tls_sni = f("tls_handshake_extensions_server_name")
        if tls_sni:
            details["tls_sni"] = tls_sni

        arp_src = f("arp_src_proto_ipv4")
        arp_dst = f("arp_dst_proto_ipv4")
        arp_op = f("arp_opcode")
        if arp_src:
            src_ip = arp_src
        if arp_dst:
            dst_ip = arp_dst

        icmp_type = f("icmp_type")
        if icmp_type:
            details["icmp_type"] = icmp_type

        modbus_fc = f("mbtcp_pdu_type") or f("modbus_func_code") or f("mbtcp_func_code") or f("modbus_funccode")
        modbus_unit = f("mbtcp_unit_id") or f("modbus_unit_id")
        modbus_ref = f("modbus_reference_num") or f("mbtcp_regnum") or f("modbus_regnum")
        modbus_cnt = f("modbus_word_cnt") or f("modbus_bytecnt")
        if modbus_fc or src_port in _MODBUS_PORTS or dst_port in _MODBUS_PORTS:
            fc_int = modbus_fc.split("(")[0].strip() if modbus_fc else ""
            fc_label = _MODBUS_FC.get(fc_int, f"FC={fc_int}" if fc_int else "")
            details["modbus_fc"] = fc_int
            details["modbus_fc_name"] = fc_label
            if modbus_unit:
                details["modbus_unit_id"] = modbus_unit
            if modbus_ref:
                details["modbus_ref"] = modbus_ref
            if modbus_cnt:
                details["modbus_count"] = modbus_cnt

        dnp3_fc = f("dnp3.al.func") or f("dnp3_al_func")
        dnp3_ctl = f("dnp3.ctl") or f("dnp3_ctl")
        dnp3_obj = f("dnp3.al.obj") or f("dnp3_al_obj")
        dnp3_src = f("dnp3.src") or f("dnp3_src")
        dnp3_dst = f("dnp3.dst") or f("dnp3_dst")
        if dnp3_fc or src_port in _DNP3_PORTS or dst_port in _DNP3_PORTS:
            fc_int = dnp3_fc.split("(")[0].strip() if dnp3_fc else ""
            fc_label = _DNP3_FC.get(fc_int, f"FC={fc_int}" if fc_int else "")
            details["dnp3_fc"] = fc_int
            details["dnp3_fc_name"] = fc_label
            if dnp3_src:
                details["dnp3_src"] = dnp3_src
            if dnp3_dst:
                details["dnp3_dst"] = dnp3_dst
            if dnp3_obj:
                details["dnp3_obj"] = dnp3_obj
            if dnp3_ctl:
                details["dnp3_ctl"] = dnp3_ctl

        opcua_msg = f("opcua.transport.type") or f("opcua_transport_type")
        opcua_svc = f("opcua.servicenodeid.numeric") or f("opcua_servicenodeid_numeric")
        opcua_ep = f("opcua.transport.endpoint") or f("opcua_transport_endpoint")
        opcua_sec = f("opcua.SecurityPolicyUri") or f("opcua_SecurityPolicyUri")
        if opcua_msg or opcua_svc or src_port in _OPCUA_PORTS or dst_port in _OPCUA_PORTS:
            msg_label = _OPCUA_MSG_TYPE.get(opcua_msg, opcua_msg)
            svc_label = _OPCUA_SERVICE.get(opcua_svc, f"Service={opcua_svc}" if opcua_svc else "")
            details["opcua_msg_type"] = msg_label
            details["opcua_service"] = svc_label
            if opcua_ep:
                details["opcua_endpoint"] = opcua_ep
            if opcua_sec:
                details["opcua_security"] = opcua_sec.split("#")[-1] if "#" in opcua_sec else opcua_sec

        info = self._build_info(details, http_method, http_code, tls_sni, dns_query, dns_resp, arp_src, arp_dst, arp_op, icmp_type, src_ip, dst_ip, src_port, dst_port)

        try:
            ts = float(f("frame_time_epoch"))
        except (ValueError, TypeError):
            ts = time.time()

        try:
            length = int(f("frame_len"))
        except (ValueError, TypeError):
            length = 0

        return {
            "id": index,
            "timestamp": ts,
            "layers": protocols,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": src_port,
            "dst_port": dst_port,
            "protocol": _detect_protocol_from_list(protocols, details, src_port, dst_port),
            "length": length,
            "info": info,
            "color": PROTOCOL_COLORS.get(_detect_protocol_from_list(protocols, details, src_port, dst_port), "gray"),
            "details": details,
        }

    def _build_info(self, details: dict, http_method: str, http_code: str, tls_sni: str, dns_query: str, dns_resp: str, arp_src: str, arp_dst: str, arp_op: str, icmp_type: str, src_ip: str, dst_ip: str, src_port: str, dst_port: str) -> str:
        if details.get("modbus_fc"):
            fc_name = details.get("modbus_fc_name") or f"FC={details['modbus_fc']}"
            unit = f" unit={details['modbus_unit_id']}" if details.get("modbus_unit_id") else ""
            ref = f" ref={details['modbus_ref']}" if details.get("modbus_ref") else ""
            return f"Modbus {fc_name}{unit}{ref}"
        elif details.get("dnp3_fc"):
            fc_name = details.get("dnp3_fc_name") or f"FC={details['dnp3_fc']}"
            d_src = f" src={details['dnp3_src']}" if details.get("dnp3_src") else ""
            d_dst = f" dst={details['dnp3_dst']}" if details.get("dnp3_dst") else ""
            return f"DNP3 {fc_name}{d_src}{d_dst}"
        elif details.get("opcua_msg_type"):
            svc = details.get("opcua_service") or ""
            return f"OPC-UA {details['opcua_msg_type']}" + (f" / {svc}" if svc else "")
        elif http_method:
            return f"HTTP {http_method} {details.get('http_host', '')}{details.get('http_uri', '')}"
        elif http_code:
            return f"HTTP {http_code}"
        elif tls_sni:
            return f"TLS SNI: {tls_sni}"
        elif dns_query:
            return f"DNS Query: {dns_query}"
        elif dns_resp:
            return f"DNS Response: {dns_resp}"
        elif arp_src:
            return f"ARP op={arp_op} {arp_src} → {arp_dst}"
        elif icmp_type:
            return f"ICMP type={icmp_type} {src_ip} → {dst_ip}"
        else:
            return f"{src_ip}:{src_port} → {dst_ip}:{dst_port}"


class PysharkHandler(ProtocolHandler):
    """Handler for live pyshark packets."""

    def can_parse(self, packet: Any) -> bool:
        return hasattr(packet, "layers") and hasattr(packet, "sniff_timestamp")

    def parse(self, packet: Any, index: int) -> dict:
        try:
            layers = [layer.layer_name.upper() for layer in packet.layers]
        except Exception:
            layers = []

        result: dict = {
            "id": index,
            "timestamp": float(packet.sniff_timestamp) if hasattr(packet, "sniff_timestamp") else time.time(),
            "layers": layers,
            "src_ip": "",
            "dst_ip": "",
            "src_port": "",
            "dst_port": "",
            "protocol": "",
            "length": 0,
            "info": "",
            "details": {},
        }

        if hasattr(packet, "ip"):
            result["src_ip"] = self._safe(packet.ip, "src")
            result["dst_ip"] = self._safe(packet.ip, "dst")

        if hasattr(packet, "ipv6") and not result["src_ip"]:
            result["src_ip"] = self._safe(packet.ipv6, "src")
            result["dst_ip"] = self._safe(packet.ipv6, "dst")

        if hasattr(packet, "tcp"):
            result["src_port"] = self._safe(packet.tcp, "srcport")
            result["dst_port"] = self._safe(packet.tcp, "dstport")
            result["details"]["tcp_flags"] = self._safe(packet.tcp, "flags")
            result["details"]["tcp_seq"] = self._safe(packet.tcp, "seq")

        if hasattr(packet, "udp"):
            result["src_port"] = self._safe(packet.udp, "srcport")
            result["dst_port"] = self._safe(packet.udp, "dstport")

        if hasattr(packet, "dns"):
            qry_name = self._safe(packet.dns, "qry_name")
            resp_name = self._safe(packet.dns, "resp_name")
            result["details"]["dns_query"] = qry_name
            result["details"]["dns_response"] = resp_name
            result["info"] = f"DNS {'Query' if qry_name else 'Response'}: {qry_name or resp_name}"

        if hasattr(packet, "http"):
            method = self._safe(packet.http, "request_method")
            uri = self._safe(packet.http, "request_uri")
            host = self._safe(packet.http, "host")
            resp_code = self._safe(packet.http, "response_code")
            result["details"]["http_method"] = method
            result["details"]["http_uri"] = uri
            result["details"]["http_host"] = host
            result["details"]["http_response_code"] = resp_code
            if method:
                result["info"] = f"HTTP {method} {host}{uri}"
            elif resp_code:
                result["info"] = f"HTTP {resp_code}"

        if hasattr(packet, "tls"):
            sni = self._safe(packet.tls, "handshake_extensions_server_name")
            result["details"]["tls_sni"] = sni
            if sni:
                result["info"] = f"TLS SNI: {sni}"

        if hasattr(packet, "arp"):
            result["src_ip"] = self._safe(packet.arp, "src_proto_ipv4")
            result["dst_ip"] = self._safe(packet.arp, "dst_proto_ipv4")
            result["info"] = f"ARP {self._safe(packet.arp, 'opcode')}"

        try:
            result["length"] = int(packet.length)
        except Exception:
            pass

        result["protocol"] = detect_protocol(result)
        result["color"] = PROTOCOL_COLORS.get(result["protocol"], "gray")

        if not result["info"]:
            result["info"] = f"{result['src_ip']}:{result['src_port']} → {result['dst_ip']}:{result['dst_port']}"

        return result

    def _safe(self, obj: Any, *attrs: str, default: str = "") -> str:
        for attr in attrs:
            try:
                obj = getattr(obj, attr)
            except AttributeError:
                return default
        return str(obj) if obj is not None else default


class ScapyHandler(ProtocolHandler):
    """Handler for scapy packets from pcap files."""

    def can_parse(self, packet: Any) -> bool:
        return hasattr(packet, "time") and hasattr(packet, "layers")

    def parse(self, packet: Any, index: int) -> dict:
        from scapy.layers.inet import IP, TCP, UDP, ICMP
        from scapy.layers.inet6 import IPv6
        from scapy.layers.l2 import ARP, Ether
        from scapy.layers.dns import DNS

        layers = []
        current = packet
        while current:
            layers.append(type(current).__name__.upper())
            current = current.payload if current.payload and current.payload.__class__.__name__ != "NoPayload" else None

        result: dict = {
            "id": index,
            "timestamp": float(packet.time),
            "layers": layers,
            "src_ip": "",
            "dst_ip": "",
            "src_port": "",
            "dst_port": "",
            "protocol": "",
            "length": len(packet),
            "info": "",
            "details": {},
        }

        if packet.haslayer(IP):
            result["src_ip"] = packet[IP].src
            result["dst_ip"] = packet[IP].dst
        elif packet.haslayer(IPv6):
            result["src_ip"] = packet[IPv6].src
            result["dst_ip"] = packet[IPv6].dst

        if packet.haslayer(TCP):
            result["src_port"] = str(packet[TCP].sport)
            result["dst_port"] = str(packet[TCP].dport)
            result["details"]["tcp_flags"] = str(packet[TCP].flags)
        elif packet.haslayer(UDP):
            result["src_port"] = str(packet[UDP].sport)
            result["dst_port"] = str(packet[UDP].dport)

        if packet.haslayer(DNS):
            dns = packet[DNS]
            qname = dns.qd.qname.decode("utf-8", errors="replace") if dns.qd else ""
            result["details"]["dns_query"] = qname
            result["info"] = f"DNS Query: {qname}"

        if packet.haslayer(ARP):
            result["src_ip"] = packet[ARP].psrc
            result["dst_ip"] = packet[ARP].pdst
            result["info"] = f"ARP op={packet[ARP].op}"

        try:
            from scapy.layers.http import HTTP, HTTPRequest, HTTPResponse
            if packet.haslayer(HTTPRequest):
                method = packet[HTTPRequest].Method.decode("utf-8", errors="replace") if packet[HTTPRequest].Method else ""
                path = packet[HTTPRequest].Path.decode("utf-8", errors="replace") if packet[HTTPRequest].Path else ""
                host = packet[HTTPRequest].Host.decode("utf-8", errors="replace") if packet[HTTPRequest].Host else ""
                result["details"]["http_method"] = method
                result["details"]["http_uri"] = path
                result["details"]["http_host"] = host
                result["info"] = f"HTTP {method} {host}{path}"

            if packet.haslayer(HTTPResponse):
                status = packet[HTTPResponse].Status_Code.decode("utf-8", errors="replace") if packet[HTTPResponse].Status_Code else ""
                result["details"]["http_response_code"] = status
                result["info"] = f"HTTP Response {status}"
        except ImportError:
            pass

        if packet.haslayer(ICMP):
            result["info"] = f"ICMP type={packet[ICMP].type}"

        result["protocol"] = detect_protocol(result)
        result["color"] = PROTOCOL_COLORS.get(result["protocol"], "gray")

        if not result["info"]:
            result["info"] = f"{result['src_ip']}:{result['src_port']} → {result['dst_ip']}:{result['dst_port']}"

        return result


_HANDLERS: list[ProtocolHandler] = [
    TsharkJsonHandler(),
    PysharkHandler(),
    ScapyHandler(),
]


def parse_packet(packet: Any, index: int = 0) -> dict:
    """
    Unified entry point that auto-detects packet type and parses accordingly.

    Args:
        packet: A packet in one of these formats:
            - tshark NDJSON dict (from tshark -T ek)
            - pyshark live packet object
            - scapy packet object (from pcap file)
        index: Packet sequence number

    Returns:
        Normalized dict with keys: id, timestamp, layers, src_ip, dst_ip,
        src_port, dst_port, protocol, length, info, color, details
    """
    for handler in _HANDLERS:
        if handler.can_parse(packet):
            return handler.parse(packet, index)

    raise ValueError(f"Unknown packet type: {type(packet)}")


def _detect_protocol_from_list(protocols: list, details: dict, sport: str, dport: str) -> str:
    upper = [p.upper() for p in protocols]
    if "MBTCP" in upper or "MODBUS" in upper or details.get("modbus_fc") or sport in _MODBUS_PORTS or dport in _MODBUS_PORTS:
        return "MODBUS"
    if "DNP3" in upper or details.get("dnp3_fc") or sport in _DNP3_PORTS or dport in _DNP3_PORTS:
        return "DNP3"
    if "OPCUA" in upper or details.get("opcua_msg_type") or sport in _OPCUA_PORTS or dport in _OPCUA_PORTS:
        return "OPC-UA"
    if details.get("http_method") or details.get("http_response_code"):
        return "HTTP"
    if details.get("tls_sni") or "TLS" in upper or "SSL" in upper:
        return "TLS"
    if details.get("dns_query") or details.get("dns_response") or "DNS" in upper:
        return "DNS"
    if "ICMP" in upper:
        return "ICMP"
    if "ARP" in upper:
        return "ARP"
    if sport in ("80", "8080", "8000") or dport in ("80", "8080", "8000"):
        return "HTTP"
    if sport in ("443", "8443") or dport in ("443", "8443"):
        return "TLS"
    if sport == "53" or dport == "53":
        return "DNS"
    if "TCP" in upper:
        return "TCP"
    if "UDP" in upper:
        return "UDP"
    return "OTHER"


def detect_protocol(pkt_dict: dict) -> str:
    layers = pkt_dict.get("layers", [])
    layers_upper = [l.upper() for l in layers]
    details = pkt_dict.get("details", {})
    sport = pkt_dict.get("src_port", "")
    dport = pkt_dict.get("dst_port", "")
    if "MBTCP" in layers_upper or "MODBUS" in layers_upper or details.get("modbus_fc") or sport in _MODBUS_PORTS or dport in _MODBUS_PORTS:
        return "MODBUS"
    if "DNP3" in layers_upper or details.get("dnp3_fc") or sport in _DNP3_PORTS or dport in _DNP3_PORTS:
        return "DNP3"
    if "OPCUA" in layers_upper or details.get("opcua_msg_type") or sport in _OPCUA_PORTS or dport in _OPCUA_PORTS:
        return "OPC-UA"
    for proto in ["HTTP", "TLS", "SSL", "DNS", "ICMP", "UDP", "TCP", "ARP"]:
        if proto in layers_upper:
            if proto == "TLS":
                return "HTTPS"
            return proto
    return "OTHER"


parse_tshark_json = lambda data, index: TsharkJsonHandler().parse(data, index)
parse_pyshark_packet = lambda pkt, index: PysharkHandler().parse(pkt, index)
parse_scapy_packet = lambda pkt, index: ScapyHandler().parse(pkt, index)
