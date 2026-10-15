"""The `windows` event profile: structured Windows Security events for the `cribl_windows_events` destination.

Nothing about the domain is written here. The domain names, the domain controllers, servers and workstations, the people and
their admin, service and break-glass accounts all come from the ACTIVE ORGANIZATION, read from the shared organization store
when a tool is called (never at import: a fresh install can start the connector before the store exists). A missing
organization, or one that lacks a host the scenario must name, is a broken install: the call fails with a clear error and no
built-in roster takes over.

An event is the structured dict `windows_events.prepare` takes (the `wec-sender.send_events` shape: `event_id`, `computer`,
`time`, `event_data`, and for the ids Windows' catalogue here does not hold `provider` and `rendering`); the connector
renders it to Windows Event XML and posts the XML as a plain string. Three kinds of scenario:

  baseline_logons   benign logon traffic (4624, 4672 for administrators, 4634) of the organization's domain. A port of the
                    `windows` profile of wec-sender (`wec-sender/src/profiles/windows.py`): same mapping of the organization
                    onto hosts and accounts, same SIDs and addresses, same session shapes, so an event generated here and one
                    generated there for the same seed render to the same XML (tests/test_windows_profile.py compares them).
  admin_activity    benign administration by the organization's administrator accounts: helpdesk password resets (4724) and
                    unlocks (4767) of ordinary users, ordinary user accounts created (4720), ordinary users added to and
                    removed from the organization's ordinary department groups (4728 / 4729) and 4738 changes of display
                    name, script path, home directory or password age. Identities are stable (the organization's); the
                    groups are never a privileged one, and the new accounts are named like staff.
  <attack>          fifteen scenarios, one per Windows trigger skill (`bundles/spark/mcp/skills/workflows/trigger_<name>_alert`).
                    Each sends the SAME events as the skill's JSON block: `windows_recipes.json` holds those blocks verbatim,
                    with their `<CHANGE: label>` placeholders, and every call fills the placeholders as the skill's table
                    says: the times as now minus N seconds (relative to the window's end), and every identity (actor,
                    RIDs, logon id, host and account names, addresses) NEW. A scheduled call therefore fires its detector
                    the way a manual replay of the skill does. tests/test_windows_profile.py checks the embedded blocks
                    against the skill files and the rendered XML against a filled skill block.

The skills were written against Phantom Lab and name its hosts and domain (`_LAB_HOSTS`, `_SKILL_NAMES` below). Before a recipe
is filled, every such name is rewritten to the active organization's: the domain, NetBIOS name, realm, DN and SID base to the
organization's; each lab host to the organization's host of the same kind, found by its role and `purpose` ("PHDC01" and
"PHDC02" to its first and second domain controller, "PHSRV-SQL01" to its SQL server, "PHSRV-CA01" to its certificate
authority, ...). An organization that has no host of a kind a scenario names cannot carry that scenario: the call fails with a
clear error saying which host to add, and the other scenarios still work. The skills themselves are not edited: they stay the
single source of the recipes (`windows_recipes.json` is their first JSON blocks, regenerated when a skill changes).

Freshness. The detectors count what an actor did for the first time in 30 days and deduplicate for a day, so a call must
look like a first-time actor. Identity values are drawn at random from wide ranges and, for unseeded calls, never repeat
within the process (`_Source`): names carry a random token, RIDs are 100000 to 90 million (above every RID an organization
holds and the earlier lab runs use), hosts are the organization's workstation prefix and five digits (for Phantom Lab,
`PHWS-12345`; its managed workstations have three), and addresses are drawn from the organization's `unmanaged` network, the
pool for newly seen devices. A seeded call (tests) is reproducible and tracks repeats only within itself.
"""
from __future__ import annotations

import functools
import hashlib
import ipaddress
import json
import random
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import OrganizationView, get_view

from . import _fresh

# The profile interface (see profiles/__init__.py).
NAME = "windows"
DESCRIPTION = ("Windows Security events for the cribl_windows_events destination: baseline_logons and admin_activity "
               "(benign, the organization's domain) and one scenario per Windows trigger skill (privileged group adds, DCSync, "
               "Kerberos, lockouts, account deletions, hidden accounts, shadow credentials, ...).")
EXPECTED_DATASET = "cribl_windows_events"
EXPECTED_DATASETS = ("cribl_windows_events",)
CRIBL_DESTINATIONS = ("cribl_windows_events",)
DEFAULT_DESTINATION = "cribl_windows_events"
CRIBL_ONLY = True
# The events are structured Windows events, not vendor objects: the tool layer renders them to XML and never sends them
# to any other kind of destination.
WINDOWS_EVENTS = True
TEST_ID_FIELD = "event_id"
TIME_FIELD = "time"

PROVIDER = "Microsoft-Windows-Security-Auditing"
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}   # Python's datetime.weekday()
_SERVER_WEIGHT_HEAD = (4, 2)      # the first server is the busiest, the second next; every later one weighs 1
FIRST_DEPARTMENT_GROUP_RID = 2101  # organization groups carry no RID: the n-th ordinary group of the document gets 2100 + n


def active_view() -> OrganizationView:
    """The active organization, read now. The tools pass the view they read (the instance may pin one); this is for callers
    that hold none (tests, scripts). Raises OrganizationUnavailable."""
    return get_view()


def _unusable(view: OrganizationView, why: str) -> OrganizationUnavailable:
    """An organization that cannot carry the scenario is a broken install: OrganizationUnavailable, which the tool layer
    returns as `{ok: false, error}` saying what to add."""
    return OrganizationUnavailable(f"organization {view.id!r} cannot drive the windows profile: {why}")


@dataclass(frozen=True)
class Host:
    name: str
    fqdn: str
    ip: str
    role: str          # dc | server | workstation (| security: a domain-joined tool server)
    sid: str           # the machine account's SID
    lsass_pid: int

    @property
    def account(self) -> str:
        return self.name + "$"


@dataclass(frozen=True)
class User:
    login: str
    display: str
    sid: str
    role: str          # staff | admin | service
    home: str          # name of the home workstation (service accounts: the server they run on)


class Directory:
    """Hosts, accounts and groups of the organization's Windows domain, for the benign scenarios. Immutable after
    construction; every lookup is deterministic (a pure function of the organization), so the same login always has the same
    SID and home workstation.

    Hosts are the organization's domain-joined hosts that have a `rid` and an address; the machine account's SID is
    `<domain sid>-<rid>`. Accounts keep the organization's order (staff, administrators, service accounts); a leaver's account
    and the break-glass account never appear in baseline traffic, they are the findings. Build one with `directory()`;
    `Directory(view)` is for callers that already hold an OrganizationView."""

    def __init__(self, view: OrganizationView) -> None:
        self.view = view
        self.organization = view.id
        self.netbios, self.dns, self.domain_sid = view.netbios, view.dns, view.sid_base
        self.dn = ",".join(f"DC={part}" for part in view.dns.split("."))
        # When workstation sign-ins are likely is the organization's locale: its UTC offset, working week and office hours.
        self.utc_offset_hours = view.utc_offset_hours
        self.workdays = tuple(_WEEKDAYS[day[:3].lower()] for day in view.workweek)
        self.work_hours = (view.work_start_hour, view.work_end_hour)
        self.hosts: list[Host] = []
        for h in view.hosts:
            if not h.get("rid") or not h.get("ip") or not h.get("domain_joined", True):
                continue                       # appliances, cloud and DMZ machines are not in the Windows domain
            self.hosts.append(Host(h["name"], view.fqdn(h), h["ip"], h["role"], view.sid(h["rid"]),
                                   600 + hashlib.sha256(h["name"].encode()).digest()[0] % 200))
        self._by_name = {h.name.upper(): h for h in self.hosts}
        self.workstations = [h for h in self.hosts if h.role == "workstation"]
        self.servers = [h for h in self.hosts if h.role == "server"]
        self.dcs = [h for h in self.hosts if h.role == "dc"]
        self.users: list[User] = []
        for role in ("staff", "admin", "service"):
            for account in view.accounts_by_role(role):
                if not account.sid:
                    raise _unusable(view, f"account {account.login!r} has no rid, so it has no SID")
                home = self._by_name.get((account.home or "").split(".")[0].upper())
                if home is None:
                    raise _unusable(view, f"account {account.login!r} works at {account.home!r}, which is not a domain-joined "
                                          "host with a rid and an address")
                self.users.append(User(account.login, account.display, account.sid, role, home.name))
        self.staff = [u for u in self.users if u.role == "staff"]
        self.admins = [u for u in self.users if u.role == "admin"]
        self.services = [u for u in self.users if u.role == "service"]
        missing = [what for what, items in (("domain controller", self.dcs), ("server", self.servers),
                                            ("staff account", self.staff), ("administrator account", self.admins),
                                            ("service account", self.services)) if not items]
        if missing:
            raise _unusable(view, f"it has no domain-joined {', no '.join(missing)}")
        purpose = {h["name"].upper(): (h.get("purpose") or "").lower() for h in view.hosts}
        # Administration is written on a domain controller that takes writes, never on a read-only one.
        self.writable_dcs = [h for h in self.dcs if "read-only" not in purpose.get(h.name.upper(), "")]
        self.server_weights = list((_SERVER_WEIGHT_HEAD + (1,) * len(self.servers))[:len(self.servers)])
        # Service accounts authenticate from the application server (else the first server).
        self.service_source = next((s for s in self.servers if "application" in purpose.get(s.name.upper(), "")), self.servers[0])
        self._file_server = next((s for s in self.servers if "file server" in purpose.get(s.name.upper(), "")), None)
        # The ordinary department groups: the document's non-privileged groups that no service account belongs to. RIDs follow
        # the document's order among its non-privileged groups, as an AD would have allocated them at creation.
        ordinary = [g["name"] for g in view.doc.get("groups", []) if not g.get("privileged")]
        service_groups = {g for a in view.accounts_by_role("service", logs_on=False) for g in a.groups}
        self.groups: list[tuple[str, str]] = [
            (name, f"{self.domain_sid}-{FIRST_DEPARTMENT_GROUP_RID - 1 + n}")
            for n, name in enumerate(ordinary, 1) if name not in service_groups]

    def host(self, name: str) -> Host:
        try:
            return self._by_name[name.split(".")[0].upper()]
        except KeyError:
            raise _unusable(self.view, f"{name!r} is not a domain-joined host with a rid and an address") from None

    @property
    def file_server(self) -> Host:
        if self._file_server is None:
            raise _unusable(self.view, "it has no file server (a server whose purpose says 'file server'), which holds the "
                                       "home directories")
        return self._file_server

    def new_hire_sid(self, login: str) -> str:
        """The SID of an account the organization does not hold: a stable one derived from the login (as wec-sender's
        `user_sid`)."""
        return f"{self.domain_sid}-{5000 + int(hashlib.sha1(login.lower().encode()).hexdigest(), 16) % 90000}"

    def is_business_time(self, when: datetime) -> bool:
        local = when + timedelta(hours=self.utc_offset_hours)
        return local.weekday() in self.workdays and self.work_hours[0] <= local.hour < self.work_hours[1]


_directory_cache: tuple[OrganizationView, Directory] | None = None


def directory(view: OrganizationView | None = None) -> Directory:
    """The Directory of `view` (default: the active organization), built NOW (never at import). It is cached per view object,
    and a view is replaced whenever the organization changes, so an edit shows up on the next call."""
    global _directory_cache
    view = view or active_view()
    cached = _directory_cache
    if cached is None or cached[0] is not view:
        cached = _directory_cache = (view, Directory(view))
    return cached[1]


# -- event plumbing -------------------------------------------------------------------------------------------------------

def iso(when: datetime) -> str:
    """An event's `time`: UTC with microseconds, which `windows_events.parse_time` reads back exactly."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _guid(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return "{" + f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}".upper() + "}"


def logon_id(computer: str, login: str, when: datetime, salt: int = 0) -> str:
    """A logon session id: unique per (computer, login, time); the 4634 reuses it."""
    h = hashlib.sha256(f"{computer}|{login}|{when.isoformat()}|{salt}".encode()).digest()
    return f"0x{int.from_bytes(h[:4], 'big') % 0xFFF000 + 0x10000:X}"


def _event(event_id: int, computer: str, when: datetime, data: dict[str, str], **extra: Any) -> dict[str, Any]:
    """A structured event whose `time` is still a datetime (`_finish` turns it into text once the events are ordered)."""
    return {"event_id": event_id, "computer": computer, "channel": "Security", "time": when, **extra, "event_data": data}


def _finish(events: list[dict[str, Any]], rank: dict[int, int] | None = None) -> list[dict[str, Any]]:
    """Order by time (then by `rank` of the event id, so a logon precedes its 4672) and render the times as text."""
    ranks = rank or {}
    events.sort(key=lambda e: (e["time"], ranks.get(e["event_id"], 9)))
    return [{**e, "time": iso(e["time"])} for e in events]


# -- baseline_logons (a port of wec-sender's) -------------------------------------------------------------------------------

def _logon_data(d: Directory, kind: str, user: User, target: Host, source: Host, lid: str, port: int) -> dict[str, str]:
    """EventData of a 4624 for one kind of logon: interactive | unlock | cached | network | ntlm | rdp."""
    admin = user.role == "admin"
    data = {
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": target.account, "SubjectDomainName": d.netbios,
        "SubjectLogonId": "0x3E7", "TargetUserSid": user.sid, "TargetUserName": user.login,
        "TargetDomainName": d.netbios, "TargetLogonId": lid, "WorkstationName": source.name,
        "IpAddress": source.ip, "IpPort": str(port),
        "ElevatedToken": "%%1842" if admin else "%%1843", "LogonGuid": "{00000000-0000-0000-0000-000000000000}",
    }
    if kind in ("interactive", "unlock", "cached"):
        data.update(LogonType={"interactive": "2", "unlock": "7", "cached": "11"}[kind],
                    LogonProcessName="User32 ", AuthenticationPackageName="Negotiate", LmPackageName="-",
                    KeyLength="0", ProcessId=f"0x{target.lsass_pid + 100:X}",
                    ProcessName="C:\\Windows\\System32\\winlogon.exe", IpPort="0",
                    LogonGuid=_guid("guid", target.name, user.login, lid))
    elif kind == "rdp":
        data.update(LogonType="10", LogonProcessName="User32 ", AuthenticationPackageName="Negotiate",
                    LmPackageName="-", KeyLength="0", ProcessId=f"0x{target.lsass_pid + 200:X}",
                    ProcessName="C:\\Windows\\System32\\svchost.exe", IpPort="0",
                    LogonGuid=_guid("guid", target.name, user.login, lid))
    elif kind == "network":
        data.update(LogonType="3", LogonProcessName="Kerberos", AuthenticationPackageName="Kerberos",
                    LmPackageName="-", KeyLength="0", LogonGuid=_guid("guid", target.name, user.login, lid))
    else:  # ntlm
        data.update(LogonType="3", LogonProcessName="NtLmSsp ", AuthenticationPackageName="NTLM",
                    LmPackageName="NTLM V2", KeyLength="128")
    return data


def _session(d: Directory, kind: str, user: User, target: Host, source: Host, when: datetime, logoff: datetime,
             rng: random.Random, salt: int) -> list[dict[str, Any]]:
    """4624 (+ 4672 for administrators) at `when`, 4634 at `logoff`, all sharing one logon id."""
    lid = logon_id(target.fqdn, user.login, when, salt)
    data = _logon_data(d, kind, user, target, source, lid, 49152 + rng.randrange(16000))
    common = {"process_id": target.lsass_pid}
    events = [_event(4624, target.name, when, data, activity_id=_guid("act", lid, target.name), **common)]
    if user.role == "admin":
        events.append(_event(4672, target.name, when + timedelta(milliseconds=1), {
            "SubjectUserSid": user.sid, "SubjectUserName": user.login, "SubjectDomainName": d.netbios,
            "SubjectLogonId": lid}, **common))
    events.append(_event(4634, target.name, logoff, {
        "TargetUserSid": user.sid, "TargetUserName": user.login, "TargetDomainName": d.netbios,
        "TargetLogonId": lid, "LogonType": data["LogonType"]}, **common))
    return events


_CATEGORIES = ("workstation", "server", "dc", "service", "rdp")
_WEIGHTS_BUSINESS = (50, 25, 12, 8, 5)
_WEIGHTS_QUIET = (8, 12, 10, 55, 15)


def baseline_logons(d: Directory, count: int, start: datetime, end: datetime, rng: random.Random) -> list[dict[str, Any]]:
    """Benign logon traffic shaped by the time of day: workstation sign-ins (interactive, unlock, cached) in business hours,
    network logons on servers and DCs, service accounts around the clock, a little admin RDP.

    Exactly `count` events made of whole sessions (4624, 4672 for administrators, 4634), so every 4634 follows its 4624 with
    the same logon id and every administrator logon has its 4672. When `count` leaves one event over, it is one last 4624 (a
    session still open): at most one session in a result is open. A logoff that would fall after the window ends is placed at
    a random moment between its logon and the end, so a short window does not pile every logoff on one timestamp.

    The draws are those of wec-sender's `baseline_logons`, in the same order: do not reorder them."""
    span = (end - start).total_seconds()
    people = d.staff + d.admins
    events: list[dict[str, Any]] = []
    salt = 0
    while len(events) < count:
        remaining = count - len(events)
        salt += 1
        when = start + timedelta(seconds=rng.uniform(0, span * 0.8))
        weights = _WEIGHTS_BUSINESS if d.is_business_time(when) else _WEIGHTS_QUIET
        category = rng.choices(_CATEGORIES, weights)[0]
        # A 2-event gap cannot hold an administrator session (three events): keep to staff and service accounts.
        small = remaining < 3
        if small and category == "rdp":
            category = "server"

        def logoff_after(low: float, high: float) -> datetime:
            natural = when + timedelta(seconds=rng.uniform(low, high))
            if natural <= end:
                return natural
            return when + timedelta(seconds=rng.uniform(1.0, max((end - when).total_seconds(), 1.0)))

        if category == "workstation":
            user = rng.choice(d.staff) if (small or rng.random() < 0.85) else rng.choice(d.admins)
            kind = rng.choices(("interactive", "unlock", "cached"), (55, 30, 15))[0]
            host = d.host(user.home)
            session = _session(d, kind, user, host, host, when, logoff_after(1200, 14400), rng, salt)
        elif category == "server":
            user = rng.choice(d.staff)
            host = rng.choices(d.servers, d.server_weights)[0]
            kind = "network" if rng.random() < 0.65 else "ntlm"
            session = _session(d, kind, user, host, d.host(user.home), when, logoff_after(5, 900), rng, salt)
        elif category == "dc":
            user = rng.choice(d.staff if small else people)
            kind = "network" if rng.random() < 0.8 else "ntlm"
            session = _session(d, kind, user, rng.choice(d.dcs), d.host(user.home), when, logoff_after(1, 120), rng, salt)
        elif category == "service":
            user = rng.choice(d.services)
            kind = "network" if rng.random() < 0.5 else "ntlm"
            session = _session(d, kind, user, d.host(user.home), d.service_source, when, logoff_after(30, 1800), rng, salt)
        else:
            user = rng.choice(d.admins)
            host = rng.choice(d.servers + d.dcs)
            session = _session(d, "rdp", user, host, d.host(user.home), when, logoff_after(300, 3600), rng, salt)
        if remaining == 1:
            if user.role == "admin":
                continue                      # its 4624 would lack the 4672: draw another user
            session = session[:1]             # the one open session
        elif len(session) > remaining:
            continue
        events += session
    return _finish(events, {4624: 0, 4672: 1, 4634: 2})


# -- admin_activity ---------------------------------------------------------------------------------------------------------

# The groups of admin_activity are the Directory's ordinary department groups (global security groups): their RIDs sit below the
# fresh-identity range and above the accounts'.
_NEW_HIRE_FIRST = ("Hanan", "Salman", "Mona", "Rakan", "Aisha", "Badr", "Ghada", "Fahad")
_NEW_HIRE_LAST = ("Alshehri", "Alharbi", "Alsaadi", "Alnajjar", "Alomari", "Alhazmi")
_ADMIN_KINDS = (("reset_password", 25), ("unlock", 25), ("group_add", 14), ("group_remove", 9), ("change", 22), ("create", 5))

_MESSAGES = {
    4720: "A user account was created.\n\nSubject:\n\tSecurity ID:\t\t{SubjectUserSid}\n\tAccount Name:\t\t{SubjectUserName}\n"
          "\tAccount Domain:\t\t{SubjectDomainName}\n\tLogon ID:\t\t{SubjectLogonId}\n\nNew Account:\n\tSecurity ID:\t\t{TargetSid}\n"
          "\tAccount Name:\t\t{TargetUserName}\n\tAccount Domain:\t\t{TargetDomainName}\n\nAttributes:\n"
          "\tSAM Account Name:\t{SamAccountName}\n\tDisplay Name:\t\t{DisplayName}\n\tUser Principal Name:\t{UserPrincipalName}",
    4724: "An attempt was made to reset an account's password.\n\nSubject:\n\tSecurity ID:\t\t{SubjectUserSid}\n"
          "\tAccount Name:\t\t{SubjectUserName}\n\tAccount Domain:\t\t{SubjectDomainName}\n\tLogon ID:\t\t{SubjectLogonId}\n\n"
          "Target Account:\n\tSecurity ID:\t\t{TargetSid}\n\tAccount Name:\t\t{TargetUserName}\n\tAccount Domain:\t\t{TargetDomainName}",
    4767: "A user account was unlocked.\n\nSubject:\n\tSecurity ID:\t\t{SubjectUserSid}\n\tAccount Name:\t\t{SubjectUserName}\n"
          "\tAccount Domain:\t\t{SubjectDomainName}\n\tLogon ID:\t\t{SubjectLogonId}\n\nTarget Account:\n"
          "\tSecurity ID:\t\t{TargetSid}\n\tAccount Name:\t\t{TargetUserName}\n\tAccount Domain:\t\t{TargetDomainName}",
    4728: "A member was added to a security-enabled global group.\n\nSubject:\n\tSecurity ID:\t\t{SubjectUserSid}\n"
          "\tAccount Name:\t\t{SubjectUserName}\n\tAccount Domain:\t\t{SubjectDomainName}\n\tLogon ID:\t\t{SubjectLogonId}\n\n"
          "Member:\n\tSecurity ID:\t\t{MemberSid}\n\tAccount Name:\t\t{MemberName}\n\nGroup:\n\tSecurity ID:\t\t{TargetSid}\n"
          "\tGroup Name:\t\t{TargetUserName}\n\tGroup Domain:\t\t{TargetDomainName}\n\nAdditional Information:\n\tPrivileges:\t\t-",
    4729: "A member was removed from a security-enabled global group.\n\nSubject:\n\tSecurity ID:\t\t{SubjectUserSid}\n"
          "\tAccount Name:\t\t{SubjectUserName}\n\tAccount Domain:\t\t{SubjectDomainName}\n\tLogon ID:\t\t{SubjectLogonId}\n\n"
          "Member:\n\tSecurity ID:\t\t{MemberSid}\n\tAccount Name:\t\t{MemberName}\n\nGroup:\n\tSecurity ID:\t\t{TargetSid}\n"
          "\tGroup Name:\t\t{TargetUserName}\n\tGroup Domain:\t\t{TargetDomainName}\n\nAdditional Information:\n\tPrivileges:\t\t-",
    4738: "A user account was changed.\n\nSubject:\n\tSecurity ID:\t\t{SubjectUserSid}\n\tAccount Name:\t\t{SubjectUserName}\n"
          "\tAccount Domain:\t\t{SubjectDomainName}\n\tLogon ID:\t\t{SubjectLogonId}\n\nTarget Account:\n"
          "\tSecurity ID:\t\t{TargetSid}\n\tAccount Name:\t\t{TargetUserName}\n\tAccount Domain:\t\t{TargetDomainName}\n\n"
          "Changed Attributes:\n\tSAM Account Name:\t{SamAccountName}\n\tDisplay Name:\t{DisplayName}\n"
          "\tUser Principal Name:\t{UserPrincipalName}\n\tHome Directory:\t{HomeDirectory}\n\tHome Drive:\t{HomePath}\n"
          "\tScript Path:\t{ScriptPath}\n\tProfile Path:\t{ProfilePath}\n\tUser Workstations:\t{UserWorkstations}\n"
          "\tPassword Last Set:\t{PasswordLastSet}\n\tAccount Expires:\t{AccountExpires}\n\tPrimary Group ID:\t{PrimaryGroupId}\n"
          "\tAllowedToDelegateTo:\t{AllowedToDelegateTo}\n\tOld UAC Value:\t{OldUacValue}\n\tNew UAC Value:\t{NewUacValue}\n"
          "\tUser Account Control:\t{UserAccountControl}\n\tUser Parameters:\t{UserParameters}\n\tSID History:\t{SidHistory}\n"
          "\tLogon Hours:\t{LogonHours}\n\nAdditional Information:\n\tPrivileges:\t\t-",
}
_TASKS = {4720: "User Account Management", 4724: "User Account Management", 4767: "User Account Management",
          4738: "User Account Management", 4728: "Security Group Management", 4729: "Security Group Management"}
# Every 4738 attribute that a change leaves alone is "-" (the order is the skills' 4738 block's, after its Dummy and the
# subject, target and privilege fields).
_UNCHANGED_4738 = {"SamAccountName": "-", "DisplayName": "-", "UserPrincipalName": "-", "HomeDirectory": "-",
                   "HomePath": "-", "ScriptPath": "-", "ProfilePath": "-", "UserWorkstations": "-", "PasswordLastSet": "-",
                   "AccountExpires": "-", "PrimaryGroupId": "-", "AllowedToDelegateTo": "-", "OldUacValue": "-",
                   "NewUacValue": "-", "UserAccountControl": "-", "UserParameters": "-", "SidHistory": "-", "LogonHours": "-"}


def _structured(event_id: int, computer: str, when: datetime, data: dict[str, str]) -> dict[str, Any]:
    """A non-catalogued event: it carries its provider, message and task, with the message filled from `data`."""
    message = re.sub(r"\{(\w+)\}", lambda m: data.get(m.group(1), "-"), _MESSAGES[event_id])
    return _event(event_id, computer, when, data, provider=PROVIDER, rendering={"message": message, "task": _TASKS[event_id]})


def _subject(d: Directory, admin: User, session: str) -> dict[str, str]:
    return {"SubjectUserSid": admin.sid, "SubjectUserName": admin.login, "SubjectDomainName": d.netbios, "SubjectLogonId": session}


def _local_time_text(d: Directory, when: datetime) -> str:
    """Windows' text for a date in a 4738 message: `10/6/2026 9:14:03 AM` in the controller's local time."""
    local = when + timedelta(hours=d.utc_offset_hours)
    return f"{local.month}/{local.day}/{local.year} {local.hour % 12 or 12}:{local:%M:%S} {'AM' if local.hour < 12 else 'PM'}"


def admin_activity(d: Directory, count: int, start: datetime, end: datetime, rng: random.Random) -> list[dict[str, Any]]:
    """`count` ordinary administration events by the organization's administrator accounts on the domain controllers. The first
    half of the administrators is the helpdesk (resets, unlocks, attribute changes), the other half the directory team (account
    creation, group membership); a single administrator is both. Groups are the organization's ordinary department groups.
    An administrator's logon id is the same for the whole UTC day, like one long session."""
    if not d.writable_dcs:
        raise _unusable(d.view, "it has no writable domain controller to administer")
    if not d.groups:
        raise _unusable(d.view, "it has no ordinary (non-privileged) group that no service account belongs to, so there is "
                                "nothing to add users to")
    span = (end - start).total_seconds()
    half = len(d.admins) // 2
    helpdesk, directory_team = (d.admins[:half], d.admins[half:]) if half else (d.admins, d.admins)
    events: list[dict[str, Any]] = []
    for _ in range(count):
        when = start + timedelta(seconds=rng.uniform(0, span))
        kind = _fresh.weighted(rng, _ADMIN_KINDS)
        dc = rng.choice(d.writable_dcs)
        admin = rng.choice(helpdesk if kind in ("reset_password", "unlock", "change") else directory_team)
        session = logon_id(dc.fqdn, admin.login, datetime(when.year, when.month, when.day, tzinfo=timezone.utc))
        subject = _subject(d, admin, session)
        target = rng.choice(d.staff)
        if kind in ("reset_password", "unlock"):
            data = {"TargetUserName": target.login, "TargetDomainName": d.netbios, "TargetSid": target.sid, **subject}
            events.append(_structured(4724 if kind == "reset_password" else 4767, dc.name, when, data))
        elif kind in ("group_add", "group_remove"):
            group, group_sid = rng.choice(d.groups)
            data = {"MemberName": f"CN={target.display},OU=Users,{d.dn}", "MemberSid": target.sid, **subject,
                    "TargetUserName": group, "TargetDomainName": d.netbios, "TargetSid": group_sid, "PrivilegeList": "-"}
            events.append(_structured(4728 if kind == "group_add" else 4729, dc.name, when, data))
        elif kind == "change":
            change = rng.choice(("DisplayName", "ScriptPath", "HomeDirectory", "PasswordLastSet"))
            changed = {
                "DisplayName": lambda: {"DisplayName": target.display},
                "ScriptPath": lambda: {"ScriptPath": "logon.bat"},
                "HomeDirectory": lambda: {"HomeDirectory": f"\\\\{d.file_server.name}\\home$\\{target.login}", "HomePath": "H:"},
                "PasswordLastSet": lambda: {"PasswordLastSet": _local_time_text(d, when)},
            }[change]()
            data = {"Dummy": "-", **subject, "TargetUserName": target.login, "TargetDomainName": d.netbios, "TargetSid": target.sid,
                    "PrivilegeList": "-", **{**_UNCHANGED_4738, **changed}}
            events.append(_structured(4738, dc.name, when, data))
        else:
            first, last = rng.choice(_NEW_HIRE_FIRST), rng.choice(_NEW_HIRE_LAST)
            login = f"{first}.{last}".lower()
            data = {**subject, "TargetUserName": login, "TargetDomainName": d.netbios, "TargetSid": d.new_hire_sid(login),
                    "SamAccountName": login, "DisplayName": f"{first} {last}", "UserPrincipalName": f"{login}@{d.dns}",
                    "PrivilegeList": "-"}
            events.append(_structured(4720, dc.name, when, data))
    return _finish(events)


# -- the attack scenarios: the skills' event blocks, filled fresh -------------------------------------------------------------

_PLACEHOLDER = re.compile(r"<CHANGE: ([^>]+)>")
_ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,19}")
ATTACKS = ("machine_account_domain_admins", "privileged_group_add", "dcsync", "guest_account_enabled", "sms_admins",
           "weak_service_tickets", "excessive_lockouts", "samaccountname_change", "multiple_account_deletions",
           "hidden_user_created", "default_account_masquerade", "spoofed_samaccountname_tickets", "shadow_credentials",
           "delegation_to_krbtgt", "privileged_certificate_request")
BENIGN_SCENARIOS = ("baseline_logons", "admin_activity")
SCENARIOS = BENIGN_SCENARIOS + ATTACKS
DEFAULT_COUNT = {"baseline_logons": 30, "admin_activity": 10}
_BENIGN: dict[str, Callable[..., list[dict[str, Any]]]] = {"baseline_logons": baseline_logons, "admin_activity": admin_activity}


@functools.lru_cache(maxsize=1)
def recipes() -> dict[str, list[dict[str, Any]]]:
    """The skills' event blocks (`<CHANGE: label>` placeholders unfilled), by scenario. Never mutate: fill a copy."""
    data = json.loads((Path(__file__).with_name("windows_recipes.json")).read_text(encoding="utf-8"))
    missing = set(ATTACKS) - set(data)
    if missing or set(data) - set(ATTACKS):
        raise RuntimeError(f"windows_recipes.json does not hold exactly the attack scenarios (missing {sorted(missing)})")
    return data


# The fewest events that make a scenario's recipe complete; a larger count must be a whole number of recipes.
MIN_COUNT = {name: len(events) for name, events in recipes().items()}


def labels(scenario: str) -> list[str]:
    """Every placeholder label of a scenario's block, in first-appearance order."""
    seen: dict[str, None] = {}
    for label in _PLACEHOLDER.findall(json.dumps(recipes()[scenario])):
        seen.setdefault(label)
    return list(seen)


# -- binding the skills' lab names to the organization ------------------------------------------------------------------------

# The kinds of host a recipe names: (roles it may have, a word its `purpose` holds, a word it must not hold). A writable domain
# controller needs no purpose.
_KINDS: dict[str, tuple[tuple[str, ...], str | None, str | None]] = {
    "domain controller": (("dc",), None, "read-only"),
    "read-only domain controller": (("dc",), "read-only", None),
    "file server": (("server", "security"), "file server", None),
    "application server": (("server", "security"), "application server", None),
    "SQL server": (("server", "security"), "sql", None),
    "web server": (("server", "security"), "web server", None),
    "certificate authority": (("server", "security"), "certificate authority", None),
    "mail server": (("server", "security"), "mail server", None),
    "endpoint management server": (("server", "security"), "endpoint management", None),
    "backup server": (("server", "security"), "backup server", None),
}
_SCHEME = re.compile(r"(.*?)(\d+)")


class _Lab:
    """The organization facts the recipes name, resolved on demand from one OrganizationView. A fact the organization cannot
    give raises OrganizationUnavailable saying what to add; a scenario that does not name it never asks."""

    def __init__(self, view: OrganizationView) -> None:
        self.view = view

    def hosts(self, kind: str) -> list[dict[str, Any]]:
        roles, word, not_word = _KINDS[kind]
        return [h for h in self.view.hosts if h["role"] in roles and h.get("domain_joined", True)
                and (word is None or word in (h.get("purpose") or "").lower())
                and (not_word is None or not_word not in (h.get("purpose") or "").lower())]

    def host(self, kind: str, position: int = 1) -> dict[str, Any]:
        found = self.hosts(kind)
        if len(found) < position:
            roles, word, _ = _KINDS[kind]
            need = f" whose purpose mentions {word!r}" if word else ""
            raise OrganizationUnavailable(
                f"organization {self.view.id!r} has no {kind}" + ("" if position == 1 else f" number {position}")
                + f": the scenario names one, so add a host of role {' or '.join(roles)}{need}")
        return found[position - 1]

    def stem(self, kind: str) -> str:
        """The name of the organization's first host of `kind` without its trailing number (PHSRV-WEB for PHSRV-WEB01)."""
        first = self.host(kind)["name"]
        m = _SCHEME.fullmatch(first)
        return m.group(1) if m else first

    def staff_rid(self) -> int:
        for account in self.view.accounts_by_role("staff"):
            if account.rid:
                return account.rid
        raise OrganizationUnavailable(f"organization {self.view.id!r} has no staff account with a rid")

    def workstation_prefix(self) -> str:
        return self.view.fresh_host_prefix()

    def fresh_ip(self, rng: random.Random) -> str:
        """A never-seen internal address from the organization's `unmanaged` network: a /24 chosen at random, then a host
        address in it from .20 to .250 (clipped to the range). Two draws, third octet first."""
        low, high = self.view.fresh_ip_range()
        block = rng.randrange(low >> 8, (high >> 8) + 1)
        first = max(20, low - (block << 8)) if block == low >> 8 else 20
        last = min(250, high - (block << 8)) if block == high >> 8 else 250
        if first > last:
            first, last = max(low - (block << 8), 0) if block == low >> 8 else 0, min(high - (block << 8), 255) if block == high >> 8 else 255
        return str(ipaddress.ip_address((block << 8) + rng.randrange(first, last + 1)))


# The hosts the skills' recipes name. They are Phantom Lab's, and each is bound to the organization's host of the same kind:
# the Nth domain controller, or the host whose `purpose` says what the lab host does.
_LAB_HOSTS: dict[str, tuple[str, int]] = {
    "PHDC01": ("domain controller", 1), "PHDC02": ("domain controller", 2), "PHRODC-JED01": ("read-only domain controller", 1),
    "PHSRV-FS01": ("file server", 1), "PHSRV-APP01": ("application server", 1), "PHSRV-SQL01": ("SQL server", 1),
    "PHSRV-WEB01": ("web server", 1), "PHSRV-CA01": ("certificate authority", 1), "PHSRV-EXCH01": ("mail server", 1),
    "PHSRV-SCCM01": ("endpoint management server", 1), "PHSRV-BKP01": ("backup server", 1),
}
# The other names the skills carry, written against Phantom Lab, are the domain's. Each match is rewritten to the active
# organization's.
_SKILL_NAMES = re.compile(r"""
    (?P<sid>S-1-5-21-3623811015-3361044348-30300820)(?P<rid>-(?:1001|1105)(?!\d))?
  | (?P<dn>DC=phantom,DC=lab)
  | (?<![A-Za-z0-9])(?P<realm>PHANTOM\.LAB)
  | (?<![A-Za-z0-9])(?P<dns>phantom\.lab)
  | (?<![A-Za-z0-9])(?P<netbios>PHANTOM)(?![A-Za-z0-9])
  | (?<![A-Za-z0-9])(?P<dcstem>PHDC)(?=<CHANGE)
  | (?<![A-Za-z0-9])(?P<host>%s)(?![A-Za-z0-9])
""" % "|".join(sorted(map(re.escape, _LAB_HOSTS), key=len, reverse=True)), re.X)
# Two SID suffixes of the lab are rewritten: -1001 is the machine account of its second domain controller (PHDC02), -1105 its
# first staff account (the account that holds the SPNs in the Kerberoasting recipe). The well-known ones (-501 Guest, -502
# krbtgt, -512 Domain Admins) are the same in every domain and stay.


def _binder(lab: _Lab) -> Callable[[re.Match], str]:
    view = lab.view

    def bind(m: re.Match) -> str:
        if m.group("sid"):
            rid = m.group("rid")
            if rid == "-1001":
                return f"{view.sid_base}-{lab.host('domain controller', 2)['rid']}"
            if rid == "-1105":
                return f"{view.sid_base}-{lab.staff_rid()}"
            return view.sid_base + (rid or "")
        if m.group("dn"):
            return ",".join(f"DC={part}" for part in view.dns.split("."))
        if m.group("realm"):
            return view.dns.upper()
        if m.group("dns"):
            return view.dns
        if m.group("netbios"):
            return view.netbios
        if m.group("dcstem"):
            return lab.stem("domain controller")
        kind, position = _LAB_HOSTS[m.group("host")]
        return lab.host(kind, position)["name"]

    return bind


def _bind_text(text: str, lab: _Lab) -> str:
    return _SKILL_NAMES.sub(_binder(lab), text)


def bind(template: Any, lab: _Lab) -> Any:
    """`template` (a skill block) with the skills' lab names rewritten to the organization's. A copy."""
    if isinstance(template, dict):
        return {k: bind(v, lab) for k, v in template.items()}
    if isinstance(template, list):
        return [bind(v, lab) for v in template]
    if isinstance(template, str):
        return _bind_text(template, lab)
    return template


_bound_cache: dict[str, tuple[OrganizationView, list[dict[str, Any]]]] = {}


def bound_recipe(scenario: str, view: OrganizationView | None = None) -> list[dict[str, Any]]:
    """The scenario's recipe bound to the organization (still holding its `<CHANGE: label>` placeholders). Cached per view
    object, so an edit to the organization shows up on the next call. Never mutate: fill a copy."""
    view = view or active_view()
    cached = _bound_cache.get(scenario)
    if cached is None or cached[0] is not view:
        cached = _bound_cache[scenario] = (view, bind(recipes()[scenario], _Lab(view)))
    return cached[1]


_SEEN: set[tuple[str, str]] = set()
_SEEN_LOCK = threading.Lock()
_SEEN_LIMIT = 200_000
RID_RANGE = (100_000, 90_000_000)


class _Source:
    """Draws identity values that were never drawn before: in this call and, unless the call is seeded, in this process.

    Within a call a label has one value everywhere it appears (the skills' rule); across calls nothing repeats, so every
    call looks like a first-time actor to a detector that remembers accounts for 30 days. The process-wide record is bounded
    (it restarts empty past `_SEEN_LIMIT` draws, and with every restart of the container; the random ranges are wide enough
    that a repeat is then astronomically unlikely, not impossible)."""

    def __init__(self, rng: random.Random, shared: bool) -> None:
        self.rng, self.shared, self.local = rng, shared, set()

    def unique(self, kind: str, make: Callable[[], str]) -> str:
        for _ in range(10_000):
            value = make()
            key = (kind, value)
            if key in self.local:
                continue
            if self.shared:
                with _SEEN_LOCK:
                    if key in _SEEN:
                        continue
                    if len(_SEEN) >= _SEEN_LIMIT:
                        _SEEN.clear()
                    _SEEN.add(key)
            self.local.add(key)
            return value
        raise RuntimeError(f"could not draw a new {kind}")

    def hex(self, n: int) -> str:
        return "".join(self.rng.choice("0123456789abcdef") for _ in range(n))

    def digits(self, n: int, low: int = 0) -> str:
        return str(self.rng.randrange(max(10 ** (n - 1), low), 10 ** n))


def _label_value(label: str, scenario: str, src: _Source, end: datetime, actor: str | None, ip: str | None, lab: _Lab) -> str:
    """The value of one placeholder label, per the skills' placeholder tables."""
    ago = re.fullmatch(r"now minus (\d+) s", label)
    if ago:
        return (end - timedelta(seconds=int(ago.group(1)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    u = src.unique
    if label == "actor":
        # "a new account name that is not a person's": adm.run<token> (svc.run<token> for the service account of Kerberoasting).
        return actor or u("name", lambda: ("svc.run" if scenario == "weak_service_tickets" else "adm.run") + src.hex(6))
    if label in ("actor RID", "machine RID", "member RID") or re.fullmatch(r"(lockout|deleted) RID \d+|repeat lockout RID", label):
        return u("rid", lambda: str(src.rng.randrange(*RID_RANGE)))
    if label == "actor logon id":
        return u("logon", lambda: "0x%X" % src.rng.randrange(0x100000, 0xFFFFFF))
    if label == "machine":
        if scenario == "hidden_user_created":      # the hidden account's name, without the `$`: a stem never used before
            return u("name", lambda: "svcprint" + src.digits(5))
        if scenario == "default_account_masquerade":  # the member server that gets the local accounts: a new web server
            return u("host", lambda: lab.stem("web server") + src.digits(4, 1000))
        return u("host", lambda: lab.workstation_prefix() + src.digits(5, 10000))
    if label in ("attacker host", "caller host"):
        return u("host", lambda: lab.workstation_prefix() + src.digits(5, 10000))
    if label in ("attacker IP", "client IP"):
        return ip or u("ip", lambda: lab.fresh_ip(src.rng))
    if label == "member display name":
        return u("display", lambda: "Run Member " + src.digits(5, 10000))
    if re.fullmatch(r"lockout user \d+", label):
        return u("name", lambda: "l.u" + src.hex(6))
    if label == "repeat lockout user":
        return u("name", lambda: "l.rpt" + src.hex(6))
    if re.fullmatch(r"deleted user \d+", label):
        return u("name", lambda: "tmp.sw" + src.hex(6))
    raise ValueError(f"no generator for the placeholder <CHANGE: {label}> of {scenario}")


def fresh_values(scenario: str, *, now: datetime, seed: int | None = None, target_user: str | None = None,
                 source_ip: str | None = None, view: OrganizationView | None = None) -> dict[str, str]:
    """A value for every placeholder label of `scenario`: the times relative to `now` and every identity new. A label that
    appears twice in a block has this one value in both places. The hosts and addresses follow `view` (default: the active
    organization)."""
    if scenario not in ATTACKS:
        raise ValueError(f"unknown attack scenario {scenario!r}")
    view = view or active_view()
    return _values(scenario, _Source(random.Random(seed), shared=seed is None), now, _clean_actor(target_user, view), _clean_ip(source_ip),
                   _Lab(view))


def _values(scenario: str, src: _Source, end: datetime, actor: str | None, ip: str | None, lab: _Lab) -> dict[str, str]:
    return {label: _label_value(label, scenario, src, end, actor, ip, lab) for label in labels(scenario)}


def _clean_actor(target_user: str | None, view: OrganizationView) -> str | None:
    """The acting account a caller named, or None. Every Windows attack scenario acts as a NEW account (the detectors count what
    an account did for the first time), so the name must be one the organization does not hold: an organization account would
    be stamped with a made-up RID and contradict its real SID."""
    if not target_user or not target_user.strip():
        return None
    name = target_user.strip().rsplit("\\", 1)[-1].split("@", 1)[0]   # DOMAIN\user and user@domain collapse to the bare name
    if not _ACTOR.fullmatch(name):
        raise ValueError("target_user must be an account name of letters, digits, dots, dashes and underscores (at most 20, "
                         "no trailing $): it becomes the Windows account that acts")
    if view.account(name) is not None:
        raise ValueError(
            f"target_user {name!r} is an account of organization {view.id!r}, but the Windows attack scenarios act as a NEW "
            "account (a detector that profiles first-time activity would not fire for an account with history, and the "
            "events would give a real account a made-up SID). Pass a name the organization does not hold, such as "
            f"'adm.run1', or leave it empty for a generated one. Accounts in use: {_choices(view)}")
    return name


def _choices(view: OrganizationView, limit: int = 12) -> str:
    logins = [a.login for a in view.accounts]
    return ", ".join(logins[:limit]) + (f", ... ({len(logins)} in all)" if len(logins) > limit else "")


def _clean_ip(source_ip: str | None) -> str | None:
    if not source_ip or not source_ip.strip():
        return None
    try:
        address = ipaddress.ip_address(source_ip.strip())
    except ValueError:
        raise ValueError("source_ip must be an IPv4 address") from None
    if address.version != 4:
        raise ValueError("source_ip must be an IPv4 address (the Kerberos events carry it as ::ffff:<address>)")
    return str(address)


def fill(template: Any, values: dict[str, str]) -> Any:
    """`template` (a skill block: dicts, lists, strings) with every `<CHANGE: label>` replaced by its value."""
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, values) for v in template]
    if isinstance(template, str):
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)
    return template


def _attack(scenario: str, count: int, end: datetime, seed: int | None, target_user: str | None, source_ip: str | None,
            view: OrganizationView) -> list[dict[str, Any]]:
    size = MIN_COUNT[scenario]
    if count % size:
        raise ValueError(f"{scenario} sends {size} event(s) per run: count must be a multiple of {size}")
    # One source over all the repetitions, so each repetition's identities differ from the others'.
    src, actor, ip = _Source(random.Random(seed), shared=seed is None), _clean_actor(target_user, view) if "actor" in labels(scenario) else None, _clean_ip(source_ip)
    template, lab = bound_recipe(scenario, view), _Lab(view)
    out: list[dict[str, Any]] = []
    for _ in range(count // size):
        out += fill(template, _values(scenario, src, end, actor, ip, lab))
    # Oldest first. A stable sort keeps the skill's order for events of one second, which is the order they render in.
    return sorted(out, key=lambda e: e["time"])


def build_events(
    scenario: str, count: int, *, view: OrganizationView, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Structured Windows events for `scenario`, oldest first and never later than `now`.

    The window ends `start_offset_minutes` before `now`. The benign scenarios spread `count` events over the last
    `spread_seconds` of it (and ignore `target_user` and `source_ip`). An attack scenario sends its skill's events, timed as
    the skill says (now minus N seconds from the window's end, so `spread_seconds` does not apply); `count` must be a whole
    number of recipes (`MIN_COUNT`), each with its own new identities. `target_user` names the acting account instead of a
    generated one: a bare name the organization does NOT hold (the attack scenarios act as a new account; an organization
    account is refused with a clear error). It is the service account of `weak_service_tickets` and unused by
    `excessive_lockouts` and `privileged_certificate_request`, which have no acting account and `source_ip` the IPv4 address of the attacking host (`dcsync`, `weak_service_tickets`,
    `spoofed_samaccountname_tickets`). `view` is the organization the domain, hosts and accounts come from; it raises
    OrganizationUnavailable (the tool returns `{ok: false, error}`) when the organization cannot carry the scenario."""
    name = (scenario or "").strip().lower()
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    end = now - timedelta(minutes=max(int(start_offset_minutes or 0), 0))
    if name in ATTACKS:
        return _attack(name, count, end, seed, target_user, source_ip, view)
    start = end - timedelta(seconds=max(int(spread_seconds or 0), 5))
    return _BENIGN[name](directory(view), count, start, end, random.Random(seed))


def sample_event(*, view: OrganizationView, now: datetime) -> dict[str, Any]:
    """One benign network logon of a directory user, for completeness (the tool sends its own 4624 test event)."""
    d = directory(view)
    user, host = d.staff[0], d.servers[0]
    lid = logon_id(host.fqdn, user.login, now)
    data = _logon_data(d, "network", user, host, d.host(user.home), lid, 49152)
    return {**_event(4624, host.name, now, data, process_id=host.lsass_pid, activity_id=_guid("act", lid, host.name)), "time": iso(now)}


def sample_id(event: dict[str, Any]) -> str:
    """What `generate_events` reports as a sample id: the event id and the computer it was written on."""
    return f"{event['event_id']}@{event['computer']}"


def describe(events: list[dict[str, Any]]) -> dict[str, Any]:
    """What a result tells the operator about a call, so its alert can be found: the accounts that acted (the subjects of
    the events that are not computer accounts; else the requester of a certificate; else the accounts acted on)."""
    actors: dict[str, None] = {}
    for key in ("SubjectUserName", "Requester", "TargetUserName"):
        for event in events:
            name = (event.get("event_data") or {}).get(key) or ""
            if name and (key == "Requester" or not name.endswith("$")) and name != "SYSTEM":
                actors.setdefault(name)
        if actors:
            break
    return {"actors": list(actors)[:10]}
