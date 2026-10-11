"""The `windows` event profile: structured Windows Security events for the `cribl_windows_events` destination.

An event is the structured dict `windows_events.prepare` takes (the `wec-sender.send_events` shape: `event_id`, `computer`,
`time`, `event_data`, and for the ids Windows' catalogue here does not hold `provider` and `rendering`); the connector
renders it to Windows Event XML and posts the XML as a plain string. Three kinds of scenario:

  baseline_logons   benign logon traffic (4624, 4672 for administrators, 4634) of a STABLE synthetic domain. A port of the
                    `windows` profile of wec-sender (`wec-sender/src/profiles/windows.py`): same directory (2 domain
                    controllers, 4 servers, 26 workstations; 22 staff, 4 administrators, 4 service accounts), same
                    personas, same SIDs and addresses, same session shapes, so an event generated here and one generated
                    there for the same seed render to the same XML (tests/test_windows_profile.py compares them).
  admin_activity    benign administration by the same four IT administrators: helpdesk password resets (4724) and unlocks
                    (4767) of ordinary users, ordinary user accounts created (4720), ordinary users added to and removed
                    from ordinary department groups (4728 / 4729) and 4738 changes of display name, script path, home
                    directory or password age. Identities are stable (the directory's); the groups are fixed department
                    groups, never a privileged one, and the new accounts are named like staff.
  <attack>          fifteen scenarios, one per Windows trigger skill (`bundles/spark/mcp/skills/workflows/trigger_<name>_alert`).
                    Each sends the SAME events as the skill's JSON block: `windows_recipes.json` holds those blocks verbatim,
                    with their `<CHANGE: label>` placeholders, and every call fills the placeholders as the skill's table
                    says: the times as now minus N seconds (relative to the window's end), and every identity (actor,
                    RIDs, logon id, host and account names, addresses) NEW. A scheduled call therefore fires its detector
                    the way a manual replay of the skill does. tests/test_windows_profile.py checks the embedded blocks
                    against the skill files and the rendered XML against a filled skill block.

Freshness. The detectors count what an actor did for the first time in 30 days and deduplicate for a day, so a call must
look like a first-time actor. Identity values are drawn at random from wide ranges and, for unseeded calls, never repeat
within the process (`_Source`): names carry a random token, RIDs are 100000 to 90 million (above every RID the directory,
the test event and the earlier lab runs use), hosts are `PHWS-<5 digits>` (the directory has `PHWS-001` to `PHWS-026`), and
addresses are private ones outside the directory's. A seeded call (tests) is reproducible and tracks repeats only within
itself.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import random
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .. import windows_events
from . import _fresh

# The profile interface (see profiles/__init__.py).
NAME = "windows"
DESCRIPTION = ("Windows Security events for the cribl_windows_events destination: baseline_logons and admin_activity "
               "(benign, a stable synthetic domain) and one scenario per Windows trigger skill (privileged group adds, DCSync, "
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

DOMAIN_SID = windows_events.DOMAIN_SID
NETBIOS = "PHANTOM"
DNS = "phantom.lab"
FIRST_USER_RID = 1105
LOCAL_UTC_OFFSET_HOURS = 3        # business hours are Saudi local time (UTC+3), working week Sunday-Thursday
HOST_COUNT = 32
PHANTOM_PREFIX = "PH"
PROVIDER = "Microsoft-Windows-Security-Auditing"

_STAFF = [
    ("Noura", "Alharbi"), ("Khalid", "Alotaibi"), ("Abdullah", "Alzahrani"), ("Sara", "Almutairi"),
    ("Faisal", "Alqahtani"), ("Reem", "Aldosari"), ("Omar", "Alshehri"), ("Huda", "Alghamdi"),
    ("Yousef", "Alharthi"), ("Layla", "Almalki"), ("Tariq", "Alsubaie"), ("Dana", "Alanazi"),
    ("Majed", "Alsaleh"), ("Lama", "Alfaifi"), ("Saud", "Alrashid"), ("Hessa", "Alkhaldi"),
    ("Bandar", "Alshammari"), ("Maha", "Alyami"), ("Nasser", "Alamri"), ("Rana", "Alsulami"),
    ("Waleed", "Albishi"), ("Amal", "Alruwaili"),
]
_ADMINS = [("Ibrahim", "Alkhalifa"), ("Mansour", "Alwadi"), ("Shahad", "Alotaibi"), ("Turki", "Alsudairi")]
# (login, display name, the server it logs on to)
_SERVICES = [("svc-sql", "SQL Service", "SQL01"), ("svc-backup", "Backup Service", "FS01"),
             ("svc-web", "Web Service", "WEB01"), ("svc-app", "Application Service", "APP01")]
_SERVERS = ["FS01", "APP01", "SQL01", "WEB01"]
_SERVER_WEIGHTS = [4, 2, 1, 1]


@dataclass(frozen=True)
class Host:
    name: str
    fqdn: str
    ip: str
    role: str          # dc | server | workstation
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
    """Hosts and users of the synthetic domain: the directory of wec-sender's `windows` profile at its defaults. Every
    lookup is deterministic (a pure function of names), so the same login always has the same SID and home workstation."""

    def __init__(self) -> None:
        self.netbios, self.dns = NETBIOS, DNS
        names = ([("PHDC01", "dc"), ("PHDC02", "dc")] + [(f"{PHANTOM_PREFIX}SRV-{s}", "server") for s in _SERVERS])
        names += [(f"PHWS-{i:03d}", "workstation") for i in range(1, HOST_COUNT - len(names) + 1)]
        self.hosts: list[Host] = []
        for index, (name, role) in enumerate(names):
            if role == "dc":
                ip = f"10.20.0.{10 + index}"
            elif role == "server":
                ip = f"10.20.1.{20 + index - 2}"
            else:
                w = index - 6
                ip = f"10.20.{16 + w // 200}.{20 + w % 200}"
            digest = hashlib.sha256(name.encode()).digest()
            self.hosts.append(Host(name, f"{name}.{self.dns}", ip, role, f"{DOMAIN_SID}-{1000 + index}", 600 + digest[0] % 200))
        self._by_name = {h.name.upper(): h for h in self.hosts}
        self.workstations = [h for h in self.hosts if h.role == "workstation"]
        self.servers = [h for h in self.hosts if h.role == "server"]
        self.dcs = [h for h in self.hosts if h.role == "dc"]
        self.users: list[User] = []
        rid = FIRST_USER_RID
        for i, (first, last) in enumerate(_STAFF):
            self.users.append(User(f"{first[0]}{last}".lower(), f"{first} {last}", f"{DOMAIN_SID}-{rid}", "staff",
                                   self.workstations[i % len(self.workstations)].name))
            rid += 1
        for j, (first, last) in enumerate(_ADMINS):
            self.users.append(User(f"adm.{first[0]}{last}".lower(), f"{first} {last} (admin)", f"{DOMAIN_SID}-{rid}", "admin",
                                   self.workstations[(len(_STAFF) + j) % len(self.workstations)].name))
            rid += 1
        for login, display, server in _SERVICES:
            self.users.append(User(login, display, f"{DOMAIN_SID}-{rid}", "service", f"{PHANTOM_PREFIX}SRV-{server}"))
            rid += 1
        self.staff = [u for u in self.users if u.role == "staff"]
        self.admins = [u for u in self.users if u.role == "admin"]
        self.services = [u for u in self.users if u.role == "service"]

    def host(self, name: str) -> Host:
        return self._by_name[name.split(".")[0].upper()]


@lru_cache(maxsize=1)
def directory() -> Directory:
    return Directory()


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


def _is_business_time(when: datetime) -> bool:
    local = when + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    return local.weekday() in (6, 0, 1, 2, 3) and 7 <= local.hour < 17


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
        weights = _WEIGHTS_BUSINESS if _is_business_time(when) else _WEIGHTS_QUIET
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
            host = rng.choices(d.servers, _SERVER_WEIGHTS)[0]
            kind = "network" if rng.random() < 0.65 else "ntlm"
            session = _session(d, kind, user, host, d.host(user.home), when, logoff_after(5, 900), rng, salt)
        elif category == "dc":
            user = rng.choice(d.staff if small else people)
            kind = "network" if rng.random() < 0.8 else "ntlm"
            session = _session(d, kind, user, rng.choice(d.dcs), d.host(user.home), when, logoff_after(1, 120), rng, salt)
        elif category == "service":
            user = rng.choice(d.services)
            kind = "network" if rng.random() < 0.5 else "ntlm"
            session = _session(d, kind, user, d.host(user.home), d.host(f"{PHANTOM_PREFIX}SRV-APP01"), when, logoff_after(30, 1800), rng, salt)
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

# Ordinary department groups (global security groups). Fixed RIDs below the fresh-identity range and above the directory's.
_GROUPS = (("SG-Finance", 2101), ("SG-HR", 2102), ("SG-Sales", 2103), ("SG-Engineering", 2104),
           ("SG-VPN-Users", 2105), ("SG-Project-Atlas", 2106))
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


def new_hire_sid(login: str) -> str:
    """The SID of an account the directory does not hold: a stable one derived from the login (as wec-sender's `user_sid`)."""
    return f"{DOMAIN_SID}-{5000 + int(hashlib.sha1(login.lower().encode()).hexdigest(), 16) % 90000}"


def _subject(admin: User, session: str) -> dict[str, str]:
    return {"SubjectUserSid": admin.sid, "SubjectUserName": admin.login, "SubjectDomainName": NETBIOS, "SubjectLogonId": session}


def _local_time_text(when: datetime) -> str:
    """Windows' text for a date in a 4738 message: `10/6/2026 9:14:03 AM` in the controller's local time."""
    local = when + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    return f"{local.month}/{local.day}/{local.year} {local.hour % 12 or 12}:{local:%M:%S} {'AM' if local.hour < 12 else 'PM'}"


def admin_activity(d: Directory, count: int, start: datetime, end: datetime, rng: random.Random) -> list[dict[str, Any]]:
    """`count` ordinary administration events by the directory's four IT administrators on the domain controllers. The first
    two administrators are the helpdesk (resets, unlocks, attribute changes), the other two the directory team (account
    creation, group membership). An administrator's logon id is the same for the whole UTC day, like one long session."""
    span = (end - start).total_seconds()
    helpdesk, directory_team = d.admins[:2], d.admins[2:]
    events: list[dict[str, Any]] = []
    for _ in range(count):
        when = start + timedelta(seconds=rng.uniform(0, span))
        kind = _fresh.weighted(rng, _ADMIN_KINDS)
        dc = rng.choice(d.dcs)
        admin = rng.choice(helpdesk if kind in ("reset_password", "unlock", "change") else directory_team)
        session = logon_id(dc.fqdn, admin.login, datetime(when.year, when.month, when.day, tzinfo=timezone.utc))
        subject = _subject(admin, session)
        target = rng.choice(d.staff)
        if kind in ("reset_password", "unlock"):
            data = {"TargetUserName": target.login, "TargetDomainName": NETBIOS, "TargetSid": target.sid, **subject}
            events.append(_structured(4724 if kind == "reset_password" else 4767, dc.name, when, data))
        elif kind in ("group_add", "group_remove"):
            group, rid = rng.choice(_GROUPS)
            data = {"MemberName": f"CN={target.display},OU=Users,DC=phantom,DC=lab", "MemberSid": target.sid, **subject,
                    "TargetUserName": group, "TargetDomainName": NETBIOS, "TargetSid": f"{DOMAIN_SID}-{rid}", "PrivilegeList": "-"}
            events.append(_structured(4728 if kind == "group_add" else 4729, dc.name, when, data))
        elif kind == "change":
            change = rng.choice(("DisplayName", "ScriptPath", "HomeDirectory", "PasswordLastSet"))
            changed = {
                "DisplayName": {"DisplayName": target.display},
                "ScriptPath": {"ScriptPath": "logon.bat"},
                "HomeDirectory": {"HomeDirectory": f"\\\\{PHANTOM_PREFIX}SRV-FS01\\home$\\{target.login}", "HomePath": "H:"},
                "PasswordLastSet": {"PasswordLastSet": _local_time_text(when)},
            }[change]
            data = {"Dummy": "-", **subject, "TargetUserName": target.login, "TargetDomainName": NETBIOS, "TargetSid": target.sid,
                    "PrivilegeList": "-", **{**_UNCHANGED_4738, **changed}}
            events.append(_structured(4738, dc.name, when, data))
        else:
            first, last = rng.choice(_NEW_HIRE_FIRST), rng.choice(_NEW_HIRE_LAST)
            login = f"{first}.{last}".lower()
            data = {**subject, "TargetUserName": login, "TargetDomainName": NETBIOS, "TargetSid": new_hire_sid(login),
                    "SamAccountName": login, "DisplayName": f"{first} {last}", "UserPrincipalName": f"{login}@{DNS}",
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


@lru_cache(maxsize=1)
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


def _label_value(label: str, scenario: str, src: _Source, end: datetime, actor: str | None, ip: str | None) -> str:
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
        if scenario == "default_account_masquerade":  # the member server that gets the local accounts
            return u("host", lambda: "PHSRV-WEB" + src.digits(4, 1000))
        return u("host", lambda: "PHWS-" + src.digits(5, 10000))
    if label in ("attacker host", "caller host"):
        return u("host", lambda: "PHWS-" + src.digits(5, 10000))
    if label in ("attacker IP", "client IP"):
        return ip or u("ip", lambda: f"10.20.{src.rng.randrange(100, 200)}.{src.rng.randrange(20, 251)}")
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
                 source_ip: str | None = None) -> dict[str, str]:
    """A value for every placeholder label of `scenario`: the times relative to `now` and every identity new. A label that
    appears twice in a block has this one value in both places."""
    if scenario not in ATTACKS:
        raise ValueError(f"unknown attack scenario {scenario!r}")
    return _values(scenario, _Source(random.Random(seed), shared=seed is None), now, _clean_actor(target_user), _clean_ip(source_ip))


def _values(scenario: str, src: _Source, end: datetime, actor: str | None, ip: str | None) -> dict[str, str]:
    return {label: _label_value(label, scenario, src, end, actor, ip) for label in labels(scenario)}


def _clean_actor(target_user: str | None) -> str | None:
    if not target_user or not target_user.strip():
        return None
    name = target_user.strip().rsplit("\\", 1)[-1].split("@", 1)[0]   # DOMAIN\user and user@domain collapse to the bare name
    if not _ACTOR.fullmatch(name):
        raise ValueError("target_user must be an account name of letters, digits, dots, dashes and underscores (at most 20, "
                         "no trailing $): it becomes the Windows account that acts")
    return name


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


def _attack(scenario: str, count: int, end: datetime, seed: int | None, target_user: str | None, source_ip: str | None) -> list[dict[str, Any]]:
    size = MIN_COUNT[scenario]
    if count % size:
        raise ValueError(f"{scenario} sends {size} event(s) per run: count must be a multiple of {size}")
    # One source over all the repetitions, so each repetition's identities differ from the others'.
    src, actor, ip = _Source(random.Random(seed), shared=seed is None), _clean_actor(target_user), _clean_ip(source_ip)
    out: list[dict[str, Any]] = []
    for _ in range(count // size):
        out += fill(recipes()[scenario], _values(scenario, src, end, actor, ip))
    # Oldest first. A stable sort keeps the skill's order for events of one second, which is the order they render in.
    return sorted(out, key=lambda e: e["time"])


def build_events(
    scenario: str, count: int, *, domain: str, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Structured Windows events for `scenario`, oldest first and never later than `now`.

    The window ends `start_offset_minutes` before `now`. The benign scenarios spread `count` events over the last
    `spread_seconds` of it (and ignore `target_user` and `source_ip`). An attack scenario sends its skill's events, timed as
    the skill says (now minus N seconds from the window's end, so `spread_seconds` does not apply); `count` must be a whole
    number of recipes (`MIN_COUNT`), each with its own new identities. `target_user` names the acting account instead of a
    new one (a bare name; the service account of `weak_service_tickets`, and unused by `privileged_certificate_request`,
    which has no acting account) and `source_ip` the IPv4 address of the attacking host (`dcsync`, `weak_service_tickets`,
    `spoofed_samaccountname_tickets`). `domain` is unused: the domain is the synthetic PHANTOM / phantom.lab one."""
    name = (scenario or "").strip().lower()
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    end = now - timedelta(minutes=max(int(start_offset_minutes or 0), 0))
    if name in ATTACKS:
        return _attack(name, count, end, seed, target_user, source_ip)
    start = end - timedelta(seconds=max(int(spread_seconds or 0), 5))
    return _BENIGN[name](directory(), count, start, end, random.Random(seed))


def sample_event(*, domain: str, now: datetime) -> dict[str, Any]:
    """One benign network logon of a directory user, for completeness (the tool sends its own 4624 test event)."""
    d = directory()
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
