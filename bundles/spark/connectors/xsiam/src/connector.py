"""XSIAM tools ported from advanced-mcp for enrichment, lookups, and XQL references."""

import asyncio
import functools
import json
import time
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastmcp import Context
from pydantic import BaseModel, Field

from ._papi_client import Fetcher
from ._xql_enrichment import (
    collect_dataset_fields,
    collect_stage_docs,
    extract_dataset,
    extract_stage_names,
)


# Explicit tool exports. Without `__all__` the runtime falls back to
# auto-discovery (logs a missing-__all__ warning; pulls Pydantic Request
# classes in along with real tools). The runtime filters non-functions in
# the fallback path, but the
# explicit-export form is deterministic and documents the public
# surface in one place.
__all__ = [
    "xsiam_run_xql_query",
    "xsiam_get_cases",
    "xsiam_send_webhook_log",
    "xsiam_add_lookup_data",
    "xsiam_get_lookup_data",
    "xsiam_remove_lookup_data",
    "xsiam_get_datasets",
    "xsiam_create_dataset",
    "xsiam_find_xql_examples_rag",
    "xsiam_get_dataset_fields",
    "xsiam_get_xql_examples",
    "xsiam_get_asset_by_id",
    "xsiam_get_assets",
    "xsiam_get_issues",

    # incidents + alerts + IoC + download
    "xsiam_incidents_list",
    "xsiam_incidents_get_extra_data",
    "xsiam_incidents_update",
    "xsiam_alerts_list",
    "xsiam_alerts_update",
    "xsiam_ioc_insert_json",
    "xsiam_ioc_disable",
    "xsiam_ioc_enable",
    "xsiam_download_file",

    # endpoints + response + scripts (18 tools)
    "xsiam_endpoints_list_all",
    "xsiam_endpoints_get",
    "xsiam_endpoints_isolate",
    "xsiam_endpoints_unisolate",
    "xsiam_endpoints_scan",
    "xsiam_endpoints_scan_all",
    "xsiam_endpoints_set_alias",
    "xsiam_endpoints_retrieve_file",
    "xsiam_endpoints_quarantine_file",
    "xsiam_response_get_action_status",
    "xsiam_response_get_file_retrieval_details",
    "xsiam_scripts_list",
    "xsiam_scripts_get_metadata",
    "xsiam_scripts_run_script",
    "xsiam_scripts_run_snippet",
    "xsiam_scripts_get_execution_status",
    "xsiam_scripts_get_execution_results",
    "xsiam_scripts_get_execution_result_files",

    # admin + XSIAM-unique (18 tools)
    "xsiam_audit_list_management_logs",
    "xsiam_audit_list_agent_logs",
    "xsiam_distribution_list",
    "xsiam_distribution_create",
    "xsiam_distribution_get_url",
    "xsiam_distribution_versions",
    "xsiam_alert_exclusions_list",
    "xsiam_alert_exclusions_create",
    "xsiam_alert_exclusions_delete",
    "xsiam_hash_get_analytics",
    "xsiam_hash_blocklist",
    "xsiam_exploits_list",
    "xsiam_exploits_get_details",
    "xsiam_parsers_list",
    "xsiam_parsers_get",
    "xsiam_datamodel_describe",
    "xsiam_broker_list",
    "xsiam_broker_get",
]


def _create_response(data: dict, is_error: bool = False) -> dict:
    if "success" not in data:
        data["success"] = not is_error
    return data


def _get_xsiam_config() -> dict:
    """Read live xsiam instance config + resolved secrets from InstanceStore.

    A live InstanceStore lookup (not env-driven settings captured once at
    boot). Single source of truth = the primary-xsiam instance edited via
    /connectors. Mirrors the xlog and caldera patterns.

    Config field names are api_url / api_id / api_key (uniform with the
    Cortex XDR connector). Legacy papiUrl / papiAuthId / papiAuthHeader
    names are still accepted on read at _get_fetcher's lookup chain, so
    existing instances keep working without migration.

    Returns the instance's merged_config dict with both non-secret
    config fields (api_url, api_id, playgroundId, webhookEndpoint)
    and resolved secret fields (api_key, webhookKey). Raises
    ValueError with operator-actionable text when no xsiam instance
    is configured.

    Uses the runtime-native `config.config.get_config()` proxy rather
    than importing `usecase.instance_store` from the agent's Python tree
    (same approach as the cortex-xdr connector). Container-mode connectors
    have no `/app/usecase/` directory, so such an import would crash
    every xsiam tool call with `ModuleNotFoundError: No module named
    'usecase'`. The runtime's `_load_instance` populates the contextvar
    that `get_config()` reads; no usecase tree needed.
    """
    from config.config import get_config

    proxy = get_config()
    # Drain the proxy into a plain dict so the downstream
    # field-name-fallback lookups in _get_fetcher (which use
    # `.get()` syntax) work unchanged. The proxy raises
    # AttributeError on missing keys; we tolerate that via getattr
    # with a None default so the lookup chain runs to completion.
    return {
        "api_url": getattr(proxy, "api_url", None),
        "papiUrl": getattr(proxy, "papiUrl", None),
        "xsiam_papi_url": getattr(proxy, "xsiam_papi_url", None),
        "baseUrl": getattr(proxy, "baseUrl", None),
        "api_id": getattr(proxy, "api_id", None),
        "papiAuthId": getattr(proxy, "papiAuthId", None),
        "xsiam_api_id": getattr(proxy, "xsiam_api_id", None),
        "api_key_id": getattr(proxy, "api_key_id", None),
        "api_key": getattr(proxy, "api_key", None),
        "papiAuthHeader": getattr(proxy, "papiAuthHeader", None),
        "playgroundId": getattr(proxy, "playgroundId", None),
        "webhookEndpoint": getattr(proxy, "webhookEndpoint", None),
        "webhookKey": getattr(proxy, "webhookKey", None),
    }


def _get_fetcher() -> Fetcher:
    """Resolve the XSIAM PAPI fetcher from the live instance config.

    The lookup chain accepts BOTH the uniform names
    (api_url / api_id / api_key) AND the legacy papi* names so
    existing instances keep working. Uniform names win when both are
    present (operator updated via the form); legacy falls through when
    only legacy is set (operator hasn't re-saved the instance).
    """
    cfg = _get_xsiam_config()
    papi_url = (
        cfg.get("api_url")
        or cfg.get("papiUrl")
        or cfg.get("xsiam_papi_url")
        or cfg.get("baseUrl")
    )
    if not papi_url:
        raise ValueError(
            "xsiam instance has no api_url configured. Edit at /connectors."
        )
    api_key = cfg.get("api_key") or cfg.get("papiAuthHeader")
    if not api_key:
        raise ValueError(
            "xsiam instance has no api_key (Authorization header) configured."
        )
    api_key_id = (
        cfg.get("api_id")
        or cfg.get("papiAuthId")
        or cfg.get("xsiam_api_id")
        or cfg.get("api_key_id")
    )
    if not api_key_id:
        raise ValueError(
            "xsiam instance has no api_id (X-Auth-ID header) configured. "
            "Edit at /connectors."
        )

    base_url = str(papi_url).rstrip("/")
    if "/public_api" in base_url:
        if not base_url.endswith("/public_api/v1"):
            base_url = base_url.split("/public_api")[0].rstrip("/") + "/public_api/v1"
    else:
        base_url = f"{base_url}/public_api/v1"

    return Fetcher(base_url, str(api_key), str(api_key_id))


def _get_resources_dir() -> Path:
    module_dir = Path(__file__).resolve().parents[3]
    resources_dir = module_dir / "resources"
    if resources_dir.exists():
        return resources_dir
    return Path("/app/resources")


class RunXqlQueryRequest(BaseModel):
    """Request model for running XQL queries."""

    query: str = Field(description="XQL query to execute. For syntax reference use cortex-docs/xql_lookup; for tenant-specific dataset/field discovery use xsiam_get_datasets and xsiam_get_dataset_fields.")


class GetCasesRequest(BaseModel):
    """Request model for searching cases."""

    query: str = Field(description="Search query for cases (e.g., 'severity:high AND status:new').")


class WebhookLogRequest(BaseModel):
    """Request model for sending webhook logs to XSIAM."""

    message: str = Field(description="Log message/body to send to the XSIAM HTTP custom collector.")
    event_type: Optional[str] = Field(
        default="mcp_event",
        description="Logical event type/name. Example: 'mcp_event'",
    )
    severity: Optional[str] = Field(
        default="info",
        description="Severity label (info|warning|error). Example: 'info'",
    )
    metadata_json: Optional[str] = Field(
        default=None,
        description="Optional JSON metadata payload to include.",
    )


class LookupDataRequest(BaseModel):
    """Request model for adding lookup data."""

    dataset_name: str = Field(description="Name of the lookup dataset to add data to.")
    data: List[Dict[str, Any]] = Field(description="List of records to add (each record is a dict).")
    key_fields: Optional[List[str]] = Field(default=None, description="Optional unique key fields.")


class GetLookupDataRequest(BaseModel):
    """Request model for retrieving lookup data."""

    dataset_name: str = Field(description="Name of the lookup dataset to query.")
    filters: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Filter conditions (field, operator, value).",
    )
    limit: int = Field(default=20, ge=1, le=1000, description="Max records (1-1000).")


class RemoveLookupDataRequest(BaseModel):
    """Request model for removing lookup data."""

    dataset_name: str = Field(description="Name of the lookup dataset.")
    filters: List[Dict[str, Any]] = Field(description="Filter conditions to identify records to delete.")


class CreateDatasetRequest(BaseModel):
    """Request model for creating a dataset."""

    dataset_name: str = Field(description="Name for new dataset (lowercase with underscores).")
    dataset_schema: Dict[str, Any] = Field(description="Schema definition with field types.")
    dataset_type: str = Field(default="lookup", description="Dataset type (default: lookup).")


class FindXqlExamplesRequest(BaseModel):
    """Request model for XQL RAG search."""

    intent: str = Field(description="Analyst intent to match against the curated XQL library.")
    top_k: int = Field(default=5, ge=1, le=10, description="Number of top examples to return (max 10).")


class GetAssessmentResultsRequest(BaseModel):
    """Request model for vulnerability assessment results."""

    filters: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Filter conditions for vulnerability assessments.",
    )


class GetAssetByIdRequest(BaseModel):
    """Request model for fetching asset by ID."""

    asset_id: str = Field(description="Unique asset identifier in XSIAM.")


class GetAssetsRequest(BaseModel):
    """Request model for asset search."""

    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Filter object with AND/OR arrays. Each item uses SEARCH_FIELD, SEARCH_TYPE, SEARCH_VALUE. "
            "SEARCH_TYPE values: EQ, IN, NIN, NEQ, IS, IS_NOT, LIKE_ANY, NOT_LIKE_ANY, WILDCARD, "
            "WILDCARD_NOT, REGEX, REGEX_NOT, GT, LT, GTE, LTE, RELATIVE_TIMESTAMP, RANGE, CONTAINS, "
            "JSON_SEARCH, JSON_OVERLAPS, JSON_OVERLAPS_NOT, NCONTAINS, CONTAINS_IN_LIST, "
            "NOT_CONTAINS_IN_LIST, ARRAY_LEN_EQ, ARRAY_LEN_NEQ, ARRAY_CONTAINS, ARRAY_CONTAINS_NUMBERS, "
            "ARRAY_NOT_CONTAINS, JSON_EQ, JSON_NEQ, JSON_WILDCARD_NOT, JSON_WILDCARD, JSON_GTE, "
            "JSON_LTE, JSON_GT, JSON_LT, JSON_CONTAINS_NOT, JSON_CONTAINS, JSON_ARRAY_CONTAINED_IN, "
            "JSON_ARRAY_NOT_CONTAINED_IN, JSON_ARRAY_CONTAINS, JSON_ARRAY_CONTAINS_NOT, "
            "JSON_IS_EMPTY, JSON_IS_NOT_EMPTY."
        ),
    )
    sort: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Sort criteria (field and order).",
    )
    search_from: int = Field(default=0, description="Pagination offset.")
    search_to: int = Field(default=100, description="Pagination limit (max 1000).")


class GetIssuesRequest(BaseModel):
    """Request model for issues search."""

    filters: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Filters array of objects with keys: field, operator, value. "
            "field allowed values: issue_id, external_id, detection_method, domain, "
            "severity, _insert_time, status. "
            "operator allowed values: in, gte, lte. "
            "value is the value or list of values to compare against."
        ),
    )
    search_from: int = Field(default=0, description="Pagination offset.")


def _xql_hint(message: str) -> str:
    """What usually went wrong, for a model that gets only 'bad query syntax' back. Models repeat the same few mistakes."""
    low = message.lower()
    if "bad query syntax" in low:
        return ("XQL syntax error. Common causes: `config timeframe = 1h` must be the FIRST stage, before `dataset = ...`; "
                "there is no arithmetic on current_time() in a filter (use `config timeframe = 15m`, or compare "
                "`to_epoch(_time, \"MILLIS\")` with an epoch you got from time_now); `_time` and `_insert_time` are timestamps, "
                "not numbers; no invented functions (string_contains_any, ...).")
    if "timeout" in low:
        return "The query was too broad. Name one dataset, add a filter, and keep `config timeframe` as short as possible."
    return ""


async def xsiam_run_xql_query(query: str = "", ctx: Context = None) -> dict:
    """
    Execute custom XQL query against XSIAM datasets.

    Queries the last 30 minutes unless the query starts with `config timeframe = <n><m|h|d>`, for example
    `config timeframe = 1d | dataset = alerts | limit 10`; use that for any other window. XQL has no arithmetic on
    `current_time()` inside a filter, so never write `_time > current_time() - 5m`. In the `alerts` dataset the stored
    `alert_source` values for Analytics alerts are MAGNIFIER and ANALYTICS_BIOC. Returns JSON results.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_run_xql_query",
        "arguments": {
          "query": "datamodel dataset = corelight_http_raw | limit 10"
        }
      }
    }
    """
    request = RunXqlQueryRequest(query=query)
    if not request.query or not request.query.strip():
        return _create_response({"error": "XQL query is required"}, is_error=True)

    try:
        fetcher = _get_fetcher()
        to_ts = int(time.time() * 1000)
        from_ts = to_ts - (30 * 60 * 1000)

        start_payload = {"request_data": {"query": request.query.strip(), "timeframe": {"from": from_ts, "to": to_ts}}}
        start_resp = await fetcher.send_request("xql/start_xql_query", data=start_payload)
        query_id = start_resp.get("reply")
        if not query_id:
            return _create_response({"error": "Error starting XQL", "details": start_resp}, is_error=True)

        await asyncio.sleep(2)
        results_payload = {
            "request_data": {"query_id": query_id, "pending_flag": False, "limit": 1000, "format": "json"}
        }
        results_resp = await fetcher.send_request("xql/get_query_results", data=results_payload)
        return _create_response(results_resp)
    except Exception as e:
        out = {"error": f"Error running XQL: {str(e)}"}
        hint = _xql_hint(str(e))
        if hint:
            out["hint"] = hint
        return _create_response(out, is_error=True)


async def xsiam_get_cases(query: str = "", ctx: Context = None) -> dict:
    """
    Search security cases/issues in XSIAM.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_cases",
        "arguments": {
          "query": "severity:high AND status:new"
        }
      }
    }
    """
    request = GetCasesRequest(query=query)
    if not request.query:
        return _create_response({"error": "Query required"}, is_error=True)

    try:
        cfg = _get_xsiam_config()
        playground_id = cfg.get("playgroundId") or cfg.get("playground_id")
        if not playground_id:
            return _create_response(
                {
                    "error": (
                        "playgroundId is required for XSOAR commands. "
                        "Edit the xsiam instance at /connectors and set the "
                        "playgroundId field."
                    )
                },
                is_error=True,
            )
        fetcher = _get_fetcher()
        command = f"!getIssues query=`{request.query}`"
        payload = {"investigationId": str(playground_id), "data": command}
        response = await fetcher.send_request("/xsoar/entry/execute/sync", data=payload)
        return _create_response({"result": response})
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_send_webhook_log(
    message: str = "",
    event_type: Optional[str] = "mcp_event",
    severity: Optional[str] = "info",
    metadata_json: Optional[str] = None,
    ctx: Context = None,
) -> dict:
    """
    Send a structured log to the XSIAM HTTP Custom Collector using WEBHOOK_ENDPOINT/WEBHOOK_KEY env vars.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_send_webhook_log",
        "arguments": {
          "message": "Test log from Phantom MCP",
          "event_type": "mcp_event",
          "severity": "info"
        }
      }
    }
    """
    request = WebhookLogRequest(
        message=message,
        event_type=event_type,
        severity=severity,
        metadata_json=metadata_json,
    )
    try:
        cfg = _get_xsiam_config()
    except ValueError as exc:
        return _create_response({"error": str(exc)}, is_error=True)

    webhook_endpoint = cfg.get("webhookEndpoint") or cfg.get("webhook_endpoint")
    webhook_key = cfg.get("webhookKey") or cfg.get("webhook_key")
    if not webhook_endpoint or not webhook_key:
        return _create_response(
            {
                "error": (
                    "webhookEndpoint and webhookKey must be set on the xsiam "
                    "instance. Edit at /connectors."
                )
            },
            is_error=True,
        )

    try:
        ip_address = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip_address = "unknown"

    metadata: Optional[dict] = None
    if request.metadata_json:
        try:
            loaded = json.loads(request.metadata_json)
            metadata = loaded if isinstance(loaded, dict) else {"data": loaded}
        except json.JSONDecodeError:
            metadata = {"raw": request.metadata_json}

    payload = {
        "timestamp": int(time.time() * 1000),
        "hostname": socket.gethostname(),
        "ip": ip_address,
        "event_type": request.event_type or "mcp_event",
        "severity": (request.severity or "info").lower(),
        "message": request.message,
    }
    if metadata is not None:
        payload["metadata"] = metadata

    headers = {"Authorization": str(webhook_key), "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(str(webhook_endpoint), json=payload, headers=headers)

        if 200 <= response.status_code < 300:
            return _create_response({"message": f"Sent log to webhook (HTTP {response.status_code})"})
        return _create_response(
            {"error": f"HTTP {response.status_code}", "details": response.text[:500]},
            is_error=True,
        )
    except httpx.TimeoutException:
        return _create_response({"error": "Request timeout while sending webhook log"}, is_error=True)
    except httpx.RequestError as e:
        return _create_response({"error": f"Request failed - {str(e)}"}, is_error=True)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_add_lookup_data(
    dataset_name: str = "",
    data: Optional[List[Dict[str, Any]]] = None,
    key_fields: Optional[List[str]] = None,
    ctx: Context = None,
) -> dict:
    """
    Add or update data in an XSIAM lookup dataset.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_add_lookup_data",
        "arguments": {
          "dataset_name": "ioc_lookup",
          "data": [{"ip": "1.2.3.4", "label": "suspicious"}]
        }
      }
    }
    """
    request = LookupDataRequest(
        dataset_name=dataset_name,
        data=data if data is not None else [],
        key_fields=key_fields,
    )
    try:
        fetcher = _get_fetcher()
        payload = {"request_data": {"dataset_name": request.dataset_name, "data": request.data}}
        if request.key_fields:
            payload["request_data"]["key_fields"] = request.key_fields
        response = await fetcher.send_request("xql/lookups/add_data", data=payload)
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_get_lookup_data(
    dataset_name: str = "",
    filters: Optional[List[Dict[str, Any]]] = None,
    limit: int = 20,
    ctx: Context = None,
) -> dict:
    """
    Retrieve data from an XSIAM lookup dataset.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_lookup_data",
        "arguments": {
          "dataset_name": "ioc_lookup",
          "limit": 10
        }
      }
    }
    """
    request = GetLookupDataRequest(dataset_name=dataset_name, filters=filters, limit=limit)
    try:
        fetcher = _get_fetcher()
        payload = {"request_data": {"dataset_name": request.dataset_name, "limit": request.limit}}
        if request.filters:
            payload["request_data"]["filters"] = request.filters
        response = await fetcher.send_request("xql/lookups/get_data", data=payload)
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_remove_lookup_data(
    dataset_name: str = "",
    filters: Optional[List[Dict[str, Any]]] = None,
    ctx: Context = None,
) -> dict:
    """
    Remove data from an XSIAM lookup dataset.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_remove_lookup_data",
        "arguments": {
          "dataset_name": "ioc_lookup",
          "filters": [{"field": "ip", "operator": "equals", "value": "1.2.3.4"}]
        }
      }
    }
    """
    request = RemoveLookupDataRequest(
        dataset_name=dataset_name,
        filters=filters if filters is not None else [],
    )
    try:
        fetcher = _get_fetcher()
        payload = {"request_data": {"dataset_name": request.dataset_name, "filters": request.filters}}
        response = await fetcher.send_request("xql/lookups/remove_data", data=payload)
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_get_datasets(ctx: Context) -> dict:
    """
    List all available datasets in XSIAM.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_datasets",
        "arguments": {}
      }
    }
    """
    try:
        fetcher = _get_fetcher()
        response = await fetcher.send_request("xql/get_datasets", data={})
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_create_dataset(
    dataset_name: str = "",
    dataset_schema: Optional[Dict[str, Any]] = None,
    dataset_type: str = "lookup",
    ctx: Context = None,
) -> dict:
    """
    Create a new lookup dataset in XSIAM.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_create_dataset",
        "arguments": {
          "dataset_name": "ioc_lookup",
          "dataset_schema": {"ip": "string", "label": "string"}
        }
      }
    }
    """
    request = CreateDatasetRequest(
        dataset_name=dataset_name,
        dataset_schema=dataset_schema if dataset_schema is not None else {},
        dataset_type=dataset_type,
    )
    try:
        fetcher = _get_fetcher()
        payload = {
            "request_data": {
                "dataset_name": request.dataset_name,
                "dataset_schema": request.dataset_schema,
                "dataset_type": request.dataset_type,
            }
        }
        response = await fetcher.send_request("xql/add_dataset", data=payload)
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_find_xql_examples_rag(intent: str = "", top_k: int = 5, ctx: Context = None) -> dict:
    """
    Retrieve top XQL examples by natural-language intent.

    This tool is a THIN WRAPPER around the runtime's spec-compliant
    `SqliteKnowledgeBase` (manifest.knowledge.bundled[].name == "xql-examples"),
    embedded via VertexEmbedder / text-embedding-004. Agents (and any
    external callers) call `xsiam_find_xql_examples_rag(intent, top_k)`
    and get a `{status, intent, matches, stage_docs, dataset_fields}`
    structure back.

    The enrichment fields (stage_docs from xql_doc.md, dataset_fields
    from dataset_fields.md) are still computed inline — those are pure
    markdown lookups, not vector ops, so they're cheap to recompute.

    Prefer the runtime's `knowledge_search` built-in for new callers —
    that's the spec-blessed surface, kb-name agnostic, and works for
    every loaded KB (phantom-soc, xql-examples, future ones).

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_find_xql_examples_rag",
        "arguments": {
          "intent": "Find C2 beaconing examples",
          "top_k": 5
        }
      }
    }
    """
    request = FindXqlExamplesRequest(intent=intent, top_k=top_k)
    intent = (request.intent or "").strip()
    if not intent:
        return {"status": "error", "message": "Intent must not be empty."}

    # Pull the KB singleton wired by main.py. Same module path the
    # cognitive_tools.knowledge_search built-in uses — single source of
    # truth, no duplicate ingestion.
    try:
        from usecase.kb_store import knowledge_base
    except ImportError:
        return {
            "status": "error",
            "message": "knowledge base module unavailable on this MCP runtime",
        }

    kb = knowledge_base()
    if kb is None:
        return {
            "status": "error",
            "message": "knowledge base not initialized — did the runtime boot complete?",
        }

    try:
        hits = kb.search(intent, kb_name="xql-examples", limit=request.top_k)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"kb.search failed: {exc}"}

    matches: list[dict[str, Any]] = []
    stage_names: set[str] = set()
    datasets: set[str] = set()
    for doc, score in hits:
        # Re-extract from content rather than relying on metadata so
        # entries written by future converter versions stay compatible.
        # (The current converter does write `dataset` to frontmatter,
        # but treating content as canonical avoids drift.)
        meta_dataset = doc.metadata.get("dataset") if isinstance(doc.metadata, dict) else None
        ds = meta_dataset or extract_dataset(doc.content)
        # The body wraps the SQL in a fenced ```sql block; pull just
        # the query for the legacy `query` field. If parsing fails,
        # fall back to the full body — better one slightly noisy
        # response than a failed call.
        sql = _strip_fenced_sql(doc.content) or doc.content
        match = {
            "id": doc.doc_id,
            "title": doc.title,
            "query": sql.strip(),
            "dataset": ds,
            "score": float(score),
        }
        matches.append(match)
        stage_names.update(extract_stage_names(sql))
        if ds:
            datasets.add(ds)

    resources_dir = _get_resources_dir()
    return {
        "status": "ok",
        "intent": intent,
        "matches": matches,
        "stage_docs": collect_stage_docs(resources_dir, sorted(stage_names)),
        "dataset_fields": collect_dataset_fields(resources_dir, sorted(datasets)),
    }


def _strip_fenced_sql(body: str) -> str | None:
    """Extract the SQL out of a ```sql ... ``` fenced block.

    Entries written by the converter look like:

        # <Title>

        **Dataset**: `...`

        ```sql
        dataset = ...
        | filter ...
        ```

    Return None if no fenced block is found — caller decides what to
    fall back to.
    """
    import re as _re
    m = _re.search(r"```(?:sql)?\n(.*?)```", body, flags=_re.DOTALL)
    return m.group(1) if m else None


async def xsiam_get_dataset_fields(ctx: Context) -> dict:
    """
    Get reference mapping of XSIAM dataset names to their available XDM fields.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_dataset_fields",
        "arguments": {}
      }
    }
    """
    path = _get_resources_dir() / "dataset_fields.md"
    if not path.exists():
        return _create_response({"error": "dataset_fields.md not found"}, is_error=True)
    return {"content": path.read_text(encoding="utf-8")}


async def xsiam_get_xql_examples(ctx: Context) -> dict:
    """
    Get collection of real-world XQL query examples from correlation rules and dashboards.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_xql_examples",
        "arguments": {}
      }
    }
    """
    path = _get_resources_dir() / "xql_examples.md"
    if not path.exists():
        return _create_response({"error": "xql_examples.md not found"}, is_error=True)
    return {"content": path.read_text(encoding="utf-8")}


# NOTE: There is deliberately no `xsiam_get_xql_doc` tool serving a bundled
# XQL reference document: the `cortex-docs` connector provides
# `cortex-docs/xql_lookup` against the public Palo Alto Cortex docs
# API — universal access (no XSIAM API key required), always
# up-to-date, and covers all Cortex products (XDR / XSIAM / AgentiX
# / Cloud / XSOAR / Xpanse).
#
# The cortex_xql_query_authoring skill at
# `bundles/spark/mcp/skills/foundation/cortex_xql_query_authoring.md`
# already routes through cortex-docs/xql_lookup. No skill update needed.


async def xsiam_get_asset_by_id(asset_id: str = "", ctx: Context = None) -> dict:
    """
    Retrieve full details for a specific asset by ID.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_asset_by_id",
        "arguments": {
          "asset_id": "ff75e045ecc6b1f47fd6104752b2f15ec3f0cedf9346dba6a1453d26c34001e6"
        }
      }
    }
    """
    request = GetAssetByIdRequest(asset_id=asset_id)
    try:
        fetcher = _get_fetcher()
        response = await fetcher.send_request(f"/assets/{request.asset_id}/", method="GET")
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_get_assets(
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[List[Dict[str, Any]]] = None,
    search_from: int = 0,
    search_to: int = 100,
    ctx: Context = None,
) -> dict:
    """
    Search and retrieve monitored assets from XSIAM.

    Filters format: object with AND/OR arrays of {SEARCH_FIELD, SEARCH_TYPE, SEARCH_VALUE}.
    Example:
    {
      "filters": {
        "AND": [
          {
            "SEARCH_FIELD": "xdm.asset.type.class",
            "SEARCH_TYPE": "NEQ",
            "SEARCH_VALUE": "Other"
          }
        ]
      }
    }

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_assets",
        "arguments": {
          "search_from": 0,
          "search_to": 25,
          "filters": {
            "AND": [
              {
                "SEARCH_FIELD": "xdm.asset.type.class",
                "SEARCH_TYPE": "NEQ",
                "SEARCH_VALUE": "Other"
              }
            ]
          }
        }
      }
    }
    """
    request = GetAssetsRequest(
        filters=filters,
        sort=sort,
        search_from=search_from,
        search_to=search_to,
    )
    try:
        fetcher = _get_fetcher()
        request_data: Dict[str, Any] = {"search_from": request.search_from, "search_to": request.search_to}
        if request.filters:
            request_data["filters"] = request.filters
        if request.sort:
            request_data["sort"] = request.sort
        response = await fetcher.send_request("/assets/", method="POST", data={"request_data": request_data})
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


async def xsiam_get_issues(
    filters: Optional[List[Dict[str, Any]]] = None,
    search_from: int = 0,
    ctx: Context = None,
) -> dict:
    """
    Search and retrieve security issues from XSIAM.

    Filters format: an array of objects with {field, operator, value}.
    Allowed fields (the API rejects anything else, for example creation_time): id, external_id, severity,
    status.progress, detection.method, observation_time, _insert_time, last_modified, issue_domain, category,
    detection.rule_id, assigned_to, asset_ids, asset_names, asset_types. Time fields (observation_time,
    _insert_time, last_modified) take epoch milliseconds; call time_now first if you need one.
    Allowed operators: in, gte, lte.
    Value can be a scalar or list depending on the operator.
    search_from is a ROW offset (0 for the first page), never a timestamp.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "xsiam_get_issues",
        "arguments": {
          "search_from": 0,
          "filters": [
            {
              "field": "severity",
              "operator": "in",
              "value": ["HIGH", "CRITICAL"]
            }
          ]
        }
      }
    }
    """
    request = GetIssuesRequest(filters=filters, search_from=search_from)
    try:
        fetcher = _get_fetcher()
        payload: Dict[str, Any] = {"request_data": {"search_from": request.search_from}}
        if request.filters:
            payload["request_data"]["filters"] = request.filters
        response = await fetcher.send_request("/issue/search/", data=payload)
        return _create_response(response)
    except Exception as e:
        return _create_response({"error": str(e)}, is_error=True)


# ───────────────────────────────────────────────────────────────────
# XSIAM incidents + alerts + IoC + download (12 tools)
# ───────────────────────────────────────────────────────────────────
#
# Mirrors the cortex-xdr connector's pattern. XSIAM and XDR share the Cortex Public
# API surface for these categories — same /public_api/v1/<category>/
# <action>/ paths, same request_data envelopes, same response shapes.
# Tools below use kwarg-style (consistent with the XDR connector) for
# tooling-friendly per-arg agent introspection.


def _xsiam_err(message: str, **extra: Any) -> dict:
    return {"ok": False, "success": False, "error": message, **extra}


def _xsiam_ok(payload: dict) -> dict:
    out = {"ok": True, "success": True}
    out.update(payload)
    return out


def _xsiam_wrap(fn):
    """Mirror of XDR's _wrap_xdr_call. Catches exceptions, returns error envelope."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            return _xsiam_err(f"{type(e).__name__}: {e}")
    return wrapper


# ─── Incidents ───────────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_incidents_list(
    modification_time: Optional[int] = None,
    after_modification: bool = False,
    creation_time: Optional[int] = None,
    after_creation: bool = False,
    incident_id_list: Optional[list[str]] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List XSIAM incidents with filters. Same shape as XDR incidents_list.

    Args:
        modification_time: Unix-millis filter.
        after_modification: If true, modification_time is the lower bound.
        creation_time: Unix-millis filter.
        after_creation: If true, creation_time is the lower bound.
        incident_id_list: Specific IDs.
        description: Substring match.
        status: One of new / under_investigation / resolved_threat_handled /
                resolved_known_issue / resolved_duplicate /
                resolved_false_positive / resolved_other.
        search_from / search_to: Pagination.
    """
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if modification_time is not None:
        filters.append({"field": "modification_time", "operator": "gte" if after_modification else "lte", "value": modification_time})
    if creation_time is not None:
        filters.append({"field": "creation_time", "operator": "gte" if after_creation else "lte", "value": creation_time})
    if incident_id_list:
        filters.append({"field": "incident_id_list", "operator": "in", "value": incident_id_list})
    if description:
        filters.append({"field": "description", "operator": "contains", "value": description})
    if status:
        filters.append({"field": "status", "operator": "eq", "value": status})
    body = {"request_data": {"filters": filters, "search_from": search_from, "search_to": search_to}}
    resp = await fetcher.send_request("/incidents/get_incidents/", data=body)
    return _xsiam_ok({"incidents": (resp.get("reply") or {}).get("incidents", [])})


@_xsiam_wrap
async def xsiam_incidents_get_extra_data(
    incident_id: str,
    alerts_limit: int = 50,
) -> dict:
    """Full details for one XSIAM incident — alerts, artifacts, users, hosts."""
    if not incident_id:
        return _xsiam_err("incident_id is required")
    fetcher = _get_fetcher()
    body = {"request_data": {"incident_id": incident_id, "alerts_limit": alerts_limit}}
    resp = await fetcher.send_request("/incidents/get_incident_extra_data/", data=body)
    return _xsiam_ok({"incident": resp.get("reply")})


@_xsiam_wrap
async def xsiam_incidents_update(incident_id: str, update_data: dict) -> dict:
    """Update XSIAM incident's mutable metadata — status / severity / assignee / comment."""
    if not incident_id or not isinstance(update_data, dict) or not update_data:
        return _xsiam_err("incident_id and non-empty update_data required")
    fetcher = _get_fetcher()
    body = {"request_data": {"incident_id": incident_id, "update_data": update_data}}
    await fetcher.send_request("/incidents/update_incident/", data=body)
    return _xsiam_ok({"incident_id": incident_id, "updated": True})


# ─── Alerts ───────────────────────────────────────────────────────


_ALERT_KEEP = (
    "alert_id", "name", "severity", "category", "source", "action_pretty", "resolution_status", "alert_type",
    "detection_timestamp", "local_insert_ts", "host_name", "host_ip", "user_name", "endpoint_id", "case_id", "external_id",
    "mitre_tactic_id_and_name", "mitre_technique_id_and_name", "original_tags", "description",
)


def _slim_alert(alert: dict) -> dict:
    """One alert without its raw events: a single port-scan alert carries about 300 KB of them, and a chat re-sends every
    tool result on every later turn. `event_count` says how many were left out; query the dataset in XQL for the events."""
    out = {k: alert[k] for k in _ALERT_KEEP if alert.get(k) is not None}
    if isinstance(out.get("description"), str):
        out["description"] = out["description"][:400]
    out["event_count"] = len(alert.get("events") or [])
    return out


@_xsiam_wrap
async def xsiam_alerts_list(
    severity: Optional[list[str]] = None,
    status: Optional[list[str]] = None,
    alert_source: Optional[list[str]] = None,
    since_minutes: Optional[int] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List XSIAM alerts, newest first (multi-event shape).

    Args:
        severity: only these severities, e.g. ["SEV_040_HIGH"] or ["high"].
        status: only these statuses.
        alert_source: only these sources. Analytics alerts are stored as
            ["MAGNIFIER", "ANALYTICS_BIOC"]; correlation rules as ["CORRELATION"].
        since_minutes: only alerts created in the last N minutes. Use this for
            "what fired in the last hour", instead of building a timestamp.
        search_from, search_to: ROW offsets for paging, never timestamps. The
            defaults 0 and 100 return the first 100 rows; search_to minus
            search_from may be at most 100.

    Example: {"since_minutes": 60, "alert_source": ["MAGNIFIER", "ANALYTICS_BIOC"]}
    """
    if search_from < 0 or search_to <= search_from or search_to - search_from > 100:
        return _xsiam_err(
            "search_from and search_to are ROW OFFSETS for paging (defaults 0 and 100, at most 100 rows per call), "
            "not timestamps. To list recent alerts pass since_minutes, for example since_minutes=60."
        )
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if severity:
        filters.append({"field": "severity", "operator": "in", "value": severity})
    if status:
        filters.append({"field": "status", "operator": "in", "value": status})
    if alert_source:
        filters.append({"field": "alert_source", "operator": "in", "value": alert_source})
    if since_minutes is not None:
        if since_minutes <= 0:
            return _xsiam_err("since_minutes must be a positive number of minutes")
        filters.append({"field": "creation_time", "operator": "gte", "value": int(time.time() * 1000) - since_minutes * 60_000})
    body = {"request_data": {"filters": filters, "search_from": search_from, "search_to": search_to,
                             "sort": {"field": "creation_time", "keyword": "desc"}}}
    resp = await fetcher.send_request("/alerts/get_alerts_multi_events/", data=body)
    alerts = [_slim_alert(a) for a in (resp.get("reply") or {}).get("alerts", [])]
    return _xsiam_ok({"alerts": alerts, "returned": len(alerts), "total": (resp.get("reply") or {}).get("total_count")})


@_xsiam_wrap
async def xsiam_alerts_update(alert_id_list: list[str], update_data: dict) -> dict:
    """Bulk-update one or more alerts (severity / status / resolve_comment)."""
    if not alert_id_list or not isinstance(update_data, dict) or not update_data:
        return _xsiam_err("alert_id_list and non-empty update_data required")
    fetcher = _get_fetcher()
    body = {"request_data": {"alert_id_list": alert_id_list, "update_data": update_data}}
    await fetcher.send_request("/alerts/update_alerts/", data=body)
    return _xsiam_ok({"updated_count": len(alert_id_list), "alert_id_list": alert_id_list})


# ─── IoC management ───────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_ioc_insert_json(indicators: list[dict], validate: bool = True) -> dict:
    """Bulk-upload IoCs. Each dict needs indicator + type + severity + reputation."""
    if not indicators or not isinstance(indicators, list):
        return _xsiam_err("indicators must be a non-empty list of IoC dicts")
    fetcher = _get_fetcher()
    body = {"request_data": {"validate": validate, "indicators": indicators}}
    resp = await fetcher.send_request("/indicators/insert_jsons/", data=body)
    return _xsiam_ok({
        "inserted_count": len(indicators),
        "errors": (resp.get("reply") or {}).get("errors") or [],
    })


@_xsiam_wrap
async def xsiam_ioc_disable(indicators: list[str]) -> dict:
    """Disable IoCs by value."""
    if not indicators:
        return _xsiam_err("indicators required")
    fetcher = _get_fetcher()
    body = {"request_data": {"indicators": indicators}}
    await fetcher.send_request("/indicators/disable_iocs/", data=body)
    return _xsiam_ok({"disabled_count": len(indicators), "indicators": indicators})


@_xsiam_wrap
async def xsiam_ioc_enable(indicators: list[str]) -> dict:
    """Re-enable previously disabled IoCs."""
    if not indicators:
        return _xsiam_err("indicators required")
    fetcher = _get_fetcher()
    body = {"request_data": {"indicators": indicators}}
    await fetcher.send_request("/indicators/enable_iocs/", data=body)
    return _xsiam_ok({"enabled_count": len(indicators), "indicators": indicators})


# ─── File download ────────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_download_file(file_link: str) -> dict:
    """Download bytes from an XSIAM-issued retrieval URL.

    Companion to xsiam_endpoints_retrieve_file — once retrieval
    completes, pass file_link from xsiam_response_get_file_retrieval_details
    here to pull the bytes as base64.

    Pre-condition: file_link must point at the configured XSIAM tenant FQDN.
    """
    if not file_link or not isinstance(file_link, str):
        return _xsiam_err("file_link must be a non-empty string")
    cfg = _get_xsiam_config()
    api_url = cfg.get("api_url", "")
    if api_url and not file_link.startswith(api_url.rstrip("/")):
        return _xsiam_err("file_link does not match configured XSIAM tenant",
                          api_url=api_url, file_link_prefix=file_link[:60])
    # XSIAM's downloads return raw bytes — we can't use send_request directly
    # (it expects JSON responses). Use httpx directly with the bearer headers.
    import base64
    import httpx
    headers = {"Authorization": cfg.get("api_key", ""), "x-xdr-auth-id": str(cfg.get("api_id", ""))}
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(file_link, headers=headers)
    if r.status_code != 200:
        return _xsiam_err(f"HTTP {r.status_code} downloading file",
                          body=r.text[:200])
    return _xsiam_ok({
        "file_link": file_link,
        "size_bytes": len(r.content),
        "content_b64": base64.b64encode(r.content).decode("ascii"),
    })


# ───────────────────────────────────────────────────────────────────
# XSIAM endpoints + response + scripts (18 tools)
# ───────────────────────────────────────────────────────────────────
#
# Mirrors the XDR endpoints/response/scripts tier with xsiam_*
# prefix + xsiam's Fetcher.send_request. Same /public_api/v1/<api>/
# <call>/ paths as XDR — XSIAM uses the Cortex Public API.


def _build_xsiam_endpoint_filters(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None,
    group_name: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    alias: Optional[list[str]] = None,
    isolate: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
) -> list[dict]:
    """Compose XSIAM endpoint filters. Same field set as XDR."""
    filters: list[dict] = []
    if endpoint_id_list:
        filters.append({"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list})
    if dist_name:
        filters.append({"field": "dist_name", "operator": "in", "value": dist_name})
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


# ─── Endpoints ────────────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_endpoints_list_all() -> dict:
    """List ALL XSIAM endpoints."""
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/endpoints/get_endpoints/", data={"request_data": {}})
    endpoints = (resp.get("reply") or {}).get("endpoints") or resp.get("reply") or []
    return _xsiam_ok({"endpoints": endpoints, "total": len(endpoints) if isinstance(endpoints, list) else 0})


@_xsiam_wrap
async def xsiam_endpoints_get(
    endpoint_id_list: Optional[list[str]] = None,
    dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None,
    group_name: Optional[list[str]] = None,
    platform: Optional[list[str]] = None,
    alias: Optional[list[str]] = None,
    hostname: Optional[list[str]] = None,
    isolate: Optional[list[str]] = None,
) -> dict:
    """Get filtered XSIAM endpoints. Same shape as xdr_endpoints_get."""
    fetcher = _get_fetcher()
    filters = _build_xsiam_endpoint_filters(
        endpoint_id_list=endpoint_id_list, dist_name=dist_name, ip_list=ip_list,
        group_name=group_name, platform=platform, alias=alias, hostname=hostname, isolate=isolate,
    )
    body = {"request_data": {"filters": filters} if filters else {}}
    resp = await fetcher.send_request("/endpoints/get_endpoint/", data=body)
    endpoints = (resp.get("reply") or {}).get("endpoints") or []
    return _xsiam_ok({"endpoints": endpoints, "total": len(endpoints)})


@_xsiam_wrap
async def xsiam_endpoints_isolate(
    endpoint_id_list: Optional[list[str]] = None, dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None, platform: Optional[list[str]] = None, hostname: Optional[list[str]] = None,
) -> dict:
    """Isolate XSIAM endpoints. At least one filter required."""
    fetcher = _get_fetcher()
    filters = _build_xsiam_endpoint_filters(endpoint_id_list=endpoint_id_list, dist_name=dist_name,
                                              ip_list=ip_list, platform=platform, hostname=hostname)
    if not filters:
        return _xsiam_err("at least one filter required")
    resp = await fetcher.send_request("/endpoints/isolate/", data={"request_data": {"filters": filters}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id"), "endpoints_affected": reply.get("endpoints_count", 0)})


@_xsiam_wrap
async def xsiam_endpoints_unisolate(
    endpoint_id_list: Optional[list[str]] = None, dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None, platform: Optional[list[str]] = None, hostname: Optional[list[str]] = None,
) -> dict:
    """Unisolate XSIAM endpoints."""
    fetcher = _get_fetcher()
    filters = _build_xsiam_endpoint_filters(endpoint_id_list=endpoint_id_list, dist_name=dist_name,
                                              ip_list=ip_list, platform=platform, hostname=hostname)
    if not filters:
        return _xsiam_err("at least one filter required")
    resp = await fetcher.send_request("/endpoints/unisolate/", data={"request_data": {"filters": filters}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id"), "endpoints_affected": reply.get("endpoints_count", 0)})


@_xsiam_wrap
async def xsiam_endpoints_scan(
    endpoint_id_list: Optional[list[str]] = None, dist_name: Optional[list[str]] = None,
    ip_list: Optional[list[str]] = None, platform: Optional[list[str]] = None, hostname: Optional[list[str]] = None,
) -> dict:
    """Trigger scan on matching XSIAM endpoints."""
    fetcher = _get_fetcher()
    filters = _build_xsiam_endpoint_filters(endpoint_id_list=endpoint_id_list, dist_name=dist_name,
                                              ip_list=ip_list, platform=platform, hostname=hostname)
    if not filters:
        return _xsiam_err("at least one filter required")
    resp = await fetcher.send_request("/endpoints/scan/", data={"request_data": {"filters": filters}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id"), "endpoints_affected": reply.get("endpoints_count", 0)})


@_xsiam_wrap
async def xsiam_endpoints_scan_all() -> dict:
    """Scan EVERY XSIAM endpoint (high-impact)."""
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/endpoints/scan/", data={"request_data": {"filters": []}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id")})


@_xsiam_wrap
async def xsiam_endpoints_set_alias(endpoint_id_list: list[str], alias_name: str) -> dict:
    """Set alias for one or more XSIAM endpoints."""
    if not endpoint_id_list:
        return _xsiam_err("endpoint_id_list is required")
    fetcher = _get_fetcher()
    body = {"request_data": {
        "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
        "alias": alias_name,
    }}
    await fetcher.send_request("/endpoints/update_agent_name/", data=body)
    return _xsiam_ok({"endpoint_id_list": endpoint_id_list, "alias_name": alias_name})


@_xsiam_wrap
async def xsiam_endpoints_retrieve_file(endpoint_id_list: list[str], files: dict) -> dict:
    """Retrieve files from XSIAM endpoints. files = {windows/linux/macos: [paths]}."""
    if not endpoint_id_list or not isinstance(files, dict):
        return _xsiam_err("endpoint_id_list and files dict required")
    fetcher = _get_fetcher()
    body = {"request_data": {
        "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
        "files": files,
    }}
    resp = await fetcher.send_request("/endpoints/file_retrieval/", data=body)
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id"), "endpoints_count": reply.get("endpoints_count", 0)})


@_xsiam_wrap
async def xsiam_endpoints_quarantine_file(endpoint_id_list: list[str], file_path: str, file_hash: str) -> dict:
    """Quarantine a file across XSIAM endpoints by path + SHA-256."""
    if not endpoint_id_list or not file_path or not file_hash:
        return _xsiam_err("endpoint_id_list, file_path, file_hash required")
    fetcher = _get_fetcher()
    body = {"request_data": {
        "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
        "file_path": file_path, "file_hash": file_hash,
    }}
    resp = await fetcher.send_request("/endpoints/quarantine/", data=body)
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id"), "file_path": file_path})


# ─── Response action status ───────────────────────────────────────


@_xsiam_wrap
async def xsiam_response_get_action_status(action_id: str) -> dict:
    """Get status of any XSIAM response action."""
    if not action_id:
        return _xsiam_err("action_id is required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/actions/get_action_status/",
                                       data={"request_data": {"group_action_id": action_id}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": action_id, "status_per_endpoint": reply.get("data", {})})


@_xsiam_wrap
async def xsiam_response_get_file_retrieval_details(action_id: str) -> dict:
    """Download URLs for a completed XSIAM file_retrieval action."""
    if not action_id:
        return _xsiam_err("action_id is required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/actions/file_retrieval_details/",
                                       data={"request_data": {"group_action_id": action_id}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": action_id, "files": reply.get("data", [])})


# ─── Scripts library ─────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_scripts_list(
    name: Optional[list[str]] = None,
    windows_supported: Optional[bool] = None,
    linux_supported: Optional[bool] = None,
    macos_supported: Optional[bool] = None,
) -> dict:
    """List XSIAM scripts library."""
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if name:
        filters.append({"field": "name", "operator": "in", "value": name})
    if windows_supported is not None:
        filters.append({"field": "windows_supported", "operator": "eq", "value": windows_supported})
    if linux_supported is not None:
        filters.append({"field": "linux_supported", "operator": "eq", "value": linux_supported})
    if macos_supported is not None:
        filters.append({"field": "macos_supported", "operator": "eq", "value": macos_supported})
    body = {"request_data": {"filters": filters} if filters else {}}
    resp = await fetcher.send_request("/scripts/get_scripts/", data=body)
    reply = resp.get("reply") or {}
    scripts = reply.get("scripts") or (reply if isinstance(reply, list) else [])
    return _xsiam_ok({"scripts": scripts})


@_xsiam_wrap
async def xsiam_scripts_get_metadata(script_uid: str) -> dict:
    """Full definition of one XSIAM script."""
    if not script_uid:
        return _xsiam_err("script_uid is required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/scripts/get_script_metadata/",
                                       data={"request_data": {"script_uid": script_uid}})
    return _xsiam_ok({"script": (resp.get("reply") or {}).get("script")})


@_xsiam_wrap
async def xsiam_scripts_run_script(
    script_uid: str, endpoint_id_list: list[str],
    parameters_values: Optional[dict] = None, timeout: int = 600,
) -> dict:
    """Run a library script on XSIAM endpoints."""
    if not script_uid or not endpoint_id_list:
        return _xsiam_err("script_uid and endpoint_id_list required")
    fetcher = _get_fetcher()
    body = {"request_data": {
        "script_uid": script_uid,
        "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
        "parameters_values": parameters_values or {}, "timeout": timeout,
    }}
    resp = await fetcher.send_request("/scripts/run_script/", data=body)
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id")})


@_xsiam_wrap
async def xsiam_scripts_run_snippet(snippet_code: str, endpoint_id_list: list[str], timeout: int = 600) -> dict:
    """Run ad-hoc snippet on XSIAM endpoints."""
    if not snippet_code or not endpoint_id_list:
        return _xsiam_err("snippet_code and endpoint_id_list required")
    fetcher = _get_fetcher()
    body = {"request_data": {
        "snippet_code": snippet_code,
        "filters": [{"field": "endpoint_id_list", "operator": "in", "value": endpoint_id_list}],
        "timeout": timeout,
    }}
    resp = await fetcher.send_request("/scripts/run_snippet_code_script/", data=body)
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": reply.get("action_id")})


@_xsiam_wrap
async def xsiam_scripts_get_execution_status(action_id: str) -> dict:
    """Poll status of an XSIAM script-execution action."""
    if not action_id:
        return _xsiam_err("action_id is required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/scripts/get_script_execution_status/",
                                       data={"request_data": {"action_id": action_id}})
    return _xsiam_ok({"action_id": action_id, "status_per_endpoint": resp.get("reply") or {}})


@_xsiam_wrap
async def xsiam_scripts_get_execution_results(action_id: str) -> dict:
    """Get XSIAM script execution results."""
    if not action_id:
        return _xsiam_err("action_id is required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/scripts/get_script_execution_results/",
                                       data={"request_data": {"action_id": action_id}})
    return _xsiam_ok({"action_id": action_id, "results": resp.get("reply") or {}})


@_xsiam_wrap
async def xsiam_scripts_get_execution_result_files(action_id: int, endpoint_id: int) -> dict:
    """Retrieve files a script produced on a specific endpoint."""
    if not action_id or not endpoint_id:
        return _xsiam_err("action_id and endpoint_id are required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/scripts/get_script_execution_result_files/",
                                       data={"request_data": {"action_id": action_id, "endpoint_id": endpoint_id}})
    reply = resp.get("reply") or {}
    return _xsiam_ok({"action_id": action_id, "endpoint_id": endpoint_id, "file_link": reply.get("DATA")})


# ───────────────────────────────────────────────────────────────────
# XSIAM admin + XSIAM-unique (18 tools)
# ───────────────────────────────────────────────────────────────────
#
# Common admin (audit/distribution/exclusions/hash/exploits) mirrors
# the XDR admin additions with xsiam_* prefix. Plus XSIAM-unique categories:
# parsers, datamodel introspection (XSIAM-license-gated), broker VM mgmt.
# Hand-authored from public XSIAM docs knowledge; validate against a real tenant.


# ─── Audit logs ──────────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_audit_list_management_logs(
    audit_owner_email: Optional[list[str]] = None,
    audit_severity: Optional[list[str]] = None,
    audit_result: Optional[list[str]] = None,
    timestamp_gte: Optional[int] = None,
    timestamp_lte: Optional[int] = None,
    search_from: int = 0,
    search_to: int = 100,
) -> dict:
    """List XSIAM management-actions audit log."""
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if audit_owner_email:
        filters.append({"field": "audit_owner_email", "operator": "in", "value": audit_owner_email})
    if audit_severity:
        filters.append({"field": "audit_severity", "operator": "in", "value": audit_severity})
    if audit_result:
        filters.append({"field": "audit_result", "operator": "in", "value": audit_result})
    if timestamp_gte is not None:
        filters.append({"field": "timestamp", "operator": "gte", "value": timestamp_gte})
    if timestamp_lte is not None:
        filters.append({"field": "timestamp", "operator": "lte", "value": timestamp_lte})
    body = {"request_data": {"filters": filters, "search_from": search_from, "search_to": search_to}}
    resp = await fetcher.send_request("/audits/management_logs/", data=body)
    return _xsiam_ok({"audit_entries": (resp.get("reply") or {}).get("data", [])})


@_xsiam_wrap
async def xsiam_audit_list_agent_logs(
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
    """List XSIAM per-agent audit log."""
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
    body = {"request_data": {"filters": filters, "search_from": search_from, "search_to": search_to}}
    resp = await fetcher.send_request("/audits/agents_reports/", data=body)
    return _xsiam_ok({"audit_entries": (resp.get("reply") or {}).get("data", [])})


# ─── Distribution lists ──────────────────────────────────────────


@_xsiam_wrap
async def xsiam_distribution_list() -> dict:
    """List XSIAM distribution lists (agent installer bundles)."""
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/distributions/get_distributions/", data={"request_data": {}})
    return _xsiam_ok({"distributions": (resp.get("reply") or {}).get("distributions", [])})


@_xsiam_wrap
async def xsiam_distribution_create(
    name: str, platform: str, package_type: str = "standalone",
    agent_version: Optional[str] = None, description: Optional[str] = None,
) -> dict:
    """Create new XSIAM distribution list."""
    if not name or not platform:
        return _xsiam_err("name and platform required")
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"name": name, "platform": platform, "package_type": package_type}
    if agent_version:
        rd["agent_version"] = agent_version
    if description:
        rd["description"] = description
    resp = await fetcher.send_request("/distributions/create/", data={"request_data": rd})
    return _xsiam_ok({"distribution_id": (resp.get("reply") or {}).get("distribution_id")})


@_xsiam_wrap
async def xsiam_distribution_get_url(distribution_id: str) -> dict:
    """Get installer URL for an XSIAM distribution."""
    if not distribution_id:
        return _xsiam_err("distribution_id required")
    fetcher = _get_fetcher()
    body = {"request_data": {"distribution_id": distribution_id, "package_type": "standalone"}}
    resp = await fetcher.send_request("/distributions/get_dist_url/", data=body)
    return _xsiam_ok({"download_url": (resp.get("reply") or {}).get("distribution_url")})


@_xsiam_wrap
async def xsiam_distribution_versions() -> dict:
    """List XSIAM agent versions per platform."""
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/distributions/get_versions/", data={"request_data": {}})
    return _xsiam_ok({"versions": resp.get("reply") or {}})


# ─── Alert exclusions ────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_alert_exclusions_list(
    tenant_id: Optional[str] = None,
    search_from: int = 0, search_to: int = 100,
) -> dict:
    """List XSIAM alert-exclusion rules."""
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"search_from": search_from, "search_to": search_to}
    if tenant_id:
        rd["tenant_id"] = tenant_id
    resp = await fetcher.send_request("/alerts_exclusion/get_alert_exclusion/", data={"request_data": rd})
    return _xsiam_ok({"exclusions": (resp.get("reply") or {}).get("alert_exclusions", [])})


@_xsiam_wrap
async def xsiam_alert_exclusions_create(
    name: str, filter_expression: dict, comment: Optional[str] = None,
) -> dict:
    """Create XSIAM alert-exclusion rule."""
    if not name or not filter_expression:
        return _xsiam_err("name and filter_expression required")
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"name": name, "filterData": filter_expression}
    if comment:
        rd["comment"] = comment
    resp = await fetcher.send_request("/alerts_exclusion/create_alert_exclusion/", data={"request_data": rd})
    return _xsiam_ok({"exclusion_id": (resp.get("reply") or {}).get("alert_exclusion_id")})


@_xsiam_wrap
async def xsiam_alert_exclusions_delete(alert_exclusion_id: str) -> dict:
    """Delete XSIAM alert-exclusion rule."""
    if not alert_exclusion_id:
        return _xsiam_err("alert_exclusion_id required")
    fetcher = _get_fetcher()
    body = {"request_data": {"alert_exclusion_id": alert_exclusion_id}}
    await fetcher.send_request("/alerts_exclusion/delete_alert_exclusion/", data=body)
    return _xsiam_ok({"alert_exclusion_id": alert_exclusion_id, "deleted": True})


# ─── Hash analytics ──────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_hash_get_analytics(file_hash: str) -> dict:
    """Get XSIAM analytics for a file hash."""
    if not file_hash:
        return _xsiam_err("file_hash required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/hash_exceptions/get_hash_analytics/",
                                       data={"request_data": {"hash": file_hash}})
    return _xsiam_ok({"hash": file_hash, "analytics": resp.get("reply")})


@_xsiam_wrap
async def xsiam_hash_blocklist(file_hashes: list[str], comment: Optional[str] = None) -> dict:
    """Add file hashes to XSIAM global blocklist."""
    if not file_hashes:
        return _xsiam_err("file_hashes required")
    fetcher = _get_fetcher()
    rd: dict[str, Any] = {"hash_list": file_hashes}
    if comment:
        rd["comment"] = comment
    await fetcher.send_request("/hash_exceptions/blocklist/", data={"request_data": rd})
    return _xsiam_ok({"blocked_count": len(file_hashes), "file_hashes": file_hashes})


# ─── Exploits ────────────────────────────────────────────────────


@_xsiam_wrap
async def xsiam_exploits_list(
    endpoint_id_list: Optional[list[str]] = None,
    cve_id: Optional[list[str]] = None,
    search_from: int = 0, search_to: int = 100,
) -> dict:
    """List XSIAM exploit detections."""
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if endpoint_id_list:
        filters.append({"field": "endpoint_id", "operator": "in", "value": endpoint_id_list})
    if cve_id:
        filters.append({"field": "cve_id", "operator": "in", "value": cve_id})
    body = {"request_data": {"filters": filters, "search_from": search_from, "search_to": search_to}}
    resp = await fetcher.send_request("/exploits/get_exploits/", data=body)
    return _xsiam_ok({"exploits": (resp.get("reply") or {}).get("exploits", [])})


@_xsiam_wrap
async def xsiam_exploits_get_details(exploit_id: str) -> dict:
    """Full details of one XSIAM exploit detection."""
    if not exploit_id:
        return _xsiam_err("exploit_id required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/exploits/get_exploit_details/",
                                       data={"request_data": {"exploit_id": exploit_id}})
    return _xsiam_ok({"exploit": (resp.get("reply") or {}).get("exploit")})


# ─── XSIAM-unique: Parsers ──────────────────────────────────────


@_xsiam_wrap
async def xsiam_parsers_list(
    vendor: Optional[str] = None, product: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> dict:
    """List XSIAM parsers (vendor-log → XDM schema transformers).

    XSIAM-unique — XDR doesn't expose parsers directly (managed via
    modeling-rule pipeline instead).
    """
    fetcher = _get_fetcher()
    filters: list[dict] = []
    if vendor:
        filters.append({"field": "vendor", "operator": "eq", "value": vendor})
    if product:
        filters.append({"field": "product", "operator": "eq", "value": product})
    if enabled is not None:
        filters.append({"field": "enabled", "operator": "eq", "value": enabled})
    body = {"request_data": {"filters": filters} if filters else {}}
    resp = await fetcher.send_request("/parser/get_parsers/", data=body)
    return _xsiam_ok({"parsers": (resp.get("reply") or {}).get("parsers", [])})


@_xsiam_wrap
async def xsiam_parsers_get(parser_id: str) -> dict:
    """Full definition of one XSIAM parser."""
    if not parser_id:
        return _xsiam_err("parser_id required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/parser/get_parser/",
                                       data={"request_data": {"parser_id": parser_id}})
    return _xsiam_ok({"parser": (resp.get("reply") or {}).get("parser")})


# ─── XSIAM-unique: Datamodel ────────────────────────────────────


@_xsiam_wrap
async def xsiam_datamodel_describe(dataset: str) -> dict:
    """XSIAM-licensed datamodel introspection — get XDM-typed schema for a dataset.

    Internally builds an XQL query with the `datamodel` stage. XDR-only
    tenants return "Invalid License - XSIAM" for this query — XSIAM-only.
    """
    if not dataset:
        return _xsiam_err("dataset required")
    fetcher = _get_fetcher()
    query = f"dataset = {dataset} | datamodel"
    body = {"request_data": {"query": query, "tenants": []}}
    # Start the query
    start_resp = await fetcher.send_request("/xql/start_xql_query/", data=body)
    execution_id = (start_resp.get("reply") or {}).get("execution_id")
    if not execution_id:
        return _xsiam_err("could not start datamodel query", raw_response=start_resp)
    # Poll for results (XSIAM datamodel queries are usually fast — <5s)
    import asyncio as _async
    for _attempt in range(20):
        await _async.sleep(1)
        poll = await fetcher.send_request(
            "/xql/get_query_results/",
            data={"request_data": {"query_id": execution_id, "limit": 1000}},
        )
        reply = poll.get("reply") or {}
        status = reply.get("status")
        if status == "SUCCESS":
            return _xsiam_ok({
                "dataset": dataset,
                "fields": (reply.get("results") or {}).get("data", []),
            })
        if status in ("FAIL", "FAILED", "CANCELLED"):
            return _xsiam_err(
                "datamodel query failed",
                hint="XDR-only tenants return 'Invalid License - XSIAM' here — XSIAM license required",
                raw_response=poll,
            )
    return _xsiam_err("datamodel query timed out after 20s")


# ─── XSIAM-unique: Broker ───────────────────────────────────────


@_xsiam_wrap
async def xsiam_broker_list() -> dict:
    """List XSIAM Broker VMs (on-prem data collectors)."""
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/broker/list_brokers/", data={"request_data": {}})
    return _xsiam_ok({"brokers": (resp.get("reply") or {}).get("brokers", [])})


@_xsiam_wrap
async def xsiam_broker_get(broker_id: str) -> dict:
    """Full status + config for one XSIAM Broker VM."""
    if not broker_id:
        return _xsiam_err("broker_id required")
    fetcher = _get_fetcher()
    resp = await fetcher.send_request("/broker/get_broker/",
                                       data={"request_data": {"broker_id": broker_id}})
    return _xsiam_ok({"broker": (resp.get("reply") or {}).get("broker")})
