"""Generic HTTP webhook destination handler.

Supports four authentication modes (discriminated by config.auth_type):

  - none:            no auth header
  - bearer:          Authorization: Bearer <bearer_token>
  - basic:           Authorization: Basic <base64(user:pass)>
  - api_key_header:  <header_name>: <header_value>

Plus optional custom_headers as a JSON object.

The send() path uses application/json by default but honors
content_type from the manifest. For arrays of records the body is
either a JSON array (application/json) or one record per line
(application/x-ndjson) or a plain-text concatenation (text/plain).
"""

from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

_DEFAULT_TIMEOUT = 10  # seconds


def _build_headers(merged_config: dict[str, Any]) -> dict[str, str]:
    """Build the full header set for a webhook request."""
    headers: dict[str, str] = {}
    headers["Content-Type"] = str(
        merged_config.get("content_type") or "application/json"
    )

    auth = str(merged_config.get("auth_type") or "none").lower()
    if auth == "bearer":
        token = merged_config.get("bearer_token") or ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth == "basic":
        u = merged_config.get("basic_username") or ""
        p = merged_config.get("basic_password") or ""
        if u or p:
            creds = f"{u}:{p}".encode("utf-8")
            headers["Authorization"] = (
                "Basic " + base64.b64encode(creds).decode("ascii")
            )
    elif auth == "api_key_header":
        name = (merged_config.get("header_name") or "").strip()
        value = merged_config.get("header_value") or ""
        if name and value:
            headers[name] = value
    # auth == "none" → no Authorization header

    # Operator-supplied custom headers (JSON object as a string).
    custom = merged_config.get("custom_headers")
    if custom:
        try:
            parsed = json.loads(custom) if isinstance(custom, str) else custom
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    headers[str(k)] = str(v)
        except (ValueError, TypeError):
            # Silently skip malformed custom_headers — frontend should
            # have validated. The probe will still succeed with the
            # mandatory headers; operators can fix in a re-edit.
            pass

    headers.setdefault("User-Agent", "phantom-log-destination/0.17")
    return headers


def _format_body(
    records: list[dict[str, Any]] | None, content_type: str,
) -> bytes:
    """Serialize records into the body per content-type."""
    if not records:
        return b""
    if content_type.startswith("application/x-ndjson"):
        return ("\n".join(json.dumps(r, default=str) for r in records)
                + "\n").encode("utf-8")
    if content_type.startswith("text/plain"):
        return ("\n".join(json.dumps(r, default=str) for r in records)
                + "\n").encode("utf-8")
    # default application/json: wrap in a list (single record →
    # single-element list, callers don't have to special-case).
    return json.dumps(records, default=str).encode("utf-8")


async def probe(merged_config: dict[str, Any]) -> dict[str, Any]:
    """Send a `{"phantom_test": true, ...}` payload; report ok/latency."""
    url = str(merged_config.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "url is required", "latency_ms": 0}

    method = str(merged_config.get("method") or "POST").upper()
    content_type = str(
        merged_config.get("content_type") or "application/json"
    )
    body_obj = {
        "phantom_test": True,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": "phantom log-destination probe",
    }
    headers = _build_headers(merged_config)
    body = _format_body([body_obj], content_type)

    req = urllib.request.Request(
        url, data=body, method=method, headers=headers,
    )
    # SSL verification is never disabled for the webhook type.
    # Operators with internal CAs can ship the CA via WEBHOOK custom
    # headers (or use the syslog TLS field set for that need).
    ctx = ssl.create_default_context()

    started = time.monotonic()
    try:
        with urllib.request.urlopen(
            req, context=ctx, timeout=_DEFAULT_TIMEOUT,
        ) as resp:
            status = resp.status
            _ = resp.read(4096)  # drain a bit
    except urllib.error.HTTPError as e:
        latency = int((time.monotonic() - started) * 1000)
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False,
                "error": f"HTTP {e.code}: {body_text or e.reason}",
                "latency_ms": latency}
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        latency = int((time.monotonic() - started) * 1000)
        return {"ok": False,
                "error": f"{type(e).__name__}: {e}",
                "latency_ms": latency}

    latency = int((time.monotonic() - started) * 1000)
    return {"ok": 200 <= status < 300,
            "error": None if 200 <= status < 300
                     else f"HTTP {status}",
            "latency_ms": latency}


async def send(
    merged_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send a batch of records to the webhook endpoint."""
    if not records:
        return {"sent": 0, "failed": 0, "errors": []}

    url = str(merged_config.get("url") or "").strip()
    if not url:
        return {"sent": 0, "failed": len(records),
                "errors": ["url is required"]}

    method = str(merged_config.get("method") or "POST").upper()
    content_type = str(
        merged_config.get("content_type") or "application/json"
    )
    headers = _build_headers(merged_config)
    body = _format_body(records, content_type)

    req = urllib.request.Request(
        url, data=body, method=method, headers=headers,
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
            req, context=ctx, timeout=_DEFAULT_TIMEOUT,
        ) as resp:
            if 200 <= resp.status < 300:
                return {"sent": len(records), "failed": 0, "errors": []}
            return {"sent": 0, "failed": len(records),
                    "errors": [f"HTTP {resp.status}"]}
    except Exception as e:  # noqa: BLE001
        return {"sent": 0, "failed": len(records),
                "errors": [f"{type(e).__name__}: {e}"]}
