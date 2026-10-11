"""Shared test infrastructure: a throwaway PKI and an in-process fake WEC applet. Nothing here touches a network
beyond the loopback interface.

The fake applet is an HTTPS server that REQUIRES a client certificate, presents a server certificate with a CN and
no subjectAltName (like the real one), replays tests/fixtures/enumerate_response.xml for Enumerate (rewriting the
host and port, and giving every Enumerate fresh identifiers), and records every delivery.
"""
from __future__ import annotations

import base64
import datetime as dt
import ssl
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = Path(__file__).parent / "fixtures" / "enumerate_response.xml"
FIXTURE_HOST = "HTTPS://broker.example.lab:5986"
FIXTURE_IDENTIFIER = "61b87860-52f0-41a3-9a74-8719d8832e20"
PFX_PASSWORD = "pfx-pass-Zq81!"
MANAGER_PATH = "/wsman/SubscriptionManager/WEC"


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(cn: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(_name(cn)).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    return key, cert


def make_leaf(ca_key, ca_cert, cn: str, *, server: bool):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    eku = ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def make_pfx(client_key, client_cert, ca_cert, password: str = PFX_PASSWORD) -> bytes:
    """A PFX; `ca_cert` is the bundled CA, or a list of bundled certificates."""
    from cryptography.hazmat.primitives.serialization import pkcs12
    cas = list(ca_cert) if isinstance(ca_cert, (list, tuple)) else [ca_cert]
    return pkcs12.serialize_key_and_certificates(
        b"client", client_key, client_cert, cas, serialization.BestAvailableEncryption(password.encode()))


def pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def key_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


class Pki:
    """One CA, a client certificate packed into a PFX, and a server certificate (CN only, no SAN)."""

    def __init__(self, ca_cn: str = "Phantom Test CA", server_cn: str = "127.0.0.1") -> None:
        self.ca_key, self.ca_cert = make_ca(ca_cn)
        self.client_key, self.client_cert = make_leaf(self.ca_key, self.ca_cert, "phantom-client", server=False)
        self.server_key, self.server_cert = make_leaf(self.ca_key, self.ca_cert, server_cn, server=True)
        self.pfx = make_pfx(self.client_key, self.client_cert, self.ca_cert)
        self.pfx_b64 = base64.b64encode(self.pfx).decode()
        self.ca_thumbprint = self.ca_cert.fingerprint(hashes.SHA1()).hex().upper()

    def pfx_b64_wrapped(self, width: int = 64) -> str:
        """The base64 broken into lines (and padded with blanks), as a pasted secret may be."""
        return "\n  ".join(self.pfx_b64[i:i + width] for i in range(0, len(self.pfx_b64), width)) + "\n"


class FakeApplet:
    def __init__(self, pki: Pki, *, server_cert=None, server_key=None) -> None:
        self.pki = pki
        self.enumerations = 0
        self.deliveries: list[dict] = []     # recorded delivery requests
        self.enumerates: list[dict] = []     # recorded enumerate requests
        self.valid_identifiers: set[str] = set()
        self.statuses: list[int] = []        # status queue for deliveries (default 200); popped from the front
        self.enumerate_status = 200
        self.enumerate_encoding = "utf-8"
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # silence
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                record = {"path": self.path, "headers": dict(self.headers), "body": body,
                          "peer_cert": self.connection.getpeercert()}
                if self.path == MANAGER_PATH:
                    return outer._enumerate(self, record)
                return outer._deliver(self, record)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=pem(pki.ca_cert).decode())
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            c, k = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
            Path(c).write_bytes(pem(server_cert or pki.server_cert))
            Path(k).write_bytes(key_pem(server_key or pki.server_key))
            ctx.load_cert_chain(c, k)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    # -- handlers ----------------------------------------------------------------------------------------------
    def _reply(self, handler: BaseHTTPRequestHandler, status: int, body: bytes, ctype: str = "application/soap+xml") -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Server", "WEC Broker")
        handler.end_headers()
        handler.wfile.write(body)

    def _enumerate(self, handler, record) -> None:
        with self.lock:
            self.enumerations += 1
            self.enumerates.append(record)
            ident = str(uuid.uuid4())
            self.valid_identifiers.add(ident)
        text = FIXTURE.read_text(encoding="utf-8").replace(FIXTURE_HOST, f"HTTPS://127.0.0.1:{self.port}")
        text = text.replace(FIXTURE_IDENTIFIER, ident)
        enc = self.enumerate_encoding
        body = (b"\xff\xfe" + text.encode("utf-16-le")) if enc == "utf-16" else text.encode("utf-8")
        if self.enumerate_status != 200:
            return self._reply(handler, self.enumerate_status, b"nope")
        self._reply(handler, 200, body)

    def _deliver(self, handler, record) -> None:
        with self.lock:
            status = self.statuses.pop(0) if self.statuses else 200
            self.deliveries.append({**record, "status": status})
        self._reply(handler, status, b"")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(scope="session")
def pki() -> Pki:
    return Pki()


@pytest.fixture(scope="session")
def other_pki() -> Pki:
    """A completely different CA with its own client and server certificates."""
    return Pki(ca_cn="Some Other CA")


@pytest.fixture()
def applet(pki):
    srv = FakeApplet(pki)
    yield srv
    srv.close()


@pytest.fixture()
def manager_url(applet, pki) -> str:
    return f"Server=HTTPS://127.0.0.1:{applet.port}{MANAGER_PATH},Refresh=600,IssuerCA={pki.ca_thumbprint}"
