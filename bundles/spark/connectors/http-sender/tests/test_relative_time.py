"""Event times may be written relative to the connector's own clock: a model has no clock of its own.

A model asked to compute "now minus N s" itself can stamp events a day in the past, so the detector never fires;
the connector resolves the relative form against its own clock instead."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.windows_events import parse_time


def _close(value, seconds_ago):
    expected = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    assert abs((value - expected).total_seconds()) < 5


@pytest.mark.parametrize("text, ago", [("now", 0), ("now-120s", 120), ("now - 5m", 300), ("NOW-1h", 3600), ("now-90", 90)])
def test_relative_forms(text, ago):
    _close(parse_time(text), ago)


def test_absolute_times_still_parse():
    assert parse_time("2026-10-06T04:00:00Z") == datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)


def test_garbage_still_raises():
    with pytest.raises(ValueError):
        parse_time("yesterday-ish")
