"""The connector-runtime view over an organization: account roles, hosts, fresh-identity ranges, the test hook."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from usecase import organization_model as om

REPO = Path(__file__).resolve().parents[4]
BUNDLE = REPO / "bundles" / "spark"


@pytest.fixture(scope="module")
def ov():
    runtime = REPO / "phantom-connector-runtime"
    sys.path.insert(0, str(runtime))
    try:
        from runtime import organization_view
        yield organization_view
    finally:
        sys.path.remove(str(runtime))
        for m in [m for m in sys.modules if m == "runtime" or m.startswith("runtime.")]:
            del sys.modules[m]


@pytest.fixture()
def doc(monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()
    return om.parse_document((BUNDLE / "organization" / "phantom-lab.yaml").read_text(encoding="utf-8"))


@pytest.fixture()
def view(ov, doc):
    return ov.OrganizationView(doc)


def test_identity_basics(view):
    assert (view.dns, view.netbios, view.email_domain) == ("phantom.lab", "PHANTOM", "phantom.lab")
    assert view.sid_base == "S-1-5-21-3623811015-3361044348-30300820"
    assert view.sid(1105) == "S-1-5-21-3623811015-3361044348-30300820-1105"
    assert view.utc_offset_hours == 3 and view.work_start_hour == 8 and view.work_end_hour == 17


def test_account_order_and_roles(view):
    roles = [a.role for a in view.accounts]
    # staff accounts first, then admins, then services: the order the Windows profiles draw from
    assert roles == sorted(roles, key=["staff", "admin", "service"].index)
    admins = {a.login for a in view.accounts_by_role("admin")}
    assert {"adm.ialkhalifa", "adm.jalsaif"} <= admins
    assert "adm.breakglass" not in admins                      # never part of normal traffic
    assert "ralsayegh" not in {a.login for a in view.accounts_by_role("staff")}   # the leaver's account is disabled
    assert "ralsayegh" in {a.login for a in view.accounts_by_role("staff", logs_on=False)}
    assert {a.login for a in view.accounts_by_role("service")} >= {"svc-sql", "svc-backup", "svc-web", "svc-app"}


def test_lookups(view):
    assert view.account("ADM.IALKHALIFA").person == "ialkhalifa"
    assert view.person("nalharbi")["workstation"] == "PHWS-001"
    ws = view.workstation_of("adm.ialkhalifa")
    assert ws["name"] == "PHWS-023" and ws["ip"] == "10.20.16.42"
    assert view.workstation_of("svc-sql")["name"] == "PHSRV-SQL01"
    assert view.host("phws-001.phantom.lab")["ip"] == "10.20.16.20"
    assert view.fqdn(view.host("PHDC01")) == "PHDC01.phantom.lab"
    assert [p["login"] for p in view.people_with_flag("vip")] == ["falqarni", "malessa"]


def test_fresh_identity_ranges(view):
    assert view.fresh_host_prefix() == "PHWS-"
    lo, hi = view.fresh_ip_range()
    import ipaddress
    assert str(ipaddress.ip_address(lo)) == "10.20.100.0" and str(ipaddress.ip_address(hi)) == "10.20.199.255"
    assert view.is_internal("10.20.16.20") and view.is_internal("10.20.150.9") and not view.is_internal("8.8.8.8")


def test_missing_unmanaged_network_is_an_explicit_error(ov, doc):
    doc["networks"] = [n for n in doc["networks"] if n["kind"] != "unmanaged"]
    v = ov.OrganizationView(doc)
    with pytest.raises(Exception, match="unmanaged"):
        v.fresh_ip_range()


def test_derived_sid_is_stable_and_domain_specific(ov, doc):
    doc["domain"].pop("sid")
    a, b = ov.OrganizationView(doc), ov.OrganizationView(doc)
    assert a.sid_base == b.sid_base and a.sid_base.startswith("S-1-5-21-")
    doc["domain"]["dns"] = "other.example"
    assert ov.OrganizationView(doc).sid_base != a.sid_base


def test_loader_hook_and_cache(ov, doc):
    calls = []

    def loader(pinned):
        calls.append(pinned)
        return doc

    ov.set_organization_loader(loader)
    try:
        v1, v2 = ov.get_view(), ov.get_view()
        assert v1 is v2 and calls == [None, None]
        assert ov.get_view("x").id == "phantom-lab" and calls[-1] == "x"
    finally:
        ov.set_organization_loader(None)
