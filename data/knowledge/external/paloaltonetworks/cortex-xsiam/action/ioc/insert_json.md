# Insert Json

**HTTP**: `POST /public_api/v1/indicators/insert_jsons/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_ioc_insert_json`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

## Purpose

Upload IOCs as JSON objects that you retrieved from external threat intelligence sources.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `indicators` | `List[IoC]` | `—` | List of IoC objects |
| `validate` | `Optional[bool]` | `True` | Whether to return an array of errors in the case of an unsuccessful update indicator API request. |

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

Returns an IoCResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/indicators/insert_jsons/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `insert_json` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_ioc_insert_json`
- Source mapping: `ebarti/cortex_xdr_client/api/ioc_api.py` → `insert_json`
