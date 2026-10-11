"""Transport for the Cortex XSIAM HTTP Log Collector.

Wire contract (Cortex docs, "Set up an HTTP Log Collector to receive logs"):

  POST https://api-<tenant>/logs/v1/event
  Authorization: <collector key>          raw value, NOT "Bearer <key>"
  Content-Type:  application/json         (the collector's Log Format is JSON)
  Body:          records separated by "\\n" (NDJSON); 1 MiB per request is the
                 recommended size, 10 MiB the hard limit; 5 MB per record.

  200 {"error": "false"}  ok            401 bad key / collector deleted or disabled
  404 wrong URL           413 too large   429 rate limit (400 req/s per endpoint)
  500 body does not match the collector's configured Log Format

The vendor and product of a JSON collector are fixed by the collector's own
configuration (the dataset is `<vendor>_<product>_raw`); the request cannot
choose them. The vendor and product headers below are sent anyway as a harmless
hint; the collector ignores them when it does not honour them.

The collector key is only ever placed in the Authorization header. It is never
logged, never returned, and never part of an exception message.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import httpx

# The docs recommend 1 MiB per request; stay a little under it.
MAX_BATCH_BYTES = 900_000
# Per-record hard limit is 5 MB; refuse anything close to it up front.
MAX_RECORD_BYTES = 4_000_000
# 429 is the documented rate limit. 5xx gateway errors are transient. A plain
# 500 means the body did not match the collector's Log Format: retrying only
# repeats the mistake, so it is not in this set.
RETRY_STATUS = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 4


# What a secret header value may contain: printable ASCII, no space (0x21-0x7E). Anything else is refused
# up front with a fixed message, because the HTTP library's rejection of a bad header value quotes it.
_SECRET_OK = re.compile(r"[\x21-\x7e]+")
SECRET_REFUSED = "{what} contains characters that cannot be sent in a header: use printable ASCII only (no spaces or control characters)"


def valid_secret(value: str) -> bool:
    return bool(_SECRET_OK.fullmatch(value or ""))


def scrub(text: str, secret: str) -> str:
    """`text` with `secret` removed, also in its JSON-escaped and repr-escaped forms (an echo may escape it)."""
    if not secret:
        return text
    for form in (secret, json.dumps(secret)[1:-1], repr(secret)[1:-1]):
        if form:
            text = text.replace(form, "[redacted]")
    return text


def dataset_name(vendor: str, product: str) -> str:
    """The dataset the collector derives from its vendor/product: `<v>_<p>_raw`."""
    slug = lambda s: re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")  # noqa: E731
    return f"{slug(vendor)}_{slug(product)}_raw"


def to_ndjson_records(events: list[dict[str, Any]]) -> list[str]:
    """One compact JSON line per event. A record must not contain a raw newline,
    which `json.dumps` guarantees by escaping it."""
    records = []
    for ev in events:
        line = json.dumps(ev, separators=(",", ":"), ensure_ascii=False)
        if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("an event exceeds the collector's per-record size limit")
        records.append(line)
    return records


def split_batches(records: list[str], max_bytes: int = MAX_BATCH_BYTES) -> list[list[str]]:
    """Group records into request bodies no larger than `max_bytes`."""
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    for rec in records:
        rec_size = len(rec.encode("utf-8")) + 1  # the newline separator
        if current and size + rec_size > max_bytes:
            batches.append(current)
            current, size = [], 0
        current.append(rec)
        size += rec_size
    if current:
        batches.append(current)
    return batches


def post_events(
    url: str,
    key: str,
    events: list[dict[str, Any]],
    *,
    vendor: str,
    product: str,
    verify_tls: bool = True,
    timeout: float = 15.0,
    max_batch_bytes: int = MAX_BATCH_BYTES,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """POST `events` to the collector in batches. Never raises for transport or
    HTTP failures; those come back as `ok: false` with what was already accepted.

    Returns `{ok, sent, failed, batches, http_status, response, error?}`.
    `sent` counts events in batches the collector answered 200 to.
    """
    if not valid_secret(key):
        return {"ok": False, "sent": 0, "failed": len(events), "batches": 0, "http_status": None,
                "response": "", "error": SECRET_REFUSED.format(what="the collector key")}
    try:
        batches = split_batches(to_ndjson_records(events), max_batch_bytes)
    except ValueError as exc:
        return {"ok": False, "sent": 0, "failed": len(events), "batches": 0,
                "http_status": None, "response": "", "error": str(exc)}

    headers = {
        "Authorization": key,
        "Content-Type": "application/json",
        "x-palo-alto-networks-vendor": vendor,
        "x-palo-alto-networks-product": product,
    }
    sent = 0
    last_status: int | None = None
    last_body = ""
    # follow_redirects is pinned off: a redirect must never carry the key to another host.
    with httpx.Client(verify=verify_tls, timeout=timeout, transport=transport, follow_redirects=False) as client:
        for index, batch in enumerate(batches):
            body = "\n".join(batch).encode("utf-8")
            outcome = _post_with_retry(client, url, headers, body, sleep, secret=key)
            last_status, last_body = outcome["status"], outcome["body"]
            if outcome["error"] is not None or last_status != 200:
                failed = len(events) - sent
                return {
                    "ok": False, "sent": sent, "failed": failed, "batches": index,
                    "http_status": last_status, "response": last_body,
                    "error": outcome["error"] or _explain(last_status),
                }
            sent += len(batch)
    return {"ok": True, "sent": sent, "failed": 0, "batches": len(batches),
            "http_status": last_status, "response": last_body}


# Failures that retrying cannot fix: the request itself is malformed.
_NOT_RETRYABLE = (httpx.LocalProtocolError, httpx.UnsupportedProtocol, UnicodeError, ValueError)
# A request that may already have landed when the answer was lost.
POSSIBLY_LANDED = (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError)


def _post_with_retry(
    client: httpx.Client, url: str, headers: dict[str, str], body: bytes,
    sleep: Callable[[float], None], *, secret: str = "", retry_possibly_landed: bool = True,
) -> dict[str, Any]:
    """POST once, retrying 429 / gateway errors and connection failures. `secret` is scrubbed from the response
    BEFORE it is cut to 300 characters. A transport failure is reported by exception type only: the library's
    message can quote a header value. With `retry_possibly_landed` False a lost answer is final (a retry would
    duplicate a batch that may have landed)."""
    delay = 1.0
    status: int | None = None
    text = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.post(url, headers=headers, content=body)
        except (httpx.HTTPError, UnicodeError, ValueError) as exc:
            error = f"{type(exc).__name__}: the request could not be completed"
            if (isinstance(exc, _NOT_RETRYABLE) or attempt == MAX_ATTEMPTS
                    or (not retry_possibly_landed and isinstance(exc, POSSIBLY_LANDED))):
                return {"status": None, "body": "", "error": error}
            sleep(delay)
            delay *= 2
            continue
        status, text = resp.status_code, scrub(resp.text, secret)[:300]
        if status in RETRY_STATUS and attempt < MAX_ATTEMPTS:
            sleep(delay)
            delay *= 2
            continue
        break
    return {"status": status, "body": text, "error": None}


def _explain(status: int | None) -> str:
    return {
        401: "401 unauthorized: the collector key is wrong, or the HTTP collector is deleted or disabled",
        404: "404 not found: the collector URL is wrong (expected https://api-<tenant>/logs/v1/event)",
        413: "413 payload too large: the request exceeded the collector's 10 MiB limit",
        429: "429 rate limited: the collector allows 400 requests per second per endpoint",
        500: "500 the body does not match the collector's Log Format (it must be JSON for this connector)",
    }.get(status or 0, f"collector answered HTTP {status}")
