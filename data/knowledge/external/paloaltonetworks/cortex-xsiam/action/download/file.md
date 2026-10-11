# Download File

**HTTP**: `POST /public_api/v1/download/download_file/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_download_file`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

## Purpose

Downloads the file at the given URI, previously requested by get_file_retrieval_details function

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `file_api_value` | `str` | `—` | (no docstring) |

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

Contents of the file

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/download/download_file/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `download_file` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_download_file`
- Source mapping: `ebarti/cortex_xdr_client/api/download_api.py` → `download_file`
