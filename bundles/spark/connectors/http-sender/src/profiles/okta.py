"""The `okta` event profile: synthetic Okta System Log events.

Each event has the shape of one object from Okta's System Log API
(`GET /api/v1/logs`), which is also the shape the Cortex Okta pack's
modeling rules read (`okta_sso_raw` and `okta_okta_raw`): top-level `actor`, `client`, `outcome`,
`target`, `debugContext`, `securityContext`, `authenticationContext`,
`transaction`, `request`, `eventType`, `severity`, `displayMessage`,
`legacyEventType`, `uuid` and `published`.

`published` is an ISO-8601 timestamp. The Okta pack's parsing rule copies it to `_time`,
so with the pack installed a back-dated `published` back-dates the event. Without the pack
(e.g. a tenant without it) the dataset is raw-only and `_time` is the ingestion time.

Identity is UPN-shaped (`alternateId` is an email) and bare. A `DOMAIN\\user`
form may collapse identity in the Cortex analytics engine (UNVERIFIED hypothesis: not measured here;
bare names are used so the question never arises).

Addresses are real, geo-resolvable public IPs from `ippools`, because Cortex derives country, city and ASN
from the IP itself and ignores any label in the event: each benign user has one stable Saudi home address, and
the attack scenarios default to an out-of-country one. `client.geographicalContext` and `securityContext` carry
what Cortex resolves for that address, so the event agrees with the enrichment the analytics engine does itself.
Everything else here is synthetic: names and ids are fictitious.

Two scenarios exist for the `cribl_okta_sso` destination (the Cortex Cribl endpoint under the Okta SSO source UUID, which
gives the events the native feed's treatment): `tor_signin` and `fastpass_phishing`. Both read a Tor exit from the
dated snapshot in `ippools`. `tor_signin` replays the measured recipe, which used BASELINE users (the pool users, so
the detector has a history to compare) with a never-seen app per event; it is the one scenario here whose actors are
not fresh by default, and `target_user` overrides that.

`fastpass_phishing` follows the shape measured on a Cortex tenant (the `trigger_okta_fastpass_phishing_alert` skill) with these
differences, NOT re-measured: the phishing host in `logOnlySecurityData` is a reserved `.invalid` name (the measured one was
real-looking); `client.geographicalContext.geolocation` is null; the country label is null when `source_ip` is given
(otherwise the exit's country from the snapshot); `securityContext.domain` stays
`torproject.org` for every address, and the users are `fastpass.phishing.<id>@<userDomain>` where the measured
shape used a real-looking domain.
"""
from __future__ import annotations

import hashlib
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import _fresh, ippools

# The profile interface (see profiles/__init__.py).
NAME = "okta"
DESCRIPTION = ("Okta System Log objects: benign logins, failed-then-success, password spray, MFA fatigue; "
               "Tor sign-in and FastPass phishing for the cribl_okta_sso destination.")
# The collectors these events are meant for: the new one (vendor Okta, product Okta; models 58 xdm.* fields
# from one event) and the older one (vendor Okta, product SSO). A destination named otherwise is warned about.
EXPECTED_DATASET = "okta_okta"
EXPECTED_DATASETS = ("okta_okta", "okta_sso")
TEST_ID_FIELD = "uuid"
# The field that carries an event's time (the Okta pack's parsing rule copies it to `_time`).
TIME_FIELD = "published"
SCENARIOS = ("benign_logins", "failed_then_success", "password_spray", "mfa_fatigue", "tor_signin", "fastpass_phishing")
# The Cribl destination that suits this profile, and the scenarios that default to it when it is configured. Every
# other scenario keeps the primary destination.
CRIBL_DESTINATIONS = ("cribl_okta_sso",)
SCENARIO_DESTINATION = {"tor_signin": "cribl_okta_sso", "fastpass_phishing": "cribl_okta_sso",
                        "mfa_fatigue": "cribl_okta_sso", "failed_then_success": "cribl_okta_sso"}
# Over the HTTP collector the Okta detectors stay silent except FastPass, so the first two only make sense through Cribl
# (a warning is always given when they go elsewhere). The other two ("Multiple Okta MFA requests" fired from them over
# Cribl) default to Cribl only when it is configured, so an instance without Cribl behaves as before.
CRIBL_ONLY_SCENARIOS = ("tor_signin", "fastpass_phishing")

_USERS = [
    ("Noura", "Alharbi"), ("Khalid", "Alotaibi"), ("Abdullah", "Alzahrani"),
    ("Sara", "Almutairi"), ("Faisal", "Alqahtani"), ("Reem", "Aldosari"),
    ("Omar", "Alshehri"), ("Huda", "Alghamdi"), ("Yousef", "Alharthi"),
    ("Layla", "Almalki"), ("Tariq", "Alsubaie"), ("Dana", "Alanazi"),
]

_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", "Windows 10", "CHROME", "Computer"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15", "Mac OS X", "SAFARI", "Computer"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1", "iOS", "SAFARI", "Mobile"),
]
_ATTACK_AGENT = ("python-requests/2.31.0", "Unknown", "UNKNOWN", "Unknown")
_PHISHED_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
                  "Unknown", "UNKNOWN", "Computer")
# Apps a baseline user has never opened: each tor_signin event gets one of these with a fresh suffix.
_NEW_APPS = ["PagerDuty", "Anaplan", "Intercom", "Lucidchart", "Zendesk", "Asana", "Notion", "Figma", "Miro", "Airtable"]
# `securityContext.asNumber` of a Tor event: the placeholder that fired in the measured runs (Cortex derives the real ASN).
_TOR_AS = 16019
_APPS = ["Salesforce", "Microsoft Office 365", "Slack", "Workday", "ServiceNow", "GitHub Enterprise"]
# `securityContext.domain` of the four home ASNs (ippools.HOME); any other ISP gets a name derived from it.
_ASN_DOMAIN = {25019: "example-isp.example", 35819: "mobily.com.sa", 39891: "example-isp.example", 43766: "zain.com.sa"}


def _isp_domain(net: ippools.Range) -> str:
    """The ISP's domain for `securityContext`: known for the home ASNs, else its first word on a reserved TLD."""
    if net.asn in _ASN_DOMAIN:
        return _ASN_DOMAIN[net.asn]
    word = "".join(c for c in net.isp.split()[0].lower() if c.isalnum())
    return f"{word or 'isp'}.example"


def _geo_context(net: ippools.Range | None) -> dict[str, Any]:
    """`client.geographicalContext` for an address; all null for one outside the pools."""
    return {"city": net and net.city, "state": net and net.region, "country": net and net.country,
            "postalCode": None, "geolocation": {"lat": net.lat, "lon": net.lon} if net else None}


def _security_context(net: ippools.Range | None) -> dict[str, Any]:
    return {"asNumber": net and net.asn, "asOrg": net and net.isp, "isp": net and net.isp,
            "domain": _isp_domain(net) if net else None, "isProxy": False}


def iso(ts: datetime) -> str:
    """Okta's timestamp form: UTC, millisecond precision, trailing Z."""
    ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def user_id(login: str) -> str:
    """The Okta user id (`00u` + 17 characters) of a login: a pure function of it.

    Real Okta gives a user one id for life and every event of that user carries it. A fresh random id per event
    would split one identity into hundreds in any baseline keyed on it, so the id is derived from the login.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    digest = hashlib.sha256(login.strip().lower().encode("utf-8")).digest()
    return "00u" + "".join(alphabet[b % len(alphabet)] for b in digest[:17])


class _Factory:
    """Deterministic when seeded, so the tests can assert on exact output."""

    def __init__(self, domain: str, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.domain = domain

    # -- identities -----------------------------------------------------
    def okta_id(self, prefix: str) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return prefix + "".join(self.rng.choice(alphabet) for _ in range(17))

    def uid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def user(self, index: int) -> dict[str, str]:
        first, last = _USERS[index % len(_USERS)]
        suffix = "" if index < len(_USERS) else str(index // len(_USERS) + 1)
        login = f"{first.lower()}.{last.lower()}{suffix}@{self.domain}"
        return {"id": user_id(login), "login": login, "name": f"{first} {last}{suffix}"}

    # -- event pieces ---------------------------------------------------
    def event(
        self, *, when: datetime, event_type: str, display: str, legacy: str,
        result: str, reason: str | None, actor: dict[str, str], ip: str,
        net: ippools.Range | None, agent: tuple[str, str, str, str],
        severity: str, target: list[dict[str, Any]] | None = None,
        uri: str = "/idp/idx/identify",
    ) -> dict[str, Any]:
        geo_ctx = _geo_context(net)
        raw_ua, os_name, browser, device = agent
        return {
            "actor": {"id": actor["id"], "type": "User", "alternateId": actor["login"],
                      "displayName": actor["name"], "detailEntry": None},
            "client": {"userAgent": {"rawUserAgent": raw_ua, "os": os_name, "browser": browser},
                       "zone": "null", "device": device, "id": None, "ipAddress": ip,
                       "geographicalContext": geo_ctx},
            "device": None,
            "authenticationContext": {"authenticationProvider": None, "credentialProvider": None,
                                      "credentialType": None, "issuer": None, "interface": None,
                                      "authenticationStep": 0,
                                      "externalSessionId": self.okta_id("idx")},
            "displayMessage": display,
            "eventType": event_type,
            "outcome": {"result": result, "reason": reason},
            "published": iso(when),
            "securityContext": _security_context(net),
            "severity": severity,
            "debugContext": {"debugData": {"requestId": self.okta_id("Z"), "requestUri": uri,
                                           "threatSuspected": "false", "url": uri + "?"}},
            "legacyEventType": legacy,
            "transaction": {"type": "WEB", "id": self.okta_id("Z"), "detail": {}},
            "uuid": self.uid(),
            "version": "0",
            "request": {"ipChain": [{"ip": ip, "geographicalContext": geo_ctx, "version": "V4", "source": None}]},
            "target": target if target is not None else [],
        }

    def app_target(self, app: str) -> list[dict[str, Any]]:
        return [{"id": self.okta_id("0oa"), "type": "AppInstance", "alternateId": app,
                 "displayName": app, "detailEntry": None}]

    def user_target(self, user: dict[str, str]) -> list[dict[str, Any]]:
        return [{"id": user["id"], "type": "User", "alternateId": user["login"],
                 "displayName": user["name"], "detailEntry": None}]

    # -- the two building blocks used by every scenario ------------------
    def login(self, when: datetime, user: dict[str, str], ip: str, net: ippools.Range | None, agent: Any,
              *, ok: bool) -> dict[str, Any]:
        return self.event(
            when=when, event_type="user.session.start", display="User login to Okta",
            legacy="core.user_auth.login_success" if ok else "core.user_auth.login_failed",
            result="SUCCESS" if ok else "FAILURE",
            reason=None if ok else "INVALID_CREDENTIALS",
            actor=user, ip=ip, net=net, agent=agent,
            severity="INFO" if ok else "WARN",
            target=self.app_target("Okta Dashboard") if ok else [],
        )

    def sso(self, when: datetime, user: dict[str, str], ip: str, net: ippools.Range | None, agent: Any,
            app: str) -> dict[str, Any]:
        return self.event(
            when=when, event_type="user.authentication.sso", display="User single sign on to app",
            legacy="app.auth.sso", result="SUCCESS", reason=None, actor=user, ip=ip, net=net,
            agent=agent, severity="INFO", target=self.app_target(app), uri="/app/sso/saml",
        )


def _times(end: datetime, count: int, spread_seconds: int) -> list[datetime]:
    """`count` timestamps ascending across the window that ends at `end`."""
    if count <= 1 or spread_seconds <= 0:
        return [end] * max(count, 0)
    step = spread_seconds / (count - 1)
    return [end - timedelta(seconds=spread_seconds - i * step) for i in range(count)]


def build_events(
    scenario: str, count: int, *, domain: str, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build `count` events for `scenario`, oldest first.

    The window ends `start_offset_minutes` before `now` and is
    `spread_seconds` wide; nothing is ever dated after `now`.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    f = _Factory(domain, seed)
    end = now - timedelta(minutes=max(start_offset_minutes, 0))
    times = _times(end, count, spread_seconds)

    if scenario == "benign_logins":
        return _benign(f, times)
    if scenario == "tor_signin":
        return _tor_signin(f, times, target_user, domain, source_ip)
    if scenario == "fastpass_phishing":
        return _fastpass_phishing(f, times, domain, source_ip)
    victim = _named_user(f, target_user, domain)
    # An attacker comes from outside the country; an overriding `source_ip` carries the geography
    # of the pool range it sits in, and none at all when it is in neither pool.
    ip, net = (source_ip, ippools.range_of(source_ip)) if source_ip else ippools.abroad_pick(f.rng)
    if scenario == "failed_then_success":
        return _failed_then_success(f, times, victim, ip, net)
    if scenario == "password_spray":
        return _password_spray(f, times, ip, net)
    return _mfa_fatigue(f, times, victim, ip, net)


def _named_user(f: _Factory, login: str | None, domain: str) -> dict[str, str]:
    if not login:
        return f.user(0)
    login = login.rsplit("\\", 1)[-1]  # a DOMAIN\\user form collapses identity in Cortex analytics
    login = login.lower()  # Okta logins are case-insensitive; one spelling keeps one identity
    login = login if "@" in login else f"{login}@{domain}"
    first = login.split("@", 1)[0].replace(".", " ").title()
    return {"id": user_id(login), "login": login, "name": first}


def _benign(f: _Factory, times: list[datetime]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times):
        idx = i // 2 % len(_USERS)
        (ip, net), user = ippools.home_for(idx), f.user(idx)  # one stable address per user, on every run
        agent = _AGENTS[idx % len(_AGENTS)]
        if i % 2 == 0:
            out.append(f.login(when, user, ip, net, agent, ok=True))
        else:
            out.append(f.sso(when, user, ip, net, agent, _APPS[(i // 2) % len(_APPS)]))
    return out


def _failed_then_success(f: _Factory, times: list[datetime], victim: dict[str, str], ip: str,
                         net: ippools.Range | None) -> list[dict[str, Any]]:
    out = [f.login(t, victim, ip, net, _ATTACK_AGENT, ok=False) for t in times[:-1]]
    out.append(f.login(times[-1], victim, ip, net, _ATTACK_AGENT, ok=True))
    return out


def _password_spray(f: _Factory, times: list[datetime], ip: str, net: ippools.Range | None) -> list[dict[str, Any]]:
    return [f.login(t, f.user(i), ip, net, _ATTACK_AGENT, ok=False) for i, t in enumerate(times)]


def _mfa_fatigue(f: _Factory, times: list[datetime], victim: dict[str, str], ip: str,
                 net: ippools.Range | None) -> list[dict[str, Any]]:
    """Push prompts the user keeps denying, then one approval."""
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times[:-1]):
        if i % 2 == 0:
            out.append(f.event(
                when=when, event_type="system.push.send_factor_verify_push",
                display="Send Okta Verify push", legacy="core.user.factor.attempt_success",
                result="SUCCESS", reason=None, actor=victim, ip=ip, net=net, agent=_ATTACK_AGENT,
                severity="INFO", target=f.user_target(victim), uri="/api/v1/authn/factors"))
        else:
            out.append(f.event(
                when=when, event_type="user.mfa.okta_verify.deny_push",
                display="Deny Okta Verify push", legacy="core.user.factor.attempt_fail",
                result="FAILURE", reason="USER_REJECTED_OKTA_VERIFY_PUSH", actor=victim, ip=ip,
                net=net, agent=_ATTACK_AGENT, severity="WARN", target=f.user_target(victim),
                uri="/api/v1/authn/factors"))
    out.append(f.event(
        when=times[-1], event_type="user.authentication.auth_via_mfa",
        display="Authentication of user via MFA", legacy="core.user.factor.attempt_success",
        result="SUCCESS", reason=None, actor=victim, ip=ip, net=net, agent=_ATTACK_AGENT,
        severity="INFO", target=f.user_target(victim), uri="/api/v1/authn/factors"))
    return out


def _tor_context(ev: dict[str, Any], exit_: ippools.TorExit | None) -> None:
    """Mark an event's `securityContext` as a Tor exit: the proxy flags the detectors read."""
    org = exit_.org if exit_ else "Tor exit relay"
    ev["securityContext"].update({"asNumber": _TOR_AS, "asOrg": org, "isp": org, "domain": "torproject.org", "isProxy": True})


def _tor_signin(f: _Factory, times: list[datetime], target_user: str | None, domain: str,
                source_ip: str | None) -> list[dict[str, Any]]:
    """Successful SSO from a Tor exit: baseline users, a different exit and a never-seen app each time."""
    exits = ippools.tor_exits(f.rng, len(times))
    victim = _named_user(f, target_user, domain) if target_user else None
    start = f.rng.randrange(len(_USERS))
    known = {e.ip: e for e in ippools.ALL_TOR_EXITS}
    out = []
    for i, when in enumerate(times):
        user = victim or f.user((start + i) % len(_USERS))
        ip = source_ip or exits[i].ip
        ev = f.sso(when, user, ip, None, _AGENTS[0], f"{f.rng.choice(_NEW_APPS)} {_fresh.hexs(f.rng, 4)}")
        _tor_context(ev, known.get(ip))
        out.append(ev)
    return out


def _fastpass_phishing(f: _Factory, times: list[datetime], domain: str, source_ip: str | None) -> list[dict[str, Any]]:
    """Okta blocked a FastPass phishing attempt: a brand-new user and a new Tor exit for every event (dedup is per day)."""
    exits = ippools.tor_exits(f.rng, len(times))
    out = []
    for i, when in enumerate(times):
        tag = _fresh.hexs(f.rng, 6)
        login = f"fastpass.phishing.{tag}@{domain}"
        user = {"id": user_id(login), "login": login, "name": f"Fastpass Phishing {tag.upper()}"}
        ip, exit_ = (source_ip, None) if source_ip else (exits[i].ip, exits[i])
        ev = f.event(
            when=when, event_type="user.authentication.auth_via_mfa", display="FastPass declined phishing attempt",
            legacy="core.user.factor.attempt_success", result="FAILURE", reason="FastPass declined phishing attempt",
            actor=user, ip=ip, net=None, agent=_PHISHED_AGENT, severity="WARN", target=[],
            uri="/api/internal/v1/mappings")
        if exit_:
            ev["client"]["geographicalContext"]["country"] = exit_.country
            ev["request"]["ipChain"][0]["geographicalContext"]["country"] = exit_.country
        _tor_context(ev, exit_)
        ev["device"] = {"id": "guo" + _fresh.hexs(f.rng, 19), "name": "Unknown Device", "os_platform": "UNKNOWN",
                        "os_version": "Unknown", "managed": True, "registered": True, "status": "ACTIVE",
                        "screenLockType": "PASSCODE"}
        ev["authenticationContext"].update({
            "authenticationProvider": "FACTOR_PROVIDER", "credentialProvider": "OKTA_CREDENTIAL_PROVIDER",
            "credentialType": "SIGNED_NONCE", "externalSessionId": "ext-session-" + f.uid(),
            "authnContextClassRef": "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken"})
        ev["debugContext"]["debugData"].update({
            "dtHash": _fresh.hexs(f.rng, 64), "deviceFingerprint": _fresh.hexs(f.rng, 32), "factor": "SIGNED_NONCE",
            "risk": "{level=HIGH}",
            "behaviors": "{New Geo-Location=POSITIVE, New Device=NEGATIVE, New IP=POSITIVE, New State=NEGATIVE, "
                         "New Country=NEGATIVE, Velocity Behavior=NEGATIVE, New City=NEGATIVE}",
            "threatSuspected": "true",
            "logOnlySecurityData": '{"behaviors":{},"phishingUrl":"https://login-okta-verify.invalid/login/login.htm?fromURI=%2Fapp%2FuserHome",'
                                   '"originCheckResult":"MISMATCH","requestedUri":"/idp/idx/challenge/answer?"}',
            "threatDetections": '{"Phishing Attempt Blocked": "HIGH"}'})
        out.append(ev)
    return out


def sample_event(*, domain: str, now: datetime) -> dict[str, Any]:
    """One benign, unmistakably-synthetic login for proving the collector path."""
    f = _Factory(domain)
    user = {"id": user_id(f"phantom.test@{domain}"), "login": f"phantom.test@{domain}", "name": "Phantom Test"}
    ip, net = ippools.home_for(0)
    return f.login(now, user, ip, net, _AGENTS[0], ok=True)
