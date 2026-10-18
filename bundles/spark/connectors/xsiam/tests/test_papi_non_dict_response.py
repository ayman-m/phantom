"""PAPIClient.request must never hand a caller a bare list.

Measured 2026-10-18: `xsiam_scripts_run_snippet` crashed with `AttributeError: 'list' object
has no attribute 'get'` on a well-formed call. The cause: `run_snippet_code_script` returned a
top-level JSON list instead of the usual `{"reply": {...}}` dict every other PAPI endpoint uses,
and every one of connector.py's 27+ call sites does `resp.get("reply") or {}` with no shape
check. Rather than add an isinstance guard to each of them, the guard belongs once in the HTTP
layer: a non-dict payload now raises PAPIResponseError (caught by `_xsiam_wrap` and turned into a
normal `{"ok": false, "error": "..."}` tool result) instead of corrupting every caller silently."""

from __future__ import annotations

import asyncio

import httpx

from src._papi_client import PAPIClient
from src._papi_exceptions import PAPIResponseError


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def _client_with_response(payload) -> PAPIClient:
    client = PAPIClient("https://example.test", {"Authorization": "x", "x-xdr-auth-id": "y"})

    async def fake_send(self, request, **kw):
        return _FakeResponse(200, payload)

    client.send = fake_send.__get__(client, PAPIClient)  # type: ignore[method-assign]
    return client


def test_bare_list_response_raises_papi_response_error() -> None:
    client = _client_with_response(["unexpected", "list", "shape"])
    try:
        asyncio.run(client.request("POST", "/scripts/run_snippet_code_script/", json={}))
        assert False, "expected PAPIResponseError"
    except PAPIResponseError as e:
        assert "list" in str(e)


def test_normal_dict_response_still_passes_through() -> None:
    client = _client_with_response({"reply": {"action_id": "abc123"}})
    result = asyncio.run(client.request("POST", "/scripts/run_snippet_code_script/", json={}))
    assert result == {"reply": {"action_id": "abc123"}}
