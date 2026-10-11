"""winevent: Windows Event XML rendering and the event catalogue. Offline, standard library only."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest

from src import winevent
from src.winevent import Event

NS = {"e": winevent.EVT_NS}
T0 = datetime(2026, 10, 3, 9, 15, 20, 123456, tzinfo=timezone.utc)


def render(**kw):
    kw.setdefault("computer", "PHDC01.phantom.lab")
    kw.setdefault("time", T0)
    return winevent.render_event(Event(**kw), record_id=kw.pop("record_id", 4242))


def tree(rendered) -> ET.Element:
    return ET.fromstring(rendered.xml)


def sysval(root, tag):
    return root.find(f"e:System/e:{tag}", NS)


def test_4624_system_block():
    r = render(event_id=4624, data={"TargetUserName": "nalharbi", "LogonType": "2"})
    root = tree(r)
    assert root.tag == f"{{{winevent.EVT_NS}}}Event"
    prov = sysval(root, "Provider")
    assert prov.get("Name") == "Microsoft-Windows-Security-Auditing"
    assert prov.get("Guid") == "{54849625-5478-4994-A5BA-3E3B0328C30D}"
    assert [sysval(root, t).text for t in ("EventID", "Version", "Level", "Task", "Opcode", "Keywords", "Channel", "Computer")] == \
        ["4624", "2", "0", "12544", "0", "0x8020000000000000", "Security", "PHDC01.phantom.lab"]
    assert sysval(root, "EventRecordID").text == "4242"
    assert sysval(root, "Security") is not None
    ex = sysval(root, "Execution")
    assert ex.get("ProcessID").isdigit() and ex.get("ThreadID").isdigit()
    assert re.fullmatch(r"2026-10-03T09:15:20\.\d{7}Z", sysval(root, "TimeCreated").get("SystemTime"))
    assert sysval(root, "TimeCreated").get("SystemTime") == "2026-10-03T09:15:20.1234560Z"


def test_rendering_info_is_real_text_never_placeholders():
    root = tree(render(event_id=4624, data={"TargetUserName": "nalharbi", "TargetDomainName": "PHANTOM", "LogonType": "10",
                                            "IpAddress": "10.20.16.20"}))
    info = root.find("e:RenderingInfo", NS)
    msg = info.find("e:Message", NS).text
    assert msg.startswith("An account was successfully logged on.")
    assert "Account Name:\t\tnalharbi" in msg and "Logon Type:\t\t10" in msg and "10.20.16.20" in msg
    assert "{" not in msg.replace("{00000000-0000-0000-0000-000000000000}", "")
    assert info.find("e:Level", NS).text == "Information"
    assert info.find("e:Task", NS).text == "Logon"
    assert info.find("e:Opcode", NS).text == "Info"
    assert info.find("e:Channel", NS).text == "Security"
    assert info.find("e:Provider", NS).text == "Microsoft Windows security auditing."
    assert [k.text for k in info.findall("e:Keywords/e:Keyword", NS)] == ["Audit Success"]
    assert "Impersonation Level:\t\tImpersonation" in msg, "%%1833 is shown as its text"


@pytest.mark.parametrize("event_id,task,task_name,first_line", [
    (4624, "12544", "Logon", "An account was successfully logged on."),
    (4625, "12546", "Logon", "An account failed to log on."),
    (4634, "12545", "Logoff", "An account was logged off."),
    (4672, "12548", "Special Logon", "Special privileges assigned to new logon."),
])
def test_catalogue_entries(event_id, task, task_name, first_line):
    root = tree(render(event_id=event_id))
    assert sysval(root, "Task").text == task
    info = root.find("e:RenderingInfo", NS)
    assert info.find("e:Task", NS).text == task_name
    assert info.find("e:Message", NS).text.splitlines()[0] == first_line


def test_failure_outcome_sets_the_failure_keyword_and_hex():
    root = tree(render(event_id=4625, outcome="failure", data={"TargetUserName": "bob"}))
    assert sysval(root, "Keywords").text == "0x8010000000000000"
    assert [k.text for k in root.findall("e:RenderingInfo/e:Keywords/e:Keyword", NS)] == ["Audit Failure"]
    msg = root.find("e:RenderingInfo/e:Message", NS).text
    assert "Failure Reason:\t\tUnknown user name or bad password." in msg
    assert "Status:\t\t\t0xC000006D" in msg


def test_outcome_aliases():
    for value in ("Audit Failure", "FAILURE", "failed"):
        assert sysval(tree(render(event_id=4624, outcome=value)), "Keywords").text == "0x8010000000000000"
    assert sysval(tree(render(event_id=4624, outcome="Audit Success")), "Keywords").text == "0x8020000000000000"


def test_named_data_follow_the_catalogue_order_with_defaults_and_extras():
    root = tree(render(event_id=4634, data={"LogonType": "2", "TargetUserName": "bob", "Extra": "z"}))
    names = [d.get("Name") for d in root.findall("e:EventData/e:Data", NS)]
    assert names == ["TargetUserSid", "TargetUserName", "TargetDomainName", "TargetLogonId", "LogonType", "Extra"]
    values = {d.get("Name"): d.text for d in root.findall("e:EventData/e:Data", NS)}
    assert values["TargetUserName"] == "bob" and values["TargetDomainName"] == "-" and values["Extra"] == "z"


def test_positional_data_are_unnamed():
    root = tree(render(event_id=1200, provider="AD FS Auditing", channel="Security", data=["a", "b", 3, None],
                       message="The Federation Service issued a valid token.", rendering={"task": "None"}))
    data = root.findall("e:EventData/e:Data", NS)
    assert [d.text for d in data] == ["a", "b", "3", "-"]
    assert all(d.get("Name") is None for d in data)
    assert sysval(root, "Provider").get("Name") == "AD FS Auditing"
    assert sysval(root, "Provider").get("Guid") is None, "no guid is invented for a provider we do not know"


def test_uncatalogued_event_without_text_is_refused_with_what_to_add():
    with pytest.raises(winevent.EventError) as err:
        render(event_id=9999)
    assert "9999" in str(err.value) and "provider" in str(err.value) and "message" in str(err.value)
    with pytest.raises(winevent.EventError):
        render(event_id=9999, provider="X", message="m")          # task still missing
    r = render(event_id=9999, provider="X", message="m", rendering={"task": "T"})
    assert tree(r).find("e:RenderingInfo/e:Task", NS).text == "T"


def test_rendering_overrides():
    root = tree(render(event_id=4624, rendering={"message": "custom", "level": "Warning", "task": "Odd",
                                                 "opcode": "Start", "keywords": ["Classic", "Audit Success"],
                                                 "provider": "Custom provider."}))
    info = root.find("e:RenderingInfo", NS)
    assert [info.find(f"e:{t}", NS).text for t in ("Message", "Level", "Task", "Opcode", "Provider")] == \
        ["custom", "Warning", "Odd", "Start", "Custom provider."]
    assert [k.text for k in info.findall("e:Keywords/e:Keyword", NS)] == ["Classic", "Audit Success"]


def test_special_and_illegal_characters_keep_the_xml_well_formed():
    nasty = 'a ]]> b <c> & "q" \x00\x08 end'
    root = tree(render(event_id=4624, data={"TargetUserName": nasty}))
    got = [d.text for d in root.findall("e:EventData/e:Data", NS) if d.get("Name") == "TargetUserName"][0]
    assert got == 'a ]]> b <c> & "q"  end'
    assert "]]>" not in render(event_id=4624, data={"TargetUserName": nasty}).xml


def test_naive_times_are_utc_and_timezones_are_converted():
    ksa = timezone(timedelta(hours=3))
    a = tree(render(event_id=4634, time=datetime(2026, 10, 3, 12, 0, 0, tzinfo=ksa)))
    b = tree(render(event_id=4634, time=datetime(2026, 10, 3, 9, 0, 0)))
    assert sysval(a, "TimeCreated").get("SystemTime") == sysval(b, "TimeCreated").get("SystemTime") == "2026-10-03T09:00:00.0000000Z"


def test_catalogue_is_a_table_a_new_id_is_data():
    d = winevent.EventDef(event_id=4688, provider=winevent.SECURITY_PROVIDER, provider_guid=winevent.SECURITY_GUID,
                          provider_display=winevent.SECURITY_DISPLAY, channel="Security", version=2, task=13312,
                          task_name="Process Creation", message="A new process has been created.\n\nName: {NewProcessName}",
                          fields=(("NewProcessName", "-"),))
    winevent.CATALOG[(d.provider, 4688)] = d
    try:
        root = tree(render(event_id=4688, data={"NewProcessName": "C:\\x.exe"}))
        assert root.find("e:RenderingInfo/e:Message", NS).text.endswith("Name: C:\\x.exe")
        assert sysval(root, "Task").text == "13312"
    finally:
        del winevent.CATALOG[(d.provider, 4688)]


# ── record ids ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_record_ids_are_monotonic_per_computer_and_independent_between_computers():
    events = [Event(event_id=4624, computer=c, time=T0 + timedelta(seconds=s)) for c, s in
              [("A", 5), ("B", 1), ("A", 1), ("A", 1), ("B", 9), ("A", 20)]]
    out = winevent.render_all(events)
    assert [r.time for r in out] == sorted(r.time for r in out), "rendered in time order"
    for comp in ("A", "B"):
        ids = [r.record_id for r in out if r.computer == comp]
        assert ids == sorted(set(ids)) and len(ids) == len(set(ids)), f"strictly increasing for {comp}"


def test_record_ids_keep_increasing_across_calls_because_they_follow_the_clock():
    first = winevent.render_all([Event(event_id=4624, computer="A", time=T0)])[0].record_id
    second = winevent.render_all([Event(event_id=4624, computer="A", time=T0 + timedelta(minutes=5))])[0].record_id
    assert second > first > 0


def test_explicit_record_id_is_kept():
    assert winevent.render_all([Event(event_id=4624, computer="A", time=T0, record_id=77)])[0].record_id == 77


# ── caller strings that reach the XML ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["a\x00b", "a\x08b", "a\x1fb", "a\ud800b", "a\udfffb", "a\ufffeb"])
def test_names_and_computer_with_illegal_characters_are_refused(bad):
    with pytest.raises(winevent.EventError, match="control or invalid"):
        render(event_id=4624, data={bad: "x"})
    with pytest.raises(winevent.EventError, match="control or invalid"):
        render(event_id=4624, computer=f"PH{bad}")
    with pytest.raises(winevent.EventError):
        winevent.render_all([Event(event_id=4624, computer=f"PH{bad}", time=T0)])


def test_blank_computer_is_refused():
    with pytest.raises(winevent.EventError, match="empty"):
        render(event_id=4624, computer="   ")


@pytest.mark.parametrize("bad", ["a\x00b", "a\ud800b", "a\x08\udfffb"])
def test_illegal_characters_in_values_are_removed_and_never_break_encoding(bad):
    r = render(event_id=4624, data={"TargetUserName": bad}, message=bad, rendering={"task": bad, "keywords": [bad]},
               provider=None, activity_id=bad)
    r.xml.encode("utf-16-le")            # a lone surrogate would raise here
    root = tree(r)
    assert [d.text for d in root.findall("e:EventData/e:Data", NS) if d.get("Name") == "TargetUserName"] == ["ab"]
    assert root.find("e:System/e:Correlation", NS).get("ActivityID") == "ab"


@pytest.mark.parametrize("value,expected", [(12345, "12345"), (1.5, "1.5"), (True, "true"), ("{GUID}", "{GUID}")])
def test_non_string_activity_id_is_coerced(value, expected):
    assert tree(render(event_id=4624, activity_id=value)).find("e:System/e:Correlation", NS).get("ActivityID") == expected


def test_empty_activity_id_adds_no_correlation():
    assert tree(render(event_id=4624, activity_id="")).find("e:System/e:Correlation", NS) is None
    assert tree(render(event_id=4624)).find("e:System/e:Correlation", NS) is None


def test_non_list_keywords_and_non_integer_ids_are_clean_errors():
    assert [k.text for k in tree(render(event_id=4624, rendering={"keywords": 7})).findall("e:RenderingInfo/e:Keywords/e:Keyword", NS)] == ["7"]
    with pytest.raises(winevent.EventError, match="whole number"):
        render(event_id="abc")
