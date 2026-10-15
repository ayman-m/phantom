"""The organization document: the bundled Phantom Lab seed, the validation rules, the read views and the edits."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from usecase import organization_model as om

BUNDLE = Path(__file__).resolve().parents[2]  # bundles/spark
SEED = BUNDLE / "organization" / "phantom-lab.yaml"


@pytest.fixture(autouse=True)
def _bundle_root(monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(BUNDLE))
    om.load_schema.cache_clear()


@pytest.fixture()
def doc() -> dict:
    return om.parse_document(SEED.read_text(encoding="utf-8"))


def test_seed_is_valid(doc):
    assert om.validate_document(doc) == []


def test_seed_shape(doc):
    s = om.summary(doc)
    assert s["people"] == 50
    assert s["departments"] == {"Finance": 7, "HR": 6, "Sales": 9, "Engineering": 10, "IT": 9, "Executive": 4,
                                "Operations": 5}
    assert s["service_accounts"] == 6 + 1  # six service accounts and the break-glass account
    assert s["hosts"]["workstation"] == 50
    assert s["admin_accounts"] == 7


def test_seed_personas(doc):
    p = om.personas(doc)
    assert {r["login"] for r in p["vip"]} == {"falqarni", "malessa"}
    assert [r["login"] for r in p["outlier"]] == ["aalzamil"]
    assert {r["login"] for r in p["contractors"]} == {"ext.salburaidi", "ext.ralmubarak"}
    assert [r["login"] for r in p["leavers"]] == ["ralsayegh"]
    assert [s["login"] for s in p["break_glass"]] == ["adm.breakglass"]
    assert len(p["service_accounts"]) == 6


def test_every_workstation_has_one_owner_and_an_address_in_its_network(doc):
    nets = {n["id"]: n for n in doc["networks"]}
    owners = [h["owner"] for h in doc["hosts"] if h["role"] == "workstation"]
    assert len(owners) == len(set(owners)) == 50
    for h in doc["hosts"]:
        assert om.network_contains(nets[h["network"]], h["ip"])


def test_cortex_setup_lists_ranges_and_suffix(doc):
    c = om.cortex_setup(doc)
    assert "10.20.0.0/16" in c["internal_ranges"] and "192.168.160.0/24" in c["internal_ranges"]
    assert c["domain_suffixes"] == ["phantom.lab"]
    unmanaged = next(n for n in c["networks"] if n["id"] == "ruh-unmanaged")
    assert "10.20.100.0/22" in unmanaged["cidrs"] and "10.20.192.0/21" in unmanaged["cidrs"]


def test_okta_id_matches_http_sender_function(doc):
    p = next(p for p in doc["people"] if p["login"] == "nalharbi")
    assert p["okta_id"] == om.okta_user_id(p["email"])


# ── validation rules ───────────────────────────────────────────────────────────────────────────────────────────────


def _errors(doc, mutate):
    d = copy.deepcopy(doc)
    mutate(d)
    return om.validate_document(d)


def _has(errors, text):
    return any(text in e for e in errors)


def test_duplicate_login_is_rejected(doc):
    errs = _errors(doc, lambda d: d["people"][1].update(login=d["people"][0]["login"]))
    assert _has(errs, "login")


def test_duplicate_host_address_is_rejected(doc):
    errs = _errors(doc, lambda d: d["hosts"][3].update(ip=d["hosts"][2]["ip"]))
    assert _has(errs, "host address")


def test_host_outside_its_network_is_rejected(doc):
    errs = _errors(doc, lambda d: d["hosts"][0].update(ip="10.99.0.1"))
    assert _has(errs, "outside network")


def test_unknown_network_is_rejected(doc):
    errs = _errors(doc, lambda d: d["hosts"][0].update(network="nope"))
    assert _has(errs, "does not exist")


def test_person_workstation_must_exist_and_be_theirs(doc):
    assert _has(_errors(doc, lambda d: d["people"][0].update(workstation="PHWS-999")), "does not exist")
    assert _has(_errors(doc, lambda d: d["people"][0].update(workstation=d["people"][1]["workstation"])), "owned by")


def test_manager_must_exist(doc):
    errs = _errors(doc, lambda d: d["people"][2].update(manager="ghost"))
    assert _has(errs, "manager")


def test_manager_cycle_is_rejected(doc):
    def loop(d):
        ceo = next(p for p in d["people"] if p["login"] == "falqarni")
        ceo["manager"] = "malessa"  # the CFO reports to the CEO
    assert _has(_errors(doc, loop), "loops back")


def test_group_must_be_declared(doc):
    errs = _errors(doc, lambda d: d["people"][0]["groups"].append("SG-Nope"))
    assert _has(errs, "SG-Nope")


def test_email_must_use_the_email_domain(doc):
    errs = _errors(doc, lambda d: d["people"][0].update(email="x@other.example"))
    assert _has(errs, "not in the domain")


def test_contractor_and_leaver_rules(doc):
    def bad_contractor(d):
        p = next(p for p in d["people"] if p["login"] == "ext.ralmubarak")
        p["login"] = "ralmubarak"
        p["email"] = "rayan.almubarak@phantom.lab"
        for h in d["hosts"]:
            if h.get("owner") == "ext.ralmubarak":
                h["owner"] = "ralmubarak"
    assert _has(_errors(doc, bad_contractor), "starts with 'ext.'")
    assert _has(_errors(doc, lambda d: next(p for p in d["people"] if "leaver" in p.get("flags", []))
                        .pop("disabled_on")), "disabled_on")


def test_network_not_covered_by_internal_ranges(doc):
    errs = _errors(doc, lambda d: d["cortex"]["internal_ranges"].remove("10.21.0.0/16"))
    assert _has(errs, "not covered")


def test_schema_error_is_reported_before_semantics(doc):
    errs = _errors(doc, lambda d: d.pop("people"))
    assert errs and all("people" in e or "required" in e for e in errs)


def test_parse_errors():
    with pytest.raises(om.OrganizationError):
        om.parse_document("")
    with pytest.raises(om.OrganizationError):
        om.parse_document("- a\n- b\n")
    with pytest.raises(om.OrganizationError):
        om.parse_document("{not json", "json")


def test_yaml_and_json_round_trip(doc):
    assert om.parse_document(om.to_yaml(doc)) == doc
    assert om.parse_document(om.to_json(doc)) == doc


# ── read views ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_section_people_filter_by_department_and_flag(doc):
    fin = om.section(doc, "people", "department=Finance")
    assert fin["total"] == 7 and all(r["department"] == "Finance" for r in fin["rows"])
    vip = om.section(doc, "people", "flag=vip")
    assert {r["login"] for r in vip["rows"]} == {"falqarni", "malessa"}
    assert all(r["workstation_ip"] for r in vip["rows"])


def test_section_bare_word_matches_name_and_login(doc):
    r = om.section(doc, "people", "noura")
    assert [x["login"] for x in r["rows"]] == ["nalharbi"]


def test_section_hosts_roles_and_cap(doc):
    servers = om.section(doc, "hosts", "role=server")
    assert servers["total"] >= 8
    ws = om.section(doc, "hosts", "role=workstation", limit=10)
    assert ws["total"] == 50 and ws["returned"] == 10 and ws["truncated"] is True and ws["next_offset"] == 10
    nxt = om.section(doc, "hosts", "role=workstation", limit=10, offset=ws["next_offset"])
    assert nxt["offset"] == 10 and nxt["rows"][0]["name"] != ws["rows"][0]["name"]


def test_section_accounts_has_sids_and_admin_rows(doc):
    rows = om.section(doc, "accounts", "kind=admin")["rows"]
    assert {r["login"] for r in rows} >= {"adm.ialkhalifa", "adm.jalsaif"}
    assert all(r["sid"].startswith("S-1-5-21-") for r in rows)


def test_section_unknown_name_is_an_error(doc):
    with pytest.raises(om.OrganizationError):
        om.section(doc, "nonsense")


# ── edits ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_add_new_hire_fills_in_the_rest(doc):
    new, notes = om.apply_changes(doc, {"upsert": {"people": [
        {"given_name": "Amira", "family_name": "Alfarsi", "title": "Financial Analyst", "department": "Finance"}]}})
    om.require_valid(new)
    p = next(p for p in new["people"] if p["login"] == "aalfarsi")
    assert p["email"] == "amira.alfarsi@phantom.lab" and p["okta_id"].startswith("00u")
    assert p["workstation"] == "PHWS-051" and p["manager"] == "nalharbi"
    ws = next(h for h in new["hosts"] if h["name"] == "PHWS-051")
    assert ws["ip"] == "10.20.16.70" and ws["owner"] == "aalfarsi" and ws["network"] == "ruh-workstations"
    assert any("PHWS-051" in n for n in notes)
    assert len(doc["people"]) == 50  # the original is untouched


def test_second_hire_gets_the_next_address(doc):
    d1, _ = om.apply_changes(doc, {"upsert": {"people": [
        {"given_name": "A", "family_name": "One", "title": "Analyst", "department": "Finance"}]}})
    d2, _ = om.apply_changes(d1, {"upsert": {"people": [
        {"given_name": "B", "family_name": "Two", "title": "Analyst", "department": "Finance"}]}})
    om.require_valid(d2)
    ips = {h["name"]: h["ip"] for h in d2["hosts"]}
    assert ips["PHWS-051"] == "10.20.16.70" and ips["PHWS-052"] == "10.20.16.71"


def test_hire_in_jeddah_lands_in_the_branch_block(doc):
    new, _ = om.apply_changes(doc, {"upsert": {"people": [
        {"given_name": "C", "family_name": "Three", "title": "Engineer", "department": "Engineering", "site": "JED"}]}})
    om.require_valid(new)
    ws = next(h for h in new["hosts"] if h.get("owner") == "cthree")
    assert ws["ip"].startswith("10.21.16.") and ws["network"] == "jed-lan"


def test_upsert_existing_person_merges_fields(doc):
    new, notes = om.apply_changes(doc, {"upsert": {"people": [{"login": "nalharbi", "title": "Head of Finance"}]}})
    p = next(p for p in new["people"] if p["login"] == "nalharbi")
    assert p["title"] == "Head of Finance" and p["department"] == "Finance"
    assert len(new["people"]) == 50 and notes == ["people: updated nalharbi"]


def test_remove_person_reparents_reports_and_removes_their_workstation(doc):
    new, notes = om.apply_changes(doc, {"remove": {"people": ["nalharbi"]}})
    om.require_valid(new)  # the cascade leaves a consistent organization
    assert not any(p["login"] == "nalharbi" for p in new["people"])
    assert all(p.get("manager") != "nalharbi" for p in new["people"])
    assert not any(h["name"] == "PHWS-001" for h in new["hosts"])
    assert any("now reports to malessa" in n for n in notes) and any("PHWS-001 removed" in n for n in notes)


def test_removing_the_leaver_is_one_call(doc):
    new, _ = om.apply_changes(doc, {"remove": {"people": ["ralsayegh"]}})
    om.require_valid(new)
    assert len(new["people"]) == 49 and len([h for h in new["hosts"] if h["role"] == "workstation"]) == 49


def test_remove_unknown_key_is_an_error(doc):
    with pytest.raises(om.OrganizationError):
        om.apply_changes(doc, {"remove": {"people": ["ghost"]}})


def test_set_merges_and_null_deletes(doc):
    new, _ = om.apply_changes(doc, {"set": {"locale": {"timezone": "Asia/Dubai"}, "description": "x"}})
    assert new["locale"]["timezone"] == "Asia/Dubai" and new["locale"]["workweek"] == doc["locale"]["workweek"]
    new2, _ = om.apply_changes(new, {"set": {"cloud": {"gcp": None}}})
    assert "gcp" not in new2["cloud"]


def test_bad_change_shapes_are_rejected(doc):
    for bad in ({}, {"nope": 1}, {"set": {"people": []}}, {"upsert": {"widgets": []}}, {"upsert": {"people": "x"}}):
        with pytest.raises(om.OrganizationError):
            om.apply_changes(doc, bad)


# ── paging under the chat route's tool-result cap ────────────────────────────────────────────────────────────────

def test_default_pages_stay_under_the_tool_result_cap_and_say_what_they_are(doc):
    import json
    for name in ("people", "hosts", "accounts", "networks", "groups", "personas", "overview"):
        out = om.section(doc, name, None, 500)
        assert len(json.dumps(out)) < 14_000, name          # the chat route keeps only head and tail past 16 KB
        if "rows" in out:
            assert out["returned"] == len(out["rows"]) and out["truncated"] == (out["returned"] < out["total"])


def test_paging_walks_the_whole_list_without_a_gap_or_a_repeat(doc):
    seen, offset = [], 0
    while True:
        page = om.section(doc, "people", None, 500, offset, max_bytes=3_000)
        assert page["returned"] >= 1
        seen += [r["login"] for r in page["rows"]]
        if not page["truncated"]:
            break
        offset = page["next_offset"]
    assert seen == [p["login"] for p in doc["people"]]


def test_detail_adds_the_rare_columns_and_nothing_else_changes(doc):
    light = om.section(doc, "people", "login=nalharbi")["rows"][0]
    full = om.section(doc, "people", "login=nalharbi", detail=True)["rows"][0]
    assert {"sid", "okta_id", "home_ip", "groups"}.isdisjoint(light) and {"sid", "okta_id", "home_ip", "groups"} <= set(full)
    assert {k: v for k, v in full.items() if k in light} == light
