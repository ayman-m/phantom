"""Test helper: the organization that reproduces the roster wec-sender used to hard-code.

`tests/fixtures/pre_organization_baseline.json` holds the old Directory (hosts, users, SIDs, addresses, home hosts) as it was
captured before the connector read the shared organization. `cut_organization()` writes that directory back as an
organization document, so the profile can be proven to produce byte-identical events from it. The administrators are people
whose own login is the `adm.` login, in the privileged groups (no separate admin account), the way the old roster had them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).parent / "fixtures" / "pre_organization_baseline.json"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def cut_organization() -> dict[str, Any]:
    fx = load_fixture()
    rid = lambda sid: int(sid.rsplit("-", 1)[1])
    hosts = [{"name": name, "role": role, "ip": ip, "rid": rid(sid), "domain_joined": True,
              "purpose": "Application server" if name.endswith("-APP01") else role, "network": "cut-net", "site": "CUT"}
             for name, _fqdn, ip, role, sid, _pid in fx["directory"]["hosts"]]
    people, services = [], []
    for login, display, sid, role, home in fx["directory"]["users"]:
        if role == "service":
            services.append({"login": login, "display_name": display, "kind": "service", "host": home, "rid": rid(sid),
                             "groups": ["SG-Service-Accounts"]})
            continue
        given, _, family = display.removesuffix(" (admin)").partition(" ")
        people.append({"login": login, "given_name": given, "family_name": family, "display_name": display,
                       "rid": rid(sid), "workstation": home,
                       "groups": ["SG-IT-Admins", "Domain Admins"] if role == "admin" else ["SG-Staff"]})
    return {
        "schema_version": 1, "id": "pre-organization-cut", "name": "Pre-organization roster", "domain": dict(fx["domain"]),
        # The old profile's business week: UTC+3, Sunday to Thursday, 07:00 to 17:00 local.
        "locale": {"timezone": "Asia/Riyadh", "utc_offset_hours": 3, "workweek": ["sun", "mon", "tue", "wed", "thu"],
                   "work_hours": {"start": "07:00", "end": "17:00"}},
        "networks": [{"id": "cut-unmanaged", "name": "unmanaged", "kind": "unmanaged", "range": "10.20.100.0-10.20.199.255"}],
        "groups": [{"name": "SG-Staff", "privileged": False}, {"name": "SG-Service-Accounts", "privileged": False},
                   {"name": "SG-IT-Admins", "privileged": True}, {"name": "Domain Admins", "privileged": True}],
        "people": people, "service_accounts": services, "hosts": hosts,
    }
