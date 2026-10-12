"""GET /api/v1/workers -- the xlog data-worker list the /tasks page renders.

Covers the pure parsing/redaction helpers and the route wiring (bearer gate,
xlog answers, xlog errors, xlog unreachable) with xlog itself faked out.
"""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api import worker_rates
from api.worker_rates import (
    parse_list_workers,
    redact_destination,
    register_worker_rate_routes,
)
from config.config import config as _config


def test_redact_destination_keeps_broker_literals():
    assert redact_destination("udp:10.0.0.8:514") == "udp:10.0.0.8:514"


def test_redact_destination_strips_userinfo_and_query():
    out = redact_destination("https://user:pw@collector.example:8443/logs/v1?api_key=SECRET#frag")
    # The path is masked as well: a collector token is often a path segment.
    assert out == "https://collector.example:8443/\u2026"
    assert "SECRET" not in out and "pw" not in out and "logs" not in out


def test_redact_destination_masks_a_token_in_the_path():
    out = redact_destination("https://collector.example/logs/v1/ABCDEF123456SECRETTOKEN/events")
    assert out == "https://collector.example/\u2026"
    assert "ABCDEF123456SECRETTOKEN" not in out


def test_redact_destination_without_a_path_adds_no_marker():
    assert redact_destination("https://collector.example:8443") == "https://collector.example:8443"
    assert redact_destination("https://collector.example:8443?token=SECRET") == "https://collector.example:8443"


def test_redact_destination_keeps_ipv6_brackets():
    assert redact_destination("https://[2001:db8::1]:8443/x/SECRET") == "https://[2001:db8::1]:8443/\u2026"
    assert redact_destination("http://[::1]/SECRET") == "http://[::1]/\u2026"
    assert redact_destination("udp:[2001:db8::1]:514") == "udp:[2001:db8::1]:514"


def test_redact_destination_unparseable_url_leaks_nothing():
    out = redact_destination("https://user:pw@[bad/SECRETPATH?token=SECRET")
    assert "SECRET" not in out and "pw" not in out and "user" not in out


def test_redact_destination_handles_none():
    assert redact_destination(None) == ""


def test_parse_list_workers_maps_fields():
    body = {
        "data": {
            "listWorkers": [
                {
                    "worker": "abc-123",
                    "type": "CEF",
                    "status": "Running",
                    "count": "5",
                    "interval": "2",
                    "destination": "udp:10.0.0.8:514",
                    "createdAt": "2026-10-12 10:00:00",
                }
            ]
        }
    }
    assert parse_list_workers(body) == [
        {
            "worker": "abc-123",
            "type": "CEF",
            "status": "Running",
            "count": "5",
            "interval": "2",
            "destination": "udp:10.0.0.8:514",
            "created_at": "2026-10-12 10:00:00",
        }
    ]


def test_parse_list_workers_empty_list_is_not_an_error():
    assert parse_list_workers({"data": {"listWorkers": []}}) == []


@pytest.mark.parametrize(
    "body",
    [None, [], {"errors": [{"message": "boom"}]}, {"data": None}, {"data": {"listWorkers": None}}],
)
def test_parse_list_workers_rejects_unusable_bodies(body):
    with pytest.raises(ValueError):
        parse_list_workers(body)


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


def _client(monkeypatch, handler):
    """TestClient whose xlog calls are answered by `handler(request)`."""
    monkeypatch.setattr(_config, "mcp_token", "test-mcp-token")
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def _factory(*a, **kw):
        kw["transport"] = transport
        return real(*a, **kw)

    monkeypatch.setattr(worker_rates.httpx, "AsyncClient", _factory)
    mcp = _FakeMcp()
    register_worker_rate_routes(mcp)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    return TestClient(app)


AUTH = {"Authorization": "Bearer test-mcp-token"}


def test_route_requires_bearer(monkeypatch):
    c = _client(monkeypatch, lambda req: httpx.Response(200, json={}))
    assert c.get("/api/v1/workers").status_code == 401


def test_route_returns_workers_and_posts_the_graphql_query(monkeypatch):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["body"] = req.content.decode()
        return httpx.Response(
            200,
            json={
                "data": {
                    "listWorkers": [
                        {
                            "worker": "w1",
                            "type": "CEF",
                            "status": "Running",
                            "count": "5",
                            "interval": "2",
                            "destination": "udp:10.0.0.8:514",
                            "createdAt": "t",
                        }
                    ]
                }
            },
        )

    c = _client(monkeypatch, handler)
    r = c.get("/api/v1/workers", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert r.json()["workers"][0]["worker"] == "w1"
    assert seen["method"] == "POST"
    assert "listWorkers" in seen["body"]


def test_route_surfaces_graphql_errors_as_502(monkeypatch):
    c = _client(
        monkeypatch,
        lambda req: httpx.Response(200, json={"errors": [{"message": "no"}]}),
    )
    r = c.get("/api/v1/workers", headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"] == "xlog_error"


def test_route_maps_xlog_auth_rejection(monkeypatch):
    c = _client(monkeypatch, lambda req: httpx.Response(401))
    r = c.get("/api/v1/workers", headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"] == "auth_error"


def test_route_reports_unreachable_xlog(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused")

    c = _client(monkeypatch, handler)
    r = c.get("/api/v1/workers", headers=AUTH)
    assert r.status_code == 502
    assert r.json()["error"] == "unreachable"
