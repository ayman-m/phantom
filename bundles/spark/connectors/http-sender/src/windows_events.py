"""Windows events for the `cribl_windows_events` destination.

The Windows Event Logs source of the Cortex Cribl endpoint takes Windows Event XML, not a JSON object. Measured on a
Cortex tenant: the XML posted as ONE PLAIN STRING,
`{"data": "<Event xmlns=...>...</Event>"}`, lands fully parsed in `microsoft_windows_raw` and fires the Windows identity
detectors; the same XML wrapped in an object (`{"data": {"_raw": "<Event ...>"}}`) is accepted with HTTP 200 and lands
nothing. So what `cribl.post` receives for this destination is the XML string itself.

This module accepts exactly what `wec-sender.send_events` accepts (a structured event: `event_id`, `computer`, `time`,
`provider`, `rendering`, `event_data`, ...), renders it with the renderer copied from wec-sender (`winevent.py`), and also
lets a caller pass XML it already has. `structured_event`, `qualify` and `parse_time` are ports of wec-sender's
`_structured_event`, `_qualify` and `_parse_time`; keep them in step (tests/test_windows_events.py compares the XML both
connectors produce for the nine WEC trigger skills).

Standard library only.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from . import winevent

DEFAULT_DNS = "phantom.lab"
# The synthetic domain's SID (the one wec-sender's `windows` profile and the nine WEC trigger skills use).
DOMAIN_SID = "S-1-5-21-3623811015-3361044348-30300820"
TEST_COMPUTER = "PHANTOM-CRIBLTEST01"

_SYSTEM_KEYS = ("version", "level", "task", "opcode", "record_id", "process_id", "thread_id", "activity_id", "message")
_EVENT_KEYS = {"event_id", "computer", "channel", "provider", "time", "event_data", "outcome", "keywords",
               "rendering", *_SYSTEM_KEYS}
# Described to the caller whenever a string is refused, so the fix is in the message.
XML_HINT = "a string must be Windows Event XML starting with <Event; otherwise pass a structured event object"


class Prepared(NamedTuple):
    """One event ready to post: its XML and what a result reports about it."""

    xml: str
    computer: str
    time: datetime | None
    record_id: int | None


def qualify(computer: str, dns: str) -> str:
    """A short computer name with the domain's DNS suffix; a name that already has a dot is left alone."""
    name = computer.strip()
    return name if "." in name else f"{name}.{dns}"


_RELATIVE_TIME = re.compile(r"^now(?:\s*-\s*(\d+)\s*(s|m|h)?)?$", re.I)


def _relative_time(text: str) -> datetime | None:
    """`now`, `now-120s`, `now-5m`, `now-1h`: the connector's own clock, so a model never does clock arithmetic."""
    m = _RELATIVE_TIME.match(text)
    if not m:
        return None
    seconds = int(m.group(1) or 0) * {"s": 1, "m": 60, "h": 3600}[(m.group(2) or "s").lower()]
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def parse_time(value: Any) -> datetime | None:
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


def structured_event(index: int, raw: Any, default_dns: str) -> winevent.Event:
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
        when = parse_time(raw.get("time"))
    except (ValueError, OverflowError, OSError):
        raise ValueError(f"{where}.time must be an ISO-8601 timestamp or epoch seconds") from None
    system = {k: raw[k] for k in _SYSTEM_KEYS if raw.get(k) is not None}
    try:
        for k in ("version", "level", "task", "opcode", "record_id", "process_id", "thread_id"):
            if k in system:
                system[k] = int(system[k])
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{where}: version, level, task, opcode, record_id, process_id and thread_id must be whole numbers") from None
    return winevent.Event(event_id=event_id, computer=qualify(computer, default_dns), channel=raw.get("channel"),
                          provider=raw.get("provider"), time=when, data=data, outcome=str(outcome),
                          rendering=rendering, **system)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _as_given(index: int, text: str) -> Prepared:
    """A string the caller already rendered: checked (never changed) and described. ValueError names the item."""
    where = f"events[{index}]"
    if not text.lstrip().startswith("<Event"):
        raise ValueError(f"{where} is a string but not Windows Event XML: {XML_HINT}")
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError(f"{where} must not declare a DOCTYPE or an ENTITY")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:  # the message holds a position, never the text
        raise ValueError(f"{where} is not well-formed XML ({exc})") from None
    if _local(root.tag) != "Event":
        raise ValueError(f"{where} is XML but its root is not <Event>: {XML_HINT}")
    computer, when, record = "", None, None
    for node in root.iter():
        name = _local(node.tag)
        if name == "Computer" and not computer:
            computer = (node.text or "").strip()
        elif name == "TimeCreated" and when is None:
            try:
                when = parse_time(node.attrib.get("SystemTime"))
            except (ValueError, OverflowError, OSError):
                when = None
        elif name == "EventRecordID" and record is None and (node.text or "").strip().isdigit():
            record = int(node.text.strip())
    return Prepared(text, computer or "(unknown)", when, record)


def _render_problem(ev: winevent.Event) -> str | None:
    """Why `ev` cannot be rendered, or None."""
    try:
        winevent.render_event(ev)
    except winevent.EventError as exc:
        return str(exc)
    except (ValueError, TypeError, OverflowError, UnicodeError) as exc:
        return (f"could not be rendered ({type(exc).__name__}); check event_data, rendering and the system fields")
    return None


def prepare(items: list[Any], default_dns: str = DEFAULT_DNS) -> list[Prepared]:
    """Everything in `items` as XML, validated before anything is sent. Raises ValueError naming the first bad item.

    A dict is a structured event (the wec-sender shape): rendered with the copied renderer, in time order and with
    per-computer record ids exactly as wec-sender does, and those come first in the result. A string is Windows Event XML
    the caller already has and is passed through unchanged, after the others, in the order given."""
    structured: list[tuple[int, winevent.Event]] = []
    given: list[Prepared] = []
    for index, raw in enumerate(items):
        if isinstance(raw, str):
            given.append(_as_given(index, raw))
        elif isinstance(raw, dict):
            structured.append((index, structured_event(index, raw, default_dns)))
        else:
            raise ValueError(f"events[{index}] must be an object (a structured Windows event) or a string of Windows Event XML")
    rendered: list[winevent.RenderedEvent] = []
    if structured:
        try:
            rendered = winevent.render_all([ev for _, ev in structured])
        except (ValueError, TypeError, OverflowError, UnicodeError):
            for index, ev in structured:  # name the item that cannot be rendered
                problem = _render_problem(ev)
                if problem:
                    raise ValueError(f"events[{index}]: {problem}") from None
            raise ValueError("an event could not be rendered; check event_data, rendering and the system fields") from None
    return [Prepared(r.xml, r.computer, r.time, r.record_id) for r in rendered] + given


def summary(prepared: list[Prepared]) -> dict[str, Any]:
    """What a send result reports about the events: count, per-computer counts, first and last time, sample record ids."""
    computers: dict[str, int] = {}
    for p in prepared:
        computers[p.computer] = computers.get(p.computer, 0) + 1
    times = [p.time for p in prepared if p.time is not None]
    out: dict[str, Any] = {"events": len(prepared), "computers": computers,
                           "sample_record_ids": [p.record_id for p in prepared[:5] if p.record_id is not None]}
    if times:
        out["first_time"], out["last_time"] = iso(min(times)), iso(max(times))
    return out


def iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_test_event(dns: str, test_id: str, now: datetime) -> tuple[dict[str, Any], dict[str, str]]:
    """One benign 4624 (network logon) as a structured event, plus what the result reports about it.

    Like wec-sender's test event: a clearly synthetic host, the test id in `LogonGuid` (a field that is a GUID by nature).
    The actor is fresh on every call (its name carries the start of the test id), so a test never joins another actor's
    history. The suffix is lower-cased (wec-sender's test event goes through its Directory, which does the same) and the
    NetBIOS domain is its first label, upper-cased."""
    dns = dns.strip().lower()
    netbios = (dns.split(".")[0] or "phantom").upper()
    fqdn = qualify(TEST_COMPUTER, dns)
    login = "phantom.test" + test_id.replace("-", "")[:6].lower()
    sid = f"{DOMAIN_SID}-{5000 + int(hashlib.sha1(login.encode()).hexdigest(), 16) % 90000}"
    digest = hashlib.sha256(f"{fqdn}|{login}|{now.isoformat()}".encode()).digest()
    logon_id = f"0x{int.from_bytes(digest[:4], 'big') % 0xFFF000 + 0x10000:X}"
    event = {
        "event_id": 4624, "computer": fqdn, "channel": "Security", "time": iso(now),
        "event_data": {
            "SubjectUserSid": "S-1-5-18", "SubjectUserName": TEST_COMPUTER.upper() + "$", "SubjectDomainName": netbios,
            "SubjectLogonId": "0x3E7", "TargetUserSid": sid, "TargetUserName": login, "TargetDomainName": netbios,
            "TargetLogonId": logon_id, "LogonType": "3", "LogonProcessName": "Kerberos",
            "AuthenticationPackageName": "Kerberos", "WorkstationName": TEST_COMPUTER.upper(),
            "LogonGuid": "{" + test_id.upper() + "}", "LmPackageName": "-", "KeyLength": "0",
            "IpAddress": "10.20.250.250", "IpPort": "49999"},
    }
    return event, {"computer": fqdn, "actor": login, "logon_id": logon_id}
