# Get All Endpoints

**HTTP**: `POST /public_api/v1/endpoints/get_endpoints/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_endpoints_list_all`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

## Purpose

Gets a list of your endpoints.

## Parameters

_No parameters._

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

A GetAllEndpointsResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/get_endpoints/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_all_endpoints` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_endpoints_list_all`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `get_all_endpoints`
