"""wec-sender connector: delivers synthetic Windows events to a Cortex XSIAM Broker's Windows Event Collector.

Tools (the runtime strips the `phantom_` prefix, so the agent sees `wec-sender/<tool>`):

  phantom_list_subscriptions  Enumerate the collector's subscriptions (also the connection test)
  phantom_send_test_event     one identifiable event, with an XQL query that proves it landed
  phantom_generate_events     synthetic scenarios from a built-in profile (`windows`: `baseline_logons`)
  phantom_send_events         caller-supplied structured events, rendered to Windows Event XML here

Events are forwarded over WS-Management (source-initiated forwarding, mutual TLS to the applet on 5986) so they
ingest with `_collector_type = "WEC"`: the endpoint-style feed a CEF source cannot produce. This is a deliberate,
scoped exception to Phantom's syslog/CEF-only delivery. The client certificate (PFX) and its
password are read from the instance's secret slots at call time; no tool returns or accepts one, so the agent
never handles a credential. All of this is synthetic telemetry sent only to the operator's own broker.
"""
from __future__ import annotations

import functools
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import get_view

from . import profiles, winevent, wsman

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_CALL = 5000
MAX_SPREAD_SECONDS = 7 * 24 * 3600          # a week
MAX_OFFSET_MINUTES = 2 * 365 * 24 * 60      # two years back
XPATH_PREVIEW = 200
_SYSTEM_KEYS = ("version", "level", "task", "opcode", "record_id", "process_id", "thread_id", "activity_id", "message")
_EVENT_KEYS = {"event_id", "computer", "channel", "provider", "time", "event_data", "outcome", "keywords",
               "rendering", *_SYSTEM_KEYS}


def _settings() -> dict[str, Any]:
    """Instance config and secrets, with defaults. Split out so tests can stub it."""
    from config.config import get_config

    cfg = get_config()

    def get(name: str, default: Any = None) -> Any:
        return getattr(cfg, name, default)

    def number(name: str, default: float) -> float:
        try:
            return float(get(name, default) or default)
        except (TypeError, ValueError):
            return default

    return {
        "url": (get("subscriptionManagerUrl", "") or "").strip(),
        "sender": (get("senderComputerName", "") or "").strip() or wsman.DEFAULT_SENDER_COMPUTER,
        "timeout": number("timeoutSeconds", 30),
        "organization": str(get("organization", "") or "").strip(),   # empty = follow the active organization
        "pfx": get("clientPfx", "") or "",
        "pfx_password": get("clientPfxPassword", "") or "",
    }


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _client(settings: dict[str, Any]) -> tuple[wsman.WecClient | None, dict[str, Any] | None]:
    """(client, None) or (None, error result). Names the missing or wrong setting; never echoes a secret."""
    if not settings["url"]:
        return None, _err("subscriptionManagerUrl is not set: paste the value from the Cortex console "
                          "(Server=HTTPS://<broker>:5986/wsman/SubscriptionManager/WEC,Refresh=...,IssuerCA=...)")
    for slot, label in (("pfx", "clientPfx"), ("pfx_password", "clientPfxPassword")):
        if not str(settings[slot]).strip():
            return None, _err(f"secret {label} is not set on this instance")
    try:
        client = wsman.WecClient(settings["url"], settings["pfx"], settings["pfx_password"],
                                 sender_computer_name=settings["sender"], timeout=settings["timeout"])
    except wsman.WecError as exc:
        return None, _err(str(exc))
    return client, None


def _guarded(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Turn any failure into {ok: false, error}: the agent never sees a stack trace."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except wsman.WecError as exc:
            logger.warning("wec-sender: %s failed: %s", fn.__name__, exc)
            extra = {}
            if exc.report is not None:
                extra = {"sent": exc.report.sent, "envelopes": exc.report.envelopes}
            return _err(str(exc), **extra)
        except winevent.EventError as exc:
            return _err(str(exc))
        except OrganizationUnavailable as exc:
            logger.warning("wec-sender: %s cannot use the organization: %s", fn.__name__, exc)
            return _err(f"the organization is not available: {exc}")
        except Exception as exc:  # noqa: BLE001 - last line of defence for the tool boundary
            logger.error("wec-sender: %s failed unexpectedly: %s", fn.__name__, type(exc).__name__)
            return _err(f"unexpected {type(exc).__name__} in {fn.__name__}; see the connector log")
    return wrapper


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _qualify(computer: str, dns: str) -> str:
    name = computer.strip()
    return name if "." in name else f"{name}.{dns}"


def _summary(rendered: list[winevent.RenderedEvent], report: wsman.SendReport | None, **extra: Any) -> dict[str, Any]:
    per_computer: dict[str, int] = {}
    for r in rendered:
        per_computer[r.computer] = per_computer.get(r.computer, 0) + 1
    out: dict[str, Any] = {
        "ok": True, "events": len(rendered), "computers": per_computer,
        "first_time": _iso(min(r.time for r in rendered)), "last_time": _iso(max(r.time for r in rendered)),
        "sample_record_ids": [r.record_id for r in rendered[:5]],
    }
    if report is not None:
        out.update(sent=report.sent, envelopes=report.envelopes, reenumerations=report.reenumerations,
                   subscriptions=report.by_subscription)
    out.update(extra)
    return out


def _send(client: wsman.WecClient, rendered: list[winevent.RenderedEvent], **extra: Any) -> dict[str, Any]:
    """Forward rendered events. `sent` in the result is the number the applet ACCEPTED (HTTP 200), not the number
    that landed: landing is proven only by the XQL query a tool returns."""
    report = client.send(wsman.WecEvent(r.computer, r.channel, r.xml) for r in rendered)
    return _summary(rendered, report, **extra)


def _deliver(client: wsman.WecClient, events: list[winevent.Event], **extra: Any) -> dict[str, Any]:
    return _send(client, winevent.render_all(events), **extra)


def _whole(name: str, value: Any, low: int, high: int) -> str | None:
    """None when `value` is a whole number in [low, high] (a bool is not one), else the message to return."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return f"{name} must be a whole number from {low} to {high}"
    return None


@_guarded
def phantom_list_subscriptions() -> dict[str, Any]:
    """List the subscriptions the Windows Event Collector offers, which doubles as the connection test.

    Use it first after creating or changing an instance, or when the operator asks "can you reach the
    collector?" / "which subscriptions exist?". It performs a WS-Enumeration against the Broker VM's collector
    over mutual TLS and returns what came back. A success proves the certificate, its CA, the URL and the port.

    Returns:
      {"ok": true, "manager": "broker.example:5986", "sender": "<computer name used>", "subscriptions": [
        {"name": "Authentication Event Logs", "version": "uuid:...", "delivery_path": "/wsman/subscriptions/<guid>/1",
         "max_envelope_size": 524288, "heartbeat": "PT3600.000S", "channels": ["Security"],
         "queries": [{"path": "Security", "xpath": "*[System[(EventID=4776 or ...)]]"}]}, ...]}
      On failure: {"ok": false, "error": "<what to fix>"}.
    """
    settings = _settings()
    client, failure = _client(settings)
    if failure:
        return failure
    subs = client.enumerate()
    return {"ok": True, "manager": f"{client.target.host}:{client.target.port}", "sender": client.sender,
            "subscriptions": [{
                "name": s.name, "version": s.version, "delivery_path": s.delivery_path,
                "max_envelope_size": s.max_envelope_size, "heartbeat": s.heartbeat, "channels": list(s.channels),
                "queries": [{"path": q.path, "xpath": q.xpath[:XPATH_PREVIEW] + ("..." if len(q.xpath) > XPATH_PREVIEW else "")}
                            for q in s.queries]} for s in subs]}


@_guarded
def phantom_send_test_event(computer: str | None = None, event_id: int = 4624) -> dict[str, Any]:
    """Send ONE identifiable test event and return an XQL query that proves it landed.

    Use it after list_subscriptions succeeds, or whenever the operator asks "did it land?". The default is a
    4624 (successful logon) for a clearly synthetic host and user; the test id is the event's LogonGuid. A 4634
    (logoff) is always preceded by its 4624 with the same logon id, so both are sent and reported.

    Args:
      computer: host name (short or FQDN) the event claims to come from. Default: <NETBIOS>-WECTEST01.<domain dns>
        (names from the active organization, e.g. PHANTOM-WECTEST01.phantom.lab for the bundled Phantom Lab). The test
        logon's source address is a stable address from the organization's pool for unmanaged and newly seen devices.
      event_id: one of the catalogue ids: 4624, 4625, 4634, 4672 (default 4624).

    Returns:
      {"ok": true, "sent": 1, "test_id": "<guid>", "sent_at": "<iso>", "computer": "<fqdn>", "event_id": 4624,
       "record_id": 123, "events": [{"event_id": 4624, "record_id": 123, "time": "<iso>"}], "logon_id": "0x...",
       "subscriptions": {"Authentication Event Logs": 1},
       "verify_with_xql": 'dataset = microsoft_windows_raw | filter _collector_type = "WEC" and computer_name = "<fqdn>"'}
      `sent` counts events the applet ACCEPTED (HTTP 200). It does not prove they landed: that is proven only by
      the XQL query returning the row (allow about 10 s).
    """
    settings = _settings()
    client, failure = _client(settings)
    if failure:
        return failure
    directory = profiles.windows.directory(settings["organization"])
    if computer is not None and not isinstance(computer, str):
        return _err("computer must be a host name")
    fqdn = _qualify(computer or directory.test_computer(), directory.dns)
    now = datetime.now(timezone.utc)
    test_id = str(uuid.uuid4())
    defn = None if isinstance(event_id, bool) or not isinstance(event_id, int) else winevent.lookup(event_id)
    if defn is None:
        return _err(f"event_id {event_id!r} is not in the catalogue; use one of "
                    f"{', '.join(str(k[1]) for k in sorted(winevent.CATALOG))}")
    if defn.event_id in (4624, 4634):
        # A logoff is only meaningful after its logon: send the 4624 and then the 4634 with the same logon id.
        logon = profiles.windows.synthetic_test_logon(directory, fqdn, test_id,
                                                      now - timedelta(seconds=2) if defn.event_id == 4634 else now)
        events = [logon] if defn.event_id == 4624 else [logon, profiles.windows.synthetic_test_logoff(logon, now)]
    else:
        sid = directory.user_sid("phantom.wectest")
        named = {"SubjectUserSid": sid, "SubjectUserName": "phantom.wectest", "SubjectDomainName": directory.netbios,
                 "TargetUserSid": sid, "TargetUserName": "phantom.wectest", "TargetDomainName": directory.netbios}
        events = [winevent.Event(event_id=defn.event_id, computer=fqdn, time=now,
                                 data={k: v for k, v in named.items() if k in dict(defn.fields)},
                                 outcome="failure" if defn.event_id == 4625 else "success")]
    rendered = winevent.render_all(events)
    result = _send(client, rendered)
    own = next(r for r in reversed(rendered) if r.event_id == defn.event_id)
    return {"ok": True, "sent": result["sent"], "test_id": test_id,
            "test_id_field": "LogonGuid" if any(e.event_id == 4624 for e in events) else None,
            "sent_at": _iso(now), "computer": fqdn, "event_id": defn.event_id, "record_id": own.record_id,
            "events": [{"event_id": r.event_id, "record_id": r.record_id, "time": r.system_time} for r in rendered],
            "logon_id": dict(events[0].data).get("TargetLogonId") if defn.event_id in (4624, 4634) else None,
            "subscriptions": result["subscriptions"],
            "verify_with_xql": f'dataset = microsoft_windows_raw | filter _collector_type = "WEC" and computer_name = "{fqdn}"'}


@_guarded
def phantom_generate_events(profile: str = "windows", scenario: str = "baseline_logons", count: int = 20,
                            spread_seconds: int = 120, start_offset_minutes: int = 0,
                            dry_run: bool = False) -> dict[str, Any]:
    """Generate synthetic Windows events from a built-in profile and forward them over WEC.

    The profile `windows` uses the ACTIVE ORGANIZATION (the same people, accounts, hosts and domain every other
    connector uses; read it with organization_get): its domain controllers, servers and workstations, and its
    staff, administrator and service accounts. A leaver's account and the break-glass account are never part of
    baseline traffic. Identities are stable: a login always has the same SID and home workstation, a host the same
    address, so repeated runs build a baseline. If no organization is active the tool returns an error that says
    what to fix; it never invents a domain.

    Scenario `baseline_logons`: benign traffic shaped by the time of day (business hours are the organization's:
    its working week and office hours in its local time): interactive, unlock and cached logons on workstations (4624), network logons on servers
    and DCs, service-account logons, occasional administrator RDP with special privileges (4672), and a 4634
    logoff for each logon later in the window. More scenarios (failed logons, Kerberos, AD FS) plug into the
    same registry later.

    Args:
      profile: the built-in profile; only "windows" today.
      scenario: "baseline_logons" today.
      count: total events, 1-5000 (default 20).
      spread_seconds: width of the time window the events are spread across, 1-604800 (default 120).
      start_offset_minutes: end the window this many minutes in the past, to back-date, 0-1051200 (default 0). The
        event's own TimeCreated is `_time` on the tenant, so back-dating works.
      dry_run: true = build and return the first 3 events (with their XML) without sending anything.

    Returns (`sent` = events the applet ACCEPTED with HTTP 200; landing is proven only by an XQL query on the dataset):
      {"ok": true, "events": 40, "sent": 40, "envelopes": 14, "computers": {"phws-004.<domain dns>": 6, ...},
       "first_time": "<iso>", "last_time": "<iso>", "sample_record_ids": [..], "subscriptions": {...},
       "profile": "windows", "scenario": "baseline_logons"}. dry_run adds "preview": [...] and sends nothing.

    Example payload:
      {"profile": "windows", "scenario": "baseline_logons", "count": 200, "spread_seconds": 3600,
       "start_offset_minutes": 120}
    """
    try:
        prof = profiles.get(profile)
    except ValueError as exc:
        return _err(str(exc), profiles=sorted(profiles.PROFILES))
    for message in (_whole("count", count, 1, MAX_EVENTS_PER_CALL),
                    _whole("spread_seconds", spread_seconds, 1, MAX_SPREAD_SECONDS),
                    _whole("start_offset_minutes", start_offset_minutes, 0, MAX_OFFSET_MINUTES)):
        if message:
            return _err(message)
    settings = _settings()
    directory = prof.directory(settings["organization"])
    try:
        events = prof.build_events(scenario, count, directory=directory, now=datetime.now(timezone.utc),
                                   spread_seconds=spread_seconds, start_offset_minutes=start_offset_minutes)
    except ValueError as exc:
        return _err(str(exc), scenarios=list(prof.SCENARIOS))
    meta = {"profile": prof.NAME, "scenario": scenario}
    if dry_run:
        rendered = winevent.render_all(events)
        out = _summary(rendered, None, dry_run=True, sent=0, **meta)
        out["preview"] = [{"event_id": r.event_id, "computer": r.computer, "channel": r.channel,
                           "time": r.system_time, "record_id": r.record_id, "xml": r.xml} for r in rendered[:3]]
        return out
    client, failure = _client(settings)
    if failure:
        return failure
    return _deliver(client, events, **meta)


_RELATIVE_TIME = re.compile(r"^now(?:\s*-\s*(\d+)\s*(s|m|h)?)?$", re.I)


def _relative_time(text: str) -> datetime | None:
    """`now`, `now-120s`, `now-5m`, `now-1h`: the connector's own clock, so a model never does clock arithmetic."""
    m = _RELATIVE_TIME.match(text)
    if not m:
        return None
    seconds = int(m.group(1) or 0) * {"s": 1, "m": 60, "h": 3600}[(m.group(2) or "s").lower()]
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    relative = _relative_time(str(value).strip())
    if relative is not None:
        return relative
    text = str(value).strip().replace("Z", "+00:00")
    if "." in text:  # Windows writes 7 fractional digits; fromisoformat takes at most 6
        head, _, rest = text.partition(".")
        digits = ""
        for ch in rest:
            if not ch.isdigit():
                break
            digits += ch
        text = f"{head}.{digits[:6].ljust(6, '0')}{rest[len(digits):]}"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _structured_event(index: int, raw: Any, default_dns: str) -> winevent.Event:
    """One caller-supplied dict as an Event; ValueError names the item and the problem."""
    where = f"events[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be an object")
    unknown = sorted(set(raw) - _EVENT_KEYS)
    if unknown:
        raise ValueError(f"{where} has unknown field(s) {', '.join(unknown)}; allowed: {', '.join(sorted(_EVENT_KEYS))}")
    try:
        event_id = int(raw["event_id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError(f"{where}.event_id is required and must be a whole number") from None
    computer = str(raw.get("computer") or "").strip()
    if not computer:
        raise ValueError(f"{where}.computer is required")
    data = raw.get("event_data")
    if data is not None and not isinstance(data, (dict, list)):
        raise ValueError(f"{where}.event_data must be an object (named Data) or a list (positional Data)")
    rendering = raw.get("rendering") or {}
    if not isinstance(rendering, dict):
        raise ValueError(f"{where}.rendering must be an object")
    outcome = raw.get("outcome")
    if outcome is None:
        kw = raw.get("keywords")
        outcome = " ".join(kw) if isinstance(kw, list) else (kw or "success")
    for key in ("channel", "provider"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            raise ValueError(f"{where}.{key} must be a string")
    try:
        when = _parse_time(raw.get("time"))
    except (ValueError, OverflowError, OSError):
        raise ValueError(f"{where}.time must be an ISO-8601 timestamp or epoch seconds") from None
    system = {k: raw[k] for k in _SYSTEM_KEYS if raw.get(k) is not None}
    try:
        for k in ("version", "level", "task", "opcode", "record_id", "process_id", "thread_id"):
            if k in system:
                system[k] = int(system[k])
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{where}: version, level, task, opcode, record_id, process_id and thread_id must be whole numbers") from None
    return winevent.Event(event_id=event_id, computer=_qualify(computer, default_dns), channel=raw.get("channel"),
                          provider=raw.get("provider"), time=when, data=data, outcome=str(outcome),
                          rendering=rendering, **system)


@_guarded
def phantom_send_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Forward caller-supplied STRUCTURED events; the connector renders each to Windows Event XML.

    Use it for a specific event the operator wants to test, or an id with no scenario yet. Catalogued ids (4624,
    4625, 4634, 4672) get real rendered text (message, task, level, keywords) for free. Any other id needs
    `provider`, `rendering.message` and `rendering.task`. Always give `time` (ISO-8601 UTC, or epoch seconds) to
    back-date; the default is now.

    Args:
      events: list of 1-5000 objects, each:
        event_id (int, required), computer (required; short names get the active organization's DNS suffix),
        channel (default Security), provider (default: the catalogue's), time,
        event_data (object = named Data, or list = positional Data: AD FS events use unnamed Data),
        outcome ("success" | "failure", or keywords: ["Audit Failure"]; failure sets event_result=failure),
        rendering ({message, level, task, opcode, channel, provider, keywords}: overrides for the rendered text),
        and optional System overrides: version, level, task, opcode, record_id, process_id, thread_id,
        activity_id, message.

    Returns (`sent` = events the applet ACCEPTED with HTTP 200; landing is proven only by an XQL query):
      {"ok": true, "events": 2, "sent": 2, "envelopes": 1, "computers": {...}, "first_time": "...",
       "last_time": "...", "sample_record_ids": [...], "subscriptions": {"Authentication Event Logs": 2}}

    Example payload:
      {"events": [{"event_id": 4625, "computer": "<a workstation of the active organization>", "outcome": "failure",
                   "time": "2026-10-03T09:15:00Z",
                   "event_data": {"TargetUserName": "<a login of the active organization>",
                                  "TargetDomainName": "<its NetBIOS name>", "IpAddress": "<the workstation's address>",
                                  "LogonType": "3"}}]}
      Take the names, NetBIOS domain and addresses from the active organization (organization_get) so the event
      belongs to a real person and host there.
    """
    if not isinstance(events, list) or not events:
        return _err("events must be a non-empty list of objects")
    if len(events) > MAX_EVENTS_PER_CALL:
        return _err(f"at most {MAX_EVENTS_PER_CALL} events per call")
    settings = _settings()
    default_dns = get_view(settings["organization"] or None).dns   # read now, so a missing organization is a clear error
    parsed = []
    for index, raw in enumerate(events):
        try:
            parsed.append(_structured_event(index, raw, default_dns))
        except ValueError as exc:
            return _err(str(exc))
    try:
        winevent.render_all(parsed)  # validate every event before anything is sent
    except winevent.EventError as exc:
        return _err(str(exc))
    except (ValueError, TypeError, OverflowError, UnicodeError) as exc:
        return _err(f"an event could not be rendered ({type(exc).__name__}); check event_data, rendering and the system fields")
    client, failure = _client(settings)
    if failure:
        return failure
    return _deliver(client, parsed)


__all__ = ["phantom_list_subscriptions", "phantom_send_test_event", "phantom_generate_events", "phantom_send_events"]
