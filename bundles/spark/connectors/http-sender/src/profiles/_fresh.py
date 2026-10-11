"""Shared helpers of the cloud profiles (`aws_cloudtrail`, `gcp_audit`, `azure_ad_audit`).

Those profiles replay one-shot detection recipes, and an analytics detector that profiles "first time seen" needs
every replay to look like a first-time actor. So every name, id, key and account they emit is generated per call from
the profile's `random.Random` (seeded only by tests), never hard-coded.

The `benign_activity` scenarios are the opposite: a baseline needs the SAME actors on every call. Their identities come
from `person` and `stable` / `stable_guid` below, which are pure functions of an index or a label (no randomness, no
clock), so a user keeps one name, one id, one key and one home address for as long as the code does not change.
"""
from __future__ import annotations

import hashlib
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

_FIRST = ("noura", "khalid", "abdullah", "sara", "faisal", "reem", "omar", "huda", "yousef", "layla", "tariq", "dana")
_LAST = ("alharbi", "alotaibi", "alzahrani", "almutairi", "alqahtani", "aldosari", "alshehri", "alghamdi",
         "alharthi", "almalki", "alsubaie", "alanazi")


def hexs(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def rid(rng: random.Random, n: int, alphabet: str = string.ascii_uppercase + string.digits) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def guid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def handle(rng: random.Random) -> str:
    """A fresh person's login name, e.g. `noura.alharbi.3fa91c` (6 hex characters make a repeat practically impossible)."""
    return f"{rng.choice(_FIRST)}.{rng.choice(_LAST)}.{hexs(rng, 6)}"


def bare_name(login: str | None) -> str | None:
    """A caller-supplied principal name reduced to its bare, lowercase form (`DOMAIN\\user` collapses identity in Cortex)."""
    if not login or not login.strip():
        return None
    return login.strip().rsplit("\\", 1)[-1].lower()


def run_recipe(steps: Callable[[int], list[dict[str, Any]]], count: int, times: list[datetime],
               stamp: Callable[[dict[str, Any], datetime], None]) -> list[dict[str, Any]]:
    """`count` events: repetition 0, 1, ... of `steps(k)` until there are enough, cut to `count`, then each stamped
    with its time (ascending, so a recipe's steps keep their order)."""
    out: list[dict[str, Any]] = []
    k = 0
    while len(out) < count:
        batch = steps(k)
        if not batch:
            raise ValueError("a scenario recipe produced no events")
        out.extend(batch)
        k += 1
    out = out[:count]
    for event, when in zip(out, times):
        stamp(event, when)
    return out


# -- stable identities (benign_activity) --------------------------------------------------------------------------------

UPPER_DIGITS = string.ascii_uppercase + string.digits


def person(index: int) -> tuple[str, str]:
    """The `index`-th persona of the shared pool: the same twelve people the okta profile logs in, so one person has one
    name and (with `ippools.home_for(index)`) one home address in every profile."""
    return _FIRST[index % len(_FIRST)], _LAST[index % len(_LAST)]


def stable(label: str, n: int, alphabet: str = "0123456789abcdef") -> str:
    """`n` characters of `alphabet` that are a pure function of `label` (a sha256 stream): the same identity gets the same
    id on every call, which is what lets a baseline build history on it."""
    out = ""
    block = 0
    while len(out) < n:
        digest = hashlib.sha256(f"{label}|{block}".encode("utf-8")).digest()
        out += "".join(alphabet[b % len(alphabet)] for b in digest)
        block += 1
    return out[:n]


def stable_guid(label: str) -> str:
    """A GUID that is a pure function of `label`."""
    return str(uuid.UUID(bytes=hashlib.sha256(label.encode("utf-8")).digest()[:16], version=4))


def jittered_times(rng: random.Random, end: datetime, count: int, spread_seconds: int) -> list[datetime]:
    """`count` ascending timestamps across the window that ends at `end`: the first at the window's start and the last at
    `end`, the others at random moments between, so benign traffic is not a metronome. Never after `end`."""
    if count <= 1 or spread_seconds <= 0:
        return [end] * max(count, 0)
    width = float(spread_seconds)
    inner = sorted(rng.uniform(0.0, width) for _ in range(count - 2))
    return [end - timedelta(seconds=width - offset) for offset in [0.0, *inner, width]]


def weighted(rng: random.Random, table: tuple[tuple[Any, int], ...]) -> Any:
    """One key of `table` ((key, weight), ...) at random."""
    return rng.choices([k for k, _ in table], [w for _, w in table])[0]
