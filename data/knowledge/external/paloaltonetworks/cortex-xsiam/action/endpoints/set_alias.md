# Set Endpoint Alias

**HTTP**: `POST /public_api/v1/endpoints/update_agent_name/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_endpoints_set_alias`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

## Purpose

Set or modify an Alias field for your endpoints.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `new_alias` | `str` | `—` | The alias name you want to set or modify. |
| `endpoint_id_list` | `List[str]` | `None` | List of endpoint IDs. |
| `endpoint_status` | `EndpointStatus` | `None` | Status of the endpoint ID. |
| `dist_name` | `str` | `None` | Distribution / Installation Package name. |
| `ip_list` | `List[str]` | `None` | List of IP addresses. |
| `group_name` | `List[str]` | `None` | Group name the agent belongs to. |
| `platform` | `List[EndpointPlatform]` | `None` | Platform name. |
| `alias` | `List[str]` | `None` | Alias name. |
| `isolate` | `List[IsolateStatus]` | `None` | If the endpoint was isolated. |
| `hostname` | `List[str]` | `None` | Hostname |

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

A ResponseStatusResponse if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/update_agent_name/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `set_endpoint_alias` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_endpoints_set_alias`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `set_endpoint_alias`
