"""XSIAM HTTP Collector destination handler.

The XSIAM HTTP Collector ONLY uses:
  - Authorization: <auth_key>                  (required)
  - x-xdr-source / x-xdr-vendor / x-xdr-product (optional tags)

There is deliberately no auth_id field: the x-xdr-auth-id header belongs
to the PAPI envelope, and the HTTP Collector rejects it.

Payload shape:
  POST <url>
  Content-Type: application/json
  {"events": [{...record...}, ...]}

# XSIAM dataset destination

Records sent via the HTTP Collector ALWAYS land in the XSIAM dataset
named `phantom_logs_raw`. The dataset name is hardcoded on the XSIAM
side (derived from the 'phantom' brand on the collector). The events
arrive as one outer row per batch with an `events` JSON-array column
holding the original record list — a downstream XSIAM modeling rule
unflattens that array per-event.

XQL to verify records arrived:
    dataset = phantom_logs_raw
    | filter to_string(events) contains "<your distinctive marker>"
    | limit 20

(Contrast with the syslog/broker path — that one uses the
`<vendor>_<product>_raw` dataset name derived from CEF header fields.
See bundles/spark/destinations/syslog/handler.py docstring.)

XSIAM-side documentation:
  https://docs-cortex.paloaltonetworks.com/r/Cortex-XSIAM/Cortex-XSIAM-Documentation/Ingest-logs-from-an-HTTP-Collector
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

_DEFAULT_TIMEOUT = 10


def _build_headers(merged_config: dict[str, Any]) -> dict[str, str]:
    """Build headers for an XSIAM HTTP Collector request.

    x-xdr-auth-id is never emitted: that header is for the PAPI
    envelope, not the HTTP Collector, and XSIAM rejects it on Collector
    endpoints. The Collector authenticates via the Authorization header
    alone (whose value is the operator's auth_key).
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "phantom-log-destination/0.17 (xsiam_http)",
    }
    auth_key = merged_config.get("auth_key") or ""
    if auth_key:
        headers["Authorization"] = auth_key
    # Optional tags (mirror the XSIAM payload conventions)
    src = (merged_config.get("source") or "").strip()
    if src:
        headers["x-xdr-source"] = src
    vendor = (merged_config.get("vendor") or "").strip()
    if vendor:
        headers["x-xdr-vendor"] = vendor
    product = (merged_config.get("product") or "").strip()
    if product:
        headers["x-xdr-product"] = product
    return headers


def _envelope(records: list[dict[str, Any]]) -> bytes:
    return json.dumps({"events": records}, default=str).encode("utf-8")


async def probe(merged_config: dict[str, Any]) -> dict[str, Any]:
    url = str(merged_config.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "url is required", "latency_ms": 0}

    sample = {
        "phantom_test": True,
        "_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": "phantom log-destination probe",
    }
    req = urllib.request.Request(
        url, data=_envelope([sample]), method="POST",
        headers=_build_headers(merged_config),
    )
    ctx = ssl.create_default_context()

    started = time.monotonic()
    try:
        with urllib.request.urlopen(
            req, context=ctx, timeout=_DEFAULT_TIMEOUT,
        ) as resp:
            status = resp.status
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
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return {"ok": False,
                "error": f"{type(e).__name__}: {e}",
                "latency_ms": latency}

    latency = int((time.monotonic() - started) * 1000)
    return {"ok": 200 <= status < 300,
            "error": None if 200 <= status < 300 else f"HTTP {status}",
            "latency_ms": latency}


async def send(
    merged_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    if not records:
        return {"sent": 0, "failed": 0, "errors": []}
    url = str(merged_config.get("url") or "").strip()
    if not url:
        return {"sent": 0, "failed": len(records),
                "errors": ["url is required"]}

    req = urllib.request.Request(
        url, data=_envelope(records), method="POST",
        headers=_build_headers(merged_config),
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
