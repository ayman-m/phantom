"""wsman: the requests this client builds (Enumerate and Events envelopes), batching and routing. Offline."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from conftest import FIXTURE
from src import wsman

S, A, W, E_, N = wsman.SOAP, wsman.WSA, wsman.WSMAN, wsman.WSE, wsman.WSEN
SUBS = wsman.parse_enumerate_response(FIXTURE.read_bytes())
FWD, AUTH = SUBS
TARGET = wsman.parse_subscription_manager_url("Server=HTTPS://broker.example.lab:5986/wsman/SubscriptionManager/WEC,Refresh=600")


def parse(body: bytes) -> ET.Element:
    assert body[:2] == b"\xff\xfe", "UTF-16LE with a byte-order mark"
    return ET.fromstring(wsman.decode_message(body))


def header(root, ns, local):
    return root.find(f"{{{S}}}Header/{{{ns}}}{local}")


def test_enumerate_request_carries_the_required_headers():
    root = parse(wsman.build_enumerate_request(TARGET, "sender.phantom.lab", 30))
    assert header(root, A, "To").text == "HTTPS://broker.example.lab:5986/wsman/SubscriptionManager/WEC"
    assert header(root, W, "ResourceURI").text == "http://schemas.microsoft.com/wbem/wsman/1/SubscriptionManager/Subscription"
    assert header(root, A, "Action").text == "http://schemas.xmlsoap.org/ws/2004/09/enumeration/Enumerate"
    assert header(root, A, "ReplyTo").find(f"{{{A}}}Address").text == "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"
    assert header(root, A, "MessageID").text.startswith("uuid:")
    assert header(root, W, "MaxEnvelopeSize").text.isdigit()
    assert header(root, W, "OperationTimeout").text == "PT30.000S"
    assert header(root, W, "Locale").get(f"{{{wsman.XML_NS}}}lang") == "en-US"
    assert header(root, wsman.MSWSMAN, "DataLocale") is not None
    assert header(root, wsman.MACHINEID, "MachineID").text == "sender.phantom.lab"
    enum = root.find(f"{{{S}}}Body/{{{N}}}Enumerate")
    assert enum.find(f"{{{W}}}OptimizeEnumeration") is not None
    assert enum.find(f"{{{W}}}MaxElements").text.isdigit()


def test_message_ids_are_unique():
    ids = {header(parse(wsman.build_enumerate_request(TARGET, "s")), A, "MessageID").text for _ in range(5)}
    assert len(ids) == 5


def test_events_envelope_structure():
    xmls = ["<Event><System/></Event>", "<Event><System>é</System></Event>"]
    root = parse(wsman.build_events_envelope(AUTH, "PHDC01.phantom.lab", xmls))
    assert header(root, A, "To").text == AUTH.delivery_url
    assert header(root, A, "Action").text == "http://schemas.dmtf.org/wbem/wsman/1/wsman/Events"
    assert header(root, E_, "Identifier").text == AUTH.identifier
    assert header(root, wsman.MACHINEID, "MachineID").text == "PHDC01.phantom.lab"
    assert header(root, W, "MaxEnvelopeSize").text == "524288"
    events = root.findall(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event")
    assert [e.get("Action") for e in events] == ["http://schemas.dmtf.org/wbem/wsman/1/wsman/Event"] * 2
    assert [e.text for e in events] == xmls


def test_events_are_wrapped_in_cdata_on_the_wire():
    text = wsman.decode_message(wsman.build_events_envelope(AUTH, "h", ["<Event>a &amp; b</Event>"]))
    assert "<![CDATA[<Event>a &amp; b</Event>]]>" in text


def test_cdata_end_marker_inside_an_event_is_split_safely():
    nasty = "<Event>x ]]> y ]]]]> z</Event>"
    body = wsman.build_events_envelope(AUTH, "h", [nasty, "<Event>second</Event>"])
    root = parse(body)  # still well-formed
    got = [e.text for e in root.findall(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event")]
    assert got == [nasty, "<Event>second</Event>"]


def test_events_that_look_like_placeholders_are_not_rescanned():
    body = wsman.build_events_envelope(AUTH, "h", ["@@abc:1@@", "second"])
    root = parse(body)
    assert [e.text for e in root.findall(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event")] == ["@@abc:1@@", "second"]


# ── batching ────────────────────────────────────────────────────────────────────────────────────────────────────
def big_events(n, chars=3000):
    return [f"<Event>{i:05d}{'x' * chars}</Event>" for i in range(n)]


def test_batches_keep_every_encoded_envelope_under_the_limit():
    xmls = big_events(300)          # about 900 kB of characters, 1.8 MB encoded
    batches = wsman.plan_batches(AUTH, "h", xmls)
    assert len(batches) > 3
    assert [i for b in batches for i in b] == list(range(300)), "every event exactly once, in order"
    for batch in batches:
        encoded = wsman.build_events_envelope(AUTH, "h", [xmls[i] for i in batch])
        assert len(encoded) < AUTH.max_envelope_size * wsman.ENVELOPE_FILL + 4


def test_batch_size_counts_utf16_bytes_not_characters():
    # 150k characters is under 524288 as characters but 300 kB encoded: one batch; 250k characters must split
    assert len(wsman.plan_batches(AUTH, "h", ["<E>" + "y" * 150_000 + "</E>"])) == 1
    assert len(wsman.plan_batches(AUTH, "h", ["<E>" + "y" * 125_000 + "</E>"] * 3)) >= 2


def test_cdata_splitting_is_counted_in_the_budget():
    xmls = ["<E>" + "]]>" * 8_000 + "</E>"] * 2   # 24k characters, 120k once split
    batches = wsman.plan_batches(AUTH, "h", xmls)
    assert len(batches) == 2
    for batch in batches:
        assert len(wsman.build_events_envelope(AUTH, "h", [xmls[i] for i in batch])) < AUTH.max_envelope_size


def test_one_event_larger_than_an_envelope_is_an_error():
    with pytest.raises(wsman.WecError, match="does not fit"):
        wsman.plan_batches(AUTH, "h", ["<E>" + "z" * 300_000 + "</E>"])


def test_a_small_envelope_limit_is_honoured():
    from dataclasses import replace
    small = replace(AUTH, max_envelope_size=20_000)
    xmls = big_events(10, 1500)
    batches = wsman.plan_batches(small, "h", xmls)
    assert len(batches) > 2
    for b in batches:
        assert len(wsman.build_events_envelope(small, "h", [xmls[i] for i in b])) < 20_000


# ── routing ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_security_goes_to_authentication_everything_else_to_forwarded():
    assert wsman.select_subscription(SUBS, "Security").name == "Authentication Event Logs"
    assert wsman.select_subscription(SUBS, "security").name == "Authentication Event Logs"
    assert wsman.select_subscription(SUBS, "System").name == "ForwardedEvents"
    assert wsman.select_subscription(SUBS, "AD FS/Admin").name == "ForwardedEvents"


def test_missing_preferred_subscription_falls_back_to_the_first():
    assert wsman.select_subscription([FWD], "Security").name == "ForwardedEvents"
    assert wsman.select_subscription([AUTH], "Application").name == "Authentication Event Logs"


def test_both_envelopes_carry_the_ms_wsmv_tracking_headers():
    """The live applet answers an Enumerate without SessionId/OperationID/SequenceId with an empty HTTP 200
    (measured against a live applet), so every request carries them: SessionId is the client's, OperationID is per request."""
    session = "uuid:11111111-2222-3333-4444-555555555555"
    enum = parse(wsman.build_enumerate_request(TARGET, "sender.phantom.lab", 30, session_id=session))
    first = parse(wsman.build_events_envelope(AUTH, "dc01.phantom.lab", ["<Event/>"], 30, session))
    second = parse(wsman.build_events_envelope(AUTH, "dc01.phantom.lab", ["<Event/>"], 30, session))
    for root in (enum, first, second):
        assert header(root, wsman.MSWSMAN, "SessionId").text == session
        assert header(root, wsman.MSWSMAN, "SequenceId").text == "1"
        assert header(root, wsman.MSWSMAN, "OperationID").text.startswith("uuid:")
    assert header(first, wsman.MSWSMAN, "OperationID").text != header(second, wsman.MSWSMAN, "OperationID").text


def test_an_empty_ok_reply_to_enumerate_is_a_clear_protocol_error(monkeypatch):
    """HTTP 200 with no body is how the applet says it did not recognise the request."""
    client = wsman.WecClient.__new__(wsman.WecClient)
    client.target, client.sender, client.timeout = TARGET, "sender.phantom.lab", 30.0
    client.session_id = "uuid:11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(client, "_post", lambda path, body: (200, b"", None))
    with pytest.raises(wsman.WecProtocolError, match="empty body"):
        client.enumerate()


# ── real UTF-16 bytes: characters above U+FFFF take 4 ───────────────────────────────────────────────────────────
def test_astral_characters_are_counted_as_four_bytes():
    xmls = [f"<Event>{i}{chr(0x1F600) * 30_000}</Event>" for i in range(8)]   # 30k characters, 120 kB each encoded
    batches = wsman.plan_batches(AUTH, "h", xmls)
    assert len(batches) >= 3 and [i for b in batches for i in b] == list(range(8))
    for b in batches:
        size = len(wsman.build_events_envelope(AUTH, "h", [xmls[i] for i in b]))
        assert size <= AUTH.max_envelope_size * wsman.ENVELOPE_FILL, size


def test_one_astral_event_that_fits_in_characters_but_not_in_bytes_is_refused():
    # 130k astral characters = 260k UTF-16 code units = 520 kB: over the limit although "only" 130k characters
    with pytest.raises(wsman.WecError, match="does not fit"):
        wsman.plan_batches(AUTH, "h", [f"<E>{chr(0x1F600) * 130_000}</E>"])


def test_unsendable_text_is_refused_at_planning_time():
    with pytest.raises(wsman.WecError, match="control or invalid"):
        wsman.plan_batches(AUTH, "h", ["<E>\x00</E>"])
    with pytest.raises(wsman.WecError, match="control or invalid"):
        wsman.plan_batches(AUTH, "h", ["<E>\ud800</E>"])
    with pytest.raises(wsman.WecError, match="computer name"):
        wsman.plan_batches(AUTH, "bad\x01host", ["<E/>"])


def test_machine_id_is_cleaned_of_illegal_characters():
    root = parse(wsman.build_events_envelope(AUTH, "ho\x01st\ud800", ["<E/>"]))
    assert header(root, wsman.MACHINEID, "MachineID").text == "host"
    root = parse(wsman.build_enumerate_request(TARGET, "se\x02nder"))
    assert header(root, wsman.MACHINEID, "MachineID").text == "sender"
