"""Transport for the Cortex XSIAM Cribl integration endpoint.

The endpoint is what Cribl Stream's Cortex XSIAM destination posts to. A request that carries a
data source's DEDICATED `Source-Identifier` UUID is treated as that vendor's native feed: the rows get
the source's collector type, parsing, normalized audit rows and out-of-the-box Analytics, which the generic
HTTP collector never produced (measured on a Cortex tenant: 25 distinct detectors fired).

Wire contract (measured):

  POST https://api-<tenant>/logs/v1/integrated/cribl/data
  Authorization:          <token>               raw value, NOT "Bearer <token>"
  Source-Identifier:      <dedicated UUID>      one per source, see SOURCES
  Format:                 json
  Integration-Identifier: <name>                becomes `_collector_name` on the rows
  Content-Type:           application/json
  Body: NDJSON, EACH LINE WRAPPED {"data": <the vendor's event object>}; an unwrapped line
        lands as `_raw_log` only (no columns, no XDM). The Windows source differs: its
        event is the Windows Event XML as ONE PLAIN STRING, {"data": "<Event ...>"}; wrapped in an object it is
        answered 200 and lands nothing (measured), so `post` refuses an object for that source.

  200 {"num_records": N, "success": "true"}     400 says which header is missing

Events are sent in batches of 300. The token is only ever placed in the Authorization header. It is
never logged and never returned: a token that is not printable ASCII is refused before any request (the HTTP
library's complaint about a bad header value would quote it), every response is scrubbed of it before being cut
to length, and a transport failure is reported by exception type only.

A batch that may have landed is never resent: the timeout is at least 60 seconds (the lab sender's), a lost
answer (read timeout or reset) is final, and only a failure to connect or a 429 / gateway error is retried.
Redirects are never followed, so the token cannot be forwarded to another host.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, NamedTuple
from urllib.parse import urlparse

import httpx

from . import collector

# Events per request (the size Cribl Stream itself uses); a batch is also kept under the byte limit.
BATCH_EVENTS = 300
DEFAULT_INTEGRATION = "phantom-http-sender"
# The path every Cribl endpoint URL ends with (the HTTP collector's is /logs/v1/event: pasting that here must fail).
PATH = "/logs/v1/integrated/cribl/data"
# Seconds: the proven lab sender used 60, and a short timeout plus a retry could duplicate a batch that landed.
MIN_TIMEOUT = 60.0
# Destination names are `cribl_<alias>`.
PREFIX = "cribl_"
# The alias of the one source whose events are Windows Event XML strings, not objects (see windows_events.py).
WINDOWS = "windows_events"
# The Integration-Identifier travels in a header: keep it short and plain.
_INTEGRATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,63}")


class Source(NamedTuple):
    uuid: str
    dataset: str
    label: str


# Dedicated Source-Identifier UUIDs, from the Cortex docs page "Data source UUIDs" (public values, not secrets).
# The generic UUID (needs Vendor and Product headers) is deliberately absent: the generic path is the HTTP collector.
SOURCES: dict[str, Source] = {
    "okta_sso": Source("5faf4c1fdb8443d9920d6a54815432c1", "okta_sso_raw", "Okta SSO"),
    "azure_ad_signins": Source("f56dcfdf6bca43e793a4b6e9290e7b12", "msft_azure_ad_raw", "Azure AD sign-ins (Graph signIns)"),
    "azure_ad_audit": Source("0e076d5abe864bf78e8145ea9e0d749e", "msft_azure_ad_audit_raw", "Azure AD audit (Graph directoryAudits)"),
    "azure_event_hub": Source("fce13a1d51294f84bae4a37851503060", "msft_azure_raw", "Azure Event Hubs"),
    "aws_audit": Source("c19f87b6262f48259b3d5d2a2c691802", "amazon_aws_raw", "AWS CloudTrail"),
    "gcp_cloud_logging": Source("00a8322c85e14beabfa7ad5f3d62db73", "google_cloud_logging_raw", "GCP Cloud Logging"),
    WINDOWS: Source("63b0fbeb501e4650896e7064d3412e14", "microsoft_windows_raw", "Windows Event Logs"),
    "proofpoint_tap": Source("3eefce0f791e4391a3643b8cf860a361", "proofpoint_tap_raw", "Proofpoint TAP"),
}


def destination_name(alias: str) -> str:
    return PREFIX + alias


def check_url(url: str) -> str | None:
    """A problem with the Cribl URL, or None. The token travels in a header, so it must be https; and it must be the
    Cribl endpoint, not an HTTP collector's, whose dataset the events would pollute."""
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        return "the Cribl URL (criblUrl) must be an https:// URL"
    if not parsed.path.endswith(PATH):
        return f"the Cribl URL (criblUrl) must end in {PATH} (an HTTP collector's /logs/v1/event URL does not belong here)"
    return None


def check_integration(name: str) -> str | None:
    if not _INTEGRATION.fullmatch(name or ""):
        return "criblIntegration must be 1-64 letters, digits, spaces, dots, dashes or underscores"
    return None


def to_records(events: list[Any]) -> list[str]:
    """One compact `{"data": <event>}` line per event (an object, or for the Windows source the event's XML as a plain
    string); `json.dumps` escapes any newline inside an event, and all non-ASCII (the proven lab sender's form; raw UTF-8
    on this endpoint is untested)."""
    records = []
    for ev in events:
        line = json.dumps({"data": ev}, separators=(",", ":"))
        if len(line.encode("utf-8")) > collector.MAX_RECORD_BYTES:
            raise ValueError("an event exceeds the endpoint's per-record size limit")
        records.append(line)
    return records


def batches(records: list[str]) -> list[list[str]]:
    """Groups of at most BATCH_EVENTS records, each also under the byte limit."""
    out: list[list[str]] = []
    for i in range(0, len(records), BATCH_EVENTS):
        out.extend(collector.split_batches(records[i:i + BATCH_EVENTS]))
    return out


def post(
    url: str,
    token: str,
    source: Source,
    events: list[Any],
    *,
    integration: str = DEFAULT_INTEGRATION,
    verify_tls: bool = True,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """POST `events` to the Cribl endpoint under `source`'s identity. Never raises for transport or HTTP
    failures; those come back as `ok: false` with what was already accepted.

    Returns `{ok, sent, failed, batches, batch_status, num_records, http_status, response, error?}`.
    `sent` counts events in batches the endpoint answered 200 to with the right `num_records`.
    """
    def scrub(text: str) -> str:
        return collector.scrub(text, token)

    def failure(error: str, sent: int = 0, done: int = 0, statuses: list[int] | None = None,
                status: int | None = None, body: str = "", records: int = 0) -> dict[str, Any]:
        return {"ok": False, "sent": sent, "failed": len(events) - sent, "batches": done,
                "batch_status": statuses or [], "num_records": records, "http_status": status,
                "response": scrub(body), "error": scrub(error)}

    problem = (check_url(url) or check_integration(integration)
               or (None if collector.valid_secret(token) else collector.SECRET_REFUSED.format(what="the Cribl token (criblToken)")))
    if not problem and source == SOURCES[WINDOWS] and not all(isinstance(ev, str) for ev in events):
        # Measured: an object under this UUID is answered 200 and lands nothing, so refuse rather than send it.
        problem = ("events for the Windows Event Logs source must be Windows Event XML strings, each posted as a plain "
                   "{\"data\": \"<Event ...>\"} line (an object lands nothing): send structured Windows events with send_events")
    if problem:
        return failure(problem)
    try:
        groups = batches(to_records(events))
    except ValueError as exc:
        return failure(str(exc))

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "Source-Identifier": source.uuid,
        "Format": "json",
        "Integration-Identifier": integration,
    }
    sent = records = 0
    statuses: list[int] = []
    status: int | None = None
    body = ""
    # follow_redirects is pinned off: a redirect must never carry the token to another host.
    with httpx.Client(verify=verify_tls, timeout=max(timeout, MIN_TIMEOUT), transport=transport,
                      follow_redirects=False) as client:
        for index, group in enumerate(groups):
            # The measured body ends with a newline after the last line.
            payload = ("\n".join(group) + "\n").encode("utf-8")
            # Same retry policy as the collector (429, gateway errors, connection failures), except that a lost
            # answer is final: that batch may have landed, and a retry would duplicate it.
            outcome = collector._post_with_retry(client, url, headers, payload, sleep, secret=token,
                                                 retry_possibly_landed=False)
            status, body = outcome["status"], outcome["body"]
            if outcome["error"] is not None:
                return failure(outcome["error"], sent, index, statuses, status, body, records)
            statuses.append(status or 0)
            if status != 200:
                return failure(_explain(status), sent, index, statuses, status, body, records)
            accepted, problem = _accepted(body, len(group))
            if problem:
                return failure(problem, sent, index, statuses, status, body, records)
            sent += len(group)
            records += accepted
    return {"ok": True, "sent": sent, "failed": 0, "batches": len(groups), "batch_status": statuses,
            "num_records": records, "http_status": status, "response": scrub(body)}


def _accepted(body: str, expected: int) -> tuple[int, str | None]:
    """(records the endpoint counted, a problem or None) for a 200 answer `{"num_records": N, "success": "true"}`.
    N may arrive as an int or as a string of digits; anything else is a failure."""
    try:
        answer = json.loads(body)
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or "num_records" not in answer:
        return 0, "the endpoint answered 200 but not with num_records: the request was not processed as an integration feed"
    if str(answer.get("success")).lower() != "true":
        return 0, "the endpoint answered 200 with success=false"
    raw = answer["num_records"]
    if isinstance(raw, int) and not isinstance(raw, bool):
        count = raw
    elif isinstance(raw, str) and raw.isascii() and raw.isdigit():
        count = int(raw)
    else:
        return 0, "the endpoint answered 200 with a num_records that is not a count"
    if count != expected:
        return count, f"the endpoint counted {count} records for a batch of {expected}: some lines were not parsed"
    return count, None


def _explain(status: int | None) -> str:
    return {
        400: "400 bad request: a required header (Source-Identifier, Format, Integration-Identifier) is missing or "
             "the body is not NDJSON of {\"data\": ...} lines; the response says which",
        401: "401 unauthorized: the Cribl token is wrong, or the Cribl collector is deleted or disabled",
        403: "403 forbidden: the Cribl token is not allowed to use this Source-Identifier",
        404: "404 not found: the Cribl URL is wrong (expected https://api-<tenant>/logs/v1/integrated/cribl/data)",
        413: "413 payload too large: the request exceeded the endpoint's size limit",
        429: "429 rate limited: the endpoint is throttling this collector",
    }.get(status or 0, f"the Cribl endpoint answered HTTP {status}")
