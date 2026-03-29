"""
Unit tests for agent/analyzer.py

Covers:
  - _build_summary: empty packets, field aggregation, limits
  - _build_prompt: message structure, JSON embedding
  - generate_insights: empty fallback, calls chat_completion (mocked)
  - generate_insights_stream: empty fallback, yields tokens (mocked)
"""

import pytest
import json
from unittest.mock import AsyncMock, patch

from agent.analyzer import _build_summary, _build_prompt, generate_insights, generate_insights_stream
from tests.conftest import make_packet


# ── _build_summary ────────────────────────────────────────────────────────────

class TestBuildSummary:
    def test_empty_packets_returns_empty_dict(self):
        assert _build_summary([]) == {}

    def test_total_count(self):
        pkts = [make_packet() for _ in range(7)]
        s = _build_summary(pkts)
        assert s["total"] == 7

    def test_duration_calculated(self):
        pkts = [
            make_packet(timestamp=1000.0),
            make_packet(timestamp=1010.0),
        ]
        s = _build_summary(pkts)
        assert s["duration_s"] == pytest.approx(10.0)

    def test_duration_zero_for_single_packet(self):
        s = _build_summary([make_packet(timestamp=5000.0)])
        assert s["duration_s"] == 0.0

    def test_protocol_counts(self):
        pkts = [make_packet(protocol="DNS")] * 3 + [make_packet(protocol="TCP")] * 2
        s = _build_summary(pkts)
        assert s["protocols"]["DNS"] == 3
        assert s["protocols"]["TCP"] == 2

    def test_top_src_ips(self):
        pkts = [make_packet(src_ip="10.0.0.1")] * 4 + [make_packet(src_ip="10.0.0.2")]
        s = _build_summary(pkts)
        assert "10.0.0.1" in s["top_src_ips"]
        assert s["top_src_ips"]["10.0.0.1"] == 4

    def test_top_dst_ips(self):
        pkts = [make_packet(dst_ip="8.8.8.8")] * 6
        s = _build_summary(pkts)
        assert "8.8.8.8" in s["top_dst_ips"]

    def test_top_dst_ports(self):
        pkts = [make_packet(dst_port="443")] * 5
        s = _build_summary(pkts)
        assert "443" in s["top_dst_ports"]

    def test_dns_queries_collected_and_deduplicated(self):
        pkts = [
            make_packet(details={"dns_query": "example.com"}),
            make_packet(details={"dns_query": "example.com"}),   # duplicate
            make_packet(details={"dns_query": "other.com"}),
        ]
        s = _build_summary(pkts)
        assert "example.com" in s["dns_queries"]
        assert s["dns_queries"].count("example.com") == 1

    def test_dns_queries_capped_at_15(self):
        pkts = [make_packet(details={"dns_query": f"host{i}.com"}) for i in range(20)]
        s = _build_summary(pkts)
        assert len(s["dns_queries"]) <= 15

    def test_http_requests_collected(self):
        pkts = [make_packet(details={
            "http_method": "POST",
            "http_host": "api.example.com",
            "http_uri": "/data",
        })]
        s = _build_summary(pkts)
        assert len(s["http_requests"]) == 1
        assert "POST" in s["http_requests"][0]

    def test_http_requests_capped_at_10(self):
        pkts = [make_packet(details={
            "http_method": "GET",
            "http_host": f"host{i}.com",
            "http_uri": "/",
        }) for i in range(15)]
        s = _build_summary(pkts)
        assert len(s["http_requests"]) <= 10

    def test_tls_sni_collected_and_deduplicated(self):
        pkts = [
            make_packet(details={"tls_sni": "secure.example.com"}),
            make_packet(details={"tls_sni": "secure.example.com"}),
        ]
        s = _build_summary(pkts)
        assert s["tls_sni"].count("secure.example.com") == 1

    def test_tls_sni_capped_at_15(self):
        pkts = [make_packet(details={"tls_sni": f"host{i}.com"}) for i in range(20)]
        s = _build_summary(pkts)
        assert len(s["tls_sni"]) <= 15

    def test_top_lists_capped_at_8_and_5(self):
        pkts = [make_packet(protocol=f"P{i}") for i in range(20)]
        s = _build_summary(pkts)
        assert len(s["protocols"]) <= 8

        pkts2 = [make_packet(src_ip=f"10.0.0.{i}") for i in range(20)]
        s2 = _build_summary(pkts2)
        assert len(s2["top_src_ips"]) <= 5


# ── _build_prompt ─────────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_returns_list_of_two_messages(self):
        pkts = [make_packet()]
        msgs = _build_prompt(pkts)
        assert len(msgs) == 2

    def test_first_message_is_system(self):
        msgs = _build_prompt([make_packet()])
        assert msgs[0]["role"] == "system"

    def test_second_message_is_user(self):
        msgs = _build_prompt([make_packet()])
        assert msgs[1]["role"] == "user"

    def test_user_message_contains_json_summary(self):
        pkts = [make_packet(protocol="DNS")]
        msgs = _build_prompt(pkts)
        content = msgs[1]["content"]
        # Should contain a parseable JSON block
        start = content.find("{")
        end = content.rfind("}") + 1
        assert start != -1
        parsed = json.loads(content[start:end])
        assert "protocols" in parsed

    def test_empty_packets_still_builds_prompt(self):
        # _build_summary returns {} for empty, prompt still valid
        msgs = _build_prompt([])
        assert len(msgs) == 2


# ── generate_insights ─────────────────────────────────────────────────────────

class TestGenerateInsights:
    @pytest.mark.asyncio
    async def test_empty_packets_returns_fallback(self):
        result = await generate_insights([])
        assert "No packets" in result

    @pytest.mark.asyncio
    async def test_calls_chat_completion_with_prompt(self):
        with patch("agent.analyzer.chat_completion", new_callable=AsyncMock) as mock_cc:
            mock_cc.return_value = "Traffic looks normal."
            result = await generate_insights([make_packet()])
        assert result == "Traffic looks normal."
        assert mock_cc.called

    @pytest.mark.asyncio
    async def test_passes_max_tokens_600(self):
        with patch("agent.analyzer.chat_completion", new_callable=AsyncMock) as mock_cc:
            mock_cc.return_value = "ok"
            await generate_insights([make_packet()])
        _, kwargs = mock_cc.call_args
        assert kwargs.get("max_tokens") == 600


# ── generate_insights_stream ──────────────────────────────────────────────────

class TestGenerateInsightsStream:
    @pytest.mark.asyncio
    async def test_empty_packets_yields_fallback(self):
        tokens = []
        async for t in generate_insights_stream([]):
            tokens.append(t)
        assert "No packets" in "".join(tokens)

    @pytest.mark.asyncio
    async def test_yields_tokens_from_stream(self):
        async def fake_stream(msgs, **kwargs):
            for t in ["Interesting", " traffic"]:
                yield t

        with patch("agent.analyzer.chat_completion_stream", side_effect=fake_stream):
            tokens = []
            async for t in generate_insights_stream([make_packet()]):
                tokens.append(t)

        assert "".join(tokens) == "Interesting traffic"
