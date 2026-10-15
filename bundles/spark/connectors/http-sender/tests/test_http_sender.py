"""http-sender connector: unit tests. No network: the collector is an httpx MockTransport.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.organization_view import get_view  # noqa: E402
from src import collector, connector, destinations, profiles  # noqa: E402
from src.profiles import _org, ippools, okta as okta_events  # noqa: E402

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
KEY = "sekrit-collector-key-0123456789"
URL = "https://api-tenant.example.test/logs/v1/event"
PUBLISHED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def build(scenario, count, **kw):
    return okta_events.build_events(scenario, count, view=get_view(), now=NOW, seed=7, **kw)


def email(local):
    """The email of the organization person whose address starts with `local` (the bundled organization is active)."""
    view = get_view()
    return f"{local}@{view.email_domain}"


def pool():
    """The people who may log on, as the profiles see them."""
    return _org.logon_people(get_view())


# ── event shape ─────────────────────────────────────────────────────────

REQUIRED = {"actor", "client", "outcome", "target", "debugContext", "securityContext",
            "authenticationContext", "transaction", "request", "eventType", "severity",
            "displayMessage", "legacyEventType", "uuid", "published"}


@pytest.mark.parametrize("scenario", okta_events.SCENARIOS)
def test_every_scenario_emits_full_system_log_objects(scenario):
    events = build(scenario, 8)
    assert len(events) == 8
    for ev in events:
        assert REQUIRED <= ev.keys()
        assert PUBLISHED.match(ev["published"])
        assert "@" in ev["actor"]["alternateId"] and "\\" not in ev["actor"]["alternateId"]
        assert ev["outcome"]["result"] in ("SUCCESS", "FAILURE")
    assert len({e["uuid"] for e in events}) == 8


def test_published_never_after_now_and_ascending():
    events = build("benign_logins", 10, spread_seconds=300, start_offset_minutes=5)
    times = [e["published"] for e in events]
    assert times == sorted(times)
    assert times[-1] <= okta_events.iso(NOW)
    assert times[-1] == "2026-09-30T11:55:00.000Z"  # 5 minutes back-dated


def test_failed_then_success_is_one_user_one_ip_ending_in_success():
    events = build("failed_then_success", 6, target_user="Noura.Alharbi", source_ip="203.0.113.99")
    assert [e["outcome"]["result"] for e in events] == ["FAILURE"] * 5 + ["SUCCESS"]
    assert {e["actor"]["alternateId"] for e in events} == {email("noura.alharbi")}
    assert {e["actor"]["id"] for e in events} == {get_view().person("nalharbi")["okta_id"]}
    assert {e["client"]["ipAddress"] for e in events} == {"203.0.113.99"}
    assert events[0]["outcome"]["reason"] == "INVALID_CREDENTIALS"


# ── the IP model: real, geo-resolvable addresses ──────────────────

def in_range(ip, pool_range):
    return ipaddress.ip_address(ip) in ipaddress.ip_network(pool_range.cidr)


def home_range_of(ip):
    return next((r for r in ippools.HOME if in_range(ip, r)), None)


def abroad_range_of(ip):
    return next((r for r in ippools.ABROAD if in_range(ip, r)), None)


def home_ips(events):
    return {e["actor"]["alternateId"]: e["client"]["ipAddress"] for e in events}


def test_a_user_keeps_one_home_address_across_events_and_runs():
    n = 2 * len(pool())  # a login and an SSO event for every person who may log on
    first, second = build("benign_logins", n), build("benign_logins", n, spread_seconds=900, start_offset_minutes=30)
    for events in (first, second):
        by_user = {}
        for ev in events:
            by_user.setdefault(ev["actor"]["alternateId"], set()).add(ev["client"]["ipAddress"])
        assert len(by_user) == len(pool()) and all(len(ips) == 1 for ips in by_user.values())
    other_seed = okta_events.build_events("benign_logins", n, view=get_view(), now=NOW, seed=99)
    assert home_ips(first) == home_ips(second) == home_ips(other_seed)
    assert len(set(home_ips(first).values())) == len(pool())  # one address per person


def test_benign_events_come_from_a_home_range_and_agree_with_what_cortex_resolves():
    for ev in build("benign_logins", 30):
        ip, geo, sec = ev["client"]["ipAddress"], ev["client"]["geographicalContext"], ev["securityContext"]
        net = home_range_of(ip)
        assert net is not None and net.country == "Saudi Arabia"
        assert (geo["country"], geo["city"], geo["state"]) == (net.country, net.city, net.region)
        assert geo["geolocation"] == {"lat": net.lat, "lon": net.lon}
        assert (sec["asNumber"], sec["asOrg"], sec["isp"], sec["isProxy"]) == (net.asn, net.isp, net.isp, False)
        assert sec["domain"] == okta_events._ASN_DOMAIN[net.asn]
        assert ev["request"]["ipChain"][0] == {"ip": ip, "geographicalContext": geo, "version": "V4", "source": None}


def test_home_addresses_are_the_ones_the_organization_gives_its_people():
    by_email = {p["email"]: p for p in get_view().people}
    for ev in build("benign_logins", 24):
        person = by_email[ev["actor"]["alternateId"]]
        assert ev["client"]["ipAddress"] == person["home_ip"]
        assert ev["actor"]["id"] == person["okta_id"] and ev["actor"]["displayName"] == person["display_name"]


@pytest.mark.parametrize("scenario", ["failed_then_success", "password_spray", "mfa_fatigue"])
def test_attacks_default_to_an_out_of_country_address_with_matching_geo(scenario):
    events = build(scenario, 9)
    (ip,) = {e["client"]["ipAddress"] for e in events}
    net = abroad_range_of(ip)
    assert net is not None and home_range_of(ip) is None and net.country != "Saudi Arabia"
    for ev in events:
        geo, sec = ev["client"]["geographicalContext"], ev["securityContext"]
        assert (geo["country"], geo["city"]) == (net.country, net.city)
        assert (sec["asNumber"], sec["isp"]) == (net.asn, net.isp)


def test_every_abroad_range_gets_a_harmless_domain_and_no_home_range_is_an_attacker():
    assert {okta_events._isp_domain(r) for r in ippools.HOME} == {"example-isp.example", "mobily.com.sa", "zain.com.sa"}
    for r in ippools.ABROAD:
        assert re.fullmatch(r"[a-z0-9]+\.example", okta_events._isp_domain(r)), r
    for seed in range(40):
        events = okta_events.build_events("password_spray", 3, view=get_view(), now=NOW, seed=seed)
        assert home_range_of(events[0]["client"]["ipAddress"]) is None


def build_seeded(scenario, seed):
    return okta_events.build_events(scenario, 4, view=get_view(), now=NOW, seed=seed)


def test_attack_default_ip_is_seeded_and_varies_with_the_seed():
    ips = {seed: build_seeded("password_spray", seed)[0]["client"]["ipAddress"] for seed in range(30)}
    assert ips[1] == build_seeded("password_spray", 1)[0]["client"]["ipAddress"]
    assert len(set(ips.values())) > 5
    for scenario in ("failed_then_success", "password_spray", "mfa_fatigue"):
        assert build_seeded(scenario, 3) == build_seeded(scenario, 3)


def test_source_ip_override_wins_and_takes_its_geo_from_the_pool_range_it_sits_in():
    inside = ippools.host_in(ippools.ABROAD[4], 77)
    events = build("password_spray", 3, source_ip=inside)
    assert {e["client"]["ipAddress"] for e in events} == {inside}
    assert events[0]["client"]["geographicalContext"]["country"] == ippools.ABROAD[4].country
    assert events[0]["securityContext"]["asNumber"] == ippools.ABROAD[4].asn


def test_source_ip_outside_every_pool_is_kept_with_unknown_safe_geo():
    events = build("failed_then_success", 3, source_ip="203.0.113.99")
    assert {e["client"]["ipAddress"] for e in events} == {"203.0.113.99"}
    geo, sec = events[0]["client"]["geographicalContext"], events[0]["securityContext"]
    assert geo == {"city": None, "state": None, "country": None, "postalCode": None, "geolocation": None}
    assert (sec["asNumber"], sec["asOrg"], sec["isp"], sec["domain"]) == (None, None, None, None)


def test_the_sample_event_comes_from_a_home_address():
    ev = okta_events.sample_event(view=get_view(), now=NOW)
    assert ev["actor"]["alternateId"] == f"phantom.test@{get_view().email_domain}"
    assert ev["client"]["ipAddress"] == ippools.home_for(0)[0]
    assert ev["client"]["geographicalContext"]["country"] == "Saudi Arabia"


def test_domain_backslash_user_is_reduced_to_bare_name():
    events = build("failed_then_success", 2, target_user="Acme\\khalid.alotaibi")
    assert events[0]["actor"]["alternateId"] == email("khalid.alotaibi")


def test_password_spray_is_one_ip_many_users_all_failures():
    events = build("password_spray", 30)
    assert len({e["client"]["ipAddress"] for e in events}) == 1
    assert len({e["actor"]["alternateId"] for e in events}) == 30
    assert {e["outcome"]["result"] for e in events} == {"FAILURE"}


def test_mfa_fatigue_alternates_push_and_deny_then_approves():
    events = build("mfa_fatigue", 7)
    kinds = [e["eventType"] for e in events]
    assert kinds[:6] == ["system.push.send_factor_verify_push", "user.mfa.okta_verify.deny_push"] * 3
    assert kinds[-1] == "user.authentication.auth_via_mfa"
    assert events[-1]["outcome"]["result"] == "SUCCESS"


def test_seed_makes_output_reproducible():
    assert build("benign_logins", 5) == build("benign_logins", 5)


def test_unknown_scenario_and_zero_count_rejected():
    with pytest.raises(ValueError):
        build("ransomware", 3)
    with pytest.raises(ValueError):
        build("benign_logins", 0)


# ── transport ───────────────────────────────────────────────────────────

def make_transport(statuses, seen):
    """Answer with `statuses` in order, recording each request."""
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, json={"error": "false"} if status == 200 else {"error": "x"})

    return httpx.MockTransport(handler)


def post(events, statuses=(200,), seen=None, sleeps=None):
    seen = seen if seen is not None else []
    return collector.post_events(
        URL, KEY, events, vendor="Okta", product="SSO",
        transport=make_transport(statuses, seen),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
    )


def test_request_matches_the_documented_wire_contract():
    seen: list[httpx.Request] = []
    result = post(build("benign_logins", 3), seen=seen)
    assert result["ok"] and result["sent"] == 3 and result["batches"] == 1
    req = seen[0]
    assert req.headers["authorization"] == KEY  # raw key, no Bearer
    assert req.headers["content-type"] == "application/json"
    lines = req.content.decode().split("\n")
    assert len(lines) == 3 and all(isinstance(json.loads(line), dict) for line in lines)


def test_key_is_never_in_the_result():
    for statuses in ((200,), (401,), (500,)):
        assert KEY not in repr(post(build("benign_logins", 2), statuses=statuses))


def test_401_fails_fast_without_retry_and_explains():
    seen: list[httpx.Request] = []
    result = post(build("benign_logins", 2), statuses=(401,), seen=seen)
    assert not result["ok"] and result["http_status"] == 401 and result["sent"] == 0
    assert len(seen) == 1
    assert "key is wrong" in result["error"]


def test_plain_500_is_a_format_error_and_is_not_retried():
    seen: list[httpx.Request] = []
    result = post(build("benign_logins", 2), statuses=(500,), seen=seen)
    assert len(seen) == 1 and "Log Format" in result["error"]


def test_429_is_retried_with_backoff_then_succeeds():
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    result = post(build("benign_logins", 2), statuses=(429, 429, 200), seen=seen, sleeps=sleeps)
    assert result["ok"] and len(seen) == 3 and sleeps == [1.0, 2.0]


def test_large_send_is_split_under_the_batch_limit():
    events = build("benign_logins", 40)
    records = collector.to_ndjson_records(events)
    batches = collector.split_batches(records, max_bytes=8_000)
    assert len(batches) > 1
    assert sum(len(b) for b in batches) == 40
    assert all(sum(len(r.encode()) + 1 for r in b) <= 8_000 for b in batches)


def test_partial_failure_reports_how_many_were_accepted():
    events = build("benign_logins", 40)
    result = collector.post_events(
        URL, KEY, events, vendor="Okta", product="SSO", max_batch_bytes=8_000,
        transport=make_transport((200, 401), []), sleep=lambda _s: None,
    )
    assert not result["ok"] and result["http_status"] == 401
    assert 0 < result["sent"] < 40 and result["sent"] + result["failed"] == 40


def test_dataset_name_is_derived_like_the_collector_does():
    assert collector.dataset_name("Okta", "SSO") == "okta_sso_raw"
    assert collector.dataset_name("Google Cloud", "Cloud Audit Logs") == "google_cloud_cloud_audit_logs_raw"


# ── destinations ────────────────────────────────────────────────────────

PROOFPOINT_URL = "https://api-other.example.test/logs/v1/event"
PROOFPOINT_KEY = "other-collector-key-9876543210"
EXTRA = f'[{{"url": "{PROOFPOINT_URL}", "vendor": "Proofpoint", "product": "Email Security"}}]'
EXTRA_KEYS = f'{{"proofpoint_email_security": "{PROOFPOINT_KEY}"}}'


def load(**over):
    cfg = {"url": URL, "key": KEY, "vendor": "Okta", "product": "SSO", "extra": "", "extra_keys": "", **over}
    return destinations.load(cfg)


def test_the_primary_destination_is_named_after_its_dataset():
    dests, problems = load()
    assert list(dests) == ["okta_sso"] and problems == []
    assert dests["okta_sso"].dataset == "okta_sso_raw" and dests["okta_sso"].primary


def test_additional_destinations_join_the_primary_with_their_own_key():
    dests, problems = load(extra=EXTRA, extra_keys=EXTRA_KEYS)
    assert list(dests) == ["okta_sso", "proofpoint_email_security"] and problems == []
    other = dests["proofpoint_email_security"]
    assert (other.url, other.key, other.vendor, other.product) == (PROOFPOINT_URL, PROOFPOINT_KEY, "Proofpoint", "Email Security")
    assert not other.primary and other.dataset == "proofpoint_email_security_raw"


@pytest.mark.parametrize("wanted", ["okta_sso", "OKTA_SSO", "okta_sso_raw", " Okta-SSO "])
def test_a_destination_can_be_addressed_by_name_or_dataset(wanted):
    dests, problems = load()
    dest, error = destinations.resolve(dests, problems, wanted)
    assert error is None and dest.name == "okta_sso"


def test_no_destination_means_the_primary_and_an_unknown_one_lists_the_choices():
    dests, problems = load(extra=EXTRA, extra_keys=EXTRA_KEYS)
    assert destinations.resolve(dests, problems, None)[0].name == "okta_sso"
    dest, error = destinations.resolve(dests, problems, "splunk")
    assert dest is None and "okta_sso, proofpoint_email_security" in error


def test_bad_json_is_reported_without_breaking_the_primary():
    dests, problems = load(extra="[{not json", extra_keys="also not json")
    assert list(dests) == ["okta_sso"]
    assert any("additionalDestinations is not valid JSON" in p for p in problems)
    assert any("additionalKeys is not valid JSON" in p for p in problems)


def test_wrong_shapes_duplicates_and_stray_keys_are_each_reported():
    extra = ('[{"url": "https://x.test/l", "vendor": "Okta", "product": "SSO"}, '
             '{"vendor": "Only"}, "nope"]')
    dests, problems = load(extra=extra, extra_keys='{"ghost": "k"}')
    assert list(dests) == ["okta_sso"]
    assert any("repeats destination 'okta_sso'" in p for p in problems)
    assert sum("needs string fields url, vendor and product" in p for p in problems) == 2
    assert any("'ghost'" in p for p in problems)


def test_a_config_error_never_echoes_the_key_text():
    _, problems = load(extra_keys="{" + KEY)
    assert KEY not in " ".join(problems)


def test_primary_needs_a_vendor_and_product():
    dests, problems = load(vendor="", product="")
    assert dests == {} and any("vendor and product are required" in p for p in problems)
    dest, error = destinations.resolve(dests, problems, None)
    assert dest is None and "vendor and product" in error


def test_check_names_the_right_secret_slot():
    dests, _ = load(extra=EXTRA, extra_keys="")
    assert "collectorKey" in destinations.check(destinations.Destination("okta_sso", URL, "", "Okta", "SSO", primary=True))
    assert "additionalKeys" in destinations.check(dests["proofpoint_email_security"])
    assert destinations.check(dests["okta_sso"]) is None


# ── tool layer ──────────────────────────────────────────────────────────

@pytest.fixture
def settings(monkeypatch):
    cfg = {"url": URL, "key": KEY, "vendor": "Okta", "product": "SSO", "extra": EXTRA, "extra_keys": EXTRA_KEYS,
           "organization": "", "verify_tls": True, "timeout": 5.0}
    monkeypatch.setattr(connector, "_settings", lambda: dict(cfg))
    return cfg


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_post(url, key, events, **kw):
        calls.append({"url": url, "key": key, "events": events, **kw})
        return {"ok": True, "sent": len(events), "failed": 0, "batches": 1,
                "http_status": 200, "response": '{"error":"false"}'}

    monkeypatch.setattr(connector.collector, "post_events", fake_post)
    return calls


def test_list_destinations_shows_readiness_and_never_a_key(settings):
    result = connector.phantom_list_destinations()
    assert result["ok"] and [d["destination"] for d in result["destinations"]] == ["okta_sso", "proofpoint_email_security"]
    first, second = result["destinations"]
    assert first["default"] and not second["default"] and first["ready"] and second["ready"]
    assert second["host"] == "api-other.example.test" and second["dataset"] == "proofpoint_email_security_raw"
    assert "okta" in result["profiles"]
    assert KEY not in repr(result) and PROOFPOINT_KEY not in repr(result)


def test_list_destinations_flags_a_destination_that_is_not_ready(settings):
    settings["extra_keys"] = ""
    second = connector.phantom_list_destinations()["destinations"][1]
    assert not second["ready"] and "additionalKeys" in second["problem"]


def test_generic_test_event_fits_any_source(settings, sent):
    result = connector.phantom_send_test_event()
    assert result["ok"] and result["sent"] == 1 and result["dataset"] == "okta_sso_raw"
    event = sent[0]["events"][0]
    assert set(event) == {"phantom_test_id", "phantom_test_time", "message"}
    assert result["test_id"] == event["phantom_test_id"]
    assert result["verify_with_xql"] == f'dataset = okta_sso_raw | filter phantom_test_id = "{result["test_id"]}"'
    assert KEY not in repr(result)


def test_test_event_with_a_profile_is_that_sources_own_sample(settings, sent):
    result = connector.phantom_send_test_event(profile="okta")
    event = sent[0]["events"][0]
    assert event["eventType"] == "user.session.start" and event["actor"]["alternateId"] == f"phantom.test@{get_view().email_domain}"
    assert result["verify_with_xql"] == f'dataset = okta_sso_raw | filter uuid = "{event["uuid"]}"'


def test_unknown_profile_is_refused_with_the_choices(settings, sent):
    assert "okta" in connector.phantom_send_test_event(profile="nope")["error"]
    assert "okta" in connector.phantom_generate_events("nope", "benign_logins")["error"]
    assert sent == []


def test_a_destination_uses_its_own_url_key_and_dataset(settings, sent):
    result = connector.phantom_send_test_event(destination="proofpoint_email_security")
    assert (sent[0]["url"], sent[0]["key"]) == (PROOFPOINT_URL, PROOFPOINT_KEY)
    assert (sent[0]["vendor"], sent[0]["product"]) == ("Proofpoint", "Email Security")
    assert result["destination"] == "proofpoint_email_security" and result["dataset"] == "proofpoint_email_security_raw"
    assert PROOFPOINT_KEY not in repr(result)
    connector.phantom_send_test_event()
    assert (sent[1]["url"], sent[1]["key"]) == (URL, KEY), "no destination means the primary one"


def test_unknown_destination_is_reported_not_sent(settings, sent):
    result = connector.phantom_send_test_event(destination="splunk")
    assert not result["ok"] and "okta_sso, proofpoint_email_security" in result["error"] and sent == []


def test_refuses_to_send_a_key_over_plain_http(settings, sent):
    settings["url"] = "http://api-tenant.example.test/logs/v1/event"
    assert "https" in connector.phantom_send_test_event()["error"]
    settings["extra"] = EXTRA.replace("https://", "http://")
    assert "https" in connector.phantom_send_test_event(destination="proofpoint_email_security")["error"]
    assert sent == []


def test_missing_key_or_url_is_reported_not_raised(settings, sent):
    settings["key"] = ""
    assert "collectorKey" in connector.phantom_send_test_event()["error"]
    settings["key"], settings["url"] = KEY, ""
    assert "collector URL" in connector.phantom_send_test_event()["error"]
    assert sent == []


def test_generate_events_dry_run_sends_nothing_and_needs_no_credentials(settings, sent):
    settings["key"] = settings["url"] = ""
    result = connector.phantom_generate_events("okta", "password_spray", count=5, dry_run=True)
    assert result["ok"] and result["dry_run"] and result["sent"] == 0
    assert len(result["events"]) == 3 and sent == []


def test_generate_events_sends_and_summarises(settings, sent):
    result = connector.phantom_generate_events("okta", "failed_then_success", count=6, target_user="noura.alharbi")
    assert result["ok"] and result["sent"] == 6 and result["scenario"] == "failed_then_success"
    assert result["profile"] == "okta" and result["destination"] == "okta_sso" and "warning" not in result
    assert len(result["sample_ids"]) == 5 and result["first_time"] <= result["last_time"]
    assert len(sent[0]["events"]) == 6


@pytest.mark.parametrize("vendor,product,destination,profile", [
    ("Okta", "SSO", "okta_sso", "okta"),
    ("Okta", "Okta", "okta_okta", "okta"),
    ("google_workspace", "drive", "google_workspace_drive", "google_workspace"),
])
def test_profiles_accept_every_collector_they_suit_without_a_warning(settings, sent, vendor, product, destination, profile):
    settings["vendor"], settings["product"] = vendor, product
    scenario = connector.profiles.get(profile).SCENARIOS[0]
    result = connector.phantom_generate_events(profile, scenario, count=3, dry_run=True)
    assert result["ok"] and result["destination"] == destination and "warning" not in result
    assert sent == []


def test_the_okta_profile_prefers_okta_okta_and_still_warns_for_an_unrelated_dataset(settings, sent):
    assert okta_events.EXPECTED_DATASET == "okta_okta"
    assert okta_events.EXPECTED_DATASETS == ("okta_okta", "okta_sso")
    result = connector.phantom_generate_events("okta", "benign_logins", count=2, dry_run=True,
                                               destination="proofpoint_email_security")
    assert result["warning"] == ("profile 'okta' produces events for 'okta_okta' or 'okta_sso' "
                                 "but the destination is 'proofpoint_email_security'")


def test_every_profile_names_its_preferred_dataset_first():
    for prof in profiles.PROFILES.values():
        assert prof.EXPECTED_DATASETS[0] == prof.EXPECTED_DATASET


def test_generate_events_warns_when_the_destination_is_not_the_profiles_source(settings, sent):
    result = connector.phantom_generate_events("okta", "benign_logins", count=3, destination="proofpoint_email_security")
    assert result["ok"] and "okta_sso" in result["warning"] and sent[0]["url"] == PROOFPOINT_URL


def test_generate_events_input_errors(settings, sent):
    assert not connector.phantom_generate_events("okta", "nope")["ok"]
    assert connector.phantom_generate_events("okta", "mfa_fatigue", count=1, dry_run=True)["count_raised"]["used"] == 2
    assert not connector.phantom_generate_events("okta", "benign_logins", count=10_000)["ok"]
    assert sent == []


def test_send_events_passes_objects_through_unchanged_to_the_chosen_destination(settings, sent):
    payload = [{"anything": "goes", "n": 1}]
    result = connector.phantom_send_events(payload, destination="proofpoint_email_security")
    assert result["ok"] and sent[0]["events"] == payload and sent[0]["key"] == PROOFPOINT_KEY
    assert result["destination"] == "proofpoint_email_security"


def test_send_events_validates_input(settings, sent):
    assert not connector.phantom_send_events([])["ok"]
    assert not connector.phantom_send_events(["not an object"])["ok"]
    assert not connector.phantom_send_events([{"a": 1}] * 5001)["ok"]
    assert sent == []


def test_no_tool_ever_returns_a_collector_key(settings, sent):
    results = [
        connector.phantom_list_destinations(),
        connector.phantom_send_test_event(), connector.phantom_send_test_event(destination="proofpoint_email_security"),
        connector.phantom_generate_events("okta", "benign_logins", count=2),
        connector.phantom_generate_events("okta", "benign_logins", count=2, dry_run=True),
        connector.phantom_send_events([{"a": 1}]), connector.phantom_send_events([{"a": 1}], destination="nope"),
    ]
    text = repr(results)
    assert KEY not in text and PROOFPOINT_KEY not in text


# ── the manifest ────────────────────────────────────────────────────────

def manifest():
    import yaml

    return yaml.safe_load((Path(__file__).resolve().parents[1] / "connector.yaml").read_text())


def test_tool_names_and_arguments_match_the_manifest():
    import inspect

    declared = {t["name"]: t for t in manifest()["spec"]["tools"]}
    exported = {n.removeprefix("phantom_"): getattr(connector, n) for n in connector.__all__}
    assert declared.keys() == exported.keys()
    for name, fn in exported.items():
        params = set(inspect.signature(fn).parameters)
        assert {a["name"] for a in declared[name]["args"]} == params, name


def test_the_manifest_carries_no_provider_specific_defaults():
    props = manifest()["configSchema"]["properties"]
    assert props["vendor"]["default"] == "" and props["product"]["default"] == ""
    # identities are the organization's: no domain setting, and an optional pin of one organization (empty = the active one)
    assert "userDomain" not in props
    assert props["organization"]["type"] == "string" and props["organization"]["default"] == ""
    # Which fields an instance needs depends on its destination kind (destinationMode, which the connector
    # ignores and only the Add-instance form uses), so the schema requires none of them itself.
    assert not manifest()["configSchema"].get("required")
    mode = props["destinationMode"]
    assert mode["enum"] == ["http", "cribl", "both"] and mode["default"] == "http"
    # a bundle connector declares no `image`: the updater derives it from the release digest pin, and an
    # explicit one would make the agent pass an image_ref that bypasses the pin
    assert manifest()["id"] == "http-sender" and manifest()["version"] == "1.0.0" and "image" not in manifest()
    slots = {s["name"]: s for s in manifest()["secretSlots"]}
    assert not slots["collectorKey"]["required"] and "HTTP collector" in slots["collectorKey"]["description"]
    assert not slots["additionalKeys"]["required"]
    assert "criblToken" in slots and not slots["criblToken"]["required"]  # Cribl mode is optional
