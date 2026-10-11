"""Every STREAMING worker (one created with a schema_override) gets a lifetime: with no duration_seconds and no max_events it stops by itself after 900 s.

Callers often leave both unset even with the guidance in the tool text, and the worker would then stream until someone stopped it.
The tool enforces the bound; `continuous=True` is the explicit way to ask for a worker that runs until stopped."""

from __future__ import annotations

import asyncio

from src.workers import DEFAULT_WORKER_SECONDS, _bound_by_default

seen: dict = {}
SCHEMA = [{"name": "srcip", "type": "string"}]


@_bound_by_default
async def _fake(type: str, *, duration_seconds=None, max_events=None, schema_override=None):
    seen.clear()
    seen.update(duration_seconds=duration_seconds, max_events=max_events)
    return [{"worker": "w1", "status": "Running"}]


def test_a_worker_with_no_bound_gets_the_default_lifetime_and_says_so() -> None:
    out = asyncio.run(_fake("CEF", schema_override=SCHEMA))
    assert seen["duration_seconds"] == DEFAULT_WORKER_SECONDS == 900
    assert out[0]["bounded_by_default"]["duration_seconds"] == 900 and "continuous" in out[0]["bounded_by_default"]["why"]


def test_an_explicit_bound_is_left_alone() -> None:
    assert asyncio.run(_fake("CEF", schema_override=SCHEMA, duration_seconds=120)) == [{"worker": "w1", "status": "Running"}] and seen["duration_seconds"] == 120
    assert asyncio.run(_fake("CEF", schema_override=SCHEMA, max_events=50)) == [{"worker": "w1", "status": "Running"}]
    assert seen["duration_seconds"] is None and seen["max_events"] == 50


def test_continuous_is_the_explicit_way_to_run_until_stopped() -> None:
    out = asyncio.run(_fake("CEF", schema_override=SCHEMA, continuous=True))
    assert seen["duration_seconds"] is None and seen["max_events"] is None
    assert "continuous" in out[0]["warning"] and "bounded_by_default" not in out[0]


def test_the_generic_path_is_bounded_by_count_and_never_promised_a_lifetime() -> None:
    out = asyncio.run(_fake("CEF"))
    assert seen["duration_seconds"] is None and seen["max_events"] is None   # nothing injected: xlog would not accept it
    assert "bounded_by_default" not in out[0] and "count" in out[0]["bounded_by"] and "warning" not in out[0]


def test_the_generic_path_says_so_when_a_bound_is_asked_for_and_cannot_apply() -> None:
    for extra in ({"duration_seconds": 120}, {"max_events": 50}, {"continuous": True}):
        out = asyncio.run(_fake("CEF", **extra))
        assert "ignored" in out[0]["warning"], extra
