# Get Query Results Stream

**HTTP**: `POST /public_api/v1/xql/get_query_results_stream/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_xql_get_results_stream`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/xql-apis/get-xql-query-exported-data.html

## Purpose

Returns the results of an XQL Query.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `stream_id` | `str` | `—` | Integer representing the unique ID generate by the response to Get XQL Query Results API. |

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

Dictionary of results

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/xql/get_query_results_stream/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_query_results_stream` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_xql_get_results_stream`
- Source mapping: `ebarti/cortex_xdr_client/api/xql_api.py` → `get_query_results_stream`
