# COPY of ../wec-sender/src/winevent.py (the Windows Event XML renderer). The two connectors ship as separate
# container images and cannot share code, so the renderer is duplicated here; it MUST stay in step with the original:
# a change to one is a change to the other, and tests/test_windows_events.py loads both and compares their XML byte for
# byte. Only this header differs.
"""Windows Event XML renderer and event catalogue for wec-sender.

Standalone module (standard library only). It turns a structured `Event` into the XML a Windows forwarder sends
over WEC, in the Windows Event XML schema (namespace http://schemas.microsoft.com/win/2004/08/events/event):

    <Event xmlns="..."> <System>...</System> <EventData>...</EventData> <RenderingInfo>...</RenderingInfo> </Event>

The Cortex WEC applet builds its dataset columns from this XML (measured on a Cortex tenant):
  _time           System/TimeCreated@SystemTime            (so back-dating works)
  event_id, provider_name, provider_guid, computer_name, channel, record_id, process_pid, process_thread_id
                  System
  event_action    RenderingInfo/Task          message  RenderingInfo/Message        log_level  RenderingInfo/Level
  event_result    "failure" when RenderingInfo/Keywords holds "Audit Failure", else "success"
  event_data      JSON of EventData/Data: named Data keyed by Name; UNNAMED Data become param1..paramN
                  (AD FS events rely on that)
so RenderingInfo is always real text, never a placeholder.

THE CATALOGUE IS A TABLE (`CATALOG`): adding an event id is a data change, one `EventDef` in `_define`. Each entry
carries the provider, version, task number and display name, the standard first sentence of the message (mandatory)
with the field block, and the EventData field list with defaults. Left for later, with the shape each needs:
  4688  process creation        Security / Process Creation (task 13312), named Data
  4768  Kerberos TGT request    Security / Kerberos Authentication Service (14339), named Data
  4769  Kerberos service ticket Security / Kerberos Service Ticket Operations (14337), named Data
  4662  object operation        Security / Directory Service Access (14080), named Data
  4728, 4732  group membership  Security / Security Group Management (13826), named Data
  4720  user account created    Security / User Account Management (13824), named Data
  4776  NTLM credential check   Security / Credential Validation (14336), named Data
  AD FS 1200  provider "AD FS Auditing", channel Security, UNNAMED (positional) Data: set `positional=True`
              and give `fields` as ("param1", ...) names; callers then pass a list.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

EVT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"
SECURITY_PROVIDER = "Microsoft-Windows-Security-Auditing"
SECURITY_GUID = "{54849625-5478-4994-A5BA-3E3B0328C30D}"
SECURITY_DISPLAY = "Microsoft Windows security auditing."
KEYWORDS_SUCCESS = "0x8020000000000000"
KEYWORDS_FAILURE = "0x8010000000000000"
_LEVEL_TEXT = {0: "Information", 1: "Critical", 2: "Error", 3: "Warning", 4: "Information", 5: "Verbose"}
_OPCODE_TEXT = {0: "Info", 1: "Start", 2: "Stop"}
# Parameter-message ids Windows stores in EventData; the Message shows their text.
_PARAM_TEXT = {"%%1832": "Identification", "%%1833": "Impersonation", "%%1840": "Delegation",
               "%%1842": "Yes", "%%1843": "No", "%%2313": "Unknown user name or bad password."}
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


class EventError(ValueError):
    """The event cannot be rendered (unknown id without enough text, bad time, ...). The message says what to add."""


@dataclass(frozen=True)
class EventDef:
    event_id: int
    provider: str
    provider_guid: str
    provider_display: str
    channel: str
    version: int
    task: int
    task_name: str
    message: str                                   # first line = the standard first sentence; {Field} placeholders
    fields: tuple[tuple[str, str], ...] = ()       # (EventData name, default value), in wire order
    level: int = 0
    opcode: int = 0
    keywords_success: str = KEYWORDS_SUCCESS
    keywords_failure: str = KEYWORDS_FAILURE
    positional: bool = False                       # unnamed Data (param1..paramN)


CATALOG: dict[tuple[str, int], EventDef] = {}


def _define(**kw: Any) -> EventDef:
    d = EventDef(provider=SECURITY_PROVIDER, provider_guid=SECURITY_GUID, provider_display=SECURITY_DISPLAY,
                 channel="Security", **kw)
    CATALOG[(d.provider, d.event_id)] = d
    return d


_SUBJECT = """Subject:
\tSecurity ID:\t\t{SubjectUserSid}
\tAccount Name:\t\t{SubjectUserName}
\tAccount Domain:\t\t{SubjectDomainName}
\tLogon ID:\t\t{SubjectLogonId}"""

_define(
    event_id=4624, version=2, task=12544, task_name="Logon",
    message=f"""An account was successfully logged on.

{_SUBJECT}

Logon Information:
\tLogon Type:\t\t{{LogonType}}
\tRestricted Admin Mode:\t{{RestrictedAdminMode}}
\tVirtual Account:\t\t{{VirtualAccount}}
\tElevated Token:\t\t{{ElevatedToken}}

Impersonation Level:\t\t{{ImpersonationLevel}}

New Logon:
\tSecurity ID:\t\t{{TargetUserSid}}
\tAccount Name:\t\t{{TargetUserName}}
\tAccount Domain:\t\t{{TargetDomainName}}
\tLogon ID:\t\t{{TargetLogonId}}
\tLinked Logon ID:\t\t{{TargetLinkedLogonId}}
\tNetwork Account Name:\t{{TargetOutboundUserName}}
\tNetwork Account Domain:\t{{TargetOutboundDomainName}}
\tLogon GUID:\t\t{{LogonGuid}}

Process Information:
\tProcess ID:\t\t{{ProcessId}}
\tProcess Name:\t\t{{ProcessName}}

Network Information:
\tWorkstation Name:\t{{WorkstationName}}
\tSource Network Address:\t{{IpAddress}}
\tSource Port:\t\t{{IpPort}}

Detailed Authentication Information:
\tLogon Process:\t\t{{LogonProcessName}}
\tAuthentication Package:\t{{AuthenticationPackageName}}
\tTransited Services:\t{{TransmittedServices}}
\tPackage Name (NTLM only):\t{{LmPackageName}}
\tKey Length:\t\t{{KeyLength}}""",
    fields=(
        ("SubjectUserSid", "S-1-5-18"), ("SubjectUserName", "-"), ("SubjectDomainName", "-"),
        ("SubjectLogonId", "0x3E7"), ("TargetUserSid", "S-1-0-0"), ("TargetUserName", "-"),
        ("TargetDomainName", "-"), ("TargetLogonId", "0x0"), ("LogonType", "3"),
        ("LogonProcessName", "NtLmSsp "), ("AuthenticationPackageName", "NTLM"), ("WorkstationName", "-"),
        ("LogonGuid", "{00000000-0000-0000-0000-000000000000}"), ("TransmittedServices", "-"),
        ("LmPackageName", "NTLM V2"), ("KeyLength", "128"), ("ProcessId", "0x0"), ("ProcessName", "-"),
        ("IpAddress", "-"), ("IpPort", "-"), ("ImpersonationLevel", "%%1833"), ("RestrictedAdminMode", "-"),
        ("TargetOutboundUserName", "-"), ("TargetOutboundDomainName", "-"), ("VirtualAccount", "%%1843"),
        ("TargetLinkedLogonId", "0x0"), ("ElevatedToken", "%%1843"),
    ),
)

_define(
    event_id=4625, version=0, task=12546, task_name="Logon",
    message=f"""An account failed to log on.

{_SUBJECT}

Logon Type:\t\t\t{{LogonType}}

Account For Which Logon Failed:
\tSecurity ID:\t\t{{TargetUserSid}}
\tAccount Name:\t\t{{TargetUserName}}
\tAccount Domain:\t\t{{TargetDomainName}}

Failure Information:
\tFailure Reason:\t\t{{FailureReason}}
\tStatus:\t\t\t{{Status}}
\tSub Status:\t\t{{SubStatus}}

Process Information:
\tCaller Process ID:\t{{ProcessId}}
\tCaller Process Name:\t{{ProcessName}}

Network Information:
\tWorkstation Name:\t{{WorkstationName}}
\tSource Network Address:\t{{IpAddress}}
\tSource Port:\t\t{{IpPort}}

Detailed Authentication Information:
\tLogon Process:\t\t{{LogonProcessName}}
\tAuthentication Package:\t{{AuthenticationPackageName}}
\tTransited Services:\t{{TransmittedServices}}
\tPackage Name (NTLM only):\t{{LmPackageName}}
\tKey Length:\t\t{{KeyLength}}""",
    fields=(
        ("SubjectUserSid", "S-1-0-0"), ("SubjectUserName", "-"), ("SubjectDomainName", "-"),
        ("SubjectLogonId", "0x0"), ("TargetUserSid", "S-1-0-0"), ("TargetUserName", "-"),
        ("TargetDomainName", "-"), ("Status", "0xC000006D"), ("FailureReason", "%%2313"),
        ("SubStatus", "0xC000006A"), ("LogonType", "3"), ("LogonProcessName", "NtLmSsp "),
        ("AuthenticationPackageName", "NTLM"), ("WorkstationName", "-"), ("TransmittedServices", "-"),
        ("LmPackageName", "-"), ("KeyLength", "0"), ("ProcessId", "0x0"), ("ProcessName", "-"),
        ("IpAddress", "-"), ("IpPort", "-"),
    ),
)

_define(
    event_id=4634, version=0, task=12545, task_name="Logoff",
    message="""An account was logged off.

Subject:
\tSecurity ID:\t\t{TargetUserSid}
\tAccount Name:\t\t{TargetUserName}
\tAccount Domain:\t\t{TargetDomainName}
\tLogon ID:\t\t{TargetLogonId}

Logon Type:\t\t\t{LogonType}

This event is generated when a logon session is destroyed. It may be positively correlated with a logon event \
using the Logon ID value. Logon IDs are only unique between reboots on the same computer.""",
    fields=(("TargetUserSid", "S-1-0-0"), ("TargetUserName", "-"), ("TargetDomainName", "-"),
            ("TargetLogonId", "0x0"), ("LogonType", "3")),
)

_define(
    event_id=4672, version=0, task=12548, task_name="Special Logon",
    message=f"""Special privileges assigned to new logon.

{_SUBJECT}

Privileges:\t\t{{PrivilegeList}}""",
    fields=(("SubjectUserSid", "S-1-5-18"), ("SubjectUserName", "-"), ("SubjectDomainName", "-"),
            ("SubjectLogonId", "0x3E7"),
            ("PrivilegeList", "SeSecurityPrivilege\n\t\t\tSeBackupPrivilege\n\t\t\tSeRestorePrivilege\n\t\t\t"
                              "SeTakeOwnershipPrivilege\n\t\t\tSeDebugPrivilege\n\t\t\tSeSystemEnvironmentPrivilege\n\t\t\t"
                              "SeLoadDriverPrivilege\n\t\t\tSeImpersonatePrivilege\n\t\t\tSeEnableDelegationPrivilege")),
)


def lookup(event_id: int, provider: str | None = None) -> EventDef | None:
    """The catalogue entry for an event id (optionally pinned to a provider), or None."""
    if provider is not None:
        return CATALOG.get((provider, int(event_id)))
    return next((d for (_, i), d in CATALOG.items() if i == int(event_id)), None)


# ── the structured event ────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Event:
    """One event, structured. Only `event_id` and `computer` are required for a catalogued id."""

    event_id: int
    computer: str
    channel: str | None = None
    provider: str | None = None
    time: datetime | None = None                 # timezone-aware or naive UTC; default: now
    data: Mapping[str, Any] | list[Any] | None = None   # dict = named Data, list = positional Data
    outcome: str = "success"                     # "success" | "failure" (or "Audit Success"/"Audit Failure")
    version: int | None = None
    level: int | None = None
    task: int | None = None
    opcode: int | None = None
    record_id: int | None = None
    process_id: int | None = None
    thread_id: int | None = None
    activity_id: str | None = None
    message: str | None = None
    rendering: Mapping[str, Any] = field(default_factory=dict)   # message, level, task, opcode, channel, provider, keywords


@dataclass(frozen=True)
class RenderedEvent:
    xml: str
    computer: str
    channel: str
    event_id: int
    record_id: int
    time: datetime
    system_time: str


def system_time(when: datetime) -> str:
    """Windows' SystemTime: UTC with a 7-digit fraction (100 ns ticks) and a trailing Z."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond:06d}0Z"


class RecordIds:
    """EventRecordID, monotonic per computer and stateless across restarts: derived from the event time
    (milliseconds since 2026-01-01), bumped by one when two events of a computer would collide."""

    def __init__(self) -> None:
        self._last: dict[str, int] = {}

    def next(self, computer: str, when: datetime) -> int:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        candidate = max(1000, int((when - _EPOCH).total_seconds() * 1000))
        rid = max(self._last.get(computer, 0) + 1, candidate)
        self._last[computer] = rid
        return rid


def _s(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return _XML_ILLEGAL.sub("", str(value))


def _strict(value: Any, what: str) -> str:
    """`value` as text, refused (not silently altered) when it holds characters XML cannot carry. Used for the
    names that route and identify an event: the computer and the EventData `Name` keys."""
    text = value if isinstance(value, str) else str(value)
    if _XML_ILLEGAL.search(text):
        raise EventError(f"{what} contains a control or invalid character (control codes and lone surrogates cannot be sent)")
    return text


def _merged_data(defn: EventDef | None, data: Any) -> list[tuple[str | None, str]]:
    """EventData entries as (name or None, value), catalogue fields first and in wire order."""
    if isinstance(data, (list, tuple)):
        return [(None, _s(v)) for v in data]
    given = dict(data or {})
    out: list[tuple[str | None, str]] = []
    if defn is not None:
        for name, default in defn.fields:
            out.append((name, _s(given.pop(name, default))))
    out.extend((_strict(k, "an event_data name"), _s(v)) for k, v in given.items())
    if defn is not None and defn.positional and not isinstance(data, (list, tuple)):
        return [(None, v) for _, v in out]
    return out


def _fill(template: str, values: Mapping[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: _PARAM_TEXT.get(values.get(m.group(1), "-"), values.get(m.group(1), "-")), template)


def _x(tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    # Unqualified names plus one literal xmlns attribute on the root (set in render_event): ElementTree cannot
    # serialize qualified elements next to unqualified attributes (Name, Guid, SystemTime) under a default namespace.
    node = ET.Element(tag, attrs)
    if text is not None:
        node.text = text
    return node


def _outcome_is_failure(outcome: str | None) -> bool:
    return "fail" in (outcome or "success").lower()


def render_event(ev: Event, record_id: int | None = None, now: datetime | None = None) -> RenderedEvent:
    """Render one event. Raises EventError when a non-catalogued event lacks the text Windows would have supplied."""
    try:
        event_id = int(ev.event_id)
    except (TypeError, ValueError):
        raise EventError("event_id must be a whole number") from None
    computer = _strict(ev.computer, "the computer name").strip()
    if not computer:
        raise EventError("the computer name is empty")
    defn = lookup(event_id, ev.provider)
    ren = dict(ev.rendering or {})
    provider = ev.provider or ren.get("provider_name") or (defn.provider if defn else None)
    if defn is None:
        missing = [n for n, v in (("provider", provider), ("message", ev.message or ren.get("message")),
                                  ("task (rendering.task)", ren.get("task"))) if not v]
        if missing:
            raise EventError(f"event id {event_id} is not in the catalogue "
                             f"({', '.join(str(k[1]) for k in sorted(CATALOG))}): supply {', '.join(missing)}")
    channel = ev.channel or ren.get("channel") or (defn.channel if defn else "Security")
    when = ev.time or now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    failure = _outcome_is_failure(ev.outcome)
    rid = record_id if record_id is not None else ev.record_id
    if rid is None:
        rid = RecordIds().next(computer, when)
    h = sum(map(ord, computer)) + rid
    process_id = ev.process_id if ev.process_id is not None else 500 + h % 500
    thread_id = ev.thread_id if ev.thread_id is not None else 1000 + (h * 7) % 6000
    level = ev.level if ev.level is not None else (defn.level if defn else 4)
    opcode = ev.opcode if ev.opcode is not None else (defn.opcode if defn else 0)
    task = ev.task if ev.task is not None else (defn.task if defn else 0)
    version = ev.version if ev.version is not None else (defn.version if defn else 0)
    guid = defn.provider_guid if defn and (provider == defn.provider) else None
    sys_keywords = (defn.keywords_failure if failure else defn.keywords_success) if defn else (
        KEYWORDS_FAILURE if failure else KEYWORDS_SUCCESS)

    system = _x("System")
    prov = _x("Provider", Name=_s(provider))
    if guid:
        prov.set("Guid", guid)
    system.append(prov)
    for tag, text in (("EventID", str(event_id)), ("Version", str(version)), ("Level", str(level)),
                      ("Task", str(task)), ("Opcode", str(opcode)), ("Keywords", sys_keywords)):
        system.append(_x(tag, text))
    system.append(_x("TimeCreated", SystemTime=system_time(when)))
    system.append(_x("EventRecordID", str(rid)))
    if ev.activity_id is not None and str(ev.activity_id) != "":
        system.append(_x("Correlation", ActivityID=_s(ev.activity_id)))
    system.append(_x("Execution", ProcessID=str(process_id), ThreadID=str(thread_id)))
    system.append(_x("Channel", _s(channel)))
    system.append(_x("Computer", computer))
    system.append(_x("Security"))

    entries = _merged_data(defn, ev.data)
    event_data = _x("EventData")
    for name, value in entries:
        node = _x("Data", value)
        if name is not None:
            node.set("Name", name)
        event_data.append(node)
    named = {n: v for n, v in entries if n is not None}

    message = ev.message or ren.get("message")
    if not message and defn is not None:
        message = _fill(defn.message, named)
    keywords = ren.get("keywords")
    if keywords is not None and not isinstance(keywords, (list, tuple)):
        keywords = [keywords]
    if not keywords:
        keywords = ["Audit Failure" if failure else "Audit Success"]
    rendering = _x("RenderingInfo", Culture="en-US")
    rendering.append(_x("Message", _s(message)))
    rendering.append(_x("Level", _s(ren.get("level") or _LEVEL_TEXT.get(level, "Information"))))
    rendering.append(_x("Task", _s(ren.get("task") or (defn.task_name if defn else ""))))
    rendering.append(_x("Opcode", _s(ren.get("opcode") or _OPCODE_TEXT.get(opcode, "Info"))))
    rendering.append(_x("Channel", _s(channel)))
    rendering.append(_x("Provider", _s(ren.get("provider") or (defn.provider_display if defn else provider))))
    kw = _x("Keywords")
    for k in keywords:
        kw.append(_x("Keyword", _s(k)))
    rendering.append(kw)

    root = _x("Event", xmlns=EVT_NS)
    root.extend([system, event_data, rendering])
    xml = ET.tostring(root, encoding="unicode")
    return RenderedEvent(xml=xml, computer=computer, channel=_s(channel), event_id=event_id,
                         record_id=rid, time=when, system_time=system_time(when))


def render_all(events: Iterable[Event], record_ids: RecordIds | None = None,
               now: datetime | None = None) -> list[RenderedEvent]:
    """Render in time order (stable), giving every computer strictly increasing record ids."""
    ids = record_ids or RecordIds()
    now = now or datetime.now(timezone.utc)
    stamped = []
    for index, ev in enumerate(events):
        when = ev.time or now
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        stamped.append((when, index, ev))
    out = []
    for when, _, ev in sorted(stamped, key=lambda t: (t[0], t[1])):
        rid = ev.record_id if ev.record_id is not None else ids.next(str(ev.computer).strip(), when)
        out.append(render_event(ev, record_id=rid, now=now))
    return out
