"""Built-in event profiles for `generate_events`.

A profile builds synthetic Windows events (structured `winevent.Event` objects; the connector renders them to Event XML
and delivers them over WEC). Adding a profile means adding a module here and one line to PROFILES.

Each profile module provides:

  NAME              the value of generate_events(profile=...)
  DESCRIPTION       one line for the tool's messages
  EXPECTED_DATASET  the dataset the events are meant to land in
  SCENARIOS         mapping scenario name -> builder function (new scenarios plug in here)
  build_events(scenario, count, *, directory, now, spread_seconds, start_offset_minutes, seed=None) -> list[Event]
                    (raises ValueError)
"""
from __future__ import annotations

from types import ModuleType

from . import windows

PROFILES: dict[str, ModuleType] = {m.NAME: m for m in (windows,)}


def get(name: str) -> ModuleType:
    """The profile called `name` (case-insensitive). Raises ValueError listing the choices."""
    profile = PROFILES.get((name or "").strip().lower())
    if profile is None:
        raise ValueError(f"unknown profile {name!r}; choose one of {', '.join(sorted(PROFILES))}")
    return profile
