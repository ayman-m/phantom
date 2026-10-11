"""wsman: parsing the applet's EnumerateResponse, the console value, and the PFX. Offline, no sockets."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import FIXTURE, PFX_PASSWORD
from src import wsman

XML = FIXTURE.read_text(encoding="utf-8")
BASE = "HTTPS://broker.example.lab:5986/wsman/subscriptions"


def test_fixture_subscriptions():
    subs = wsman.parse_enumerate_response(XML.encode())
    assert [s.name for s in subs] == ["ForwardedEvents", "Authentication Event Logs"]
    fwd, auth = subs
    assert fwd.delivery_url == f"{BASE}/11111111-2222-3333-4444-555555555555/1"
    assert auth.delivery_url == f"{BASE}/aaaaaaaa-bbbb-4ccc-8ddd-000000000001/1"
    assert fwd.delivery_path == "/wsman/subscriptions/11111111-2222-3333-4444-555555555555/1"
    assert fwd.identifier == "61b87860-52f0-41a3-9a74-8719d8832e20"
    assert fwd.version == "uuid:66666666-7777-8888-9999-000000000000"
    assert (fwd.max_envelope_size, auth.max_envelope_size) == (524288, 524288)
    assert fwd.heartbeat == "PT3600.000S" and fwd.heartbeat_seconds == 3600.0
    assert [q.path for q in fwd.queries] == ["ForwardedEvents"]
    assert "Level<= 5" in fwd.queries[0].xpath and "\t" not in fwd.queries[0].xpath
    assert auth.channels == ("Security",)
    assert "EventID=4776" in auth.queries[0].xpath and "EventID=4624" in auth.queries[0].xpath


def test_parser_reads_the_right_elements_not_look_alikes():
    """In the fixture EndTo/NotifyTo and both MaxEnvelopeSize copies agree, so mutate the decoys."""
    mutated = XML.replace("<e:EndTo><a:Address>HTTPS://broker.example.lab", "<e:EndTo><a:Address>HTTPS://decoy.example")
    mutated = re.sub(r"(<e:EndTo>.*?<e:Identifier>)[^<]+", r"\1DECOY-ID", mutated)
    mutated = mutated.replace('<w:MaxEnvelopeSize s:mustUnderstand="true">524288', '<w:MaxEnvelopeSize s:mustUnderstand="true">111')
    # only the Delivery (Policy="Notify") size of the second subscription changes
    second = mutated.index("Authentication Event Logs")
    mutated = mutated[:second] + mutated[second:].replace('Policy="Notify">524288', 'Policy="Notify">262144', 1)
    fwd, auth = wsman.parse_enumerate_response(mutated)
    assert fwd.delivery_url.startswith(BASE) and "decoy" not in fwd.delivery_url
    assert fwd.identifier != "DECOY-ID" and auth.identifier != "DECOY-ID"
    assert fwd.max_envelope_size == 524288
    assert auth.max_envelope_size == 262144


@pytest.mark.parametrize("make", [
    lambda t: t.encode("utf-8"),
    lambda t: b"\xef\xbb\xbf" + t.encode("utf-8"),
    lambda t: b"\xff\xfe" + t.encode("utf-16-le"),
    lambda t: b"\xfe\xff" + t.encode("utf-16-be"),
    lambda t: ('<?xml version="1.0" encoding="UTF-8"?>' + t).encode("utf-8"),
    lambda t: b"\xff\xfe" + ('<?xml version="1.0" encoding="UTF-16"?>' + t).encode("utf-16-le"),
    lambda t: t.encode("utf-16-le"),   # no BOM at all
], ids=["utf8", "utf8-bom", "utf16le-bom", "utf16be-bom", "utf8-decl", "utf16-decl", "utf16-nobom"])
def test_reply_encodings(make):
    assert [s.name for s in wsman.parse_enumerate_response(make(XML))] == ["ForwardedEvents", "Authentication Event Logs"]


def test_fault_and_garbage_are_protocol_errors():
    fault = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><s:Fault><s:Code/>'
             '<s:Reason><s:Text xml:lang="en">access denied</s:Text></s:Reason></s:Fault></s:Body></s:Envelope>')
    with pytest.raises(wsman.WecProtocolError, match="access denied"):
        wsman.parse_enumerate_response(fault)
    with pytest.raises(wsman.WecProtocolError):
        wsman.parse_enumerate_response("<not-xml")
    with pytest.raises(wsman.WecProtocolError):
        wsman.parse_enumerate_response("<a/>")


def test_empty_items_is_no_subscriptions():
    empty = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
             'xmlns:n="http://schemas.xmlsoap.org/ws/2004/09/enumeration" '
             'xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"><s:Body><n:EnumerateResponse>'
             '<w:Items/><w:EndOfSequence/></n:EnumerateResponse></s:Body></s:Envelope>')
    assert wsman.parse_enumerate_response(empty) == []
    with pytest.raises(wsman.WecProtocolError, match="no subscriptions"):
        wsman.select_subscription([], "Security")


# ── the console value ───────────────────────────────────────────────────────────────────────────────────────────
def test_console_value_is_parsed_and_kept_as_issued():
    raw = "Server=HTTPS://broker.example.lab:5986/wsman/SubscriptionManager/WEC,Refresh=900,IssuerCA=11:11 111111111111111111111111111111111111"
    t = wsman.parse_subscription_manager_url(raw)
    assert t.url == "HTTPS://broker.example.lab:5986/wsman/SubscriptionManager/WEC"
    assert (t.host, t.port, t.path, t.refresh) == ("broker.example.lab", 5986, "/wsman/SubscriptionManager/WEC", 900)
    assert t.issuer_ca == "1111111111111111111111111111111111111111"


def test_bare_url_and_defaults():
    t = wsman.parse_subscription_manager_url("https://Broker.Example.lab/wsman/SubscriptionManager/WEC")
    assert (t.host, t.port, t.refresh, t.issuer_ca) == ("broker.example.lab", 5986, 600, None)
    assert t.url == "https://Broker.Example.lab/wsman/SubscriptionManager/WEC"


@pytest.mark.parametrize("bad", ["", "   ", "http://broker:5986/x", "Server=HTTP://b:5986/x", "Refresh=600",
                                 "Server=HTTPS://b:5986/x,Refresh=soon", "Server=HTTPS://b:5986/x,IssuerCA=12",
                                 "garbage", "Server=HTTPS://:5986/x"])
def test_bad_console_values_are_config_errors(bad):
    with pytest.raises(wsman.WecConfigError):
        wsman.parse_subscription_manager_url(bad)


# ── the PFX ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_identity_tolerates_whitespace_in_base64(pki):
    ident = wsman.load_client_identity(pki.pfx_b64_wrapped(), PFX_PASSWORD, pki.ca_thumbprint.lower())
    assert ident.issuer_thumbprint == pki.ca_thumbprint
    assert ident.issuer_ca.subject == pki.ca_cert.subject


def test_wrong_password_and_bad_inputs_are_clear_and_leak_nothing(pki):
    secrets_ = [pki.pfx_b64, "not-the-password-9"]
    for args in ((pki.pfx_b64, "not-the-password-9"), ("@@@not base64@@@", PFX_PASSWORD), ("", PFX_PASSWORD),
                 (pki.pfx_b64[:200], PFX_PASSWORD)):
        with pytest.raises(wsman.WecConfigError) as err:
            wsman.load_client_identity(*args)
        assert not any(s in str(err.value) for s in secrets_ + [PFX_PASSWORD]), "error text must not echo secrets"
    with pytest.raises(wsman.WecConfigError, match="clientPfxPassword"):
        wsman.load_client_identity(pki.pfx_b64, "wrong")


def test_wrong_issuer_ca_thumbprint_is_refused(pki, other_pki):
    with pytest.raises(wsman.WecConfigError, match="IssuerCA"):
        wsman.load_client_identity(pki.pfx_b64, PFX_PASSWORD, other_pki.ca_thumbprint)


def test_identity_repr_shows_no_key_material(pki):
    ident = wsman.load_client_identity(pki.pfx_b64, PFX_PASSWORD)
    assert "redacted" in repr(ident)


# ── trust anchor: only the CA that issued the client certificate ────────────────────────────────────────────────
def _pfx_b64(pki, cas):
    import base64
    from conftest import make_pfx
    return base64.b64encode(make_pfx(pki.client_key, pki.client_cert, cas)).decode()


def test_only_the_issuing_ca_becomes_a_trust_anchor_other_bundled_certificates_are_ignored(pki, other_pki):
    ident = wsman.load_client_identity(_pfx_b64(pki, [other_pki.ca_cert, pki.ca_cert]), PFX_PASSWORD)
    assert ident.issuer_ca.subject == pki.ca_cert.subject
    ctx = wsman.build_ssl_context(ident)
    roots = ctx.get_ca_certs()
    assert [dict(x[0] for x in r["subject"])["commonName"] for r in roots] == ["Phantom Test CA"]


def test_a_single_bundled_certificate_that_did_not_issue_the_client_certificate_is_refused(pki, other_pki):
    with pytest.raises(wsman.WecConfigError, match="does not bundle the CA"):
        wsman.load_client_identity(_pfx_b64(pki, [other_pki.ca_cert]), PFX_PASSWORD)
    with pytest.raises(wsman.WecConfigError, match="does not bundle the CA"):
        wsman.load_client_identity(_pfx_b64(pki, []), PFX_PASSWORD)


def test_a_look_alike_ca_with_the_same_name_but_another_key_is_refused(pki):
    from conftest import make_ca
    _, forged = make_ca("Phantom Test CA")
    assert forged.subject == pki.client_cert.issuer
    with pytest.raises(wsman.WecConfigError, match="does not bundle the CA"):
        wsman.load_client_identity(_pfx_b64(pki, [forged]), PFX_PASSWORD)
