"""Secrets (the collector key, the Cribl token) never reach a result or an error, whatever they contain.

These tests run the REAL httpx / h11 stack against a local socket server on 127.0.0.1 (a MockTransport skips h11's
header validation, which is where a bad secret can leak: its error text quotes the value). No network.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import collector, cribl  # noqa: E402

NEWLINE_TOKEN = "tok-line1\nline2-secret"
NON_ASCII_TOKEN = "tok-ünïcode-secret-ε"
LONG_TOKEN = "T" + "".join(chr(ord("a") + (i * 7) % 26) for i in range(100))  # 101 printable chars
FIXED = collector.SECRET_REFUSED


class Server:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.mode = "count"  # "count": 200 with the line count; "echo": 400 with the Authorization header in the body
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                auth = self.headers.get("Authorization", "")
                outer.requests.append({"auth": auth, "headers": dict(self.headers), "body": body})
                if outer.mode == "echo":
                    # The token lands across the 300-character cut that results are truncated to.
                    status, payload = 400, ("A" * 250 + auth + "B" * 50).encode()
                else:
                    lines = [x for x in body.decode().split("\n") if x]
                    status, payload = 200, json.dumps({"num_records": len(lines), "success": "true", "error": "false"}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # keep pytest output quiet
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    srv = Server()
    yield srv
    srv.close()


@pytest.fixture(autouse=True)
def local_http_allowed(monkeypatch):
    # cribl.post insists on https; the local test server speaks plain http.
    monkeypatch.setattr(cribl, "check_url", lambda url: None)


def send_http(server, secret, evs=({"a": 1},)):
    return collector.post_events(f"{server.url}/logs/v1/event", secret, list(evs), vendor="V", product="P",
                                 sleep=lambda _s: None)


def send_cribl(server, secret, evs=({"a": 1},)):
    return cribl.post(f"{server.url}{cribl.PATH}", secret, cribl.SOURCES["okta_sso"], list(evs), sleep=lambda _s: None)


TRANSPORTS = [pytest.param(send_http, id="collector.post_events"), pytest.param(send_cribl, id="cribl.post")]


def forms(secret: str) -> set[str]:
    """Every shape a quoted secret can take in an error, plus pieces of it."""
    out = {secret, repr(secret), repr(secret.encode("utf-8", "backslashreplace")), json.dumps(secret), json.dumps(secret, ensure_ascii=False)}
    out |= {piece for piece in re.split(r"[\n\t ]", secret) if len(piece) > 5}
    return {f for f in out if f}


def assert_clean(result, secret):
    text = repr(result)
    for form in forms(secret):
        assert form not in text, form
    # no window of 12 characters of the secret survives either (a cut token is still a leaked token)
    for i in range(max(len(secret) - 11, 1)):
        assert secret[i:i + 12] not in text, secret[i:i + 12]


# -- the server and the happy path work -------------------------------------------------------------------------

@pytest.mark.parametrize("send", TRANSPORTS)
def test_a_valid_secret_is_sent_raw_in_the_authorization_header(server, send):
    result = send(server, LONG_TOKEN, [{"a": 1}, {"a": 2}])
    assert result["ok"] and result["sent"] == 2
    assert [r["auth"] for r in server.requests] == [LONG_TOKEN]
    assert LONG_TOKEN not in repr(result)


# -- BLOCKER 1: a secret that cannot be a header value -----------------------------------------------------------

@pytest.mark.parametrize("send", TRANSPORTS)
@pytest.mark.parametrize("secret,what", [(NEWLINE_TOKEN, "newline"), (NON_ASCII_TOKEN, "non-ascii"),
                                         ("has a space", "space"), ("tab\tinside", "tab"), ("del\x7fchar", "del")])
def test_a_bad_secret_is_refused_with_a_fixed_message_and_nothing_is_sent(server, send, secret, what):
    sleeps: list[float] = []
    result = (collector.post_events(f"{server.url}/logs/v1/event", secret, [{"a": 1}], vendor="V", product="P", sleep=sleeps.append)
              if send is send_http else
              cribl.post(f"{server.url}{cribl.PATH}", secret, cribl.SOURCES["okta_sso"], [{"a": 1}], sleep=sleeps.append))
    assert result["ok"] is False and result["sent"] == 0 and result["http_status"] is None
    assert result["error"] in (FIXED.format(what="the collector key"), FIXED.format(what="the Cribl token (criblToken)"))
    assert server.requests == [] and sleeps == []  # never sent, never retried
    assert_clean(result, secret)


@pytest.mark.parametrize("send", TRANSPORTS)
def test_an_empty_secret_is_refused_too(server, send):
    assert send(server, "")["ok"] is False and server.requests == []


# -- scrub before truncating ------------------------------------------------------------------------------------

@pytest.mark.parametrize("send", TRANSPORTS)
def test_a_long_secret_straddling_the_300_character_cut_is_scrubbed_whole(server, send):
    server.mode = "echo"
    result = send(server, LONG_TOKEN)
    assert not result["ok"] and result["http_status"] == 400
    assert server.requests[0]["auth"] == LONG_TOKEN  # it really was on the wire and really was echoed
    assert result["response"].startswith("A" * 250) and "[redacted]" in result["response"]
    assert_clean(result, LONG_TOKEN)


def test_truncating_first_would_have_left_part_of_the_token():
    # The failure shape, stated directly: cut to 300, then replace the whole token.
    body = "A" * 250 + LONG_TOKEN + "B" * 50
    old = body[:300].replace(LONG_TOKEN, "[redacted]")
    assert LONG_TOKEN[:12] in old  # what truncating first would leak
    assert LONG_TOKEN[:12] not in collector.scrub(body, LONG_TOKEN)[:300]


def test_scrub_removes_the_escaped_forms_of_an_echoed_secret():
    secret = 'ab"cd\\ef'  # printable ASCII with the two characters JSON and repr both escape
    for echoed in (secret, json.dumps(secret)[1:-1], repr(secret)[1:-1]):
        assert "ab" not in collector.scrub(f"seen {echoed} here", secret)
    assert collector.scrub("nothing here", "") == "nothing here"


# -- transport exceptions by type name only ---------------------------------------------------------------------

@pytest.mark.parametrize("header", [NEWLINE_TOKEN, NON_ASCII_TOKEN])
def test_the_library_error_for_a_bad_header_is_reported_by_type_only(server, header):
    """Bypass the up-front check and let the real stack reject the value: its own message quotes it."""
    sleeps: list[float] = []
    with httpx.Client() as client:
        with pytest.raises((httpx.LocalProtocolError, UnicodeError)) as raw:  # proves the library does fail, and quotes
            client.post(f"{server.url}/x", headers={"Authorization": header}, content=b"x")
        outcome = collector._post_with_retry(client, f"{server.url}/x", {"Authorization": header}, b"x", sleeps.append, secret=header)
    assert outcome["status"] is None and sleeps == [] and server.requests == []
    assert re.fullmatch(r"(LocalProtocolError|UnicodeEncodeError): the request could not be completed", outcome["error"])
    assert_clean(outcome, header)
    # The library's own message does carry part of the value (which is why its text is never passed on).
    assert ("line2" if header == NEWLINE_TOKEN else "\\xfc") in str(raw.value)


# -- the other transport failures stay by type too ---------------------------------------------------------------

@pytest.mark.parametrize("send", TRANSPORTS)
def test_a_connection_failure_is_reported_by_type_with_the_secret_absent(server, send):
    server.close()  # nothing listens any more
    result = send(server, LONG_TOKEN)
    assert not result["ok"] and re.fullmatch(r"\w+: the request could not be completed", result["error"])
    assert_clean(result, LONG_TOKEN)
