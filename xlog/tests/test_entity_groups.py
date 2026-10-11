"""Fields that belong to one simulated machine must vary together.

Without entity groups every field resolves independently, so an
observables_dict of {shost: [a, b], src: [ip1, ip2]} emits the CROSS-PRODUCT —
host `a` gets ip1 on one event and ip2 on the next. Entity groups express
"these fields describe the same endpoint".

Cortex analytics are
entity-PROFILING detectors: they learn what is normal for an endpoint and alert
on deviation, and the Analytics Engine's activation prerequisite is network logs
from >=30 ENDPOINTS over >=2 weeks. Uncorrelated output leaves hosts with no
stable identity — one `shost` claiming tens of thousands of distinct `src`
values — so only pattern-matching BIOCs fire, not the profiling engine. One
worker per endpoint is capped by WORKERS_NUMBER at 25 install-wide, so it can
never present 30 endpoints while any other feed runs.
"""
from __future__ import annotations

import collections

from app.dynamic_schema import ENTITY_GROUP_KEY, generate_records_with_override

FIELDS = [
    {"name": "shost", "type": "host"},
    {"name": "src", "type": "ipv4"},
    {"name": "suser", "type": "user"},
    {"name": "app", "type": "string"},
]
ENTITIES = [
    {"shost": "wks-001", "src": "10.20.5.1", "suser": "ahmed"},
    {"shost": "wks-002", "src": "10.20.5.2", "suser": "sameh"},
    {"shost": "wks-003", "src": "10.20.5.3", "suser": "mohamed"},
]


def _by_host(records, field):
    out = collections.defaultdict(set)
    for r in records:
        out[r["shost"]].add(r[field])
    return out


def test_entity_fields_stay_bound_together():
    """One draw per record fixes shost + src + suser as a unit."""
    recs = generate_records_with_override(
        300, FIELDS, observable_overrides={"app": ["HTTP", "HTTPS"], ENTITY_GROUP_KEY: ENTITIES}
    )
    expected = {e["shost"]: (e["src"], e["suser"]) for e in ENTITIES}
    for host, ips in _by_host(recs, "src").items():
        assert ips == {expected[host][0]}, f"{host} drew {len(ips)} IPs; entity binding broken"
    for host, users in _by_host(recs, "suser").items():
        assert users == {expected[host][1]}, f"{host} drew {len(users)} users"


def test_non_entity_fields_still_vary_independently():
    """The grouping must not accidentally pin everything else."""
    recs = generate_records_with_override(
        300, FIELDS, observable_overrides={"app": ["HTTP", "HTTPS", "DNS"], ENTITY_GROUP_KEY: ENTITIES}
    )
    assert {r["app"] for r in recs} == {"HTTP", "HTTPS", "DNS"}


def test_reserved_key_never_reaches_the_wire():
    """__entities__ is control data, not a vendor field."""
    recs = generate_records_with_override(
        10, FIELDS, observable_overrides={ENTITY_GROUP_KEY: ENTITIES}
    )
    assert all(ENTITY_GROUP_KEY not in r for r in recs)


def test_without_entities_the_cross_product_still_happens():
    """Pins the OLD behaviour, so a future refactor cannot silently reintroduce
    it for callers that pass parallel lists instead of entity groups."""
    recs = generate_records_with_override(
        300,
        FIELDS,
        observable_overrides={
            "shost": [e["shost"] for e in ENTITIES],
            "src": [e["src"] for e in ENTITIES],
        },
    )
    assert any(len(ips) > 1 for ips in _by_host(recs, "src").values())


def test_malformed_entity_pool_is_ignored_not_fatal():
    """A bad __entities__ must not abort a generation run."""
    for bad in ("not-a-list", 42, {"shost": "x"}):
        recs = generate_records_with_override(
            5, FIELDS, observable_overrides={"app": ["HTTP"], ENTITY_GROUP_KEY: bad}
        )
        assert len(recs) == 5
        assert all(ENTITY_GROUP_KEY not in r for r in recs)
