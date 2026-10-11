# Scan All Endpoints

**HTTP**: `POST /public_api/v1/endpoints/scan/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xdr_endpoints_scan_all`
**Phantom connector**: `cortex-xdr` (per-instance: see Tools tab on `/connectors/cortex-xdr-<instance>`)

## Purpose

Scans all endpoints.

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

A ResponseActionResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/scan/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/cortex-xdr-client`'s `scan_all_endpoints` wrapper — see https://github.com/ebarti/cortex-xdr-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xdr_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_endpoints_scan_all`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `scan_all_endpoints`
