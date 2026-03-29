import pytest
from modbus.diagnostics import DiagnosticsEngine

def test_record_and_get_stats():
    eng = DiagnosticsEngine()
    eng.record("s1", fc=3, addr=40001, rtt_ms=10.0, status="ok", response=[100])
    eng.record("s1", fc=3, addr=40001, rtt_ms=20.0, status="ok", response=[101])
    eng.record("s1", fc=3, addr=40100, rtt_ms=8.0, status="exception", exception_code=2, response=None)
    stats = eng.get_stats("s1")
    assert stats["rtt"]["avg"] == pytest.approx(12.67, abs=0.1)
    assert stats["rtt"]["p50"] > 0
    assert len(stats["exceptions"]) == 1
    assert stats["exceptions"][0]["code"] == 2
    assert stats["exceptions"][0]["count"] == 1
    assert stats["heatmap"][40001] == 2
    assert stats["heatmap"][40100] == 1
    assert len(stats["transactions"]) == 3

def test_empty_session_returns_zeroes():
    eng = DiagnosticsEngine()
    stats = eng.get_stats("nonexistent")
    assert stats["rtt"]["avg"] == 0
    assert stats["exceptions"] == []
    assert stats["transactions"] == []

def test_transaction_ring_buffer_capped():
    eng = DiagnosticsEngine()
    for i in range(1100):
        eng.record("s1", fc=3, addr=40001, rtt_ms=10.0, status="ok", response=[i])
    stats = eng.get_stats("s1")
    assert len(stats["transactions"]) == 1000

def test_percentiles():
    eng = DiagnosticsEngine()
    for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        eng.record("s1", fc=3, addr=1, rtt_ms=float(ms), status="ok", response=[0])
    stats = eng.get_stats("s1")
    # With linear interpolation on 10 values [10..100]:
    # p50: idx=4.5 -> 50 + 0.5*(60-50) = 55.0
    # p95: idx=8.55 -> 90 + 0.55*(100-90) = 95.5
    # p99: idx=8.91 -> 90 + 0.91*(100-90) = 99.1
    assert stats["rtt"]["p50"] == pytest.approx(55.0, abs=0.1)
    assert stats["rtt"]["p95"] == pytest.approx(95.5, abs=0.1)
    assert stats["rtt"]["p99"] == pytest.approx(99.1, abs=0.1)
