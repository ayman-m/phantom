"""wsman.WecClient against the in-process fake applet (mutual TLS on loopback), plus the TLS security properties."""
from __future__ import annotations

import os
import socket
import ssl
import xml.etree.ElementTree as ET

import pytest

from conftest import MANAGER_PATH, PFX_PASSWORD, FakeApplet, Pki
from src import wsman

S, A, W, E_ = wsman.SOAP, wsman.WSA, wsman.WSMAN, wsman.WSE


def client_for(applet, pki, url=None, **kw) -> wsman.WecClient:
    url = url or f"Server=HTTPS://127.0.0.1:{applet.port}{MANAGER_PATH},Refresh=600,IssuerCA={pki.ca_thumbprint}"
    return wsman.WecClient(url, pki.pfx_b64, PFX_PASSWORD, sender_computer_name="sender.phantom.lab", timeout=5, **kw)


def ev(computer, channel="Security", n=0, pad=0):
    return wsman.WecEvent(computer, channel, f"<Event><System><Computer>{computer}</Computer></System><N>{n}</N>{'x' * pad}</Event>")


def envelope(delivery):
    return ET.fromstring(wsman.decode_message(delivery["body"]))


def hdr(root, ns, local):
    return root.find(f"{{{S}}}Header/{{{ns}}}{local}")


# ── enumerate ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_enumerate_sends_the_expected_request_and_presents_the_client_certificate(applet, pki):
    subs = client_for(applet, pki).enumerate()
    assert [s.name for s in subs] == ["ForwardedEvents", "Authentication Event Logs"]
    assert subs[0].delivery_url.startswith(f"HTTPS://127.0.0.1:{applet.port}/wsman/subscriptions/")
    req = applet.enumerates[0]
    assert req["headers"]["Content-Type"] == "application/soap+xml;charset=UTF-16"
    assert req["body"][:2] == b"\xff\xfe"
    assert req["peer_cert"]["subject"][0][0] == ("commonName", "phantom-client")
    root = envelope(req)
    assert hdr(root, A, "Action").text.endswith("/enumeration/Enumerate")
    assert hdr(root, wsman.MACHINEID, "MachineID").text == "sender.phantom.lab"
    assert hdr(root, A, "To").text == f"HTTPS://127.0.0.1:{applet.port}{MANAGER_PATH}"


def test_identifiers_are_new_on_every_enumerate(applet, pki):
    c = client_for(applet, pki)
    assert c.enumerate()[0].identifier != c.enumerate()[0].identifier


def test_utf16_enumerate_reply_is_understood(applet, pki):
    applet.enumerate_encoding = "utf-16"
    assert len(client_for(applet, pki).enumerate()) == 2


def test_enumerate_http_error_is_a_protocol_error(applet, pki):
    applet.enumerate_status = 503
    with pytest.raises(wsman.WecProtocolError, match="503"):
        client_for(applet, pki).enumerate()


# ── delivery ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_send_routes_by_channel_one_envelope_per_computer(applet, pki):
    events = [ev("PHDC01.phantom.lab", n=1), ev("PHWS-001.phantom.lab", n=2), ev("PHDC01.phantom.lab", n=3),
              ev("PHWS-001.phantom.lab", "System", n=4), ev("PHDC01.phantom.lab", "Application", n=5)]
    report = client_for(applet, pki).send(events)
    assert report.sent == 5 and report.envelopes == 4 and report.reenumerations == 0
    assert report.by_computer == {"PHDC01.phantom.lab": 3, "PHWS-001.phantom.lab": 2}
    assert report.by_subscription == {"Authentication Event Logs": 3, "ForwardedEvents": 2}
    assert applet.enumerations == 1, "one Enumerate at the start of the send"
    sub_paths = {"auth": "/wsman/subscriptions/aaaaaaaa-bbbb-4ccc-8ddd-000000000001/1",
                 "fwd": "/wsman/subscriptions/11111111-2222-3333-4444-555555555555/1"}
    seen = []
    for d in applet.deliveries:
        assert d["status"] == 200
        assert d["headers"]["Content-Type"] == "application/soap+xml;charset=UTF-16"
        assert d["body"][:2] == b"\xff\xfe"
        root = envelope(d)
        assert hdr(root, A, "Action").text == "http://schemas.dmtf.org/wbem/wsman/1/wsman/Events"
        assert hdr(root, E_, "Identifier").text in applet.valid_identifiers
        assert hdr(root, A, "To").text == f"HTTPS://127.0.0.1:{applet.port}{d['path']}"
        machine = hdr(root, wsman.MACHINEID, "MachineID").text
        events_in = root.findall(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event")
        for e in events_in:   # nothing from another computer in this envelope
            assert f"<Computer>{machine}</Computer>" in e.text
        seen.append((machine, d["path"], len(events_in)))
    assert sorted(seen) == sorted([("PHDC01.phantom.lab", sub_paths["auth"], 2), ("PHWS-001.phantom.lab", sub_paths["auth"], 1),
                                   ("PHWS-001.phantom.lab", sub_paths["fwd"], 1), ("PHDC01.phantom.lab", sub_paths["fwd"], 1)])


def test_delivery_uses_the_identifier_of_the_same_enumerate(applet, pki):
    c = client_for(applet, pki)
    c.send([ev("H1.phantom.lab")])
    first_ids = set(applet.valid_identifiers)
    c.send([ev("H1.phantom.lab")])
    ids_used = [hdr(envelope(d), E_, "Identifier").text for d in applet.deliveries]
    assert ids_used[0] in first_ids and ids_used[1] not in first_ids
    assert ids_used[0] != ids_used[1], "identifiers are never reused across Enumerates"


def test_large_sends_are_split_under_the_envelope_limit(applet, pki):
    events = [ev("PHSRV-FS01.phantom.lab", n=i, pad=3000) for i in range(200)]
    report = client_for(applet, pki).send(events)
    assert report.sent == 200 and report.envelopes >= 3
    for d in applet.deliveries:
        assert len(d["body"]) < 524288 * wsman.ENVELOPE_FILL + 4
    delivered = sum(len(envelope(d).findall(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event")) for d in applet.deliveries)
    assert delivered == 200


def test_delivered_event_xml_is_unchanged(applet, pki):
    original = ev("H1.phantom.lab", n=7)
    client_for(applet, pki).send([original])
    got = envelope(applet.deliveries[0]).find(f"{{{S}}}Body/{{{W}}}Events/{{{W}}}Event").text
    assert got == original.xml


def test_non_200_triggers_one_reenumerate_and_one_retry(applet, pki):
    applet.statuses = [500]
    report = client_for(applet, pki).send([ev("H1.phantom.lab")])
    assert report.sent == 1 and report.reenumerations == 1
    assert applet.enumerations == 2
    assert [d["status"] for d in applet.deliveries] == [500, 200]
    ids = [hdr(envelope(d), E_, "Identifier").text for d in applet.deliveries]
    assert ids[0] != ids[1], "the retry carries the NEW identifier"


def test_second_failure_raises_and_reports_only_what_was_delivered(applet, pki):
    applet.statuses = [200, 500, 500]       # first computer fine, second fails twice
    c = client_for(applet, pki)
    with pytest.raises(wsman.WecDeliveryError) as err:
        c.send([ev("A1.phantom.lab"), ev("B1.phantom.lab"), ev("B1.phantom.lab", n=2)])
    assert err.value.status == 500
    assert err.value.report.sent == 1 and err.value.report.by_computer == {"A1.phantom.lab": 1}
    assert [d["status"] for d in applet.deliveries] == [200, 500, 500], "retried once, delivered envelopes not resent"


def test_subscription_list_is_refreshed_after_the_refresh_interval(applet, pki):
    ticks = iter(range(0, 10_000, 400))   # each clock read advances 400 s; Refresh is 600 s
    c = client_for(applet, pki, clock=lambda: next(ticks))
    report = c.send([ev("A1.phantom.lab"), ev("B1.phantom.lab"), ev("C1.phantom.lab")])
    assert report.sent == 3 and report.reenumerations >= 1
    assert applet.enumerations == 1 + report.reenumerations


# ── TLS security ────────────────────────────────────────────────────────────────────────────────────────────────
def test_certificate_cn_mismatch_raises_before_any_request_is_sent(pki):
    from conftest import make_leaf
    key, cert = make_leaf(pki.ca_key, pki.ca_cert, "other-host.example", server=True)
    srv = FakeApplet(pki, server_cert=cert, server_key=key)
    try:
        with pytest.raises(wsman.WecTlsError, match="does not match"):
            client_for(srv, pki).enumerate()
        with pytest.raises(wsman.WecTlsError, match="does not match"):
            client_for(srv, pki).send([ev("H1.phantom.lab")])
        assert srv.enumerates == [] and srv.deliveries == [], "no request bytes reached the server"
    finally:
        srv.close()


def test_a_pfx_from_a_different_ca_is_refused(applet, pki, other_pki):
    c = wsman.WecClient(f"Server=HTTPS://127.0.0.1:{applet.port}{MANAGER_PATH},Refresh=600",
                        other_pki.pfx_b64, PFX_PASSWORD, timeout=5)
    with pytest.raises(wsman.WecTlsError):
        c.enumerate()
    assert applet.enumerates == []


def test_wrong_issuer_ca_in_the_console_value_is_refused_up_front(applet, pki, other_pki):
    url = f"Server=HTTPS://127.0.0.1:{applet.port}{MANAGER_PATH},IssuerCA={other_pki.ca_thumbprint}"
    with pytest.raises(wsman.WecConfigError, match="IssuerCA"):
        wsman.WecClient(url, pki.pfx_b64, PFX_PASSWORD)


def test_a_server_that_wants_a_different_client_ca_fails_cleanly(pki, other_pki):
    srv = FakeApplet(other_pki)       # trusts only other_pki's client certificates
    try:
        c = wsman.WecClient(f"Server=HTTPS://127.0.0.1:{srv.port}{MANAGER_PATH}", pki.pfx_b64, PFX_PASSWORD, timeout=5)
        with pytest.raises(wsman.WecError):
            c.enumerate()
    finally:
        srv.close()


def test_connection_refused_is_a_transport_error(pki):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(wsman.WecTransportError):
        wsman.WecClient(f"https://127.0.0.1:{port}{MANAGER_PATH}", pki.pfx_b64, PFX_PASSWORD, timeout=2).enumerate()


def test_ssl_context_trusts_only_the_pfx_ca_and_verifies(pki):
    ctx = wsman.build_ssl_context(wsman.load_client_identity(pki.pfx_b64, PFX_PASSWORD))
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is False, "the hostname is checked by hand (no SAN on the applet's certificate)"
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    roots = ctx.get_ca_certs()
    assert [dict(x[0] for x in r["subject"])["commonName"] for r in roots] == ["Phantom Test CA"]


def test_private_key_only_touches_disk_encrypted_and_is_deleted(pki, monkeypatch):
    seen = {}
    original = ssl.SSLContext.load_cert_chain

    def spy(self, certfile, keyfile=None, password=None):
        data = __import__("pathlib").Path(keyfile).read_bytes()
        seen.update(dir=os.path.dirname(keyfile), mode=os.stat(keyfile).st_mode & 0o777, key=data, password=password)
        return original(self, certfile, keyfile, password)

    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain", spy)
    wsman.build_ssl_context(wsman.load_client_identity(pki.pfx_b64, PFX_PASSWORD))
    assert b"BEGIN ENCRYPTED PRIVATE KEY" in seen["key"] and b"BEGIN PRIVATE KEY" not in seen["key"]
    assert seen["mode"] == 0o600 and seen["password"]
    assert seen["password"] != PFX_PASSWORD.encode(), "a one-time passphrase, not the PFX password"
    assert not os.path.exists(seen["dir"]), "the directory is gone as soon as the key is loaded"
    if os.path.isdir("/dev/shm"):
        assert seen["dir"].startswith("/dev/shm")


@pytest.mark.parametrize("host,names_ok", [("broker.example.lab", True), ("BROKER.example.lab.", True), ("other.lab", False)])
def test_verify_peer_name_cn_without_san(pki, host, names_ok):
    from conftest import make_leaf
    from cryptography.hazmat.primitives import serialization
    _, cert = make_leaf(pki.ca_key, pki.ca_cert, "broker.example.lab", server=True)
    der = cert.public_bytes(serialization.Encoding.DER)
    if names_ok:
        wsman.verify_peer_name(der, host)
    else:
        with pytest.raises(wsman.WecTlsError):
            wsman.verify_peer_name(der, host)
    with pytest.raises(wsman.WecTlsError):
        wsman.verify_peer_name(None, host)


def test_verify_peer_name_prefers_san_when_present(pki):
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cn-only.lab")]))
            .issuer_name(pki.ca_cert.subject).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("*.san.lab")]), critical=False)
            .sign(pki.ca_key, hashes.SHA256()))
    der = cert.public_bytes(serialization.Encoding.DER)
    wsman.verify_peer_name(der, "broker.san.lab")
    with pytest.raises(wsman.WecTlsError):
        wsman.verify_peer_name(der, "cn-only.lab")      # the SAN decides once it exists


# ── planning happens before any delivery ────────────────────────────────────────────────────────────────────────
def test_an_oversized_event_for_a_later_computer_fails_before_anything_is_sent(applet, pki):
    events = [ev("A1.phantom.lab"), ev("A1.phantom.lab", n=2), ev("B1.phantom.lab", pad=600_000)]
    with pytest.raises(wsman.WecError, match="does not fit") as err:
        client_for(applet, pki).send(events)
    assert applet.deliveries == []
    assert err.value.report.sent == 0 and err.value.report.envelopes == 0


def test_unsendable_event_for_a_later_computer_also_fails_before_anything_is_sent(applet, pki):
    with pytest.raises(wsman.WecError, match="control or invalid"):
        client_for(applet, pki).send([ev("A1.phantom.lab"), wsman.WecEvent("B1.phantom.lab", "Security", "<E>\x07</E>")])
    assert applet.deliveries == []


def test_a_subscription_that_disappears_in_a_refresh_is_a_protocol_error_with_the_partial_report(applet, pki):
    ticks = iter(range(0, 10_000, 400))
    c = client_for(applet, pki, clock=lambda: next(ticks))
    real = c.enumerate
    calls = []

    def enumerate_without_auth():
        subs = real()
        calls.append(1)
        return subs if len(calls) == 1 else [s for s in subs if s.name != "Authentication Event Logs"]

    c.enumerate = enumerate_without_auth
    with pytest.raises(wsman.WecProtocolError, match="no longer offered") as err:
        c.send([ev("A1.phantom.lab"), ev("B1.phantom.lab"), ev("C1.phantom.lab")])
    assert err.value.report.sent == 1 and err.value.report.reenumerations == 1
    assert len(applet.deliveries) == 1


def test_a_server_certificate_from_a_bundled_but_non_issuing_ca_is_refused(pki, other_pki):
    import base64
    from conftest import make_leaf, make_pfx
    key, cert = make_leaf(other_pki.ca_key, other_pki.ca_cert, "127.0.0.1", server=True)
    srv = FakeApplet(pki, server_cert=cert, server_key=key)     # trusts our client certificate, shows a foreign server certificate
    try:
        pfx = base64.b64encode(make_pfx(pki.client_key, pki.client_cert, [pki.ca_cert, other_pki.ca_cert])).decode()
        c = wsman.WecClient(f"Server=HTTPS://127.0.0.1:{srv.port}{MANAGER_PATH}", pfx, PFX_PASSWORD, timeout=5)
        with pytest.raises(wsman.WecTlsError):
            c.enumerate()
        assert srv.enumerates == []
    finally:
        srv.close()
