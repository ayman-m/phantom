"""Cortex XSIAM Asset Inventory destination — Vulnerability Ingest ("BYOS").

WHY THIS EXISTS. Cortex XSIAM models ASSETS in a separate subsystem from
logs, and none of Phantom's log paths can reach it. Verified empirically on
a live tenant:

  * A CEF event sent through the Broker carrying the same flat
    `xdm_asset_provider` / `xdm_asset_type_id` / `xdm_asset_strong_id`
    columns that the first-party `panw_ad_hygiene_*_raw` datasets use LANDS
    as a dataset and creates NO asset. Column shape does not promote.
  * `xdm.asset.*` is not part of the event XDM schema at all — 0 of ~930
    vendored modeling rules assign it — so no parsing or modeling rule can
    emit an asset.
  * The Asset Inventory REST API (`/public_api/v1/assets/`) is READ-ONLY;
    there is no create/update/delete verb.
  * `POST /logs/v1/xsiam` (the `collector-type: assets` path that shipping
    XSOAR asset collectors use) authenticates with
    `demisto.getLicenseCustomField('Http_Connector.token')` — a license
    custom field readable only from code running INSIDE the tenant. An
    external system can never hold it. All auth variants, including none,
    return an identical empty 401.

That leaves exactly one door for an external system, which this handler
implements.

THE CONTRACT (each element verified against a live tenant, not docs)

    POST {url}/public_api/vulnerability-management/v1/external-scans/assets
    Authorization: <api_key>          # plain, NOT the nonce+SHA256 scheme
    x-xdr-auth-id: <auth_id>
    Content-Type: application/json

    {"assets": [ {...}, ... ]}        # at least 1 item; [] is a 422

Per asset only `last_seen` (epoch milliseconds) is REQUIRED — the server
generates `asset_id` when absent. A vulnerability is NOT required: a body of
`{"assets":[{"last_seen":<ms>}]}` returns 200 with
`{"assets_count":1,"vulnerabilities_count":0,...}`.

Nested vulnerabilities require `vulnerability_id`, and `cve_id` must be a
LIST of strings (a bare string is a 422 `list_type` error).

A successful call is ASYNCHRONOUS and returns
`{"assets_count","vulnerabilities_count","job_id","job_status":"INITIATED"}`.
There is no job-status endpoint — GET on the job path returns 500 and GET on
the collection returns 405. Confirm landing by reading the inventory back.

TWO HARD LIMITS, both inherent and neither fixable here:

  * RATE: 10 requests per hour. This handler therefore sends ONE request per
    send() call carrying every record it was given. Batch upstream; do not
    loop over records.
  * FIDELITY: the platform OVERRIDES asset typing. A record submitted with
    `provider: AWS` and `asset_type: EC2_INSTANCE` materialised as
    `xdm.asset.provider = OTHER`, `xdm.asset.type.id = GENERIC_DEVICE_IP`,
    `xdm.asset.realm = Other`, with `strong_id` prefixed `byos:`. BYOS
    cannot produce cloud-typed assets. Properly-typed cloud assets
    (AZURE/GCP/AWS) come only from first-party discovery, which runs from
    Palo Alto's own SaaS and cannot be pointed at Phantom.

Entitlement shows up as a clean 403 "URL Forbidden. You do not have
permissions to access this resource" — distinct from a 401, which means the
key or the auth scheme is wrong.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

_PATH = "/public_api/vulnerability-management/v1/external-scans/assets"
_TIMEOUT = 60
_SEVERITIES = ("low", "medium", "high", "critical")


def _ctx(verify_ssl: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _headers(cfg: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": str(cfg.get("api_key") or ""),
        "x-xdr-auth-id": str(cfg.get("auth_id") or ""),
        "Content-Type": "application/json",
    }


def _endpoint(cfg: dict[str, Any]) -> str:
    return str(cfg.get("url") or "").strip().rstrip("/") + _PATH


def _normalize_vuln(raw: Any, default_severity: str, now_ms: int) -> dict[str, Any] | None:
    """Coerce a record's vulnerability into the shape the API validates.

    The two rejections the API actually raises are a missing
    `vulnerability_id` and a `cve_id` that is not a list, so both are
    repaired here rather than surfaced as a 422 the operator must decode.
    """
    if not isinstance(raw, dict):
        return None
    v = dict(raw)

    cve = v.get("cve_id")
    if isinstance(cve, str):
        v["cve_id"] = [cve]
    elif cve is None:
        v.pop("cve_id", None)
    elif not isinstance(cve, list):
        v["cve_id"] = [str(cve)]

    if not v.get("vulnerability_id"):
        cves = v.get("cve_id") or []
        v["vulnerability_id"] = str(cves[0]) if cves else f"phantom-{now_ms}"

    sev = str(v.get("severity") or default_severity).lower()
    v["severity"] = sev if sev in _SEVERITIES else default_severity
    v.setdefault("last_seen", now_ms)
    return v


def _to_asset(record: dict[str, Any], default_severity: str, now_ms: int) -> dict[str, Any]:
    """Project a generated record onto the BYOS asset schema.

    Unknown keys are passed through untouched: the API tolerates extra
    fields, and preserving them keeps the record readable in the inventory's
    raw view.
    """
    a = dict(record)

    # `last_seen` is the one genuinely required field. Accept seconds and
    # ISO-ish inputs from the generator rather than rejecting them.
    ls = a.get("last_seen")
    if isinstance(ls, (int, float)):
        a["last_seen"] = int(ls * 1000) if ls < 1e12 else int(ls)
    else:
        a["last_seen"] = now_ms

    fs = a.get("first_seen")
    if isinstance(fs, (int, float)):
        a["first_seen"] = int(fs * 1000) if fs < 1e12 else int(fs)

    vulns = a.get("vulnerabilities")
    if isinstance(vulns, list):
        cleaned = [
            nv
            for nv in (_normalize_vuln(v, default_severity, now_ms) for v in vulns)
            if nv is not None
        ]
        if cleaned:
            a["vulnerabilities"] = cleaned
        else:
            a.pop("vulnerabilities", None)
    elif vulns is not None:
        a.pop("vulnerabilities", None)

    return a


def _post(cfg: dict[str, Any], body: dict[str, Any]) -> tuple[int, str]:
    req = urllib.request.Request(
        _endpoint(cfg),
        data=json.dumps(body, default=str).encode("utf-8"),
        headers=_headers(cfg),
        method="POST",
    )
    ctx = _ctx(_truthy(cfg.get("verify_ssl")))
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            return int(resp.status), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return int(e.code), e.read().decode("utf-8", "replace")


def _explain(status: int, body: str) -> str:
    """Turn the API's status codes into something an operator can act on."""
    if status == 403:
        return (
            "403 Forbidden — the API key lacks manage_vulnerabilities_action, "
            "or the tenant has no Exposure Management entitlement."
        )
    if status == 401:
        return (
            "401 Unauthorized — wrong key or auth scheme. This endpoint takes a "
            "STANDARD key (plain Authorization + x-xdr-auth-id), not the advanced "
            "nonce+SHA256 signature."
        )
    if status == 429:
        return "429 Rate limited — the BYOS endpoint allows 10 requests per hour."
    return f"HTTP {status}: {body[:300]}"


async def probe(merged_config: dict[str, Any]) -> dict[str, Any]:
    """Check reachability + entitlement WITHOUT creating an asset.

    Posts `{"assets": []}`, which the server rejects with a 422 `too_short`
    because the list needs at least one item. That reply proves the endpoint
    is reachable AND the caller is entitled, while creating nothing — which
    is why this type sets `probe.send_test_message: false`.
    """
    if not str(merged_config.get("url") or "").strip():
        return {"ok": False, "error": "url is required", "latency_ms": 0}
    if not str(merged_config.get("api_key") or "").strip():
        return {"ok": False, "error": "api_key is required", "latency_ms": 0}

    started = time.monotonic()
    try:
        status, body = _post(merged_config, {"assets": []})
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    latency = int((time.monotonic() - started) * 1000)

    # 422 is the SUCCESS signal here — reachable, authorized, empty list refused.
    if status == 422:
        return {"ok": True, "latency_ms": latency}
    if 200 <= status < 300:
        # Should not happen for an empty list, but do not fail a working path.
        return {"ok": True, "latency_ms": latency}
    return {"ok": False, "error": _explain(status, body), "latency_ms": latency}


async def send(
    merged_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create asset records from a batch.

    Sends ONE request carrying every record. The endpoint allows only 10
    requests per hour, so looping per record would exhaust the budget after
    ten assets.
    """
    if not records:
        return {"sent": 0, "failed": 0, "errors": []}
    if not str(merged_config.get("url") or "").strip():
        return {"sent": 0, "failed": len(records), "errors": ["url is required"]}

    default_severity = str(merged_config.get("default_severity") or "medium").lower()
    if default_severity not in _SEVERITIES:
        default_severity = "medium"

    now_ms = int(time.time() * 1000)
    assets = [_to_asset(r, default_severity, now_ms) for r in records if isinstance(r, dict)]
    if not assets:
        return {"sent": 0, "failed": len(records), "errors": ["no dict records to send"]}

    try:
        status, body = _post(merged_config, {"assets": assets})
    except Exception as e:  # noqa: BLE001
        return {
            "sent": 0,
            "failed": len(records),
            "errors": [f"{type(e).__name__}: {e}"],
        }

    if 200 <= status < 300:
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {}
        return {
            "sent": int(parsed.get("assets_count") or len(assets)),
            "failed": 0,
            "errors": [],
            "job_id": parsed.get("job_id"),
            "job_status": parsed.get("job_status"),
            "vulnerabilities_count": parsed.get("vulnerabilities_count"),
        }

    return {"sent": 0, "failed": len(records), "errors": [_explain(status, body)]}
