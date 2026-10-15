"""Test helper: the organization that reproduces the roster the windows profile used to hard-code, and the baseline harness.

`tests/fixtures/pre_organization_windows_baseline.json` holds what the `windows` profile produced BEFORE it read the shared
organization: the old directory (hosts, users, SIDs, addresses, home hosts) and one sha256 per scenario, seed and variant.
`cut_organization()` writes that directory back as an organization document, so the profile can be proven to produce
byte-identical events from it; `digests()` reproduces the capture (`json.dumps(sort_keys=True, default=str, indent=1)` of the
events; the capture passed `domain="lab.test"` where the profile now takes the organization `view`) so the same hashes can be computed from any organization.

The old administrators are people whose own login is the `adm.` login, in the privileged groups (no separate admin account),
as the old roster had them. The old roster never held a certificate authority, but the privileged_certificate_request recipe
named one (`PHCA01`) and now binds to the organization's by its purpose: the cut organization carries it as a `security` host
so it stays out of the server pool. The old Kerberoasting spread (weak_service_tickets) named hosts the old roster never had
(PHSRV-SQL02 ... web07) and the skill now names the organization's own servers, so that scenario has no byte-identical
counterpart: `FOLLOWS_THE_SKILL` lists the scenarios whose recipe changed with the skills after the baseline was captured.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).parent / "fixtures" / "pre_organization_windows_baseline.json"
SEED = "khalid.alotaibi"
FOLLOWS_THE_SKILL = ("weak_service_tickets",)
SEEDS = (1, 7)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


_PURPOSE = {"FS01": "File server", "APP01": "Application server", "SQL01": "SQL Server", "WEB01": "Internal web server"}
# The six ordinary groups the old admin_activity drew from, in the order that gave them RIDs 2101 to 2106.
_DEPARTMENT_GROUPS = ["SG-Finance", "SG-HR", "SG-Sales", "SG-Engineering", "SG-VPN-Users", "SG-Project-Atlas"]


def cut_organization() -> dict[str, Any]:
    fx = load_fixture()
    rid = lambda sid: int(sid.rsplit("-", 1)[1])
    hosts = []
    for name, _fqdn, ip, role, sid, _pid in fx["directory"]["hosts"]:
        purpose = {"dc": "Domain controller", "workstation": "Workstation"}.get(role) or _PURPOSE[name.split("-")[-1]]
        hosts.append({"name": name, "role": role, "ip": ip, "rid": rid(sid), "domain_joined": True, "purpose": purpose,
                      "network": "cut-net", "site": "CUT"})
    for extra in fx["extra_hosts"]:
        hosts.append({"name": extra["name"], "role": "security", "ip": "10.20.3.30", "domain_joined": True,
                      "purpose": extra["purpose"], "network": "cut-net", "site": "CUT"})
    people, services = [], []
    staff_index = 0
    for login, display, sid, role, home in fx["directory"]["users"]:
        if role == "service":
            services.append({"login": login, "display_name": display, "kind": "service", "host": home, "rid": rid(sid),
                             "groups": ["SG-Service-Accounts"]})
            continue
        given, _, family = display.removesuffix(" (admin)").partition(" ")
        if role == "admin":
            groups = ["SG-IT-Admins", "Domain Admins"]
        else:
            groups = [_DEPARTMENT_GROUPS[staff_index % len(_DEPARTMENT_GROUPS)]]
            staff_index += 1
        people.append({"login": login, "given_name": given, "family_name": family, "display_name": display,
                       "rid": rid(sid), "workstation": home, "groups": groups})
    return {
        "schema_version": 1, "id": "pre-organization-cut", "name": "Pre-organization roster", "domain": dict(fx["domain"]),
        # The old profile's business week: UTC+3, Sunday to Thursday, 07:00 to 17:00 local.
        "locale": {"timezone": "Asia/Riyadh", "utc_offset_hours": 3, "workweek": ["sun", "mon", "tue", "wed", "thu"],
                   "work_hours": {"start": "07:00", "end": "17:00"}},
        "networks": [{"id": "cut-unmanaged", "name": "unmanaged", "kind": "unmanaged", "range": "10.20.100.0-10.20.199.255"}],
        "groups": [*({"name": g, "privileged": False} for g in _DEPARTMENT_GROUPS),
                   {"name": "SG-Service-Accounts", "privileged": False},
                   {"name": "SG-IT-Admins", "privileged": True}, {"name": "Domain Admins", "privileged": True}],
        "people": people, "service_accounts": services, "hosts": hosts,
    }


def digest(obj: Any) -> str:
    """sha256 of the capture script's text for an object (`dump` in capture_baseline.py)."""
    text = json.dumps(obj, sort_keys=True, default=str, indent=1)
    return hashlib.sha256(text.encode()).hexdigest()


def outputs(profile, view) -> dict[str, Any]:
    """Every scenario's events for each seed and variant, keyed like the fixture's hashes ('dcsync.s1.plain'), plus 'sample',
    built from the organization `view`. An error is part of the behaviour and is recorded as {'error': ...}."""
    now = datetime.fromisoformat(load_fixture()["now"])
    out: dict[str, Any] = {}
    for scenario in profile.SCENARIOS:
        count = getattr(profile, "MIN_COUNT", {}).get(scenario) or getattr(profile, "DEFAULT_COUNT", {}).get(scenario) or 12
        for seed in SEEDS:
            for variant, kw in (("plain", {}), ("target", {"target_user": SEED})):
                try:
                    events = profile.build_events(scenario, count, view=view, now=now, seed=seed, **kw)
                except Exception as exc:
                    events = {"error": f"{type(exc).__name__}: {exc}"}
                out[f"{scenario}.s{seed}.{variant}"] = events
    out["sample"] = profile.sample_event(view=view, now=now)
    return out
