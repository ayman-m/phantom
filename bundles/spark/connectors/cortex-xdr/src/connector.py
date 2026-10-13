"""Cortex XDR connector — tool implementations.

Mirrors the xsiam connector structure: live
InstanceStore lookup for config + resolved secrets on every call,
build a stateless Fetcher, dispatch to /public_api/v1/... endpoints.

Tool catalog (alphabetical):
  xdr_get_cases_and_issues   POST /incidents/get_incidents — list incidents with filters
  xdr_get_incident_extra_data POST /incidents/get_incident_extra_data — full alert detail for one incident
  xdr_get_xql_results        POST /xql/get_query_results — poll an in-flight XQL execution
  xdr_run_xql_query          POST /xql/start_xql_query + poll — synchronous XQL execution with bounded wait

Auth model (same as XSIAM, same Cortex platform):
  Authorization: <api_key>       — Standard API key from the XDR console
                                   (plain header; an Advanced key needs a signed nonce and is not supported)
  x-xdr-auth-id: <api_id>        — integer key identifier
  Content-Type:  application/json

Config field names follow the uniform connector schema:
api_url + api_id + api_key — operators don't translate between XSIAM
and XDR.
"""
from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ._xdr_client import (
    Fetcher,
    XDRAuthError,
    XDRError,
    XDRRateLimitError,
    XDRRequestError,
    XDRServerError,
)


# Explicit tool exports. Without __all__, the
# connector-runtime entrypoint falls back to auto-discovery — which
# happens to pick up the *signature* of `_wrap_xdr_call`'s inner
# `wrapper` because the @-decorator replaced each public function's
# attributes but not its inspect.signature() shape. fastmcp's
# Tool.from_function rejects functions with *args, so registration
# crashed at startup with "Functions with *args are not supported as
# tools". Listing the public tool names here makes the runtime use
# the explicit-export path AND lets `functools.wraps` below restore
# the original wrapped signature.
__all__ = [
    # Original names (legacy aliases)
    "get_cases_and_issues",
    "get_incident_extra_data",
    "get_alerts",
    "run_xql_query",
    "get_xql_results",
    "list_datasets",  # empirical dataset enumeration

    # xdr_<category>_<action> rename aliases
    "xdr_incidents_list",
    "xdr_incidents_get_extra_data",
    "xdr_alerts_list",
    "xdr_xql_run_query",
    "xdr_xql_get_results",
    "xdr_xql_list_datasets",

    # incident / alert / IOC tools
    "xdr_incidents_update",
    "xdr_alerts_update",
    "xdr_ioc_insert_json",
    "xdr_ioc_disable",
    "xdr_ioc_enable",
    "xdr_download_file",

    # endpoints + response + scripts
    "xdr_endpoints_list_all",
    "xdr_endpoints_get",
    "xdr_endpoints_isolate",
    "xdr_endpoints_unisolate",
    "xdr_endpoints_scan",
    "xdr_endpoints_scan_all",
    "xdr_endpoints_set_alias",
    "xdr_endpoints_retrieve_file",
    "xdr_endpoints_quarantine_file",
    "xdr_response_get_action_status",
    "xdr_response_get_file_retrieval_details",
    "xdr_scripts_list",
    "xdr_scripts_get_metadata",
    "xdr_scripts_run_script",
    "xdr_scripts_run_snippet",
    "xdr_scripts_get_execution_status",
    "xdr_scripts_get_execution_results",
    "xdr_scripts_get_execution_result_files",

    # admin endpoints (audit / asset / distribution / exclusion / hash / exploit)
    "xdr_audit_list_management_logs",
    "xdr_audit_list_agent_logs",
    "xdr_assets_list",
    "xdr_assets_get",
    "xdr_distribution_list",
    "xdr_distribution_create",
    "xdr_distribution_get_url",
    "xdr_distribution_versions",
    "xdr_alert_exclusions_list",
    "xdr_alert_exclusions_create",
    "xdr_alert_exclusions_delete",
    "xdr_hash_get_analytics",
    "xdr_hash_blocklist",
    "xdr_exploits_list",
    "xdr_exploits_get_details",
]
# Function names are BARE (no xdr_ prefix). The connector-runtime's
# fixed prefix-stripping rules (phantom-connector-runtime/runtime/entrypoint.py)
# know about `phantom_<connector_id>_`, `<connector_id>_`, `phantom_`;
# `cortex-xdr_` doesn't match `xdr_`, so a prefixed function would be
# registered as `xdr_get_cases_and_issues` while the agent proxy calls
# bare names.
#
# So the prefix is left off the function definitions. connector.yaml
# `functionPrefix: "xdr_"` is still respected by the agent's wrapper
# generator (which builds `xdr_<bare>` aliases for the agent-side
# tool catalog), but the actual function names + container-side
# registrations stay bare. This aligns with how xsiam works
# (`xsiam_run_xql_query` happens to equal `<connector_id>_run_xql_query`
# so the strip lands on the bare name). For cortex-xdr the strip
# never matches, so the bare names are written by hand.


def _err(message: str, **extra: Any) -> dict:
    """Standard error envelope. Agents branch on `ok=false`."""
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return payload


def _ok(payload: dict) -> dict:
    """Standard success envelope."""
    if not isinstance(payload, dict):
        payload = {"value": payload}
    if "ok" not in payload:
        payload = {"ok": True, **payload}
    return payload


def _get_xdr_config() -> dict:
    """Read live cortex-xdr instance config + resolved secrets.

    Uses the connector-runtime's `config.config.get_config()` proxy
    rather than importing `usecase.instance_store` from the agent's
    Python tree: the connector runs in a separate container where
    `usecase/` doesn't exist, so such an import would raise
    ModuleNotFoundError on every tool call.

    The connector-runtime's `_load_instance` already opens the
    container-local `InstanceStoreReader`, resolves secrets via
    `SecretStoreReader`, merges them into a flat dict, and stashes
    the dict on a contextvar via `set_current_instance`. The
    `get_config()` proxy reads that contextvar — it returns a
    _ConfigProxy whose attribute access maps to the merged dict.
    """
    from config.config import get_config

    proxy = get_config()
    # The proxy raises AttributeError on missing keys. Convert that
    # into the operator-actionable ValueError that the chat UI
    # surfaces cleanly via _wrap_xdr_call.
    try:
        api_url = proxy.api_url
    except AttributeError:
        raise ValueError(
            "No cortex-xdr instance configured (api_url missing). Add a "
            "primary instance via /connectors with api_url + api_id + "
            "api_key, or configure it during first-time setup."
        )
    # Return the underlying merged dict so callers can do dict-style
    # .get() lookups (which is what _get_fetcher does).
    return {
        "api_url": api_url,
        "api_id": getattr(proxy, "api_id", None),
        "api_key": getattr(proxy, "api_key", None),
        "pollIntervalSeconds": getattr(proxy, "pollIntervalSeconds", 3),
        "maxPollAttempts": getattr(proxy, "maxPollAttempts", 40),
    }


def _get_fetcher() -> Fetcher:
    """Resolve the XDR Fetcher from the live instance config.

    Field name lookup matches XSIAM's pattern: prefer the new uniform
    names; no legacy fallback needed since cortex-xdr is greenfield
    (no pre-existing instances with old name patterns).
    """
    cfg = _get_xdr_config()

    api_url = cfg.get("api_url") or cfg.get("baseUrl")
    if not api_url:
        raise ValueError(
            "cortex-xdr instance has no api_url configured. Edit at /connectors."
        )
    api_key = cfg.get("api_key")
    if not api_key:
        raise ValueError(
            "cortex-xdr instance has no api_key (Authorization header) configured."
        )
    api_id = cfg.get("api_id")
    if not api_id:
        raise ValueError(
            "cortex-xdr instance has no api_id (X-Auth-ID header) configured. "
            "Edit at /connectors."
        )

    return Fetcher(str(api_url), str(api_key), str(api_id))


def _wrap_xdr_call(fn):
    """Decorator: convert XDR exceptions to error envelopes.

    The MCP tool surface returns dicts uniformly — never raises —
    so the agent can branch on `ok=false` instead of try/except.

    Uses `functools.wraps` rather than a manual __name__/__doc__ copy,
    which would leave the wrapper's
    inspect.signature() as `(*args, **kwargs)`, which fastmcp's
    Tool.from_function inspects + rejects with "Functions with *args
    are not supported as tools". functools.wraps sets __wrapped__ on
    the wrapper so inspect.signature() unwraps to the ORIGINAL
    function's typed signature — exactly what fastmcp needs to
    derive a tool schema from. Same observable behaviour at call
    time; only the introspection layer changes.
    """
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            result = await fn(*args, **kwargs)
            return _ok(result) if isinstance(result, dict) else _ok({"value": result})
        except XDRAuthError as exc:
            return _err(f"Cortex XDR auth failed: {exc}", is_auth_error=True)
        except XDRRateLimitError as exc:
            return _err(f"Cortex XDR rate-limited: {exc}", retryable=True)
        except XDRServerError as exc:
            return _err(f"Cortex XDR server error: {exc}", retryable=True)
        except XDRRequestError as exc:
            return _err(f"Cortex XDR request rejected: {exc}")
        except XDRError as exc:
            return _err(f"Cortex XDR error: {exc}")
        except ValueError as exc:
            # _get_fetcher's operator-actionable config errors
            return _err(str(exc))
        except Exception as exc:  # pragma: no cover — defensive
            return _err(f"xdr unexpected error: {type(exc).__name__}: {exc}")
    return wrapper


_RELATIVE_TIME_RE = __import__("re").compile(
    r"^\d+\s*(ms|mo|[smhdwy])$", __import__("re").IGNORECASE,
)


# XQL field-name alias map for the field-not-found error auto-suggest.
# LLM callers can burn ~7 xdr_run_xql_query attempts per question searching
# for the right field name when a KB example used a different tenant's
# naming. Common patterns:
#
#  - LLM tries `bytes_sent` / `bytes_received` (Splunk/QRadar style);
#    XDR uses `action_total_upload` / `action_total_download`
#  - LLM tries `timestamp` (generic SIEM); XDR uses `_time`
#  - LLM tries `host_count` / `hosts` (CrowdStrike style); XDR uses
#    `agent_hostname` / `dst_agent_hostname`
#  - LLM tries `process_name` (generic); XDR uses
#    `actor_process_image_name` / `action_process_image_name`
#  - LLM tries `command_line`; XDR uses `*_process_command_line`
#
# Each map entry is "wrong-guess field → list of likely-correct
# canonical names". On a FAIL response with `unknown field X`, we
# look up X here and bundle the suggestions into the error response.
# The LLM reads "did you mean: action_total_upload" and substitutes
# on the next iteration, saving 6+ retry attempts.
#
# This is heuristic — not exhaustive. Add entries as we observe new
# LLM-confusion patterns in chat sessions. Adding a wrong entry is
# low-risk: the LLM still has to actually use the suggestion + can
# fall back to cortex_search if none of them match.
_XQL_FIELD_ALIASES: dict[str, list[str]] = {
    # Bytes / network volume
    "bytes_sent": ["action_total_upload", "action_total_bytes_sent"],
    "bytes_received": ["action_total_download", "action_total_bytes_received"],
    "action_bytes_sent": ["action_total_upload"],
    "action_bytes_received": ["action_total_download"],
    "action_network_bytes": ["action_total_upload", "action_total_download"],
    "action_network_bytes_sent": ["action_total_upload"],
    "action_network_bytes_received": ["action_total_download"],
    "action_network_sent_bytes": ["action_total_upload"],
    "action_pkts_sent": ["action_total_pkts_sent"],
    "action_pkts_received": ["action_total_pkts_received"],
    "action_total_bytes": ["action_total_upload", "action_total_download"],
    # Time
    "timestamp": ["_time"],
    "event_timestamp": ["_time"],
    "detection_timestamp": ["_time"],
    "creation_time": ["_time", "first_seen"],
    # Host / endpoint
    "host_count": ["agent_hostname"],
    "hostname": ["agent_hostname"],
    "host_name": ["agent_hostname"],
    "hosts": ["agent_hostname"],
    "endpoint_hostname": ["agent_hostname", "endpoint_name"],
    "dst_hostname": ["dst_agent_hostname"],
    "dest_hostname": ["dst_agent_hostname"],
    # Process — actor side
    "process_name": [
        "actor_process_image_name", "action_process_image_name",
        "causality_actor_process_image_name",
    ],
    "parent_process_name": [
        "actor_process_image_name", "causality_actor_process_image_name",
    ],
    "child_process_name": ["action_process_image_name"],
    "command_line": [
        "actor_process_command_line", "action_process_image_command_line",
    ],
    "process_command_line": [
        "actor_process_command_line", "action_process_image_command_line",
    ],
    "process_path": [
        "actor_process_image_path", "action_process_image_path",
    ],
    # User
    "user": ["actor_primary_username", "actor_effective_username"],
    "username": ["actor_primary_username", "actor_effective_username"],
    "user_name": ["actor_primary_username", "actor_effective_username"],
    # File
    "file_name": ["action_file_name"],
    "file_path": ["action_file_path"],
    "filename": ["action_file_name"],
    # Network
    "src_ip": ["action_local_ip"],
    "source_ip": ["action_local_ip"],
    "dst_ip": ["action_remote_ip"],
    "dest_ip": ["action_remote_ip"],
    "destination_ip": ["action_remote_ip"],
    "remote_ip": ["action_remote_ip"],
    "remote_port": ["action_remote_port"],
    "dst_port": ["action_remote_port"],
    "destination_port": ["action_remote_port"],
    "src_port": ["action_local_port"],
    "source_port": ["action_local_port"],
}


def _extract_unknown_field(err: object) -> Optional[str]:
    """Pull the field name out of an XDR validation error.

    XDR returns FAIL responses with `error` as either a string OR a
    dict containing `validation_message`. Field-not-found errors carry
    text like `unknown field 'X'.` or `unknown field X.`. Returns the
    extracted name (without quotes or trailing punctuation) when we
    can identify one; None otherwise.
    """
    import re as _re
    if not err:
        return None
    text = ""
    if isinstance(err, str):
        text = err
    elif isinstance(err, dict):
        text = (
            str(err.get("validation_message", ""))
            or str(err.get("err_message", ""))
            or str(err.get("message", ""))
            or str(err)
        )
    else:
        text = str(err)
    m = _re.search(r"unknown field[\s:]+['\"]?([a-zA-Z_][\w]*)['\"]?", text)
    return m.group(1) if m else None


def _suggest_field_aliases(field: str) -> list[str]:
    """Return canonical-name suggestions for a field the LLM probably
    typo'd or guessed wrong. Falls back to common-XDR-prefix candidates
    if the field isn't in the static alias map (e.g. tries to match
    `*_image_name` family if the field name ends in `_name`)."""
    direct = _XQL_FIELD_ALIASES.get(field.lower(), [])
    if direct:
        return direct
    # Heuristic fallback — if the guess looks like a generic SIEM field
    # name, return the most likely XDR-family options based on suffix.
    lower = field.lower()
    if lower.endswith("_name") and "process" in lower:
        return ["actor_process_image_name", "action_process_image_name"]
    if lower.endswith("_ip") or lower.endswith("ip"):
        return ["action_remote_ip", "action_local_ip"]
    if lower.endswith("_port") or lower.endswith("port"):
        return ["action_remote_port", "action_local_port"]
    if lower.endswith("user") or lower.endswith("_user"):
        return ["actor_primary_username", "actor_effective_username"]
    return []


def _iso_to_ms(ts: Optional[str], default_offset_hours: int = 0) -> int:
    """Convert ISO timestamp (or None → now+offset) to ms since epoch.

    Cortex XDR API expects millisecond timestamps in filter request
    bodies. Default offset of 0 = now; negative offset = N hours ago.

    Accepts a numeric epoch (string or int) in addition to ISO.
    LLMs commonly pass `from_time=<int>` or `from_time="<ms-as-string>"`
    when they've already computed an epoch-ms boundary (e.g. the
    kill-chain skill captures op_start_epoch and passes it through).
    Feeding such a value to `datetime.fromisoformat("1779160958000")`
    would be parsed as `1779-16-09-58000` and raise
    "month must be in 1..12" — a confusing operator-facing error that
    masks a legitimate caller intent. Numeric input is therefore treated
    as already-epoch-ms (10 digits = seconds; 13 = ms).

    Relative-time expressions ("24h", "7d", "1w") are rejected with
    a helpful error message that routes the caller to the right place.
    LLMs do call `xdr_run_xql_query(query=..., timeframe_from="24h")`;
    the bare "Invalid isoformat string: '24h'" error would not tell them
    what to do. Instead an XQL-domain error points the LLM to the
    XQL-native `config timeframe = 24h` pattern, which is what most
    of the KB examples use.
    The error message itself is the recipe — the LLM reads it,
    recognizes the pattern, and switches to the query-body form on
    the next iteration without burning more XDR API quota.
    """
    if ts is None or ts == "":
        return int(
            (datetime.now(timezone.utc) + timedelta(hours=default_offset_hours)).timestamp()
            * 1000
        )

    # Numeric input fast-path. Accept int directly, or a string of
    # pure digits (optionally with leading minus, though epoch should
    # never be negative for our purposes). 10 digits = epoch seconds;
    # 13 digits = epoch milliseconds. We canonicalize to ms.
    if isinstance(ts, (int, float)):
        n = int(ts)
        return n * 1000 if n < 10_000_000_000 else n  # < 10^10 → seconds → ms
    if isinstance(ts, str) and ts.lstrip("-").isdigit():
        n = int(ts)
        return n * 1000 if abs(n) < 10_000_000_000 else n

    # Relative-time-expression reject. "24h", "7d", "1w", etc.
    # The LLM thinks this is a relative-time string the connector should
    # interpret; it's not. Raise a specific error that tells the LLM
    # what the right pattern is.
    if isinstance(ts, str) and _RELATIVE_TIME_RE.match(ts.strip()):
        raise ValueError(
            f"`timeframe_from` / `timeframe_to` must be ISO datetime "
            f"strings (e.g. '2026-05-20T00:00:00Z'), NOT relative-time "
            f"expressions like {ts!r}. To restrict the query to the last "
            f"{ts}, put `config timeframe = {ts}` at the start of your "
            f"query body instead — same effect, XQL-native, no function "
            f"args needed. This is the form 95% of the operator's KB "
            f"examples use. See build_xql_query skill Step 7."
        )

    # ISO string path. Accept ISO with or without timezone; assume
    # UTC if naive. The Z→+00:00 swap handles the common Z-suffix
    # form that XDR's own timestamps emit.
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ─── xdr_get_cases_and_issues ──────────────────────────────────────────


@_wrap_xdr_call
def _clamp_int(value: object, default: int, lo: int, hi: int) -> int:
    """Coerce `value` to an int clamped to [lo, hi], falling back to `default`
    when it is None or non-numeric.

    The connector runtime passes None for unspecified optional
    args, so a bare `int(value)` would raise TypeError on an empty-args call —
    e.g. `xdr_incidents_list` with no `limit` would hit `int(None)`. Routing
    every clamped limit through this helper makes those calls degrade to the
    default instead of throwing.
    """
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


async def get_cases_and_issues(
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    endpoint: Optional[str] = None,
    severity: Optional[list] = None,
    status: Optional[list] = None,
    limit: int = 50,
    time_field: str = "modification_time",
) -> dict:
    """List Cortex XDR incidents (cases) within filters.

    Args:
        from_time: Lower bound. Accepts an ISO timestamp
            (e.g. "2026-05-17T00:00:00Z") OR an epoch value as
            a numeric string ("1779160958" for seconds, or
            "1779160958000" for milliseconds). Default: 24h ago.
            (Numeric epoch input is accepted to match
            common LLM tool-call patterns where the caller already
            computed an epoch boundary.)
        to_time:   Upper bound. Same input formats as from_time.
                   Default: now.
        endpoint:  Hostname filter (matches alert.endpoint_name).
        severity:  Subset of ['low','medium','high','critical'].
        status:    Subset of ['new','under_investigation', ...].
        limit:     Max incidents (default 50, max 100).
        time_field: Which timestamp field to filter on. One of:
            - "modification_time" (default) — captures cases
              that have been TOUCHED in this window (new issues added,
              status changes, severity escalations). Use this for
              "what's happening NOW?" / "what should I investigate
              today?" / "did my attack simulation trigger anything?"
              XDR clusters new alerts into existing cases by threat
              fingerprint, so a case created LAST WEEK can receive a
              new alert TODAY. Only modification_time catches that;
              creation_time would silently miss it.
            - "creation_time" — captures cases
              WHOLLY NEW in this window. Use when you specifically
              want a fresh-start view ("what brand-new cases did the
              IDS surface today?", "how many net-new investigations
              this week?"). Misses updates to older cases.

    Returns:
        On success: {ok, incidents: [...], total_count, applied_filters}.
        Each incident: {incident_id, incident_name, severity, status,
                        alert_count, host_count, creation_time,
                        modification_time}.
        On failure: {ok: false, error}.
    """
    # Validate the time_field arg. The default is modification_time so the
    # common semantic ("what's been touched recently?") works: a case created
    # at 07:51 UTC can keep receiving new alerts from an ongoing Caldera kill
    # chain; filtering on creation_time (07:51 < from_time 08:06) would return
    # 0 incidents and miss those updates.
    if time_field not in ("creation_time", "modification_time"):
        return {
            "ok": False,
            "error": (
                "time_field must be 'creation_time' or 'modification_time', "
                f"got {time_field!r}"
            ),
        }

    from_ms = _iso_to_ms(from_time, default_offset_hours=-24)
    to_ms = _iso_to_ms(to_time, default_offset_hours=0)
    limit = _clamp_int(limit, 50, 1, 100)

    filters: list[dict] = [
        {"field": time_field, "operator": "gte", "value": from_ms},
        {"field": time_field, "operator": "lte", "value": to_ms},
    ]
    if endpoint:
        filters.append({"field": "alert_sources", "operator": "in", "value": [endpoint]})
        # Cortex XDR API also accepts host filtering via "hosts" field on
        # the get_incidents endpoint — operators see different results
        # depending on which field they filter on. We use alert_sources
        # since it's the path the XDR console uses.
    if severity:
        filters.append({"field": "severity", "operator": "in", "value": severity})
    if status:
        filters.append({"field": "status", "operator": "in", "value": status})

    body = {
        "request_data": {
            "search_from": 0,
            "search_to": limit,
            "filters": filters,
            # Sort by the same field we're filtering on so the
            # "newest" rows in the result list match the filter semantic.
            "sort": {"field": time_field, "keyword": "desc"},
        }
    }

    fetcher = _get_fetcher()
    response = await fetcher.post("/incidents/get_incidents", body)

    # Response shape: {reply: {total_count, result_count, incidents: [...]}}
    reply = response.get("reply", {})
    incidents = reply.get("incidents", [])
    total = reply.get("total_count", len(incidents))

    # Project a compact summary per incident — operators don't need
    # every field at the list level. Use xdr_get_incident_extra_data
    # for full detail on a specific one.
    summary = [
        {
            "incident_id": inc.get("incident_id"),
            "incident_name": inc.get("incident_name") or inc.get("description"),
            "severity": inc.get("severity"),
            "status": inc.get("status"),
            "alert_count": inc.get("alert_count"),
            "host_count": inc.get("host_count", 0),
            "creation_time": inc.get("creation_time"),
            "modification_time": inc.get("modification_time"),
            "assigned_user": inc.get("assigned_user_pretty_name"),
            "starred": inc.get("starred", False),
        }
        for inc in incidents
    ]

    return {
        "incidents": summary,
        "total_count": total,
        "result_count": len(summary),
        "applied_filters": {
            "from_time": from_time,
            "to_time": to_time,
            "endpoint": endpoint,
            "severity": severity,
            "status": status,
            "limit": limit,
            "time_field": time_field,
        },
    }


# ─── xdr_get_incident_extra_data ──────────────────────────────────────


@_wrap_xdr_call
async def get_incident_extra_data(
    incident_id: str,
    alerts_limit: int = 50,
) -> dict:
    """Fetch full details for one incident — including all alerts.

    Use AFTER xdr_get_cases_and_issues to drill into a specific
    incident. Returns alerts, network artifacts, file artifacts,
    and related user/host context.

    Args:
        incident_id:  ID from a prior xdr_get_cases_and_issues hit.
        alerts_limit: Cap on alerts returned (default 50).

    Returns:
        On success: {ok, incident, alerts, network_artifacts, file_artifacts}.
        On failure: {ok: false, error}.
    """
    if not incident_id:
        raise ValueError("incident_id is required")

    body = {
        "request_data": {
            "incident_id": str(incident_id),
            "alerts_limit": _clamp_int(alerts_limit, 50, 1, 1000),
        }
    }

    fetcher = _get_fetcher()
    response = await fetcher.post("/incidents/get_incident_extra_data", body)

    # Response shape: {reply: {incident: {...}, alerts: {...}, network_artifacts: {...}, file_artifacts: {...}}}
    reply = response.get("reply", {})
    alerts_obj = reply.get("alerts", {})
    network_obj = reply.get("network_artifacts", {})
    file_obj = reply.get("file_artifacts", {})

    return {
        "incident": reply.get("incident", {}),
        "alerts": alerts_obj.get("data", []),
        "alerts_total": alerts_obj.get("total_count", 0),
        "network_artifacts": network_obj.get("data", []),
        "network_artifacts_total": network_obj.get("total_count", 0),
        "file_artifacts": file_obj.get("data", []),
        "file_artifacts_total": file_obj.get("total_count", 0),
    }


# ─── xdr_get_alerts ────────────────────────────────────────────────────


@_wrap_xdr_call
async def get_alerts(
    alert_ids: Optional[list] = None,
    severity: Optional[list] = None,
    status: Optional[list] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    limit: int = 50,
    sort_by: str = "creation_time",
) -> dict:
    """List Cortex XDR alerts (a.k.a. 'issues') across all cases.

    Wraps XDR's /public_api/v1/alerts/get_alerts REST endpoint. Use
    for:
      * Looking up specific alerts by ID (e.g. from an XDR Console URL
        or a colleague's hand-off): `get_alerts(alert_ids=[40119, 40265])`
      * Hunting alerts by technique / host / severity / time without
        going through their parent cases.
      * Drilling into a specific alert ID outside the case-clustering
        view (XDR's case-clustering aggregates alerts into incidents
        by threat fingerprint; this tool gives you the alert-level
        flat view).

    For case-level queries (cases that cluster multiple alerts), use
    xdr_get_cases_and_issues. For alerts WITHIN a specific case, use
    xdr_get_incident_extra_data with that incident_id. For free-form
    data-lake queries, use xdr_run_xql_query (but note: XDR's XQL
    `preset = xdr_alerts` returns HTTP 500 in some tenants — this REST
    tool is the reliable alternative).

    Args:
        alert_ids: Specific integer alert IDs to fetch (e.g.
            [40119, 40265]). When provided, time / severity / status
            filters are still respected but typically you'd omit them
            to fetch by ID alone. XDR's API requires these to be
            integers — the connector coerces strings via int(x).
        severity: Subset of ['low', 'medium', 'high', 'critical'].
        status:   Subset of ['new', 'under_investigation', 'resolved_*'].
        from_time: Lower bound on creation_time. ISO timestamp or
            numeric epoch (same input shapes as get_cases_and_issues).
            Default: 24h ago.
        to_time:   Upper bound on creation_time. Default: now.
        limit:     Max alerts (default 50, max 100).
        sort_by:   'creation_time' (default) or 'detection_timestamp'.

    Returns:
        On success: {ok, alerts: [...], total_count, applied_filters}.
        Each alert summary: {alert_id, name, severity, category, source,
            host_name, mitre_technique_id_and_name, mitre_tactic_id_and_name,
            creation_time, detection_timestamp, case_id, user_name,
            actor_process_image_name, actor_process_command_line,
            action_file_name, action_file_path, description}.
        On failure: {ok: false, error}.

    Why this tool exists separately from XQL: in production tenants,
    we observed XDR's XQL alerts preset (`preset = xdr_alerts`) returning
    HTTP 500 errors consistently across many query shapes, while the
    REST `/alerts/get_alerts` endpoint stays available. This tool is the
    durable path for alert lookup — same data, less infrastructure
    fragility.
    """
    # Validate sort_by
    if sort_by not in ("creation_time", "detection_timestamp"):
        return {
            "ok": False,
            "error": (
                "sort_by must be 'creation_time' or 'detection_timestamp', "
                f"got {sort_by!r}"
            ),
        }

    from_ms = _iso_to_ms(from_time, default_offset_hours=-24)
    to_ms = _iso_to_ms(to_time, default_offset_hours=0)
    limit = _clamp_int(limit, 50, 1, 100)

    filters: list[dict] = []

    if alert_ids:
        # XDR's API rejects string IDs with: "alert_id_list list must
        # contain only integers". Coerce defensively — LLM tool calls
        # commonly serialize IDs as strings.
        try:
            coerced_ids = [int(x) for x in alert_ids]
        except (TypeError, ValueError) as exc:
            return {
                "ok": False,
                "error": f"alert_ids must be coercible to int: {exc}",
            }
        filters.append({"field": "alert_id_list", "operator": "in", "value": coerced_ids})

    # When alert_ids is the primary selector and no explicit time window
    # was passed, SKIP the default-24h time filters. The default-24h window
    # makes sense for unfiltered list queries ("most recent alerts") but
    # breaks ID lookups for older alerts: get_alerts(alert_ids=[40119])
    # would return 0 if alert 40119 was created >24h ago, because the
    # AND-of-filters semantic excludes it.
    #
    # Decision matrix:
    #   alert_ids set, NO explicit time   → skip time filters (search across all history)
    #   alert_ids set, EXPLICIT time      → apply both (operator wants the intersect)
    #   alert_ids unset                   → apply time filters (default 24h window)
    explicit_time = (from_time is not None) or (to_time is not None)
    if not alert_ids or explicit_time:
        filters.append({"field": "creation_time", "operator": "gte", "value": from_ms})
        filters.append({"field": "creation_time", "operator": "lte", "value": to_ms})

    if severity:
        filters.append({"field": "severity", "operator": "in", "value": severity})
    if status:
        filters.append({"field": "status", "operator": "in", "value": status})

    body = {
        "request_data": {
            "search_from": 0,
            "search_to": limit,
            "filters": filters,
            "sort": {"field": sort_by, "keyword": "desc"},
        }
    }

    fetcher = _get_fetcher()
    response = await fetcher.post("/alerts/get_alerts", body)

    # Response shape: {reply: {total_count, result_count, alerts: [...]}}
    reply = response.get("reply", {})
    alerts = reply.get("alerts", [])
    total = reply.get("total_count", len(alerts))

    # Project a compact summary per alert — XDR returns ~80 fields per
    # alert, most are noise for the agent's reasoning. The summary keeps
    # the fields the LLM needs to triage, correlate, and explain.
    # For full forensic detail on a specific alert, use
    # xdr_get_incident_extra_data with that alert's case_id.
    summary = []
    for a in alerts:
        summary.append({
            "alert_id": a.get("alert_id") or a.get("id"),
            "name": a.get("name"),
            "severity": a.get("severity"),
            "category": a.get("category"),
            "source": a.get("source"),
            "host_name": a.get("host_name") or a.get("agent_hostname"),
            "host_ip": a.get("host_ip"),
            "user_name": a.get("user_name"),
            "case_id": a.get("case_id"),
            "creation_time": a.get("creation_time"),
            "detection_timestamp": a.get("detection_timestamp"),
            "mitre_technique_id_and_name": a.get("mitre_technique_id_and_name"),
            "mitre_tactic_id_and_name": a.get("mitre_tactic_id_and_name"),
            "actor_process_image_name": a.get("actor_process_image_name"),
            "actor_process_command_line": a.get("actor_process_command_line"),
            "causality_actor_process_image_name":
                a.get("causality_actor_process_image_name"),
            "action_process_image_name": a.get("action_process_image_name"),
            "action_process_image_command_line":
                a.get("action_process_image_command_line"),
            "action_file_name": a.get("action_file_name"),
            "action_file_path": a.get("action_file_path"),
            "description": a.get("description"),
        })

    return {
        "alerts": summary,
        "total_count": total,
        "result_count": len(summary),
        "applied_filters": {
            "alert_ids": alert_ids,
            "severity": severity,
            "status": status,
            "from_time": from_time,
            "to_time": to_time,
            "limit": limit,
            "sort_by": sort_by,
        },
    }


# ─── xdr_run_xql_query ─────────────────────────────────────────────────


async def _start_xql_query(
    fetcher: Fetcher,
    query: str,
    tenant_ids: Optional[list] = None,
    timeframe_from: Optional[str] = None,
    timeframe_to: Optional[str] = None,
) -> str:
    """Kick off an XQL query; return the execution_id."""
    request_data: dict[str, Any] = {"query": query}
    if tenant_ids:
        request_data["tenants"] = tenant_ids
    # Cortex XDR XQL accepts a timeframe object with absolute ms timestamps.
    if timeframe_from or timeframe_to:
        request_data["timeframe"] = {
            "from": _iso_to_ms(timeframe_from, default_offset_hours=-24),
            "to": _iso_to_ms(timeframe_to, default_offset_hours=0),
        }

    response = await fetcher.post(
        "/xql/start_xql_query/",
        {"request_data": request_data},
    )
    reply = response.get("reply")
    if isinstance(reply, dict):
        eid = reply.get("execution_id") or reply.get("query_id")
    else:
        eid = reply  # XDR sometimes returns the id as a bare string
    if not eid:
        raise XDRError(f"start_xql_query returned no execution_id: {response!r}")
    return str(eid)


async def _get_xql_results(
    fetcher: Fetcher,
    execution_id: str,
    limit: int = 1000,
) -> dict:
    """Poll once for results. Returns the raw reply dict."""
    body = {
        "request_data": {
            "query_id": execution_id,
            "pending_flag": True,
            "limit": _clamp_int(limit, 1000, 1, 10000),
            "format": "json",
        }
    }
    response = await fetcher.post("/xql/get_query_results/", body)
    return response.get("reply", {})


@_wrap_xdr_call
async def run_xql_query(
    query: str,
    tenant_ids: Optional[list] = None,
    timeframe_from: Optional[str] = None,
    timeframe_to: Optional[str] = None,
) -> dict:
    """Execute an XQL query synchronously (with bounded polling).

    Args:
        query:          XQL query text.
        tenant_ids:     Optional multi-tenant scope.
        timeframe_from: ISO timestamp lower bound. Default: 24h ago.
        timeframe_to:   ISO timestamp upper bound. Default: now.

    Returns:
        Complete: {ok, status: 'SUCCESS', execution_id, results: [...],
                   total_rows, fields}.
        Still running: {ok, status: 'PENDING', execution_id} —
                       caller polls via xdr_get_xql_results.
        On failure: {ok: false, error}.
    """
    if not query or not isinstance(query, str) or not query.strip():
        raise ValueError("query is required (non-empty string)")

    cfg = _get_xdr_config()
    poll_interval = max(1, int(cfg.get("pollIntervalSeconds", 3)))
    max_attempts = max(1, int(cfg.get("maxPollAttempts", 40)))

    fetcher = _get_fetcher()
    execution_id = await _start_xql_query(
        fetcher, query, tenant_ids, timeframe_from, timeframe_to
    )

    for attempt in range(max_attempts):
        await asyncio.sleep(poll_interval)
        reply = await _get_xql_results(fetcher, execution_id)
        status = reply.get("status", "PENDING")
        if status == "SUCCESS":
            results = reply.get("results", {})
            return {
                "status": "SUCCESS",
                "execution_id": execution_id,
                "results": results.get("data", []),
                "total_rows": reply.get("number_of_results", 0),
                "fields": results.get("fields", []),
            }
        if status in ("FAIL", "FAILED", "CANCELLED", "TIMEOUT"):
            err = reply.get("err_message") or reply.get("error") or status
            out = {
                "status": status,
                "execution_id": execution_id,
                "error": err,
            }
            # Field-not-found auto-suggest. Extract the
            # unknown-field name + bundle canonical-XDR alternatives
            # into the response so the LLM can substitute on the next
            # iteration without burning 6+ retries searching for the
            # right name.
            unknown_field = _extract_unknown_field(err)
            if unknown_field:
                suggestions = _suggest_field_aliases(unknown_field)
                if suggestions:
                    out["unknown_field"] = unknown_field
                    out["field_suggestions"] = suggestions
                    out["fix_hint"] = (
                        f"XDR doesn't have a field named '{unknown_field}'. "
                        f"Try one of: {', '.join(suggestions)}. If none "
                        f"match the user's intent, call cortex_search("
                        f"query='<dataset> <field>', product='xql') to "
                        f"find the canonical name. Do NOT retry "
                        f"xdr_run_xql_query with another guess — that's "
                        f"the forbidden field-thrashing pattern."
                    )
            return out
        # else PENDING — keep polling

    # Polling window exceeded — return execution_id for caller to poll
    return {
        "status": "PENDING",
        "execution_id": execution_id,
        "note": (
            f"query still running after {max_attempts * poll_interval}s; "
            f"call xdr_get_xql_results with execution_id to retrieve "
            f"results when ready"
        ),
    }


# ─── xdr_get_xql_results ───────────────────────────────────────────────


@_wrap_xdr_call
async def get_xql_results(
    execution_id: str,
    limit: int = 1000,
) -> dict:
    """Retrieve results from an in-flight XQL query by execution_id.

    Use when xdr_run_xql_query returned status=PENDING.

    Args:
        execution_id: From a prior xdr_run_xql_query call.
        limit:        Max rows (default 1000, max 10000).

    Returns:
        {ok, status, results, total_rows, fields, execution_id}.
    """
    if not execution_id:
        raise ValueError("execution_id is required")

    fetcher = _get_fetcher()
    reply = await _get_xql_results(fetcher, str(execution_id), limit=limit)
    status = reply.get("status", "PENDING")
    results = reply.get("results", {}) if isinstance(reply.get("results"), dict) else {}

    return {
        "status": status,
        "execution_id": execution_id,
        "results": results.get("data", []),
        "total_rows": reply.get("number_of_results", 0),
        "fields": results.get("fields", []),
        "error": reply.get("err_message") if status in ("FAIL", "FAILED") else None,
    }


# list-datasets tool.
#
# The official Cortex public docs don't expose a dedicated /datasets endpoint
# (the XSIAM-tier `datamodel` XQL stage is license-gated and returns
# "Invalid License - XSIAM" on XDR-only tenants). So this tool uses
# the empirical-probe approach: for a curated catalog of well-known
# Cortex XDR / XSIAM dataset names, run `dataset = X | limit 1` for
# each + report which exist in THIS tenant.
#
# This is actually more useful in practice than a generic schema
# list would be — it returns datasets the operator's tenant ACTUALLY
# has data in (vs. all-possible-dataset-names some of which may be
# off-tenant). The cost per call is bounded by the curated list
# size × ~1s per quick limit-1 query.
#
# Curated names sourced from:
#  - Cortex XDR Public API docs (xdr_data, endpoints, alerts, etc.)
#  - XSIAM dataset documentation (va_endpoints, va_cves,
#    host_inventory, asset_inventory, agent_auditing, etc.)
#  - Datasets observed empirically on a live tenant
#
# Adding a new dataset name = one line in _KNOWN_DATASETS.

_KNOWN_DATASETS: tuple[tuple[str, str], ...] = (
    # Core XDR telemetry
    ("xdr_data", "Process, file, network, registry, login events from XDR agents"),
    ("agent_auditing", "XDR agent self-audit events (start/stop, policy changes)"),
    # Endpoints + assets
    ("endpoints", "XDR-managed endpoints with agent installed (inventory)"),
    ("host_inventory", "Discovered hosts (XSIAM asset management)"),
    ("asset_inventory", "Broader asset management (XSIAM)"),
    # Alerts / issues / incidents (XSIAM-tier datasets)
    ("alerts", "XSIAM alerts — flat legacy schema with alert_id, severity, host_name, etc."),
    ("issues", "XSIAM issues — XDM-normalized nested schema (xdm.issue.*); parallel to alerts"),
    ("incidents", "XSIAM incident records aggregating related alerts"),
    # Vulnerability assessment
    ("va_endpoints", "Vulnerability-assessed endpoints (XSIAM VA module)"),
    ("va_cves", "CVE catalog with affected hosts (XSIAM VA module)"),
    # Cloud
    ("cloud_audit_logs", "Cloud provider audit logs (AWS CloudTrail, GCP Audit, Azure)"),
    ("cloud_users", "Cloud identity provider users"),
    # Performance
    ("metrics_source", "Broker / collector performance metrics"),
    # Vendor integrations (typically not present on basic-XDR tenants)
    ("panw_ngfw_traffic_raw", "Palo Alto NGFW traffic logs (requires NGFW integration)"),
    ("panw_ngfw_url_raw", "Palo Alto NGFW URL filtering logs"),
    ("panw_ngfw_threat_raw", "Palo Alto NGFW threat logs"),
    ("microsoft_windows_raw", "Windows event log (requires Windows event collector)"),
    ("symantec_endpoint_protection_raw", "Symantec EP alerts (requires Symantec integration)"),
    ("cef_raw", "Generic CEF-format logs"),
    ("syslog_raw", "Generic syslog logs"),
)


@_wrap_xdr_call
async def list_datasets(include_empty: bool = True, probe_timeout_s: int = 10) -> dict:
    """List XQL datasets that exist in this XDR tenant.

    Empirical probe: tries `dataset = X | limit 1` for each
    well-known dataset name + reports which exist with data. Faster
    than running counts; bounded by len(_KNOWN_DATASETS) queries.

    Use this when:
      - You're building an XQL query and want to confirm the target
        dataset exists before constructing the full query body.
      - The user asked a vague question ("show me logs") and you
        need to enumerate what data sources are available.
      - You hit an HTTP 500 on a query and want to verify the
        dataset is present (vs. a tenant-config gap — Pattern A
        of the build_xql_query skill).

    Args:
        include_empty:  When true (default), include datasets that
                       returned SUCCESS but with 0 sample rows
                       (the dataset exists but is empty in the
                       default 24h timeframe). Set false to filter
                       to data-bearing datasets only.
        probe_timeout_s: Per-probe deadline. Default 10s. Probes
                       run sequentially (not parallel) to avoid
                       burning XDR's per-query quota.

    Returns:
        {ok, datasets: [{name, description, exists, row_count,
                         sample_field_count, error}], probed: N}.
    """
    catalog: list[dict] = []
    fetcher = _get_fetcher()

    for name, description in _KNOWN_DATASETS:
        entry: dict = {
            "name": name,
            "description": description,
            "exists": False,
        }
        try:
            execution_id = await _start_xql_query(
                fetcher,
                f"dataset = {name} | limit 1",
                None, None, None,
            )
            # Poll briefly. Most probes complete in <2s.
            poll_start = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - poll_start > probe_timeout_s:
                    entry["error"] = "probe timeout"
                    break
                await asyncio.sleep(0.5)
                reply = await _get_xql_results(fetcher, execution_id, limit=1)
                status = reply.get("status", "PENDING")
                if status == "SUCCESS":
                    entry["exists"] = True
                    results = reply.get("results") or {}
                    if isinstance(results, dict):
                        data = results.get("data") or []
                        entry["row_count_sample"] = len(data)
                        if data and isinstance(data[0], dict):
                            entry["sample_field_count"] = len(data[0])
                    break
                if status in ("FAIL", "FAILED", "CANCELLED", "TIMEOUT"):
                    err = reply.get("err_message") or reply.get("error") or status
                    # The hallmark "dataset doesn't exist" error from
                    # XDR: 500 with "Invalid License - XSIAM" or
                    # "An unexpected error occurred by XDR public API".
                    # Either way → mark MISSING.
                    entry["error"] = str(err)[:200]
                    break
                # else PENDING — keep polling
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"probe error: {str(exc)[:200]}"
        catalog.append(entry)

    if not include_empty:
        catalog = [e for e in catalog if e.get("exists")]

    return {
        "datasets": catalog,
        "probed": len(_KNOWN_DATASETS),
        "found": sum(1 for e in catalog if e.get("exists")),
    }


# ───────────────────────────────────────────────────────────────────
# Extended tool surface
# ───────────────────────────────────────────────────────────────────
#
# This block extends the original hand-coded tools to the
# full ebarti-derived surface. Conventions:
#   1. Tool functions follow the `xdr_<category>_<action>` naming.
#      Bare names are bound at registration via __all__ + the
#      connector-runtime's prefix-strip logic.
#   2. Six aliases point at the original names so existing operator
#      workflows keep working. Aliases live
#      in connector.yaml `spec.tools[]` — Python doesn't need to
#      duplicate them because the connector-runtime registers by tool
#      name. The original function names stay as the canonical
#      implementations; the new names are thin wrappers.
#   3. Four tools have no original counterpart: incidents_update,
#      alerts_update, ioc_disable, ioc_enable.
#   4. Wrapped via _wrap_xdr_call for shared error handling.


# ─── Aliases for the new naming convention (renames) ─────────────


@_wrap_xdr_call
async def xdr_incidents_list(
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    endpoint: Optional[str] = None,
    severity: Optional[list[str]] = None,
    status: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> dict:
    """Alias of get_cases_and_issues. List Cortex XDR incidents."""
    return await get_cases_and_issues(
        from_time=from_time,
        to_time=to_time,
        endpoint=endpoint,
        severity=severity,
        status=status,
        limit=limit,
    )


@_wrap_xdr_call
async def xdr_incidents_get_extra_data(
    incident_id: str,
    alerts_limit: int = 50,
) -> dict:
    """Alias of get_incident_extra_data."""
    return await get_incident_extra_data(
        incident_id=incident_id,
        alerts_limit=alerts_limit,
    )


@_wrap_xdr_call
async def xdr_alerts_list(
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    endpoint: Optional[str] = None,
    severity: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> dict:
    """Alias of get_alerts. List Cortex XDR alerts."""
    return await get_alerts(
        from_time=from_time,
        to_time=to_time,
        endpoint=endpoint,
        severity=severity,
        limit=limit,
    )


@_wrap_xdr_call
async def xdr_xql_run_query(
    query: str,
    tenant_ids: Optional[list[str]] = None,
    timeframe_from: Optional[str] = None,
    timeframe_to: Optional[str] = None,
) -> dict:
    """Alias of run_xql_query."""
    return await run_xql_query(
        query=query,
        tenant_ids=tenant_ids,
        timeframe_from=timeframe_from,
        timeframe_to=timeframe_to,
    )


@_wrap_xdr_call
async def xdr_xql_get_results(
    execution_id: str,
    limit: Optional[int] = None,
) -> dict:
    """Alias of get_xql_results."""
    return await get_xql_results(
        execution_id=execution_id,
        limit=limit,
    )


@_wrap_xdr_call
async def xdr_xql_list_datasets(
    include_empty: bool = True,
    probe_timeout_s: int = 10,
) -> dict:
    """Alias of list_datasets."""
    return await list_datasets(
        include_empty=include_empty,
        probe_timeout_s=probe_timeout_s,
    )


# ─── New tools — incidents.update + alerts.update ────────────────


@_wrap_xdr_call
async def xdr_incidents_update(
    incident_id: str,
    update_data: dict,
) -> dict:
    """Update an XDR incident's metadata.

    Mutable fields the XDR API accepts (per the ebarti reference + the
    public-API docs link in data/knowledge/external/.../incidents/update.md):

      - assigned_user_mail (str)
      - assigned_user_pretty_name (str)
      - manual_severity (str: "low" | "medium" | "high" | "critical")
      - manual_description (str)
      - status (str): one of
          new / under_investigation / resolved_threat_handled /
          resolved_known_issue / resolved_duplicate /
          resolved_false_positive / resolved_other
      - resolve_comment (str)

    Args:
        incident_id: The XDR incident id (string, from xdr_incidents_list).
        update_data: Dict of {field: value} for the fields above. Only the
            fields present in this dict are sent; XDR leaves the rest
            untouched.

    Returns:
        {ok: True, incident_id, updated: bool} on success.
    """
    if not incident_id:
        return _err("incident_id is required")
    if not isinstance(update_data, dict) or not update_data:
        return _err("update_data must be a non-empty dict")

    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "incident_id": incident_id,
            "update_data": update_data,
        }
    }
    await fetcher.post("/public_api/v1/incidents/update_incident/", body)
    return _ok({
        "incident_id": incident_id,
        "updated": True,
    })


@_wrap_xdr_call
async def xdr_alerts_update(
    alert_id_list: list[str],
    update_data: dict,
) -> dict:
    """Bulk-update one or more alerts.

    Args:
        alert_id_list: List of alert IDs to apply the same update to.
        update_data: Dict of {field: value}. Common fields:
            - severity (str): low / medium / high / critical
            - status (str): new / under_investigation / resolved
            - resolve_comment (str)
            - assigned_user (str)

    Returns:
        {ok: True, updated_count, alert_id_list}.
    """
    if not alert_id_list or not isinstance(alert_id_list, list):
        return _err("alert_id_list must be a non-empty list of strings")
    if not isinstance(update_data, dict) or not update_data:
        return _err("update_data must be a non-empty dict")

    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "alert_id_list": alert_id_list,
            "update_data": update_data,
        }
    }
    await fetcher.post("/public_api/v1/alerts/update_alerts/", body)
    return _ok({
        "updated_count": len(alert_id_list),
        "alert_id_list": alert_id_list,
    })


# ─── New tools — IoC management ───────────────────────────────────


@_wrap_xdr_call
async def xdr_ioc_insert_json(
    indicators: list[dict],
    validate: bool = True,
) -> dict:
    """Upload IoCs (indicators of compromise) as JSON.

    Args:
        indicators: List of IoC dicts. Each dict requires:
            - indicator (str): the IoC value (IPv4, domain, hash, URL)
            - type (str): "IP" | "DOMAIN_NAME" | "HASH" | "FILENAME" | ...
            - severity (str): "informational" | "low" | "medium" | "high" | "critical"
            - reputation (str): "GOOD" | "SUSPICIOUS" | "BAD"
          Optional: vendors[], comment, expiration_date.
        validate: If True (default), XDR validates each indicator's
            format before insertion; bad entries are reported as errors.

    Returns:
        {ok: True, inserted_count, errors: [...]}

    Use when the operator pastes a list of IoCs from a threat-intel
    feed and wants them blocking/alerting at the EDR layer.
    """
    if not indicators or not isinstance(indicators, list):
        return _err("indicators must be a non-empty list of IoC dicts")

    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "validate": validate,
            "indicators": indicators,
        }
    }
    resp = await fetcher.post("/public_api/v1/indicators/insert_jsons/", body)
    return _ok({
        "inserted_count": len(indicators),
        "errors": (resp.get("reply") or {}).get("errors") or [],
    })


@_wrap_xdr_call
async def xdr_ioc_disable(indicators: list[str]) -> dict:
    """Disable one or more IoCs (don't alert/block on them anymore).

    Args:
        indicators: List of IoC values (NOT IDs — the original
            indicator strings, e.g. ["malicious.example.com", "1.2.3.4"]).

    Returns:
        {ok: True, disabled_count}.
    """
    if not indicators or not isinstance(indicators, list):
        return _err("indicators must be a non-empty list of IoC value strings")

    fetcher = _get_fetcher()
    body = {"request_data": {"indicators": indicators}}
    await fetcher.post("/public_api/v1/indicators/disable_iocs/", body)
    return _ok({
        "disabled_count": len(indicators),
        "indicators": indicators,
    })


@_wrap_xdr_call
async def xdr_ioc_enable(indicators: list[str]) -> dict:
    """Re-enable previously disabled IoCs.

    Args:
        indicators: List of IoC value strings (mirrors xdr_ioc_disable).

    Returns:
        {ok: True, enabled_count}.
    """
    if not indicators or not isinstance(indicators, list):
        return _err("indicators must be a non-empty list of IoC value strings")

    fetcher = _get_fetcher()
    body = {"request_data": {"indicators": indicators}}
    await fetcher.post("/public_api/v1/indicators/enable_iocs/", body)
    return _ok({
        "enabled_count": len(indicators),
        "indicators": indicators,
    })


# ─── New tools — File download ────────────────────────────────────


@_wrap_xdr_call
async def xdr_download_file(file_link: str) -> dict:
    """Download a file that XDR previously made available via a retrieval action.

    Companion to xdr_endpoints_retrieve_file — once a file-
    retrieval action completes, XDR returns a download URL via
    xdr_response_get_file_retrieval_details. Pass that URL here and the
    bytes are streamed back as base64.

    Args:
        file_link: The fully-qualified file_link string from the
            retrieval-details response. Should match the XDR tenant's
            FQDN; the connector refuses URLs from other hosts.

    Returns:
        {ok: True, file_link, size_bytes, content_b64} or
        {ok: False, error: "..."}.

    Use when the operator says "pull the quarantine file from endpoint X
    for analysis" — chain after xdr_endpoints_retrieve_file +
    xdr_response_get_file_retrieval_details.
    """
    if not file_link or not isinstance(file_link, str):
        return _err("file_link must be a non-empty string")
    # Defensive — refuse URLs not pointing at the configured tenant FQDN
    cfg = _get_xdr_config()
    api_url = cfg.get("api_url", "")
    if api_url and not file_link.startswith(api_url.rstrip("/")):
        return _err(
            "file_link does not match configured XDR tenant",
            api_url=api_url,
            file_link_prefix=file_link[:60],
        )

    fetcher = _get_fetcher()
    # XDR's download endpoint returns the raw bytes (not a JSON envelope).
    # We base64-encode for transport back to the agent.
    import base64

    raw_bytes = await fetcher.get_bytes(file_link)
    return _ok({
        "file_link": file_link,
        "size_bytes": len(raw_bytes),
        "content_b64": base64.b64encode(raw_bytes).decode("ascii"),
    })


# ───────────────────────────────────────────────────────────────────
# Endpoints + response + scripts (18 tools)
# ───────────────────────────────────────────────────────────────────
#
# Tools that exercise the XDR "Response" surface — listing endpoints,
# isolate/unisolate/scan/quarantine actions, file retrieval, and the
# scripts library. Each tool follows the same pattern: build a request
# body, POST via Fetcher, wrap the response.
#
# Endpoint filter pattern (per XDR docs): {filters: [{field, operator,
# value}, ...]} where operator is one of in / contains / gte / lte /
# eq / neq. Helper `_build_endpoint_filters` constructs this from the
# operator-friendly named args.


def _build_endpoint_filters(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    first_seen: Optional[int] = None,
    after_first_seen: bool = False,
    last_seen: Optional[int] = None,
    after_last_seen: bool = False,
    ip_list: Optional[list[str]] = None,
    group_name: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    alias: Optional[list[str]] = None,
    isolate: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
) -> list[dict]:
    """Compose the XDR endpoint-filter array from operator-friendly kwargs.

    Each filter is {field, operator, value}. Multiple filters AND together.
    """
    filters: list[dict] = []
    if endpoint_id_list:
        filters.append({"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list})
    if dist_name:
        filters.append({"field": "dist_name", "operator": "in", "value": dist_name})
    if first_seen is not None:
        filters.append({
            "field": "first_seen",
            "operator": "gte" if after_first_seen else "lte",
            "value": first_seen,
        })
    if last_seen is not None:
        filters.append({
            "field": "last_seen",
            "operator": "gte" if after_last_seen else "lte",
            "value": last_seen,
        })
    if ip_list:
        filters.append({"field": "ip_list", "operator": "in", "value": ip_list})
    if group_name:
        filters.append({"field": "group_name", "operator": "in", "value": group_name})
    if platform:
        filters.append({"field": "platform", "operator": "in", "value": platform})
    if alias:
        filters.append({"field": "alias", "operator": "in", "value": alias})
    if isolate:
        filters.append({"field": "isolate", "operator": "in", "value": isolate})
    if hostname:
        filters.append({"field": "hostname", "operator": "in", "value": hostname})
    return filters


# ─── Endpoints management ────────────────────────────────────────


@_wrap_xdr_call
async def xdr_endpoints_list_all() -> dict:
    """List ALL XDR endpoints (no filters). Higher-volume than xdr_endpoints_get.

    Returns:
        {ok, endpoints: [...], total}
    """
    fetcher = _get_fetcher()
    resp = await fetcher.post("/public_api/v1/endpoints/get_endpoints/", {"request_data": {}})
    endpoints = (resp.get("reply") or {}).get("endpoints") or resp.get("reply") or []
    return _ok({
        "endpoints": endpoints,
        "total": len(endpoints) if isinstance(endpoints, list) else 0,
    })


@_wrap_xdr_call
async def xdr_endpoints_get(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None,
    group_name: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    alias: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
    isolate: Optional[list[str]] = None,
) -> dict:
    """Get filtered endpoints. Use any subset of the filters; they AND together.

    Common operator workflows:
      - "List isolated endpoints" → isolate=["isolated"]
      - "Show Windows endpoints" → platform=["windows"]
      - "Find machine with hostname x" → hostname=["x"]

    Args:
        endpoint_id_list: Specific endpoint IDs to match.
        dist_name: Distribution list names.
        ip_list: IPv4/IPv6 addresses to match.
        group_name: Endpoint group names.
        platform: ["windows" | "linux" | "macos"].
        alias: Custom aliases.
        hostname: Endpoint hostnames.
        isolate: Isolation status filter ("isolated" | "unisolated").

    Returns:
        {ok, endpoints: [...], total}
    """
    fetcher = _get_fetcher()
    filters = _build_endpoint_filters(
        endpoint_id_list=endpoint_id_list, dist_name=dist_name, ip_list=ip_list,
        group_name=group_name, platform=platform, alias=alias,
        hostname=hostname, isolate=isolate,
    )
    body = {"request_data": {"filters": filters} if filters else {}}
    resp = await fetcher.post("/public_api/v1/endpoints/get_endpoint/", body)
    endpoints = (resp.get("reply") or {}).get("endpoints") or []
    return _ok({"endpoints": endpoints, "total": len(endpoints)})


@_wrap_xdr_call
async def xdr_endpoints_isolate(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
) -> dict:
    """Isolate one or more endpoints from the network. Up to 1000 per request.

    Returns:
        {ok, action_id, endpoints_affected}.
    """
    fetcher = _get_fetcher()
    filters = _build_endpoint_filters(
        endpoint_id_list=endpoint_id_list, dist_name=dist_name, ip_list=ip_list,
        platform=platform, hostname=hostname,
    )
    if not filters:
        return _err("at least one filter required to specify which endpoints to isolate")
    body = {"request_data": {"filters": filters}}
    resp = await fetcher.post("/public_api/v1/endpoints/isolate/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": reply.get("action_id"),
        "endpoints_affected": reply.get("endpoints_count", 0),
    })


@_wrap_xdr_call
async def xdr_endpoints_unisolate(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
) -> dict:
    """Unisolate one or more endpoints (restore network connectivity)."""
    fetcher = _get_fetcher()
    filters = _build_endpoint_filters(
        endpoint_id_list=endpoint_id_list, dist_name=dist_name, ip_list=ip_list,
        platform=platform, hostname=hostname,
    )
    if not filters:
        return _err("at least one filter required to specify which endpoints to unisolate")
    body = {"request_data": {"filters": filters}}
    resp = await fetcher.post("/public_api/v1/endpoints/unisolate/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": reply.get("action_id"),
        "endpoints_affected": reply.get("endpoints_count", 0),
    })


@_wrap_xdr_call
async def xdr_endpoints_scan(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
) -> dict:
    """Trigger a scan on the matching endpoints."""
    fetcher = _get_fetcher()
    filters = _build_endpoint_filters(
        endpoint_id_list=endpoint_id_list, dist_name=dist_name, ip_list=ip_list,
        platform=platform, hostname=hostname,
    )
    if not filters:
        return _err("at least one filter required to specify which endpoints to scan")
    body = {"request_data": {"filters": filters}}
    resp = await fetcher.post("/public_api/v1/endpoints/scan/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": reply.get("action_id"),
        "endpoints_affected": reply.get("endpoints_count", 0),
    })


@_wrap_xdr_call
async def xdr_endpoints_scan_all() -> dict:
    """Trigger a scan on EVERY endpoint in the tenant. High-impact — confirm intent."""
    fetcher = _get_fetcher()
    body = {"request_data": {"filters": []}}
    resp = await fetcher.post("/public_api/v1/endpoints/scan/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": reply.get("action_id"),
    })


@_wrap_xdr_call
async def xdr_endpoints_set_alias(
    endpoint_id_list: list[str],
    alias_name: str,
) -> dict:
    """Set or change the alias (operator-friendly name) for one or more endpoints."""
    if not endpoint_id_list:
        return _err("endpoint_id_list is required")
    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
            "alias": alias_name,
        }
    }
    await fetcher.post("/public_api/v1/endpoints/update_agent_name/", body)
    return _ok({"endpoint_id_list": endpoint_id_list, "alias_name": alias_name})


@_wrap_xdr_call
async def xdr_endpoints_retrieve_file(
    endpoint_id_list: list[str],
    files: dict,
) -> dict:
    """Retrieve files from one or more endpoints. Up to 20 files, 100 endpoints.

    Args:
        endpoint_id_list: Which endpoints to pull files from.
        files: Per-platform file-path dict, e.g.:
            { "windows": ["C:\\path\\to\\file"],
              "linux":   ["/var/log/auth.log"],
              "macos":   ["/Users/x/Documents/y"] }

    Returns:
        {ok, action_id} — poll xdr_response_get_file_retrieval_details for status.
    """
    if not endpoint_id_list:
        return _err("endpoint_id_list is required")
    if not files or not isinstance(files, dict):
        return _err("files dict required (keys: windows / linux / macos)")
    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
            "files": files,
        }
    }
    resp = await fetcher.post("/public_api/v1/endpoints/file_retrieval/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": reply.get("action_id"),
        "endpoints_count": reply.get("endpoints_count", 0),
    })


@_wrap_xdr_call
async def xdr_endpoints_quarantine_file(
    endpoint_id_list: list[str],
    file_path: str,
    file_hash: str,
) -> dict:
    """Quarantine a specific file across one or more endpoints.

    Args:
        endpoint_id_list: Which endpoints.
        file_path: Absolute path of the file.
        file_hash: SHA-256 of the file (defense-in-depth — XDR verifies before quarantining).

    Returns:
        {ok, action_id}.
    """
    if not endpoint_id_list:
        return _err("endpoint_id_list is required")
    if not file_path or not file_hash:
        return _err("file_path and file_hash are required")
    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
            "file_path": file_path,
            "file_hash": file_hash,
        }
    }
    resp = await fetcher.post("/public_api/v1/endpoints/quarantine/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": reply.get("action_id"),
        "file_path": file_path,
    })


# ─── Response action status ───────────────────────────────────────


@_wrap_xdr_call
async def xdr_response_get_action_status(action_id: str) -> dict:
    """Get the status of any action (isolate / unisolate / scan / quarantine / etc.).

    Args:
        action_id: Returned by any of the action tools above.

    Returns:
        {ok, action_id, status: {endpoint_id: "COMPLETED" | "PENDING" | "FAILED"}}
    """
    if not action_id:
        return _err("action_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"group_action_id": action_id}}
    resp = await fetcher.post("/public_api/v1/actions/get_action_status/", body)
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": action_id,
        "status_per_endpoint": reply.get("data", {}),
    })


@_wrap_xdr_call
async def xdr_response_get_file_retrieval_details(action_id: str) -> dict:
    """Get download URLs for a completed file_retrieval action.

    Args:
        action_id: From xdr_endpoints_retrieve_file.

    Returns:
        {ok, files: [{endpoint_id, file_link, file_path}, ...]} — pipe each
        `file_link` to xdr_download_file to pull the bytes.
    """
    if not action_id:
        return _err("action_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"group_action_id": action_id}}
    resp = await fetcher.post("/public_api/v1/actions/file_retrieval_details/", body)
    reply = resp.get("reply") or {}
    return _ok({"action_id": action_id, "files": reply.get("data", [])})


# ─── Scripts library ─────────────────────────────────────────────


@_wrap_xdr_call
async def xdr_scripts_list(
    name: Optional[list[str]] = None,
    description: Optional[list[str]] = None,
    created_by: Optional[list[str]] = None,
    windows_supported: Optional[bool] = None,
    linux_supported: Optional[bool] = None,
    macos_supported: Optional[bool] = None,
) -> dict:
    """List scripts in the XDR script library. Filters AND together."""
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if name:
        filters.append({"field": "name", "operator": "in", "value": name})
    if description:
        filters.append({"field": "description", "operator": "in", "value": description})
    if created_by:
        filters.append({"field": "created_by", "operator": "in", "value": created_by})
    if windows_supported is not None:
        filters.append({"field": "windows_supported", "operator": "eq", "value": windows_supported})
    if linux_supported is not None:
        filters.append({"field": "linux_supported", "operator": "eq", "value": linux_supported})
    if macos_supported is not None:
        filters.append({"field": "macos_supported", "operator": "eq", "value": macos_supported})
    body = {"request_data": {"filters": filters} if filters else {}}
    resp = await fetcher.post("/public_api/v1/scripts/get_scripts/", body)
    reply = resp.get("reply") or {}
    scripts = reply.get("scripts") or reply if isinstance(reply, list) else []
    return _ok({"scripts": scripts})


@_wrap_xdr_call
async def xdr_scripts_get_metadata(script_uid: str) -> dict:
    """Get the full definition of one script (parameters, source, supported platforms)."""
    if not script_uid:
        return _err("script_uid is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"script_uid": script_uid}}
    resp = await fetcher.post("/public_api/v1/scripts/get_script_metadata/", body)
    return _ok({"script": (resp.get("reply") or {}).get("script")})


@_wrap_xdr_call
async def xdr_scripts_run_script(
    script_uid: str,
    endpoint_id_list: list[str],
    parameters_values: Optional[dict] = None,
    timeout: int = 600,
) -> dict:
    """Run a script from the library on one or more endpoints.

    Args:
        script_uid: From xdr_scripts_list.
        endpoint_id_list: Which endpoints to run on.
        parameters_values: Script-specific parameters (key/value pairs).
        timeout: Seconds before XDR considers the script timed out (default 600).

    Returns:
        {ok, action_id} — poll xdr_scripts_get_execution_status.
    """
    if not script_uid or not endpoint_id_list:
        return _err("script_uid and endpoint_id_list are required")
    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "script_uid": script_uid,
            "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
            "parameters_values": parameters_values or {},
            "timeout": timeout,
        }
    }
    resp = await fetcher.post("/public_api/v1/scripts/run_script/", body)
    reply = resp.get("reply") or {}
    return _ok({"action_id": reply.get("action_id")})


@_wrap_xdr_call
async def xdr_scripts_run_snippet(
    snippet_code: str,
    endpoint_id_list: list[str],
    timeout: int = 600,
) -> dict:
    """Run an ad-hoc PowerShell/bash/Python snippet on endpoints (no library entry).

    Args:
        snippet_code: The script text. Platform is inferred from the endpoints' OS.
        endpoint_id_list: Targets.
        timeout: Seconds before timeout (default 600).

    Returns:
        {ok, action_id}.
    """
    if not snippet_code or not endpoint_id_list:
        return _err("snippet_code and endpoint_id_list are required")
    fetcher = _get_fetcher()
    body = {
        "request_data": {
            "snippet_code": snippet_code,
            "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
            "timeout": timeout,
        }
    }
    resp = await fetcher.post("/public_api/v1/scripts/run_snippet_code_script/", body)
    reply = resp.get("reply") or {}
    return _ok({"action_id": reply.get("action_id")})


@_wrap_xdr_call
async def xdr_scripts_get_execution_status(action_id: str) -> dict:
    """Poll the status of a script-execution action."""
    if not action_id:
        return _err("action_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"action_id": action_id}}
    resp = await fetcher.post("/public_api/v1/scripts/get_script_execution_status/", body)
    reply = resp.get("reply") or {}
    return _ok({"action_id": action_id, "status_per_endpoint": reply})


@_wrap_xdr_call
async def xdr_scripts_get_execution_results(action_id: str) -> dict:
    """Pull the OUTPUT (stdout / structured result) of a completed script execution."""
    if not action_id:
        return _err("action_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"action_id": action_id}}
    resp = await fetcher.post("/public_api/v1/scripts/get_script_execution_results/", body)
    reply = resp.get("reply") or {}
    return _ok({"action_id": action_id, "results": reply})


@_wrap_xdr_call
async def xdr_scripts_get_execution_result_files(
    action_id: int,
    endpoint_id: int,
) -> dict:
    """Retrieve any files a script execution produced on a specific endpoint."""
    if not action_id or not endpoint_id:
        return _err("action_id and endpoint_id are required")
    fetcher = _get_fetcher()
    body = {"request_data": {"action_id": action_id, "endpoint_id": endpoint_id}}
    resp = await fetcher.post(
        "/public_api/v1/scripts/get_script_execution_result_files/", body
    )
    reply = resp.get("reply") or {}
    return _ok({
        "action_id": action_id,
        "endpoint_id": endpoint_id,
        "file_link": reply.get("DATA"),
    })


# ───────────────────────────────────────────────────────────────────
# Admin endpoints (15 tools)
# ───────────────────────────────────────────────────────────────────
#
# Audit logs, asset inventory, distribution-list management, alert
# exclusions, hash analytics + blocklist, exploits.
#
# Hand-authored from public XDR API knowledge — NOT from ebarti, which
# doesn't cover these categories. Paths + body shapes mirror the
# /public_api/v1/<category>/<action>/ pattern + request_data envelope
# used by the rest of the XDR API. Validate each against a real XDR
# tenant; any divergence from the docs should be fixed here.


# ─── Audit logs ──────────────────────────────────────────────────


@_wrap_xdr_call
async def xdr_audit_list_management_logs(
    audit_owner_email: Optional[list[str]] = None,
    audit_asset_type: Optional[list[str]] = None,
    audit_severity: Optional[list[str]] = None,
    audit_result: Optional[list[str]] = None,
    timestamp_gte: Optional[int] = None,
    timestamp_lte: Optional[int] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List management-actions audit log entries (who did what in the XDR console).

    Args follow the standard XDR filter pattern.

    Filter values for audit_severity: SEV_010_INFO, SEV_020_LOW, SEV_030_MEDIUM, SEV_040_HIGH.
    Filter values for audit_result: SUCCESS, FAIL, PARTIAL.
    """
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if audit_owner_email:
        filters.append({"field": "audit_owner_email", "operator": "in", "value": audit_owner_email})
    if audit_asset_type:
        filters.append({"field": "audit_asset_type", "operator": "in", "value": audit_asset_type})
    if audit_severity:
        filters.append({"field": "audit_severity", "operator": "in", "value": audit_severity})
    if audit_result:
        filters.append({"field": "audit_result", "operator": "in", "value": audit_result})
    if timestamp_gte is not None:
        filters.append({"field": "timestamp", "operator": "gte", "value": timestamp_gte})
    if timestamp_lte is not None:
        filters.append({"field": "timestamp", "operator": "lte", "value": timestamp_lte})
    body = {
        "request_data": {
            "filters": filters,
            "search_from": search_from,
            "search_to": search_to,
        }
    }
    resp = await fetcher.post("/public_api/v1/audits/management_logs/", body)
    return _ok({"audit_entries": (resp.get("reply") or {}).get("data", [])})


@_wrap_xdr_call
async def xdr_audit_list_agent_logs(
    endpoint_ids: Optional[list[str]] = None,
    endpoint_names: Optional[list[str]] = None,
    type_: Optional[list[str]] = None,
    sub_type: Optional[list[str]] = None,
    result: Optional[list[str]] = None,
    timestamp_gte: Optional[int] = None,
    timestamp_lte: Optional[int] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List per-agent audit log entries (what each XDR agent did).

    Use to investigate what an agent reported around an incident.
    """
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if endpoint_ids:
        filters.append({"field": "endpoint_id", "operator": "in", "value": endpoint_ids})
    if endpoint_names:
        filters.append({"field": "endpoint_name", "operator": "in", "value": endpoint_names})
    if type_:
        filters.append({"field": "type", "operator": "in", "value": type_})
    if sub_type:
        filters.append({"field": "sub_type", "operator": "in", "value": sub_type})
    if result:
        filters.append({"field": "result", "operator": "in", "value": result})
    if timestamp_gte is not None:
        filters.append({"field": "timestamp", "operator": "gte", "value": timestamp_gte})
    if timestamp_lte is not None:
        filters.append({"field": "timestamp", "operator": "lte", "value": timestamp_lte})
    body = {
        "request_data": {
            "filters": filters,
            "search_from": search_from,
            "search_to": search_to,
        }
    }
    resp = await fetcher.post("/public_api/v1/audits/agents_reports/", body)
    return _ok({"audit_entries": (resp.get("reply") or {}).get("data", [])})


# ─── Asset management ────────────────────────────────────────────


@_wrap_xdr_call
async def xdr_assets_list(
    asset_type: Optional[list[str]] = None,
    risk_level: Optional[list[str]] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List assets (endpoints + cloud assets + users) tracked by XDR's asset inventory.

    asset_type values: ENDPOINT, USER, CLOUD_INSTANCE, CONTAINER.
    risk_level values: LOW, MEDIUM, HIGH, CRITICAL.
    """
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if asset_type:
        filters.append({"field": "type", "operator": "in", "value": asset_type})
    if risk_level:
        filters.append({"field": "risk_level", "operator": "in", "value": risk_level})
    body = {
        "request_data": {
            "filters": filters,
            "search_from": search_from,
            "search_to": search_to,
        }
    }
    resp = await fetcher.post("/public_api/v1/assets/get_assets/", body)
    return _ok({"assets": (resp.get("reply") or {}).get("assets", [])})


@_wrap_xdr_call
async def xdr_assets_get(asset_id: str) -> dict:
    """Get full details of one asset (its risk score, attributes, related events)."""
    if not asset_id:
        return _err("asset_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"asset_id": asset_id}}
    resp = await fetcher.post("/public_api/v1/assets/get_asset/", body)
    return _ok({"asset": (resp.get("reply") or {}).get("asset")})


# ─── Distribution list management ────────────────────────────────


@_wrap_xdr_call
async def xdr_distribution_list() -> dict:
    """List XDR distribution lists (agent install URL/installer collections)."""
    fetcher = _get_fetcher()
    body = {"request_data": {}}
    resp = await fetcher.post("/public_api/v1/distributions/get_distributions/", body)
    return _ok({
        "distributions": (resp.get("reply") or {}).get("distributions", []),
    })


@_wrap_xdr_call
async def xdr_distribution_create(
    name: str,
    platform: str,
    package_type: str = "standalone",
    agent_version: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Create a new XDR distribution list (installer bundle).

    Args:
        name: Distribution display name.
        platform: "windows" | "linux" | "macos" | "android".
        package_type: "standalone" | "upgrade" (default standalone).
        agent_version: Specific agent version (default = latest GA).
        description: Operator notes.
    """
    if not name or not platform:
        return _err("name and platform are required")
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {
        "name": name,
        "platform": platform,
        "package_type": package_type,
    }
    if agent_version:
        rd["agent_version"] = agent_version
    if description:
        rd["description"] = description
    body = {"request_data": rd}
    resp = await fetcher.post("/public_api/v1/distributions/create/", body)
    return _ok({
        "distribution_id": (resp.get("reply") or {}).get("distribution_id"),
    })


@_wrap_xdr_call
async def xdr_distribution_get_url(distribution_id: str) -> dict:
    """Return the installer download URL for a distribution."""
    if not distribution_id:
        return _err("distribution_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"distribution_id": distribution_id, "package_type": "standalone"}}
    resp = await fetcher.post("/public_api/v1/distributions/get_dist_url/", body)
    return _ok({"download_url": (resp.get("reply") or {}).get("distribution_url")})


@_wrap_xdr_call
async def xdr_distribution_versions() -> dict:
    """List available XDR agent versions per platform (for use in distribution_create)."""
    fetcher = _get_fetcher()
    body = {"request_data": {}}
    resp = await fetcher.post("/public_api/v1/distributions/get_versions/", body)
    return _ok({"versions": resp.get("reply") or {}})


# ─── Alert exclusions ────────────────────────────────────────────


@_wrap_xdr_call
async def xdr_alert_exclusions_list(
    tenant_id: Optional[str] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List alert exclusions (rules that suppress specific alerts from showing)."""
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"search_from": search_from, "search_to": search_to}
    if tenant_id:
        rd["tenant_id"] = tenant_id
    body = {"request_data": rd}
    resp = await fetcher.post("/public_api/v1/alerts_exclusion/get_alert_exclusion/", body)
    return _ok({"exclusions": (resp.get("reply") or {}).get("alert_exclusions", [])})


@_wrap_xdr_call
async def xdr_alert_exclusions_create(
    name: str,
    filter_expression: dict,
    comment: Optional[str] = None,
) -> dict:
    """Create a new alert-exclusion rule.

    Args:
        name: Operator-readable name for the exclusion.
        filter_expression: XDR alert-filter dict (field/operator/value triples).
            See /public_api/v1/alerts/get_alerts_multi_events for the field
            namespace. Example:
                {"AND": [{"SEARCH_FIELD": "alert_name", "SEARCH_TYPE": "EQ",
                          "SEARCH_VALUE": "Some Noisy Alert"}]}
        comment: Description / context.
    """
    if not name or not filter_expression:
        return _err("name and filter_expression are required")
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"name": name, "filterData": filter_expression}
    if comment:
        rd["comment"] = comment
    body = {"request_data": rd}
    resp = await fetcher.post("/public_api/v1/alerts_exclusion/create_alert_exclusion/", body)
    return _ok({"exclusion_id": (resp.get("reply") or {}).get("alert_exclusion_id")})


@_wrap_xdr_call
async def xdr_alert_exclusions_delete(alert_exclusion_id: str) -> dict:
    """Delete an alert-exclusion rule by id."""
    if not alert_exclusion_id:
        return _err("alert_exclusion_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"alert_exclusion_id": alert_exclusion_id}}
    await fetcher.post("/public_api/v1/alerts_exclusion/delete_alert_exclusion/", body)
    return _ok({"alert_exclusion_id": alert_exclusion_id, "deleted": True})


# ─── Hash analytics ──────────────────────────────────────────────


@_wrap_xdr_call
async def xdr_hash_get_analytics(file_hash: str) -> dict:
    """Get analytics for a file hash — XDR's per-tenant intelligence on the hash."""
    if not file_hash:
        return _err("file_hash is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"hash": file_hash}}
    resp = await fetcher.post("/public_api/v1/hash_exceptions/get_hash_analytics/", body)
    return _ok({"hash": file_hash, "analytics": resp.get("reply")})


@_wrap_xdr_call
async def xdr_hash_blocklist(
    file_hashes: list[str],
    comment: Optional[str] = None,
) -> dict:
    """Add file hashes to the global blocklist (XDR blocks execution).

    Args:
        file_hashes: List of SHA-256 strings.
        comment: Operator note for the blocklist entry.
    """
    if not file_hashes:
        return _err("file_hashes must be a non-empty list of SHA-256 strings")
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"hash_list": file_hashes}
    if comment:
        rd["comment"] = comment
    body = {"request_data": rd}
    await fetcher.post("/public_api/v1/hash_exceptions/blocklist/", body)
    return _ok({"blocked_count": len(file_hashes), "file_hashes": file_hashes})


# ─── Exploits ────────────────────────────────────────────────────


@_wrap_xdr_call
async def xdr_exploits_list(
    endpoint_id_list: Optional[list[str]] = None,
    cve_id: Optional[list[str]] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List exploits XDR has detected/mitigated. Optionally filter by endpoint or CVE."""
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if endpoint_id_list:
        filters.append({"field": "endpoint_id", "operator": "in", "value": endpoint_id_list})
    if cve_id:
        filters.append({"field": "cve_id", "operator": "in", "value": cve_id})
    body = {
        "request_data": {
            "filters": filters,
            "search_from": search_from,
            "search_to": search_to,
        }
    }
    resp = await fetcher.post("/public_api/v1/exploits/get_exploits/", body)
    return _ok({"exploits": (resp.get("reply") or {}).get("exploits", [])})


@_wrap_xdr_call
async def xdr_exploits_get_details(exploit_id: str) -> dict:
    """Full details of one exploit detection (process chain, registry, files, network)."""
    if not exploit_id:
        return _err("exploit_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"exploit_id": exploit_id}}
    resp = await fetcher.post("/public_api/v1/exploits/get_exploit_details/", body)
    return _ok({"exploit": (resp.get("reply") or {}).get("exploit")})
