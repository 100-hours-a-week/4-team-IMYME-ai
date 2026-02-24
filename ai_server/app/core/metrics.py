"""
In-process metrics collector for ai_server.

Collects:
  - API E2E latency  (sliding window, last MAX_SAMPLES requests)
  - RPS              (timestamp deque, 1 s / 60 s windows)
  - CPU / Memory     (psutil process)
  - Network I/O      (psutil net_io_counters)

Thread-safe via threading.Lock.
Python 3.10 compatible.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

import psutil

# ─── tunables ────────────────────────────────────────────────────────────────
MAX_SAMPLES = 2_000  # latency ring buffer size
TIMESTAMP_WINDOW = 60.0  # seconds kept in the RPS deque
# ─────────────────────────────────────────────────────────────────────────────

_lock = threading.Lock()

# latency samples (ms), newest at right
_latency_deque: deque[float] = deque(maxlen=MAX_SAMPLES)

# request finish-timestamps (monotonic), kept only within TIMESTAMP_WINDOW
_ts_deque: deque[float] = deque()

# cumulative counters
_requests_total: int = 0
_status_counts: dict[str, int] = {}

# psutil handles (created once)
_process = psutil.Process()


# ─── public API ──────────────────────────────────────────────────────────────


def record_request(latency_ms: float, status_code: int) -> None:
    """Call this after each HTTP response is sent."""
    now = time.monotonic()
    status_key = str(status_code)

    with _lock:
        _latency_deque.append(latency_ms)

        # evict old timestamps
        cutoff = now - TIMESTAMP_WINDOW
        while _ts_deque and _ts_deque[0] < cutoff:
            _ts_deque.popleft()
        _ts_deque.append(now)

        global _requests_total
        _requests_total += 1
        _status_counts[status_key] = _status_counts.get(status_key, 0) + 1


def get_metrics() -> dict[str, Any]:
    """Return a point-in-time snapshot. Never raises."""
    try:
        return _build_metrics()
    except Exception:
        return {"error": "metrics collection failed"}


# ─── internals ───────────────────────────────────────────────────────────────


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Return the pct-th percentile of a pre-sorted list (0–100)."""
    n = len(sorted_data)
    if n == 0:
        return 0.0
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def _build_metrics() -> dict[str, Any]:
    now = time.monotonic()

    with _lock:
        latency_snapshot = list(_latency_deque)
        ts_snapshot = list(_ts_deque)
        requests_total = _requests_total
        status_counts = dict(_status_counts)

    # ── latency ──────────────────────────────────────────────────────────────
    if latency_snapshot:
        sorted_lat = sorted(latency_snapshot)
        avg_ms = sum(sorted_lat) / len(sorted_lat)
        p95_ms = _percentile(sorted_lat, 95)
        p99_ms = _percentile(sorted_lat, 99)
    else:
        avg_ms = p95_ms = p99_ms = 0.0
    sample_size = len(latency_snapshot)

    # ── throughput ───────────────────────────────────────────────────────────
    cutoff_1s = now - 1.0
    cutoff_60s = now - TIMESTAMP_WINDOW
    rps_1s = sum(1 for t in ts_snapshot if t >= cutoff_1s)
    requests_last_60s = sum(1 for t in ts_snapshot if t >= cutoff_60s)
    rps_60s_avg = round(requests_last_60s / TIMESTAMP_WINDOW, 4)

    # ── resource utilization ─────────────────────────────────────────────────
    try:
        cpu_pct = _process.cpu_percent(interval=None)
        mem = _process.memory_info()
        mem_rss = mem.rss
        mem_vms = mem.vms
    except Exception:
        cpu_pct = mem_rss = mem_vms = 0

    try:
        net = psutil.net_io_counters()
        net_sent = net.bytes_sent
        net_recv = net.bytes_recv
        net_pkts_sent = net.packets_sent
        net_pkts_recv = net.packets_recv
    except Exception:
        net_sent = net_recv = net_pkts_sent = net_pkts_recv = 0

    return {
        "latency": {
            "avg_ms": round(avg_ms, 3),
            "p95_ms": round(p95_ms, 3),
            "p99_ms": round(p99_ms, 3),
            "sample_size": sample_size,
        },
        "throughput": {
            "rps_1s": rps_1s,
            "rps_60s_avg": rps_60s_avg,
            "requests_total": requests_total,
            "requests_last_60s": requests_last_60s,
            "status_counts": status_counts,
        },
        "resource_utilization": {
            "cpu_percent_process": cpu_pct,
            "memory_rss_bytes": mem_rss,
            "memory_vms_bytes": mem_vms,
            "network_io_bytes_sent": net_sent,
            "network_io_bytes_recv": net_recv,
            "network_packets_sent": net_pkts_sent,
            "network_packets_recv": net_pkts_recv,
        },
    }
