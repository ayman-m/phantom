"""The `windows` profile: a stable synthetic Windows domain and its logon activity.

Identity is a PURE FUNCTION of names (no randomness, no clock): the same login always has the same SID, home
workstation and address; the same host always has the same address, SID and lsass process id. That is what lets a
baseline build history on the tenant: run it every day and the same ~30 users keep signing in from the same
machines. Randomness is only used to vary WHAT happens in a window (which user, which server, how long), and is
seedable so tests can assert exact output.

The directory (defaults, hostCount = 32):
  2 domain controllers  PHDC01, PHDC02
  4 servers             PHSRV-FS01, PHSRV-APP01, PHSRV-SQL01, PHSRV-WEB01
  26 workstations       PHWS-001 .. PHWS-026
  30 accounts           22 staff, 4 administrators (adm.<name>), 4 service accounts (svc-*)
`Computer` in an event is the FQDN `<name>.<domainDns>`. Domain SID S-1-5-21-3623811015-3361044348-30300820; user
RIDs start at 1105 in the fixed order of the tables below. The probe hosts PHTM-WEC-* are never used here: they
already have first-seen history on the tenant.

Scenarios (`SCENARIOS`): `baseline_logons`. More plug in by adding a function and a registry entry.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..winevent import Event

NAME = "windows"
DESCRIPTION = "Windows Security events over WEC: baseline logons (4624 / 4672 / 4634) for a stable synthetic domain."
EXPECTED_DATASET = "microsoft_windows_raw"
DOMAIN_SID = "S-1-5-21-3623811015-3361044348-30300820"
FIRST_USER_RID = 1105
LOCAL_UTC_OFFSET_HOURS = 3        # business hours are Saudi local time (UTC+3), working week Sunday-Thursday
MAX_HOSTS = 100
PHANTOM_PREFIX = "PH"

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
    """Hosts and users of the synthetic domain. Immutable after construction; every lookup is deterministic."""

    def __init__(self, domain_netbios: str = "PHANTOM", domain_dns: str = "phantom.lab", host_count: int = 32) -> None:
        self.netbios = (domain_netbios or "PHANTOM").strip().upper()
        self.dns = (domain_dns or "phantom.lab").strip().lower()
        self.host_count = max(8, min(int(host_count or 32), MAX_HOSTS))
        names = ([("PHDC01", "dc"), ("PHDC02", "dc")] + [(f"{PHANTOM_PREFIX}SRV-{s}", "server") for s in _SERVERS])
        names += [(f"PHWS-{i:03d}", "workstation") for i in range(1, self.host_count - len(names) + 1)]
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
            self.hosts.append(Host(name=name, fqdn=f"{name}.{self.dns}",
                                   ip=ip, role=role, sid=f"{DOMAIN_SID}-{1000 + index}",
                                   lsass_pid=600 + digest[0] % 200))
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
            self.users.append(User(f"adm.{first[0]}{last}".lower(), f"{first} {last} (admin)", f"{DOMAIN_SID}-{rid}",
                                   "admin", self.workstations[(len(_STAFF) + j) % len(self.workstations)].name))
            rid += 1
        for login, display, server in _SERVICES:
            self.users.append(User(login, display, f"{DOMAIN_SID}-{rid}", "service", f"{PHANTOM_PREFIX}SRV-{server}"))
            rid += 1
        self._user_by_login = {u.login: u for u in self.users}
        self.staff = [u for u in self.users if u.role == "staff"]
        self.admins = [u for u in self.users if u.role == "admin"]
        self.services = [u for u in self.users if u.role == "service"]

    def host(self, name: str) -> Host:
        return self._by_name[name.split(".")[0].upper()]

    def user(self, login: str) -> User:
        return self._user_by_login[login.lower()]

    def user_sid(self, login: str) -> str:
        """The SID of any login: a pool user's own, or for a name outside the pool a stable one derived from it."""
        known = self._user_by_login.get(login.lower())
        if known:
            return known.sid
        return f"{DOMAIN_SID}-{5000 + int(hashlib.sha1(login.lower().encode()).hexdigest(), 16) % 90000}"


# ── field builders ──────────────────────────────────────────────────────────────────────────────────────────────
def _guid(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return "{" + f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}".upper() + "}"


def logon_id(computer: str, login: str, when: datetime, salt: int = 0) -> str:
    """A logon session id: unique per (computer, login, time); the 4634 reuses it."""
    h = hashlib.sha256(f"{computer}|{login}|{when.isoformat()}|{salt}".encode()).digest()
    return f"0x{int.from_bytes(h[:4], 'big') % 0xFFF000 + 0x10000:X}"


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
             rng: random.Random, salt: int) -> list[Event]:
    """4624 (+ 4672 for administrators) at `when`, 4634 at `logoff`, all sharing one logon id."""
    lid = logon_id(target.fqdn, user.login, when, salt)
    data = _logon_data(d, kind, user, target, source, lid, 49152 + rng.randrange(16000))
    common = dict(computer=target.fqdn, channel="Security", process_id=target.lsass_pid)
    events = [Event(event_id=4624, time=when, data=data, activity_id=_guid("act", lid, target.name), **common)]
    if user.role == "admin":
        events.append(Event(event_id=4672, time=when + timedelta(milliseconds=1), data={
            "SubjectUserSid": user.sid, "SubjectUserName": user.login, "SubjectDomainName": d.netbios,
            "SubjectLogonId": lid}, **common))
    events.append(Event(event_id=4634, time=logoff, data={
        "TargetUserSid": user.sid, "TargetUserName": user.login, "TargetDomainName": d.netbios,
        "TargetLogonId": lid, "LogonType": data["LogonType"]}, **common))
    return events


# ── scenarios ───────────────────────────────────────────────────────────────────────────────────────────────────
def _is_business_time(when: datetime) -> bool:
    local = when + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    return local.weekday() in (6, 0, 1, 2, 3) and 7 <= local.hour < 17


_CATEGORIES = ("workstation", "server", "dc", "service", "rdp")
_WEIGHTS_BUSINESS = (50, 25, 12, 8, 5)
_WEIGHTS_QUIET = (8, 12, 10, 55, 15)


def baseline_logons(d: Directory, count: int, start: datetime, end: datetime, rng: random.Random) -> list[Event]:
    """Benign logon traffic shaped by the time of day: workstation sign-ins (interactive, unlock, cached) in
    business hours, network logons on servers and DCs, service accounts around the clock, a little admin RDP.

    Exactly `count` events made of whole sessions (4624, 4672 for administrators, 4634), so every 4634 follows its
    4624 with the same logon id and every administrator logon has its 4672. When `count` leaves one event over, it is
    one last 4624 (a session still open): at most one session in a result is open. A logoff that would fall after the
    window ends is placed at a random moment between its logon and the end, so a short window does not pile every
    logoff on one timestamp."""
    span = (end - start).total_seconds()
    people = d.staff + d.admins
    events: list[Event] = []
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
            session = _session(d, kind, user, d.host(user.home), d.host(f"{PHANTOM_PREFIX}SRV-APP01"), when,
                               logoff_after(30, 1800), rng, salt)
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
    rank = {4624: 0, 4672: 1, 4634: 2}
    events.sort(key=lambda e: (e.time, rank.get(e.event_id, 9)))
    return events


SCENARIOS: dict[str, Callable[..., list[Event]]] = {"baseline_logons": baseline_logons}


def build_events(scenario: str, count: int, *, directory: Directory, now: datetime, spread_seconds: int = 120,
                 start_offset_minutes: int = 0, seed: int | None = None) -> list[Event]:
    """Events for `scenario`, spread over a window of `spread_seconds` that ENDS `start_offset_minutes` ago.
    Never later than `now`; ascending in time. Raises ValueError for an unknown scenario."""
    fn = SCENARIOS.get((scenario or "").strip().lower())
    if fn is None:
        raise ValueError(f"unknown scenario {scenario!r} for profile {NAME!r}; choose one of {', '.join(SCENARIOS)}. "
                         "The attack recipes (dcsync, guest_account_enabled, ...) are scenarios of http-sender's `windows` profile "
                         "(destination cribl_windows_events); over WEC, send them with send_events and the events from the skill")
    if count < 1:
        raise ValueError("count must be at least 1")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    end = now - timedelta(minutes=max(int(start_offset_minutes or 0), 0))
    start = end - timedelta(seconds=max(int(spread_seconds or 0), 5))
    return fn(directory, count, start, end, random.Random(seed))


def synthetic_test_logon(directory: Directory, computer_fqdn: str, test_id: str, when: datetime) -> Event:
    """One clearly synthetic 4624 for `send_test_event`. The test id rides in LogonGuid, a field that is a GUID
    by nature, so repeated tests reuse one host and one user instead of minting new entities each time."""
    login = "phantom.wectest"
    short = computer_fqdn.split(".")[0]
    lid = logon_id(computer_fqdn, login, when)
    return Event(event_id=4624, computer=computer_fqdn, channel="Security", time=when, data={
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": short.upper() + "$", "SubjectDomainName": directory.netbios,
        "SubjectLogonId": "0x3E7", "TargetUserSid": directory.user_sid(login), "TargetUserName": login,
        "TargetDomainName": directory.netbios, "TargetLogonId": lid, "LogonType": "3",
        "LogonProcessName": "Kerberos", "AuthenticationPackageName": "Kerberos", "WorkstationName": short.upper(),
        "LogonGuid": "{" + test_id.upper() + "}", "LmPackageName": "-", "KeyLength": "0",
        "IpAddress": "10.20.250.250", "IpPort": "49999"})


def synthetic_test_logoff(logon: Event, when: datetime) -> Event:
    """The 4634 that closes the session opened by `logon` (a 4624 from synthetic_test_logon): same computer and logon id."""
    d = dict(logon.data)
    return Event(event_id=4634, computer=logon.computer, channel="Security", time=when, data={
        "TargetUserSid": d["TargetUserSid"], "TargetUserName": d["TargetUserName"],
        "TargetDomainName": d["TargetDomainName"], "TargetLogonId": d["TargetLogonId"], "LogonType": d["LogonType"]})
