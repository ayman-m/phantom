"""Tests for the xsiam_assets (BYOS) destination handler.

The handler exists because the Vulnerability Ingest API is the ONLY way an
external system can create Cortex XSIAM asset_inventory rows. Its contract
was reverse-engineered against a live tenant, so these tests pin the parts
that were learned the hard way:

  - `probe()` must treat HTTP 422 as SUCCESS. It posts an empty asset list
    precisely so the server refuses it, which proves reachability AND
    entitlement while creating nothing.
  - 403 and 401 mean different, actionable things (missing entitlement vs
    wrong auth scheme) and must not be collapsed into one message.
  - `send()` must issue ONE request per call. The endpoint allows 10
    requests per hour, so a per-record loop would exhaust the budget after
    ten assets.
  - The record coercions repair the two payload shapes the API actually
    rejects: a `cve_id` that is not a list, and a missing `vulnerability_id`.

Every HTTP call is monkeypatched; these tests never reach the network.
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from pathlib import Path
from typing import Any

import pytest

_HANDLER_PATH = (
    Path(__file__).resolve().parents[3]
    / "spark" / "destinations" / "xsiam_assets" / "handler.py"
)


def _load_handler():
    spec = importlib.util.spec_from_file_location("xsiam_assets_handler", _HANDLER_PATH)
    assert spec and spec.loader, f"cannot load handler at {_HANDLER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def handler():
    return _load_handler()


@pytest.fixture()
def cfg() -> dict[str, Any]:
    return {
        "url": "https://api-example.xdr.eu.paloaltonetworks.com",
        "api_key": "k",
        "auth_id": "1",
        "default_severity": "medium",
        "verify_ssl": "true",
    }


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# probe()


def test_probe_treats_422_as_success(handler, cfg, monkeypatch) -> None:
    """422 is the intended reply: the empty list is refused, nothing created."""
    seen: dict[str, Any] = {}

    def fake_post(_cfg, body):
        seen["body"] = body
        return 422, '{"detail":[{"type":"too_short"}]}'

    monkeypatch.setattr(handler, "_post", fake_post)
    out = _run(handler.probe(cfg))
    assert out["ok"] is True
    # The probe must send an EMPTY list — sending a real asset would create one.
    assert seen["body"] == {"assets": []}


def test_probe_403_explains_entitlement(handler, cfg, monkeypatch) -> None:
    monkeypatch.setattr(handler, "_post", lambda c, b: (403, "forbidden"))
    out = _run(handler.probe(cfg))
    assert out["ok"] is False
    assert "manage_vulnerabilities_action" in out["error"]


def test_probe_401_explains_auth_scheme(handler, cfg, monkeypatch) -> None:
    """401 must NOT be reported as an entitlement problem — it is the wrong key."""
    monkeypatch.setattr(handler, "_post", lambda c, b: (401, ""))
    out = _run(handler.probe(cfg))
    assert out["ok"] is False
    assert "STANDARD key" in out["error"]
    assert "manage_vulnerabilities_action" not in out["error"]


def test_probe_requires_url_and_key(handler) -> None:
    assert _run(handler.probe({}))["ok"] is False
    assert _run(handler.probe({"url": "https://x"}))["ok"] is False


# --------------------------------------------------------------------------
# send()


def test_send_empty_is_a_noop(handler, cfg, monkeypatch) -> None:
    def boom(_c, _b):  # pragma: no cover - must not be called
        raise AssertionError("send([]) must not issue a request")

    monkeypatch.setattr(handler, "_post", boom)
    assert _run(handler.send(cfg, [])) == {"sent": 0, "failed": 0, "errors": []}


def test_send_issues_exactly_one_request_for_the_batch(handler, cfg, monkeypatch) -> None:
    """10 requests/hour — batching is the whole point."""
    calls: list[dict[str, Any]] = []

    def fake_post(_c, body):
        calls.append(body)
        return 200, '{"assets_count":3,"vulnerabilities_count":0,"job_id":"j","job_status":"INITIATED"}'

    monkeypatch.setattr(handler, "_post", fake_post)
    now = int(time.time() * 1000)
    out = _run(handler.send(cfg, [{"last_seen": now} for _ in range(3)]))

    assert len(calls) == 1, "must not loop per record"
    assert len(calls[0]["assets"]) == 3
    assert out["sent"] == 3
    assert out["job_id"] == "j"


def test_send_reports_rate_limit_clearly(handler, cfg, monkeypatch) -> None:
    monkeypatch.setattr(handler, "_post", lambda c, b: (429, ""))
    out = _run(handler.send(cfg, [{"last_seen": 1}]))
    assert out["sent"] == 0 and out["failed"] == 1
    assert "10 requests per hour" in out["errors"][0]


# --------------------------------------------------------------------------
# record coercion — the shapes the live API actually rejects


def test_last_seen_seconds_are_promoted_to_milliseconds(handler) -> None:
    secs = int(time.time())
    a = handler._to_asset({"last_seen": secs}, "medium", 0)
    assert a["last_seen"] == secs * 1000


def test_last_seen_defaults_when_absent(handler) -> None:
    a = handler._to_asset({"hostname": "h"}, "medium", 12345)
    assert a["last_seen"] == 12345


def test_bare_cve_id_string_becomes_a_list(handler) -> None:
    """A bare string is a 422 `list_type` error on the live API."""
    a = handler._to_asset(
        {"last_seen": 1, "vulnerabilities": [{"cve_id": "CVE-2021-44228"}]},
        "medium", 999,
    )
    v = a["vulnerabilities"][0]
    assert v["cve_id"] == ["CVE-2021-44228"]


def test_missing_vulnerability_id_is_filled_from_cve(handler) -> None:
    a = handler._to_asset(
        {"last_seen": 1, "vulnerabilities": [{"cve_id": ["CVE-2021-44228"]}]},
        "medium", 999,
    )
    assert a["vulnerabilities"][0]["vulnerability_id"] == "CVE-2021-44228"


def test_unknown_severity_falls_back_to_default(handler) -> None:
    a = handler._to_asset(
        {"last_seen": 1, "vulnerabilities": [{"vulnerability_id": "v", "severity": "spicy"}]},
        "high", 1,
    )
    assert a["vulnerabilities"][0]["severity"] == "high"


def test_non_list_vulnerabilities_are_dropped(handler) -> None:
    a = handler._to_asset({"last_seen": 1, "vulnerabilities": "nope"}, "medium", 1)
    assert "vulnerabilities" not in a


def test_unknown_fields_are_passed_through(handler) -> None:
    """The API tolerates extra keys; preserving them keeps the raw view useful."""
    a = handler._to_asset({"last_seen": 1, "hostname": "h", "custom": "x"}, "medium", 1)
    assert a["hostname"] == "h" and a["custom"] == "x"
