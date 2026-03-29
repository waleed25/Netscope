"""
Unit tests for agent/tools/ package

Covers:
  - parse_tool_call: all valid tools, edge cases, invalid inputs
  - network tool runners: subprocess execution, timeout, error handling
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from agent.tools import parse_tool_call, TOOL_REGISTRY, MAX_OUTPUT, ensure_all
from agent.tools.network import _run_subprocess

# Ensure all tool modules are loaded for tests that check the full registry
ensure_all()


# ── parse_tool_call ────────────────────────────────────────────────────────────

class TestParseToolCall:

    def test_ping_with_host(self):
        result = parse_tool_call("TOOL: ping 8.8.8.8")
        assert result == ("ping", "8.8.8.8")

    def test_tracert_with_host(self):
        result = parse_tool_call("TOOL: tracert 1.1.1.1")
        assert result == ("tracert", "1.1.1.1")

    def test_arp_no_args(self):
        result = parse_tool_call("TOOL: arp")
        assert result == ("arp", "")

    def test_netstat_with_flags(self):
        result = parse_tool_call("TOOL: netstat -ano")
        assert result == ("netstat", "-ano")

    def test_ipconfig_with_flag(self):
        result = parse_tool_call("TOOL: ipconfig /all")
        assert result == ("ipconfig", "/all")

    def test_case_insensitive_prefix(self):
        result = parse_tool_call("tool: ping 8.8.8.8")
        assert result == ("ping", "8.8.8.8")

    def test_leading_whitespace_stripped(self):
        result = parse_tool_call("   TOOL: arp")
        assert result == ("arp", "")

    def test_no_tool_prefix_returns_none(self):
        assert parse_tool_call("ping 8.8.8.8") is None

    def test_unknown_tool_returns_none(self):
        assert parse_tool_call("TOOL: nmap -sV 8.8.8.8") is None

    def test_empty_string_returns_none(self):
        assert parse_tool_call("") is None

    def test_only_tool_prefix_returns_none(self):
        assert parse_tool_call("TOOL:") is None

    def test_tool_name_is_lowercased(self):
        result = parse_tool_call("TOOL: PING 8.8.8.8")
        assert result == ("ping", "8.8.8.8")

    def test_multiword_args_preserved(self):
        result = parse_tool_call("TOOL: netstat -a -n -o")
        assert result == ("netstat", "-a -n -o")

    def test_all_tools_registered(self):
        """Verify all expected tools are in the registry."""
        # Original 24
        expected = {
            "ping", "tracert", "arp", "netstat", "ipconfig", "capture",
            "system_status", "llm_status", "list_models", "token_usage",
            "query_packets", "list_insights", "generate_insight", "expert_analyze",
            "rag_status", "rag_search",
            "modbus_sim", "modbus_read", "modbus_write", "modbus_scan",
            "modbus_analyze", "list_modbus_sessions",
            "full_audit", "network_recon",
            # New tools added in rewrite
            "tshark_expert", "tshark_filter",
            "dnp3_analyze", "dnp3_forensics",
            "modbus_forensics",
            "list_skills", "get_skill", "create_skill", "update_skill",
            "delete_skill", "reload_skills",
        }
        assert expected.issubset(set(TOOL_REGISTRY.keys()))


# ── _run_subprocess (network tools) ──────────────────────────────────────────

class TestRunSubprocess:

    def _mock_run(self, stdout="output", returncode=0):
        m = MagicMock()
        m.stdout = stdout
        m.stderr = ""
        m.returncode = returncode
        return m

    def test_returns_stdout(self):
        with patch("subprocess.run", return_value=self._mock_run("PING output")):
            result = _run_subprocess(["ping", "-n", "4", "8.8.8.8"])
        assert result == "PING output"

    def test_output_truncated_at_max(self):
        long_output = "x" * (MAX_OUTPUT + 500)
        with patch("subprocess.run", return_value=self._mock_run(long_output)):
            result = _run_subprocess(["arp", "-a"])
        assert len(result) <= MAX_OUTPUT + 100
        assert "truncated" in result

    def test_timeout_returns_error_string(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ping", timeout=30)):
            result = _run_subprocess(["ping", "-n", "4", "8.8.8.8"])
        assert "timed out" in result

    def test_subprocess_exception_returns_error_string(self):
        with patch("subprocess.run", side_effect=OSError("No such file")):
            result = _run_subprocess(["ping", "-n", "4", "8.8.8.8"])
        assert "Failed to run" in result

    def test_empty_output_gets_placeholder(self):
        with patch("subprocess.run", return_value=self._mock_run("")):
            result = _run_subprocess(["arp", "-a"])
        assert "no output" in result.lower() or result != ""

    def test_stderr_included_in_output(self):
        m = MagicMock()
        m.stdout = ""
        m.stderr = "some error text"
        m.returncode = 1
        with patch("subprocess.run", return_value=m):
            result = _run_subprocess(["netstat", "-ano"])
        assert "some error text" in result


# ── Quick-mode analysis tools ─────────────────────────────────────────────────

from tests.conftest import make_packet


class TestQuickModeTools:
    @pytest.mark.asyncio
    async def test_tcp_health_check_tool_returns_string(self, monkeypatch):
        import api.routes as r
        r._packets.clear()
        r._packets.append(make_packet())
        with patch("agent.tools.analysis.tcp_health_fn",
                   return_value={"retransmissions": 5, "rsts": 1, "rtt_avg_ms": 3.0,
                                 "zero_windows": 0, "duplicate_acks": 0, "out_of_order": 0,
                                 "top_offenders": [], "estimated": True}):
            from agent.tools.analysis import run_tcp_health_check
            result = await run_tcp_health_check("")
        assert "retransmissions" in result or "5" in result

    @pytest.mark.asyncio
    async def test_stream_follow_requires_pcap(self, monkeypatch):
        import api.routes as r
        r._current_capture_file = None
        from agent.tools.analysis import run_stream_follow
        result = await run_stream_follow("0")
        assert "pcap" in result.lower() or "file" in result.lower()
