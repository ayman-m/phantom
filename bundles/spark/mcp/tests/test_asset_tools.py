"""Tests for phantom_generate_assets.

The behaviours pinned here are the ones that make the tool correct rather
than merely functional:

  - It returns the fleet it created. Without that the operator cannot
    correlate assets with log generation, which is the entire reason to
    generate assets instead of leaving the inventory empty.
  - It refuses a destination that cannot create assets, with an error that
    explains WHY rather than failing deep inside the handler. Pointing this
    at a syslog destination is the most likely operator mistake, because
    every other generation tool takes exactly that.
  - It sends ONE request per call. The endpoint allows 10 requests/hour.
  - `dry_run` builds the fleet without sending, so the hostname/IP list can
    be obtained before committing to a write.
"""

from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace
from typing import Any

import pytest

from src.usecase.builtin_components.asset_tools import (
    _build_fleet,
    phantom_generate_assets,
)


def _run(coro):
    return asyncio.run(coro)


class _Row:
    def __init__(self, type_id: str) -> None:
        self.type_id = type_id
        self.config: dict[str, Any] = {}


class _Store:
    def __init__(self, type_id: str | None) -> None:
        self._row = _Row(type_id) if type_id else None

    def get(self, _id: str):
        return self._row

    def merged_config(self, _id: str) -> dict[str, Any]:
        return {"url": "https://api-x", "api_key": "secret", "auth_id": "1"}


@pytest.fixture()
def wired(monkeypatch):
    """Wire the tool to an in-memory store + a recording dispatch_send."""
    calls: list[dict[str, Any]] = []

    async def fake_dispatch(type_id, merged, records):
        calls.append({"type_id": type_id, "merged": merged, "records": records})
        return {"sent": len(records), "failed": 0, "errors": [], "job_id": "job-1"}

    # asset_tools does `from usecase.X import ...` (no `src.` prefix), so the
    # module it binds is sys.modules["usecase.X"] — a DIFFERENT object from
    # sys.modules["src.usecase.X"]. Patching the src-prefixed copy silently
    # does nothing and the real store runs, so patch the one it imports.
    import usecase.destination_handler_registry as reg
    import usecase.log_destinations_store as store_mod

    def install(type_id: str | None):
        monkeypatch.setattr(reg, "dispatch_send", fake_dispatch, raising=False)
        monkeypatch.setattr(
            store_mod, "get_log_destination_store",
            lambda: _Store(type_id), raising=False,
        )
        # The tool imports both lazily inside the function body, so patching
        # the modules (not names in asset_tools) is what takes effect.
        return calls

    return SimpleNamespace(install=install, calls=calls)


# --------------------------------------------------------------------------
# fleet construction


def test_fleet_addresses_come_from_the_requested_subnet_in_order() -> None:
    fleet = _build_fleet(4, "10.20.30.0/24", "p", False, None, random.Random(1))
    assert [a["ip_address"] for a in fleet] == [
        "10.20.30.1", "10.20.30.2", "10.20.30.3", "10.20.30.4",
    ]


def test_fleet_is_reproducible_for_a_given_seed() -> None:
    a = _build_fleet(5, "10.0.0.0/24", "p", True, None, random.Random(42))
    b = _build_fleet(5, "10.0.0.0/24", "p", True, None, random.Random(42))
    assert [x["hostname"] for x in a] == [x["hostname"] for x in b]
    assert [x["mac_address"] for x in a] == [x["mac_address"] for x in b]


def test_fleet_truncates_rather_than_overflowing_a_small_subnet() -> None:
    """A /30 has 2 usable hosts; asking for 50 must not raise."""
    fleet = _build_fleet(50, "10.0.0.0/30", "p", False, None, random.Random(1))
    assert len(fleet) == 2


def test_every_asset_carries_last_seen() -> None:
    """`last_seen` is the one field the BYOS API actually requires."""
    fleet = _build_fleet(6, "10.0.0.0/24", "p", True, None, random.Random(3))
    assert all(isinstance(a.get("last_seen"), int) for a in fleet)


def test_vulnerabilities_use_the_shape_the_api_validates() -> None:
    """vulnerability_id required; cve_id must be a LIST (a string is a 422)."""
    fleet = _build_fleet(3, "10.0.0.0/24", "p", True, None, random.Random(5))
    vulns = [v for a in fleet for v in a.get("vulnerabilities", [])]
    assert vulns, "expected findings when with_vulnerabilities=True"
    for v in vulns:
        assert v["vulnerability_id"]
        assert isinstance(v["cve_id"], list)
        assert v["severity"] in ("low", "medium", "high", "critical")


def test_with_vulnerabilities_false_produces_a_clean_inventory() -> None:
    fleet = _build_fleet(4, "10.0.0.0/24", "p", False, None, random.Random(1))
    assert all("vulnerabilities" not in a for a in fleet)


def test_cve_ids_restricts_the_finding_pool() -> None:
    fleet = _build_fleet(6, "10.0.0.0/24", "p", True, ["CVE-2021-44228"], random.Random(2))
    seen = {c for a in fleet for v in a.get("vulnerabilities", []) for c in v["cve_id"]}
    assert seen == {"CVE-2021-44228"}


# --------------------------------------------------------------------------
# tool behaviour


def test_dry_run_builds_without_sending(wired) -> None:
    calls = wired.install("xsiam_assets")
    out = _run(phantom_generate_assets(
        destination="logdest:d1", count=3, dry_run=True, seed=1,
    ))
    assert out["dry_run"] is True
    assert out["sent"] == 0
    assert len(out["assets"]) == 3
    assert calls == [], "dry_run must not dispatch"


def test_returns_the_fleet_for_correlation(wired) -> None:
    """The hostname/IP list is what links assets to generated logs."""
    wired.install("xsiam_assets")
    out = _run(phantom_generate_assets(
        destination="logdest:d1", count=3, subnet="10.9.9.0/24", seed=1,
    ))
    assert [a["ip"] for a in out["assets"]] == ["10.9.9.1", "10.9.9.2", "10.9.9.3"]
    assert all(a["hostname"] for a in out["assets"])
    assert "observables_dict" in out["correlation_hint"]


def test_one_request_per_call_regardless_of_count(wired) -> None:
    """10 requests/hour — batching is the whole point."""
    calls = wired.install("xsiam_assets")
    _run(phantom_generate_assets(destination="logdest:d1", count=40, seed=1))
    assert len(calls) == 1
    assert len(calls[0]["records"]) == 40


def test_rejects_a_log_destination_with_an_explanation(wired) -> None:
    """Pointing this at syslog is the likeliest mistake; say why it cannot work."""
    calls = wired.install("syslog")
    out = _run(phantom_generate_assets(destination="logdest:d1", count=2))
    assert out["sent"] == 0
    assert calls == []
    err = out["errors"][0]
    assert "xsiam_assets" in err and "syslog" in err


def test_rejects_a_missing_destination(wired) -> None:
    wired.install(None)
    out = _run(phantom_generate_assets(destination="logdest:nope", count=2))
    assert out["sent"] == 0
    assert "not found" in out["errors"][0]


def test_rejects_a_raw_address(wired) -> None:
    wired.install("xsiam_assets")
    out = _run(phantom_generate_assets(destination="udp:10.0.0.1:514", count=2))
    assert out["sent"] == 0
    assert "logdest:" in out["errors"][0]


def test_invalid_subnet_is_reported_not_raised() -> None:
    out = _run(phantom_generate_assets(destination="logdest:d1", subnet="not-a-cidr"))
    assert out["sent"] == 0
    assert "invalid subnet" in out["errors"][0]


def test_dispatch_failure_is_returned_not_raised(wired, monkeypatch) -> None:
    wired.install("xsiam_assets")

    async def boom(*_a, **_k):
        raise RuntimeError("upstream exploded")

    import usecase.destination_handler_registry as reg
    monkeypatch.setattr(reg, "dispatch_send", boom, raising=False)

    out = _run(phantom_generate_assets(destination="logdest:d1", count=2, seed=1))
    assert out["sent"] == 0 and out["failed"] == 2
    assert "upstream exploded" in out["errors"][0]
    # The fleet is still returned so the caller keeps the correlation list.
    assert len(out["assets"]) == 2
