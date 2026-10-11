# Scan Endpoints

**HTTP**: `POST /public_api/v1/endpoints/scan/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_endpoints_scan`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/response-actions/scan-endpoints.html

## Purpose

Run a scan on selected endpoints.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `endpoint_id_list` | `List[str]` | `None` | List of endpoint IDs. |
| `dist_name` | `List[str]` | `None` | Name of the distribution list. |
| `first_seen` | `int` | `None` | When an endpoint was first seen. |
| `after_first_seen` | `bool` | `False` | If the first seen date will be the upper or lower bound limit. |
| `last_seen` | `int` | `None` | When an endpoint was last seen. |
| `after_last_seen` | `bool` | `False` | If the last seen date will be the upper or lower bound limit. |
| `ip_list` | `List[str]` | `None` | List of IP addresses. |
| `group_name` | `List[str]` | `None` | Name of the endpoint group. |
| `platform` | `List[EndpointPlatform]` | `None` | Platform name. |
| `alias` | `List[str]` | `None` | Endpoint alias name. |
| `hostname` | `List[str]` | `None` | Name of host. |
| `isolate` | `List[IsolateStatus]` | `None` | If the endpoint has been isolated. |
| `scan_status` | `List[ScanStatus]` | `None` | The scan status. |
| `username` | `List[str]` | `None` | Username. |

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

A ResponseActionResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/scan/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `scan_endpoints` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_endpoints_scan`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `scan_endpoints`
