"""The in-container callers of the agent's /api/chat must carry MCP_TOKEN.

Regression: the benchmark runner posted with no Authorization header, the
agent middleware answered 401 no_session_cookie, and every bench case scored
as an infrastructure error.
"""

from types import SimpleNamespace

import config.config as cfg
from usecase import agent_internal_auth, benchmark_runner


def _with_token(monkeypatch, token):
    monkeypatch.setattr(cfg, "get_config", lambda: SimpleNamespace(mcp_token=token))


def test_bearer_is_the_mcp_token(monkeypatch):
    _with_token(monkeypatch, "  tok-123 ")
    assert agent_internal_auth.internal_chat_bearer() == "Bearer tok-123"


def test_bearer_empty_when_token_unset(monkeypatch):
    _with_token(monkeypatch, "")
    assert agent_internal_auth.internal_chat_bearer() == ""


def test_benchmark_headers_carry_the_bearer(monkeypatch):
    _with_token(monkeypatch, "tok-123")
    headers = benchmark_runner._chat_headers()
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["X-Phantom-Trigger"] == "bench"


def test_benchmark_headers_omit_authorization_without_token(monkeypatch):
    _with_token(monkeypatch, "")
    assert "Authorization" not in benchmark_runner._chat_headers()
