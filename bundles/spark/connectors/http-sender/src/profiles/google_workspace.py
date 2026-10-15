"""The `google_workspace` event profile: synthetic Google Workspace audit (Drive and Login) events.

Each event has the shape of one Activity resource from the Admin SDK Reports API
(`activities.list`): top-level `kind`, `etag`, `ownerDomain`, `ipAddress`, `id`, `actor` and
`events`. `id` is an object (`time`, `uniqueQualifier`, `applicationName`, `customerId`) and
`events` is a one-item array of `{type, name, parameters[]}`, each parameter a
`{name, value | boolValue | multiValue}` object. Events are sent as top-level JSON objects; the
collector adds `_time`, `_vendor` and `_product` itself, so none are set here.

These events MODEL only when delivered to a collector whose dataset is
`google_workspace_drive_raw` (vendor `google_workspace`, product `drive`): that is where the
Cortex Google Drive pack's modeling rule is bound. Delivered to a generic `google_workspace_raw`
collector they land raw, with no `xdm.*` fields. The rule reads, per event:

  events[0].type, events[0].name   -> xdm.event.type, xdm.event.operation
  events[0].parameters[]           -> `doc_type`, `doc_title`, `owner` ONLY, and ONLY in the
                                      string form `{"name": ..., "value": "..."}` with `name`
                                      before `value` (it is matched with a regex over the
                                      re-serialised array). A bool/multiValue form is ignored.
  actor.email, actor.profileId     -> source user username / identifier
  ipAddress                        -> xdm.source.ipv4
  kind                             -> xdm.target.resource.type

The pack's parsing rule sets `_time` from `id.time`, accepting `...:SSZ` or `...:SS.mmmZ`, so
`iso()` emits the millisecond form and a back-dated `id.time` back-dates the event. With no
parsing rule installed `_time` is the ingestion time. Login events carry no Drive parameters:
sent to the Drive dataset they map event type/operation, user and IP only (on a real tenant they
belong to the Login application's own dataset).

Impossible travel is expressed in `id.time` (event time), never wall-clock: the later login is
dated `now`, the earlier one 2.5 to 6 hours before it. A Google activity carries no geolocation,
only `ipAddress`, and Cortex resolves country and ASN from the address itself, so "far apart" is a
real Saudi home address followed by a real out-of-country one (see `ippools`).

Every user has one stable Saudi home address, the same one the user has in the `okta` and
`proofpoint_tap` profiles. The actors and owners are the active organization's people who may log on (leavers excluded), by
email, with the person's own `home_ip`; `ownerDomain` is the organization's email domain and the external-share target is
on its `partner_domain`. `target_user` names one of its people (login, email or the part before the @). Everything else
here is synthetic: ids are fictitious.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from runtime.organization_view import OrganizationView

from . import _org, ippools

# The profile interface (see profiles/__init__.py).
NAME = "google_workspace"
DESCRIPTION = ("Google Workspace Admin SDK activity objects (Drive and Login): benign Drive use, public share, "
               "sensitive-file download burst, impossible-travel login. Models only on a collector whose "
               "dataset is google_workspace_drive_raw (destination google_workspace_drive).")
# The destination these events are meant for (vendor google_workspace, product drive; its dataset
# google_workspace_drive_raw is the one the Cortex Google Drive modeling rule binds to).
EXPECTED_DATASET = "google_workspace_drive"
EXPECTED_DATASETS = ("google_workspace_drive",)
# The test id is a top-level, per-event-unique field: the verify XQL filters on it as a plain
# column. `id.uniqueQualifier` is the canonical id but sits inside the `id` JSON object.
TEST_ID_FIELD = "etag"
# A dotted path: the event time lives in `id.time`. connector.py reads TIME_FIELD with a plain
# `event.get(...)`, so first_time/last_time are reported as null until it resolves dotted paths.
TIME_FIELD = "id.time"
SCENARIOS = ("benign_drive", "public_share", "sensitive_download", "impossible_travel_login")


_DOC_TYPES = ["document", "spreadsheet", "presentation", "pdf"]
_TITLES = [
    "Team Meeting Notes", "Quarterly Planning Draft", "Onboarding Checklist", "Project Timeline",
    "Vendor Evaluation Matrix", "Training Slides", "Office Move Plan", "Roadmap Overview",
    "Budget Worksheet", "Support Runbook", "Design Review Notes", "Weekly Status Report",
]
# Filenames that look worth stealing; used by sensitive_download and public_share.
_SENSITIVE = [
    ("Employee PII Master List", "spreadsheet"), ("Customer Database Backup", "archive"),
    ("Payroll Master 2026", "spreadsheet"), ("Source Code Archive", "archive"),
    ("Salary Bands 2026", "spreadsheet"), ("Customer Contracts Export", "pdf"),
    ("Board Financials Draft", "presentation"), ("Credentials Inventory", "document"),
]
# Baseline Drive traffic: mostly views, some downloads, now and then a partner share or a delete.
_BENIGN_MIX = ("view", "view", "download", "view", "share_external", "view", "view", "trash")
# (events[0].type, events[0].name) per Drive kind.
_DRIVE_KINDS = {
    "view": ("access", "view"),
    "download": ("access", "download"),
    "trash": ("delete", "trash"),
    "share_public": ("acl_change", "change_document_visibility"),
    "share_external": ("acl_change", "change_user_access"),
}
_ID_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def iso(ts: datetime) -> str:
    """Google's timestamp form for `id.time`: UTC, millisecond precision, trailing Z."""
    ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _str_param(name: str, value: str) -> dict[str, Any]:
    return {"name": name, "value": value}


def _bool_param(name: str, value: bool) -> dict[str, Any]:
    return {"name": name, "boolValue": value}


class _Factory:
    """Deterministic when seeded, so the tests can assert on exact output."""

    def __init__(self, view: OrganizationView, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.view = view
        self.domain = view.email_domain
        self.customer_id = "C0" + "".join(self.rng.choice(_ID_CHARS[:26] + _ID_CHARS[52:]) for _ in range(7))
        self.pool = _org.logon_people(view)
        self._by_email = {p["email"].lower(): p for p in view.people}

    # -- identities and ids ---------------------------------------------
    def user(self, index: int) -> str:
        """The email of person number `index` of the pool (it wraps around the organization)."""
        return _org.email(self.pool[index % len(self.pool)])

    @staticmethod
    def profile_id(email: str) -> str:
        """Google's 21-digit numeric profile id, stable per address."""
        n = int(hashlib.sha1(email.lower().encode()).hexdigest(), 16)
        digits = "".join(str((n // 10**i) % 10) for i in range(21))
        return "1" + digits[1:] if digits[0] == "0" else digits

    def home_ip(self, index: int) -> str:
        """The home address of person number `index` of the pool."""
        return _org.home(self.pool[index % len(self.pool)])[0]

    def actor_ip(self, email: str) -> str:
        """The actor's home address: the person's own."""
        return _org.home(self._by_email.get(email.lower()) or {"login": email})[0]

    def remote_ip(self) -> str:
        """An address outside the country: far from every home address."""
        return ippools.abroad_pick(self.rng)[0]

    def etag(self) -> str:
        return "".join(self.rng.choice(_ID_CHARS) for _ in range(20))

    def doc_id(self) -> str:
        return "1" + "".join(self.rng.choice(_ID_CHARS) for _ in range(43))

    def doc(self, *, sensitive: bool = False) -> dict[str, str]:
        if sensitive:
            title, kind = self.rng.choice(_SENSITIVE)
        else:
            title, kind = self.rng.choice(_TITLES), self.rng.choice(_DOC_TYPES)
        return {"id": self.doc_id(), "title": title, "type": kind}

    # -- event pieces ---------------------------------------------------
    def activity(self, *, when: datetime, app: str, actor: str, ip: str, etype: str, name: str,
                 parameters: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "kind": "admin#reports#activity",
            "etag": self.etag(),
            "ownerDomain": self.domain,
            "ipAddress": ip,
            "id": {"time": iso(when), "uniqueQualifier": str(self.rng.randint(-(2**63), 2**63 - 1)),
                   "applicationName": app, "customerId": self.customer_id},
            "actor": {"email": actor, "profileId": self.profile_id(actor), "callerType": "USER"},
            "events": [{"type": etype, "name": name, "parameters": parameters}],
        }

    def drive(self, kind: str, when: datetime, actor: str, owner: str, ip: str, doc: dict[str, str]) -> dict[str, Any]:
        """One Drive activity. `doc_type`, `doc_title` and `owner` are the three parameters the
        modeling rule reads, so they are always plain `value` strings with `name` first."""
        etype, name = _DRIVE_KINDS[kind]
        visibility = {"share_public": "public_on_the_web", "share_external": "shared_externally"}.get(kind) \
            or self.rng.choice(["private", "private", "shared_internally"])
        params = [
            _str_param("doc_id", doc["id"]), _str_param("doc_title", doc["title"]),
            _str_param("doc_type", doc["type"]), _str_param("owner", owner),
            _bool_param("owner_is_shared_drive", False), _str_param("visibility", visibility),
            _bool_param("primary_event", True), _bool_param("billable", True),
            _bool_param("actor_is_collaborator_account", False), _bool_param("is_encrypted", False),
        ]
        if kind == "share_public":
            params += [_str_param("old_visibility", "private"), _str_param("new_visibility", visibility)]
        elif kind == "share_external":
            params += [_str_param("target_user", f"reviewer.{self.rng.randint(100, 999)}@{_org.partner_domain(self.view)}"),
                       {"name": "old_value", "multiValue": ["none"]}, {"name": "new_value", "multiValue": ["can_view"]}]
        return self.activity(when=when, app="drive", actor=actor, ip=ip, etype=etype, name=name, parameters=params)

    def login(self, when: datetime, actor: str, ip: str, *, ok: bool, login_type: str = "google_password") -> dict[str, Any]:
        params = [_str_param("login_type", login_type),
                  _str_param("login_challenge_method", "password"),
                  _str_param("login_challenge_status", "Passed" if ok else "Failed")]
        if not ok:
            params.append(_str_param("login_failure_type", "login_failure_wrong_password"))
        params += [_bool_param("is_suspicious", False), _bool_param("is_second_factor", False),
                   _str_param("affected_email_address", actor)]
        return self.activity(when=when, app="login", actor=actor, ip=ip, etype="login",
                             name="login_success" if ok else "login_failure", parameters=params)


def _times(end: datetime, count: int, spread_seconds: int) -> list[datetime]:
    """`count` timestamps ascending across the window that ends at `end`."""
    if count <= 1 or spread_seconds <= 0:
        return [end] * max(count, 0)
    step = spread_seconds / (count - 1)
    return [end - timedelta(seconds=spread_seconds - i * step) for i in range(count)]


def build_events(
    scenario: str, count: int, *, view: OrganizationView, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build `count` events for `scenario`, oldest first.

    The window ends `start_offset_minutes` before `now` and is `spread_seconds` wide; nothing is
    ever dated after `now`. `impossible_travel_login` is the one exception to a single window: its
    earlier logins sit a further 2.5 to 6 hours back, and it needs `count` >= 2. The actors are the organization's
    people (`view`); `target_user` is one of them.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    if scenario == "impossible_travel_login" and count < 2:
        raise ValueError("impossible_travel_login needs count >= 2")
    f = _Factory(view, seed)
    end = now - timedelta(minutes=max(start_offset_minutes, 0))
    times = _times(end, count, spread_seconds)

    if scenario == "benign_drive":
        return _benign(f, times)
    actor = _named_user(f, target_user)
    if scenario == "public_share":
        return _public_share(f, times, actor, source_ip or f.actor_ip(actor))
    if scenario == "sensitive_download":
        return _sensitive_download(f, times, actor, source_ip or f.actor_ip(actor))
    return _impossible_travel(f, times, actor, source_ip or f.remote_ip(), spread_seconds)


def _named_user(f: _Factory, login: str | None) -> str:
    """`target_user` as the email of the organization's person it names (first person of the pool when none is given)."""
    if not login:
        return f.user(0)
    return _org.email(_org.resolve(f.view, login))


def _benign(f: _Factory, times: list[datetime]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times):
        idx = i // 2 % len(f.pool)
        out.append(f.drive(_BENIGN_MIX[i % len(_BENIGN_MIX)], when, f.user(idx), f.user(idx + 1),
                           f.home_ip(idx), f.doc()))
    return out


def _public_share(f: _Factory, times: list[datetime], actor: str, ip: str) -> list[dict[str, Any]]:
    """One actor flips sensitive-looking files to public_on_the_web."""
    return [f.drive("share_public", t, actor, actor, ip, f.doc(sensitive=True)) for t in times]


def _sensitive_download(f: _Factory, times: list[datetime], actor: str, ip: str) -> list[dict[str, Any]]:
    """A burst of downloads of sensitive-looking files by one actor. The files belong to others."""
    return [f.drive("download", t, actor, f.user(1 + i % max(len(f.pool) - 1, 1)), ip, f.doc(sensitive=True))
            for i, t in enumerate(times)]


def _impossible_travel(f: _Factory, times: list[datetime], actor: str, far_ip: str,
                       spread_seconds: int) -> list[dict[str, Any]]:
    """Logins by one actor from their Saudi home address, then (2.5 to 6 hours of event time later)
    from an out-of-country one. The gap is in `id.time`; every event is still sent now."""
    gap = timedelta(seconds=f.rng.randint(9000, 21600) + max(spread_seconds, 0))
    early = len(times) // 2
    home_ip = f.actor_ip(actor)
    return ([f.login(t - gap, actor, home_ip, ok=True, login_type="saml") for t in times[:early]]
            + [f.login(t, actor, far_ip, ok=True) for t in times[early:]])


def sample_event(*, view: OrganizationView, now: datetime) -> dict[str, Any]:
    """One benign, unmistakably-synthetic login (a test user of the organization's domain) for proving the collector path."""
    f = _Factory(view)
    return f.login(now, f"phantom.test@{view.email_domain}", ippools.home_for(0)[0], ok=True)
