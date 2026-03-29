"""
Unit tests for agent/chat.py

Covers:
  - _compact_context: empty packets, non-empty packets, field presence
  - _find_tool_call: finds first TOOL: line, returns None when absent
  - _strip_tool_lines: removes TOOL: lines, preserves other content
  - _base_messages: structure, history truncation
  - answer_question (mocked LLM): no tool call path, tool call path
  - answer_question_stream (mocked LLM): plain text streaming, tool sentinel emission
"""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import agent.chat as chat_module
from agent.chat import (
    _compact_context,
    _find_tool_call,
    _strip_tool_lines,
    _base_messages,
    answer_question,
    answer_question_stream,
    MAX_TOOL_ROUNDS,
)
from agent.tools import ToolResult
from tests.conftest import make_packet


# ── _compact_context ──────────────────────────────────────────────────────────

class TestCompactContext:
    def test_empty_packets_returns_no_packets_string(self):
        result = _compact_context([])
        assert "No packets" in result

    def test_returns_valid_json_for_nonempty(self):
        pkts = [make_packet(protocol="TCP") for _ in range(3)]
        result = _compact_context(pkts)
        parsed = json.loads(result)
        assert "packet_count" in parsed
        assert parsed["packet_count"] == 3

    def test_protocol_counts_present(self):
        pkts = [make_packet(protocol="DNS")] * 5 + [make_packet(protocol="TCP")] * 2
        parsed = json.loads(_compact_context(pkts))
        assert "protocols" in parsed
        assert parsed["protocols"]["DNS"] == 5
        assert parsed["protocols"]["TCP"] == 2

    def test_top_src_ips_present(self):
        pkts = [make_packet(src_ip="1.2.3.4") for _ in range(4)]
        parsed = json.loads(_compact_context(pkts))
        assert "top_src" in parsed
        assert "1.2.3.4" in parsed["top_src"]

    def test_dns_queries_collected(self):
        pkts = [make_packet(details={"dns_query": "example.com"})]
        parsed = json.loads(_compact_context(pkts))
        assert "dns" in parsed
        assert "example.com" in parsed["dns"]

    def test_tls_sni_collected(self):
        pkts = [make_packet(details={"tls_sni": "secure.example.com"})]
        parsed = json.loads(_compact_context(pkts))
        assert "secure.example.com" in parsed["tls"]

    def test_http_requests_collected(self):
        pkts = [make_packet(details={
            "http_method": "GET",
            "http_host": "example.com",
            "http_uri": "/page",
        })]
        parsed = json.loads(_compact_context(pkts))
        assert any("GET" in req for req in parsed["http"])

    def test_recent_packets_capped_at_three(self):
        pkts = [make_packet() for _ in range(20)]
        parsed = json.loads(_compact_context(pkts))
        assert len(parsed["recent"]) <= 3


# ── _find_tool_call ───────────────────────────────────────────────────────────

class TestFindToolCall:
    def test_finds_tool_on_its_own_line(self):
        result = _find_tool_call("TOOL: ping 8.8.8.8")
        assert result == ("ping", "8.8.8.8")

    def test_finds_tool_embedded_in_text(self):
        text = "Let me check.\nTOOL: arp\nOk."
        result = _find_tool_call(text)
        assert result == ("arp", "")

    def test_returns_first_tool_when_multiple(self):
        text = "TOOL: ping 1.1.1.1\nTOOL: arp"
        result = _find_tool_call(text)
        assert result == ("ping", "1.1.1.1")

    def test_returns_none_when_no_tool(self):
        assert _find_tool_call("Here is your answer.") is None

    def test_returns_none_for_empty_string(self):
        assert _find_tool_call("") is None

    def test_returns_none_for_unknown_tool(self):
        assert _find_tool_call("TOOL: nmap -sV host") is None


# ── _strip_tool_lines ─────────────────────────────────────────────────────────

class TestStripToolLines:
    def test_removes_tool_line(self):
        result = _strip_tool_lines("TOOL: ping 8.8.8.8\nHere is the answer.")
        assert "TOOL:" not in result
        assert "Here is the answer." in result

    def test_preserves_non_tool_lines(self):
        text = "Line one\nLine two\nLine three"
        assert _strip_tool_lines(text) == text.strip()

    def test_handles_all_tool_lines(self):
        text = "TOOL: ping 1.1.1.1\nTOOL: arp"
        result = _strip_tool_lines(text)
        assert "TOOL:" not in result
        assert result == ""

    def test_empty_string(self):
        assert _strip_tool_lines("") == ""

    def test_case_insensitive_strip(self):
        result = _strip_tool_lines("tool: arp")
        assert "tool:" not in result.lower()


# ── _base_messages ────────────────────────────────────────────────────────────

class TestBaseMessages:
    def _run(self, *args, **kwargs):
        msgs, _ = asyncio.run(_base_messages(*args, **kwargs))
        return msgs

    def test_first_message_is_system(self):
        msgs = self._run([], None)
        assert msgs[0]["role"] == "system"

    def test_system_prompt_contains_tool_descriptions_when_needed(self):
        msgs = self._run([], None, question="capture 10 seconds of traffic")
        assert "TOOL:" in msgs[0]["content"]

    def test_system_prompt_always_has_always_available_tools(self):
        # Network/System tools are always_available, so TOOL: should always appear
        msgs = self._run([], None, question="what is a firewall?")
        assert "TOOL:" in msgs[0]["content"]

    def test_traffic_context_embedded_when_question_about_packets(self):
        pkts = [make_packet()]
        msgs = self._run(pkts, None, question="show me the captured packets")
        assert "packet_count" in msgs[0]["content"]

    def test_traffic_context_omitted_for_general_questions(self):
        pkts = [make_packet()]
        msgs = self._run(pkts, None, question="what is a firewall?")
        assert "packet_count" not in msgs[0]["content"]

    def test_history_entries_included_up_to_10(self):
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
                   for i in range(20)]
        msgs = self._run([], history)
        history_in_msgs = [m for m in msgs if m["role"] in ("user", "assistant")]
        assert len(history_in_msgs) == 10  # last 10 entries (5 turns)

    def test_no_history_produces_only_system_message(self):
        msgs = self._run([], None)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"


# ── answer_question ────────────────────────────────────────────────────────────

def _make_tool_result(output: str) -> ToolResult:
    return ToolResult(tool="arp", status="ok", output=output, duration_ms=5.0, safety="safe")


class TestAnswerQuestion:
    @pytest.mark.asyncio
    async def test_plain_answer_returned_directly(self):
        with patch("agent.chat.chat_completion", new_callable=AsyncMock) as mock_cc:
            mock_cc.return_value = "Here is your answer."
            result = await answer_question("What is the traffic?", [], [])
        assert result == "Here is your answer."

    @pytest.mark.asyncio
    async def test_tool_call_executes_and_loops(self):
        call_count = 0

        async def fake_cc(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "TOOL: arp"
            return "The ARP table shows nothing unusual."

        with patch("agent.chat.chat_completion", side_effect=fake_cc):
            with patch("agent.chat.dispatch", new_callable=AsyncMock,
                       return_value=_make_tool_result("10.0.0.1  aa:bb:cc:dd")):
                result = await answer_question("Show ARP", [], [])

        assert call_count == 2
        assert "ARP" in result or "unusual" in result

    @pytest.mark.asyncio
    async def test_tool_line_stripped_from_final_answer(self):
        with patch("agent.chat.chat_completion", new_callable=AsyncMock) as mock_cc:
            mock_cc.return_value = "TOOL: arp\nSome answer."
            with patch("agent.chat.dispatch", new_callable=AsyncMock,
                       return_value=_make_tool_result("arp output")):
                async def side_effect(msgs, **kwargs):
                    return "Final answer without tool lines."
                mock_cc.side_effect = side_effect
                result = await answer_question("q", [], [])
        assert "TOOL:" not in result

    @pytest.mark.asyncio
    async def test_max_tool_rounds_not_exceeded(self):
        """LLM keeps returning TOOL: — should stop after MAX_TOOL_ROUNDS."""
        with patch("agent.chat.chat_completion", new_callable=AsyncMock) as mock_cc:
            mock_cc.return_value = "TOOL: arp"
            with patch("agent.chat.dispatch", new_callable=AsyncMock,
                       return_value=_make_tool_result("some output")):
                result = await answer_question("q", [], [])
        assert mock_cc.call_count <= MAX_TOOL_ROUNDS + 1


# ── answer_question_stream ────────────────────────────────────────────────────

class TestAnswerQuestionStream:
    @pytest.mark.asyncio
    async def test_plain_text_streamed_directly(self):
        async def fake_stream(messages, **kwargs):
            for token in ["Hello", " ", "world"]:
                yield token, False

        with patch("agent.chat.chat_completion_stream", side_effect=fake_stream):
            tokens = []
            async for chunk in answer_question_stream("hi", [], []):
                tokens.append(chunk)

        assert "".join(tokens) == "Hello world"

    @pytest.mark.asyncio
    async def test_tool_call_emits_sentinels(self):
        call_count = 0

        async def fake_stream(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield "TOOL: arp\n", False
            else:
                yield "Here is the ARP result.", False

        with patch("agent.chat.chat_completion_stream", side_effect=fake_stream):
            with patch("agent.chat.dispatch", new_callable=AsyncMock,
                       return_value=_make_tool_result("10.0.0.1  aa:bb")):
                chunks = []
                async for chunk in answer_question_stream("show arp", [], []):
                    chunks.append(chunk)

        full = "".join(chunks)
        assert "\x00TOOL_CALL:arp" in full
        assert "\x00TOOL_RESULT:" in full
        assert "ARP result" in full

    @pytest.mark.asyncio
    async def test_tool_line_not_in_streamed_text(self):
        call_count = 0

        async def fake_stream(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield "TOOL: ping 8.8.8.8\n", False
            else:
                yield "Done.", False

        with patch("agent.chat.chat_completion_stream", side_effect=fake_stream):
            with patch("agent.chat.dispatch", new_callable=AsyncMock,
                       return_value=_make_tool_result("ping output")):
                chunks = []
                async for chunk in answer_question_stream("ping it", [], []):
                    chunks.append(chunk)

        text_chunks = [c for c in chunks if not c.startswith("\x00")]
        assert not any("TOOL: ping" in c for c in text_chunks)

    @pytest.mark.asyncio
    async def test_tool_call_with_no_trailing_newline(self):
        """TOOL: line with no trailing newline should still be detected via tail flush."""
        call_count = 0

        async def fake_stream(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield "TOOL: arp", False
            else:
                yield "ARP answer.", False

        with patch("agent.chat.chat_completion_stream", side_effect=fake_stream):
            with patch("agent.chat.dispatch", new_callable=AsyncMock,
                       return_value=_make_tool_result("arp result")):
                chunks = []
                async for chunk in answer_question_stream("arp?", [], []):
                    chunks.append(chunk)

        full = "".join(chunks)
        assert "\x00TOOL_CALL:" in full
        assert "\x00TOOL_RESULT:" in full


class TestAnalysisContextInjection:
    @pytest.mark.asyncio
    async def test_analysis_context_appears_in_system_message(self):
        from unittest.mock import patch

        async def fake_chat_stream(*a, **kw):
            yield ("ok", False)

        with patch("agent.chat.chat_completion_stream", side_effect=fake_chat_stream):
            messages, _ = await _base_messages(
                packets=[], history=None, question="test",
                analysis_context="TCP: 5 retransmit",
            )

        system_content = " ".join(
            m["content"] for m in messages if m["role"] == "system"
        )
        assert "TCP: 5 retransmit" in system_content
