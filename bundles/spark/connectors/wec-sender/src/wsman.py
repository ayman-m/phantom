"""WS-Management transport for a Cortex XSIAM Broker VM's Windows Event Collector (WEC) applet.

Standalone module: standard library plus `cryptography` only, and NO import from the Phantom runtime or from the
rest of this package, so it can be loaded by file path (the live check does exactly that).

What it speaks (source-initiated event forwarding, the applet is the collector and we play the forwarder):

  1. ENUMERATE   POST <SubscriptionManager URL>   WS-Enumeration `Enumerate` (optimized, one round trip).
                 The reply lists the collector's subscriptions; each carries the delivery address, a fresh
                 `e:Identifier`, the largest envelope it accepts and its event query.
  2. DELIVER     POST <subscription delivery address>   an `Events` envelope holding Windows Event XML.
                 The reply is HTTP 200 with an empty body.

Built from public specifications, cited by document name: DMTF DSP0226 (WS-Management), W3C WS-Eventing
(2004/08), W3C WS-Enumeration (2004/09), W3C WS-Addressing (2004/08), SOAP 1.2, Microsoft MS-WSMV (WS-Management
Protocol Extensions: MachineID, DataLocale, the SubscriptionManager resource) and the Windows Event XML schema.
The applet's own `EnumerateResponse` (kept as tests/fixtures/enumerate_response.xml) is the primary source for
what it sends and accepts.

Security properties (each one is tested):
  * Mutual TLS. The client certificate and key come from a PKCS#12 file that also bundles the CA; the CA that
    issued the client certificate is the ONLY trust anchor (the system store is never consulted).
  * The applet's certificate has a CN and no subjectAltName, which Python's default hostname check rejects, so the
    check is done by hand right after connecting and BEFORE any request byte is sent. Verification is never off.
  * The private key is never written to disk in the clear: it is exported as an encrypted PEM with a one-time
    passphrase to tmpfs, loaded, and deleted in a `finally`.
  * No error text, result or log line carries the PFX, its password or key material.
"""
import base64
import binascii
import codecs
import hashlib
import http.client
import ipaddress
import os
import re
import secrets
import shutil
import socket
import ssl
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

__all__ = [
    "WecError", "WecConfigError", "WecTlsError", "WecTransportError", "WecProtocolError", "WecDeliveryError",
    "SubscriptionManager", "ClientIdentity", "SubscriptionQuery", "Subscription", "WecEvent", "SendReport",
    "WecClient", "parse_subscription_manager_url", "load_client_identity", "build_ssl_context",
    "verify_peer_name", "parse_enumerate_response", "build_enumerate_request", "build_events_envelope",
    "plan_batches", "select_subscription", "encode_message", "decode_message",
    "DEFAULT_SENDER_COMPUTER", "AUTH_SUBSCRIPTION", "FORWARDED_SUBSCRIPTION",
]

DEFAULT_SENDER_COMPUTER = "phantom-wec-sender.phantom.lab"
AUTH_SUBSCRIPTION = "Authentication Event Logs"
FORWARDED_SUBSCRIPTION = "ForwardedEvents"
CONTENT_TYPE = "application/soap+xml;charset=UTF-16"
MAX_ENUM_ELEMENTS = 32000
# Fraction of the subscription's MaxEnvelopeSize an encoded envelope may use (headroom for the applet's own limit
# accounting). The encoded size is real UTF-16LE bytes (4 for characters above U+FFFF), plus the byte-order mark.
ENVELOPE_FILL = 0.8
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# ── namespaces (prefixes follow the applet's own reply so envelopes look like the ones it already accepts) ─────────
SOAP = "http://www.w3.org/2003/05/soap-envelope"
WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
WSE = "http://schemas.xmlsoap.org/ws/2004/08/eventing"
WSEN = "http://schemas.xmlsoap.org/ws/2004/09/enumeration"
WSMAN = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
MSWSMAN = "http://schemas.microsoft.com/wbem/wsman/1/wsman.xsd"
MACHINEID = "http://schemas.microsoft.com/wbem/wsman/1/machineid"
MSSUBSCRIPTION = "http://schemas.microsoft.com/wbem/wsman/1/subscription"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"s": SOAP, "a": WSA, "e": WSE, "n": WSEN, "w": WSMAN, "p": MSWSMAN, "machineid": MACHINEID,
      "m": MSSUBSCRIPTION, "xml": XML_NS}
for _prefix, _uri in NS.items():
    if _prefix != "xml":
        # Process-wide ElementTree prefix registry: harmless here, it only chooses prefixes on output.
        ET.register_namespace(_prefix, _uri)

ANONYMOUS = "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"
SUBSCRIPTION_RESOURCE = "http://schemas.microsoft.com/wbem/wsman/1/SubscriptionManager/Subscription"
ENUMERATE_ACTION = "http://schemas.xmlsoap.org/ws/2004/09/enumeration/Enumerate"
EVENTS_ACTION = "http://schemas.dmtf.org/wbem/wsman/1/wsman/Events"
EVENT_ACTION = "http://schemas.dmtf.org/wbem/wsman/1/wsman/Event"


# ── errors ──────────────────────────────────────────────────────────────────────────────────────────────────────
class WecError(Exception):
    """Base class. `report` carries the partial SendReport when an error interrupts `WecClient.send`."""

    report: "SendReport | None" = None


class WecConfigError(WecError):
    """Bad URL, bad base64, wrong PFX password, wrong IssuerCA: fix the instance configuration."""


class WecTlsError(WecError):
    """Certificate trust or name verification failed."""


class WecTransportError(WecError):
    """The connection could not be made or broke (refused, timeout, reset)."""


class WecProtocolError(WecError):
    """The applet answered with something this client does not understand, or a SOAP fault."""


class WecDeliveryError(WecError):
    """A delivery was answered with something other than HTTP 200."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# ── element builder ─────────────────────────────────────────────────────────────────────────────────────────────
def _qn(qname: str) -> str:
    prefix, sep, local = qname.partition(":")
    return f"{{{NS[prefix]}}}{local}" if sep else qname


def E(qname: str, *children: ET.Element, text: str | None = None, **attrs: str) -> ET.Element:
    """One element: `E("w:Event", text="x", Action="...")`. Attribute keys use `__` for `:` (`s__mustUnderstand`)."""
    node = ET.Element(_qn(qname), {_qn(k.replace("__", ":")): v for k, v in attrs.items()})
    if text is not None:
        node.text = text
    node.extend(children)
    return node


def _mu(value: bool = True) -> dict[str, str]:
    return {"s__mustUnderstand": "true" if value else "false"}


def _new_message_id() -> str:
    return "uuid:" + str(uuid.uuid4()).upper()


def _duration(seconds: float) -> str:
    return f"PT{seconds:.3f}S"


def _header(to: str, action: str, max_size: int, timeout: float, machine_id: str, *,
            resource_uri: str | None = None, extra: Sequence[ET.Element] = (),
            session_id: str | None = None) -> ET.Element:
    """The SOAP header both requests share: DSP0226 addressing headers plus Microsoft's MachineID and the three
    MS-WSMV tracking headers (SessionId, OperationID, SequenceId). The applet needs the tracking headers: measured
    against a live applet, an Enumerate without them is answered with an empty HTTP 200."""
    children = [E("a:To", text=to, **_mu())]
    if resource_uri:
        children.append(E("w:ResourceURI", text=resource_uri, **_mu()))
    children += [
        E("a:ReplyTo", E("a:Address", text=ANONYMOUS, **_mu())),
        E("a:Action", text=action, **_mu()),
        E("w:MaxEnvelopeSize", text=str(max_size), **_mu()),
        E("a:MessageID", text=_new_message_id()),
        *extra,
        E("p:SessionId", text=session_id or _new_message_id(), **_mu(False)),
        E("p:OperationID", text=_new_message_id(), **_mu(False)),
        E("p:SequenceId", text="1", **_mu(False)),
        E("w:Locale", xml__lang="en-US", **_mu(False)),
        E("p:DataLocale", xml__lang="en-US", **_mu(False)),
        E("w:OperationTimeout", text=_duration(timeout)),
        E("machineid:MachineID", text=_clean(machine_id), **_mu(False)),
    ]
    return E("s:Header", *children)


_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _clean(text: str) -> str:
    """Text with the characters XML 1.0 cannot carry (controls, lone surrogates) removed."""
    return _XML_ILLEGAL.sub("", text)


def _u16_len(text: str) -> int:
    """Bytes `text` takes in UTF-16LE: 2 per character, 4 for characters above U+FFFF (surrogate pairs)."""
    try:
        return len(text.encode("utf-16-le"))
    except UnicodeEncodeError:
        raise WecError("an event or computer name contains a lone surrogate, which cannot be encoded") from None


def _serialize(root: ET.Element, **kwargs) -> str:
    return ET.tostring(root, encoding="unicode", **kwargs)


def encode_message(text: str) -> bytes:
    """UTF-16LE with a byte-order mark: the encoding the applet's `Content-Type` declares."""
    return codecs.BOM_UTF16_LE + text.encode("utf-16-le")


def decode_message(body: bytes, charset: str | None = None) -> str:
    """Text of a reply: UTF-16 or UTF-8 by byte-order mark, then by NUL pattern, then by the declared charset."""
    if body.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return body.decode("utf-16")
    if body.startswith(codecs.BOM_UTF8):
        return body.decode("utf-8-sig")
    if len(body) >= 2 and body[0] != 0 and body[1] == 0:
        return body.decode("utf-16-le")
    if len(body) >= 2 and body[0] == 0 and body[1] != 0:
        return body.decode("utf-16-be")
    try:
        return body.decode(charset or "utf-8")
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace")


# ── configuration values ────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SubscriptionManager:
    url: str            # exactly as issued: the To header carries it verbatim
    host: str
    port: int
    path: str
    refresh: int        # seconds after which the subscription list is stale
    issuer_ca: str | None  # upper-case SHA-1 thumbprint of the issuing CA, when the console value carried one


def _normalise_thumbprint(value: str) -> str:
    thumb = re.sub(r"[\s:]", "", value).upper()
    if not re.fullmatch(r"[0-9A-F]{40}", thumb):
        raise WecConfigError("IssuerCA must be a 40-hex-digit SHA-1 thumbprint")
    return thumb


def parse_subscription_manager_url(value: str) -> SubscriptionManager:
    """Parse the Cortex console value `Server=HTTPS://<fqdn>:5986/wsman/SubscriptionManager/WEC,Refresh=600,
    IssuerCA=<sha1>`, or a bare https URL."""
    raw = (value or "").strip()
    if not raw:
        raise WecConfigError("subscriptionManagerUrl is empty")
    url, refresh, issuer = raw, 600, None
    if not re.match(r"(?i)https?://", raw):
        parts = {}
        for token in raw.split(","):
            key, sep, val = token.strip().partition("=")
            if not sep:
                raise WecConfigError("subscriptionManagerUrl: expected Server=<https url>[,Refresh=<s>][,IssuerCA=<sha1>]")
            parts[key.strip().lower()] = val.strip()
        if "server" not in parts:
            raise WecConfigError("subscriptionManagerUrl has no Server=<https url> part")
        url = parts["server"]
        if parts.get("refresh"):
            try:
                refresh = int(parts["refresh"])
            except ValueError:
                raise WecConfigError("subscriptionManagerUrl: Refresh must be a whole number of seconds") from None
        if parts.get("issuerca"):
            issuer = _normalise_thumbprint(parts["issuerca"])
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise WecConfigError("subscriptionManagerUrl must be an https URL with a host name")
    try:
        port = parsed.port or 5986
    except ValueError:
        raise WecConfigError("subscriptionManagerUrl has an invalid port") from None
    return SubscriptionManager(url=url, host=parsed.hostname, port=port, path=parsed.path or "/",
                               refresh=max(refresh, 1), issuer_ca=issuer)


# ── client identity and TLS ─────────────────────────────────────────────────────────────────────────────────────
@dataclass(repr=False)
class ClientIdentity:
    """The PFX contents. Held in memory only; `repr` shows nothing."""

    cert: x509.Certificate
    key: object
    issuer_ca: x509.Certificate       # the CA that issued (and signed) the client certificate: the ONLY trust anchor

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "ClientIdentity(<redacted>)"

    @property
    def issuer_thumbprint(self) -> str:
        return hashlib.sha1(self.issuer_ca.public_bytes(serialization.Encoding.DER)).hexdigest().upper()


def _issued_by(cert: x509.Certificate, candidate: x509.Certificate) -> bool:
    """True when `candidate` is the certificate that signed `cert`: the names match AND the signature verifies."""
    if cert.issuer != candidate.subject:
        return False
    try:
        cert.verify_directly_issued_by(candidate)
    except (ValueError, TypeError, InvalidSignature):
        return False
    return True


def load_client_identity(pfx_b64: str | bytes, password: str | bytes | None,
                         issuer_ca_thumbprint: str | None = None) -> ClientIdentity:
    """Open the PFX (base64 text; whitespace and newlines tolerated). Raises WecConfigError with a message that
    names the problem but never echoes the PFX or the password."""
    text = pfx_b64.decode("ascii", "ignore") if isinstance(pfx_b64, (bytes, bytearray)) else (pfx_b64 or "")
    text = re.sub(r"\s+", "", text)
    if not text:
        raise WecConfigError("the client PFX (clientPfx) is empty")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise WecConfigError("the client PFX (clientPfx) is not valid base64") from None
    pw = password.encode() if isinstance(password, str) else password
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(data, pw or None)
    except (ValueError, TypeError):
        raise WecConfigError("the client PFX could not be opened: wrong clientPfxPassword or not a PKCS#12 file") from None
    if key is None or cert is None:
        raise WecConfigError("the client PFX must contain a certificate and its private key")
    issuer = next((c for c in (extra or []) if _issued_by(cert, c)), None)
    if issuer is None:
        raise WecConfigError("the client PFX does not bundle the CA that issued (and signed) its certificate")
    ident = ClientIdentity(cert=cert, key=key, issuer_ca=issuer)
    if issuer_ca_thumbprint and ident.issuer_thumbprint != _normalise_thumbprint(issuer_ca_thumbprint):
        raise WecConfigError(
            f"IssuerCA {_normalise_thumbprint(issuer_ca_thumbprint)} does not match the CA in the client PFX "
            f"({ident.issuer_thumbprint}): the PFX and the subscription manager value are from different CAs")
    return ident


def _tmpfs_dir() -> str | None:
    shm = "/dev/shm"
    return shm if os.path.isdir(shm) and os.access(shm, os.W_OK) else None


def build_ssl_context(identity: ClientIdentity) -> ssl.SSLContext:
    """TLS 1.2+, server verified against ONLY the CA that issued the client certificate, which is the single trust
    anchor (other certificates bundled in the PFX are ignored); client certificate presented.

    `check_hostname` is False because the applet's certificate has no subjectAltName; the name is checked by
    `verify_peer_name` right after the connection is made. `verify_mode` is CERT_REQUIRED: the chain is verified.
    The private key reaches OpenSSL through an encrypted PEM on tmpfs that lives for a few milliseconds."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # loads no default CAs
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(cadata=identity.issuer_ca.public_bytes(serialization.Encoding.PEM).decode("ascii"))
    # The pinned CA may be an intermediate: let a chain end at it instead of at a self-signed root.
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    passphrase = secrets.token_urlsafe(24).encode("ascii")
    workdir = tempfile.mkdtemp(prefix="wecid-", dir=_tmpfs_dir())  # mode 0700
    try:
        cert_path, key_path = os.path.join(workdir, "c.pem"), os.path.join(workdir, "k.pem")
        key_pem = identity.key.private_bytes(  # type: ignore[attr-defined]
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(passphrase))
        for path, payload in ((cert_path, identity.cert.public_bytes(serialization.Encoding.PEM)), (key_path, key_pem)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
        ctx.load_cert_chain(cert_path, key_path, password=passphrase)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return ctx


def _dns_match(pattern: str, host: str) -> bool:
    pattern, host = pattern.lower().rstrip("."), host.lower().rstrip(".")
    if pattern.startswith("*."):
        head, _, rest = host.partition(".")
        return bool(head) and rest == pattern[2:]
    return pattern == host


def verify_peer_name(der_cert: bytes | None, host: str) -> None:
    """Raise WecTlsError unless the (already chain-verified) server certificate names `host`.

    With a subjectAltName the SAN decides (DNS names and IP addresses); without one the subject CN does, which is
    the applet's case. A certificate that names nothing is refused."""
    if not der_cert:
        raise WecTlsError("the server presented no certificate")
    cert = x509.load_der_x509_certificate(der_cert)
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        san = None
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    if san is not None:
        dns, ips = san.get_values_for_type(x509.DNSName), [str(i) for i in san.get_values_for_type(x509.IPAddress)]
        names = dns + ips
        ok = (host_ip is not None and str(host_ip) in ips) or (host_ip is None and any(_dns_match(d, host) for d in dns))
    else:
        names = [a.value for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
        ok = any(_dns_match(n, host) for n in names)
    if not ok:
        raise WecTlsError(f"server certificate does not match the host {host!r} (it names: {', '.join(names) or 'nothing'})")


# ── subscriptions ───────────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SubscriptionQuery:
    path: str
    xpath: str


@dataclass(frozen=True)
class Subscription:
    """One collector subscription from an Enumerate. `identifier` is NEW on every Enumerate: never cache it."""

    name: str
    version: str
    delivery_url: str
    identifier: str
    max_envelope_size: int
    heartbeat: str
    queries: tuple[SubscriptionQuery, ...] = ()

    @property
    def delivery_path(self) -> str:
        return urlsplit(self.delivery_url).path

    @property
    def heartbeat_seconds(self) -> float | None:
        m = re.fullmatch(r"PT(\d+(?:\.\d+)?)S", self.heartbeat or "")
        return float(m.group(1)) if m else None

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(q.path for q in self.queries if q.path))


def _find(node: ET.Element | None, *qnames: str) -> ET.Element | None:
    for q in qnames:
        if node is None:
            return None
        node = node.find(_qn(q))
    return node


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def parse_enumerate_response(body: bytes | str, charset: str | None = None) -> list[Subscription]:
    """The subscriptions in a WS-Enumeration `EnumerateResponse` (UTF-8 or UTF-16, with or without a declaration)."""
    text = body if isinstance(body, str) else decode_message(body, charset)
    try:
        root = ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError as exc:
        raise WecProtocolError(f"the enumerate reply is not well-formed XML ({exc})") from None
    fault = root.find(f".//{_qn('s:Fault')}")
    if fault is not None:
        reason = "".join(t.text or "" for t in fault.iter(_qn("s:Text"))).strip() or "no reason given"
        raise WecProtocolError(f"the collector answered with a SOAP fault: {reason[:300]}")
    resp = root.find(f".//{_qn('n:EnumerateResponse')}")
    if resp is None:
        raise WecProtocolError("the reply is not an EnumerateResponse")
    items = resp.find(_qn("w:Items"))
    if items is None or not len(items):
        if resp.find(_qn("w:EndOfSequence")) is None and _text(resp.find(_qn("n:EnumerationContext"))):
            raise WecProtocolError("the enumeration was not completed in one reply (a Pull is needed; not supported)")
        return []
    subs: list[Subscription] = []
    for item in items.findall(_qn("m:Subscription")):
        env = item.find(_qn("s:Envelope"))
        subscribe = _find(env, "s:Body", "e:Subscribe")
        if subscribe is None:
            raise WecProtocolError("a subscription carries no Subscribe envelope")
        option_set = _find(env, "s:Header", "w:OptionSet")
        options = {o.get("Name", ""): _text(o) for o in (option_set if option_set is not None else [])}
        name = options.get("SubscriptionName", "")
        delivery = subscribe.find(_qn("e:Delivery"))
        # NotifyTo is where events go; EndTo carries the same value today but is the wrong element to trust.
        notify = _find(delivery, "e:NotifyTo")
        address = _text(_find(notify, "a:Address"))
        identifier = _text(_find(notify, "a:ReferenceProperties", "e:Identifier"))
        if not (name and address and identifier):
            raise WecProtocolError(f"subscription {name or '?'!r} lacks a name, delivery address or identifier")
        # The size the Notify delivery may use is on Delivery (Policy="Notify"); the header copy is the request's.
        size_node = next((n for n in (delivery.findall(_qn("w:MaxEnvelopeSize")) if delivery is not None else [])
                          if n.get("Policy", "Notify") == "Notify"), None)
        size_text = _text(size_node) or _text(_find(env, "s:Header", "w:MaxEnvelopeSize"))
        try:
            size = int(size_text)
        except ValueError:
            raise WecProtocolError(f"subscription {name!r} has no usable MaxEnvelopeSize") from None
        queries = []
        for sel in subscribe.iterfind(f".//{_qn('w:Filter')}//Select"):
            queries.append(SubscriptionQuery(path=sel.get("Path", ""), xpath=" ".join((sel.text or "").split())))
        subs.append(Subscription(name=name, version=_text(item.find(_qn("m:Version"))), delivery_url=address,
                                 identifier=identifier, max_envelope_size=size,
                                 heartbeat=_text(_find(delivery, "w:Heartbeats")), queries=tuple(queries)))
    return subs


def build_enumerate_request(target: SubscriptionManager, sender_computer: str, timeout: float = 30.0,
                            max_envelope_size: int = 512000, session_id: str | None = None) -> bytes:
    """The encoded `Enumerate` request for the subscription manager (DSP0226 + WS-Enumeration; MachineID per MS-WSMV)."""
    header = _header(target.url, ENUMERATE_ACTION, max_envelope_size, timeout, sender_computer,
                     resource_uri=SUBSCRIPTION_RESOURCE, session_id=session_id)
    body = E("s:Body", E("n:Enumerate", E("w:OptimizeEnumeration"), E("w:MaxElements", text=str(MAX_ENUM_ELEMENTS))))
    return encode_message(_serialize(E("s:Envelope", header, body)))


# ── delivery envelopes ──────────────────────────────────────────────────────────────────────────────────────────
def _cdata(payload: str) -> str:
    """`payload` as CDATA; a literal `]]>` is split across two sections so it can never end the section early."""
    return "<![CDATA[" + payload.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _compose_events(sub: Subscription, computer: str, event_xmls: Sequence[str], timeout: float,
                    session_id: str | None = None) -> str:
    """Events envelope as text. ElementTree has no CDATA, so each event's text is a unique token and the tokens are
    replaced by CDATA sections in one pass after serialization: the only string step in envelope building."""
    nonce = secrets.token_hex(8)
    events = [E("w:Event", text=f"@@{nonce}:{i}@@", Action=EVENT_ACTION) for i in range(len(event_xmls))]
    header = _header(sub.delivery_url, EVENTS_ACTION, sub.max_envelope_size, timeout, computer,
                     extra=[E("e:Identifier", text=sub.identifier)], session_id=session_id)
    xml = _serialize(E("s:Envelope", header, E("s:Body", E("w:Events", *events))))
    return re.sub(rf"@@{nonce}:(\d+)@@", lambda m: _cdata(event_xmls[int(m.group(1))]), xml)


def build_events_envelope(sub: Subscription, computer: str, event_xmls: Sequence[str], timeout: float = 30.0,
                          session_id: str | None = None) -> bytes:
    """The encoded delivery envelope: one `wsman:Event` per Windows Event XML string, all from `computer`."""
    return encode_message(_compose_events(sub, computer, event_xmls, timeout, session_id))


def plan_batches(sub: Subscription, computer: str, event_xmls: Sequence[str], timeout: float = 30.0) -> list[list[int]]:
    """Greedy split of `event_xmls` (by index) so every encoded envelope stays under the subscription's
    MaxEnvelopeSize with headroom. Sizes are REAL UTF-16LE bytes (2 per character, 4 for characters above U+FFFF),
    not character counts. Raises WecError for an event that cannot fit or cannot be sent (illegal XML characters)."""
    if _XML_ILLEGAL.search(computer):
        raise WecError("the computer name contains a control or invalid character")
    budget = int(sub.max_envelope_size * ENVELOPE_FILL) - 2          # minus the byte-order mark
    base = _u16_len(_compose_events(sub, computer, [], timeout))
    per_event = _u16_len(_compose_events(sub, computer, [""], timeout)) - base
    empty = _u16_len(_cdata(""))
    batches: list[list[int]] = [[]]
    used = base
    for index, xml in enumerate(event_xmls):
        if _XML_ILLEGAL.search(xml):
            raise WecError("an event contains a control or invalid character that XML cannot carry")
        cost = per_event + _u16_len(_cdata(xml)) - empty
        if base + cost > budget:
            raise WecError(f"one event ({len(xml)} characters) does not fit in an envelope of {sub.max_envelope_size} bytes")
        if used + cost > budget and batches[-1]:
            batches.append([])
            used = base
        batches[-1].append(index)
        used += cost
    return [b for b in batches if b]


def select_subscription(subs: Sequence[Subscription], channel: str) -> Subscription:
    """Security-channel events go to `Authentication Event Logs`, everything else to `ForwardedEvents`; when the
    preferred subscription is absent the first one is used."""
    if not subs:
        raise WecProtocolError("the collector has no subscriptions: create a collection in the Cortex console first")
    wanted = AUTH_SUBSCRIPTION if (channel or "").lower() == "security" else FORWARDED_SUBSCRIPTION
    return next((s for s in subs if s.name == wanted), subs[0])


# ── client ──────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class WecEvent:
    computer: str     # the Computer inside the event: becomes the envelope's MachineID
    channel: str      # decides the subscription
    xml: str          # one Windows Event XML document


@dataclass
class SendReport:
    sent: int = 0
    envelopes: int = 0
    reenumerations: int = 0
    by_computer: dict[str, int] = field(default_factory=dict)
    by_subscription: dict[str, int] = field(default_factory=dict)


class WecClient:
    """Enumerate and deliver. One instance per set of credentials; safe to reuse for many sends.

        client = WecClient("Server=HTTPS://broker.example:5986/wsman/SubscriptionManager/WEC,Refresh=600,IssuerCA=...",
                           pfx_b64, pfx_password, sender_computer_name="sender.lab", timeout=30)
        subs = client.enumerate()
        report = client.send([WecEvent(computer, "Security", xml), ...])
    """

    def __init__(self, subscription_manager_url: str, pfx_b64: str | bytes, pfx_password: str | bytes | None,
                 sender_computer_name: str = DEFAULT_SENDER_COMPUTER, timeout: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.target = parse_subscription_manager_url(subscription_manager_url)
        self.identity = load_client_identity(pfx_b64, pfx_password, self.target.issuer_ca)
        self.sender = (sender_computer_name or DEFAULT_SENDER_COMPUTER).strip()
        self.timeout = float(timeout)
        self._clock = clock
        self._ctx: ssl.SSLContext | None = None
        self.session_id = _new_message_id()     # one MS-WSMV session per client; OperationID changes per request

    # -- HTTP --------------------------------------------------------------------------------------------------
    def _context(self) -> ssl.SSLContext:
        if self._ctx is None:
            try:
                self._ctx = build_ssl_context(self.identity)
            except (ssl.SSLError, ValueError, OSError):
                raise WecConfigError("the client certificate and key could not be loaded") from None
        return self._ctx

    def _post(self, path: str, body: bytes) -> tuple[int, bytes, str | None]:
        host = self.target.host
        conn = http.client.HTTPSConnection(host, self.target.port, timeout=self.timeout, context=self._context())
        try:
            conn.connect()
            verify_peer_name(conn.sock.getpeercert(binary_form=True), host)  # type: ignore[union-attr]
            conn.request("POST", path, body=body, headers={"Content-Type": CONTENT_TYPE, "Connection": "close"})
            resp = conn.getresponse()
            data = resp.read(MAX_RESPONSE_BYTES)
            return resp.status, data, resp.headers.get_content_charset()
        except WecError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise WecTlsError(f"server certificate verification failed: {exc.verify_message or exc.reason}") from None
        except ssl.SSLError as exc:
            raise WecTlsError(f"TLS failure: {exc.reason or exc.__class__.__name__}") from None
        except (OSError, http.client.HTTPException, socket.timeout) as exc:
            raise WecTransportError(f"{host}:{self.target.port} {exc.__class__.__name__}: {exc}") from None
        finally:
            conn.close()

    # -- operations --------------------------------------------------------------------------------------------
    def enumerate(self) -> list[Subscription]:
        """Ask the subscription manager for its subscriptions. Each call returns fresh identifiers."""
        status, data, charset = self._post(self.target.path, build_enumerate_request(
            self.target, self.sender, self.timeout, session_id=self.session_id))
        if status != 200:
            raise WecProtocolError(f"enumerate answered HTTP {status}: {decode_message(data, charset)[:200]!r}")
        if not data:
            raise WecProtocolError("enumerate answered HTTP 200 with an empty body: the applet did not recognise the request")
        return parse_enumerate_response(data, charset)

    def deliver(self, sub: Subscription, computer: str, event_xmls: Sequence[str]) -> None:
        """POST one envelope to `sub`'s delivery address. Anything but HTTP 200 raises WecDeliveryError.

        The connection goes to the subscription manager's host and port with the delivery address's path: the
        address in the reply names the same applet, and the host we already verified is the one we trust."""
        body = build_events_envelope(sub, computer, event_xmls, self.timeout, self.session_id)
        status, data, charset = self._post(sub.delivery_path, body)
        if status != 200:
            raise WecDeliveryError(f"delivery to {sub.name!r} answered HTTP {status}: {decode_message(data, charset)[:200]!r}",
                                   status=status)

    def send(self, events: Iterable[WecEvent]) -> SendReport:
        """Enumerate, route by channel, batch by encoded size (one envelope never mixes computers) and deliver.

        On a non-200 delivery the subscriptions are enumerated again (fresh identifiers) and that ONE envelope is
        retried once; envelopes already delivered are never resent. Errors carry the partial report in `.report`."""
        report = SendReport()
        try:
            subs = {s.name: s for s in self.enumerate()}
            enumerated_at = self._clock()
            order = list(subs.values())
            groups: dict[tuple[str, str], list[WecEvent]] = {}
            for ev in events:
                groups.setdefault((select_subscription(order, ev.channel).name, ev.computer), []).append(ev)
            # Plan EVERY group before the first delivery: an oversized or unsendable event for a later computer
            # must fail the whole call while nothing has been sent.
            plans = []
            for (sub_name, computer), evs in groups.items():
                xmls = [e.xml for e in evs]
                plans.append((sub_name, computer, xmls, plan_batches(subs[sub_name], computer, xmls, self.timeout)))
            for sub_name, computer, xmls, batches in plans:
                for batch in batches:
                    if self._clock() - enumerated_at > self.target.refresh:
                        subs, enumerated_at = self._refresh(report), self._clock()
                    chunk = [xmls[i] for i in batch]
                    try:
                        self.deliver(self._subscription(subs, sub_name), computer, chunk)
                    except WecDeliveryError:
                        subs, enumerated_at = self._refresh(report), self._clock()
                        self.deliver(self._subscription(subs, sub_name), computer, chunk)
                    report.sent += len(chunk)
                    report.envelopes += 1
                    report.by_computer[computer] = report.by_computer.get(computer, 0) + len(chunk)
                    report.by_subscription[sub_name] = report.by_subscription.get(sub_name, 0) + len(chunk)
        except WecError as exc:
            exc.report = report
            raise
        return report

    @staticmethod
    def _subscription(subs: dict[str, Subscription], name: str) -> Subscription:
        if name not in subs:
            raise WecProtocolError(f"subscription {name!r} is no longer offered by the collector (it disappeared "
                                   f"when the list was refreshed); events already delivered are in the report")
        return subs[name]

    def _refresh(self, report: SendReport) -> dict[str, Subscription]:
        report.reenumerations += 1
        return {s.name: s for s in self.enumerate()}
