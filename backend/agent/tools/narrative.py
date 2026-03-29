"""
Narrative generator — takes a run_deep_analysis() report dict and streams
a focused LLM-generated analysis prose. The LLM receives pre-computed
structured data only; no raw packets are passed.
"""
from __future__ import annotations
from typing import AsyncGenerator

from agent.llm_client import chat_completion_stream


_SYSTEM = (
    "You are Netscope, an expert network analyst. "
    "You are given pre-computed analysis metrics from a packet capture. "
    "Write a concise, expert-level narrative (under 200 words). "
    "Lead with the single most important finding. "
    "Identify the bottleneck clearly. "
    "Flag any ICS/OT concerns if present. "
    "Use markdown bullet points for multiple findings. "
    "Do NOT repeat the raw numbers — explain what they mean."
)


def _build_prompt(report: dict) -> str:
    tcp = report.get("tcp_health", {})
    lat = report.get("latency", {}).get("aggregate", {})
    streams = report.get("streams", [])
    expert = report.get("expert_info", {})
    io = report.get("io_timeline", [])

    bursts = [b for b in io if b.get("burst")]
    burst_summary = f"burst at t={bursts[0]['t']:.1f}s" if bursts else "no bursts"
    stream_protocols = list({s.get("protocol", "") for s in streams[:5] if s.get("protocol")})
    top_offender = ""
    if tcp.get("top_offenders"):
        off = tcp["top_offenders"][0]
        top_offender = f"Top retransmitter: {off['src']} → {off['dst']} ({off['retransmits']} retransmits)."

    lines = [
        "## Capture Analysis Data",
        f"TCP Health: {tcp.get('retransmissions', 0)} retransmissions, "
        f"{tcp.get('zero_windows', 0)} zero-windows, {tcp.get('rsts', 0)} RSTs, "
        f"avg RTT {tcp.get('rtt_avg_ms', 0):.1f}ms"
        + (" (estimated)" if tcp.get("estimated") else "") + ".",
        top_offender,
        f"Latency: client {lat.get('client_ms', 0):.1f}ms / "
        f"network {lat.get('network_rtt_ms', 0):.1f}ms / "
        f"server {lat.get('server_ms', 0):.1f}ms "
        f"({lat.get('bottleneck', 'unknown')} is bottleneck, "
        f"{lat.get('server_pct', 0)}% server).",
        f"Streams: {len(streams)} total, protocols: {', '.join(stream_protocols) or 'unknown'}.",
        (
            f"Expert info: {expert.get('counts', {}).get('error', 0)} errors, "
            f"{expert.get('counts', {}).get('warning', 0)} warnings."
            if expert.get("available") else "Expert info: not available (live capture)."
        ),
        f"IO: {burst_summary}.",
        "",
        "Based on this data, provide your expert analysis:",
    ]
    return "\n".join(line for line in lines if line is not None)


async def generate_narrative(report: dict) -> AsyncGenerator[str, None]:
    """Stream an LLM-generated narrative for the given deep analysis report."""
    prompt = _build_prompt(report)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    async for token, is_reasoning in chat_completion_stream(messages, max_tokens=400):
        if not is_reasoning:
            yield token
