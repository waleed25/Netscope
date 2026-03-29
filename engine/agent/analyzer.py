"""
Auto-insight generator — trimmed prompts for fast local LLM response.
"""

from __future__ import annotations
import json
from collections import Counter
from typing import AsyncGenerator

from agent.llm_client import chat_completion, chat_completion_stream


SYSTEM_PROMPT = (
    "You are a network security analyst specialising in both IT and OT/ICS networks. "
    "Analyze packet data concisely. Use short markdown sections. Be direct and specific. "
    "When ICS protocols (Modbus, DNP3, OPC-UA) are present, highlight operational risks."
)

# Maps mode key → user-facing label and prompt focus instruction.
INSIGHT_MODES: dict[str, str] = {
    "general":  "General traffic overview — top talkers, protocols, DNS/HTTP activity, security concerns.",
    "security": "Security-focused — scan detection, unusual ports, suspicious IPs, protocol anomalies.",
    "ics":      "ICS/SCADA focus — Modbus function codes, DNP3 activity, OPC-UA security, operational risks.",
    "http":     "HTTP/web traffic — request methods, hosts, URIs, response codes.",
    "dns":      "DNS analysis — queried domains, response patterns, potential tunnelling.",
    "tls":      "TLS/encrypted traffic — SNI names, certificate issues, unencrypted sessions.",
}


def _build_summary(packets: list[dict]) -> dict:
    """Build a compact statistical summary for the LLM prompt."""
    if not packets:
        return {}

    total = len(packets)
    protocol_counts = Counter(p.get("protocol", "OTHER") for p in packets)
    src_ip_counts = Counter(p.get("src_ip", "") for p in packets if p.get("src_ip"))
    dst_ip_counts = Counter(p.get("dst_ip", "") for p in packets if p.get("dst_ip"))
    dst_port_counts = Counter(p.get("dst_port", "") for p in packets if p.get("dst_port"))

    dns_queries = list({
        p["details"]["dns_query"]
        for p in packets
        if p.get("details", {}).get("dns_query")
    })[:15]

    http_requests = [
        f"{p['details'].get('http_method')} {p['details'].get('http_host','')}{p['details'].get('http_uri','')}"
        for p in packets
        if p.get("details", {}).get("http_method")
    ][:10]

    tls_snis = list({
        p["details"]["tls_sni"]
        for p in packets
        if p.get("details", {}).get("tls_sni")
    })[:15]

    # ICS / SCADA summaries
    modbus_fc_counts = Counter(
        p["details"].get("modbus_fc_name") or p["details"].get("modbus_fc", "?")
        for p in packets
        if p.get("details", {}).get("modbus_fc")
    )
    modbus_units = list({
        p["details"]["modbus_unit_id"]
        for p in packets
        if p.get("details", {}).get("modbus_unit_id")
    })[:10]
    dnp3_fc_counts = Counter(
        p["details"].get("dnp3_fc_name") or p["details"].get("dnp3_fc", "?")
        for p in packets
        if p.get("details", {}).get("dnp3_fc")
    )
    opcua_services = Counter(
        p["details"].get("opcua_service", "?")
        for p in packets
        if p.get("details", {}).get("opcua_msg_type")
    )
    opcua_insecure = any(
        "None" in (p.get("details", {}).get("opcua_security") or "")
        for p in packets
    )

    duration = 0.0
    if total > 1:
        t0 = packets[0].get("timestamp", 0)
        t1 = packets[-1].get("timestamp", 0)
        duration = round(t1 - t0, 1)

    summary: dict = {
        "total": total,
        "duration_s": duration,
        "protocols": dict(protocol_counts.most_common(8)),
        "top_src_ips": dict(src_ip_counts.most_common(5)),
        "top_dst_ips": dict(dst_ip_counts.most_common(5)),
        "top_dst_ports": dict(dst_port_counts.most_common(8)),
        "dns_queries": dns_queries,
        "http_requests": http_requests,
        "tls_sni": tls_snis,
    }

    # Only include ICS sections if ICS packets are present
    if modbus_fc_counts:
        summary["modbus"] = {
            "function_codes": dict(modbus_fc_counts.most_common(10)),
            "unit_ids": modbus_units,
        }
    if dnp3_fc_counts:
        summary["dnp3"] = {"function_codes": dict(dnp3_fc_counts.most_common(10))}
    if dict(opcua_services):
        summary["opcua"] = {
            "services": dict(opcua_services.most_common(8)),
            "insecure_policy_detected": opcua_insecure,
        }

    return summary


def _build_prompt(packets: list[dict], mode: str = "general") -> list[dict]:
    summary = _build_summary(packets)
    focus = INSIGHT_MODES.get(mode, INSIGHT_MODES["general"])
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Analyze this network traffic summary and give insights.\n"
            f"Focus: {focus}\n\n"
            f"```json\n{json.dumps(summary)}\n```"
        )},
    ]


async def generate_insights(packets: list[dict], mode: str = "general") -> str:
    if not packets:
        return "No packets to analyze."
    return await chat_completion(_build_prompt(packets, mode), max_tokens=600)


async def generate_insights_stream(packets: list[dict], mode: str = "general") -> AsyncGenerator[str, None]:
    if not packets:
        yield "No packets to analyze."
        return
    reasoning_buf: list[str] = []
    yielded_content = False
    async for token, is_reasoning in chat_completion_stream(_build_prompt(packets, mode), max_tokens=600):
        if is_reasoning:
            reasoning_buf.append(token)
        else:
            yielded_content = True
            yield token
    # Fallback: model put everything inside <think> block — yield reasoning as content
    if not yielded_content and reasoning_buf:
        yield "".join(reasoning_buf)
