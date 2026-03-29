"""Tests for analysis_pipeline.py"""
import pytest
from tests.conftest import make_packet


def _tcp(src_ip, dst_ip, src_port, dst_port, ts, flags="", seq=None, details=None):
    p = make_packet(
        protocol="TCP", src_ip=src_ip, dst_ip=dst_ip,
        src_port=src_port, dst_port=dst_port,
        timestamp=ts, details=details or {},
    )
    if flags:
        p["details"]["tcp_flags"] = flags
    if seq is not None:
        p["details"]["tcp_seq"] = str(seq)
    return p


class TestTcpHealth:
    def test_empty_packets_returns_zeros(self):
        from agent.tools.analysis_pipeline import tcp_health
        result = tcp_health([], pcap_path=None)
        assert result["retransmissions"] == 0
        assert result["rsts"] == 0
        assert result["estimated"] is True

    def test_counts_rsts_from_tcp_flags(self):
        from agent.tools.analysis_pipeline import tcp_health
        pkts = [
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.0, flags="RST"),
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.1, flags="RST"),
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.2, flags="ACK"),
        ]
        result = tcp_health(pkts, pcap_path=None)
        assert result["rsts"] == 2
        assert result["estimated"] is True

    def test_rtt_from_syn_synack_pair(self):
        from agent.tools.analysis_pipeline import tcp_health
        # SYN at t=0, SYN-ACK at t=0.004 → RTT 4ms
        pkts = [
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.000, flags="SYN"),
            _tcp("2.2.2.2", "1.1.1.1", "80", "1000", 0.004, flags="SYN,ACK"),
        ]
        result = tcp_health(pkts, pcap_path=None)
        assert abs(result["rtt_avg_ms"] - 4.0) < 0.5


class TestStreamInventory:
    def test_groups_by_4tuple_without_pcap(self):
        from agent.tools.analysis_pipeline import stream_inventory
        pkts = [
            make_packet(src_ip="1.1.1.1", dst_ip="2.2.2.2", src_port="1000", dst_port="80", length=100),
            make_packet(src_ip="1.1.1.1", dst_ip="2.2.2.2", src_port="1000", dst_port="80", length=200),
            make_packet(src_ip="3.3.3.3", dst_ip="4.4.4.4", src_port="2000", dst_port="443", length=50),
        ]
        result = stream_inventory(pkts, pcap_path=None)
        assert len(result) == 2
        assert result[0]["bytes"] == 300   # sorted by bytes desc
        assert result[0]["packets"] == 2

    def test_detects_http_by_port(self):
        from agent.tools.analysis_pipeline import stream_inventory
        pkts = [make_packet(src_port="54321", dst_port="80", length=100)]
        result = stream_inventory(pkts, pcap_path=None)
        assert result[0]["protocol"] == "HTTP"

    def test_detects_tls_by_port(self):
        from agent.tools.analysis_pipeline import stream_inventory
        pkts = [make_packet(src_port="54321", dst_port="443", length=100)]
        result = stream_inventory(pkts, pcap_path=None)
        assert result[0]["protocol"] == "TLS"


class TestLatencyBreakdown:
    def test_returns_empty_streams_without_pcap_and_no_syn(self):
        from agent.tools.analysis_pipeline import latency_breakdown
        pkts = [make_packet()]
        result = latency_breakdown(pkts, pcap_path=None)
        assert "aggregate" in result
        assert result["aggregate"]["network_rtt_ms"] == 0.0

    def test_computes_rtt_from_syn_synack(self):
        from agent.tools.analysis_pipeline import latency_breakdown
        pkts = [
            _tcp("1.1.1.1", "2.2.2.2", "1000", "80", 0.000, flags="SYN"),
            _tcp("2.2.2.2", "1.1.1.1", "80", "1000", 0.006, flags="SYN,ACK"),
        ]
        result = latency_breakdown(pkts, pcap_path=None)
        assert result["aggregate"]["network_rtt_ms"] == pytest.approx(6.0, abs=0.5)


class TestExpertInfoSummary:
    def test_returns_unavailable_when_no_pcap(self):
        from agent.tools.analysis_pipeline import expert_info_summary
        result = expert_info_summary(None)
        assert result["available"] is False
        assert "reason" in result

    def test_returns_unavailable_for_nonexistent_pcap(self):
        from agent.tools.analysis_pipeline import expert_info_summary
        result = expert_info_summary("/nonexistent/file.pcap")
        assert result["available"] is False


class TestIoTimeline:
    def test_empty_returns_empty_list(self):
        from agent.tools.analysis_pipeline import io_timeline
        assert io_timeline([]) == []

    def test_bins_packets_by_second(self):
        from agent.tools.analysis_pipeline import io_timeline
        pkts = [
            make_packet(timestamp=0.1, length=100),
            make_packet(timestamp=0.5, length=200),
            make_packet(timestamp=1.1, length=150),
        ]
        result = io_timeline(pkts)
        assert len(result) == 2
        assert result[0]["t"] == pytest.approx(0.0, abs=0.01)
        assert result[0]["packets_per_sec"] == 2
        assert result[0]["bytes_per_sec"] == 300

    def test_annotates_burst(self):
        from agent.tools.analysis_pipeline import io_timeline
        # 5 quiet seconds then a burst
        base_pkts = [make_packet(timestamp=float(i) + 0.5) for i in range(5)]
        burst_pkts = [make_packet(timestamp=5.1 + j * 0.01) for j in range(50)]
        result = io_timeline(base_pkts + burst_pkts)
        burst_bins = [b for b in result if b["burst"]]
        assert len(burst_bins) >= 1


class TestRunDeepAnalysis:
    def test_returns_all_sections(self):
        from agent.tools.analysis_pipeline import run_deep_analysis
        pkts = [make_packet()]
        result = run_deep_analysis(pkts, pcap_path=None)
        assert set(result.keys()) == {"tcp_health", "streams", "latency", "expert_info", "io_timeline"}
