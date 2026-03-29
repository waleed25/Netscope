import dataclasses
import time
import pytest
from modbus.diagnostics import JitterMonitor, DiagnosticsEngine
from modbus.interceptor import FrameStore
from modbus.frame_parser import ParsedFrame, MBAPHeader


# ── JitterMonitor unit tests ──────────────────────────────────────────────────

def test_jitter_monitor_empty_returns_zero_samples():
    jm = JitterMonitor(target_interval_ms=1000.0)
    s = jm.stats()
    assert s["samples"] == 0
    assert s["target_ms"] == 1000.0


def test_jitter_monitor_one_tick_returns_zero_samples():
    jm = JitterMonitor(target_interval_ms=1000.0)
    jm.tick()
    s = jm.stats()
    assert s["samples"] == 0  # need 2 ticks for one interval


def test_jitter_monitor_two_ticks_records_one_interval():
    jm = JitterMonitor(target_interval_ms=100.0)
    jm._last_ns = time.time_ns() - 120_000_000  # simulate 120ms ago
    jm.tick()
    s = jm.stats()
    assert s["samples"] == 1
    assert 100.0 < s["mean_ms"] < 200.0  # rough sanity


def test_jitter_monitor_stats_keys():
    jm = JitterMonitor(target_interval_ms=500.0)
    # Inject 10 synthetic intervals: 490, 495, 500, 505, 510 × 2 each
    for ms in [490, 495, 500, 505, 510, 490, 495, 500, 505, 510]:
        jm._intervals.append(float(ms))

    s = jm.stats()
    assert set(s.keys()) >= {
        "target_ms", "samples", "mean_ms", "std_dev_ms",
        "min_ms", "max_ms", "p50_jitter_ms", "p95_jitter_ms", "timeline_ms",
    }
    assert s["min_ms"] == 490.0
    assert s["max_ms"] == 510.0
    assert s["samples"] == 10


def test_jitter_monitor_p50_jitter_is_deviation_not_raw_interval():
    jm = JitterMonitor(target_interval_ms=1000.0)
    # All intervals are 1010ms — deviation is always 10ms
    for _ in range(20):
        jm._intervals.append(1010.0)
    s = jm.stats()
    assert s["p50_jitter_ms"] == pytest.approx(10.0, abs=0.1)
    assert s["p95_jitter_ms"] == pytest.approx(10.0, abs=0.1)


def test_jitter_monitor_timeline_ms_capped_at_60():
    jm = JitterMonitor(target_interval_ms=100.0)
    for i in range(100):
        jm._intervals.append(float(100 + i))
    s = jm.stats()
    assert len(s["timeline_ms"]) == 60


def test_jitter_monitor_window_cap():
    jm = JitterMonitor(target_interval_ms=100.0, window=5)
    for i in range(10):
        jm._intervals.append(float(100 + i))
    assert len(jm._intervals) == 5  # deque capped


# ── DiagnosticsEngine.get_stats() extension tests ────────────────────────────

def _make_frame(direction: str = "tx") -> ParsedFrame:
    return ParsedFrame(
        direction=direction, ts_us=0, frame_type="tcp",
        raw_hex="", mbap=None, function_code=3,
        fc_name="Read Holding Registers", is_exception=False,
        exception_code=None, exception_name=None,
        start_address=None, quantity=None, byte_count=None,
        data_hex=None, crc_valid=None, parse_error=None,
    )


def test_get_stats_includes_jitter_when_provided():
    eng = DiagnosticsEngine()
    jm  = JitterMonitor(target_interval_ms=1000.0)
    for _ in range(5):
        jm._intervals.append(1005.0)

    stats = eng.get_stats("nonexistent", jitter_monitor=jm)
    assert "jitter" in stats
    assert stats["jitter"]["target_ms"] == 1000.0
    assert stats["jitter"]["samples"] == 5


@pytest.mark.asyncio
async def test_get_stats_includes_traffic_when_provided():
    eng   = DiagnosticsEngine()
    store = FrameStore(session_id="s1")
    await store.ingest(_make_frame("tx"))
    await store.ingest(_make_frame("rx"))

    stats = eng.get_stats("nonexistent", frame_store=store)
    assert "traffic" in stats
    assert stats["traffic"]["tx_frames"] == 1
    assert stats["traffic"]["rx_frames"] == 1
    assert len(stats["traffic"]["recent"]) == 2


def test_get_stats_without_optionals_unchanged():
    """Existing callers with only session_id still work."""
    eng = DiagnosticsEngine()
    eng.record("s1", fc=3, addr=40001, rtt_ms=10.0, status="ok", response=[100])
    stats = eng.get_stats("s1")
    assert "jitter"  not in stats
    assert "traffic" not in stats
    assert stats["rtt"]["avg"] == pytest.approx(10.0, abs=0.1)
