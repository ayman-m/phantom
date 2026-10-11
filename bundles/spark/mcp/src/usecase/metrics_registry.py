"""MetricsRegistry — in-process Prometheus-format metric collector.

Implements the metrics half of the spec's `observability` capability
(manifest.observability.metrics[]). The registry is a plain dict of
name → typed metric (Counter / Gauge / Histogram), exposed as a
Prometheus 0.0.4 text-exposition string via `format_prometheus()`.

# Why roll our own vs prometheus_client

The official `prometheus_client` library is ~1MB of code (most of which
we don't use: pushgateway, multiprocess support, asgi middleware). A
SOC simulation agent cycles through five counters and a request
histogram — the surface fits in 100 lines without a dep. We pay the
maintenance cost of a tiny registry to keep the image lean.

# Why in-process (not external collector)

Single binary, single trust boundary, single readback URL. The agent
operator scrapes /api/v1/metrics with their existing Prometheus stack
or just curls it during a postmortem. No OTel collector to operate.

# What's exported

  Counter  — monotonic counter (inc only), labels supported
  Gauge    — settable scalar, labels supported
  Histogram — bucketed observe(), exports _bucket / _sum / _count

  The manifest's metric names map 1:1 to Counter instances. New
  metrics declared by future bundle versions just need to be added
  to the registry at boot.

# Future tightening

  - OpenTelemetry traces — stub for now; observability.events from the
    manifest could be emitted as OTel events when an OTel SDK lands.
  - Per-route request histogram — hook a starlette middleware to
    observe(http_request_duration_seconds, t).

  These are deferred; the metric counters alone unblock dashboards.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger("Phantom MCP")


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = []
    for k in sorted(labels.keys()):
        # Prometheus label values must escape backslash, quote, newline.
        v = (
            str(labels[k])
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )
        pairs.append(f'{k}="{v}"')
    return "{" + ",".join(pairs) + "}"


@dataclass
class Counter:
    name: str
    help: str
    _values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, by: float = 1.0, **labels: str) -> None:
        if by < 0:
            raise ValueError("Counter.inc requires non-negative `by`")
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + float(by)

    def lines(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        with self._lock:
            items = list(self._values.items())
        if not items:
            yield f"{self.name} 0"
            return
        for key, val in items:
            label_str = _format_labels(dict(key))
            yield f"{self.name}{label_str} {val}"


@dataclass
class Gauge:
    name: str
    help: str
    _values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, value: float, **labels: str) -> None:
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            self._values[key] = float(value)

    def inc(self, by: float = 1.0, **labels: str) -> None:
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + float(by)

    def lines(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} gauge"
        with self._lock:
            items = list(self._values.items())
        if not items:
            yield f"{self.name} 0"
            return
        for key, val in items:
            label_str = _format_labels(dict(key))
            yield f"{self.name}{label_str} {val}"


# Default Prometheus latency-histogram buckets (seconds). Matches the
# canonical `prometheus_client` defaults so existing dashboards
# transplanted from other services keep their bucket layout.
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class Histogram:
    name: str
    help: str
    buckets: tuple[float, ...] = DEFAULT_BUCKETS
    _data: dict[tuple[tuple[str, str], ...], dict[str, list[int] | float]] = field(
        default_factory=dict
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(sorted((k, str(v)) for k, v in labels.items()))
        with self._lock:
            d = self._data.get(key)
            if d is None:
                d = {"counts": [0] * len(self.buckets), "sum": 0.0, "count": 0}
                self._data[key] = d
            for i, b in enumerate(self.buckets):
                if value <= b:
                    d["counts"][i] += 1  # type: ignore[index]
            d["sum"] = float(d["sum"]) + float(value)        # type: ignore[index]
            d["count"] = int(d["count"]) + 1                  # type: ignore[index]

    def lines(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        with self._lock:
            items = list(self._data.items())
        if not items:
            for b in self.buckets:
                yield f'{self.name}_bucket{{le="{b}"}} 0'
            yield f'{self.name}_bucket{{le="+Inf"}} 0'
            yield f"{self.name}_sum 0"
            yield f"{self.name}_count 0"
            return
        for key, d in items:
            label_dict = dict(key)
            for i, b in enumerate(self.buckets):
                merged = {**label_dict, "le": str(b)}
                yield f"{self.name}_bucket{_format_labels(merged)} {d['counts'][i]}"  # type: ignore[index]
            merged_inf = {**label_dict, "le": "+Inf"}
            yield f"{self.name}_bucket{_format_labels(merged_inf)} {d['count']}"
            yield f"{self.name}_sum{_format_labels(label_dict)} {d['sum']}"
            yield f"{self.name}_count{_format_labels(label_dict)} {d['count']}"


class MetricsRegistry:
    """Process-wide registry. main.py constructs one and pre-declares the
    counters from manifest.observability.metrics[]; tools and the
    HTTP middleware look the registry up via the singleton accessor."""

    def __init__(self) -> None:
        self._items: dict[str, Counter | Gauge | Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, help: str = "") -> Counter:
        with self._lock:
            existing = self._items.get(name)
            if isinstance(existing, Counter):
                return existing
            if existing is not None:
                raise ValueError(
                    f"metric {name!r} already registered as a different type"
                )
            c = Counter(name=name, help=help or name)
            self._items[name] = c
            return c

    def gauge(self, name: str, help: str = "") -> Gauge:
        with self._lock:
            existing = self._items.get(name)
            if isinstance(existing, Gauge):
                return existing
            if existing is not None:
                raise ValueError(
                    f"metric {name!r} already registered as a different type"
                )
            g = Gauge(name=name, help=help or name)
            self._items[name] = g
            return g

    def histogram(
        self, name: str, help: str = "",
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> Histogram:
        with self._lock:
            existing = self._items.get(name)
            if isinstance(existing, Histogram):
                return existing
            if existing is not None:
                raise ValueError(
                    f"metric {name!r} already registered as a different type"
                )
            h = Histogram(name=name, help=help or name, buckets=buckets)
            self._items[name] = h
            return h

    def get(self, name: str) -> Counter | Gauge | Histogram | None:
        with self._lock:
            return self._items.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._items.keys())

    def format_prometheus(self) -> str:
        """Render the full registry as Prometheus 0.0.4 text exposition."""
        out: list[str] = []
        with self._lock:
            items = list(self._items.values())
        for item in items:
            out.extend(item.lines())
            out.append("")  # blank line between metric families
        return "\n".join(out) + "\n"


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor + timer helper
# ─────────────────────────────────────────────────────────────────

_metrics: MetricsRegistry | None = None


def set_metrics_registry(reg: MetricsRegistry | None) -> None:
    global _metrics
    _metrics = reg


def metrics_registry() -> MetricsRegistry | None:
    return _metrics


class Timer:
    """Context manager for histogram observation:
       with Timer(hist, status="ok"): ...
    """

    def __init__(self, histogram: Histogram, **labels: str) -> None:
        self._h = histogram
        self._labels = labels
        self._t0: float = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._h.observe(time.monotonic() - self._t0, **self._labels)
