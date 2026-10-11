"""Shared timestamp helper for sqlite-backed stores.

The audit log + session store have always used microsecond-precision
ISO8601 strings so that ORDER BY created_at gives a deterministic
total order even for events recorded in the same wall-clock second.
This util factors the same format out for the newer stores
(api_keys, settings, notifications, media, telemetry, observability)
so they don't duplicate the strftime + fractional-seconds dance.

Format: "YYYY-MM-DDTHH:MM:SS.uuuuuuZ" (UTC, microseconds, Z suffix).
"""

from __future__ import annotations

import time


def utc_now_micros() -> str:
    """Return a microsecond-precision ISO8601 UTC timestamp."""
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime(now)) + (
        f"{int((now % 1) * 1_000_000):06d}Z"
    )
