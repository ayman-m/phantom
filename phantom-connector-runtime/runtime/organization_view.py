"""The organization as the connectors need it: accounts, hosts, identities and the fresh-identity ranges.

`organization_reader.py` returns the raw document from the shared data volume; this module turns it into the handful of
views every connector shares (http-sender and wec-sender's Windows profiles, the Okta and cloud profiles, cie-sender, the
xlog worker defaults), so each connector writes no roster of its own and two connectors can never disagree about who the
organization is.

# What an account is

A person has a normal account (`login`) and, when they administer systems, a separate admin account
(`admin_account.login`). Service accounts and the break-glass account are accounts without a person. Every account has a
role: `service` for a service account, `admin` for an account that belongs to a privileged group (Domain Admins,
SG-IT-Admins: the accounts whose logons raise 4672), `staff` for the rest. The role comes from the groups, not from a name
prefix, so an organization that calls its admin accounts something else behaves the same.

# Test hook

Connector unit tests run outside a container, with no organization.db. They call `set_organization_loader(fn)` (see each
connector's tests/conftest.py) with a function returning a document, usually the bundled Phantom Lab YAML. Production code
never calls it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable

from runtime.organization_reader import OrganizationUnavailable, load_organization

_loader: Callable[[str | None], dict[str, Any]] | None = None


def set_organization_loader(fn: Callable[[str | None], dict[str, Any]] | None) -> None:
    """Replace the source of organization documents (tests only). None restores the shared-volume reader."""
    global _loader
    _loader = fn
    _views.clear()


@dataclass(frozen=True)
class Account:
    login: str
    display: str
    rid: int | None
    sid: str | None
    role: str                 # staff | admin | service
    kind: str                 # user | admin | service | break_glass
    person: str | None        # login of the person it belongs to (None for service and break-glass accounts)
    home: str | None          # the workstation a person's account works at, or the server a service account runs on
    groups: tuple[str, ...]
    employee_number: str | None
    active: bool              # False for a leaver's account


def derived_domain_sid(dns: str) -> str:
    """A stable domain SID for an organization that declares none: three 31-bit numbers from the domain name."""
    d = hashlib.sha256(dns.lower().encode()).digest()
    n = [int.from_bytes(d[i:i + 4], "big") & 0x7FFFFFFF for i in (0, 4, 8)]
    return f"S-1-5-21-{n[0]}-{n[1]}-{n[2]}"


class OrganizationView:
    """Read-only convenience over one organization document."""

    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.id: str = doc["id"]
        self.name: str = doc["name"]
        dom = doc["domain"]
        self.dns: str = dom["dns"].lower()
        self.netbios: str = dom["netbios"].upper()
        self.email_domain: str = (dom.get("email_domain") or dom["dns"]).lower()
        self.partner_domain: str | None = dom.get("partner_domain")
        self.sid_base: str = dom.get("sid") or derived_domain_sid(self.dns)
        locale = doc.get("locale") or {}
        self.timezone: str | None = locale.get("timezone")
        self.utc_offset_hours: int = int(locale.get("utc_offset_hours", 0))
        self.workweek: tuple[str, ...] = tuple(locale.get("workweek") or ("mon", "tue", "wed", "thu", "fri"))
        wh = locale.get("work_hours") or {"start": "08:00", "end": "17:00"}
        self.work_start_hour: int = int(wh["start"].split(":")[0])
        self.work_end_hour: int = int(wh["end"].split(":")[0])
        self._privileged = {g["name"] for g in doc.get("groups", []) if g.get("privileged")}
        self.hosts: list[dict[str, Any]] = list(doc.get("hosts", []))
        self._host_by_name = {h["name"].lower(): h for h in self.hosts}
        self.people: list[dict[str, Any]] = list(doc.get("people", []))
        self._person_by_login = {p["login"].lower(): p for p in self.people}
        self.accounts: list[Account] = self._build_accounts()
        self._account_by_login = {a.login.lower(): a for a in self.accounts}

    # ── identities ──────────────────────────────────────────────────────────────────────────────────────────────────

    def sid(self, rid: int | None) -> str | None:
        return f"{self.sid_base}-{rid}" if rid else None

    def _role(self, groups: list[str]) -> str:
        return "admin" if any(g in self._privileged for g in groups) else "staff"

    def _build_accounts(self) -> list[Account]:
        staff: list[Account] = []
        admins: list[Account] = []
        for p in self.people:
            leaver = "leaver" in p.get("flags", [])
            groups = list(p.get("groups", []))
            display = p.get("display_name") or f"{p['given_name']} {p['family_name']}"
            acct = Account(p["login"], display, p.get("rid"), self.sid(p.get("rid")), self._role(groups), "user",
                           p["login"], p["workstation"], tuple(groups), p.get("employee_number"), not leaver)
            (admins if acct.role == "admin" else staff).append(acct)
            adm = p.get("admin_account")
            if adm:
                ag = list(adm.get("groups", []))
                admins.append(Account(adm["login"], adm.get("display_name") or f"{display} (admin)", adm.get("rid"),
                                      self.sid(adm.get("rid")), "admin", "admin", p["login"], p["workstation"],
                                      tuple(ag), adm.get("employee_number") or p.get("employee_number"), True))
        services: list[Account] = []
        for s in self.doc.get("service_accounts", []):
            acct = Account(s["login"], s["display_name"], s.get("rid"), self.sid(s.get("rid")),
                           "service" if s["kind"] == "service" else "admin", s["kind"], None, s["host"],
                           tuple(s.get("groups", [])), s.get("employee_number"), True)
            (services if acct.role == "service" else admins).append(acct)  # break-glass is a privileged account
        return staff + admins + services

    def account(self, login: str) -> Account | None:
        return self._account_by_login.get((login or "").lower())

    def person(self, login: str) -> dict[str, Any] | None:
        return self._person_by_login.get((login or "").lower())

    def accounts_by_role(self, role: str, *, logs_on: bool = True) -> list[Account]:
        """Accounts of a role in organization order. With `logs_on`, a leaver's disabled account and the break-glass
        account are left out: they are the ones whose logon is the finding, never part of normal traffic."""
        out = [a for a in self.accounts if a.role == role]
        return [a for a in out if a.active and a.kind != "break_glass"] if logs_on else out

    def people_with_flag(self, flag: str) -> list[dict[str, Any]]:
        return [p for p in self.people if flag in p.get("flags", [])]

    def email(self, person: dict[str, Any]) -> str:
        return person["email"]

    # ── hosts ───────────────────────────────────────────────────────────────────────────────────────────────────────

    def host(self, name: str) -> dict[str, Any] | None:
        return self._host_by_name.get((name or "").split(".")[0].lower())

    def hosts_by_role(self, role: str) -> list[dict[str, Any]]:
        return [h for h in self.hosts if h["role"] == role]

    def fqdn(self, host: dict[str, Any]) -> str:
        return f"{host['name']}.{self.dns}"

    def workstation_of(self, login: str) -> dict[str, Any] | None:
        p = self.person(login)
        if p is None:
            a = self.account(login)
            return self.host(a.home) if a and a.home else None
        return self.host(p["workstation"])

    # ── fresh identities (attack recipes mint never-seen actors, hosts and addresses) ───────────────────────────────

    def fresh_host_prefix(self) -> str:
        """The naming prefix of this organization's workstations, e.g. `PHWS-` for PHWS-001."""
        counts: dict[str, int] = {}
        for h in self.hosts_by_role("workstation"):
            m = re.fullmatch(r"(.*?)(\d+)", h["name"])
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        if not counts:
            raise OrganizationUnavailable(
                f"organization {self.id!r} has no workstations, so a scenario cannot mint a new host name")
        return max(counts, key=counts.get)

    def fresh_ip_range(self) -> tuple[int, int]:
        """(first, last) address, as integers, of the pool where unmanaged and newly seen devices live: the network of kind
        `unmanaged`. Attack recipes draw never-seen internal addresses from it."""
        for n in self.doc.get("networks", []):
            if n.get("kind") == "unmanaged":
                if n.get("cidr"):
                    net = ipaddress.ip_network(n["cidr"], strict=False)
                    return int(net.network_address) + 1, int(net.broadcast_address) - 1
                lo, hi = n["range"].split("-", 1)
                return int(ipaddress.ip_address(lo)), int(ipaddress.ip_address(hi))
        raise OrganizationUnavailable(
            f"organization {self.id!r} has no network of kind 'unmanaged'; add one (the pool for newly seen devices) so "
            "scenarios that need a never-seen internal address can draw from it")

    def is_internal(self, ip: str) -> bool:
        """Whether `ip` belongs to one of the organization's networks."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        for n in self.doc.get("networks", []):
            if n.get("cidr"):
                if addr in ipaddress.ip_network(n["cidr"], strict=False):
                    return True
            else:
                lo, hi = n["range"].split("-", 1)
                if ipaddress.ip_address(lo) <= addr <= ipaddress.ip_address(hi):
                    return True
        return False


_views: dict[tuple[str, str | None, int], OrganizationView] = {}
_views_lock = threading.Lock()


def get_view(pinned_id: str | None = None) -> OrganizationView:
    """The view of the pinned or active organization, loaded NOW (never at import: a fresh install can start a connector
    before the agent has created organization.db). Views are cached per (id, version-bearing document identity)."""
    doc = (_loader or load_organization)(pinned_id)
    # The reader returns the same dict object while (id, version) is unchanged, so object identity is a safe cache key.
    key = (doc["id"], pinned_id, id(doc))
    with _views_lock:
        view = _views.get(key)
        if view is None:
            if len(_views) > 8:
                _views.clear()
            view = _views[key] = OrganizationView(doc)
        return view
