"""Tests for narrative.py"""
import pytest
from unittest.mock import patch, AsyncMock


SAMPLE_REPORT = {
    "tcp_health": {
        "retransmissions": 42, "zero_windows": 3, "duplicate_acks": 18,
        "out_of_order": 5, "rsts": 7, "rtt_avg_ms": 4.2,
        "top_offenders": [{"src": "192.168.1.5", "dst": "10.0.0.1", "retransmits": 12}],
        "estimated": False,
    },
    "streams": [
        {"stream_id": 0, "src": "192.168.1.5:54321", "dst": "10.0.0.1:80",
         "protocol": "HTTP", "packets": 142, "bytes": 98432, "duration_s": 4.2}
    ],
    "latency": {
        "streams": [],
        "aggregate": {"network_rtt_ms": 4.2, "server_ms": 85.0, "client_ms": 11.0,
                      "bottleneck": "server", "server_pct": 85},
    },
    "expert_info": {"available": False, "reason": "live capture"},
    "io_timeline": [
        {"t": 0.0, "packets_per_sec": 12, "bytes_per_sec": 8400, "burst": False},
        {"t": 4.0, "packets_per_sec": 156, "bytes_per_sec": 109200, "burst": True},
    ],
}


@pytest.mark.asyncio
async def test_generate_narrative_yields_tokens():
    from agent.tools.narrative import generate_narrative

    async def fake_stream(messages, max_tokens=None, **kwargs):
        for token in ["The ", "capture ", "shows ", "issues."]:
            yield (token, False)

    with patch("agent.tools.narrative.chat_completion_stream", side_effect=fake_stream):
        tokens = []
        async for tok in generate_narrative(SAMPLE_REPORT):
            tokens.append(tok)
    assert "".join(tokens) == "The capture shows issues."


@pytest.mark.asyncio
async def test_generate_narrative_skips_reasoning_tokens():
    from agent.tools.narrative import generate_narrative

    async def fake_stream(messages, max_tokens=None, **kwargs):
        yield ("thinking...", True)   # reasoning token — should be skipped
        yield ("Result.", False)

    with patch("agent.tools.narrative.chat_completion_stream", side_effect=fake_stream):
        tokens = []
        async for tok in generate_narrative(SAMPLE_REPORT):
            tokens.append(tok)
    assert tokens == ["Result."]
