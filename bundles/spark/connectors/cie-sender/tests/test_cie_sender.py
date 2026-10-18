"""cie-sender connector: unit tests. No network: the SCIM server is an in-memory fake behind an httpx MockTransport.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.organization_view import OrganizationView, get_view  # noqa: E402
from src import connector, directory, scim  # noqa: E402

TOKEN = "sekrit-scim-bearer-token-0123456789"
BASE = "https://cie.example.test/scim/v2/phantom-scim"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeScim:
    """Enough of a SCIM 2.0 server for the connector: filter eq on userName/displayName, POST, path-based PATCH, DELETE."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, dict[str, Any]]] = {"Users": {}, "Groups": {}}
        self.requests: list[httpx.Request] = []
        self.fail_next: list[httpx.Response] = []

        self.drop_external_id = False

    def seed(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        rid = str(uuid.uuid4())
        self.store[kind][rid] = {**body, "id": rid}
        if self.drop_external_id:
            self.store[kind][rid].pop("externalId", None)
        return self.store[kind][rid]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if self.fail_next:
            return self.fail_next.pop(0)
        path = request.url.path.split("/scim/v2/phantom-scim", 1)[1]
        parts = [p for p in path.split("/") if p]
        kind = parts[0]
        items = self.store[kind]
        if request.method == "GET":
            found = list(items.values())
            flt = request.url.params.get("filter")
            if flt:
                m = re.fullmatch(r'(\w+) eq "(.*)"', unquote(flt))
                assert m, flt
                attr, value = m.group(1), m.group(2).replace('\\"', '"').replace("\\\\", "\\")
                found = [r for r in found if str(r.get(attr, "")).lower() == value.lower()]
            start = int(request.url.params.get("startIndex", 1))
            count = int(request.url.params.get("count", 100))
            page = found[start - 1:start - 1 + count]
            return httpx.Response(200, json={"totalResults": len(found), "startIndex": start, "Resources": page})
        if request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(201, json=self.seed(kind, body))
        rid = parts[1]
        if rid not in items:
            return httpx.Response(404, json={"detail": "not found"})
        if request.method == "DELETE":
            del items[rid]
            return httpx.Response(204)
        if request.method == "PATCH":
            body = json.loads(request.content)
            assert body["schemas"] == [scim.PATCH_SCHEMA]
            res = items[rid]
            for op in body["Operations"]:
                self._apply(res, op)
            return httpx.Response(200, json=res)
        raise AssertionError(request.method)

    @staticmethod
    def _apply(res: dict[str, Any], op: dict[str, Any]) -> None:
        path, value = op["path"], op.get("value")
        if path == "members" and op["op"] == "add":
            have = {m["value"] for m in res.setdefault("members", [])}
            res["members"] += [m for m in value if m["value"] not in have]
        elif path.startswith("members[value eq"):
            gone = re.search(r'"(.*)"', path).group(1)
            res["members"] = [m for m in res.get("members", []) if m["value"] != gone]
        elif path.startswith(scim.ENTERPRISE_SCHEMA + ":"):
            res.setdefault(scim.ENTERPRISE_SCHEMA, {})[path.split(":")[-1]] = value
        elif path.startswith("name."):
            res.setdefault("name", {})[path[5:]] = value
        elif path == 'emails[type eq "work"].value':
            res["emails"] = [{"value": value, "type": "work", "primary": True}]
        else:
            res[path] = value

    def methods(self) -> list[str]:
        return [r.method for r in self.requests]


@pytest.fixture
def server(monkeypatch):
    fake = FakeScim()
    transport = httpx.MockTransport(fake.handler)
    settings = {"base_url": BASE, "token": TOKEN, "organization": "", "style": "sam", "verify_tls": True, "timeout": 5.0}
    monkeypatch.setattr(connector, "_settings", lambda: dict(settings))
    monkeypatch.setattr(connector, "_transport", lambda: transport)
    monkeypatch.setattr(scim.time, "sleep", lambda _s: None)
    fake.settings = settings
    return fake


def users(fake: FakeScim) -> dict[str, dict[str, Any]]:
    return {u["userName"]: u for u in fake.store["Users"].values()}


def groups(fake: FakeScim) -> dict[str, dict[str, Any]]:
    return {g["displayName"]: g for g in fake.store["Groups"].values()}


# ── the directory ─────────────────────────────────────────────────────────

def _dir(style: str = "sam", service: bool = True) -> directory.Directory:
    return directory.build(get_view(), style, service)


def _cut_organization() -> dict[str, Any]:
    """The 30 accounts the directory had before organizations existed (fixtures/pre_organization_summary.json), as an
    organization document: 26 people whose logins are the staff logins and the four adm. logins, four service accounts."""
    old = json.loads((FIXTURES / "pre_organization_summary.json").read_text())
    people, services = [], []
    for u in old["users"]:
        login = u["user_name"].split("@")[0]
        display = u["display_name"]
        if u["role"] == "service":
            services.append({"login": login, "display_name": display, "kind": "service", "host": "PHSRV-SQL01",
                             "manager": u["manager"], "groups": u["groups"]})
            continue
        given, _, family = display.replace(" (admin)", "").partition(" ")
        people.append({"login": login, "given_name": given, "family_name": family, "display_name": display,
                       "email": u["email"], "title": u["title"], "department": u["department"],
                       "manager": u["manager"], "site": "RUH", "workstation": "X", "groups": u["groups"]})
    return {"id": "cut", "name": "Phantom Lab", "domain": {"dns": "phantom.lab", "netbios": "PHANTOM"},
            "groups": [{"name": g["name"], "privileged": g["privileged"]} for g in old["groups"]],
            "people": people, "service_accounts": services, "hosts": [], "networks": []}


def test_the_directory_of_the_original_30_accounts_is_reproduced():
    """Equivalence with the pre-organization directory: the same users, titles, departments, managers, groups and members."""
    old = json.loads((FIXTURES / "pre_organization_summary.json").read_text())
    new = directory.summary(directory.build(OrganizationView(_cut_organization())))
    for u in new["users"]:
        u.pop("active")
    assert new == old


def test_directory_shape():
    view = get_view()
    d = _dir()
    logins = [p.login for p in d.people]
    assert len(d.people) == len(view.accounts) == 64 and len(set(logins)) == 64
    by = d.by_login()
    assert "nalharbi" in logins and "adm.ialkhalifa" in logins and "ialkhalifa" in logins
    # an administrator has two accounts with their own employee numbers
    assert by["ialkhalifa"].employee_number != by["adm.ialkhalifa"].employee_number
    assert by["ialkhalifa"].role == "staff" and by["adm.ialkhalifa"].role == "admin"
    assert sorted(m for m in d.groups["Domain Admins"] if m != "adm.breakglass") == sorted(
        p.login for p in d.people if p.login.startswith("adm.") and p.login != "adm.breakglass")
    assert d.privileged == {"SG-IT-Admins", "Domain Admins"}
    assert d.user_name(by["nalharbi"]) == "nalharbi@phantom.lab"
    assert d.email(by["nalharbi"]) == "noura.alharbi@phantom.lab"
    assert d.email(by["adm.ialkhalifa"]) == "adm.ibrahim.alkhalifa@phantom.lab"
    dotted = _dir("dotted")
    assert dotted.user_name(dotted.by_login()["nalharbi"]) == "noura.alharbi@phantom.lab"
    # every manager is a person in the directory, and nobody is their own manager
    assert all(p.manager in by and p.manager != p.login for p in d.people if p.manager)
    assert by["falqarni"].manager is None and by["nalharbi"].manager == "malessa"


def test_managers_are_provisioned_before_their_reports():
    seen: set[str] = set()
    for p in _dir().people:
        assert p.manager is None or p.manager in seen, f"{p.login} before its manager {p.manager}"
        seen.add(p.login)


def test_leaver_is_provisioned_disabled_and_the_rest_are_active():
    d = _dir()
    assert [p.login for p in d.people if not p.active] == ["ralsayegh"]
    body = directory.user_body(d, d.by_login()["ralsayegh"], None)
    assert body["active"] is False
    assert directory.user_body(d, d.by_login()["nalharbi"], None)["active"] is True


def test_service_accounts_can_be_left_out():
    d = _dir(service=False)
    assert not any(p.role == "service" or p.login == "adm.breakglass" for p in d.people)
    assert "SG-Service-Accounts" not in d.groups


def test_directory_is_deterministic_and_validates_the_style():
    assert directory.summary(_dir()) == directory.summary(_dir())
    with pytest.raises(ValueError):
        directory.build(get_view(), "weird")


def test_an_unreadable_organization_is_an_error_not_a_default(monkeypatch):
    from runtime import organization_view as ov
    from runtime.organization_reader import OrganizationUnavailable

    def broken(_pinned):
        raise OrganizationUnavailable("organization.db not found")

    monkeypatch.setattr(connector, "_settings", lambda: {"base_url": BASE, "token": TOKEN, "organization": "",
                                                         "style": "sam", "verify_tls": True, "timeout": 5.0})
    ov.set_organization_loader(broken)
    out = connector.phantom_provision_directory(dry_run=True)
    assert out["ok"] is False and "organization.db not found" in out["error"]


# ── provisioning ──────────────────────────────────────────────────────────

def test_dry_run_makes_no_call(monkeypatch):
    def boom(_request):
        raise AssertionError("dry_run must not call the server")
    monkeypatch.setattr(connector, "_settings", lambda: {"base_url": "", "token": "", "organization": "",
                                                         "style": "sam", "verify_tls": True, "timeout": 5.0})
    monkeypatch.setattr(connector, "_transport", lambda: httpx.MockTransport(boom))
    out = connector.phantom_provision_directory(dry_run=True)
    assert out["ok"] and len(out["directory"]["users"]) == 64
    assert {g["name"] for g in out["directory"]["groups"] if g["privileged"]} == {"SG-IT-Admins", "Domain Admins"}


def test_provision_creates_everything_then_is_idempotent(server):
    out = connector.phantom_provision_directory()
    assert out["ok"], out
    assert out["users"]["created"] == 64 and out["users"]["failed"] == 0
    assert out["groups"]["created"] == 13
    u = users(server)
    noura, khalid = u["nalharbi@phantom.lab"], u["kalotaibi@phantom.lab"]
    assert noura["schemas"] == [scim.USER_SCHEMA, scim.ENTERPRISE_SCHEMA]
    assert noura["externalId"] == "phantom:nalharbi" and noura["active"] is True
    assert noura["emails"][0] == {"value": "noura.alharbi@phantom.lab", "type": "work", "primary": True}
    assert noura[scim.ENTERPRISE_SCHEMA]["department"] == "Finance"
    finance_staff = [x for x in u.values() if x[scim.ENTERPRISE_SCHEMA]["department"] == "Finance"]
    assert all(x[scim.ENTERPRISE_SCHEMA]["manager"]["value"] == noura["id"]
               for x in finance_staff if x["id"] != noura["id"])
    assert khalid[scim.ENTERPRISE_SCHEMA]["manager"]["value"] == u["falqarni@phantom.lab"]["id"]  # a department head reports to an executive
    g = groups(server)
    admins = {m["value"] for m in g["Domain Admins"]["members"]}
    assert admins == {x["id"] for x in u.values() if x["userName"].startswith("adm.")}
    assert out["members_added"] == sum(len(x["members"]) for x in g.values())
    assert "Full Sync" in out["next_step"]

    before = len(server.requests)
    again = connector.phantom_provision_directory()
    assert again["ok"] and again["users"]["unchanged"] == 64 and again["groups"]["existing"] == 13
    assert again["members_added"] == 0
    assert "POST" not in server.methods()[before:] and "PATCH" not in server.methods()[before:]


def test_provision_repairs_drift_with_path_based_patches(server):
    connector.phantom_provision_directory()
    noura = users(server)["nalharbi@phantom.lab"]
    noura["title"] = "Intern"
    noura[scim.ENTERPRISE_SCHEMA]["department"] = "Legal"
    before = len(server.requests)
    out = connector.phantom_provision_directory()
    assert out["users"]["updated"] == 1 and out["users"]["unchanged"] == 63
    assert noura["title"] == "Finance Manager" and noura[scim.ENTERPRISE_SCHEMA]["department"] == "Finance"
    patches = [json.loads(r.content) for r in server.requests[before:] if r.method == "PATCH"]
    assert [op["path"] for op in patches[0]["Operations"]] == ["title", f"{scim.ENTERPRISE_SCHEMA}:department"]


def test_foreign_user_is_skipped_and_not_grouped(server):
    foreign = server.seed("Users", {"userName": "nalharbi@phantom.lab", "externalId": "entra:abc", "title": "Real"})
    out = connector.phantom_provision_directory()
    assert out["users"]["skipped"] == 1 and out["users"]["created"] == 63
    assert server.store["Users"][foreign["id"]]["title"] == "Real"
    finance = groups(server)["SG-Finance"]
    assert foreign["id"] not in {m["value"] for m in finance["members"]}


def test_refused_token_stops_at_the_first_call(server):
    server.fail_next = [httpx.Response(401, json={"detail": "invalid token"})]
    out = connector.phantom_provision_directory()
    assert out["ok"] is False and out["http_status"] == 401 and "token" in out["hint"]
    assert len(server.requests) == 1


def test_a_rejected_first_create_stops_before_any_group(server):
    server.fail_next = [httpx.Response(200, json={"totalResults": 0, "Resources": []}),
                        httpx.Response(400, json={"detail": "Attribute 'nickName' is not supported"})]
    out = connector.phantom_provision_directory()
    assert out["ok"] is False and out["http_status"] == 400 and "nickName" in out["error"]
    assert out["object"] == "user:falqarni@phantom.lab" and "hint" in out  # the CEO: managers come first
    assert server.methods() == ["GET", "POST"] and not server.store["Groups"]


def test_a_later_failure_is_recorded_and_the_run_continues(server):
    connector.phantom_provision_directory()
    del server.store["Users"][users(server)["kalotaibi@phantom.lab"]["id"]]
    real = server.handler

    def flaky(request):
        if request.method == "POST" and b"kalotaibi" in request.content:
            server.requests.append(request)
            return httpx.Response(409, json={"detail": "conflict"})
        return real(request)
    server.handler = flaky
    connector._transport = lambda: httpx.MockTransport(flaky)
    out = connector.phantom_provision_directory()
    assert out["ok"] is False and out["users"]["failed"] == 1 and out["users"]["unchanged"] == 63
    assert out["errors"] == [{"object": "user:kalotaibi@phantom.lab", "http_status": 409, "detail": "conflict"}]


def test_a_server_that_keeps_no_external_id(server):
    server.drop_external_id = True
    stranger = server.seed("Users", {"userName": "someone@phantom.lab"})
    out = connector.phantom_provision_directory()
    assert out["ok"] and out["users"]["created"] == 64
    assert not any("externalId" in u for u in server.store["Users"].values())
    again = connector.phantom_provision_directory()
    assert again["users"]["unchanged"] == 64 and again["users"]["skipped"] == 0
    assert connector.phantom_update_user("kalotaibi", title="CFO")["ok"]
    assert connector.phantom_update_user("someone", title="x")["ok"] is False
    assert connector.phantom_set_group_membership("Domain Admins", "kalotaibi")["changed"] is True
    listed = connector.phantom_list_directory(filter='userName eq "someone@phantom.lab"')
    assert listed["items"][0]["phantom"] is False
    gone = connector.phantom_remove_provisioned(confirm=True)
    assert gone["deleted_users"] == 64 and gone["deleted_groups"] == 13
    assert set(server.store["Users"]) == {stranger["id"]}


def test_rate_limit_is_retried(server):
    server.fail_next = [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(503)]
    out = connector.phantom_test_connection()
    assert out["ok"] and out["users_total"] == 0 and out["phantom_user_found"] is False


def test_misconfiguration_is_reported_without_a_call(monkeypatch):
    for base, token, words in ((BASE, "", "scimToken"), ("http://cie.example.test/scim", TOKEN, "https"),
                               ("", TOKEN, "scimBaseUrl")):
        monkeypatch.setattr(connector, "_settings", lambda b=base, t=token: {
            "base_url": b, "token": t, "organization": "", "style": "sam", "verify_tls": True, "timeout": 5.0})
        out = connector.phantom_test_connection()
        assert out["ok"] is False and words in out["error"]


# ── changes and cleanup ───────────────────────────────────────────────────

def test_update_user_and_membership(server):
    connector.phantom_provision_directory()
    out = connector.phantom_update_user("kalotaibi", title="CFO", active=False, manager="adm.ialkhalifa")
    assert out["ok"], out
    k = users(server)["kalotaibi@phantom.lab"]
    assert k["title"] == "CFO" and k["active"] is False
    assert k[scim.ENTERPRISE_SCHEMA]["manager"]["value"] == users(server)["adm.ialkhalifa@phantom.lab"]["id"]

    add = connector.phantom_set_group_membership("Domain Admins", "kalotaibi@phantom.lab")
    assert add["ok"] and add["changed"] is True
    assert k["id"] in {m["value"] for m in groups(server)["Domain Admins"]["members"]}
    again = connector.phantom_set_group_membership("Domain Admins", "kalotaibi")
    assert again["changed"] is False
    gone = connector.phantom_set_group_membership("Domain Admins", "kalotaibi", action="remove")
    assert gone["ok"] and k["id"] not in {m["value"] for m in groups(server)["Domain Admins"]["members"]}
    assert connector.phantom_set_group_membership("No Such", "kalotaibi")["ok"] is False
    made = connector.phantom_set_group_membership("SG-Red-Team", "kalotaibi", create_group=True)
    assert made["ok"] and groups(server)["SG-Red-Team"]["externalId"] == "phantom:group:SG-Red-Team"


def test_update_user_refuses_foreign_and_empty(server):
    server.seed("Users", {"userName": "boss@phantom.lab", "externalId": "okta:9"})
    assert "not created by Phantom" in connector.phantom_update_user("boss", title="x")["error"]
    connector.phantom_provision_directory()
    assert connector.phantom_update_user("nalharbi")["ok"] is False


def test_remove_provisioned_needs_confirm_and_spares_foreign(server):
    keep = server.seed("Users", {"userName": "real@phantom.lab", "externalId": "entra:1"})
    keep_group = server.seed("Groups", {"displayName": "Real Group"})
    connector.phantom_provision_directory()
    preview = connector.phantom_remove_provisioned()
    assert preview["confirmed"] is False and preview["users"] == 64 and preview["deleted_users"] == 0
    assert len(server.store["Users"]) == 65
    out = connector.phantom_remove_provisioned(confirm=True)
    assert out["ok"] and out["deleted_users"] == 64 and out["deleted_groups"] == 13
    assert set(server.store["Users"]) == {keep["id"]} and set(server.store["Groups"]) == {keep_group["id"]}


def test_list_directory_returns_summaries(server):
    connector.phantom_provision_directory()
    out = connector.phantom_list_directory("groups", filter='displayName eq "Domain Admins"')
    assert out["ok"] and out["total"] == 1
    assert out["items"][0] == {"id": groups(server)["Domain Admins"]["id"], "name": "Domain Admins", "members": 8,
                               "phantom": True}
    page = connector.phantom_list_directory(count=5, start_index=6)
    assert page["total"] == 64 and len(page["items"]) == 5 and page["start_index"] == 6
    assert set(page["items"][0]) == {"id", "user_name", "display_name", "title", "department", "manager_id",
                                     "active", "phantom"}
    assert connector.phantom_list_directory("Devices")["ok"] is False


def test_filter_values_are_quoted():
    assert scim.quote_filter_value('a"b\\c') == '"a\\"b\\\\c"'


def test_the_token_never_appears_in_a_result(server):
    results = [connector.phantom_test_connection(), connector.phantom_provision_directory(),
               connector.phantom_list_directory(), connector.phantom_remove_provisioned()]
    server.fail_next = [httpx.Response(401, json={"detail": "bad"})]
    results.append(connector.phantom_test_connection())
    for result in results:
        assert TOKEN not in json.dumps(result)
