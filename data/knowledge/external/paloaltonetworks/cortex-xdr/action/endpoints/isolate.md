# Isolate Endpoints

**HTTP**: `POST /public_api/v1/endpoints/isolate/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xdr_endpoints_isolate`
**Phantom connector**: `cortex-xdr` (per-instance: see Tools tab on `/connectors/cortex-xdr-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/cortex-xdr/cortex-xdr-api/cortex-xdr-apis/response-actions/isolate-endpoints.html

## Purpose

Isolate one or more endpoints in a single request. Request is limited to 1000 endpoints.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `endpoint_id_list` | `List[str]` | `None` | List of endpoint IDs. |

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

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/isolate/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/cortex-xdr-client`'s `isolate_endpoints` wrapper — see https://github.com/ebarti/cortex-xdr-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xdr_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_endpoints_isolate`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `isolate_endpoints`
