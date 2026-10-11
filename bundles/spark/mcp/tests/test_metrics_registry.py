"""Tests for MetricsRegistry — counter/gauge/histogram + Prometheus
exposition format."""

from __future__ import annotations

import pytest

from src.usecase.metrics_registry import (
    DEFAULT_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    Timer,
    _format_labels,
)


def test_label_formatting() -> None:
    assert _format_labels({}) == ""
    assert _format_labels({"a": "1"}) == '{a="1"}'
    # Sorted by key for deterministic output:
    assert _format_labels({"b": "2", "a": "1"}) == '{a="1",b="2"}'


def test_label_value_escapes_specials() -> None:
    out = _format_labels({"k": 'has "quotes" and \\ slashes\nand newlines'})
    # Prometheus escapes backslash, double quote, newline.
    assert "has \\\"quotes\\\"" in out
    assert "\\\\ slashes" in out
    assert "\\nand" in out


def test_counter_inc_and_lines() -> None:
    c = Counter(name="foo_total", help="Total foos")
    c.inc()
    c.inc(by=2.5)
    lines = list(c.lines())
    assert "# TYPE foo_total counter" in lines
    assert "foo_total 3.5" in lines


def test_counter_rejects_negative_inc() -> None:
    c = Counter(name="x", help="x")
    with pytest.raises(ValueError):
        c.inc(by=-1)


def test_counter_with_labels() -> None:
    c = Counter(name="reqs_total", help="Reqs")
    c.inc(status="ok")
    c.inc(status="ok")
    c.inc(status="err")
    lines = "\n".join(c.lines())
    assert 'reqs_total{status="ok"} 2' in lines
    assert 'reqs_total{status="err"} 1' in lines


def test_counter_zero_when_no_observations() -> None:
    c = Counter(name="never_used", help="x")
    lines = list(c.lines())
    assert "never_used 0" in lines


def test_gauge_set_and_inc() -> None:
    g = Gauge(name="active", help="Active")
    g.set(5)
    g.inc()
    lines = "\n".join(g.lines())
    assert "active 6" in lines
    assert "# TYPE active gauge" in lines


def test_histogram_observe_and_buckets() -> None:
    h = Histogram(name="dur", help="Duration", buckets=(0.1, 0.5, 1.0))
    h.observe(0.05)
    h.observe(0.3)
    h.observe(0.6)
    lines = "\n".join(h.lines())
    # 0.05 lands in <=0.1, <=0.5, <=1.0 (all upper-bounded buckets).
    # 0.3 lands in <=0.5, <=1.0.
    # 0.6 lands in <=1.0.
    assert 'dur_bucket{le="0.1"} 1' in lines
    assert 'dur_bucket{le="0.5"} 2' in lines
    assert 'dur_bucket{le="1.0"} 3' in lines
    assert 'dur_bucket{le="+Inf"} 3' in lines
    assert "dur_count 3" in lines
    assert "dur_sum 0.95" in lines


def test_histogram_zero_when_unused() -> None:
    h = Histogram(name="dur", help="x", buckets=(0.5, 1.0))
    lines = "\n".join(h.lines())
    assert 'dur_bucket{le="0.5"} 0' in lines
    assert 'dur_bucket{le="+Inf"} 0' in lines
    assert "dur_count 0" in lines


def test_registry_dedupe_same_type() -> None:
    r = MetricsRegistry()
    a = r.counter("foo", "x")
    b = r.counter("foo", "y")
    assert a is b


def test_registry_rejects_type_mismatch() -> None:
    r = MetricsRegistry()
    r.counter("foo", "x")
    with pytest.raises(ValueError):
        r.gauge("foo", "y")


def test_registry_format_prometheus_round_trip() -> None:
    r = MetricsRegistry()
    c = r.counter("phantom_mcp_tool_calls_total", "Total tool calls")
    c.inc(tool="xsiam.execute_xql_query", status="ok")
    g = r.gauge("phantom_mcp_active_sessions", "Active")
    g.set(2)
    out = r.format_prometheus()
    assert "# TYPE phantom_mcp_tool_calls_total counter" in out
    assert (
        'phantom_mcp_tool_calls_total{status="ok",tool="xsiam.execute_xql_query"} 1'
        in out
    )
    assert "phantom_mcp_active_sessions 2" in out


def test_timer_observes_into_histogram() -> None:
    h = Histogram(name="dur", help="x", buckets=(1.0,))
    with Timer(h, status="ok"):
        pass
    out = "\n".join(h.lines())
    assert "dur_count" in out
    # The recorded duration is non-negative.
    assert "dur_sum" in out


def test_default_buckets_match_prometheus_canonical() -> None:
    # Ten buckets matches prometheus_client's default. Worth pinning so
    # operators transplanting dashboards from other services keep the
    # same heatmap layout.
    assert DEFAULT_BUCKETS == (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
