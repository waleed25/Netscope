from __future__ import annotations
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class _Transaction:
    seq: int
    ts: float
    session_id: str
    fc: int
    addr: int
    rtt_ms: float
    status: str              # "ok" | "exception" | "timeout"
    exception_code: int | None
    response_summary: str    # short str, e.g. "[100,200,...]" or "EC02"


class DiagnosticsEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._rtt: dict[str, deque] = {}           # session_id -> deque(maxlen=1000)
        self._exc: dict[str, dict] = {}            # session_id -> {(fc,addr,ec): count}
        self._heatmap: dict[str, dict] = {}        # session_id -> {addr: count}
        self._transactions: dict[str, deque] = {}  # session_id -> deque(maxlen=1000)
        self._seq: dict[str, int] = {}
        self._timeline_buckets: dict[str, dict] = {}  # session_id -> {bucket_ts: {sum_rtt, count, exceptions}}

    def _ensure(self, sid: str):
        with self._lock:
            if sid not in self._rtt:
                self._rtt[sid] = deque(maxlen=1000)
                self._exc[sid] = {}
                self._heatmap[sid] = {}
                self._transactions[sid] = deque(maxlen=1000)
                self._seq[sid] = 0
                self._timeline_buckets[sid] = {}

    def _percentile(self, sorted_data: list[float], pct: float) -> float:
        if not sorted_data:
            return 0.0
        n = len(sorted_data)
        if n == 1:
            return sorted_data[0]
        idx = (pct / 100) * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_data[lo] + frac * (sorted_data[hi] - sorted_data[lo])

    def record(
        self, session_id: str, fc: int, addr: int, rtt_ms: float,
        status: str, response: Any, exception_code: int | None = None,
    ):
        self._ensure(session_id)
        sid = session_id
        with self._lock:
            self._rtt[sid].append(rtt_ms)
            self._heatmap[sid][addr] = self._heatmap[sid].get(addr, 0) + 1
            if status == "exception" and exception_code is not None:
                key = (fc, addr, exception_code)
                self._exc[sid][key] = self._exc[sid].get(key, 0) + 1
            self._seq[sid] += 1
            if status == "exception" and exception_code is not None:
                resp_str = f"EC{exception_code:02d}"
            elif response is not None:
                vals = list(response) if hasattr(response, "__iter__") else [response]
                resp_str = str(vals[:5])[:-1] + ("…]" if len(vals) > 5 else "]")
            else:
                resp_str = "timeout"
            self._transactions[sid].append(_Transaction(
                seq=self._seq[sid], ts=time.time(), session_id=sid,
                fc=fc, addr=addr, rtt_ms=rtt_ms, status=status,
                exception_code=exception_code, response_summary=resp_str,
            ))
            # Timeline bucket (1s)
            bucket = int(time.time())
            bkt = self._timeline_buckets[sid]
            if bucket not in bkt:
                bkt[bucket] = {"sum_rtt": 0.0, "count": 0, "exceptions": 0}
            bkt[bucket]["sum_rtt"] += rtt_ms
            bkt[bucket]["count"] += 1
            if status == "exception":
                bkt[bucket]["exceptions"] += 1
            # Keep only last 180 buckets (3 min)
            old_keys = [k for k in bkt if k < bucket - 180]
            for k in old_keys:
                del bkt[k]

    def get_stats(
        self,
        session_id: str,
        jitter_monitor: "JitterMonitor | None" = None,
        frame_store: "Any" = None,
    ) -> dict:
        sid = session_id
        if sid not in self._rtt:
            result = {
                "rtt": {"avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
                "exceptions": [],
                "heatmap": {},
                "timeline": [],
                "transactions": [],
                "req_rate": 0.0,
                "total_polls": 0,
            }
            if jitter_monitor is not None:
                result["jitter"] = jitter_monitor.stats()
            if frame_store is not None:
                result["traffic"] = {
                    **frame_store.counters(),
                    "recent": [asdict(f) for f in frame_store.get_recent(10)],
                }
            return result
        with self._lock:
            rtts = list(self._rtt[sid])
            exc_items = list(self._exc[sid].items())
            heatmap = dict(self._heatmap[sid])
            timeline_buckets = dict(self._timeline_buckets[sid])
            transactions_snapshot = list(self._transactions[sid])
            total_polls = self._seq[sid]

        if rtts:
            sorted_rtts = sorted(rtts)
            n = len(sorted_rtts)
            avg = sum(sorted_rtts) / n
            p50 = self._percentile(sorted_rtts, 50)
            p95 = self._percentile(sorted_rtts, 95)
            p99 = self._percentile(sorted_rtts, 99)
        else:
            avg = p50 = p95 = p99 = 0.0
        exc_list = [
            {"fc": k[0], "addr": k[1], "code": k[2], "count": v}
            for k, v in sorted(exc_items, key=lambda x: -x[1])
        ]
        timeline = []
        for ts in sorted(timeline_buckets):
            bkt = timeline_buckets[ts]
            timeline.append({
                "ts": ts,
                "avg_rtt": round(bkt["sum_rtt"] / bkt["count"], 2) if bkt["count"] else 0,
                "count": bkt["count"],
                "exceptions": bkt["exceptions"],
            })
        txns = [
            {
                "seq": t.seq, "ts": t.ts, "session_id": t.session_id,
                "fc": t.fc, "addr": t.addr,
                "rtt_ms": round(t.rtt_ms, 2), "status": t.status,
                "exception_code": t.exception_code, "response_summary": t.response_summary,
            }
            for t in reversed(transactions_snapshot)
        ]
        recent = [t for t in transactions_snapshot if time.time() - t.ts <= 10]
        req_rate = round(len(recent) / 10.0, 2)
        result = {
            "rtt": {"avg": round(avg, 2), "p50": round(p50, 2), "p95": round(p95, 2), "p99": round(p99, 2)},
            "exceptions": exc_list,
            "heatmap": heatmap,
            "timeline": timeline,
            "transactions": txns,
            "req_rate": req_rate,
            "total_polls": total_polls,
        }
        if jitter_monitor is not None:
            result["jitter"] = jitter_monitor.stats()
        if frame_store is not None:
            result["traffic"] = {
                **frame_store.counters(),
                "recent": [asdict(f) for f in frame_store.get_recent(10)],
            }
        return result

    def clear(self, session_id: str):
        with self._lock:
            for d in (self._rtt, self._exc, self._heatmap, self._transactions,
                      self._seq, self._timeline_buckets):
                d.pop(session_id, None)


# ── JitterMonitor ─────────────────────────────────────────────────────────────

@dataclass
class JitterMonitor:
    """
    Tracks poll-start-to-poll-start interval deviation from a configured target.
    Call tick() at the top of every poll cycle, before any I/O.
    """
    target_interval_ms: float
    window: int = 300

    def __post_init__(self):
        self._lock = threading.Lock()
        self._intervals: deque[float] = deque(maxlen=self.window)
        self._last_ns: int | None = None

    def tick(self) -> None:
        now = time.time_ns()
        with self._lock:
            if self._last_ns is not None:
                self._intervals.append((now - self._last_ns) / 1_000_000)
            self._last_ns = now

    def stats(self) -> dict:
        with self._lock:
            iv = list(self._intervals)
        n = len(iv)
        if n == 0:
            return {"target_ms": self.target_interval_ms, "samples": 0}
        if n == 1:
            dev = abs(iv[0] - self.target_interval_ms)
            return {
                "target_ms":      self.target_interval_ms,
                "samples":        1,
                "mean_ms":        round(iv[0], 3),
                "std_dev_ms":     0.0,
                "min_ms":         round(iv[0], 3),
                "max_ms":         round(iv[0], 3),
                "p50_jitter_ms":  round(dev, 3),
                "p95_jitter_ms":  round(dev, 3),
                "timeline_ms":    [round(iv[0], 3)],
            }
        devs = sorted(abs(x - self.target_interval_ms) for x in iv)
        return {
            "target_ms":      self.target_interval_ms,
            "samples":        n,
            "mean_ms":        round(statistics.mean(iv), 3),
            "std_dev_ms":     round(statistics.stdev(iv), 3),
            "min_ms":         round(min(iv), 3),
            "max_ms":         round(max(iv), 3),
            "p50_jitter_ms":  round(devs[n // 2], 3),
            "p95_jitter_ms":  round(statistics.quantiles(devs, n=20)[18], 3),
            "timeline_ms":    [round(x, 3) for x in iv[-60:]],
        }


# Singleton
diagnostics_engine = DiagnosticsEngine()
