"""Same relative-time forms as http-sender, so one skill text works on both Windows routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.connector import _parse_time


@pytest.mark.parametrize("text, ago", [("now", 0), ("now-120s", 120), ("now - 5m", 300), ("now-1h", 3600)])
def test_relative_forms(text, ago):
    expected = datetime.now(timezone.utc) - timedelta(seconds=ago)
    assert abs((_parse_time(text) - expected).total_seconds()) < 5


def test_absolute_time_still_parses():
    assert _parse_time("2026-10-06T04:00:00Z") == datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
