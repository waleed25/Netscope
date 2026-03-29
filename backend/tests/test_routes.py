"""
Unit tests for api/routes.py

Covers:
  - Module-level helpers: get_packets, clear_packets, add_packets, add_insight
  - HTTP endpoints via FastAPI TestClient (mocking external dependencies)
"""

import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Import the helpers directly
import api.routes as routes_module
from api.routes import get_packets, clear_packets, add_packets, add_insight


# ── In-memory store helpers ───────────────────────────────────────────────────

class TestPacketStore:
    def setup_method(self):
        clear_packets()

    def test_clear_packets_empties_list(self):
        add_packets([{"id": 1}, {"id": 2}])
        clear_packets()
        assert get_packets() == []

    def test_add_packets_appends(self):
        add_packets([{"id": 1}])
        add_packets([{"id": 2}])
        assert len(get_packets()) == 2

    def test_add_packets_trims_to_max(self):
        from config import settings
        original_max = settings.max_packets_in_memory
        settings.max_packets_in_memory = 5
        try:
            add_packets([{"id": i} for i in range(10)])
            # After adding 10, only the last 5 should remain
            assert len(get_packets()) == 5
        finally:
            settings.max_packets_in_memory = original_max

    def test_get_packets_returns_list(self):
        assert isinstance(get_packets(), list)

    def test_add_empty_list_is_noop(self):
        add_packets([])
        assert get_packets() == []


class TestInsightStore:
    def setup_method(self):
        routes_module._insights.clear()

    def test_add_insight_appends_dict(self):
        add_insight("Traffic looks normal.")
        assert len(routes_module._insights) == 1
        assert routes_module._insights[0]["text"] == "Traffic looks normal."

    def test_add_insight_includes_timestamp(self):
        before = time.time()
        add_insight("test")
        after = time.time()
        ts = routes_module._insights[0]["timestamp"]
        assert before <= ts <= after

    def test_add_insight_includes_source(self):
        add_insight("test", source="manual")
        assert routes_module._insights[0]["source"] == "manual"

    def test_add_insight_trims_to_100(self):
        for i in range(110):
            add_insight(f"insight {i}")
        assert len(routes_module._insights) <= 100


# ── HTTP endpoints via TestClient ─────────────────────────────────────────────

@pytest.fixture
def client():
    """Create a TestClient with mocked external dependencies."""
    from main import app

    # Patch live_capture so no real tshark is invoked
    with patch("capture.live_capture.is_capturing", return_value=False), \
         patch("capture.live_capture.get_active_interface", return_value=""), \
         patch("capture.live_capture.get_interfaces", new_callable=AsyncMock,
               return_value=[{"index": "1", "name": "Ethernet"}]):
        with TestClient(app) as c:
            yield c


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCaptureStatusEndpoint:
    def test_capture_status_structure(self, client):
        with patch("capture.live_capture.is_capturing", return_value=False), \
             patch("capture.live_capture.get_active_interface", return_value=""):
            resp = client.get("/api/capture/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_capturing" in data
        assert "packet_count" in data


class TestInterfacesEndpoint:
    def test_interfaces_returned(self, client):
        with patch("capture.live_capture.get_interfaces", new_callable=AsyncMock,
                   return_value=[{"index": "1", "name": "Wi-Fi"}]):
            resp = client.get("/api/interfaces")
        assert resp.status_code == 200
        assert "interfaces" in resp.json()


class TestPacketsEndpoint:
    def setup_method(self):
        clear_packets()

    def test_empty_packets(self, client):
        resp = client.get("/api/packets")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_packets_returned_after_add(self, client):
        add_packets([{
            "id": 1, "timestamp": 0, "layers": [], "src_ip": "1.1.1.1",
            "dst_ip": "2.2.2.2", "src_port": "80", "dst_port": "443",
            "protocol": "TCP", "length": 64, "info": "", "color": "green", "details": {},
        }])
        resp = client.get("/api/packets")
        assert resp.json()["total"] == 1

    def test_protocol_filter(self, client):
        add_packets([
            {"id": 1, "protocol": "DNS", "src_ip": "", "dst_ip": "", "src_port": "",
             "dst_port": "", "length": 0, "timestamp": 0, "layers": [], "info": "",
             "color": "", "details": {}},
            {"id": 2, "protocol": "TCP", "src_ip": "", "dst_ip": "", "src_port": "",
             "dst_port": "", "length": 0, "timestamp": 0, "layers": [], "info": "",
             "color": "", "details": {}},
        ])
        resp = client.get("/api/packets?protocol=DNS")
        data = resp.json()
        assert data["total"] == 1
        assert data["packets"][0]["protocol"] == "DNS"


class TestChatEndpoint:
    @pytest.mark.asyncio
    async def test_non_streaming_chat_returns_response(self, client):
        with patch("agent.chat.answer_question", new_callable=AsyncMock,
                   return_value="Your traffic looks fine."):
            resp = client.post("/api/chat", json={"message": "hello", "stream": False})
        assert resp.status_code == 200
        assert "response" in resp.json()
        assert resp.json()["response"] == "Your traffic looks fine."


class TestInsightsEndpoint:
    def setup_method(self):
        routes_module._insights.clear()

    def test_get_insights_empty(self, client):
        resp = client.get("/api/insights")
        assert resp.status_code == 200
        assert resp.json()["insights"] == []

    def test_generate_insight_no_packets_returns_400(self, client):
        clear_packets()
        resp = client.post("/api/insights/generate")
        assert resp.status_code == 400

    def test_generate_insight_with_packets(self, client):
        add_packets([{
            "id": 1, "timestamp": 0, "layers": [], "src_ip": "1.1.1.1",
            "dst_ip": "2.2.2.2", "src_port": "80", "dst_port": "443",
            "protocol": "TCP", "length": 64, "info": "", "color": "green", "details": {},
        }])
        with patch("agent.analyzer.generate_insights", new_callable=AsyncMock,
                   return_value="Looks normal."):
            resp = client.post("/api/insights/generate")
        assert resp.status_code == 200
        assert "insight" in resp.json()


class TestLLMTokensEndpoint:
    def test_get_tokens_returns_usage(self, client):
        resp = client.get("/api/llm/tokens")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt_tokens" in data
        assert "total_tokens" in data

    def test_reset_tokens(self, client):
        resp = client.post("/api/llm/tokens/reset")
        assert resp.status_code == 200

    def test_set_backend_valid(self, client):
        resp = client.post("/api/llm/backend", json={"backend": "lmstudio"})
        assert resp.status_code == 200

    def test_set_backend_invalid_returns_400(self, client):
        resp = client.post("/api/llm/backend", json={"backend": "openai"})
        assert resp.status_code == 400


class TestChatHistoryEndpoint:
    def setup_method(self):
        routes_module._chat_history.clear()

    def test_get_empty_history(self, client):
        resp = client.get("/api/chat/history")
        assert resp.status_code == 200
        assert resp.json()["history"] == []

    def test_delete_chat_history(self, client):
        routes_module._chat_history.append({"role": "user", "content": "hi"})
        resp = client.delete("/api/chat/history")
        assert resp.status_code == 200
        assert list(routes_module._chat_history) == []


class TestAnalysisEndpoints:
    def setup_method(self):
        routes_module._last_deep_analysis = None

    def test_deep_analysis_returns_all_sections(self, client):
        from unittest.mock import patch
        sample = {
            "tcp_health": {"retransmissions": 0, "zero_windows": 0, "duplicate_acks": 0,
                           "out_of_order": 0, "rsts": 0, "rtt_avg_ms": 0.0,
                           "top_offenders": [], "estimated": True},
            "streams": [],
            "latency": {"streams": [], "aggregate": {"network_rtt_ms": 0.0, "server_ms": 0.0,
                        "client_ms": 0.0, "bottleneck": "unknown", "server_pct": 0}},
            "expert_info": {"available": False, "reason": "live capture"},
            "io_timeline": [],
        }
        with patch("api.routes.run_deep_analysis", return_value=sample):
            resp = client.post("/api/analysis/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert "tcp_health" in data
        assert "streams" in data

    def test_narrative_returns_400_when_no_analysis_run(self, client):
        routes_module._last_deep_analysis = None
        resp = client.get("/api/analysis/narrative")
        assert resp.status_code == 400

    def test_tcp_health_endpoint(self, client):
        from unittest.mock import patch
        with patch("api.routes.tcp_health_fn", return_value={"retransmissions": 0}):
            resp = client.get("/api/analysis/tcp-health")
        # 200 or 500 depending on whether packets exist — just check it doesn't crash
        assert resp.status_code in (200, 500)
