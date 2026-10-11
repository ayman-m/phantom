"""xsiam_alerts_list: paging offsets are not timestamps, and recent alerts are asked for with since_minutes.

A model that wants recent alerts must not pass an epoch as search_from: the API answers a timestamp-shaped offset with an
opaque 500. The tool has a time filter (`since_minutes`) and rejects timestamp-shaped offsets with a message that says
what to pass instead."""

from __future__ import annotations

import asyncio
import time

import src.connector as c


class _Fetcher:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    async def send_request(self, path, data=None, **kw):
        self.bodies.append(data)
        return {"reply": {"alerts": [{"alert_id": 1, "name": "Suspicious port scan", "events": [{"x": "y" * 1000}] * 50, "description": "d" * 900,
                                       "agent_os_type": "NO_HOST"}], "total_count": 1}}


def _run(**kw):
    fetcher = _Fetcher()
    orig = c._get_fetcher
    c._get_fetcher = lambda: fetcher
    try:
        return asyncio.run(c.xsiam_alerts_list(**kw)), fetcher
    finally:
        c._get_fetcher = orig


def test_timestamp_as_offset_is_rejected_with_a_helpful_message() -> None:
    out, fetcher = _run(search_from=1728188341000)
    assert out["ok"] is False
    assert "since_minutes" in out["error"] and "ROW OFFSETS" in out["error"]
    assert fetcher.bodies == []  # nothing reached the API


def test_page_larger_than_100_rows_is_rejected() -> None:
    out, _ = _run(search_from=0, search_to=500)
    assert out["ok"] is False


def test_since_minutes_becomes_a_creation_time_filter_and_newest_first() -> None:
    before = int(time.time() * 1000)
    out, fetcher = _run(since_minutes=30, alert_source=["MAGNIFIER", "ANALYTICS_BIOC"])
    assert out["ok"] is True and out["returned"] == 1
    req = fetcher.bodies[0]["request_data"]
    time_filter = next(f for f in req["filters"] if f["field"] == "creation_time")
    assert time_filter["operator"] == "gte"
    assert before - 30 * 60_000 - 2000 <= time_filter["value"] <= before - 30 * 60_000 + 5000
    assert {"field": "alert_source", "operator": "in", "value": ["MAGNIFIER", "ANALYTICS_BIOC"]} in req["filters"]
    assert req["sort"] == {"field": "creation_time", "keyword": "desc"}


def test_non_positive_since_minutes_is_rejected() -> None:
    out, _ = _run(since_minutes=0)
    assert out["ok"] is False


def test_alerts_are_summarised_without_their_raw_events() -> None:
    out, _ = _run(since_minutes=10)
    alert = out["alerts"][0]
    assert alert["name"] == "Suspicious port scan" and alert["event_count"] == 50
    assert "events" not in alert and "agent_os_type" not in alert
    assert len(alert["description"]) == 400
    assert len(str(out)) < 3000


def test_xql_syntax_errors_come_back_with_a_hint() -> None:
    assert "FIRST stage" in c._xql_hint("Server error 500: bad query syntax")
    assert "too broad" in c._xql_hint("Request timeout: ")
    assert c._xql_hint("something else") == ""
