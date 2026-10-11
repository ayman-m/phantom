"""`include_secrets` must not be reachable from off-box.

The parameter flips redaction off and returns resolved plaintext credentials.
Three endpoints honour it — instances, providers, log_destinations — but only
log_destinations checked anything beyond bearer auth. The two MOST sensitive
(connector secrets, provider credentials) were the LEAST guarded.

instances.py justified that with a comment claiming the agent's
/api/agent/backup route "verifies the operator's session cookie before proxying
here". It did not: backup delegated auth to middleware, which admitted API
keys, so any read-scoped key could retrieve every stored credential as a zip.

This is defence in depth, not the primary control — loopback is a weak signal
because the agent proxy reaches the MCP over localhost, which is the
confused-deputy hole that leaked destination tokens. That is closed at the
proxy, which strips the parameter outright. The value here is that a NEW proxy
route cannot silently re-open it.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from api.auth import require_loopback_for_secrets


class _Client:
    def __init__(self, host): self.host = host


class _Req:
    def __init__(self, params, host):
        self.query_params = params
        self.client = _Client(host) if host else None


def test_absent_parameter_is_always_allowed():
    """The redacted default path must never be gated."""
    assert require_loopback_for_secrets(_Req({}, "203.0.113.9")) is None


def test_false_value_is_allowed():
    assert require_loopback_for_secrets(
        _Req({"include_secrets": "false"}, "203.0.113.9")) is None


def test_loopback_caller_may_request_plaintext():
    """backup / vertex-credentials / anthropic-credentials all run in-container."""
    for host in ("127.0.0.1", "::1", "localhost"):
        assert require_loopback_for_secrets(
            _Req({"include_secrets": "true"}, host)) is None, host


def test_offbox_caller_is_refused():
    resp = require_loopback_for_secrets(
        _Req({"include_secrets": "true"}, "203.0.113.9"))
    assert resp is not None and resp.status_code == 403


def test_unknown_client_is_refused():
    """No peer address means we cannot prove locality — fail closed."""
    resp = require_loopback_for_secrets(_Req({"include_secrets": "true"}, None))
    assert resp is not None and resp.status_code == 403


def test_casing_does_not_bypass():
    resp = require_loopback_for_secrets(
        _Req({"include_secrets": "TRUE"}, "203.0.113.9"))
    assert resp is not None and resp.status_code == 403


def test_refusal_points_at_the_redacted_alternative():
    """An agent reads the error to correct itself; it must say what to use."""
    resp = require_loopback_for_secrets(
        _Req({"include_secrets": "true"}, "203.0.113.9"))
    body = resp.body.decode()
    assert "***" in body
