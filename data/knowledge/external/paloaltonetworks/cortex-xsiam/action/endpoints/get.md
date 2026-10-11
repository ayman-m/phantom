# Get Endpoint

**HTTP**: `POST /public_api/v1/endpoints/get_endpoint/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_endpoints_get`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

## Purpose

Gets a list of filtered endpoints.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `endpoint_id_list` | `List[str]` | `None` | List of endpoint IDs. |
| `endpoint_status` | `List[EndpointStatus]` | `None` | Status of the endpoint ID. |
| `dist_name` | `List[str]` | `None` | Distribution / Installation Package name. |
| `first_seen` | `int` | `None` | When the agent was first seen. |
| `after_first_seen` | `bool` | `False` | If the first seen date will be the upper or lower bound limit. |
| `last_seen` | `int` | `None` | When the agent was last seen. |
| `after_last_seen` | `bool` | `False` | If the last seen date will be the upper or lower bound limit. |
| `ip_list` | `List[str]` | `None` | List of IP addresses. |
| `group_name` | `List[str]` | `None` | Group name the agent belongs to. |
| `platform` | `List[EndpointPlatform]` | `None` | Platform name. |
| `alias` | `List[str]` | `None` | Alias name. |
| `hostname` | `List[str]` | `None` | Hostname. |
| `isolate` | `List[IsolateStatus]` | `None` | If the endpoint was isolated. |
| `scan_status` | `List[ScanStatus]` | `None` | A list of ScanStatus |
| `username` | `List[str]` | `None` | Username. |
| `search_from` | `int` | `None` | Integer representing the starting offset within the query result set from which you want incidents returned. |
| `search_to` | `int` | `None` | Integer representing the end offset within the result set after which you do not want incidents returned. |

## Request body (representative)

```json
{
  "request_data": {
    "filters": [ /* see ebarti filter helpers */ ],
    "search_from": 0,
    "search_to": 100
  }
}
```

## Returns

A GetEndpointResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/get_endpoint/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_endpoint` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_endpoints_get`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `get_endpoint`
