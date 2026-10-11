"""ippools: the home and abroad address pools. No network: the data was verified with Cortex's `iploc` when generated.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import ipaddress
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.profiles import ippools  # noqa: E402


def net(pool_range):
    return ipaddress.ip_network(pool_range.cidr)


def test_the_pools_are_disjoint_public_slash_24s():
    ranges = ippools.HOME + ippools.ABROAD
    assert (len(ippools.HOME), len(ippools.ABROAD)) == (24, 18)
    assert len({r.cidr for r in ranges}) == len(ranges)
    for r in ranges:
        assert net(r).prefixlen == 24 and net(r).is_global, r.cidr
    assert not any(a.overlaps(b) for i, a in enumerate(map(net, ranges)) for b in map(net, ranges[i + 1:]))


def test_home_is_saudi_across_four_isps_and_abroad_never_is():
    assert {r.country for r in ippools.HOME} == {"Saudi Arabia"}
    assert {r.asn for r in ippools.HOME} == {25019, 35819, 39891, 43766}
    assert "Saudi Arabia" not in {r.country for r in ippools.ABROAD}
    assert {ippools.HOME[i].asn for i in range(4)} == {25019, 35819, 39891, 43766}  # consecutive users differ


def test_home_for_is_stable_in_range_and_gives_each_early_user_a_different_address():
    for index in range(60):
        ip, pool_range = ippools.home_for(index)
        assert ippools.home_for(index) == (ip, pool_range) and pool_range in ippools.HOME
        assert ipaddress.ip_address(ip) in net(pool_range)
    assert len({ippools.home_for(i)[0] for i in range(24)}) == 24


def test_abroad_pick_is_deterministic_per_rng_state_and_stays_abroad():
    assert ippools.abroad_pick(random.Random(5)) == ippools.abroad_pick(random.Random(5))
    seen = set()
    for seed in range(60):
        ip, pool_range = ippools.abroad_pick(random.Random(seed))
        assert pool_range in ippools.ABROAD and ipaddress.ip_address(ip) in net(pool_range)
        seen.add(pool_range)
    assert len(seen) > 10


def test_range_of_finds_pool_addresses_and_nothing_else():
    ip, pool_range = ippools.home_for(3)
    assert ippools.range_of(ip) == pool_range
    assert ippools.range_of(ippools.host_in(ippools.ABROAD[0], 200)) == ippools.ABROAD[0]
    for other in ("203.0.113.99", "198.51.100.7", "10.1.2.3", "not an ip", "", "2001:db8::1"):
        assert ippools.range_of(other) is None


def test_index_of_uses_the_pool_number_else_a_stable_derived_one():
    assert ippools.index_of("a@x", {"a@x": 4}) == 4
    derived = ippools.index_of("stranger@x", {})
    assert derived == ippools.index_of("stranger@x", {"a@x": 4}) and 0 <= derived < len(ippools.HOME)


# -- stable Okta user ids (0.3.1) ----------------------------------------------------------------------------------

def test_okta_user_id_is_a_pure_function_of_the_login():
    import re
    from datetime import datetime, timezone

    from src.profiles import okta

    a = okta.user_id("noura.alharbi@phantom-lab.example")
    assert re.fullmatch(r"00u[A-Za-z0-9]{17}", a)
    assert a == okta.user_id("Noura.Alharbi@Phantom-Lab.example ")           # case and padding do not matter
    assert a != okta.user_id("khalid.alotaibi@phantom-lab.example")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    def ids(scenario, seed, **kw):
        events = okta.build_events(scenario, 24, domain="phantom-lab.example", now=now, spread_seconds=600,
                                   start_offset_minutes=0, target_user=kw.get("target_user"), source_ip=None, seed=seed)
        out: dict[str, set[str]] = {}
        for e in events:
            out.setdefault(e["actor"]["alternateId"], set()).add(e["actor"]["id"])
        return out

    # the same user carries one id across events AND across runs with different seeds
    one = ids("benign_logins", seed=1)
    two = ids("benign_logins", seed=2)
    assert all(len(v) == 1 for v in one.values())
    assert {k: next(iter(v)) for k, v in one.items()} == {k: next(iter(v)) for k, v in two.items()}
    assert one["noura.alharbi@phantom-lab.example"] == {a}
    # a named victim in an attack scenario is the same identity as the baseline user
    spray = ids("failed_then_success", seed=3, target_user="noura.alharbi")
    assert spray["noura.alharbi@phantom-lab.example"] == {a}
