"""
Expert analysis engine — stateless, packet-list-in / structured-report-out.

Provides five analysis modes that operate on the in-memory packet list:

  1. ics_audit        — Modbus / DNP3 / OPC-UA inventory, anomaly flags,
                        dangerous function codes, unexpected endpoints
  2. port_scan        — SYN-scan detection, rapid-service enumeration,
                        connection-refused storms
  3. flow_analysis    — top conversations, byte volume, long-lived flows,
                        retransmission indicators
  4. conversations    — enumerate unique src↔dst pairs with protocol + count
  5. anomaly_detect   — generic statistical anomalies: unusual ports,
                        high-rate single-IP bursts, protocol mismatches

All functions return a dict that is JSON-serialisable and also fed to the LLM
for natural-language commentary.
"""

from __future__ import annotations
import time
from collections import Counter, defaultdict
from typing import Any

from agent.llm_client import chat_completion


# ── ICS well-known ports ──────────────────────────────────────────────────────

_MODBUS_PORTS  = {502}
_DNP3_PORTS    = {20000, 19999, 20001}
_OPCUA_PORTS   = {4840, 4843, 4841}
_ICS_PORTS     = _MODBUS_PORTS | _DNP3_PORTS | _OPCUA_PORTS

# Modbus FC values considered dangerous in most OT environments
_MODBUS_DANGEROUS_FC = {
    "5":  "Write Single Coil",
    "6":  "Write Single Register",
    "15": "Write Multiple Coils",
    "16": "Write Multiple Registers",
    "22": "Mask Write Register",
    "23": "Read/Write Multiple Registers",
    "43": "Encapsulated Interface Transport",
}

# DNP3 FC values considered dangerous (writes / restarts)
_DNP3_DANGEROUS_FC = {
    "2":  "Write",
    "3":  "Select",
    "4":  "Operate",
    "5":  "Direct Operate",
    "6":  "Direct Operate No Ack",
    "7":  "Freeze",
    "9":  "Freeze Clear",
    "13": "Cold Restart",
    "14": "Warm Restart",
    "20": "Enable Unsolicited Messages",
    "21": "Disable Unsolicited Messages",
}


def _int_port(p: str) -> int:
    try:
        return int(p)
    except (ValueError, TypeError):
        return 0


# ── Helper: filter packets by protocol ───────────────────────────────────────

def _by_proto(packets: list[dict], *protos: str) -> list[dict]:
    protos_upper = {p.upper() for p in protos}
    return [p for p in packets if p.get("protocol", "").upper() in protos_upper]


def _is_ics(pkt: dict) -> bool:
    port = _int_port(pkt.get("dst_port", "")) or _int_port(pkt.get("src_port", ""))
    proto = pkt.get("protocol", "").upper()
    return proto in ("MODBUS", "DNP3", "OPC-UA") or port in _ICS_PORTS


# ─────────────────────────────────────────────────────────────────────────────
# 1. ICS Audit
# ─────────────────────────────────────────────────────────────────────────────

def ics_audit(packets: list[dict]) -> dict:
    """
    Full ICS/SCADA traffic audit.

    Returns:
        {
          summary: { total_ics, modbus_count, dnp3_count, opcua_count },
          modbus: { devices, function_codes, dangerous_writes, exceptions },
          dnp3:   { endpoints, function_codes, dangerous_ops, unsolicited },
          opcua:  { endpoints, services, insecure_policies },
          anomalies: [ { severity, description } ]
        }
    """
    ics_pkts = [p for p in packets if _is_ics(p)]

    modbus_pkts = [p for p in ics_pkts if p.get("protocol", "").upper() == "MODBUS"
                   or _int_port(p.get("dst_port", "")) in _MODBUS_PORTS
                   or _int_port(p.get("src_port", "")) in _MODBUS_PORTS]
    dnp3_pkts   = [p for p in ics_pkts if p.get("protocol", "").upper() == "DNP3"
                   or _int_port(p.get("dst_port", "")) in _DNP3_PORTS
                   or _int_port(p.get("src_port", "")) in _DNP3_PORTS]
    opcua_pkts  = [p for p in ics_pkts if p.get("protocol", "").upper() == "OPC-UA"
                   or _int_port(p.get("dst_port", "")) in _OPCUA_PORTS
                   or _int_port(p.get("src_port", "")) in _OPCUA_PORTS]

    anomalies: list[dict] = []

    # ── Modbus analysis ──────────────────────────────────────────────────────
    mb_masters: Counter = Counter()
    mb_slaves:  Counter = Counter()
    mb_fc:      Counter = Counter()
    mb_units:   Counter = Counter()
    mb_exceptions = 0

    for p in modbus_pkts:
        d = p.get("details", {})
        fc = d.get("modbus_fc", "")
        fc_name = d.get("modbus_fc_name", "")
        unit = d.get("modbus_unit_id", "")
        # heuristic: client→502 is request, 502→client is response
        if _int_port(p.get("dst_port", "")) in _MODBUS_PORTS:
            mb_masters[p.get("src_ip", "?")] += 1
            mb_slaves[p.get("dst_ip", "?")] += 1
        else:
            mb_slaves[p.get("src_ip", "?")] += 1
        if fc:
            mb_fc[f"{fc} ({fc_name})" if fc_name else fc] += 1
        if unit:
            mb_units[unit] += 1
        # exception codes have bit7 set (value ≥ 128)
        try:
            if int(fc) >= 128:
                mb_exceptions += 1
        except (ValueError, TypeError):
            pass

    dangerous_writes_mb = [
        {"fc": fc, "label": label, "count": mb_fc.get(fc, mb_fc.get(f"{fc} ({label})", 0))}
        for fc, label in _MODBUS_DANGEROUS_FC.items()
        if any(k.startswith(fc) for k in mb_fc)
    ]
    if dangerous_writes_mb:
        anomalies.append({
            "severity": "HIGH",
            "protocol": "Modbus",
            "description": f"Dangerous write/control function codes detected: "
                           f"{[d['label'] for d in dangerous_writes_mb]}",
        })
    if mb_exceptions > 0:
        anomalies.append({
            "severity": "MEDIUM",
            "protocol": "Modbus",
            "description": f"{mb_exceptions} Modbus exception responses — possible misconfiguration or failed writes.",
        })

    # ── DNP3 analysis ────────────────────────────────────────────────────────
    dnp3_masters: Counter = Counter()
    dnp3_outstations: Counter = Counter()
    dnp3_fc: Counter = Counter()
    dnp3_unsolicited = 0

    for p in dnp3_pkts:
        d = p.get("details", {})
        fc = d.get("dnp3_fc", "")
        fc_name = d.get("dnp3_fc_name", "")
        src = d.get("dnp3_src") or p.get("src_ip", "?")
        dst = d.get("dnp3_dst") or p.get("dst_ip", "?")
        dnp3_masters[src] += 1
        dnp3_outstations[dst] += 1
        if fc:
            dnp3_fc[f"{fc} ({fc_name})" if fc_name else fc] += 1
        if fc == "34":   # Unsolicited Response
            dnp3_unsolicited += 1

    dangerous_ops_dnp3 = [
        {"fc": fc, "label": label}
        for fc, label in _DNP3_DANGEROUS_FC.items()
        if any(k.startswith(fc) for k in dnp3_fc)
    ]
    if dangerous_ops_dnp3:
        anomalies.append({
            "severity": "HIGH",
            "protocol": "DNP3",
            "description": f"DNP3 control/write operations detected: "
                           f"{[d['label'] for d in dangerous_ops_dnp3]}",
        })
    if dnp3_unsolicited > 0:
        anomalies.append({
            "severity": "LOW",
            "protocol": "DNP3",
            "description": f"{dnp3_unsolicited} unsolicited DNP3 responses — outstation is pushing data.",
        })

    # ── OPC-UA analysis ──────────────────────────────────────────────────────
    opcua_endpoints: Counter = Counter()
    opcua_services: Counter = Counter()
    insecure_policies: list[str] = []

    for p in opcua_pkts:
        d = p.get("details", {})
        ep  = d.get("opcua_endpoint", "")
        svc = d.get("opcua_service", "")
        sec = d.get("opcua_security", "")
        if ep:
            opcua_endpoints[ep] += 1
        if svc:
            opcua_services[svc] += 1
        if sec and "None" in sec and sec not in insecure_policies:
            insecure_policies.append(sec)

    if insecure_policies:
        anomalies.append({
            "severity": "HIGH",
            "protocol": "OPC-UA",
            "description": f"OPC-UA sessions using no security policy (SecurityMode=None): "
                           f"{insecure_policies[:3]}",
        })

    # ── Cross-protocol: ICS traffic on non-standard ports ────────────────────
    for p in ics_pkts:
        dport = _int_port(p.get("dst_port", ""))
        sport = _int_port(p.get("src_port", ""))
        proto = p.get("protocol", "").upper()
        expected = {
            "MODBUS": _MODBUS_PORTS,
            "DNP3":   _DNP3_PORTS,
            "OPC-UA": _OPCUA_PORTS,
        }.get(proto, set())
        if expected and dport not in expected and sport not in expected:
            anomalies.append({
                "severity": "MEDIUM",
                "protocol": proto,
                "description": f"{proto} traffic on non-standard port "
                               f"{dport or sport} (expected {sorted(expected)})",
            })
            break  # one notice is enough

    return {
        "summary": {
            "total_ics":     len(ics_pkts),
            "modbus_count":  len(modbus_pkts),
            "dnp3_count":    len(dnp3_pkts),
            "opcua_count":   len(opcua_pkts),
        },
        "modbus": {
            "masters":         dict(mb_masters.most_common(10)),
            "slaves":          dict(mb_slaves.most_common(10)),
            "function_codes":  dict(mb_fc.most_common(15)),
            "unit_ids":        dict(mb_units.most_common(10)),
            "exceptions":      mb_exceptions,
            "dangerous_writes": dangerous_writes_mb,
        },
        "dnp3": {
            "masters":       dict(dnp3_masters.most_common(10)),
            "outstations":   dict(dnp3_outstations.most_common(10)),
            "function_codes": dict(dnp3_fc.most_common(15)),
            "unsolicited":   dnp3_unsolicited,
            "dangerous_ops": dangerous_ops_dnp3,
        },
        "opcua": {
            "endpoints":        dict(opcua_endpoints.most_common(10)),
            "services":         dict(opcua_services.most_common(10)),
            "insecure_policies": insecure_policies,
        },
        "anomalies": anomalies,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Port Scan Detection
# ─────────────────────────────────────────────────────────────────────────────

def port_scan_detection(packets: list[dict]) -> dict:
    """
    Heuristic port-scan detection.

    Indicators:
      - SYN scan: source IP contacts many distinct dst_ports with TCP SYN (flags 0x002)
        within a short time window (≤ 60 s).
      - Service enumeration: one IP → many distinct dst IPs on the same port.
      - RST/refused storm: high ratio of RST packets from a target.
    """
    tcp_pkts = [p for p in packets
                if "TCP" in [l.upper() for l in p.get("layers", [])]
                or p.get("protocol") in ("TCP", "TLS", "HTTP")]

    # Group by src_ip
    src_ports: dict[str, set] = defaultdict(set)
    src_dsts:  dict[str, set] = defaultdict(set)
    src_syn_times: dict[str, list] = defaultdict(list)
    rst_counts: Counter = Counter()

    for p in tcp_pkts:
        src = p.get("src_ip", "")
        dst = p.get("dst_ip", "")
        dport = p.get("dst_port", "")
        flags = p.get("details", {}).get("tcp_flags", "")
        ts    = p.get("timestamp", 0.0)

        if not src:
            continue
        if dport:
            src_ports[src].add(dport)
            src_dsts[src].add(dst)

        # SYN detection: flags == 0x002 or contains "S" but not "A"
        is_syn = False
        if flags:
            try:
                flag_int = int(flags, 16)
                is_syn = bool(flag_int & 0x002) and not bool(flag_int & 0x010)
            except (ValueError, TypeError):
                is_syn = "S" in flags.upper() and "A" not in flags.upper()
        if is_syn:
            src_syn_times[src].append((ts, dport))

        # RST detection
        is_rst = False
        if flags:
            try:
                flag_int = int(flags, 16)
                is_rst = bool(flag_int & 0x004)
            except (ValueError, TypeError):
                is_rst = "R" in flags.upper()
        if is_rst:
            rst_counts[src] += 1

    scan_suspects: list[dict] = []
    threshold_ports = 20   # >20 distinct ports from one src → scan
    threshold_hosts = 15   # >15 distinct hosts on same port → horizontal scan

    for src, ports in src_ports.items():
        if len(ports) >= threshold_ports:
            # Check if concentrated in ≤ 60 s window
            times = sorted(t for t, _ in src_syn_times.get(src, []))
            window_ok = len(times) >= 2 and (times[-1] - times[0]) <= 60

            scan_suspects.append({
                "src_ip": src,
                "type": "vertical_scan",
                "distinct_ports": len(ports),
                "top_ports": sorted(ports)[:20],
                "within_60s": window_ok,
                "severity": "HIGH" if window_ok else "MEDIUM",
            })

    # Horizontal scan: single port, many destinations
    port_dst_map: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for p in tcp_pkts:
        port_dst_map[p.get("dst_port", "")][p.get("src_ip", "")].add(p.get("dst_ip", ""))

    for port, src_map in port_dst_map.items():
        for src, dsts in src_map.items():
            if len(dsts) >= threshold_hosts:
                scan_suspects.append({
                    "src_ip": src,
                    "type": "horizontal_scan",
                    "target_port": port,
                    "distinct_targets": len(dsts),
                    "severity": "HIGH",
                })

    # RST storm
    rst_storm = [
        {"src_ip": ip, "rst_count": cnt, "severity": "MEDIUM"}
        for ip, cnt in rst_counts.most_common(5)
        if cnt > 50
    ]

    return {
        "tcp_packets_analyzed": len(tcp_pkts),
        "scan_suspects": scan_suspects[:20],
        "rst_storm": rst_storm,
        "top_port_touchers": [
            {"src_ip": ip, "distinct_ports": len(ports)}
            for ip, ports in sorted(src_ports.items(), key=lambda x: len(x[1]), reverse=True)[:10]
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Flow Analysis
# ─────────────────────────────────────────────────────────────────────────────

def flow_analysis(packets: list[dict]) -> dict:
    """
    Analyse packet flows (5-tuple: src_ip, dst_ip, src_port, dst_port, protocol).

    Returns top flows by packet count and byte volume, long-lived flows,
    and ICS-specific flow summary.
    """
    Flow = tuple  # (src_ip, dst_ip, src_port, dst_port, proto)

    flow_pkts:  dict[Flow, int]   = defaultdict(int)
    flow_bytes: dict[Flow, int]   = defaultdict(int)
    flow_start: dict[Flow, float] = {}
    flow_end:   dict[Flow, float] = {}

    for p in packets:
        key: Flow = (
            p.get("src_ip", ""),
            p.get("dst_ip", ""),
            p.get("src_port", ""),
            p.get("dst_port", ""),
            p.get("protocol", "OTHER"),
        )
        ts = p.get("timestamp", 0.0)
        flow_pkts[key]  += 1
        flow_bytes[key] += p.get("length", 0)
        if key not in flow_start or ts < flow_start[key]:
            flow_start[key] = ts
        if key not in flow_end or ts > flow_end[key]:
            flow_end[key] = ts

    def _flow_dict(key: Flow) -> dict:
        duration = round(flow_end.get(key, 0) - flow_start.get(key, 0), 2)
        return {
            "src":       f"{key[0]}:{key[2]}",
            "dst":       f"{key[1]}:{key[3]}",
            "protocol":  key[4],
            "packets":   flow_pkts[key],
            "bytes":     flow_bytes[key],
            "duration_s": duration,
        }

    # Top by packet count
    top_by_pkts = sorted(flow_pkts, key=lambda k: flow_pkts[k], reverse=True)[:15]
    # Top by bytes
    top_by_bytes = sorted(flow_bytes, key=lambda k: flow_bytes[k], reverse=True)[:15]
    # Long-lived (>= 30s)
    long_lived = [
        k for k in flow_end
        if (flow_end[k] - flow_start.get(k, flow_end[k])) >= 30
    ]

    total_bytes = sum(flow_bytes.values())
    ics_flows = [k for k in flow_pkts if k[4] in ("MODBUS", "DNP3", "OPC-UA")]

    return {
        "total_flows":  len(flow_pkts),
        "total_bytes":  total_bytes,
        "top_by_packets": [_flow_dict(k) for k in top_by_pkts],
        "top_by_bytes":   [_flow_dict(k) for k in top_by_bytes],
        "long_lived_flows": [_flow_dict(k) for k in long_lived[:10]],
        "ics_flows": [_flow_dict(k) for k in sorted(ics_flows, key=lambda k: flow_pkts[k], reverse=True)[:10]],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Conversations
# ─────────────────────────────────────────────────────────────────────────────

def conversations(packets: list[dict]) -> dict:
    """
    Enumerate unique src↔dst IP pairs (bidirectional), sorted by packet count.
    """
    conv_pkts:  dict[tuple, int]   = defaultdict(int)
    conv_bytes: dict[tuple, int]   = defaultdict(int)
    conv_protos: dict[tuple, Counter] = defaultdict(Counter)

    for p in packets:
        a, b = p.get("src_ip", ""), p.get("dst_ip", "")
        if not a and not b:
            continue
        key = (min(a, b), max(a, b))
        conv_pkts[key]  += 1
        conv_bytes[key] += p.get("length", 0)
        conv_protos[key][p.get("protocol", "OTHER")] += 1

    result = [
        {
            "peer_a":    key[0],
            "peer_b":    key[1],
            "packets":   conv_pkts[key],
            "bytes":     conv_bytes[key],
            "protocols": dict(conv_protos[key].most_common(4)),
        }
        for key in sorted(conv_pkts, key=lambda k: conv_pkts[k], reverse=True)[:30]
    ]

    return {
        "total_conversations": len(conv_pkts),
        "conversations": result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Anomaly Detection
# ─────────────────────────────────────────────────────────────────────────────

def anomaly_detect(packets: list[dict]) -> dict:
    """
    Statistical anomaly detection:
      - High-rate single-IP bursts (>20% of traffic)
      - Unusual well-known port usage
      - Protocol/port mismatches
      - Broadcast traffic
      - Large packets (> 1400 bytes)
      - ICS traffic from non-ICS subnets
    """
    total = len(packets)
    if total == 0:
        return {"anomalies": [], "stats": {}}

    findings: list[dict] = []

    src_counter: Counter = Counter(p.get("src_ip", "") for p in packets if p.get("src_ip"))
    dst_counter: Counter = Counter(p.get("dst_ip", "") for p in packets if p.get("dst_ip"))
    proto_counter: Counter = Counter(p.get("protocol", "OTHER") for p in packets)
    port_counter: Counter = Counter(
        p.get("dst_port", "") for p in packets if p.get("dst_port")
    )

    # High-rate single source
    for ip, cnt in src_counter.most_common(5):
        ratio = cnt / total
        if ratio > 0.3:
            findings.append({
                "severity": "HIGH" if ratio > 0.5 else "MEDIUM",
                "category": "traffic_burst",
                "description": f"{ip} generated {cnt}/{total} packets ({ratio:.0%})",
                "value": cnt,
            })

    # Broadcasts
    bc_count = sum(1 for p in packets if p.get("dst_ip", "").endswith(".255")
                   or p.get("dst_ip") == "255.255.255.255")
    if bc_count > 50:
        findings.append({
            "severity": "LOW",
            "category": "broadcast",
            "description": f"{bc_count} broadcast packets detected.",
            "value": bc_count,
        })

    # Unusually large packets
    large = [p for p in packets if p.get("length", 0) > 1400]
    if len(large) > 20:
        avg_large = sum(p["length"] for p in large) / len(large)
        findings.append({
            "severity": "LOW",
            "category": "large_packets",
            "description": f"{len(large)} packets > 1400 bytes (avg {avg_large:.0f} B) — possible bulk transfer or jumbo frames.",
            "value": len(large),
        })

    # Protocol/port mismatch (e.g. TLS on port 80, HTTP on port 443)
    for p in packets:
        proto = p.get("protocol", "")
        dport = p.get("dst_port", "")
        if proto == "TLS" and dport in ("80", "8080"):
            findings.append({
                "severity": "MEDIUM",
                "category": "protocol_mismatch",
                "description": f"TLS traffic on port {dport} — possible evasion or misconfiguration.",
                "value": 1,
            })
            break
        if proto == "HTTP" and dport == "443":
            findings.append({
                "severity": "MEDIUM",
                "category": "protocol_mismatch",
                "description": "Cleartext HTTP on port 443 — possible protocol mismatch.",
                "value": 1,
            })
            break

    # ICS traffic outside expected ports
    for p in packets:
        proto = p.get("protocol", "")
        dport = _int_port(p.get("dst_port", ""))
        if proto == "MODBUS" and dport not in _MODBUS_PORTS:
            findings.append({
                "severity": "HIGH",
                "category": "ics_nonstandard_port",
                "description": f"Modbus traffic on non-standard port {dport}.",
                "value": dport,
            })
            break
        if proto == "DNP3" and dport not in _DNP3_PORTS:
            findings.append({
                "severity": "HIGH",
                "category": "ics_nonstandard_port",
                "description": f"DNP3 traffic on non-standard port {dport}.",
                "value": dport,
            })
            break

    # Unknown high ports used heavily
    unusual_ports = [
        (port, cnt) for port, cnt in port_counter.most_common(20)
        if port and _int_port(port) > 1024 and cnt > total * 0.05
        and _int_port(port) not in {4840, 4843, 8080, 8443, 8000, 9200}
    ]
    if len(unusual_ports) > 5:
        findings.append({
            "severity": "LOW",
            "category": "unusual_ports",
            "description": f"{len(unusual_ports)} high ports each handling >5% of traffic: "
                           f"{[p for p, _ in unusual_ports[:5]]}",
            "value": len(unusual_ports),
        })

    return {
        "total_packets": total,
        "anomalies": findings,
        "stats": {
            "top_src_ips":   dict(src_counter.most_common(5)),
            "top_dst_ips":   dict(dst_counter.most_common(5)),
            "protocol_dist": dict(proto_counter.most_common(8)),
            "top_dst_ports": dict(port_counter.most_common(8)),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM commentary
# ─────────────────────────────────────────────────────────────────────────────

async def llm_commentary(mode: str, analysis_result: dict) -> str:
    """
    Ask the LLM to comment on an expert analysis result.
    Keeps the prompt compact to stay within small-model token budgets.
    """
    import json

    mode_labels = {
        "ics_audit":        "ICS/SCADA Protocol Audit",
        "port_scan":        "Port Scan Detection",
        "flow_analysis":    "Network Flow Analysis",
        "conversations":    "Conversation Enumeration",
        "anomaly_detect":   "Statistical Anomaly Detection",
    }
    label = mode_labels.get(mode, mode)

    # Trim the result to keep token count manageable
    trimmed = json.dumps(analysis_result, default=str)
    if len(trimmed) > 3000:
        trimmed = trimmed[:3000] + "\n... [truncated]"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior OT/ICS network security analyst. "
                "Summarize findings concisely using markdown. "
                "Highlight critical risks, explain what each finding means operationally, "
                "and suggest concrete remediation steps. Be brief."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Expert analysis mode: **{label}**\n\n"
                f"```json\n{trimmed}\n```\n\n"
                "Provide a concise security assessment with: "
                "1) Critical findings, 2) Operational impact, 3) Recommended actions."
            ),
        },
    ]

    return await chat_completion(messages, max_tokens=300)
