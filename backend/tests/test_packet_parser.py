"""
Unit tests for dissector/packet_parser.py

Covers:
  - _first: list unwrapping, scalar pass-through, None handling
  - _detect_protocol_from_list: all protocol branches
  - detect_protocol: layer-list based detection
  - parse_tshark_json: full packet parsing, each field, edge cases
  - _safe: attribute traversal
  - PROTOCOL_COLORS: key presence
"""

import pytest
import time

from dissector.packet_parser import (
    _first,
    _detect_protocol_from_list,
    detect_protocol,
    parse_tshark_json,
    _safe,
    PROTOCOL_COLORS,
)


# ── _first ────────────────────────────────────────────────────────────────────

class TestFirst:
    def test_list_with_one_element(self):
        assert _first(["hello"]) == "hello"

    def test_list_with_multiple_elements_returns_first(self):
        assert _first(["a", "b", "c"]) == "a"

    def test_empty_list_returns_empty_string(self):
        assert _first([]) == ""

    def test_scalar_string_returned_as_is(self):
        assert _first("direct") == "direct"

    def test_scalar_int_converted_to_string(self):
        assert _first(42) == "42"

    def test_none_returns_empty_string(self):
        assert _first(None) == ""

    def test_list_of_ints(self):
        assert _first([7, 8, 9]) == "7"


# ── _detect_protocol_from_list ────────────────────────────────────────────────

class TestDetectProtocol:
    def test_http_method_in_details(self):
        assert _detect_protocol_from_list([], {"http_method": "GET"}, "", "") == "HTTP"

    def test_http_response_code_in_details(self):
        assert _detect_protocol_from_list([], {"http_response_code": "200"}, "", "") == "HTTP"

    def test_tls_sni_in_details(self):
        assert _detect_protocol_from_list([], {"tls_sni": "example.com"}, "", "") == "TLS"

    def test_tls_in_protocol_list(self):
        assert _detect_protocol_from_list(["ETH", "IP", "TLS"], {}, "", "") == "TLS"

    def test_ssl_in_protocol_list(self):
        assert _detect_protocol_from_list(["SSL"], {}, "", "") == "TLS"

    def test_dns_query_in_details(self):
        assert _detect_protocol_from_list([], {"dns_query": "example.com"}, "", "") == "DNS"

    def test_dns_in_protocol_list(self):
        assert _detect_protocol_from_list(["DNS"], {}, "", "") == "DNS"

    def test_icmp_in_protocol_list(self):
        assert _detect_protocol_from_list(["IP", "ICMP"], {}, "", "") == "ICMP"

    def test_arp_in_protocol_list(self):
        assert _detect_protocol_from_list(["ARP"], {}, "", "") == "ARP"

    def test_port_80_is_http(self):
        assert _detect_protocol_from_list(["TCP"], {}, "", "80") == "HTTP"

    def test_port_8080_is_http(self):
        assert _detect_protocol_from_list(["TCP"], {}, "8080", "") == "HTTP"

    def test_port_443_is_tls(self):
        assert _detect_protocol_from_list(["TCP"], {}, "", "443") == "TLS"

    def test_port_53_is_dns(self):
        assert _detect_protocol_from_list(["UDP"], {}, "53", "") == "DNS"

    def test_tcp_fallback(self):
        assert _detect_protocol_from_list(["TCP"], {}, "12345", "9999") == "TCP"

    def test_udp_fallback(self):
        assert _detect_protocol_from_list(["UDP"], {}, "12345", "9999") == "UDP"

    def test_other_fallback(self):
        assert _detect_protocol_from_list(["ETH"], {}, "", "") == "OTHER"

    def test_http_takes_priority_over_tls(self):
        # HTTP detail should beat TLS in protocol list
        assert _detect_protocol_from_list(["TLS"], {"http_method": "GET"}, "", "") == "HTTP"


# ── detect_protocol (layer-list based) ───────────────────────────────────────

class TestDetectProtocolFromDict:
    def test_http_layer(self):
        assert detect_protocol({"layers": ["HTTP"]}) == "HTTP"

    def test_tls_returns_https(self):
        assert detect_protocol({"layers": ["TLS"]}) == "HTTPS"

    def test_ssl_returns_ssl(self):
        # SSL is not aliased to HTTPS — only TLS is mapped to HTTPS
        assert detect_protocol({"layers": ["SSL"]}) == "SSL"

    def test_dns_layer(self):
        assert detect_protocol({"layers": ["DNS"]}) == "DNS"

    def test_icmp_layer(self):
        assert detect_protocol({"layers": ["ICMP"]}) == "ICMP"

    def test_tcp_layer(self):
        assert detect_protocol({"layers": ["TCP"]}) == "TCP"

    def test_udp_layer(self):
        assert detect_protocol({"layers": ["UDP"]}) == "UDP"

    def test_arp_layer(self):
        assert detect_protocol({"layers": ["ARP"]}) == "ARP"

    def test_empty_layers_returns_other(self):
        assert detect_protocol({"layers": []}) == "OTHER"

    def test_case_insensitive_layer_names(self):
        assert detect_protocol({"layers": ["dns"]}) == "DNS"

    def test_priority_http_over_tcp(self):
        # HTTP is checked before TCP in the priority list
        assert detect_protocol({"layers": ["TCP", "HTTP"]}) == "HTTP"


# ── parse_tshark_json ─────────────────────────────────────────────────────────

def _make_tshark(overrides: dict = {}) -> dict:
    """Build a minimal tshark ek JSON packet."""
    base = {
        "layers": {
            "frame_protocols": ["eth:ethertype:ip:tcp"],
            "frame_time_epoch": ["1700000000.0"],
            "frame_len": ["100"],
            "ip_src": ["192.168.1.1"],
            "ip_dst": ["8.8.8.8"],
            "tcp_srcport": ["54321"],
            "tcp_dstport": ["80"],
        }
    }
    base["layers"].update(overrides)
    return base


class TestParseTsharkJson:
    def test_basic_fields_populated(self):
        pkt = parse_tshark_json(_make_tshark(), index=0)
        assert pkt["id"] == 0
        assert pkt["src_ip"] == "192.168.1.1"
        assert pkt["dst_ip"] == "8.8.8.8"
        assert pkt["src_port"] == "54321"
        assert pkt["dst_port"] == "80"
        assert pkt["length"] == 100
        assert pkt["timestamp"] == pytest.approx(1_700_000_000.0)

    def test_http_method_detected(self):
        pkt = parse_tshark_json(_make_tshark({
            "http_request_method": ["GET"],
            "http_request_uri": ["/index.html"],
            "http_host": ["example.com"],
        }), index=1)
        assert pkt["protocol"] == "HTTP"
        assert pkt["details"]["http_method"] == "GET"
        assert "GET" in pkt["info"]

    def test_http_response_code_detected(self):
        pkt = parse_tshark_json(_make_tshark({
            "http_response_code": ["200"],
        }), index=1)
        assert pkt["protocol"] == "HTTP"
        assert pkt["details"]["http_response_code"] == "200"
        assert "200" in pkt["info"]

    def test_tls_sni_detected(self):
        pkt = parse_tshark_json(_make_tshark({
            "tls_handshake_extensions_server_name": ["secure.example.com"],
            "tcp_dstport": ["443"],
        }), index=2)
        assert pkt["protocol"] == "TLS"
        assert pkt["details"]["tls_sni"] == "secure.example.com"
        assert "secure.example.com" in pkt["info"]

    def test_dns_query_detected(self):
        pkt = parse_tshark_json(_make_tshark({
            "frame_protocols": ["eth:ethertype:ip:udp:dns"],
            "dns_qry_name": ["example.com"],
            "tcp_srcport": [],
            "tcp_dstport": [],
            "udp_srcport": ["12345"],
            "udp_dstport": ["53"],
        }), index=3)
        assert pkt["protocol"] == "DNS"
        assert pkt["details"]["dns_query"] == "example.com"
        assert "DNS Query" in pkt["info"]

    def test_arp_src_overrides_ip(self):
        pkt = parse_tshark_json(_make_tshark({
            "frame_protocols": ["eth:ethertype:arp"],
            "arp_src_proto_ipv4": ["10.0.0.1"],
            "arp_dst_proto_ipv4": ["10.0.0.2"],
            "arp_opcode": ["1"],
            "ip_src": [],
            "ip_dst": [],
        }), index=4)
        assert pkt["src_ip"] == "10.0.0.1"
        assert pkt["dst_ip"] == "10.0.0.2"
        assert "ARP" in pkt["info"]

    def test_icmp_detected(self):
        pkt = parse_tshark_json(_make_tshark({
            "frame_protocols": ["eth:ethertype:ip:icmp"],
            "icmp_type": ["8"],
        }), index=5)
        assert pkt["details"]["icmp_type"] == "8"
        assert "ICMP" in pkt["info"]

    def test_tcp_flags_in_details(self):
        pkt = parse_tshark_json(_make_tshark({
            "tcp_flags": ["0x002"],
        }), index=6)
        assert pkt["details"]["tcp_flags"] == "0x002"

    def test_invalid_timestamp_falls_back_to_now(self):
        data = _make_tshark({"frame_time_epoch": ["not_a_number"]})
        before = time.time()
        pkt = parse_tshark_json(data, index=7)
        after = time.time()
        assert before <= pkt["timestamp"] <= after

    def test_invalid_length_defaults_to_zero(self):
        pkt = parse_tshark_json(_make_tshark({"frame_len": ["bad"]}), index=8)
        assert pkt["length"] == 0

    def test_color_assigned_from_protocol(self):
        pkt = parse_tshark_json(_make_tshark(), index=9)
        assert pkt["color"] in PROTOCOL_COLORS.values() or pkt["color"] == "gray"

    def test_protocol_port_80_is_http(self):
        pkt = parse_tshark_json(_make_tshark({
            "frame_protocols": ["eth:ethertype:ip:tcp"],
            "tcp_dstport": ["80"],
        }), index=10)
        assert pkt["protocol"] == "HTTP"

    def test_ipv6_src_used_when_no_ipv4(self):
        pkt = parse_tshark_json(_make_tshark({
            "ip_src": [],
            "ip_dst": [],
            "ipv6_src": ["::1"],
            "ipv6_dst": ["::2"],
        }), index=11)
        assert pkt["src_ip"] == "::1"
        assert pkt["dst_ip"] == "::2"

    def test_empty_packet_does_not_crash(self):
        pkt = parse_tshark_json({"layers": {}}, index=99)
        assert pkt["id"] == 99
        assert pkt["src_ip"] == ""
        assert pkt["protocol"] == "OTHER"


# ── _safe ─────────────────────────────────────────────────────────────────────

class TestSafe:
    def test_single_attr_exists(self):
        obj = MagicMock()
        obj.src = "10.0.0.1"
        assert _safe(obj, "src") == "10.0.0.1"

    def test_single_attr_missing_returns_default(self):
        class Obj: pass
        assert _safe(Obj(), "missing") == ""

    def test_custom_default_returned(self):
        class Obj: pass
        assert _safe(Obj(), "x", default="N/A") == "N/A"

    def test_chained_attrs(self):
        class Inner: value = "deep"
        class Outer: inner = Inner()
        assert _safe(Outer(), "inner", "value") == "deep"

    def test_chained_missing_mid_chain(self):
        class Outer: pass
        assert _safe(Outer(), "inner", "value") == ""

    def test_none_value_returns_empty_string(self):
        obj = MagicMock()
        obj.src = None
        assert _safe(obj, "src") == ""


# ── PROTOCOL_COLORS ───────────────────────────────────────────────────────────

class TestProtocolColors:
    def test_all_expected_protocols_have_colors(self):
        for proto in ["HTTP", "TLS", "DNS", "TCP", "UDP", "ICMP", "ARP", "OTHER"]:
            assert proto in PROTOCOL_COLORS, f"Missing color for {proto}"

    def test_values_are_strings(self):
        for k, v in PROTOCOL_COLORS.items():
            assert isinstance(v, str), f"Color for {k} is not a string"


# needed for _safe mock
from unittest.mock import MagicMock
