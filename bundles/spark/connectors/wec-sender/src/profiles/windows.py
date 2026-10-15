"""The `windows` profile: the active organization's Windows domain and its logon activity.

Nothing about the domain is written here. The domain names, the domain controllers, servers and workstations, the people and
their admin, service and break-glass accounts all come from the ACTIVE ORGANIZATION (or the one an instance pins with its
`organization` setting), read from the shared organization store when a tool is called. A missing organization is a broken
install and surfaces as a clear error; there is no built-in roster to fall back on.

Identity is a PURE FUNCTION of the organization (no randomness, no clock): the same login always has the same SID, home
workstation and address; the same host always has the same address, SID and lsass process id. That is what lets a baseline
build history on the tenant: run it every day and the same people keep signing in from the same machines. Randomness is only
used to vary WHAT happens in a window (which user, which server, how long), and is seedable so tests can assert exact output.

How the organization maps onto the domain:
  hosts      the domain-joined hosts that have a `rid` (domain controllers, servers, workstations, the security scanner);
             `Computer` in an event is the FQDN `<name>.<domain dns>`; the machine account SID is `<domain sid>-<rid>`
  accounts   the SID is `<domain sid>-<account rid>`; the role (staff | admin | service) comes from the organization:
             an account in a privileged group is an administrator, a service account is a service, the rest are staff;
             a leaver's account and the break-glass account never appear in baseline traffic (they are the findings)
  home       a person's account works at that person's workstation (so does their admin account); a service account runs
             on its own server
  servers    the earlier a server is listed, the busier it is (weights 4, 2, 1, 1, ...); service accounts authenticate from
             the application server
The probe hosts PHTM-WEC-* are never used here: they already have first-seen history on the tenant.

Scenarios (`SCENARIOS`): `baseline_logons`. More plug in by adding a function and a registry entry.
"""
from __future__ import annotations

import hashlib
import ipaddress
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import OrganizationView, get_view

from ..winevent import Event

NAME = "windows"
DESCRIPTION = "Windows Security events over WEC: baseline logons (4624 / 4672 / 4634) for the active organization."
EXPECTED_DATASET = "microsoft_windows_raw"
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}   # Python's datetime.weekday()
TEST_LOGIN = "phantom.wectest"    # the clearly synthetic account of send_test_event
TEST_HOST_SUFFIX = "WECTEST01"    # the synthetic host of send_test_event is <NETBIOS>-WECTEST01
_SERVER_WEIGHT_HEAD = (4, 2)      # the first server is the busiest, the second next; every later one weighs 1


@dataclass(frozen=True)
class Host:
    name: str
    fqdn: str
    ip: str
    role: str          # dc | server | workstation (| security: a domain-joined tool server that only hosts a service account)
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
    """Hosts and users of the organization's Windows domain. Immutable after construction; every lookup is deterministic.

    Build one with `directory()` (it reads the organization when called); `Directory(view)` is for callers that already
    hold an OrganizationView. Raises OrganizationUnavailable when the organization cannot carry the profile (no domain
    controller, no server, nobody to sign in, an account with no SID or with a home host that is not in the domain)."""

    def __init__(self, view: OrganizationView) -> None:
        self.view = view
        self.organization = view.id
        self.netbios = view.netbios
        self.dns = view.dns
        self.domain_sid = view.sid_base
        # Business hours are the organization's locale: its UTC offset, working week and office hours.
        self.utc_offset_hours = view.utc_offset_hours
        self.workdays = tuple(_WEEKDAYS[day[:3].lower()] for day in view.workweek)
        self.work_hours = (view.work_start_hour, view.work_end_hour)
        self.hosts: list[Host] = []
        for h in view.hosts:
            if not h.get("rid") or not h.get("ip") or not h.get("domain_joined", True):
                continue                       # appliances, cloud and DMZ machines are not in the Windows domain
            self.hosts.append(Host(name=h["name"], fqdn=view.fqdn(h), ip=h["ip"], role=h["role"], sid=view.sid(h["rid"]),
                                   lsass_pid=600 + hashlib.sha256(h["name"].encode()).digest()[0] % 200))
        self._by_name = {h.name.upper(): h for h in self.hosts}
        self.workstations = [h for h in self.hosts if h.role == "workstation"]
        self.servers = [h for h in self.hosts if h.role == "server"]
        self.dcs = [h for h in self.hosts if h.role == "dc"]
        self.users: list[User] = []
        for role in ("staff", "admin", "service"):
            for a in view.accounts_by_role(role):
                if not a.sid:
                    raise OrganizationUnavailable(f"account {a.login!r} of organization {view.id!r} has no rid, so it has no SID")
                if (a.home or "").split(".")[0].upper() not in self._by_name:
                    raise OrganizationUnavailable(
                        f"account {a.login!r} of organization {view.id!r} works at {a.home!r}, which is not a domain-joined "
                        "host with a rid and an address in that organization")
                self.users.append(User(a.login, a.display, a.sid, role, self._by_name[a.home.split(".")[0].upper()].name))
        self._user_by_login = {u.login.lower(): u for u in self.users}
        self.staff = [u for u in self.users if u.role == "staff"]
        self.admins = [u for u in self.users if u.role == "admin"]
        self.services = [u for u in self.users if u.role == "service"]
        missing = [what for what, items in (("domain controller", self.dcs), ("server", self.servers),
                                            ("staff account", self.staff), ("administrator account", self.admins),
                                            ("service account", self.services)) if not items]
        if missing:
            raise OrganizationUnavailable(
                f"organization {view.id!r} cannot drive Windows logon traffic: it has no domain-joined "
                f"{', no '.join(missing)}")
        self.server_weights = list((_SERVER_WEIGHT_HEAD + (1,) * len(self.servers))[:len(self.servers)])
        purpose = {h["name"].upper(): (h.get("purpose") or "").lower() for h in view.hosts}
        self.service_source = next((s for s in self.servers if "application" in purpose.get(s.name.upper(), "")), self.servers[0])

    def host(self, name: str) -> Host:
        return self._by_name[name.split(".")[0].upper()]

    def user(self, login: str) -> User:
        return self._user_by_login[login.lower()]

    def user_sid(self, login: str) -> str:
        """The SID of any login: an organization account's own, or for a name outside it a stable one derived from it."""
        account = self.view.account(login)
        if account is not None and account.sid:
            return account.sid
        return f"{self.domain_sid}-{5000 + int(hashlib.sha1(login.lower().encode()).hexdigest(), 16) % 90000}"

    def test_computer(self) -> str:
        """The short name of the synthetic host `send_test_event` claims to come from."""
        return f"{self.netbios}-{TEST_HOST_SUFFIX}"

    def test_ip(self) -> str:
        """The synthetic test host's address: a stable address inside the organization's pool for unmanaged and newly seen
        devices, so repeated tests reuse one entity and the address cannot collide with a managed device."""
        low, high = self.view.fresh_ip_range()
        offset = int.from_bytes(hashlib.sha256(f"{self.netbios}|{TEST_LOGIN}".encode()).digest()[:8], "big") % (high - low + 1)
        return str(ipaddress.ip_address(low + offset))


_directories: dict[int, Directory] = {}
_directories_lock = threading.Lock()


def directory(pinned_id: str | None = None) -> Directory:
    """The Directory of the pinned organization, or of the active one when `pinned_id` is empty. Read NOW, per call (never
    at import: a fresh install can start the connector before the organization store exists). The Directory is cached per
    view object, and a view is replaced whenever the organization changes, so an edit shows up on the next call."""
    view = get_view(pinned_id or None)
    with _directories_lock:
        cached = _directories.get(id(view))
        if cached is None or cached.view is not view:   # the Directory holds its view, so an id can never be reused under it
            if len(_directories) > 8:
                _directories.clear()
            cached = _directories[id(view)] = Directory(view)
        return cached


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
def _is_business_time(d: Directory, when: datetime) -> bool:
    """Whether `when` falls in the organization's working week and office hours, in its local time."""
    local = when + timedelta(hours=d.utc_offset_hours)
    return local.weekday() in d.workdays and d.work_hours[0] <= local.hour < d.work_hours[1]


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
        weights = _WEIGHTS_BUSINESS if _is_business_time(d, when) else _WEIGHTS_QUIET
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
            session = _session(d, kind, user, d.host(user.home), d.service_source, when,
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
    login = TEST_LOGIN
    short = computer_fqdn.split(".")[0]
    lid = logon_id(computer_fqdn, login, when)
    return Event(event_id=4624, computer=computer_fqdn, channel="Security", time=when, data={
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": short.upper() + "$", "SubjectDomainName": directory.netbios,
        "SubjectLogonId": "0x3E7", "TargetUserSid": directory.user_sid(login), "TargetUserName": login,
        "TargetDomainName": directory.netbios, "TargetLogonId": lid, "LogonType": "3",
        "LogonProcessName": "Kerberos", "AuthenticationPackageName": "Kerberos", "WorkstationName": short.upper(),
        "LogonGuid": "{" + test_id.upper() + "}", "LmPackageName": "-", "KeyLength": "0",
        "IpAddress": directory.test_ip(), "IpPort": "49999"})


def synthetic_test_logoff(logon: Event, when: datetime) -> Event:
    """The 4634 that closes the session opened by `logon` (a 4624 from synthetic_test_logon): same computer and logon id."""
    d = dict(logon.data)
    return Event(event_id=4634, computer=logon.computer, channel="Security", time=when, data={
        "TargetUserSid": d["TargetUserSid"], "TargetUserName": d["TargetUserName"],
        "TargetDomainName": d["TargetDomainName"], "TargetLogonId": d["TargetLogonId"], "LogonType": d["LogonType"]})
