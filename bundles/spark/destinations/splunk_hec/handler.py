"""Splunk HTTP Event Collector destination handler.

Payload shape (per Splunk HEC docs):
  POST <url>
  Authorization: Splunk <token>
  Content-Type: application/json
  {"event": <record>, "sourcetype": ..., "source": ..., "index": ...}

Multiple events can be batched as newline-separated JSON objects (no
outer array). HEC accepts both single-event and batched forms.

Docs:
  https://docs.splunk.com/Documentation/Splunk/latest/Data/HECRESTendpoints
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
    token = merged_config.get("token") or ""
    return {
        "Authorization": f"Splunk {token}",
        "Content-Type": "application/json",
        "User-Agent": "phantom-log-destination/0.17 (splunk_hec)",
    }


def _envelope(records: list[dict[str, Any]], cfg: dict[str, Any]) -> bytes:
    """Splunk HEC batched format: newline-separated JSON objects."""
    source = (cfg.get("source") or "phantom").strip()
    sourcetype = (cfg.get("sourcetype") or "phantom:synthetic").strip()
    index = (cfg.get("index") or "").strip()
    lines = []
    for r in records:
        entry: dict[str, Any] = {
            "event": r,
            "source": source,
            "sourcetype": sourcetype,
        }
        if index:
            entry["index"] = index
        lines.append(json.dumps(entry, default=str))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _make_ctx(verify_ssl: Any) -> ssl.SSLContext:
    # Accept "true"/"false" string or bool from the form.
    if isinstance(verify_ssl, str):
        verify_ssl = verify_ssl.lower() not in ("false", "0", "no", "")
    if not verify_ssl:
        ctx = ssl._create_unverified_context()  # noqa: S323
    else:
        ctx = ssl.create_default_context()
    return ctx


async def probe(merged_config: dict[str, Any]) -> dict[str, Any]:
    url = str(merged_config.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "url is required", "latency_ms": 0}

    sample = {
        "phantom_test": True,
        "_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": "phantom log-destination probe",
    }
    body = _envelope([sample], merged_config)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers=_build_headers(merged_config),
    )
    ctx = _make_ctx(merged_config.get("verify_ssl", True))

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

    body = _envelope(records, merged_config)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers=_build_headers(merged_config),
    )
    ctx = _make_ctx(merged_config.get("verify_ssl", True))
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
